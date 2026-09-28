"""Single wrapper for every Hindsight call in the application.

Rule 5 of the brief: all Hindsight API differences live in THIS module, nowhere
else. Verified against hindsight-client 0.10.1 with a live smoke test
(`scripts/smoke.py hindsight`), which confirmed:

* `create_bank(bank_id=..., name=..., mission=...)` exists and is idempotent.
* `retain(bank_id, content, context, document_id, tags, metadata, ...)`;
  `metadata` must be Dict[str, str] (bools/ints raise pydantic ValidationError).
* `recall(bank_id, query, types, max_tokens, budget, tags, tags_match, ...)` -
  result items expose `scores` = {final, reranker, semantic, keyword} and `tags`.
* `reflect(bank_id, query, budget, context, max_tokens, response_schema, ...)`
  supports `response_schema` for structured output.
* Tag scoping: `tags_match="all"` + tags narrows scope; the production bank is
  polluted by nothing else because we tag every memory with `bank:nevertwice`.

The async variants (aretain/arecall/areflect) are used inside FastAPI handlers
per the client docs; sync variants are used from scripts.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from backend.schemas.pipeline import MemoryHit
from backend.settings import get_settings

logger = logging.getLogger(__name__)

# Tags used by Never Twice. Every memory in the production bank carries
# `bank:<bank_label>` so future scope changes stay possible.
TAG_BANK = "bank:nevertwice"
TAG_INCIDENT = "kind:incident"
TAG_FEEDBACK = "kind:feedback"
TAG_PR_OUTCOME = "kind:pr_outcome"


class HindsightUnavailableError(RuntimeError):
    """Raised when the Hindsight server cannot be reached or fails."""


def stringify_metadata(metadata: dict[str, Any] | None) -> dict[str, str]:
    """Hindsight MemoryItem.metadata is Dict[str, str]; coerce safely."""
    return {str(k): str(v) for k, v in (metadata or {}).items()}


class HindsightClient:
    """All Hindsight operations used by Never Twice, in one place."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._sync: Any = None
        self._async: Any = None

    # ------------------------------------------------------------------ #
    @property
    def bank_id(self) -> str:
        return self._settings.hindsight_bank_id

    def _get_sync(self):
        if self._sync is None:
            from hindsight_client import Hindsight

            self._sync = Hindsight(
                base_url=self._settings.hindsight_base_url,
                api_key=self._settings.hindsight_api_key or None,
                timeout=self._settings.hindsight_timeout_seconds,
            )
        return self._sync

    def _get_async(self):
        if self._async is None:
            from hindsight_client import Hindsight

            self._async = Hindsight(
                base_url=self._settings.hindsight_base_url,
                api_key=self._settings.hindsight_api_key or None,
                timeout=self._settings.hindsight_timeout_seconds,
            )
        return self._async

    async def aclose(self) -> None:
        if self._async is not None:
            try:
                await self._async.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._async = None

    # ------------------------------------------------------------------ #
    # Health / discovery
    # ------------------------------------------------------------------ #
    def _health_report(self, ok: bool, error: str | None = None, version: Any = None) -> dict[str, Any]:
        report: dict[str, Any] = {
            "ok": ok,
            "base_url": self._settings.hindsight_base_url,
            "bank_id": self.bank_id,
        }
        if version is not None:
            report["version"] = getattr(version, "api_version", None)
        if error:
            report["error"] = error
        return report

    async def ahealth(self) -> dict[str, Any]:
        """Probe Hindsight connectivity from an async context. Never raises.

        The sync client runs its own asyncio loop and explodes with
        'This event loop is already running' inside FastAPI, so async
        handlers must use the a* variants - this included.
        """
        try:
            version = await self._get_async().aget_version()
            return self._health_report(True, version=version)
        except Exception as exc:  # noqa: BLE001
            return self._health_report(False, error=f"{type(exc).__name__}: {exc}"[:300])

    def health(self) -> dict[str, Any]:
        """Probe Hindsight connectivity from sync contexts (scripts). Never raises."""
        try:
            version = self._get_sync().get_version()
            return self._health_report(True, version=version)
        except Exception as exc:  # noqa: BLE001
            return self._health_report(False, error=f"{type(exc).__name__}: {exc}"[:300])

    def ensure_bank(self) -> None:
        """Create the production bank if missing (idempotent).

        Verified against hindsight-client 0.10.1: BanksApi exposes
        list_banks()/create_or_update_bank(); the high-level `create_bank`
        helper is sync-only, so the async path re-checks existence directly.
        """
        client = self._get_sync()
        try:
            client.create_bank(
                bank_id=self.bank_id,
                name="Never Twice operational memory",
                mission=(
                    "Organizational memory of production incidents: root causes, "
                    "failed fixes, what finally worked, and engineer feedback. Used "
                    "to warn developers before they repeat a historically dangerous "
                    "change."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            # Bank likely already exists; verify by listing banks.
            try:
                banks = client.banks.list_banks()
                items = getattr(banks, "banks", None) or getattr(banks, "items", None) or []
                ids = {
                    (b.get("bank_id") or b.get("id"))
                    if isinstance(b, dict)
                    else (getattr(b, "bank_id", None) or getattr(b, "id", None))
                    for b in items
                }
                if self.bank_id not in ids:
                    raise HindsightUnavailableError(
                        f"bank '{self.bank_id}' missing and create_bank failed: {exc}"
                    )
            except HindsightUnavailableError:
                raise
            except Exception as exc2:  # noqa: BLE001
                raise HindsightUnavailableError(
                    f"could not ensure bank '{self.bank_id}': {exc} / {exc2}"
                ) from exc2

    async def aensure_bank(self) -> None:
        """Async variant of ensure_bank for FastAPI handlers."""
        client = self._get_async()
        try:
            banks = await client.banks.list_banks()
            items = getattr(banks, "banks", None) or getattr(banks, "items", None) or []
            ids = {
                (b.get("bank_id") or b.get("id"))
                if isinstance(b, dict)
                else (getattr(b, "bank_id", None) or getattr(b, "id", None))
                for b in items
            }
            if self.bank_id in ids:
                return  # already exists
        except Exception as exc:  # noqa: BLE001
            raise HindsightUnavailableError(f"bank listing failed: {exc}") from exc

        # Missing: create via the low-level API (async-safe).
        from hindsight_client_api.models import CreateBankRequest

        payload = CreateBankRequest(
            name="Never Twice operational memory",
            mission=(
                "Organizational memory of production incidents: root causes, "
                "failed fixes, what finally worked, and engineer feedback. Used "
                "to warn developers before they repeat a historically dangerous "
                "change."
            ),
        )
        try:
            await client.banks.create_or_update_bank(self.bank_id, payload)
        except Exception as exc:  # noqa: BLE001
            raise HindsightUnavailableError(f"bank creation failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Retain
    # ------------------------------------------------------------------ #
    def _fresh_sync(self):
        """A Hindsight client whose loop-bound resources are not shared.

        The cached sync client keeps aiohttp sessions alive across calls; when
        calls come from different threads or after temporary asyncio.run loops
        (eval workers), a session can end up bound to a dead/foreign loop and
        every later call dies with 'Timeout context manager should be used
        inside a task'. Scripts and workers use fresh clients; the long-lived
        FastAPI path uses the async singleton instead.
        """
        from hindsight_client import Hindsight as _H

        return _H(
            base_url=self._settings.hindsight_base_url,
            api_key=self._settings.hindsight_api_key or None,
            timeout=self._settings.hindsight_timeout_seconds,
        )

    def retain_memory(
        self,
        content: str,
        *,
        context: str,
        memory_kind: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        document_id: str | None = None,
        incident_ts: str | None = None,
    ) -> dict[str, Any]:
        """Retain one memory unit into the production bank. Sync variant."""
        client = self._fresh_sync()
        all_tags = [TAG_BANK, f"kind:{memory_kind}", *(tags or [])]
        try:
            result = client.retain(
                bank_id=self.bank_id,
                content=content,
                context=context,
                document_id=document_id,
                tags=all_tags,
                metadata=stringify_metadata(metadata),
                **({"timestamp": incident_ts} if incident_ts else {}),
            )
        finally:
            try:
                import asyncio

                asyncio.run(client.aclose())  # aclose is a coroutine
            except Exception:  # noqa: BLE001
                pass
        return {
            "items_count": getattr(result, "items_count", None),
            "operation_id": getattr(result, "operation_id", None),
        }

    async def aretain_memory(
        self,
        content: str,
        *,
        context: str,
        memory_kind: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """Async retain for use inside FastAPI handlers."""
        client = self._get_async()
        all_tags = [TAG_BANK, f"kind:{memory_kind}", *(tags or [])]
        result = await client.aretain(
            bank_id=self.bank_id,
            content=content,
            context=context,
            document_id=document_id,
            tags=all_tags,
            metadata=stringify_metadata(metadata),
        )
        return {
            "items_count": getattr(result, "items_count", None),
            "operation_id": getattr(result, "operation_id", None),
        }

    # ------------------------------------------------------------------ #
    # Recall
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalise_hits(response: Any) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        for item in getattr(response, "results", None) or []:
            try:
                hits.append(MemoryHit.from_hindsight(item))
            except Exception:  # noqa: BLE001
                logger.exception("failed to normalise recall result; skipping")
        return hits

    def recall(
        self,
        query: str,
        *,
        max_tokens: int = 4096,
        budget: str = "mid",
        tags: list[str] | None = None,
        tags_match: str = "any",
        types: list[str] | None = None,
    ) -> list[MemoryHit]:
        """Sync recall returning normalised MemoryHit objects.

        The sync client owns its own event loop via _run_async; its aiohttp
        pool is bound to whichever loop created it. Calling this from a thread
        while another loop is around (FastAPI, eval workers) can resurrect a
        foreign loop's pool - 'Timeout context manager should be used inside a
        task'. A fresh client per call is always safe; cost is one connection.
        """
        client = self._fresh_sync()
        try:
            response = client.recall(
                bank_id=self.bank_id,
                query=query,
                max_tokens=max_tokens,
                budget=budget,
                types=types,
                tags=tags,
                tags_match=tags_match,
            )
        finally:
            try:
                import asyncio

                asyncio.run(client.aclose())  # aclose is a coroutine
            except Exception:  # noqa: BLE001
                pass
        return self._normalise_hits(response)

    async def arecall(
        self,
        query: str,
        *,
        max_tokens: int = 4096,
        budget: str = "mid",
        tags: list[str] | None = None,
        tags_match: str = "any",
        types: list[str] | None = None,
    ) -> list[MemoryHit]:
        """Async recall returning normalised MemoryHit objects."""
        response = await self._get_async().arecall(
            bank_id=self.bank_id,
            query=query,
            max_tokens=max_tokens,
            budget=budget,
            types=types,
            tags=tags,
            tags_match=tags_match,
        )
        return self._normalise_hits(response)

    # ------------------------------------------------------------------ #
    # Reflect
    # ------------------------------------------------------------------ #
    def reflect(
        self,
        query: str,
        *,
        context: str | None = None,
        budget: str = "mid",
        max_tokens: int = 2048,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Sync reflect. Returns {text, based_on, structured_output}."""
        kwargs: dict[str, Any] = {}
        if response_schema is not None:
            kwargs["response_schema"] = response_schema
        result = self._get_sync().reflect(
            bank_id=self.bank_id,
            query=query,
            context=context,
            budget=budget,
            max_tokens=max_tokens,
            include_facts=True,
            **kwargs,
        )
        return {
            "text": getattr(result, "text", "") or "",
            "based_on": [
                getattr(f, "model_dump", lambda: {})()
                for f in (getattr(result, "based_on", None) or [])
            ],
            "structured_output": getattr(result, "structured_output", None),
            "usage": getattr(result, "usage", None),
        }

    async def areflect(
        self,
        query: str,
        *,
        context: str | None = None,
        budget: str = "mid",
        max_tokens: int = 2048,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Async reflect. Returns {text, based_on, structured_output}."""
        kwargs: dict[str, Any] = {}
        if response_schema is not None:
            kwargs["response_schema"] = response_schema
        result = await self._get_async().areflect(
            bank_id=self.bank_id,
            query=query,
            context=context,
            budget=budget,
            max_tokens=max_tokens,
            include_facts=True,
            **kwargs,
        )
        return {
            "text": getattr(result, "text", "") or "",
            "based_on": [
                getattr(f, "model_dump", lambda: {})()
                for f in (getattr(result, "based_on", None) or [])
            ],
            "structured_output": getattr(result, "structured_output", None),
            "usage": getattr(result, "usage", None),
        }

    # ------------------------------------------------------------------ #
    # Introspection for the Memory Atlas / stats endpoints
    # ------------------------------------------------------------------ #
    def graph(self, limit: int = 200) -> dict[str, Any]:
        try:
            result = self._get_sync().memory.get_graph(bank_id=self.bank_id)
            data = result.model_dump() if hasattr(result, "model_dump") else {}
            nodes = (data.get("nodes") or [])[:limit]
            links = (data.get("links") or data.get("edges") or [])[: limit * 3]
            return {"nodes": nodes, "links": links}
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph fetch failed: %s", exc)
            return {"nodes": [], "links": [], "error": str(exc)[:200]}

    def tags(self) -> list[str]:
        try:
            result = self._get_sync().memory.list_tags(bank_id=self.bank_id)
            return [str(t) for t in (getattr(result, "tags", None) or [])]
        except Exception as exc:  # noqa: BLE001
            logger.warning("tag listing failed: %s", exc)
            return []

    def list_memories(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            result = self._get_sync().list_memories(bank_id=self.bank_id, limit=limit)
            items = getattr(result, "items", None) or []
            return [
                {
                    "id": getattr(m, "id", None),
                    "text": getattr(m, "text", ""),
                    "fact_type": getattr(m, "fact_type", ""),
                    "document_id": getattr(m, "document_id", None),
                }
                for m in items
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory listing failed: %s", exc)
            return []


# --------------------------------------------------------------------------- #
_hindsight_singleton: HindsightClient | None = None


def get_hindsight() -> HindsightClient:
    """Process-wide Hindsight client singleton."""
    global _hindsight_singleton
    if _hindsight_singleton is None:
        _hindsight_singleton = HindsightClient()
    return _hindsight_singleton
