"""The Tribunal API: live A/B/C cross-examination of one diff.

The demo question this answers in 60 seconds: what does organizational memory
actually change? The same diff is judged three ways - by the naked LLM (A), by
the LLM shown recalled memories (B), and by the full production pipeline with
recall, reflect and feedback (C). Verdicts stream in per witness.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.db.models import TribunalItem, TribunalRun
from backend.db.session import get_session
from backend.pipeline.ablation import run_tribunal_sync

tribunal_router = APIRouter(tags=["tribunal"])

_CONDITIONS = ("A", "B", "C")


class TribunalRequest(BaseModel):
    diff: str = Field(min_length=1)
    pr_title: str | None = None
    repo: str | None = None
    service: str | None = None


def _witness_payload(item: TribunalItem) -> dict[str, Any]:
    verdict = item.verdict or {}
    return {
        "condition": item.condition,
        "status": item.status,
        "level": verdict.get("level"),
        "rationale": verdict.get("rationale"),
        "suggested_checks": verdict.get("suggested_checks") or [],
        "matched_incidents": verdict.get("matched_incidents") or [],
        "learned_from_feedback": verdict.get("learned_from_feedback") or [],
        "confidence": verdict.get("confidence"),
        "evidence_count": item.evidence_count,
        "latency_ms": item.latency_ms,
        "error": item.error,
    }


def _run_payload(session: Session, run: TribunalRun) -> dict[str, Any]:
    items = session.exec(
        select(TribunalItem).where(TribunalItem.run_id == run.id).order_by(TribunalItem.condition)
    ).all()
    by_cond = {i.condition: _witness_payload(i) for i in items}
    # Seats exist from the moment the run does: if the worker has not committed
    # its pending rows yet, report them as pending rather than null holes.
    witnesses = [
        by_cond.get(c)
        or {"condition": c, "status": "pending", "evidence_count": 0}
        for c in _CONDITIONS
    ]
    ok = {c: by_cond[c] for c in _CONDITIONS if by_cond.get(c, {}).get("status") == "ok"}

    def _num(key: str, cond: str) -> float | None:
        v = ok.get(cond, {}).get(key)
        return v if isinstance(v, (int, float)) else None

    level_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    delta = None
    if {"A", "C"} <= ok.keys() and _num("confidence", "A") is not None and _num("confidence", "C") is not None:
        a_level, c_level = ok["A"].get("level"), ok["C"].get("level")
        delta = {
            "confidence_a": _num("confidence", "A"),
            "confidence_c": _num("confidence", "C"),
            "level_a": a_level,
            "level_c": c_level,
            "level_rank_shift": (
                level_rank.get(c_level or "none", 0) - level_rank.get(a_level or "none", 0)
            ),
        }

    return {
        "id": run.id,
        "status": run.status,
        "origin": run.origin,
        "pr_title": run.pr_title,
        "repo": run.repo,
        "service": run.service,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "duration_ms": run.duration_ms,
        "error": run.error,
        "witnesses": witnesses,
        "delta": delta,
    }


@tribunal_router.post("/tribunal")
async def create_tribunal(
    req: TribunalRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Accept a diff and start the three-witness cross-examination.

    Returns the run id immediately; verdicts land per witness in the DB and are
    read back by the poll endpoint, so the UI can reveal them as they arrive.
    """
    diff = req.diff.strip()
    if not diff:
        raise HTTPException(status_code=400, detail="provide 'diff'")

    run = TribunalRun(
        status="running",
        origin="ui",
        repo=req.repo,
        service=req.service,
        pr_title=req.pr_title,
        diff=diff,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    thread = threading.Thread(target=run_tribunal_sync, args=(run.id,), daemon=True)
    thread.start()

    return {"tribunal_id": run.id, "status": run.status, "poll": f"/api/tribunal/{run.id}"}


@tribunal_router.get("/tribunal/{tribunal_id}")
async def get_tribunal(
    tribunal_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    run = session.get(TribunalRun, tribunal_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"tribunal run {tribunal_id} not found")
    return _run_payload(session, run)


@tribunal_router.get("/tribunals")
async def list_tribunals(
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    rows = session.exec(
        select(TribunalRun).order_by(TribunalRun.created_at.desc()).limit(limit)
    ).all()
    return {
        "tribunals": [
            {
                "id": r.id,
                "status": r.status,
                "pr_title": r.pr_title,
                "service": r.service,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
