#!/usr/bin/env python
"""Minimal smoke tests run BEFORE building on Hindsight or an LLM provider.

Usage:
    .venv/Scripts/python.exe scripts/smoke.py hindsight
    .venv/Scripts/python.exe scripts/smoke.py llm

Rule #5 of the build brief: verify the real API surface with a tiny live probe
before writing pipeline code that depends on it.
"""

from __future__ import annotations

import json
import os
import sys
import time

HINDSIGHT_URL = os.getenv("HINDSIGHT_URL", "http://127.0.0.1:8888")
SMOKE_BANK = os.getenv("SMOKE_BANK_ID", "nevertwice-smoke")


def hindsight_smoke() -> int:
    from hindsight_client import Hindsight

    print(f"[hindsight] connecting to {HINDSIGHT_URL}")
    client = Hindsight(base_url=HINDSIGHT_URL, timeout=300.0)

    print("[hindsight] GET /version ->", client.get_version())

    # 1. ensure a bank exists (bank creation is idempotent-ish via create_bank)
    try:
        client.create_bank(
            bank_id=SMOKE_BANK,
            name="Never Twice smoke",
            mission="Throwaway bank used to verify the Hindsight API surface.",
        )
        print(f"[hindsight] bank '{SMOKE_BANK}' created/ensured")
    except Exception as exc:  # already exists is fine
        print(f"[hindsight] create_bank raised (continuing): {type(exc).__name__}: {exc}")

    # 2. retain three distinct memories, each with its own tags
    memories = [
        {
            "content": (
                "Incident INC-SMOKE-1: an nginx worker_connections value was raised from "
                "1024 to 4096 during a traffic spike. File descriptor limits were not raised "
                "alongside it, so workers hit EMFILE and the edge returned 502s for 11 minutes."
            ),
            "tags": ["service:edge-proxy", "change_category:config"],
        },
        {
            "content": (
                "Failed fix for INC-SMOKE-1: bumping worker_connections again to 8192 made the "
                "outage worse because the fd ceiling was still the binding constraint."
            ),
            "tags": ["service:edge-proxy", "change_category:config", "outcome:failed-fix"],
        },
        {
            "content": (
                "What finally worked for INC-SMOKE-1: raising the systemd LimitNOFILE for the "
                "nginx unit to 65535 and reverting worker_connections to 2048."
            ),
            "tags": ["service:edge-proxy", "change_category:config", "outcome:successful-fix"],
        },
    ]
    for i, mem in enumerate(memories, start=1):
        t0 = time.time()
        res = client.retain(
            bank_id=SMOKE_BANK,
            content=mem["content"],
            context="Never Twice smoke test fixture",
            document_id=f"smoke-{i}",
            tags=mem["tags"],
            # NOTE: Hindsight MemoryItem.metadata is Dict[str, str] - non-string
            # values raise a pydantic ValidationError. All pipeline metadata is
            # stringified for this reason.
            metadata={"smoke": "true", "index": str(i)},
        )
        print(
            f"[hindsight] retain #{i} ok in {time.time() - t0:.1f}s "
            f"items={getattr(res, 'items_count', '?')}"
        )

    # 3. recall
    t0 = time.time()
    recall = client.recall(
        bank_id=SMOKE_BANK,
        query="nginx worker_connections raised without raising file descriptor limits",
        budget="mid",
        max_tokens=1024,
    )
    results = getattr(recall, "results", []) or []
    print(f"[hindsight] recall -> {len(results)} results in {time.time() - t0:.1f}s")
    for r in results[:3]:
        text = (getattr(r, "text", "") or "")[:110].replace("\n", " ")
        print(f"    - score={getattr(r, 'score', None)} id={getattr(r, 'id', None)} :: {text}")

    # 4. reflect
    t0 = time.time()
    reflect = client.reflect(
        bank_id=SMOKE_BANK,
        query=(
            "A pull request raises nginx worker_connections from 1024 to 8192. "
            "Has a change like this caused an incident before, and did the obvious fix work?"
        ),
        budget="low",
    )
    text = getattr(reflect, "text", "") or ""
    print(f"[hindsight] reflect -> {len(text)} chars in {time.time() - t0:.1f}s")
    print("    " + text[:600].replace("\n", "\n    "))

    # 5. stats
    try:
        stats = client.get_bank_stats(bank_id=SMOKE_BANK)
        print("[hindsight] stats ->", json.dumps(stats, indent=2, default=str)[:500])
    except Exception as exc:
        print(f"[hindsight] stats unavailable: {type(exc).__name__}: {exc}")

    client.close()

    ok = bool(results) and bool(text.strip())
    print(f"[hindsight] RESULT: {'PASS' if ok else 'PARTIAL'}")
    return 0 if ok else 1


def llm_smoke() -> int:
    """Probe the configured OpenAI-compatible LLM endpoint directly."""
    from openai import OpenAI

    provider = os.getenv("LLM_PROVIDER", "ollama")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
    model = os.getenv("LLM_MODEL") or "llama3.2:latest"
    api_key = os.getenv("LLM_API_KEY") or "not-needed"

    print(f"[llm] provider={provider} base_url={base_url} model={model}")
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=120.0)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Reply with JSON only."},
            {
                "role": "user",
                "content": 'Return {"status":"ok","risk":"high"} as raw JSON, nothing else.',
            },
        ],
        temperature=0,
    )
    content = resp.choices[0].message.content or ""
    print("[llm] raw response:", content[:300])
    try:
        parsed = json.loads(content.strip().strip("`").removeprefix("json").strip())
        print("[llm] parsed JSON:", parsed)
        print("[llm] RESULT: PASS")
        return 0
    except Exception as exc:
        print(f"[llm] RESULT: FAIL (not JSON: {exc})")
        return 1


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    codes = []
    if which in ("hindsight", "all"):
        codes.append(hindsight_smoke())
    if which in ("llm", "all"):
        codes.append(llm_smoke())
    return max(codes) if codes else 2


if __name__ == "__main__":
    raise SystemExit(main())
