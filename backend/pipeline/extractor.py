"""LLM extraction of structured incidents from postmortem articles.

The schema (backend/schemas/pipeline.IncidentExtraction) forbids invention:
every unknown field must be null/empty, and extraction_confidence reflects how
much of the article actually supports the result. Invalid output is retried with
a corrective nudge, then falls back to the next model (backend/llm/client).
"""

from __future__ import annotations

import logging

from backend.llm.client import LlmCallError, LlmClient
from backend.schemas.pipeline import IncidentExtraction

logger = logging.getLogger(__name__)

# Long articles are front-loaded; feeding 60k chars to a local 3B model wastes
# minutes without adding recall. Truncation is disclosed in the DB metadata.
MAX_ARTICLE_CHARS = 14000

SYSTEM_PROMPT = """You extract structured incident data from published postmortems.

Rules:
- Use ONLY information stated in the article. If a field is not stated, use null
  (or an empty list). NEVER guess, infer or invent details.
- "trigger_change" is the change that started the incident (a config edit, a
  deploy, a migration, a dependency update, a capacity change...).
- "precursor_signature" is a one-sentence description of the change pattern that
  preceded the incident, ONLY if the article supports one.
- "change_category" is exactly one of: config, deploy, migration, dependency,
  capacity, other.
- "failed_fixes" lists attempted fixes that did NOT work (verbatim-ish, short).
- "successful_fix" is what finally resolved it, or null if unstated.
- extraction_confidence (0..1) is your honest estimate of how much of the article
  supports these fields."""


def extract_incident(
    article_text: str, source_url: str, org: str
) -> tuple[IncidentExtraction, dict]:
    """Extract one incident from cleaned article text.

    Returns (extraction, meta) where meta records which model produced it.
    Raises LlmCallError when every model in the chain fails.
    """
    client = LlmClient()
    truncated = article_text[:MAX_ARTICLE_CHARS]
    user = (
        f"Source URL: {source_url}\n"
        f"Organization (from domain): {org}\n\n"
        f"Article text:\n\n{truncated}\n\n"
        "Extract the incident as JSON per the schema."
    )
    extraction, meta = client.structured(
        task="extraction",
        system=SYSTEM_PROMPT,
        user=user,
        schema=IncidentExtraction,
    )
    logger.info(
        "extracted incident from %s (model=%s attempt=%s confidence=%.2f)",
        source_url, meta.get("model"), meta.get("attempt"), extraction.extraction_confidence,
    )
    return extraction, meta


__all__ = ["extract_incident", "LlmCallError", "MAX_ARTICLE_CHARS"]
