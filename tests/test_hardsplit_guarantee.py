"""The split guarantee, end to end (no Hindsight needed).

Simulates the ingest-time invariant: after ingestion + split, NO audit row may
point at a held-out incident. This is exactly what /api/eval/split-check
verifies live against the production DB.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from backend.db.models import Incident, RetainedMemory


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed(session: Session, n: int = 10) -> None:
    for i in range(n):
        session.add(
            Incident(source_url=f"https://example.com/p-{i}", title=f"t{i}", root_cause="c")
        )
    session.commit()


def test_heldout_never_in_audit_trail(session):
    from backend.pipeline.split import assign_splits

    _seed(session)
    counts = assign_splits(session)

    # Simulate retention having run for memory incidents only.
    memory_ids = [
        i.id for i in session.exec(select(Incident).where(Incident.split == "memory")).all()
    ]
    for iid in memory_ids:
        session.add(
            RetainedMemory(
                memory_id=f"mid-{iid}",
                origin_kind="incident",
                incident_id=iid,
                memory_kind="incident_summary",
                document_id=f"incident-{iid}-incident_summary",
            )
        )
    session.commit()

    # The invariant, in the same shape as the live split-check endpoint.
    heldout_ids = {
        i.id for i in session.exec(select(Incident).where(Incident.split == "heldout")).all()
    }
    retained_ids = {
        r.incident_id
        for r in session.exec(select(RetainedMemory)).all()
        if r.origin_kind == "incident"
    }
    leaked = sorted(heldout_ids & retained_ids)
    assert leaked == []
    assert counts["memory"] == len(retained_ids)
    assert counts["heldout"] > 0


def test_empty_split_means_pending(session):
    """Regression pin for the M2 bug: split default '' so assign_splits sees pending rows."""
    _seed(session, 3)
    rows = session.exec(select(Incident)).all()
    assert all(i.split == "" for i in rows)
    from backend.pipeline.split import assign_splits

    counts = assign_splits(session)
    assert counts["memory"] + counts["heldout"] == 3
