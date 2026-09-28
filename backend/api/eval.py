"""Evaluation API (M6): run the A/B/C ablation and read results.

POST /api/eval/generate   - generate the benchmark from held-out incidents
POST /api/eval/run        - run the ablation (background task)
GET  /api/eval/runs       - list runs with computed metrics
GET  /api/eval/runs/{id}  - one run + per-item rows
GET  /api/eval/split-check - prove held-out incidents are not in the bank
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from backend.config import get_app_config
from backend.db.models import EvalItem, EvalRun, RetainedMemory
from backend.db.session import get_session
from backend.pipeline.benchmark import generate_benchmark
from backend.pipeline.ablation import run_ablation

eval_router = APIRouter(tags=["eval"])


@eval_router.post("/eval/generate")
async def post_generate(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Generate the benchmark from held-out incidents (LLM-backed, can take minutes)."""
    try:
        report = generate_benchmark(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, **report}


@eval_router.post("/eval/run")
async def post_run(
    background: BackgroundTasks,
    benchmark_path: str | None = None,
    label: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Kick off an ablation run in the background; poll /api/eval/runs for results."""
    run = EvalRun(status="running", label=label, benchmark_path=benchmark_path)
    session.add(run)
    session.commit()
    session.refresh(run)
    background.add_task(_run_in_background, run.id, benchmark_path, label)
    return {"ok": True, "run_id": run.id, "status": "running"}


def _run_in_background(run_id: int, benchmark_path: str | None, label: str | None) -> None:
    from backend.db.session import session_scope

    with session_scope() as session:
        try:
            run_ablation(session, benchmark_path=benchmark_path, label=label, _reuse_run_id=run_id)
        except Exception as exc:  # noqa: BLE001
            from backend.db.models import EvalRun

            run = session.get(EvalRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = f"{type(exc).__name__}: {exc}"[:1000]
                session.add(run)
                session.commit()


@eval_router.get("/eval/runs")
async def get_runs(limit: int = 20, session: Session = Depends(get_session)) -> dict[str, Any]:
    rows = session.exec(
        select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
    ).all()
    return {
        "runs": [
            {
                "id": str(r.id),
                "status": r.status,
                "label": r.label,
                "item_count": r.item_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "summary": r.metrics,
                "error": r.error,
            }
            for r in rows
        ]
    }


@eval_router.get("/eval/runs/{run_id}")
async def get_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        rid = int(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="run not found")
    run = session.get(EvalRun, rid)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    items = session.exec(
        select(EvalItem).where(EvalItem.run_id == rid).order_by(EvalItem.case_id)
    ).all()
    return {
        "id": str(run.id),
        "status": run.status,
        "label": run.label,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "config_snapshot": run.config_snapshot,
        "summary": run.metrics,
        "error": run.error,
        "items": [
            {
                "id": i.id,
                "case_id": i.case_id,
                "condition": i.condition,
                "expected_label": i.expected_label,
                "predicted_level": i.predicted_level,
                "predicted_positive": i.predicted_positive,
                "correct": i.correct if i.error is None else None,
                "confidence": i.confidence,
                "evidence_count": i.evidence_count,
                "latency_ms": i.latency_ms,
                "error": i.error,
            }
            for i in items
        ],
    }


@eval_router.get("/eval/split-check")
async def get_split_check(session: Session = Depends(get_session)) -> dict[str, Any]:
    """The split guarantee, checked live: no held-out incident may be in the bank."""
    from backend.db.models import Incident

    heldout_ids = {
        i.id for i in session.exec(select(Incident).where(Incident.split == "heldout")).all()
    }
    memory_ids = {
        i.id for i in session.exec(select(Incident).where(Incident.split == "memory")).all()
    }
    retained_incident_ids = {
        r.incident_id
        for r in session.exec(select(RetainedMemory).where(RetainedMemory.origin_kind == "incident")).all()
    }
    leaked = sorted(heldout_ids & retained_incident_ids)
    return {
        "heldout_count": len(heldout_ids),
        "memory_count": len(memory_ids),
        "retained_incident_count": len(retained_incident_ids),
        "heldout_leaked_into_bank": leaked,
        "ok": len(leaked) == 0,
    }
