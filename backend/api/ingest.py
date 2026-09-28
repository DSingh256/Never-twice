"""Ingestion API (M2): run ingestion, inspect sources, retry failures."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from backend.db.models import SourceFetch
from backend.db.session import get_session
from backend.pipeline.ingest import process_source

ingest_router = APIRouter(tags=["ingest"])


@ingest_router.post("/ingest/run")
async def start_ingest(
    limit: Optional[int] = None,
    retry_failed: bool = False,
) -> dict[str, Any]:
    """Run ingestion over the configured source selection (synchronous).

    Kept synchronous on purpose: the console shows live per-source results, and
    a bounded run (30 sources) completes in minutes, not hours.
    """
    from backend.pipeline.ingest import run_ingest

    summary = await run_ingest(limit=limit, retry_failed=retry_failed)
    return {"ok": True, "summary": summary}


@ingest_router.get("/ingest/sources")
async def list_sources(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Every configured source with its pipeline status - failures included."""
    rows = session.exec(select(SourceFetch).order_by(SourceFetch.id)).all()
    return {
        "sources": [
            {
                "id": r.id,
                "url": r.url,
                "org": r.org,
                "title_hint": r.title_hint,
                "status": r.status,
                "http_status": r.http_status,
                "clean_chars": r.clean_chars,
                "error": r.error,
                "extraction_error": r.extraction_error,
                "attempts": r.attempts,
                "incident_id": r.incident_id,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in rows
        ]
    }


@ingest_router.post("/ingest/retry/{source_id}")
async def retry_source(
    source_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Re-run the pipeline for one source, whatever its previous state."""
    row = session.get(SourceFetch, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"source {source_id} not found")
    row.status = "pending"
    row.error = None
    row.extraction_error = None
    session.add(row)
    session.commit()

    result = await process_source(session, row)
    return {"ok": True, "source": {"id": result.id, "url": result.url, "status": result.status}}
