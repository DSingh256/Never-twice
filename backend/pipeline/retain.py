"""Retain incidents into Hindsight as individually meaningful memory units.

One memory per event (not one blob per article): incident summary, each failed
fix, the successful fix, the precursor signature. Tags make scope explicit:
`bank:nevertwice`, `kind:<unit>`, `incident:<id>`, `category:<...>`,
`service:<...>`, `source:<url-hash>` - so recall can slice by any of them.

Only `split == 'memory'` incidents may ever reach this module; the caller
(`run_ingest`) enforces it and a test asserts it stays true.
"""

from __future__ import annotations

import hashlib
import logging

from backend.config import get_app_config
from backend.db.models import Incident, RetainedMemory
from backend.memory.hindsight_client import get_hindsight
from sqlmodel import Session

logger = logging.getLogger(__name__)


def incident_tags(incident: Incident) -> list[str]:
    """The canonical tag set for an incident's memories."""
    url_hash = hashlib.sha1(incident.source_url.encode()).hexdigest()[:10]
    tags = [
        f"incident:{incident.id}",
        f"category:{incident.change_category}",
        f"source:{url_hash}",
    ]
    if incident.service_or_component:
        # Keep service tags URL-safe and lowercase.
        slug = "".join(c if c.isalnum() else "-" for c in incident.service_or_component.lower()).strip("-")[:40]
        if slug:
            tags.append(f"service:{slug}")
    return tags


def memory_units(incident: Incident) -> list[tuple[str, str, list[str]]]:
    """Yield (memory_kind, content, extra_tags) units for one incident.

    Empty/unknown fields produce NO memory - never filler content.
    """
    cfg = get_app_config().app
    unit_kind_map = set(cfg.memory.retain_units)
    units: list[tuple[str, str, list[str]]] = []

    summary_parts = [f"Incident: {incident.title}"]
    if incident.service_or_component:
        summary_parts.append(f"Service: {incident.service_or_component}")
    if incident.severity:
        summary_parts.append(f"Severity: {incident.severity}")
    if incident.trigger_change:
        summary_parts.append(f"Trigger: {incident.trigger_change}")
    if incident.root_cause:
        summary_parts.append(f"Root cause: {incident.root_cause}")
    if incident.symptoms:
        summary_parts.append("Symptoms: " + "; ".join(incident.symptoms[:5]))

    if "incident_summary" in unit_kind_map and incident.root_cause:
        units.append(("incident_summary", "\n".join(summary_parts), []))

    for i, fix in enumerate(incident.failed_fixes or [], start=1):
        if "failed_fix" in unit_kind_map:
            units.append((
                "failed_fix",
                f"Failed fix for '{incident.title}': {fix}",
                ["outcome:failed-fix"],
            ))

    if "successful_fix" in unit_kind_map and incident.successful_fix:
        units.append((
            "successful_fix",
            f"What finally worked for '{incident.title}': {incident.successful_fix}",
            ["outcome:successful-fix"],
        ))

    if "precursor_signature" in unit_kind_map and incident.precursor_signature:
        units.append((
            "precursor_signature",
            f"Warning sign - before incident '{incident.title}', the change pattern was: {incident.precursor_signature}",
            [],
        ))

    return units


def retain_incident(session: Session, incident: Incident) -> list[RetainedMemory]:
    """Retain one memory-split incident. Returns created RetainedMemory rows.

    Raises ValueError if the incident is held-out (defence in depth; the split
    guarantee is also asserted by tests).
    """
    if incident.split != "memory":
        raise ValueError(
            f"refusing to retain held-out incident {incident.id} ({incident.source_url})"
        )
    if incident.id is None:
        raise ValueError("incident must be persisted before retain")

    hindsight = get_hindsight()
    tags = incident_tags(incident)
    context = f"Postmortem: {incident.title} ({incident.source_url})"

    rows: list[RetainedMemory] = []
    for kind, content, extra_tags in memory_units(incident):
        document_id = f"incident-{incident.id}-{kind}"
        try:
            result = hindsight.retain_memory(
                content=content,
                context=context,
                memory_kind=kind,
                tags=tags + extra_tags,
                metadata={
                    "incident_id": str(incident.id),
                    "source_url": incident.source_url,
                    "change_category": incident.change_category,
                    "memory_kind": kind,
                },
                document_id=document_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("retain failed incident=%s kind=%s: %s", incident.id, kind, exc)
            raise
        row = RetainedMemory(
            memory_id=result.get("operation_id"),
            origin_kind="incident",
            incident_id=incident.id,
            memory_kind=kind,
            tags=tags + extra_tags,
            content_preview=content[:500],
            document_id=document_id,
        )
        session.add(row)
        rows.append(row)

    session.commit()
    logger.info("retained %d memory units for incident %s", len(rows), incident.id)
    return rows


async def aretain_incident(session: Session, incident: Incident) -> list[RetainedMemory]:
    """Async variant of retain_incident for FastAPI contexts.

    The sync client spins its own event loop and dies inside a running one, so
    every Hindsight call from a request handler must go through the a* variants.
    """
    if incident.split != "memory":
        raise ValueError(
            f"refusing to retain held-out incident {incident.id} ({incident.source_url})"
        )
    if incident.id is None:
        raise ValueError("incident must be persisted before retain")

    hindsight = get_hindsight()
    tags = incident_tags(incident)
    context = f"Postmortem: {incident.title} ({incident.source_url})"

    rows: list[RetainedMemory] = []
    for kind, content, extra_tags in memory_units(incident):
        document_id = f"incident-{incident.id}-{kind}"
        result = await hindsight.aretain_memory(
            content=content,
            context=context,
            memory_kind=kind,
            tags=tags + extra_tags,
            metadata={
                "incident_id": str(incident.id),
                "source_url": incident.source_url,
                "change_category": incident.change_category,
                "memory_kind": kind,
            },
            document_id=document_id,
        )
        row = RetainedMemory(
            memory_id=result.get("operation_id"),
            origin_kind="incident",
            incident_id=incident.id,
            memory_kind=kind,
            tags=tags + extra_tags,
            content_preview=content[:500],
            document_id=document_id,
        )
        session.add(row)
        rows.append(row)

    session.commit()
    logger.info("retained %d memory units for incident %s (async)", len(rows), incident.id)
    return rows
