#!/usr/bin/env python
"""Harvest postmortem article URLs into `config/sources.yaml`.

The danluu/post-mortems repository is an index of links, not the articles
themselves, so we need a discovered list of real article URLs to feed the
ingestion pipeline. This keeps `config/sources.yaml` auditable and regenerable
instead of hand-typed from memory.

Usage:
    .venv/Scripts/python.exe scripts/discover_sources.py            # write file
    .venv/Scripts/python.exe scripts/discover_sources.py --dry-run  # print only
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

INDEX_URL = "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md"
OUT_PATH = Path("config/sources.yaml")

# Domains that reliably serve readable postmortem prose. Chosen for signal:
# company engineering blogs with detailed root-cause write-ups.
PREFERRED_DOMAINS = (
    "github.blog",
    "github.com",
    "aws.amazon.com",
    "cloud.google.com",
    "engineering.fb.com",
    "about.gitlab.com",
    "gitlab.com",
    "blog.cloudflare.com",
    "www.cloudflare.com",
    "netflixtechblog.com",
    "medium.com",
    "slack.engineering",
    "engineering.salesforce.com",
    "blog.twitter.com",
    "eng.uber.com",
    "www.uber.com",
    "engineering.linkedin.com",
    "www.datadoghq.com",
    "www.elastic.co",
    "stripe.com",
    "shopify.engineering",
    "engineering.atspotify.com",
    "blogs.dropbox.com",
    "dropbox.tech",
    "code.facebook.com",
    "segment.com",
    "blog.discord.com",
    "discord.com",
    "blog.pagerduty.com",
    "postmortems.pagerduty.com",
    "www.honeycomb.io",
    "honeycomb.io",
    "labs.quansight.org",
    "www.troyhunt.com",
    "danluu.com",
    "opensource.googleblog.com",
    "sre.google",
    "blog.heroku.com",
    "www.heroku.com",
    "circleci.com",
    "gojek.io",
    "www.rackspace.com",
    "www.thousandeyes.com",
    "blog.thousandeyes.com",
    "cloud.google.com",
    "techblog.netflix.com",
    "www.theguardian.com",
    "blog.algolia.com",
    "www.algolia.com",
)

# Raw link targets that are noise for this pipeline.
SKIP_PATTERNS = re.compile(
    r"(twitter\.com|x\.com|news\.ycombinator|reddit\.com|/commit/|\.png|\.jpg|\.jpeg"
    r"|\.gif|\.zip|\.pdf|youtube\.com|linkedin\.com/share|web\.archive\.org/help"
    r"|github\.com/danluu|creativecommons\.org|opensource\.org/licenses)",
    re.IGNORECASE,
)

MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def domain_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_candidate(url: str) -> bool:
    if SKIP_PATTERNS.search(url):
        return False
    host = domain_of(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in PREFERRED_DOMAINS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=120)
    args = ap.parse_args()

    print(f"[discover] fetching index {INDEX_URL}")
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(INDEX_URL)
        resp.raise_for_status()
        index_md = resp.text

    seen: set[str] = set()
    entries: list[dict[str, str]] = []
    for title, url in MD_LINK.findall(index_md):
        url = url.rstrip("/.,;")
        if url in seen or not is_candidate(url):
            continue
        seen.add(url)
        title = " ".join(title.split())
        if not title or title.lower() in {"link", "here", "source", "post", "article"}:
            title = domain_of(url)
        entries.append({"url": url, "org": domain_of(url), "title_hint": title})

    entries = entries[: args.limit]
    print(f"[discover] {len(entries)} candidate sources after filtering {len(seen)} unique links")

    if args.dry_run:
        for e in entries[:40]:
            print("  ", e["url"])
        return 0

    # Preserve any hand-curated additions/overrides from an existing file.
    existing: dict[str, dict] = {}
    if OUT_PATH.exists():
        try:
            prev = yaml.safe_load(OUT_PATH.read_text(encoding="utf-8")) or {}
            for item in prev.get("sources", []) or []:
                if isinstance(item, dict) and item.get("url"):
                    existing[item["url"].rstrip("/.,;")] = item
        except Exception as exc:
            print(f"[discover] could not parse existing {OUT_PATH}: {exc}", file=sys.stderr)

    merged: list[dict] = []
    for e in entries:
        prev = existing.get(e["url"]) or {}
        merged.append({**e, **{k: v for k, v in prev.items() if k not in ("url",)}})

    # Keep curated entries that the index no longer surfaces.
    discovered = {m["url"] for m in merged}
    for url, item in existing.items():
        if url not in discovered:
            merged.append(item)

    payload = {
        "index_url": INDEX_URL,
        "notes": (
            "Generated by scripts/discover_sources.py from the danluu/post-mortems index. "
            "Edit `enabled` to control what the ingestion pipeline fetches."
        ),
        "sources": [
            {
                "url": item["url"],
                "org": item.get("org", domain_of(item["url"])),
                "title_hint": item.get("title_hint", ""),
                "enabled": item.get("enabled", True),
            }
            for item in merged
        ],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    print(f"[discover] wrote {len(payload['sources'])} sources to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
