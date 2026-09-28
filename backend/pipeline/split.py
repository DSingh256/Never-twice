"""Seeded train/held-out split.

The split is a pure function of the incident rows + config, so re-running it is
idempotent and auditable. Only `memory` incidents are ever retained into the
production Hindsight bank; held-out ones exist solely for the evaluation harness.
"""

from __future__ import annotations

import hashlib
import random

from sqlmodel import Session, select

from backend.config import get_app_config
from backend.db.models import Incident


def assign_splits(session: Session) -> dict[str, int]:
    """Assign split='memory'|'heldout' to every incident without one.

    Deterministic: incidents are ordered by the configured key, then a seeded
    RNG picks the held-out set. Re-running with the same config and corpus
    produces the same partition. Incidents that already have a split keep it
    (so the memory bank and the eval set never silently shift).
    """
    cfg = get_app_config().eval.split
    incidents = session.exec(select(Incident)).all()
    order_key = {
        "source_url": lambda i: i.source_url,
        "id": lambda i: str(i.id),
    }.get(cfg.order_by, lambda i: i.source_url)

    pending = [i for i in incidents if not i.split]
    pending.sort(key=order_key)

    rng = random.Random(cfg.seed)
    heldout_count = round(len(pending) * cfg.heldout_ratio)
    # Draw indices instead of shuffling rows: same result, clearer intent.
    heldout_indices = set(rng.sample(range(len(pending)), heldout_count)) if pending else set()

    counts = {"memory": 0, "heldout": 0}
    for idx, incident in enumerate(pending):
        incident.split = "heldout" if idx in heldout_indices else "memory"
        counts[incident.split] += 1
        session.add(incident)
    session.commit()

    # Include already-assigned rows in the report.
    for incident in incidents:
        if incident.split:
            counts.setdefault(incident.split, 0)
    return counts
