#!/usr/bin/env python
"""Generate the eval benchmark from held-out incidents (M6).

Usage: .venv/Scripts/python.exe scripts/generate_benchmark.py
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

from backend.db.session import session_scope  # noqa: E402
from backend.pipeline.benchmark import generate_benchmark  # noqa: E402


def main() -> int:
    with session_scope() as session:
        report = generate_benchmark(session)
    print(json.dumps(report, indent=2))
    if report["cases"] == 0:
        print("FATAL: no benchmark cases were generated", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
