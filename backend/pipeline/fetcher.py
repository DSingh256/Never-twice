"""Fetch and clean postmortem articles.

Fetches are recorded, never hidden: every source ends up in the `source_fetches`
table with an HTTP status, a content hash and a clear error when it fails.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from backend.config import get_app_config
from backend.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class FetchedArticle:
    url: str
    http_status: int
    text: str
    content_hash: str
    clean_chars: int
    title: str


class FetchError(RuntimeError):
    pass


def _clean_html(html: str) -> tuple[str, str]:
    """Extract (title, readable_text) from an HTML page."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "form", "iframe"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Prefer <article>/<main> when present (blog engines wrap posts in them).
    root = None
    for selector in ("article", "main", '[role="main"]'):
        found = soup.select_one(selector)
        if found and len(found.get_text(strip=True)) > 400:
            root = found
            break
    root = root or soup.body or soup

    lines = []
    for block in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote"]):
        text = block.get_text(" ", strip=True)
        if not text:
            continue
        prefix = "\n" if block.name in ("h1", "h2", "h3", "h4") else ""
        lines.append(f"{prefix}{text}")

    text = "\n".join(lines)
    # Collapse the whitespace storms some CMSes produce.
    text = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    return title, text


def fetch_article(url: str) -> FetchedArticle:
    """Download and clean one article. Raises FetchError with a clear reason."""
    settings = get_settings()
    headers = {"User-Agent": settings.ingest_user_agent, "Accept": "text/html,application/xhtml+xml"}
    try:
        with httpx.Client(
            timeout=settings.ingest_fetch_timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        raise FetchError(f"network error: {type(exc).__name__}: {exc}") from exc

    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code}")

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type and content_type:
        raise FetchError(f"unsupported content-type: {content_type}")

    html = resp.text
    try:
        title, text = _clean_html(html)
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"parse error: {type(exc).__name__}: {exc}") from exc

    min_chars = get_app_config().app.ingest.min_clean_chars
    if len(text) < min_chars:
        raise FetchError(
            f"cleaned text too short ({len(text)} < {min_chars} chars) - likely boilerplate"
        )

    return FetchedArticle(
        url=url,
        http_status=resp.status_code,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        clean_chars=len(text),
        title=title[:300],
    )
