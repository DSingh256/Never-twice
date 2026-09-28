"""Confidence computation.

Rule 4: confidence is COMPUTED from evidence, never asked from the LLM.

    confidence = w_e * evidence_factor
               + w_r * retrieval_factor
               + w_f * feedback_factor

* evidence_factor saturates with the number of supporting memories
  (1 memory is a hint, 5+ is a pattern).
* retrieval_factor is the mean normalized retrieval score of the evidence.
* feedback_factor rewards agreement with past engineer feedback and penalizes
  contradictions (e.g. raising an alert engineers previously marked a false
  positive for the same pattern).

All weights and the floor live in config/app.yaml (confidence block).
"""

from __future__ import annotations

from backend.config import get_app_config


def evidence_factor(evidence_count: int, saturation: int) -> float:
    """1 - exp decay saturating at `saturation` memories."""
    if evidence_count <= 0:
        return 0.0
    import math

    return min(1.0, 1.0 - math.exp(-1.8 * evidence_count / max(saturation, 1)))


def retrieval_factor(scores: list[float], cap: float = 1.1) -> float:
    """Mean retrieval score normalised to 0..1 (Hindsight final scores sit ~0..1.1)."""
    if not scores:
        return 0.0
    clipped = [min(s, cap) for s in scores]
    return min(1.0, sum(clipped) / (len(clipped) * cap))


def feedback_factor(
    feedback_items: list[dict],
    *,
    good_catch_support: float = 1.0,
    false_positive_penalty: float = -1.0,
) -> float:
    """Net feedback signal normalised to [-1, 1].

    `feedback_items` entries: {"verdict": "good_catch"|"false_positive", ...}
    A positive factor means past engineers validated similar alerts; negative
    means they flagged them as noise. Zero means no feedback exists yet.
    """
    if not feedback_items:
        return 0.0
    net = 0.0
    for item in feedback_items:
        if item.get("verdict") == "good_catch":
            net += good_catch_support
        elif item.get("verdict") == "false_positive":
            net += false_positive_penalty
    return max(-1.0, min(1.0, net / len(feedback_items)))


def compute_confidence(
    *,
    evidence_count: int,
    retrieval_scores: list[float],
    feedback_items: list[dict] | None = None,
) -> float:
    """Final 0..1 confidence. Deterministic, auditable, config-driven."""
    cfg = get_app_config().app.confidence
    w = cfg.normalised_weights()

    ev = evidence_factor(evidence_count, cfg.evidence_saturation)
    ret = retrieval_factor(retrieval_scores)
    fb_raw = feedback_factor(feedback_items or [])
    # Feedback in [-1,1] maps to [0,1]; absence of feedback is neutral 0.5, so a
    # fresh system is neither over- nor under-confident about its own memory.
    fb = (fb_raw + 1.0) / 2.0

    value = w.evidence * ev + w.retrieval * ret + w.feedback_agreement * fb
    return round(max(cfg.floor, min(1.0, value)), 4)
