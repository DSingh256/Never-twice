"""A/B/C ablation runner (M6).

Condition A: verdict from the diff alone (no memory)      - "is this just RAG?"
Condition B: verdict from the diff + recalled memories    - memory as context
Condition C: the full production pipeline (recall+reflect+feedback)

Every condition runs the SAME benchmark cases; per-item results land in
`eval_items`, and the aggregate metrics (accuracy, precision, recall, false
positive rate) are COMPUTED from those rows - never asserted. Feedback for
condition C is simulated from ground-truth labels on an earlier warm-up slice
only, never on the item being scored, and the warm-up retainments are tagged
so they cannot leak into the production memory bank's semantics.

If Hindsight is unreachable, A still runs and B/C fail honestly per item
(errors recorded); the run itself completes with whatever was measurable.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlmodel import Session, select

from backend.config import get_app_config
from backend.db.models import Analysis, EvalItem, EvalRun
from backend.llm.client import LlmClient
from backend.memory.hindsight_client import get_hindsight
from backend.pipeline.analysis import (
    REFLECT_SCHEMA,
    _as_str,
    _as_str_list,
    _fact_query,
    _normalise_level,
    understand_diff,
)
from backend.pipeline.benchmark import BenchmarkCase, load_benchmark
from backend.pipeline.confidence import compute_confidence
from backend.schemas.pipeline import MemoryHit

logger = logging.getLogger(__name__)

# Verdict task for conditions A (no memory) and B (memory as plain context).
A_SYSTEM = """You are a deployment risk reviewer. Given a proposed change, decide how
risky it is to merge.

Respond with JSON: {"level": "high"|"medium"|"low"|"none", "rationale": "...",
"suggested_checks": ["..."]}. Judge only from the change itself."""

B_SYSTEM = """You are a deployment risk reviewer. Given a proposed change AND
historical memories of similar past changes in this organization, decide how
risky it is to merge.

Respond with JSON: {"level": "high"|"medium"|"low"|"none", "rationale": "...",
"suggested_checks": ["..."]}. Ground the rationale in the memories when they
are relevant; say so when they are not."""


def _verdict_from_json(raw: dict[str, Any], *, evidence_count: int, scores: list[float],
                       feedback_items: list[dict], min_evidence_elevated: int) -> dict[str, Any]:
    """Normalise an LLM verdict dict into the canonical verdict shape.

    Confidence is computed by the pipeline, never taken from the model.
    """
    level = _normalise_level(raw.get("level"))
    if level in ("high", "medium") and evidence_count < min_evidence_elevated:
        level = "low"
        raw["rationale"] = f"[downgraded: only {evidence_count} supporting memory] " + _as_str(raw.get("rationale"))
    confidence = compute_confidence(
        evidence_count=evidence_count,
        retrieval_scores=scores,
        feedback_items=feedback_items,
    )
    return {
        "level": level,
        "rationale": _as_str(raw.get("rationale")),
        "suggested_checks": _as_str_list(raw.get("suggested_checks")),
        "matched_incidents": [],
        "learned_from_feedback": [],
        "evidence_count": evidence_count,
        "supporting_memory_ids": [],
        "confidence": confidence,
    }


def _facts_schema():
    from backend.schemas.pipeline import ChangeFact

    return ChangeFact


def _run_condition_a(case: BenchmarkCase, client: LlmClient) -> dict[str, Any]:
    """LLM only: the raw diff and nothing else. The 'is this just RAG?' control."""
    raw_text = client.plain(
        task="verdict_no_memory",
        system=A_SYSTEM,
        user=f"PR title: {case.pr_title}\n\nUnified diff:\n```diff\n{case.diff}\n```\n\n"
             "Return ONLY a JSON object with keys level, rationale, suggested_checks.",
    )
    raw = json.loads(_extract_json_object(raw_text), strict=False)
    return _verdict_from_json(
        raw, evidence_count=0, scores=[], feedback_items=[],
        min_evidence_elevated=get_app_config().app.risk.min_evidence_for_elevated,
    )


def _extract_json_object(text: str) -> str:
    """Pull the outermost {...} out of a model reply (verbatim rule from LlmClient)."""
    text = text.strip()
    if text.startswith("```"):
        end = text.find("```", 3)
        if end != -1:
            text = text[3:end].strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _run_condition_b(case: BenchmarkCase, client: LlmClient, hindsight: Any) -> dict[str, Any]:
    facts, _ = client.structured(
        task="diff_understanding",
        system="Extract factual change description from a unified diff. No risk judgement.",
        user=f"Unified diff:\n```diff\n{case.diff}\n```",
        schema=_facts_schema(),
    )  # recall needs a queryable summary; the verdict itself is plain JSON
    query = _fact_query(facts)
    cfg = get_app_config()
    hits: list[MemoryHit] = []
    if query.strip():
        hits = [
            h
            for h in hindsight.recall(query, max_tokens=cfg.app.memory.recall_max_tokens,
                                      budget=cfg.app.memory.recall_budget)
            if h.score >= cfg.app.risk.min_retrieval_score
        ]
    memory_block = "\n".join(f"- [{h.fact_type}] {h.text[:280]}" for h in hits[:10]) or "(no relevant memories)"
    raw_text = client.plain(
        task="verdict",
        system=B_SYSTEM,
        user=f"PR title: {case.pr_title}\n\nChange summary: {facts.summary}\n\n"
             f"Historical memories:\n{memory_block}\n\n"
             "Return ONLY a JSON object with keys level, rationale, suggested_checks.",
    )
    raw = json.loads(_extract_json_object(raw_text), strict=False)
    return _verdict_from_json(
        raw,
        evidence_count=len(hits),
        scores=[h.score for h in hits],
        feedback_items=[],
        min_evidence_elevated=cfg.app.risk.min_evidence_for_elevated,
    )


def _run_condition_c(case: BenchmarkCase, session: Session) -> dict[str, Any]:
    """Full production pipeline: persist an Analysis row and run run_analysis.

    run_analysis is async (Hindsight a* calls); in the eval worker thread there
    is no running loop, so asyncio.run is the correct bridge.
    """
    import asyncio

    import backend.memory.hindsight_client as hc
    from backend.pipeline.analysis import run_analysis

    async def _once() -> Any:
        # The singleton binds its async client to the running loop; each
        # asyncio.run creates a new loop, so use a fresh client per call and
        # close it cleanly instead of leaking loop-bound sessions.
        hc._hindsight_singleton = None
        h = hc.get_hindsight()
        try:
            analysis = Analysis(
                status="running",
                origin="api",
                pr_title=f"[eval:{case.case_id}] {case.pr_title}",
                diff=case.diff,
            )
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
            return await run_analysis(session, analysis, emit_to=None)
        finally:
            await h.aclose()

    result = asyncio.run(_once())
    if result.status != "done" or not result.verdict:
        raise RuntimeError(result.error or "condition C pipeline returned no verdict")
    return dict(result.verdict)


# --------------------------------------------------------------------------- #
# Warm-up feedback simulation for condition C
# --------------------------------------------------------------------------- #
def warmup_feedback(session: Session, cases: list[BenchmarkCase], hindsight: Any) -> set[int]:
    """Retain ground-truth-derived feedback for the warm-up slice of incidents.

    The warm-up slice is chosen PER INCIDENT (first `feedback_warmup_fraction`
    of incidents in deterministic order), and warm-up incidents are excluded
    from scoring in every condition. Slicing by case would leak: feedback for
    `i2-risky` recalls when scoring sibling cases `i2-safe` / `i2-near-miss`
    of the same incident, grading them with their own ground truth.

    Returns the set of warm-up incident ids.
    """
    frac = get_app_config().eval.scoring.feedback_warmup_fraction
    by_incident: dict[int, list[BenchmarkCase]] = {}
    for case in cases:
        by_incident.setdefault(case.incident_id, []).append(case)
    ordered = sorted(by_incident.keys())
    warmup_ids = set(ordered[: int(len(ordered) * frac)])

    retained = 0
    for case in cases:
        if case.incident_id not in warmup_ids:
            continue
        verdict = "good_catch" if case.expected_label == 1 else "false_positive"
        note = (
            f"Confirmed alert for a change like: {case.pr_title}. This pattern caused a real incident before."
            if verdict == "good_catch"
            else f"Marked as false positive for a change like: {case.pr_title}. Reviewed; the change is safe."
        )
        try:
            hindsight.retain_memory(
                content=f"Engineer feedback on a Never Twice risk verdict: '{verdict}'. {note}",
                context="Eval harness simulated engineer feedback (warm-up incidents only)",
                memory_kind="feedback",
                tags=[f"eval_case:{case.case_id}", "eval:warmup"],
                metadata={"case_id": case.case_id, "feedback_verdict": verdict},
                document_id=f"feedback-eval-{case.case_id}",
            )
            retained += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("warm-up feedback retain failed case=%s: %s", case.case_id, exc)
    logger.info("warm-up: %d feedback memories for incidents %s", retained, sorted(warmup_ids))
    return warmup_ids


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
LEVELS = ["none", "low", "medium", "high"]


def _is_positive(level: str) -> bool:
    threshold = get_app_config().eval.scoring.positive_at_or_above
    return LEVELS.index(level) >= LEVELS.index(threshold)


def _prf(tp: int, fp: int, fn: int, tn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    accuracy = (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
    }


def run_ablation(session: Session, benchmark_path: str | None = None,
                 label: str | None = None,
                 _reuse_run_id: int | None = None) -> EvalRun:
    """Run every condition over every case; persist items + computed metrics.

    `_reuse_run_id` continues a run row created elsewhere (the API pre-creates
    it so the caller gets an id immediately).
    """
    cfg = get_app_config()
    conditions = cfg.eval.conditions
    cases = load_benchmark(benchmark_path)
    if not cases:
        raise RuntimeError("benchmark has no cases; generate it first")

    client = LlmClient()
    hindsight = get_hindsight()

    if _reuse_run_id is not None:
        run = session.get(EvalRun, _reuse_run_id)
        if run is None:
            raise RuntimeError(f"eval run {_reuse_run_id} not found")
    else:
        run = EvalRun(
            status="running",
            label=label,
            benchmark_path=benchmark_path,
            config_snapshot={
                "conditions": {k: v.model_dump() for k, v in conditions.items()},
                "scoring": cfg.eval.scoring.model_dump(),
                "case_count": len(cases),
            },
            item_count=0,
        )
    session.add(run)
    session.commit()
    session.refresh(run)

    hindsight_ok = hindsight.health().get("ok", False)
    warmup_incident_ids: set[int] = set()
    if hindsight_ok:
        try:
            warmup_incident_ids = warmup_feedback(session, cases, hindsight)
        except Exception as exc:  # noqa: BLE001
            logger.warning("warm-up feedback failed: %s", exc)

    # Warm-up incidents are held out of scoring in EVERY condition, so the
    # A/B/C columns always compare the identical case set.
    scored_cases = [c for c in cases if c.incident_id not in warmup_incident_ids]

    items_done = 0
    try:
        for case in scored_cases:
            for cond_key in ("A", "B", "C"):
                cond = conditions.get(cond_key)
                if cond is None:
                    continue
                existing = session.exec(
                    select(EvalItem).where(EvalItem.run_id == run.id)
                    .where(EvalItem.case_id == case.case_id)
                    .where(EvalItem.condition == cond_key)
                ).first()
                if existing is not None:
                    continue  # idempotent per (run, case, condition)

                t0 = time.time()
                item = EvalItem(
                    run_id=run.id, case_id=case.case_id,
                    incident_id=case.incident_id, expected_label=case.expected_label,
                    condition=cond_key,
                )
                try:
                    if cond_key == "A":
                        verdict = _run_condition_a(case, client)
                    elif cond_key == "B":
                        if not hindsight_ok:
                            raise RuntimeError("hindsight unavailable for condition B")
                        verdict = _run_condition_b(case, client, hindsight)
                    else:
                        if not hindsight_ok:
                            raise RuntimeError("hindsight unavailable for condition C")
                        verdict = _run_condition_c(case, session)

                    item.predicted_level = verdict["level"]
                    item.predicted_positive = _is_positive(verdict["level"])
                    item.correct = item.predicted_positive == (case.expected_label == 1)
                    item.confidence = verdict.get("confidence")
                    item.evidence_count = verdict.get("evidence_count", 0)
                    item.supporting_memory_ids = verdict.get("supporting_memory_ids", [])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("eval item failed run=%s case=%s cond=%s: %s",
                                   run.id, case.case_id, cond_key, exc)
                    item.error = f"{type(exc).__name__}: {exc}"[:500]

                item.latency_ms = int((time.time() - t0) * 1000)
                session.add(item)
                session.commit()
                items_done += 1

        metrics = _compute_metrics(session, run.id, [c.case_id for c in scored_cases])
        run.metrics = metrics
        run.status = "done"
    except Exception as exc:  # noqa: BLE001
        logger.exception("eval run %s failed", run.id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:1000]

    run.item_count = items_done
    from datetime import datetime, timezone

    run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _compute_metrics(session: Session, run_id: int, case_ids: list[str]) -> dict[str, Any]:
    """Aggregate metrics COMPUTED from eval_items rows. Never asserted."""
    rows = session.exec(select(EvalItem).where(EvalItem.run_id == run_id)).all()
    out: dict[str, Any] = {"conditions": {}}
    for cond in ("A", "B", "C"):
        cond_rows = [r for r in rows if r.condition == cond and r.error is None]
        tp = sum(1 for r in cond_rows if r.predicted_positive and r.expected_label == 1)
        fp = sum(1 for r in cond_rows if r.predicted_positive and r.expected_label == 0)
        fn = sum(1 for r in cond_rows if not r.predicted_positive and r.expected_label == 1)
        tn = sum(1 for r in cond_rows if not r.predicted_positive and r.expected_label == 0)
        scored = tp + fp + fn + tn
        confs = [r.confidence for r in cond_rows if r.confidence is not None]
        out["conditions"][cond] = {
            "scored": scored,
            "errors": sum(1 for r in rows if r.condition == cond and r.error is not None),
            **(_prf(tp, fp, fn, tn)),
            "mean_confidence": round(sum(confs) / len(confs), 4) if confs else None,
            "mean_latency_ms": (
                round(sum(r.latency_ms or 0 for r in cond_rows) / len(cond_rows))
                if cond_rows else None
            ),
        }
    out["total_items"] = len(rows)
    out["benchmark_cases"] = len(case_ids)
    return out


# --------------------------------------------------------------------------- #
# The Tribunal: live A/B/C cross-examination of ONE submitted diff
# --------------------------------------------------------------------------- #
def run_tribunal_sync(run_id: int) -> None:
    """Run all three witnesses for a TribunalRun, persisting progress live.

    Designed to execute in a worker thread off the request path (the API
    returns the run id immediately; the poll endpoint streams each witness as
    it lands). Each witness commits its own row, so a slow reflect in witness
    C never hides witness A's verdict. A failing witness records its error and
    the others still testify.

    Witness C runs the production pipeline via asyncio.run (same bridge as
    _run_condition_c). That creates a fresh loop-bound Hindsight client, so the
    process-wide singleton is reset afterwards - the main event loop recreates
    its own client lazily on next use.
    """
    import asyncio

    import backend.memory.hindsight_client as hc
    from backend.db.models import TribunalItem, TribunalRun
    from backend.db.session import session_scope
    from backend.pipeline.analysis import run_analysis
    from backend.pipeline.benchmark import BenchmarkCase

    t0 = time.time()
    with session_scope() as session:
        run = session.get(TribunalRun, run_id)
        if run is None:
            return
        diff = run.diff
        pr_title = run.pr_title or "(untitled change)"
        service = run.service

        # Witness rows exist from the start so the UI can show pending seats.
        rows: dict[str, TribunalItem] = {
            cond: TribunalItem(run_id=run.id, condition=cond, status="pending")
            for cond in ("A", "B", "C")
        }
        for row in rows.values():
            session.add(row)
        session.commit()

        def _set(cond: str, **fields: Any) -> None:
            for k, v in fields.items():
                setattr(rows[cond], k, v)
            session.add(rows[cond])
            session.commit()

        def _case() -> BenchmarkCase:
            return BenchmarkCase(
                case_id=f"tribunal-{run.id}", incident_id=0, incident_title="",
                source_url="", kind="tribunal", expected_label=0,
                pr_title=pr_title, diff=diff,
            )

        client = LlmClient()
        hindsight = get_hindsight()
        hindsight_ok = hindsight.health().get("ok", False)
        cfg = get_app_config()

        failures = 0

        # --- Witness A: the naked LLM. No memory, no context. -------------
        _set("A", status="running")
        wa = time.time()
        try:
            verdict = _run_condition_a(_case(), client)
            _set("A", status="ok", verdict=verdict, evidence_count=0,
                 latency_ms=int((time.time() - wa) * 1000))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            _set("A", status="failed", error=f"{type(exc).__name__}: {exc}"[:500],
                 latency_ms=int((time.time() - wa) * 1000))

        # --- Witness B: the LLM shown recalled memories as plain context --
        _set("B", status="running")
        wb = time.time()
        try:
            if not hindsight_ok:
                raise RuntimeError("memory bank unreachable")
            verdict = _run_condition_b(_case(), client, hindsight)
            _set("B", status="ok", verdict=verdict,
                 evidence_count=int(verdict.get("evidence_count", 0)),
                 latency_ms=int((time.time() - wb) * 1000))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            _set("B", status="failed", error=f"{type(exc).__name__}: {exc}"[:500],
                 latency_ms=int((time.time() - wb) * 1000))

        # --- Witness C: the full production pipeline -----------------------
        _set("C", status="running")
        wc = time.time()
        try:
            if not hindsight_ok:
                raise RuntimeError("memory bank unreachable")

            async def _once() -> Any:
                hc._hindsight_singleton = None
                h = hc.get_hindsight()
                try:
                    analysis = Analysis(
                        status="running", origin="api", service=service,
                        pr_title=f"[tribunal:{run.id}] {pr_title}", diff=diff,
                    )
                    session.add(analysis)
                    session.commit()
                    session.refresh(analysis)
                    return await run_analysis(session, analysis, emit_to=None)
                finally:
                    await h.aclose()

            def _invoke() -> Any:
                return asyncio.run(_once())

            try:
                result = _invoke()
            except Exception as inner:  # noqa: BLE001
                # Hosted LLM providers advertise a quota-reset timestamp on 429s
                # ("... retry at 2026-...+00:00"). A live demo should ride out a
                # short window once instead of collapsing the witness.
                import re

                from datetime import datetime, timezone as _tz

                match = re.search(r"retry at (\S+)", str(inner))
                wait = None
                if match:
                    try:
                        retry_at = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
                        wait = (retry_at - datetime.now(_tz.utc)).total_seconds()
                    except ValueError:
                        wait = None
                if wait is not None and 0 < wait <= 120:
                    logger.warning("tribunal witness C: quota window %.0fs; waiting once", wait)
                    time.sleep(wait + 2)
                    result = _invoke()
                else:
                    raise
            if result.status != "done" or not result.verdict:
                raise RuntimeError(result.error or "production pipeline returned no verdict")
            _set("C", status="ok", verdict=dict(result.verdict),
                 evidence_count=int(result.evidence_count or 0),
                 latency_ms=int((time.time() - wc) * 1000))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            _set("C", status="failed", error=f"{type(exc).__name__}: {exc}"[:500],
                 latency_ms=int((time.time() - wc) * 1000))
        finally:
            # Witness C's private async client was loop-bound; drop the global
            # so the server's own loop rebuilds a healthy client next call.
            hc._hindsight_singleton = None

        run.status = "failed" if failures == 3 else "done"
        run.duration_ms = int((time.time() - t0) * 1000)
        from datetime import datetime, timezone

        run.finished_at = datetime.now(timezone.utc)
        session.add(run)
        session.commit()
