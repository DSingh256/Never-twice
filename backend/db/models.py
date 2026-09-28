"""Database models.

Every number the UI displays is derived from rows in these tables or from a live
Hindsight call. Nothing is seeded, no sample rows exist, and an empty database
must render honest empty states rather than placeholder content.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, JSON, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceFetch(SQLModel, table=True):
    """One attempt to fetch and clean a postmortem article."""

    __tablename__ = "source_fetches"

    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(index=True, unique=True)
    org: str = ""
    title_hint: str = ""
    # pending | fetched | extracted | failed | rejected
    status: str = Field(default="pending", index=True)
    http_status: Optional[int] = None
    content_hash: Optional[str] = None
    clean_chars: int = 0
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Set when cleaning produced text but extraction rejected or failed.
    extraction_error: Optional[str] = Field(default=None, sa_column=Column(Text))
    attempts: int = 0
    incident_id: Optional[int] = Field(default=None, foreign_key="incidents.id")
    fetched_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utcnow)


class Incident(SQLModel, table=True):
    """A structured postmortem extracted from a source article."""

    __tablename__ = "incidents"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_url: str = Field(index=True, unique=True)
    org: str = ""
    title: str = ""
    service_or_component: str = ""
    severity: Optional[str] = None
    symptoms: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    trigger_change: Optional[str] = None
    root_cause: Optional[str] = None
    failed_fixes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    successful_fix: Optional[str] = None
    preventive_actions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    change_category: str = "other"
    precursor_signature: Optional[str] = None
    extraction_confidence: Optional[float] = None
    extraction_model: Optional[str] = None
    # memory | heldout. Only `memory` incidents may ever be retained.
    # Empty default so assign_splits() can classify new rows ("" is falsy).
    split: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class RetainedMemory(SQLModel, table=True):
    """Audit trail linking a Hindsight memory back to its origin row.

    This exists so the split guarantee is checkable: every retained memory can be
    resolved to an incident, and no held-out incident may appear here.
    """

    __tablename__ = "retained_memories"

    id: Optional[int] = Field(default=None, primary_key=True)
    memory_id: Optional[str] = Field(default=None, index=True)
    # incident | feedback | pr_outcome
    origin_kind: str = Field(default="incident", index=True)
    incident_id: Optional[int] = Field(default=None, foreign_key="incidents.id", index=True)
    analysis_id: Optional[int] = Field(default=None, foreign_key="analyses.id", index=True)
    # incident_summary | failed_fix | successful_fix | precursor_signature | feedback
    memory_kind: str = ""
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    content_preview: str = Field(default="", sa_column=Column(Text))
    document_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class Analysis(SQLModel, table=True):
    """One diff analysis run."""

    __tablename__ = "analyses"

    id: Optional[int] = Field(default=None, primary_key=True)
    # running | done | failed
    status: str = Field(default="running", index=True)
    # ui | webhook | api
    origin: str = "ui"
    repo: Optional[str] = None
    service: Optional[str] = None
    pr_url: Optional[str] = None
    pr_title: Optional[str] = None
    pr_number: Optional[int] = None
    diff: str = Field(default="", sa_column=Column(Text))
    diff_truncated: bool = False
    change_facts: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    verdict: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    confidence: Optional[float] = None
    evidence_count: int = 0
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    duration_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: Optional[datetime] = None


class AnalysisStep(SQLModel, table=True):
    """A single streamed step of an analysis, persisted so SSE can replay."""

    __tablename__ = "analysis_steps"

    id: Optional[int] = Field(default=None, primary_key=True)
    analysis_id: int = Field(foreign_key="analyses.id", index=True)
    # sequentially increasing within an analysis; the SSE cursor.
    seq: int = 0
    # understand_diff | recall_memories | recall_feedback | reflect | verdict | done | error
    step: str = ""
    # started | ok | failed | skipped
    status: str = "ok"
    message: str = ""
    detail: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    duration_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)


class Feedback(SQLModel, table=True):
    """Engineer feedback on a verdict. Retained back into memory."""

    __tablename__ = "feedback"

    id: Optional[int] = Field(default=None, primary_key=True)
    analysis_id: int = Field(foreign_key="analyses.id", index=True)
    # good_catch | false_positive
    verdict: str
    note: Optional[str] = Field(default=None, sa_column=Column(Text))
    reviewer: Optional[str] = None
    # Tags used when retaining this feedback, so it can be recalled later.
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    memory_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class EvalRun(SQLModel, table=True):
    """One execution of the A/B/C ablation harness."""

    __tablename__ = "eval_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    # running | done | failed
    status: str = Field(default="running", index=True)
    label: Optional[str] = None
    benchmark_path: Optional[str] = None
    # Exact config used, so a result can never be quietly re-tuned.
    config_snapshot: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    metrics: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    item_count: int = 0
    created_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: Optional[datetime] = None


class EvalItem(SQLModel, table=True):
    """Per-benchmark-item outcome for one condition."""

    __tablename__ = "eval_items"
    __table_args__ = (UniqueConstraint("run_id", "case_id", "condition", name="uq_eval_item"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="eval_runs.id", index=True)
    case_id: str = Field(index=True)
    condition: str = Field(index=True)
    incident_id: Optional[int] = Field(default=None, foreign_key="incidents.id")
    expected_label: int = 0
    predicted_level: str = "none"
    predicted_positive: bool = False
    correct: bool = False
    confidence: Optional[float] = None
    evidence_count: int = 0
    supporting_memory_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    latency_ms: Optional[int] = None
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
