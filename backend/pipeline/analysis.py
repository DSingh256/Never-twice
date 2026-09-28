"""Diff analysis pipeline.

Steps (each is persisted as an AnalysisStep and streamed via SSE):
  1. understand_diff   - LLM extracts structured change facts (no verdict yet)
  2. recall_memories   - Hindsight recall over the change facts
  3. recall_feedback   - Hindsight recall scoped to feedback memories
  4. reflect           - Hindsight reflect over evidence (+ feedback for level)
  5. verdict           - Pydantic RiskVerdict with COMPUTED confidence

The LLM never sees a step it cannot ground: reflect's response_schema forces it
to cite evidence, and confidence/evidence_count/supporting_memory_ids are set
in code afterwards.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

from sqlmodel import Session

from backend.config import get_app_config
from backend.db.models import Analysis, AnalysisStep
from backend.llm.client import LlmCallError, LlmClient
from backend.memory.hindsight_client import get_hindsight
from backend.pipeline.confidence import compute_confidence
from backend.schemas.pipeline import (
    ChangeFact,
    FeedbackInfluence,
    MatchedIncident,
    MemoryHit,
    RiskVerdict,
)

logger = logging.getLogger(__name__)


class ReflectOutput(RiskVerdict):
    """Schema handed to Hindsight reflect's response_schema.

    Confidence/evidence fields are excluded from what the LLM fills: the
    pipeline overwrites them with computed values after reflect returns.
    """

    model_config = {"json_schema_extra": {"x-llm-only": True}}


class StepEmitter:
    """Persists every step and notifies SSE subscribers."""

    def __init__(self, session: Session, analysis_id: int):
        self.session = session
        self.analysis_id = analysis_id
        self._seq = 0
        self._subscribers: list[Callable[[dict], None]] = []
        self.finished = False

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self._subscribers.append(callback)

    def emit(
        self,
        step: str,
        status: str,
        message: str = "",
        detail: dict | None = None,
        duration_ms: int | None = None,
    ) -> dict:
        self._seq += 1
        event = {
            "seq": self._seq,
            "analysis_id": self.analysis_id,
            "step": step,
            "status": status,
            "message": message,
            "detail": detail or {},
            "duration_ms": duration_ms,
        }
        row = AnalysisStep(
            analysis_id=self.analysis_id,
            seq=self._seq,
            step=step,
            status=status,
            message=message,
            detail=detail,
            duration_ms=duration_ms,
        )
        self.session.add(row)
        self.session.commit()
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception:  # noqa: BLE001
                logger.exception("step subscriber failed")
        return event

    def finish(self) -> None:
        self.finished = True


def _truncate_diff(diff: str) -> tuple[str, bool]:
    cfg = get_app_config().app.analysis
    raw = diff.encode("utf-8", errors="replace")
    if len(raw) <= cfg.max_diff_bytes:
        return diff, False
    return raw[: cfg.max_diff_bytes].decode("utf-8", errors="ignore"), True


# --------------------------------------------------------------------------- #
# Step 1: diff understanding
# --------------------------------------------------------------------------- #
DIFF_SYSTEM = """You analyse unified diffs and extract factual change descriptions.

Rules:
- Describe ONLY what the diff shows. No speculation about risk or consequences.
- change_category is exactly one of: config, deploy, migration, dependency,
  capacity, other.
- config_keys lists configuration keys or flags changed, ideally as
  "key: old -> new".
- value_changes entries look like {"key": "...", "old": "...", "new": "..."}.
"""


def understand_diff(diff: str, pr_title: str | None) -> ChangeFact:
    client = LlmClient()
    user = (
        f"PR title (optional context): {pr_title or 'n/a'}\n\n"
        f"Unified diff:\n```diff\n{diff}\n```"
    )
    facts, meta = client.structured(
        task="diff_understanding", system=DIFF_SYSTEM, user=user, schema=ChangeFact
    )
    logger.info("diff understood (model=%s): %s", meta.get("model"), facts.summary[:120])
    return facts


# --------------------------------------------------------------------------- #
# Steps 2-3: recall
# --------------------------------------------------------------------------- #
def _fact_query(facts: ChangeFact) -> str:
    parts = [facts.summary or ""]
    if facts.affected_component:
        parts.append(f"component: {facts.affected_component}")
    if facts.config_keys:
        parts.append("config keys: " + "; ".join(facts.config_keys[:8]))
    for vc in facts.value_changes[:5]:
        parts.append(f"{vc.get('key', '')}: {vc.get('old', '')} -> {vc.get('new', '')}")
    return " | ".join(p for p in parts if p)


def _hit_to_matched(hit: MemoryHit, incident_lookup: dict[str, int]) -> dict:
    return {
        "memory_id": hit.memory_id,
        "text": hit.text,
        "fact_type": hit.fact_type,
        "score": hit.score,
        "tags": hit.tags,
        "incident_id": incident_lookup.get(hit.document_id or ""),
    }


# --------------------------------------------------------------------------- #
# Step 4: reflect
# --------------------------------------------------------------------------- #
REFLECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "rationale": {"type": "string"},
        "matched_incidents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "incident_key": {"type": "string"},
                    "why_similar": {"type": "string"},
                    "what_failed_before": {"type": "string"},
                    "failed_fixes": {"type": "array", "items": {"type": "string"}},
                    "what_worked": {"type": ["string", "null"]},
                },
                "required": ["incident_key", "why_similar"],
            },
        },
        "suggested_checks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["level", "rationale"],
}


def _reflect_query(facts: ChangeFact, evidence: list[MemoryHit], feedback: list[MemoryHit]) -> str:
    q = [
        "A developer proposes this change:",
        facts.summary or "(unparsable diff)",
    ]
    if facts.config_keys:
        q.append("Changed configuration: " + "; ".join(facts.config_keys[:8]))
    if facts.affected_component:
        q.append(f"Affected component: {facts.affected_component}")
    q.append("")
    q.append("Historical memories retrieved for similar past changes:")
    for hit in evidence[: get_app_config().app.risk.max_evidence_items]:
        q.append(f"- [{hit.fact_type}] {hit.text[:300]} (score {hit.score:.2f})")
    if feedback:
        q.append("")
        q.append("Past engineer feedback on similar alerts:")
        for fb in feedback[:5]:
            q.append(f"- {fb.text[:200]}")
    q.append("")
    q.append(
        "Does this change resemble a historically dangerous pattern? Answer with "
        "level, rationale, matched incidents (by their memory text) and checks."
    )
    return "\n".join(q)


# --------------------------------------------------------------------------- #
# Verdict sanitisation - the LLM must never be able to crash the pipeline.
# --------------------------------------------------------------------------- #
_LEVEL_ALIASES = {
    "critical": "high", "severe": "high", "extreme": "high", "blocker": "high",
    "urgent": "high", "dangerous": "high",
    "moderate": "medium", "mid": "medium", "warning": "medium", "elevated": "medium",
    "minor": "low", "potential": "low", "possible": "low", "slight": "low",
    "informational": "none", "info": "none", "safe": "none", "ok": "none",
    "no risk": "none", "benign": "none", "unknown": "none",
}
_CANONICAL_LEVELS = ("high", "medium", "low", "none")


def _normalise_level(raw: Any) -> str:
    """Map whatever the model returned onto a canonical risk level.

    qwen2.5 and friends occasionally answer 'potentially high' or 'critical'
    despite the schema enum. Validation would crash the analysis; instead we
    coerce honestly (substring matching keeps 'potentially high' -> high) and
    fall back to 'none'. Never fabricates a level that was not implied.
    """
    if not isinstance(raw, str):
        return "none"
    v = raw.strip().lower()
    if v in _CANONICAL_LEVELS:
        return v
    # Canonical substring BEFORE aliases: 'potentially high' must resolve to
    # 'high', not trip the 'potential'->'low' alias.
    for canonical in _CANONICAL_LEVELS:
        if canonical in v:
            return canonical
    for alias, mapped in _LEVEL_ALIASES.items():
        if alias in v:
            return mapped
    return "none"


def _as_str_list(raw: Any, limit: int = 8) -> list[str]:
    """Coerce an LLM field into a clean list[str] (singletons, junk tolerated).

    None entries are dropped, not stringified - a null inside a list means
    'no value', it never means the four characters N-u-l-l.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw[:limit] if x is not None and str(x).strip()]


def _as_str(raw: Any) -> str:
    return raw if isinstance(raw, str) else ("" if raw is None else str(raw))


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
async def run_analysis(
    session: Session,
    analysis: Analysis,
    emit_to: Optional[Callable[[dict], None]] = None,
) -> Analysis:
    """Execute the full pipeline for a persisted Analysis row."""
    cfg = get_app_config()
    hindsight = get_hindsight()
    started = time.time()

    emitter = StepEmitter(session, analysis.id)
    if emit_to:
        emitter.subscribe(emit_to)

    try:
        diff, truncated = _truncate_diff(analysis.diff or "")
        analysis.diff_truncated = truncated

        # ---- Step 1: understand the diff -------------------------------- #
        t0 = time.time()
        emitter.emit("understand_diff", "started", "Extracting change facts from the diff")
        facts = understand_diff(diff, analysis.pr_title)
        analysis.change_facts = json.loads(facts.model_dump_json())
        emitter.emit(
            "understand_diff",
            "ok",
            facts.summary or "Change facts extracted",
            {"files": facts.files[:10], "category": facts.change_category},
            duration_ms=int((time.time() - t0) * 1000),
        )

        # ---- Step 2: recall memories ------------------------------------ #
        t0 = time.time()
        emitter.emit("recall_memories", "started", "Searching organizational memory")
        query = _fact_query(facts)
        hits: list[MemoryHit] = []
        if query.strip():
            min_score = cfg.app.risk.min_retrieval_score
            hits = [h for h in await hindsight.arecall(query, max_tokens=cfg.app.memory.recall_max_tokens,
                                                       budget=cfg.app.memory.recall_budget)
                    if h.score >= min_score]
        emitter.emit(
            "recall_memories",
            "ok" if hits else "ok",
            f"{len(hits)} relevant memories retrieved",
            {"query": query[:300], "top_scores": [round(h.score, 3) for h in hits[:5]]},
            duration_ms=int((time.time() - t0) * 1000),
        )

        # ---- Step 3: recall feedback ------------------------------------ #
        t0 = time.time()
        emitter.emit("recall_feedback", "started", "Checking past engineer feedback")
        feedback_hits: list[MemoryHit] = []
        if query.strip():
            feedback_hits = await hindsight.arecall(
                query,
                max_tokens=2048,
                budget="low",
                tags=[f"kind:feedback"],
                tags_match="all",
            )
        emitter.emit(
            "recall_feedback",
            "ok",
            f"{len(feedback_hits)} past feedback items",
            {"count": len(feedback_hits)},
            duration_ms=int((time.time() - t0) * 1000),
        )

        # ---- Step 4: reflect -------------------------------------------- #
        t0 = time.time()
        emitter.emit("reflect", "started", "Reasoning over historical evidence")
        evidence_text = _reflect_query(facts, hits, feedback_hits)
        reflect_result = await hindsight.areflect(
            query=evidence_text,
            context=f"Never Twice risk analysis for {analysis.repo or 'a service change'}",
            budget=cfg.app.memory.reflect_budget,
            max_tokens=cfg.app.memory.reflect_max_tokens,
            response_schema=REFLECT_SCHEMA,
        )
        structured = reflect_result.get("structured_output") or {}
        emitter.emit(
            "reflect",
            "ok",
            (reflect_result.get("text") or "")[:200] or "Reflect returned no text",
            {"based_on_count": len(reflect_result.get("based_on") or [])},
            duration_ms=int((time.time() - t0) * 1000),
        )

        # ---- Step 5: verdict -------------------------------------------- #
        t0 = time.time()
        # Resolve matched incidents back to real incident rows via document ids.
        incident_lookup: dict[str, int] = {}
        doc_ids = [h.document_id for h in hits if h.document_id]
        if doc_ids:
            from backend.db.models import Incident, RetainedMemory
            from sqlmodel import select

            rows = session.exec(
                select(RetainedMemory).where(RetainedMemory.document_id.in_(doc_ids))
            ).all()
            incident_lookup = {r.document_id: r.incident_id for r in rows if r.document_id}

        matched = []
        for m in (structured.get("matched_incidents") or [])[:6]:
            if not isinstance(m, dict):
                continue
            matched.append({
                "why_similar": _as_str(m.get("why_similar")),
                "what_failed_before": _as_str(m.get("what_failed_before")),
                "failed_fixes": _as_str_list(m.get("failed_fixes")),
                "what_worked": m.get("what_worked") if isinstance(m.get("what_worked"), str) else None,
                "memory_texts": [_as_str(m.get("incident_key"))],
                "incident_ids": sorted({
                    incident_lookup.get(h.document_id)
                    for h in hits
                    if h.document_id and (
                        m.get("incident_key", "").lower() in h.text.lower()
                        or h.text.lower() in m.get("incident_key", "").lower()
                    )
                } - {None}),
            })

        feedback_influences = [
            FeedbackInfluence(feedback_verdict="good_catch", note=fb.text[:200], memory_id=fb.memory_id)
            for fb in feedback_hits
            if "good" in fb.text.lower() or "valid" in fb.text.lower()
        ] + [
            FeedbackInfluence(feedback_verdict="false_positive", note=fb.text[:200], memory_id=fb.memory_id)
            for fb in feedback_hits
            if "false positive" in fb.text.lower() or "not an issue" in fb.text.lower()
        ]

        evidence_count = len(hits)
        supporting_ids = [h.memory_id for h in hits]
        confidence = compute_confidence(
            evidence_count=evidence_count,
            retrieval_scores=[h.score for h in hits],
            feedback_items=[{"verdict": fi.feedback_verdict} for fi in feedback_influences],
        )

        # Small-sample guard: a lone memory cannot justify an elevated verdict.
        # Level is normalised first - an off-enum LLM answer must not crash here.
        level = _normalise_level(structured.get("level"))
        if level in ("high", "medium") and evidence_count < cfg.app.risk.min_evidence_for_elevated:
            level = "low"
            structured["rationale"] = (
                f"[downgraded: only {evidence_count} supporting memory] " + _as_str(structured.get("rationale"))
            )

        rationale = _as_str(structured.get("rationale"))
        suggested_checks = _as_str_list(structured.get("suggested_checks"))

        verdict = RiskVerdict(
            level=level,
            rationale=rationale,
            matched_incidents=[MatchedIncident(**{
                "incident_id": None,  # resolved below from matched[i]['incident_ids']
                "source_url": None,
                "title": _as_str(m.get("incident_key"))[:120],
                "why_similar": m["why_similar"],
                "what_failed_before": m["what_failed_before"],
                "failed_fixes": m["failed_fixes"],
                "what_worked": m["what_worked"],
            }) for m in matched],
            suggested_checks=suggested_checks,
            learned_from_feedback=feedback_influences,
            evidence_count=evidence_count,
            supporting_memory_ids=supporting_ids,
            confidence=confidence,
        )

        analysis.verdict = json.loads(verdict.model_dump_json())
        analysis.confidence = confidence
        analysis.evidence_count = evidence_count
        emitter.emit(
            "verdict",
            "ok",
            f"Level: {verdict.level} (confidence {confidence:.2f}, evidence {evidence_count})",
            {"level": verdict.level, "confidence": confidence},
            duration_ms=int((time.time() - t0) * 1000),
        )

        analysis.status = "done"
        analysis.finished_at = None
        emitter.emit("done", "ok", "Analysis complete", {"status": "done"})
        emitter.finish()

    except Exception as exc:  # noqa: BLE001
        logger.exception("analysis %s failed", analysis.id)
        analysis.status = "failed"
        analysis.error = f"{type(exc).__name__}: {exc}"[:1000]
        emitter.emit("error", "failed", str(exc)[:300], {})
        emitter.finish()

    analysis.duration_ms = int((time.time() - started) * 1000)
    analysis.finished_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis
