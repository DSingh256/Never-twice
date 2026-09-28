"""Typed access to the `config/*.yaml` files.

Rule: product behaviour lives in YAML, secrets live in `.env`. Nothing in the
codebase should contain a threshold, a model name, a URL or a category list that
a judge could reasonably want to change - it belongs here instead.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"missing config file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


# --------------------------------------------------------------------------- #
# app.yaml
# --------------------------------------------------------------------------- #
class OrgConfig(BaseModel):
    name: str
    display_name: str


class RetainConfig(BaseModel):
    bank_label: str
    retain_units: list[str]
    recall_budget: str = "mid"
    recall_max_tokens: int = 4096
    reflect_budget: str = "mid"
    reflect_max_tokens: int = 2048


class RiskConfig(BaseModel):
    levels: list[str] = Field(default_factory=lambda: ["none", "low", "medium", "high"])
    min_evidence_for_elevated: int = 2
    min_retrieval_score: float = 0.05
    max_evidence_items: int = 12


class ConfidenceWeights(BaseModel):
    evidence: float = 0.45
    retrieval: float = 0.30
    feedback_agreement: float = 0.25


class ConfidenceConfig(BaseModel):
    weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)
    evidence_saturation: int = 5
    floor: float = 0.05

    def normalised_weights(self) -> ConfidenceWeights:
        """Weights renormalised to sum to 1 so confidence stays in 0..1."""
        w = self.weights
        total = w.evidence + w.retrieval + w.feedback_agreement
        if total <= 0:
            return ConfidenceWeights()
        return ConfidenceWeights(
            evidence=w.evidence / total,
            retrieval=w.retrieval / total,
            feedback_agreement=w.feedback_agreement / total,
        )


class AnalysisConfig(BaseModel):
    small_sample_memory_count: int = 3
    timeout_seconds: int = 300
    max_diff_bytes: int = 400_000


class IngestConfig(BaseModel):
    min_clean_chars: int = 800
    max_extraction_attempts: int = 2


class FeedbackConfig(BaseModel):
    tag_prefix: str = "feedback:"


class AppConfig(BaseModel):
    org: OrgConfig
    memory: RetainConfig
    change_categories: list[str]
    risk: RiskConfig
    confidence: ConfidenceConfig
    analysis: AnalysisConfig
    ingest: IngestConfig
    feedback: FeedbackConfig


# --------------------------------------------------------------------------- #
# llm.yaml
# --------------------------------------------------------------------------- #
class LlmDefaults(BaseModel):
    temperature: float = 0.0
    timeout_seconds: int = 180
    max_attempts_per_model: int = 3
    retry_backoff_seconds: float = 2.0
    retry_backoff_max_seconds: float = 30.0


class LlmTask(BaseModel):
    models: list[str]
    max_tokens: int = 2048
    timeout_seconds: int | None = None


class LlmConfig(BaseModel):
    defaults: LlmDefaults = Field(default_factory=LlmDefaults)
    tasks: dict[str, LlmTask] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# sources.yaml
# --------------------------------------------------------------------------- #
class SourceEntry(BaseModel):
    url: str
    org: str = ""
    title_hint: str = ""
    enabled: bool = True


class SourceSelection(BaseModel):
    max_total: int = 30
    max_per_org: int = 3
    order: str = "as_listed"


class SourcesConfig(BaseModel):
    index_url: str = ""
    notes: str = ""
    selection: SourceSelection = Field(default_factory=SourceSelection)
    sources: list[SourceEntry] = Field(default_factory=list)

    def select(self) -> list[SourceEntry]:
        """Apply the declared selection policy to the enabled sources."""
        chosen: list[SourceEntry] = []
        per_org: dict[str, int] = {}
        for src in self.sources:
            if not src.enabled:
                continue
            org = src.org or src.url
            if per_org.get(org, 0) >= self.selection.max_per_org:
                continue
            per_org[org] = per_org.get(org, 0) + 1
            chosen.append(src)
            if len(chosen) >= self.selection.max_total:
                break
        return chosen


# --------------------------------------------------------------------------- #
# eval.yaml
# --------------------------------------------------------------------------- #
class SplitConfig(BaseModel):
    heldout_ratio: float = 0.35
    seed: int = 20260928
    order_by: str = "source_url"


class BenchmarkCases(BaseModel):
    risky: int = 1
    safe: int = 1


class BenchmarkConfig(BaseModel):
    cases_per_incident: BenchmarkCases = Field(default_factory=BenchmarkCases)
    near_miss_safe_ratio: float = 0.5
    seed: int = 20260928
    output_dir: str = "data/benchmark"


class ConditionConfig(BaseModel):
    label: str
    description: str
    use_recall: bool
    use_reflect: bool
    use_feedback: bool


class ScoringConfig(BaseModel):
    positive_at_or_above: str = "medium"
    feedback_warmup_fraction: float = 0.5


class EvalConfig(BaseModel):
    split: SplitConfig = Field(default_factory=SplitConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    conditions: dict[str, ConditionConfig] = Field(default_factory=dict)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #
class Config(BaseModel):
    app: AppConfig
    llm: LlmConfig
    sources: SourcesConfig
    eval: EvalConfig


@lru_cache(maxsize=1)
def get_app_config() -> Config:
    """Load and cache every YAML config file."""
    return Config(
        app=AppConfig(**_load("app.yaml")),
        llm=LlmConfig(**_load("llm.yaml")),
        sources=SourcesConfig(**_load("sources.yaml")),
        eval=EvalConfig(**_load("eval.yaml")),
    )


def reload_config() -> Config:
    """Drop the cache and re-read from disk (used by tests and hot reload)."""
    get_app_config.cache_clear()
    from backend.settings import get_settings

    get_settings.cache_clear()
    return get_app_config()
