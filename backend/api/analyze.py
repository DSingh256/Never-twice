"""Analysis API: submit diffs, stream progress over SSE, list history."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.db.models import Analysis, AnalysisStep
from backend.db.session import get_session
from backend.pipeline.analysis import run_analysis

analyze_router = APIRouter(tags=["analyze"])


class AnalyzeRequest(BaseModel):
    diff: Optional[str] = None
    pr_url: Optional[str] = None
    pr_title: Optional[str] = None
    repo: Optional[str] = None
    service: Optional[str] = None

    model_config = {"json_schema_extra": {
        "example": {"diff": "diff --git a/config.yml b/config.yml ..."}
    }}


@analyze_router.post("/analyze")
async def create_analysis(
    req: AnalyzeRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Accept a diff (or a PR URL for the webhook path) and start analysis.

    Returns the analysis id immediately; progress streams via
    GET /api/analyze/{id}/stream. An empty diff with no fetchable PR URL is a
    400, not a silent run.
    """
    diff = (req.diff or "").strip()
    if not diff and not req.pr_url:
        raise HTTPException(status_code=400, detail="provide 'diff' or 'pr_url'")

    analysis = Analysis(
        status="running",
        origin="ui",
        repo=req.repo,
        service=req.service,
        pr_url=req.pr_url,
        pr_title=req.pr_title,
        diff=diff,
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)

    # Run in the background so the client can connect to SSE immediately.
    asyncio.get_running_loop().create_task(_run_and_forget(analysis.id))
    return {"analysis_id": analysis.id, "status": analysis.status, "stream": f"/api/analyze/{analysis.id}/stream"}


async def _run_and_forget(analysis_id: int) -> None:
    """Execute the analysis on its own DB session (request session is closed)."""
    from backend.db.session import session_scope

    with session_scope() as session:
        analysis = session.get(Analysis, analysis_id)
        if analysis is None:
            return
        await run_analysis(session, analysis)


@analyze_router.get("/analyze/{analysis_id}/stream")
async def stream_analysis(analysis_id: int, session: Session = Depends(get_session)):
    """SSE stream of analysis steps, then the final verdict event."""
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail=f"analysis {analysis_id} not found")

    async def event_stream():
        last_seq = 0
        # Replay persisted steps (covers clients connecting mid-run).
        while True:
            steps = session.exec(
                select(AnalysisStep)
                .where(AnalysisStep.analysis_id == analysis_id)
                .where(AnalysisStep.seq > last_seq)
                .order_by(AnalysisStep.seq)
            ).all()
            for step in steps:
                last_seq = step.seq
                payload = {
                    "seq": step.seq,
                    "step": step.step,
                    "status": step.status,
                    "message": step.message,
                    "detail": step.detail or {},
                    "duration_ms": step.duration_ms,
                }
                yield f"event: step\ndata: {json.dumps(payload, default=str)}\n\n"

            analysis = session.get(Analysis, analysis_id)
            if analysis and analysis.status != "running":
                final = {
                    "analysis_id": analysis.id,
                    "status": analysis.status,
                    "verdict": analysis.verdict,
                    "confidence": analysis.confidence,
                    "evidence_count": analysis.evidence_count,
                    "error": analysis.error,
                    "duration_ms": analysis.duration_ms,
                }
                yield f"event: verdict\ndata: {json.dumps(final, default=str)}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@analyze_router.get("/analyses")
async def list_analyses(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Recent analyses, newest first."""
    rows = session.exec(
        select(Analysis).order_by(Analysis.created_at.desc()).limit(limit)
    ).all()
    return {
        "analyses": [
            {
                "id": r.id,
                "status": r.status,
                "pr_title": r.pr_title,
                "repo": r.repo,
                "service": r.service,
                "level": (r.verdict or {}).get("level") if r.verdict else None,
                "confidence": r.confidence,
                "evidence_count": r.evidence_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "duration_ms": r.duration_ms,
            }
            for r in rows
        ]
    }


@analyze_router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    """One analysis with its full verdict and step log."""
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail=f"analysis {analysis_id} not found")
    steps = session.exec(
        select(AnalysisStep).where(AnalysisStep.analysis_id == analysis_id).order_by(AnalysisStep.seq)
    ).all()
    return {
        "id": analysis.id,
        "status": analysis.status,
        "repo": analysis.repo,
        "service": analysis.service,
        "pr_url": analysis.pr_url,
        "pr_title": analysis.pr_title,
        "diff_truncated": analysis.diff_truncated,
        "change_facts": analysis.change_facts,
        "verdict": analysis.verdict,
        "confidence": analysis.confidence,
        "evidence_count": analysis.evidence_count,
        "error": analysis.error,
        "duration_ms": analysis.duration_ms,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "steps": [
            {
                "seq": s.seq,
                "step": s.step,
                "status": s.status,
                "message": s.message,
                "detail": s.detail,
                "duration_ms": s.duration_ms,
            }
            for s in steps
        ],
    }
