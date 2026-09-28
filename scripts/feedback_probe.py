#!/usr/bin/env python
"""Prove the feedback loop changes verdicts (M4 acceptance test).

Flow:
 1. Analyze a dangerous diff -> record verdict A.
    (--reuse-baseline ID reuses an existing completed analysis instead of
    burning a new one; verdicts are only reused when explicitly asked for.)
 2. Submit feedback ("good_catch" by default, "false_positive" with a flag)
    against that analysis.
 3. Re-analyze the SAME diff -> record verdict B.
 4. Print A vs B: level, confidence, and the feedback that influenced B.

The verdicts MUST differ (or at minimum confidence must move) after feedback -
otherwise the loop is decorative. This script prints the real values; it never
fabricates a delta.

Note on polling: reflect is LLM-backed and can take minutes when the local
model has been unloaded, so we poll GET /api/analyses/{id} with a long
deadline instead of holding an SSE connection open.

Usage: .venv/Scripts/python.exe scripts/feedback_probe.py [--false-positive]
       [--reuse-baseline ANALYSIS_ID] [--timeout SECONDS]
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"

DANGEROUS_DIFF = """diff --git a/infra/dns-resolver/terraform/main.tf b/infra/dns-resolver/terraform/main.tf
index 3c4a9f2..8b1e7d0 100644
--- a/infra/dns-resolver/terraform/main.tf
+++ b/infra/dns-resolver/terraform/main.tf
@@ -14,9 +14,7 @@ resource "aws_autoscaling_group" "dns_resolver" {
   min_size             = 3
   max_size             = 12

-  # Resolver fleet needs headroom: keep at least 2 healthy hosts.
-  min_healthy_hosts = 2
+  # Trim fleet cost.
+  min_healthy_hosts = 0
 }"""


def sign(body: dict, secret: str) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def analyze(client: httpx.Client, diff: str, title: str, timeout_s: int) -> tuple[int, dict]:
    """POST /api/analyze then poll the detail endpoint until it finishes."""
    r = client.post(f"{BASE}/api/analyze", json={"diff": diff, "pr_title": title})
    r.raise_for_status()
    analysis_id = r.json()["analysis_id"]

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        d = client.get(f"{BASE}/api/analyses/{analysis_id}")
        d.raise_for_status()
        detail = d.json()
        if detail.get("status") in ("done", "failed"):
            return analysis_id, detail
        time.sleep(5)
    raise TimeoutError(f"analysis {analysis_id} did not finish within {timeout_s}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--false-positive", action="store_true",
                    help="submit feedback as false_positive instead of good_catch")
    ap.add_argument("--reuse-baseline", type=int, default=None, metavar="ID",
                    help="use an existing completed analysis as verdict A instead of running one")
    ap.add_argument("--timeout", type=int, default=900, metavar="SECONDS",
                    help="per-analysis poll deadline (default 900)")
    args = ap.parse_args()

    secret = os.getenv("FEEDBACK_SIGNING_SECRET", "change-me-in-real-deployments")
    fb_verdict = "false_positive" if args.false_positive else "good_catch"

    with httpx.Client(timeout=30.0) as client:
        if args.reuse_baseline is not None:
            print(f"== pass 1: reusing existing analysis {args.reuse_baseline} as verdict A ==")
            d = client.get(f"{BASE}/api/analyses/{args.reuse_baseline}")
            d.raise_for_status()
            v1 = d.json()
            aid = v1["id"]
            if v1.get("status") != "done":
                print(f"  FATAL: analysis {aid} status={v1.get('status')}; need a completed baseline")
                return 2
        else:
            print("== pass 1: analyze before feedback ==")
            aid, v1 = analyze(client, DANGEROUS_DIFF, "Trim resolver fleet cost", args.timeout)

        val1 = v1.get("verdict") or {}
        print(f"  analysis={aid} level={val1.get('level')} confidence={v1.get('confidence')} "
              f"evidence={v1.get('evidence_count')}")

        print(f"== submitting feedback: {fb_verdict} ==")
        # NOTE: the server rebuilds the signed body INCLUDING reviewer when
        # present, so reviewer must be inside the body we sign.
        body = {"analysis_id": aid, "verdict": fb_verdict, "reviewer": "probe-script",
                "note": ("This exact change was fine when we did it; the alert is noise."
                         if args.false_positive else
                         "Correct - this pattern broke us before; keep flagging it.")}
        r = client.post(f"{BASE}/api/feedback",
                        json={**body, "signature": sign(body, secret)})
        print("  ", r.status_code, r.json().get("message", r.text[:120]))
        r.raise_for_status()

        print("== pass 2: re-analyze after feedback ==")
        aid2, v2 = analyze(client, DANGEROUS_DIFF, "Trim resolver fleet cost (retry)", args.timeout)
        val2 = v2.get("verdict") or {}
        print(f"  analysis={aid2} level={val2.get('level')} confidence={v2.get('confidence')} "
              f"evidence={v2.get('evidence_count')}")

        print("\n== delta ==")
        print(f"  level:       {val1.get('level')} -> {val2.get('level')}")
        c1, c2 = v1.get("confidence"), v2.get("confidence")
        if c1 is not None and c2 is not None:
            print(f"  confidence:  {c1} -> {c2} (delta {round(c2 - c1, 4)})")
        infl = val2.get("learned_from_feedback") or []
        print(f"  feedback influenced verdict: {len(infl)} item(s)")
        for f in infl[:2]:
            print("    -", (f.get("note") or "")[:110])

        changed = (val1.get("level") != val2.get("level")) or (c1 != c2 and c1 is not None and c2 is not None)
        print("\nRESULT:", "VERDICT CHANGED after feedback" if changed
              else "NO CHANGE (loop ineffective - investigate)")
        return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
