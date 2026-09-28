"""Database engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.settings import get_settings

_engine = None


def _sqlite_path(url: str) -> str | None:
    if url.startswith("sqlite"):
        # sqlite:///./data/app.db  ->  ./data/app.db
        return url.split("sqlite:///")[-1]
    return None


def get_engine():
    """Create (once) and return the SQLAlchemy engine."""
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = settings.database_url

    path = _sqlite_path(url)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if path in (":memory:",) else None,
        )
    else:
        _engine = create_engine(url, pool_pre_ping=True)

    return _engine


def init_db() -> None:
    """Create any missing tables. Safe to call on every startup."""
    from backend.db import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    with Session(get_engine()) as session:
        yield session


def session_scope() -> Session:
    """Session for use outside request handlers (pipeline workers, scripts)."""
    return Session(get_engine())
