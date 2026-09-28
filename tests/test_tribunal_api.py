"""Tribunal API contract tests.

No LLM or Hindsight access: the background worker is patched to a no-op and
every tribunal row created during a test is removed afterwards (by id
snapshot, so the dev database stays untouched regardless of thread timing).
These pin validation, 404s, and the payload shape of a fresh run (three
witness seats, no delta until witnesses testify).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.db.models import TribunalItem, TribunalRun
from backend.db.session import session_scope

MINIMAL_DIFF = "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-x\n+y\n"


@pytest.fixture()
def client(monkeypatch):
    """TestClient with the tribunal worker disabled and rows cleaned up."""

    def _noop_worker(run_id: int) -> None:
        return None

    monkeypatch.setattr("backend.api.tribunal.run_tribunal_sync", _noop_worker)

    from backend.main import create_app

    app = create_app()

    with session_scope() as session:
        rows = session.exec(select(TribunalRun.id)).all()
        max_id_before = max((r for r in rows), default=0)

    with TestClient(app) as c:
        yield c

    with session_scope() as session:
        new_runs = session.exec(
            select(TribunalRun).where(TribunalRun.id > max_id_before)
        ).all()
        for run in new_runs:
            for item in session.exec(
                select(TribunalItem).where(TribunalItem.run_id == run.id)
            ).all():
                session.delete(item)
            session.delete(run)


def test_tribunal_rejects_blank_diff(client):
    r = client.post("/api/tribunal", json={"diff": "   "})
    # Passes field validation (len > 0), rejected explicitly by the endpoint.
    assert r.status_code == 400


def test_tribunal_rejects_missing_diff(client):
    r = client.post("/api/tribunal", json={"pr_title": "x"})
    assert r.status_code == 422


def test_tribunal_poll_404_unknown_id(client):
    r = client.get("/api/tribunal/999999")
    assert r.status_code == 404


def test_tribunal_fresh_run_shape(client):
    """A just-created run has three witness seats and no delta yet."""
    r = client.post("/api/tribunal", json={"diff": MINIMAL_DIFF, "pr_title": "t"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["poll"].endswith(f"/api/tribunal/{body['tribunal_id']}")

    poll = client.get(f"/api/tribunal/{body['tribunal_id']}")
    assert poll.status_code == 200
    run = poll.json()
    assert [w["condition"] for w in run["witnesses"]] == ["A", "B", "C"]
    for w in run["witnesses"]:
        assert w["status"] == "pending"  # worker is a no-op in tests
        assert isinstance(w["evidence_count"], int)
    assert run["delta"] is None


def test_tribunals_list_includes_new_run(client):
    r = client.post("/api/tribunal", json={"diff": MINIMAL_DIFF})
    tid = r.json()["tribunal_id"]
    listing = client.get("/api/tribunals?limit=5").json()
    assert any(t["id"] == tid for t in listing["tribunals"])
