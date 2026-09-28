"""Runtime settings.

Everything here comes from environment variables (loaded from `.env` in local
development). No secret is ever read from a config YAML file or hardcoded.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings for the whole backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_env: str = "local"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    database_url: str = "sqlite:///./data/app.db"
    public_backend_url: str = "http://127.0.0.1:8000"

    # --- LLM ---------------------------------------------------------------
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "llama3.2:latest"
    llm_fallback_model: str = "llama3:latest"
    llm_api_key: str = ""
    llm_temperature: float = 0.0
    llm_timeout_seconds: int = 180
    llm_max_retries: int = 3

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "qwen/qwen3-32b"

    # --- Hindsight ---------------------------------------------------------
    hindsight_base_url: str = "http://127.0.0.1:8888"
    hindsight_api_key: str = ""
    hindsight_bank_id: str = "nevertwice-prod"
    hindsight_timeout_seconds: float = 300.0
    hindsight_retain_async: bool = True

    # --- GitHub ------------------------------------------------------------
    github_webhook_secret: str = ""
    github_token: str = ""
    github_api_url: str = "https://api.github.com"

    # --- Feedback ----------------------------------------------------------
    feedback_signing_secret: str = "change-me-in-real-deployments"

    # --- Ingestion ---------------------------------------------------------
    ingest_fetch_timeout_seconds: int = 30
    ingest_user_agent: str = "NeverTwiceBot/0.1 (+https://github.com/never-twice)"

    # --- Derived -----------------------------------------------------------
    @field_validator("database_url")
    @classmethod
    def _default_sqlite_path(cls, v: str) -> str:
        return v or "sqlite:///./data/app.db"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_llm_base_url(self) -> str:
        """Groq and Ollama both speak the OpenAI API; pick by provider."""
        if self.llm_provider.lower() == "groq":
            return self.groq_base_url
        return self.llm_base_url

    @property
    def resolved_llm_api_key(self) -> str:
        if self.llm_provider.lower() == "groq":
            return self.groq_api_key
        # Local daemons accept any non-empty placeholder.
        return self.llm_api_key or "not-needed"

    @property
    def llm_is_configured(self) -> bool:
        """True when the selected provider has enough credentials to be usable."""
        if self.llm_provider.lower() == "groq":
            return bool(self.groq_api_key)
        return bool(self.llm_base_url)

    def llm_chain(self, task: str) -> list[str]:
        """Model fallback chain for a task, from config/llm.yaml when available."""
        from backend.config import get_app_config

        task_cfg = get_app_config().llm.tasks.get(task)
        if task_cfg and task_cfg.models:
            return list(task_cfg.models)
        return [self.llm_model, self.llm_fallback_model]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
