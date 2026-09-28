#!/usr/bin/env python
"""End-to-end analysis probe against the local backend.

Posts a real config-change diff (the kind the ingested AWS EC2 DNS incident
warns about) to /api/analyze, streams the SSE steps, prints the verdict.
Run only after ingestion has populated memory.

Usage: .venv/Scripts/python.exe scripts/analyze_probe.py
"""

from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"

# A minimum-healthy-hosts style config change: the exact pattern that broke
# EC2 DNS in the ingested AWS postmortem. Real diff shape, real values.
DIFF = """diff --git a/infra/dns-resolver/terraform/main.tf b/infra/dns-resolver/terraform/main.tf
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


def main() -> int:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{BASE}/api/analyze",
            json={"diff": DIFF, "pr_title": "Trim resolver fleet cost", "repo": "infra/dns-resolver"},
        )
        if r.status_code != 200:
            print("submit failed:", r.status_code, r.text)
            return 1
        data = r.json()
        analysis_id = data["analysis_id"]
        print(f"submitted -> analysis_id={analysis_id}\n")

        verdict_event = None
        with httpx.stream("GET", f"{BASE}/api/analyze/{analysis_id}/stream", timeout=300.0) as stream:
            for line in stream.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                if payload.get("step"):
                    print(
                        f"  [{payload['step']}] {payload['status']}: {payload['message'][:110]}"
                        f" ({payload.get('duration_ms')}ms)"
                    )
                if payload.get("status") in ("done", "failed") and "verdict" in payload:
                    verdict_event = payload
                if payload.get("status") == "failed" and payload.get("step") == "error":
                    print("  ANALYSIS FAILED:", payload.get("message"))
                    return 1

        if verdict_event:
            v = verdict_event.get("verdict") or {}
            print("\nVERDICT")
            print("  level:      ", v.get("level"))
            print("  confidence: ", verdict_event.get("confidence"))
            print("  evidence:   ", verdict_event.get("evidence_count"))
            print("  rationale:  ", (v.get("rationale") or "")[:400])
            for m in (v.get("matched_incidents") or [])[:3]:
                print("  match:      ", (m.get("title") or m.get("why_similar") or "")[:110])
        return 0


if __name__ == "__main__":
    sys.exit(main())
