"""Feedback API: engineers confirm or reject verdicts; feedback is retained
back into Hindsight so future verdicts change.

POST /api/feedback  - signed submission (HMAC-SHA256 under FEEDBACK_SIGNING_SECRET)
GET  /api/feedback  - history
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.config import get_app_config
from backend.db.models import Analysis, Feedback
from backend.db.session import get_session
from backend.memory.hindsight_client import get_hindsight
from backend.schemas.pipeline import FeedbackSubmission

feedback_router = APIRouter(tags=["feedback"])


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    """Canonical JSON -> HMAC-SHA256 hex digest."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def verify_signature(payload: dict[str, Any], signature: str, secret: str) -> bool:
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(expected, signature)


@feedback_router.post("/feedback")
async def submit_feedback(
    submission: FeedbackSubmission,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Record feedback and retain it as memory so future verdicts change."""
    settings = get_settings_safe()

    # Verify signature over everything except the signature itself.
    body = {"analysis_id": submission.analysis_id, "verdict": submission.verdict}
    if submission.note is not None:
        body["note"] = submission.note
    if submission.reviewer is not None:
        body["reviewer"] = submission.reviewer
    if not verify_signature(body, submission.signature, settings.feedback_signing_secret):
        raise HTTPException(status_code=401, detail="invalid feedback signature")

    analysis = session.get(Analysis, submission.analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="analysis not found")

    cfg = get_app_config()
    hindsight = get_hindsight()

    # Feedback memory text: explicit about what the alert was and what the
    # engineer concluded, so future recall can act on it.
    verdict = analysis.verdict or {}
    feedback_text = (
        f"Engineer feedback on a Never Twice risk verdict: '{submission.verdict}'. "
        f"The change was: {verdict.get('rationale', '')[:200]} "
        f"(proposed level was '{verdict.get('level', 'unknown')}', "
        f"evidence count {analysis.evidence_count})."
    )
    if submission.note:
        feedback_text += f" Engineer note: {submission.note}"

    tags = [
        f"analysis:{submission.analysis_id}",
        f"feedback_verdict:{submission.verdict}",
    ]
    if analysis.service:
        tags.append(f"service:{analysis.service}")

    result = await hindsight.aretain_memory(
        content=feedback_text,
        context="Engineer feedback from the Never Twice UI",
        memory_kind="feedback",
        tags=tags,
        metadata={
            "analysis_id": str(submission.analysis_id),
            "feedback_verdict": submission.verdict,
        },
        document_id=f"feedback-analysis-{submission.analysis_id}",
    )

    row = Feedback(
        analysis_id=submission.analysis_id,
        verdict=submission.verdict,
        note=submission.note,
        reviewer=submission.reviewer,
        tags=tags,
        memory_id=result.get("operation_id"),
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    return {
        "ok": True,
        "feedback_id": row.id,
        "retained": True,
        "message": (
            "Feedback recorded and retained to memory. Future analyses of "
            "similar changes will weigh it."
        ),
    }


@feedback_router.get("/feedback")
async def list_feedback(limit: int = 100, session: Session = Depends(get_session)) -> dict[str, Any]:
    rows = session.exec(
        select(Feedback).order_by(Feedback.created_at.desc()).limit(limit)
    ).all()
    return {
        "feedback": [
            {
                "id": r.id,
                "analysis_id": r.analysis_id,
                "verdict": r.verdict,
                "note": r.note,
                "reviewer": r.reviewer,
                "memory_id": r.memory_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


def get_settings_safe():
    from backend.settings import get_settings

    return get_settings()
