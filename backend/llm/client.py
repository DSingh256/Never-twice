"""OpenAI-compatible LLM client.

Guarantees (rule 6 of the brief):
* every call validates output against a Pydantic schema,
* retries with exponential backoff on transient/parse failures,
* falls through a configurable model chain (config/llm.yaml),
* surfaces a clear `LlmCallError` when every attempt fails - it never crashes
  the pipeline silently and never fabricates a result.

Model names come from config/llm.yaml; endpoint and keys come from `.env`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.config import get_app_config
from backend.settings import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LlmCallError(RuntimeError):
    """Raised when every model in the chain failed to produce valid output."""


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a model reply.

    Models wrap JSON in code fences, prose, or stray text; we accept all of it.
    Model diffs also contain literal newlines INSIDE JSON string values (strict
    JSON requires \\n escapes) - the `strict=False` fallback accepts control
    characters inside strings, which rescues those replies instead of burning
    a model-chain fallback on a syntax technicality.
    """
    text = text.strip()
    # Strip ```json ... ``` fences.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Direct parse first (strict, then lenient about control chars in strings).
    try:
        json.loads(text)
        return text
    except Exception:
        pass
    try:
        json.loads(text, strict=False)
        return text
    except Exception:
        pass
    # Otherwise take the outermost {...} or [...] span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                continue
            try:
                json.loads(candidate, strict=False)
                return candidate
            except Exception:
                continue
    return text


class LlmClient:
    """Thin, honest wrapper over the OpenAI-compatible chat API."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._cfg = get_app_config().llm
        self._clients: dict[str, object] = {}

    # ------------------------------------------------------------------ #
    def _openai(self):
        """Lazily create the OpenAI client for the configured provider."""
        key = f"{self._settings.llm_provider}:{self._settings.resolved_llm_base_url}"
        if key not in self._clients:
            from openai import OpenAI

            self._clients[key] = OpenAI(
                base_url=self._settings.resolved_llm_base_url,
                api_key=self._settings.resolved_llm_api_key,
                timeout=self._settings.llm_timeout_seconds,
                max_retries=0,  # we handle retries ourselves with tenacity
            )
        return self._clients[key]

    def _task_config(self, task: str):
        return self._cfg.tasks.get(task)

    def _model_chain(self, task: str) -> list[str]:
        task_cfg = self._task_config(task)
        if task_cfg and task_cfg.models:
            return list(task_cfg.models)
        s = self._settings
        return [s.llm_model, s.llm_fallback_model]

    # ------------------------------------------------------------------ #
    @staticmethod
    def _schema_hint(schema: type[BaseModel]) -> str:
        """A compact JSON-schema hint injected into the system prompt."""
        js = schema.model_json_schema()
        # Drop noisy keys to keep prompts small.
        for k in ("title", "additionalProperties"):
            js.pop(k, None)
        for prop in js.get("properties", {}).values():
            prop.pop("title", None)
            for item in prop.get("anyOf", []):
                item.pop("title", None)
        return json.dumps(js, ensure_ascii=False)

    def _completion(self, model: str, system: str, user: str, task: str) -> str:
        task_cfg = self._task_config(task)
        defaults = self._cfg.defaults
        timeout = (task_cfg.timeout_seconds if task_cfg else None) or defaults.timeout_seconds
        response = self._openai().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=defaults.temperature,
            max_tokens=task_cfg.max_tokens if task_cfg else 2048,
            timeout=timeout,
        )
        return response.choices[0].message.content or ""

    def _attempt_once(self, model: str, system: str, user: str, task: str) -> str:
        """One completion with retries on transient errors only."""
        defaults = self._cfg.defaults

        @retry(
            retry=retry_if_exception_type((ConnectionError, TimeoutError)),
            stop=stop_after_attempt(defaults.max_attempts_per_model),
            wait=wait_exponential(
                multiplier=defaults.retry_backoff_seconds,
                max=defaults.retry_backoff_max_seconds,
            ),
            reraise=True,
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        def call() -> str:
            return self._completion(model, system, user, task)

        return call()

    # ------------------------------------------------------------------ #
    def structured(
        self,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        max_schema_retries: int = 2,
    ) -> tuple[T, dict]:
        """Run a task and validate output against `schema`.

        Walks the model chain; per model, retries schema failures a couple of
        times with a corrective nudge before moving on. Returns the validated
        model plus a metadata dict (model used, attempts made).
        """
        chain = self._model_chain(task)
        schema_hint = self._schema_hint(schema)
        full_system = (
            f"{system}\n\n"
            f"Respond with a single JSON object matching this schema. "
            f'Never invent facts; use JSON null for anything unknown.\nSchema: {schema_hint}'
        )
        last_error: Exception | None = None

        for model in chain:
            current_user = user
            for attempt in range(1, max_schema_retries + 2):
                try:
                    raw = self._attempt_once(model, full_system, current_user, task)
                    data = json.loads(_extract_json(raw))
                    validated = schema.model_validate(data)
                    return validated, {"model": model, "attempt": attempt, "raw_chars": len(raw)}
                except ValidationError as exc:
                    # Schema violations get a corrective nudge, then fall through.
                    last_error = exc
                    logger.warning(
                        "llm schema violation task=%s model=%s attempt=%s errors=%s",
                        task, model, attempt, exc.errors()[:3],
                    )
                    current_user = (
                        f"{user}\n\nYour previous reply failed schema validation: "
                        f"{exc.errors()[:3]}. Return ONLY corrected JSON."
                    )
                except Exception as exc:  # noqa: BLE001 - transport/parse/rate-limit
                    last_error = exc
                    logger.warning(
                        "llm call failure task=%s model=%s attempt=%s error=%s",
                        task, model, attempt, exc,
                    )
                    break  # this model is misbehaving; move to the next

        raise LlmCallError(
            f"All models failed for task '{task}'. Last error: {last_error}"
        )

    # ------------------------------------------------------------------ #
    def plain(self, task: str, system: str, user: str) -> str:
        """A plain-text completion with model-chain fallback (no schema)."""
        chain = self._model_chain(task)
        last_error: Exception | None = None
        for model in chain:
            try:
                return self._attempt_once(model, system, user, task)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("llm plain failure task=%s model=%s error=%s", task, model, exc)
        raise LlmCallError(f"All models failed for task '{task}'. Last error: {last_error}")

    def health_check(self) -> dict:
        """Probe the configured LLM endpoint honestly.

        Never raises; the result is surfaced verbatim by /api/health.
        """
        s = self._settings
        base = {
            "provider": s.llm_provider,
            "base_url": s.resolved_llm_base_url,
            "configured": s.llm_is_configured,
        }
        if not s.llm_is_configured:
            return {**base, "ok": False, "error": "no API key / base URL configured"}
        try:
            reply = self._completion(
                s.llm_model,
                "Reply with the single word: pong",
                "ping",
                "verdict_no_memory",
            )
            ok = "pong" in reply.lower()
            return {**base, "ok": ok, "model": s.llm_model, "reply": reply.strip()[:80]}
        except Exception as exc:  # noqa: BLE001
            return {**base, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
