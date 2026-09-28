"""Health and config endpoints - honest connectivity, no invented status."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from backend.config import get_app_config
from backend.db.session import get_session
from backend.llm.client import LlmClient
from backend.memory.hindsight_client import get_hindsight
from backend.schemas.pipeline import HealthReport
from backend.settings import get_settings

health_router = APIRouter(tags=["health"])
config_router = APIRouter(tags=["config"])


@health_router.get("/health", response_model=HealthReport)
async def health(session: Session = Depends(get_session)) -> HealthReport:
    """Report REAL connectivity to every dependency. Never fabricates status."""
    started = time.time()

    # Hindsight (async client inside the event loop; the sync client dies there).
    hs = get_hindsight()
    hindsight_report = await hs.ahealth()

    # LLM.
    llm_report = LlmClient().health_check()

    # Database - a real round-trip, not a ping-less success.
    db_report: dict[str, Any]
    try:
        session.exec(text("SELECT 1"))
        db_report = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        db_report = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    cfg = get_app_config()
    parts_ok = hindsight_report.get("ok") and llm_report.get("ok") and db_report.get("ok")
    status = "ok" if parts_ok else ("error" if not (hindsight_report.get("ok") or llm_report.get("ok")) else "degraded")

    return HealthReport(
        status=status,
        hindsight=hindsight_report,
        llm=llm_report,
        database=db_report,
        config={
            "org": cfg.app.org.name,
            "bank_label": cfg.app.memory.bank_label,
            "change_categories": cfg.app.change_categories,
            "sources_enabled": len(cfg.sources.select()),
            "sources_total": len(cfg.sources.sources),
            "heldout_ratio": cfg.eval.split.heldout_ratio,
            "conditions": sorted(cfg.eval.conditions.keys()),
            "health_duration_ms": int((time.time() - started) * 1000),
        },
    )


@config_router.get("/config")
async def get_config() -> dict[str, Any]:
    """Read-only view of the effective configuration (no secrets)."""
    settings = get_settings()
    cfg = get_app_config()
    return {
        "app": json.loads(cfg.app.model_dump_json()),
        "llm_tasks": {
            task: {"models": t.models, "max_tokens": t.max_tokens}
            for task, t in cfg.llm.tasks.items()
        },
        "eval": json.loads(cfg.eval.model_dump_json()),
        "runtime": {
            "llm_provider": settings.llm_provider,
            "llm_base_url": settings.resolved_llm_base_url,
            "hindsight_base_url": settings.hindsight_base_url,
            "hindsight_bank_id": settings.hindsight_bank_id,
            "database_url": settings.database_url.split("://")[0] + "://<redacted>",
        },
    }
