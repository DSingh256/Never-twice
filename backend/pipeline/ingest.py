"""Ingestion orchestrator: sources -> fetch -> extract -> split -> retain.

Every source is recorded with its outcome; failures are data, not exceptions -
the Ingest Console shows them with a retry button.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from backend.config import get_app_config
from backend.db.models import Incident, RetainedMemory, SourceFetch
from backend.db.session import session_scope
from backend.llm.client import LlmCallError
from backend.memory.hindsight_client import HindsightUnavailableError, get_hindsight
from backend.pipeline.extractor import extract_incident
from backend.pipeline.fetcher import FetchError, fetch_article
from backend.pipeline.retain import aretain_incident
from backend.pipeline.split import assign_splits

logger = logging.getLogger(__name__)


class IngestSummary(dict):
    """Result payload for the API; plain JSON-serialisable dict."""


def _upsert_source(session: Session, url: str, org: str, title_hint: str) -> SourceFetch:
    existing = session.exec(select(SourceFetch).where(SourceFetch.url == url)).first()
    if existing:
        return existing
    row = SourceFetch(url=url, org=org, title_hint=title_hint, status="pending")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


async def process_source(session: Session, source: SourceFetch) -> SourceFetch:
    """Run the full pipeline for one source. Never raises; status records why."""
    source.attempts += 1
    source.updated_at = datetime.now(timezone.utc)

    # 1. Fetch + clean.
    try:
        article = fetch_article(source.url)
    except FetchError as exc:
        source.status = "failed"
        source.error = str(exc)[:1000]
        session.add(source)
        session.commit()
        logger.warning("fetch failed %s: %s", source.url, exc)
        return source

    source.http_status = article.http_status
    source.content_hash = article.content_hash
    source.clean_chars = article.clean_chars
    source.fetched_at = datetime.now(timezone.utc)

    # 2. Extract (LLM) with validation.
    extraction_model: str | None = None
    try:
        extraction, meta = extract_incident(article.text, source.url, source.org)
        extraction_model = meta.get("model")
    except LlmCallError as exc:
        source.status = "failed"
        source.error = source.error or None
        source.extraction_error = str(exc)[:1000]
        session.add(source)
        session.commit()
        logger.warning("extraction failed %s: %s", source.url, exc)
        return source

    # 3. Guard against invention: a valid extraction still needs a root cause.
    if not extraction.root_cause:
        source.status = "rejected"
        source.extraction_error = "extraction had no root cause; article likely not a real postmortem"
        session.add(source)
        session.commit()
        return source

    # 4. Persist the incident.
    incident = session.exec(select(Incident).where(Incident.source_url == source.url)).first()
    if incident is None:
        incident = Incident(source_url=source.url)
    incident.org = source.org
    incident.title = extraction.title
    incident.service_or_component = extraction.service_or_component or ""
    incident.severity = extraction.severity
    incident.symptoms = extraction.symptoms
    incident.trigger_change = extraction.trigger_change
    incident.root_cause = extraction.root_cause
    incident.failed_fixes = extraction.failed_fixes
    incident.successful_fix = extraction.successful_fix
    incident.preventive_actions = extraction.preventive_actions
    incident.change_category = extraction.change_category
    incident.precursor_signature = extraction.precursor_signature
    incident.extraction_confidence = extraction.extraction_confidence
    incident.extraction_model = extraction_model
    session.add(incident)
    session.commit()
    session.refresh(incident)

    # 5. Retain into Hindsight (memory-split applied first below).
    try:
        counts = assign_splits(session)
        logger.info("split counts after ingest: %s", counts)
        if incident.split == "memory":
            await aretain_incident(session, incident)
            source.status = "extracted"
        else:
            # Held-out: recorded, never retained.
            source.status = "extracted"
            logger.info("incident %s is held-out; not retained", incident.id)
    except Exception as exc:  # noqa: BLE001
        source.status = "fetched"
        source.extraction_error = f"retain failed: {exc}"[:1000]
        session.add(source)
        session.commit()
        logger.error("retain failed for %s: %s", source.url, exc)
        return source

    source.incident_id = incident.id
    source.error = None
    source.extraction_error = None
    session.add(source)
    session.commit()
    return source


async def aensure_bank_safe() -> None:
    """Ensure the bank exists from an async context."""
    await get_hindsight().aensure_bank()


async def run_ingest(limit: int | None = None, retry_failed: bool = False) -> IngestSummary:
    """Run ingestion over the configured source selection (async; FastAPI-safe)."""
    cfg = get_app_config()
    sources_cfg = cfg.sources.select()
    await get_hindsight().aensure_bank()

    with session_scope() as session:
        rows: list[SourceFetch] = []
        for src in sources_cfg:
            rows.append(_upsert_source(session, src.url, src.org, src.title_hint))

        if retry_failed:
            stale = session.exec(
                select(SourceFetch).where(SourceFetch.status.in_(["failed", "rejected"]))
            ).all()
            for row in stale:
                row.status = "pending"
                row.error = None
                row.extraction_error = None
                session.add(row)
            session.commit()
            known = {r.url for r in rows}
            rows.extend(r for r in stale if r.url not in known)

        # Idempotency: already-extracted sources are skipped on re-runs.
        todo = [r for r in rows if r.status in ("pending", "failed", "rejected", "fetched")]
        if limit is not None:
            todo = todo[:limit]

        processed = 0
        for row in todo:
            result = await process_source(session, row)
            processed += 1
            logger.info("ingest [%d/%d] %s -> %s", processed, len(todo), result.url, result.status)

        final = session.exec(select(SourceFetch)).all()
        summary = IngestSummary(
            selected_sources=len(sources_cfg),
            attempted=len(todo),
            processed=processed,
            by_status={},
            incidents_total=len(session.exec(select(Incident)).all()),
        )
        for row in final:
            summary["by_status"][row.status] = summary["by_status"].get(row.status, 0) + 1
        return summary
