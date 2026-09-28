"""Pydantic schemas for pipeline inputs and outputs.

These are the contracts the LLM must satisfy. Every LLM response is validated
against them; invalid output is retried, then falls back to the next model, and
finally surfaces an explicit error instead of corrupting the pipeline.

Confidence is NEVER produced by the LLM: it is computed in
`backend/pipeline/confidence.py` from evidence counts, retrieval scores and
feedback agreement (rule 4 of the brief).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Change categories are loaded from config/app.yaml; kept here as a static
# literal only because Pydantic needs concrete values at class definition time.
# The pipeline validates against the config list as well.
ChangeCategory = Literal["config", "deploy", "migration", "dependency", "capacity", "other"]
RiskLevel = Literal["high", "medium", "low", "none"]


class IncidentExtraction(BaseModel):
    """Schema the LLM must fill when converting an article into an incident."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=3, description="Short factual title of the incident")
    org: Optional[str] = Field(default=None, description="Organization that published the postmortem")
    service_or_component: Optional[str] = Field(
        default=None, description="The system or component that failed, as stated in the article"
    )
    severity: Optional[str] = Field(
        default=None, description="Severity as stated in the article; null when not stated"
    )
    symptoms: list[str] = Field(default_factory=list, description="Observed symptoms, exactly as reported")
    trigger_change: Optional[str] = Field(
        default=None,
        description="The change that started the incident (config/deploy/migration/dependency). Null if not stated.",
    )
    root_cause: Optional[str] = Field(
        default=None, description="Root cause as stated by the authors; null if the article does not identify one"
    )
    failed_fixes: list[str] = Field(default_factory=list, description="Fix attempts that did not work, if any")
    successful_fix: Optional[str] = Field(
        default=None, description="What actually resolved the incident; null if not stated"
    )
    preventive_actions: list[str] = Field(default_factory=list)
    change_category: ChangeCategory = "other"
    precursor_signature: Optional[str] = Field(
        default=None,
        description=(
            "Short description of the code/config change pattern that preceded the incident. "
            "Only if the article supports it; never inferred."
        ),
    )
    extraction_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="How much of the article supports these fields"
    )

    @field_validator("symptoms", "failed_fixes", "preventive_actions", mode="before")
    @classmethod
    def _clean_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        # None entries mean 'no value' - dropped, never stringified.
        return [str(item).strip() for item in v if item is not None and str(item).strip()]

    @field_validator("title", "org", "service_or_component", "severity", "trigger_change", "root_cause", "successful_fix", "precursor_signature", mode="before")
    @classmethod
    def _clean_str(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if v.lower() in {"", "null", "none", "n/a", "unknown", "not stated"}:
                return None
        return v


class ChangeFact(BaseModel):
    """Structured facts about a diff, extracted before any verdict."""

    model_config = ConfigDict(extra="ignore")

    files: list[str] = Field(default_factory=list, description="File paths touched by the diff")
    config_keys: list[str] = Field(
        default_factory=list, description="Config keys or environment variables changed, with old -> new values"
    )
    affected_component: Optional[str] = Field(default=None, description="Best-guess service or component affected")
    change_category: ChangeCategory = "other"
    summary: str = Field(default="", description="One-sentence factual summary of what the diff does")
    value_changes: list[dict[str, str]] = Field(
        default_factory=list,
        description='List of {"key", "old", "new"} triples for concrete value changes',
    )

    @field_validator("files", "config_keys", mode="before")
    @classmethod
    def _clean_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(item).strip() for item in v if str(item).strip()]


class MatchedIncident(BaseModel):
    """A historical incident matched by recall, as presented in a verdict."""

    incident_id: Optional[int] = None
    source_url: Optional[str] = None
    title: Optional[str] = None
    why_similar: str = ""
    what_failed_before: str = ""
    failed_fixes: list[str] = Field(default_factory=list)
    what_worked: Optional[str] = None


class FeedbackInfluence(BaseModel):
    """Which past feedback shaped a verdict."""

    feedback_verdict: Literal["good_catch", "false_positive"]
    note: str = ""
    memory_id: Optional[str] = None


class RiskVerdict(BaseModel):
    """The final verdict for a diff.

    `evidence_count`, `supporting_memory_ids` and `confidence` are computed by
    the pipeline, not the LLM; the LLM proposes level/rationale/matches/checks.
    """

    level: RiskLevel = "none"
    rationale: str = Field(default="", description="Why this level, grounded in the evidence below")
    matched_incidents: list[MatchedIncident] = Field(default_factory=list)
    suggested_checks: list[str] = Field(default_factory=list)
    # Populated by the pipeline from feedback recall, not by the LLM.
    learned_from_feedback: list[FeedbackInfluence] = Field(default_factory=list)
    # Populated by the pipeline.
    evidence_count: int = 0
    supporting_memory_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class FeedbackSubmission(BaseModel):
    """A signed feedback submission."""

    analysis_id: int
    verdict: Literal["good_catch", "false_positive"]
    note: Optional[str] = None
    reviewer: Optional[str] = None
    signature: str = Field(description="HMAC of the payload under FEEDBACK_SIGNING_SECRET")


class MemoryHit(BaseModel):
    """One recalled memory, normalised across the Hindsight client shape."""

    memory_id: str
    text: str
    fact_type: str = ""
    score: float = 0.0
    tags: list[str] = Field(default_factory=list)
    document_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_hindsight(cls, result: Any) -> "MemoryHit":
        """Normalise a Hindsight recall result item.

        Verified against hindsight-client 0.10.1: results carry `scores`
        (a pydantic RecallScores with final/reranker/semantic/keyword), `tags`,
        `document_id`, and `metadata` (a JSON string or dict).
        """
        raw_scores = getattr(result, "scores", None)
        if hasattr(raw_scores, "final"):
            score = float(raw_scores.final or 0.0)
        elif isinstance(raw_scores, dict):
            score = float(raw_scores.get("final", 0.0) or 0.0)
        else:
            score = 0.0
        metadata = getattr(result, "metadata", None) or {}
        if isinstance(metadata, str):
            import json

            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {"raw": metadata}
        return cls(
            memory_id=getattr(result, "id", "") or "",
            text=getattr(result, "text", "") or "",
            fact_type=getattr(result, "type", "") or getattr(result, "fact_type", "") or "",
            score=score,
            tags=list(getattr(result, "tags", None) or []),
            document_id=getattr(result, "document_id", None),
            metadata=metadata,
        )


class HealthReport(BaseModel):
    """GET /api/health - real connectivity, honestly reported."""

    status: Literal["ok", "degraded", "error"]
    hindsight: dict[str, Any]
    llm: dict[str, Any]
    database: dict[str, Any]
    config: dict[str, Any]
