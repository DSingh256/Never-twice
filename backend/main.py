"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_app_config
from backend.db.session import get_engine, init_db
from backend.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("never-twice")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    get_app_config()  # fail fast if a YAML config is malformed
    init_db()
    logger.info("Never Twice backend starting (env=%s)", settings.app_env)
    yield
    # Release the async Hindsight session cleanly on shutdown.
    from backend.memory.hindsight_client import get_hindsight

    await get_hindsight().aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Never Twice API",
        description="Deployment gate powered by organizational memory.",
        version="0.1.0",
        lifespan=lifespan,
    )
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routers (imported here to avoid circulars at module load) ----------
    from backend.api.analyze import analyze_router
    from backend.api.eval import eval_router
    from backend.api.feedback import feedback_router
    from backend.api.ingest import ingest_router
    from backend.api.memory import memory_router
    from backend.api.routes import config_router, health_router
    from backend.api.tribunal import tribunal_router
    from backend.api.webhooks import webhook_router

    app.include_router(health_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")
    app.include_router(analyze_router, prefix="/api")
    app.include_router(feedback_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(eval_router, prefix="/api")
    app.include_router(tribunal_router, prefix="/api")
    app.include_router(webhook_router, prefix="/api")

    @app.get("/")
    async def root() -> dict:
        return {"name": "Never Twice API", "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
