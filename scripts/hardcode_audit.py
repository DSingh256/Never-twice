#!/usr/bin/env python
"""Hardcode audit: prove the product contains no fabricated data (M9).

Scans product code (backend + frontend + config) for the classic sample-data
smells: lorem ipsum, "example.com" fixtures, "sample"/"mock"/"fake"/"dummy"
data declarations, hardcoded seed rows. Runtime artefacts under data/, tests,
docs and this script itself are excluded - a doc may *describe* an example; the
product must not *ship* one.

Exit 0 = clean; exit 1 = findings printed.

Usage: .venv/Scripts/python.exe scripts/hardcode_audit.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = ["backend", "frontend/src", "config", "scripts"]
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".yaml", ".yml"}

# Patterns that indicate fabricated content. Each has an allowed-context regex;
# a match inside an allowed context does not count. `scope` limits a pattern to
# specific directories (backend Python legitimately ASSIGNS levels in pipeline
# logic; a hardcoded verdict would be sample data only in UI/config/fixture).
PATTERNS: list[tuple[str, re.Pattern, re.Pattern | None, str | None]] = [
    ("lorem ipsum", re.compile(r"lorem ipsum", re.I), None, None),
    (
        "example.com fixture",
        re.compile(r"https?://(?:www\.)?example\.(?:com|org)", re.I),
        re.compile(r"example\.com/postmortem-|example\.com/p-|example\.com/x\b"),
        None,
    ),
    (
        "sample data declaration",
        re.compile(r"(sample|dummy|fake|mock)[_-]?(data|rows?|records?)\b", re.I),
        re.compile(r"mocks\b"),
        None,
    ),
    (
        "placeholder verdict",
        re.compile(r"(level|confidence)\s*[:=]\s*[\"']?(high|medium|low|none)[\"']?\s*,?\s*$", re.I | re.M),
        re.compile(r"^\s*#|Literal|RiskLevel|enum|TYPE_CHECKING|verdict\[|raw\.get"),
        "frontend/src",
    ),
    (
        "seeded demo incident",
        re.compile(r"INSERT INTO incidents|seed_incidents|demo_incident", re.I),
        None,
        None,
    ),
    (
        "TODO/FIXME fake",
        re.compile(r"\b(TODO|FIXME)\b.*fake", re.I),
        None,
        None,
    ),
]

# Entire files that legitimately mention these words (docs-of-record, tests).
ALLOWED_FILES = {
    "scripts/hardcode_audit.py",
    "scripts/feedback_probe.py",  # demo driver: submits REAL feedback, its strings are notes
    "tests/test_extraction.py",
    "tests/test_pipeline.py",
    "tests/test_api_contracts.py",
    "tests/test_hardsplit_guarantee.py",
    "tests/test_eval_metrics.py",
}


def main() -> int:
    findings: list[tuple[str, int, str]] = []
    scanned = 0
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in ALLOWED_FILES or "node_modules" in rel or "__pycache__" in rel:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            for name, pattern, allowed, scope in PATTERNS:
                if scope is not None and not rel.startswith(scope):
                    continue
                for m in pattern.finditer(text):
                    line_no = text.count("\n", 0, m.start()) + 1
                    line = text.splitlines()[line_no - 1].strip()
                    if allowed and allowed.search(line):
                        continue
                    findings.append((f"{rel}:{line_no}", line_no, f"[{name}] {line[:110]}"))

    print(f"scanned {scanned} files under {', '.join(SCAN_DIRS)}")
    if findings:
        print(f"\n{len(findings)} FINDING(S):")
        for loc, _, desc in findings:
            print(f"  {loc}: {desc}")
        return 1
    print("clean: no fabricated-data patterns in product code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
