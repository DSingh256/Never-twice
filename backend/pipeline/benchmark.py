"""Benchmark generation from held-out incidents.

The eval set must be *derived*, never authored by hand: for every held-out
incident the LLM writes one risky PR (a diff introducing that incident's real
failure precursor) and one safe PR (a benign change to the same component).
Near-miss safe PRs - changes that superficially resemble a precursor but are
actually harmless - are added at a configured ratio so false positives are
measurable.

Ground truth comes from the case kind (risky=1, safe=0), NOT from the LLM:
the model that writes the diffs never labels them.

Output is a JSON file under config eval.benchmark.output_dir. It is a build
artefact: regenerating with the same seed and corpus reproduces it.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from backend.config import get_app_config
from backend.db.models import Incident
from backend.llm.client import LlmCallError, LlmClient

logger = logging.getLogger(__name__)


class BenchmarkCaseDraft(BaseModel):
    """What the LLM must fill in for one generated case."""

    model_config = {"extra": "ignore"}

    pr_title: str = Field(min_length=4, description="Realistic PR title")
    diff: str = Field(min_length=40, description="Unified diff of the proposed change")
    notes: str = Field(default="", description="One sentence on how the diff relates to the incident")

    @field_validator("diff", mode="before")
    @classmethod
    def _looks_like_diff(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("```"):  # tolerate fenced output
                v = v.strip("`").lstrip("diff\n").strip()
        return v


class BenchmarkCase(BaseModel):
    """A persisted eval case with ground truth."""

    case_id: str
    incident_id: int
    incident_title: str
    source_url: str
    kind: str  # risky | safe | near_miss_safe
    expected_label: int  # 1 = should alert, 0 = should not
    pr_title: str
    diff: str
    generation_notes: str = ""


RISKY_SYSTEM = """You write realistic pull-request diffs for a deployment-risk benchmark.

You will be given the factual record of a past production incident: the service,
the change that triggered it, the failure precursor, and the root cause.

Write a unified diff of a plausible code/config change that introduces EXACTLY
that failure precursor into that service. Rules:
- The diff must be small and realistic (terraform/yaml/env/code as appropriate).
- Ground every changed value in the incident record. Do not invent unrelated
  failures, and do not include any commentary about risk inside the diff.
- Keep comments in the diff plausible for a real PR (cost trimming, cleanup...).
- Output ONLY what the schema asks for."""


SAFE_SYSTEM = """You write realistic pull-request diffs for a deployment-risk benchmark.

You will be given the factual record of a past production incident: the service,
the change that triggered it, and the failure precursor.

Write a unified diff of a BENIGN change to the same component that does NOT
introduce that precursor and does not reduce safety margins. It should look like
normal engineering work (bumping a version, renaming, adding a comment,
increasing a limit). Rules:
- Same realism rules as any PR diff; small and plausible.
- It must be genuinely safe: someone with the incident record in mind should
  still approve it.
- Output ONLY what the schema asks for."""


NEAR_MISS_SYSTEM = """You write realistic pull-request diffs for a deployment-risk benchmark.

You will be given the factual record of a past production incident, including
its failure precursor signature.

Write a unified diff of a change that SUPERFICIALLY RESEMBLES the precursor
(touches the same keys/area, similar wording, similar shape) but is actually
SAFE on closer reading - e.g. a no-op rename, a comment, a value moved but
kept, a limit INCREASED where the incident had it decreased. Rules:
- The resemblance must be real (that is the point of this control group).
- The change must still be genuinely safe.
- Output ONLY what the schema asks for."""


def _incident_brief(incident: Incident) -> str:
    parts = [
        f"Incident title: {incident.title}",
        f"Organization: {incident.org or 'unknown'}",
        f"Service/component: {incident.service_or_component or 'unknown'}",
        f"Triggering change: {incident.trigger_change or 'not stated'}",
        f"Failure precursor signature: {incident.precursor_signature or 'not stated'}",
        f"Root cause: {incident.root_cause or 'not stated'}",
        f"Change category: {incident.change_category}",
    ]
    if incident.failed_fixes:
        parts.append("Failed fixes: " + "; ".join(incident.failed_fixes[:3]))
    return "\n".join(parts)


def generate_case(
    incident: Incident,
    kind: str,
    variant: int,
) -> BenchmarkCase | None:
    """Generate one benchmark case for an incident. Returns None on LLM failure."""
    client = LlmClient()
    brief = _incident_brief(incident)
    if kind == "risky":
        system, user = RISKY_SYSTEM, (
            f"{brief}\n\nWrite the risky PR diff that introduces this precursor."
        )
        expected = 1
    elif kind == "safe":
        system, user = SAFE_SYSTEM, (
            f"{brief}\n\nWrite the benign PR diff to the same component."
        )
        expected = 0
    elif kind == "near_miss_safe":
        system, user = NEAR_MISS_SYSTEM, (
            f"{brief}\n\nWrite the near-miss PR diff: resembles the precursor, is actually safe."
        )
        expected = 0
    else:
        raise ValueError(f"unknown case kind: {kind}")

    try:
        draft, meta = client.structured(
            task="benchmark_generation", system=system, user=user, schema=BenchmarkCaseDraft
        )
    except LlmCallError as exc:
        logger.warning("benchmark generation failed incident=%s kind=%s: %s", incident.id, kind, exc)
        return None

    diff = draft.diff.strip()
    if len(diff) < 40 or ("+" not in diff and "-" not in diff):
        logger.warning("generated diff implausible incident=%s kind=%s; skipping", incident.id, kind)
        return None

    return BenchmarkCase(
        case_id=f"i{incident.id}-{kind}" + (f"-{variant}" if variant else ""),
        incident_id=incident.id,
        incident_title=incident.title,
        source_url=incident.source_url,
        kind=kind,
        expected_label=expected,
        pr_title=draft.pr_title.strip(),
        diff=diff,
        generation_notes=draft.notes.strip(),
    )


def generate_benchmark(session: Session) -> dict:
    """Generate the full benchmark from held-out incidents and write it to disk.

    Returns a summary report. Idempotent per run: each invocation writes a fresh
    timestamped file plus a stable `benchmark.json` pointer.
    """
    cfg = get_app_config().eval
    bench_cfg = cfg.benchmark
    rng = random.Random(bench_cfg.seed)

    heldout = session.exec(
        select(Incident).where(Incident.split == "heldout").order_by(Incident.source_url)
    ).all()
    if not heldout:
        raise RuntimeError(
            "no held-out incidents found - run ingestion and split assignment first"
        )

    cases: list[BenchmarkCase] = []
    failures: list[dict] = []
    for incident in heldout:
        for kind, count in (
            ("risky", bench_cfg.cases_per_incident.risky),
            ("safe", bench_cfg.cases_per_incident.safe),
        ):
            for v in range(1, count + 1):
                case = generate_case(incident, kind, v if count > 1 else 0)
                if case is None:
                    failures.append({"incident_id": incident.id, "kind": kind})
                else:
                    cases.append(case)
        # Near-miss controls for a seeded subset of incidents.
        if rng.random() < bench_cfg.near_miss_safe_ratio:
            case = generate_case(incident, "near_miss_safe", 0)
            if case is None:
                failures.append({"incident_id": incident.id, "kind": "near_miss_safe"})
            else:
                cases.append(case)

    out_dir = Path(bench_cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": bench_cfg.seed,
        "heldout_incidents": len(heldout),
        "case_count": len(cases),
        "failures": failures,
        "cases": [c.model_dump() for c in cases],
    }
    stable = out_dir / "benchmark.json"
    stable.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    stamped = out_dir / f"benchmark-{stamp}.json"
    stamped.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "cases": len(cases),
        "heldout_incidents": len(heldout),
        "failures": len(failures),
        "path": str(stable),
        "risky": sum(1 for c in cases if c.expected_label == 1),
        "safe": sum(1 for c in cases if c.expected_label == 0),
    }


def load_benchmark(path: str | None = None) -> list[BenchmarkCase]:
    """Load cases from the benchmark file (config path by default)."""
    cfg = get_app_config().eval.benchmark
    file = Path(path or cfg.output_dir) / "benchmark.json"
    if path and not file.exists():
        file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"benchmark not found at {file}; run scripts/generate_benchmark.py")
    data = json.loads(file.read_text(encoding="utf-8"))
    return [BenchmarkCase(**c) for c in data["cases"]]
