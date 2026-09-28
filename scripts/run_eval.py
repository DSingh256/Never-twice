#!/usr/bin/env python
"""Run the A/B/C ablation over the benchmark and print the measured table (M6).

Usage: .venv/Scripts/python.exe scripts/run_eval.py [--label hackathon] [--timeout 3600]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, ".")

from backend.db.session import session_scope  # noqa: E402
from backend.pipeline.ablation import run_ablation  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="cli")
    ap.add_argument("--timeout", type=int, default=3600, help="seconds before giving up")
    args = ap.parse_args()

    print(f"== running ablation (label={args.label}) ==", flush=True)
    started = time.time()
    with session_scope() as session:
        run = run_ablation(session, label=args.label)

    metrics = run.metrics or {}
    conds = metrics.get("conditions", {})

    print(f"\n== run {run.id}: {run.status} == {run.item_count} item(s), "
          f"{int(time.time() - started)}s")
    header = f"{'cond':5} {'scored':>6} {'acc':>6} {'prec':>6} {'rec':>6} {'f1':>6} {'fpr':>6} {'conf':>6} {'lat_ms':>7}"
    print(header)
    for cond in ("A", "B", "C"):
        m = conds.get(cond, {})
        conf = m.get("mean_confidence")
        lat = m.get("mean_latency_ms")
        print(
            f"{cond:5} {m.get('scored', 0):>6} {m.get('accuracy', 0):>6.2f} "
            f"{m.get('precision', 0):>6.2f} {m.get('recall', 0):>6.2f} "
            f"{m.get('f1', 0):>6.2f} {m.get('false_positive_rate', 0):>6.2f} "
            f"{('%.2f' % conf) if conf is not None else '-':>6} "
            f"{str(lat) if lat is not None else '-':>7}"
        )
    print(json.dumps({"errors": {c: conds.get(c, {}).get("errors") for c in ("A", "B", "C")}}, indent=1))

    if run.error:
        print(f"RUN ERROR: {run.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
