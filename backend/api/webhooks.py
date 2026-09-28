"""GitHub webhook API (M8).

POST /api/webhooks/github  - receives pull_request events, verifies the
X-Hub-Signature-256 HMAC over the RAW body under GITHUB_WEBHOOK_SECRET, fetches
the PR's unified diff from the GitHub API, and starts the same analysis
pipeline the UI uses (origin='webhook').

GET  /api/webhooks/github/status - honest readiness report for the demo.

No verification bypass: an unconfigured secret is a 503, a bad signature is a
401. `ping` events are acknowledged without analysis.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from backend.db.models import Analysis
from backend.db.session import get_session
from backend.settings import get_settings

webhook_router = APIRouter(tags=["webhooks"])


def _verify_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """GitHub sends 'sha256=<hex>' of the raw request body (HMAC-SHA256)."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256=").strip())


async def _fetch_pr_diff(pr_url: str) -> tuple[str, str, str, int | None]:
    """Fetch (diff, repo, title, pr_number) for a pull request.

    Works with any PR URL; the .diff URL is derived from the API URL, and the
    unified diff is requested with the v3.diff media type. GITHUB_TOKEN is used
    when present (rate limits, private repos).
    """
    settings = get_settings()
    # https://github.com/owner/repo/pull/42 -> api.github.com/repos/owner/repo/pulls/42
    parts = pr_url.rstrip("/").split("/")
    if len(parts) < 4 or parts[-2] != "pull":
        raise HTTPException(status_code=400, detail=f"not a PR URL: {pr_url}")
    owner, repo, number = parts[-4], parts[-3], parts[-1]

    api_url = f"{settings.github_api_url}/repos/{owner}/{repo}/pulls/{number}"
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "never-twice-gate",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            diff_resp = await client.get(api_url, headers=headers)
            diff_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = (
                "GitHub rate limit reached; configure GITHUB_TOKEN"
                if status == 403
                else f"GitHub returned {status} for {pr_url}"
            )
            raise HTTPException(status_code=502, detail=detail)
        diff = diff_resp.text

        meta_headers = dict(headers, Accept="application/vnd.github+json")
        meta_resp = await client.get(api_url, headers=meta_headers)
        title, repo_full = "", f"{owner}/{repo}"
        if meta_resp.status_code == 200:
            meta = meta_resp.json()
            title = meta.get("title") or ""
            repo_full = (meta.get("base") or {}).get("repo", {}).get("full_name") or repo_full

    return diff, repo_full, title, int(number) if number.isdigit() else None


@webhook_router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    settings = get_settings()
    secret = settings.github_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="GITHUB_WEBHOOK_SECRET is not configured; refusing to accept webhooks",
        )

    raw = await request.body()
    if not _verify_signature(raw, request.headers.get("X-Hub-Signature-256"), secret):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    event = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="body is not JSON")

    if event == "ping":
        return {"ok": True, "handled": "ping"}

    if event != "pull_request":
        return {"ok": True, "handled": f"ignored event {event}"}

    action = payload.get("action")
    if action not in ("opened", "synchronize", "reopened"):
        return {"ok": True, "handled": f"ignored pull_request action {action}"}

    pr = payload.get("pull_request") or {}
    pr_url = pr.get("html_url")
    if not pr_url:
        raise HTTPException(status_code=400, detail="pull_request payload has no html_url")

    diff, repo_full, title, pr_number = await _fetch_pr_diff(pr_url)
    if not diff.strip():
        return {"ok": True, "handled": "empty diff", "analysis_id": None}

    analysis = Analysis(
        status="running",
        origin="webhook",
        repo=repo_full,
        pr_url=pr_url,
        pr_title=title or None,
        pr_number=pr_number,
        diff=diff[: get_app_max_diff()],
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)

    asyncio.get_running_loop().create_task(_run_webhook_analysis(analysis.id))
    return {
        "ok": True,
        "handled": "pull_request",
        "analysis_id": analysis.id,
        "stream": f"/api/analyze/{analysis.id}/stream",
    }


def get_app_max_diff() -> int:
    from backend.config import get_app_config

    return get_app_config().app.analysis.max_diff_bytes


async def _run_webhook_analysis(analysis_id: int) -> None:
    from backend.db.session import session_scope
    from backend.pipeline.analysis import run_analysis

    with session_scope() as session:
        analysis = session.get(Analysis, analysis_id)
        if analysis is None:
            return
        await run_analysis(session, analysis)


@webhook_router.get("/webhooks/github/status")
async def webhook_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "secret_configured": bool(settings.github_webhook_secret),
        "token_configured": bool(settings.github_token),
        "api_url": settings.github_api_url,
        "events": ["pull_request(opened|synchronize|reopened)", "ping"],
        "signature": "X-Hub-Signature-256 (HMAC-SHA256 over raw body)",
    }
