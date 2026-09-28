"""Memory introspection API (M7): the Atlas and Console read from here.

All data is read live from Hindsight and the audit DB - the API adds nothing
and invents nothing. Empty responses are honest empty states.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.db.models import Analysis, Feedback, Incident, RetainedMemory
from backend.db.session import get_session
from backend.memory.hindsight_client import get_hindsight

memory_router = APIRouter(tags=["memory"])

# Atlas sections map UI tabs onto our own tag convention. `retain.py` tags
# every unit `kind:<memory_kind>`; feedback lands as `kind:feedback`.
ATLAS_SECTIONS: list[dict[str, str]] = [
    {"tag": "kind:incident_summary", "label": "Incident summaries"},
    {"tag": "kind:failed_fix", "label": "Failed fixes"},
    {"tag": "kind:successful_fix", "label": "What finally worked"},
    {"tag": "kind:precursor_signature", "label": "Precursor signatures"},
    {"tag": "kind:feedback", "label": "Engineer feedback"},
]


def _item_to_dict(item: Any) -> dict[str, Any]:
    tags: list[str] = []
    raw_tags = getattr(item, "tags", None)
    if isinstance(raw_tags, str):
        try:
            tags = json.loads(raw_tags)
        except Exception:
            tags = [t for t in raw_tags.split(",") if t]
    elif raw_tags:
        tags = [str(t) for t in raw_tags]
    return {
        "id": getattr(item, "id", None),
        "text": (getattr(item, "text", "") or "")[:500],
        "fact_type": getattr(item, "type", None) or getattr(item, "fact_type", ""),
        "document_id": getattr(item, "document_id", None),
        "created_at": getattr(item, "created_at", None),
        "tags": tags,
    }


@memory_router.get("/memory/stats")
async def memory_stats(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Live counts from the bank + audit table; honest zeros when empty."""
    hindsight = get_hindsight()

    by_type: dict[str, int] = {}
    total_units = 0
    documents = 0
    try:
        client = hindsight._get_async()
        resp = await client.alist_memories(bank_id=hindsight.bank_id, limit=1000)
        items = getattr(resp, "items", None) or []
        total_units = len(items)
        documents = len({getattr(i, "document_id", None) for i in items if getattr(i, "document_id", None)})
        for it in items:
            t = getattr(it, "type", None) or "unknown"
            by_type[t] = by_type.get(t, 0) + 1
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"hindsight unavailable: {exc}")

    from sqlmodel import func

    retained = session.exec(select(RetainedMemory)).all()
    feedback_rows = session.exec(select(Feedback)).all()
    analysis_rows = session.exec(select(Analysis)).all()

    return {
        "bank_id": hindsight.bank_id,
        "total_memory_units": total_units,
        "documents": documents,
        "by_type": by_type,
        "audit": {
            "retained_rows": len(retained),
            "incidents_memory_split": sum(
                1 for i in session.exec(select(Incident).where(Incident.split == "memory")).all()
            ),
            "incidents_heldout_split": sum(
                1 for i in session.exec(select(Incident).where(Incident.split == "heldout")).all()
            ),
        },
        "app_totals": {
            "analyses": len(analysis_rows),
            "feedback": len(feedback_rows),
        },
    }


@memory_router.get("/memory/list")
async def memory_list(
    tag: str | None = None,
    type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Browse memory units, optionally filtered.

    `tag` filtering uses our audit table (Hindsight list API filters by type,
    not tags): memory units carry document_id, and the audit table maps
    document_id -> tags, so filtering is exact and never invented.
    """
    hindsight = get_hindsight()
    try:
        client = hindsight._get_async()
        kwargs: dict[str, Any] = {"limit": min(limit, 200), "offset": offset}
        if type:
            kwargs["type"] = type
        if q:
            kwargs["search_query"] = q
        resp = await client.alist_memories(bank_id=hindsight.bank_id, **kwargs)
        items = getattr(resp, "items", None) or []
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"hindsight units: {exc}")

    results = [_item_to_dict(i) for i in items]

    if tag:
        # document_id -> tags, derived from the audit tables (exact, no guessing).
        # Feedback submissions keep their own audit rows whose document ids are
        # deterministic (feedback-analysis-{id}); RetainedMemory rows carry tags
        # directly. Both are real records - nothing is inferred.
        doc_tags: dict[str, list[str]] = {}
        for r in session.exec(select(RetainedMemory)).all():
            if r.document_id:
                doc_tags.setdefault(r.document_id, []).extend(r.tags or [])
        for f in session.exec(select(Feedback)).all():
            doc_tags.setdefault(f"feedback-analysis-{f.analysis_id}", []).extend(
                ["kind:feedback", f"feedback_verdict:{f.verdict}"]
            )
        results = [r for r in results if tag in doc_tags.get(r.get("document_id") or "", [])]
        total = len(results)
    else:
        total = len(results)

    return {"memories": results[:limit], "total": total}


@memory_router.get("/memory/graph")
async def memory_graph(limit: int = 200) -> dict[str, Any]:
    """The bank's entity graph, as Hindsight reports it (sync wrapper, scripts-safe)."""
    return get_hindsight().graph(limit=limit)


@memory_router.get("/memory/tags")
async def memory_tags() -> dict[str, Any]:
    """All tags present in the bank."""
    return {"tags": get_hindsight().tags()}


@memory_router.get("/memory/search")
async def memory_search(q: str, limit: int = 20) -> dict[str, Any]:
    """Recall against the bank - the same operation the verdict pipeline uses."""
    if not q.strip():
        return {"memories": []}
    hits = await get_hindsight().arecall(q, max_tokens=4096, budget="mid")
    return {
        "memories": [
            {
                "id": h.memory_id,
                "text": h.text[:500],
                "score": round(h.score, 4),
                "fact_type": h.fact_type,
                "tags": h.tags,
                "document_id": h.document_id,
            }
            for h in hits[:limit]
        ]
    }
