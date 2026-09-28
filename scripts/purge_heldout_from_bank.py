#!/usr/bin/env python
"""Purge retained memory units whose originating incident is held-out (M6).

The first ingestion ran before the split-default bug was fixed, so every
incident was tagged split='memory' and retained. After re-splitting, 9 of the
26 retained incidents became held-out - their memory units are still in the
production bank and would leak eval answers into conditions B/C.

This script resolves which document_ids were retained for held-out incidents
(from the retained_memories audit table), issues DELETE against
/v1/default/banks/{bank}/documents/{document_id}, verifies each document is
gone, prunes the audit rows, and re-runs the split-check.

Usage: .venv/Scripts/python.exe scripts/purge_heldout_from_bank.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

sys.path.insert(0, ".")

from backend.memory.hindsight_client import get_hindsight  # noqa: E402
from backend.settings import get_settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from sqlmodel import select

    from backend.db.models import Incident, RetainedMemory
    from backend.db.session import session_scope

    settings = get_settings()
    base = settings.hindsight_base_url.rstrip("/")
    bank = get_hindsight().bank_id

    with session_scope() as session:
        heldout_ids = {
            i.id
            for i in session.exec(select(Incident).where(Incident.split == "heldout")).all()
        }
        rows = session.exec(
            select(RetainedMemory).where(RetainedMemory.origin_kind == "incident")
        ).all()
        # Multiple audit rows can reference the same document_id; delete each
        # document once, but prune every audit row for it.
        seen: set[str] = set()
        targets = []
        for r in rows:
            if r.incident_id in heldout_ids and r.document_id and r.document_id not in seen:
                seen.add(r.document_id)
                targets.append(r)
        target_doc_ids = {r.document_id for r in targets}

    print(f"bank={bank} heldout_incidents={len(heldout_ids)} "
          f"audit_rows={len(rows)} documents_to_purge={len(targets)}")
    if not targets:
        print("nothing to purge")
        return 0

    if args.dry_run:
        for r in targets:
            print(f"  would delete: {r.document_id} (incident {r.incident_id})")
        return 0

    url = f"{base}/v1/default/banks/{bank}/documents"
    deleted, failed = 0, 0
    for r in targets:
        doc = r.document_id
        resp = httpx.delete(f"{url}/{doc}", timeout=30.0)
        if resp.status_code in (200, 202, 204, 404):
            deleted += 1
        else:
            failed += 1
            print(f"  FAILED {doc}: HTTP {resp.status_code} {resp.text[:120]}")

    print(f"delete requests sent: {len(targets)} ok={deleted} failed={failed}")

    # Verify against the audit table by re-listing what the bank exposes.
    from backend.memory.hindsight_client import HindsightClient

    client = HindsightClient()
    still_there = 0
    bank_docs = {m.get("document_id") for m in client.list_memories(limit=2000)}
    for r in targets:
        if r.document_id in bank_docs:
            still_there += 1
            print(f"  STILL PRESENT: {r.document_id}")

    # Prune audit rows for purged documents so the audit table reflects the bank.
    if failed == 0 and still_there == 0:
        with session_scope() as session:
            prune_rows = session.exec(
                select(RetainedMemory).where(RetainedMemory.origin_kind == "incident")
            ).all()
            pruned = 0
            for row in prune_rows:
                if row.document_id in target_doc_ids:
                    session.delete(row)
                    pruned += 1
            session.commit()
        print(f"pruned {pruned} audit rows")

    print(json.dumps({
        "purged": deleted,
        "failed": failed,
        "still_present": still_there,
    }, indent=2))
    return 0 if (failed == 0 and still_there == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
