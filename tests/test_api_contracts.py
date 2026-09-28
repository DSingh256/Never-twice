"""API contract tests: feedback signatures and webhook signatures.

No Hindsight or LLM access needed - these pin the authentication rules.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient


def _sign(body: dict, secret: str) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def _client():
    import os

    os.environ["FEEDBACK_SIGNING_SECRET"] = "test-secret"
    os.environ["GITHUB_WEBHOOK_SECRET"] = "whsec-test"
    from backend.main import create_app

    app = create_app()
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Feedback signature (reviewer must be INSIDE the signed body)
# --------------------------------------------------------------------------- #
def test_feedback_rejects_bad_signature():
    with _client() as client:
        r = client.post(
            "/api/feedback",
            json={"analysis_id": 1, "verdict": "good_catch", "signature": "deadbeef"},
        )
        assert r.status_code == 401


def test_feedback_signature_covers_reviewer():
    """The 401 bug this pins: signing without 'reviewer' but sending it.

    The server rebuilds the signed body including reviewer when present.
    """
    with _client() as client:
        body_with = {"analysis_id": 999999, "verdict": "good_catch", "reviewer": "t"}
        sig = _sign(body_with, "test-secret")
        # Right signature, nonexistent analysis -> must pass auth (404 next).
        r = client.post(
            "/api/feedback", json={**body_with, "signature": sig}
        )
        assert r.status_code == 404  # auth ok; analysis missing

        body_without = {"analysis_id": 999999, "verdict": "good_catch"}
        sig2 = _sign(body_without, "test-secret")
        r2 = client.post(
            "/api/feedback",
            json={**body_without, "reviewer": "t", "signature": sig2},
        )
        assert r2.status_code == 401  # signature no longer covers reviewer


# --------------------------------------------------------------------------- #
# Webhook signature over the RAW body
# --------------------------------------------------------------------------- #
def _gh_signature(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_webhook_ping_requires_signature():
    with _client() as client:
        raw = json.dumps({"zen": "ok"}).encode()
        r = client.post(
            "/api/webhooks/github",
            content=raw,
            headers={"Content-Type": "application/json", "X-GitHub-Event": "ping"},
        )
        assert r.status_code == 401


def test_webhook_ping_happy_path():
    with _client() as client:
        raw = json.dumps({"zen": "ok"}).encode()
        r = client.post(
            "/api/webhooks/github",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": _gh_signature(raw, "whsec-test"),
            },
        )
        assert r.status_code == 200
        assert r.json()["handled"] == "ping"


def test_webhook_non_pr_event_ignored():
    with _client() as client:
        raw = json.dumps({"action": "published"}).encode()
        r = client.post(
            "/api/webhooks/github",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": _gh_signature(raw, "whsec-test"),
            },
        )
        assert r.status_code == 200
        assert "ignored" in r.json()["handled"]


def test_webhook_ignores_labeled_action_without_analysis():
    with _client() as client:
        raw = json.dumps(
            {"action": "labeled", "pull_request": {"html_url": "https://github.com/o/r/pull/1"}}
        ).encode()
        r = client.post(
            "/api/webhooks/github",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": _gh_signature(raw, "whsec-test"),
            },
        )
        assert r.status_code == 200
        assert "ignored" in r.json()["handled"]
