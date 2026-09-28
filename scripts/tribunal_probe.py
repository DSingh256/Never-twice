"""Live-fire the Tribunal: convene on the demo diff and poll to completion.

Usage: .venv/Scripts/python.exe scripts/tribunal_probe.py
Polls until all three witnesses testify; prints the A-vs-C delta.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"
DIFF = """diff --git a/infra/dns-resolver/terraform/main.tf b/infra/dns-resolver/terraform/main.tf
--- a/infra/dns-resolver/terraform/main.tf
+++ b/infra/dns-resolver/terraform/main.tf
@@ -14,9 +14,7 @@
-  min_healthy_hosts = 2
+  min_healthy_hosts = 0
"""

req = urllib.request.Request(
    f"{BASE}/api/tribunal",
    data=json.dumps(
        {"diff": DIFF, "pr_title": "Lower min healthy hosts to zero", "service": "dns-resolver"}
    ).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as r:
    created = json.load(r)
tid = created["tribunal_id"]
print("tribunal", tid, "convened")

deadline = time.time() + 300
last = None
while time.time() < deadline:
    time.sleep(4)
    with urllib.request.urlopen(f"{BASE}/api/tribunal/{tid}", timeout=30) as r:
        run = json.load(r)
    states = {w["condition"]: w["status"] for w in run["witnesses"]}
    if states != last:
        print(int(time.time() - (deadline - 300)), "s:", states)
        last = states
    if run["status"] != "running":
        break

print("== final ==")
print("status:", run["status"], "duration_s:", round((run["duration_ms"] or 0) / 1000, 1))
for w in run["witnesses"]:
    print(
        f"  {w['condition']} [{w['status']}] level={w['level']} "
        f"conf={w['confidence']} ev={w['evidence_count']} "
        f"lat={round((w['latency_ms'] or 0) / 1000, 1)}s err={w['error']}"
    )
d = run.get("delta")
if d:
    print(
        "delta: conf",
        f"{d['confidence_a']} -> {d['confidence_c']}",
        "| level", d["level_a"], "->", d["level_c"],
        "| rank_shift", d["level_rank_shift"],
    )
