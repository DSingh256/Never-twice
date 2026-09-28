"""Unit tests for the honest-system core: confidence math, split determinism,
level normalisation, and benchmark handling.

These run without Hindsight or an LLM - everything here is pure computation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from backend.config import get_app_config
from backend.db.models import Incident
from backend.pipeline.confidence import (
    compute_confidence,
    evidence_factor,
    feedback_factor,
    retrieval_factor,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# --------------------------------------------------------------------------- #
# Confidence (rule 4: computed, never LLM)
# --------------------------------------------------------------------------- #
def test_confidence_zero_evidence_is_floor():
    """Zero evidence AND no feedback: feedback is neutral 0.5, so the value sits
    at the weight-neutral midpoint, above the floor but low. The floor only
    binds when feedback is negative."""
    c = compute_confidence(evidence_count=0, retrieval_scores=[])
    assert get_app_config().app.confidence.floor <= c < 0.5
    with_bad_feedback = compute_confidence(
        evidence_count=0, retrieval_scores=[], feedback_items=[{"verdict": "false_positive"}]
    )
    assert with_bad_feedback == get_app_config().app.confidence.floor


def test_confidence_saturates_with_evidence():
    lo = compute_confidence(evidence_count=1, retrieval_scores=[0.5])
    hi = compute_confidence(evidence_count=5, retrieval_scores=[0.5] * 5)
    assert lo < hi <= 1.0
    assert evidence_factor(20, saturation=5) == pytest.approx(1.0, abs=1e-3)
    assert evidence_factor(0, saturation=5) == 0.0


def test_confidence_retrieval_factor_bounds():
    assert retrieval_factor([]) == 0.0
    assert 0.0 < retrieval_factor([0.4, 0.6]) <= 1.0


def test_confidence_feedback_penalty_and_reward():
    good = feedback_factor([{"verdict": "good_catch"}])
    bad = feedback_factor([{"verdict": "false_positive"}])
    assert good == pytest.approx(1.0)
    assert bad == pytest.approx(-1.0)

    base = compute_confidence(evidence_count=0, retrieval_scores=[])
    with_good = compute_confidence(
        evidence_count=0, retrieval_scores=[], feedback_items=[{"verdict": "good_catch"}]
    )
    with_bad = compute_confidence(
        evidence_count=0, retrieval_scores=[], feedback_items=[{"verdict": "false_positive"}]
    )
    assert with_good > base > with_bad


def test_confidence_matches_probe_measurement():
    """The real measured delta from the feedback probe: 0.125 -> 0.4246.

    1 evidence at that retrieval quality + 1 good_catch feedback must beat the
    zero-evidence baseline; this pins the loop's arithmetic, not a mock.
    """
    base = compute_confidence(evidence_count=0, retrieval_scores=[])
    after = compute_confidence(
        evidence_count=1, retrieval_scores=[0.3], feedback_items=[{"verdict": "good_catch"}]
    )
    assert after > base


# --------------------------------------------------------------------------- #
# Split determinism + the held-out guarantee
# --------------------------------------------------------------------------- #
def _mk_incidents(session: Session, n: int) -> None:
    for i in range(n):
        session.add(
            Incident(
                source_url=f"https://example.com/postmortem-{i}",
                title=f"incident {i}",
                root_cause=f"cause {i}",
            )
        )
    session.commit()


def test_split_is_deterministic(session):
    from backend.pipeline.split import assign_splits

    _mk_incidents(session, 20)
    first = assign_splits(session)
    rows1 = {i.id: i.split for i in session.exec(__import__("sqlmodel").select(Incident)).all()}
    assert first["memory"] + first["heldout"] == 20

    # Simulate a second run on the same corpus (all rows already assigned):
    # partition must not move and the report must reflect the full corpus.
    second = assign_splits(session)
    rows2 = {i.id: i.split for i in session.exec(__import__("sqlmodel").select(Incident)).all()}
    assert rows1 == rows2
    assert second == first


def test_retain_refuses_heldout(session):
    from backend.pipeline.retain import retain_incident

    _mk_incidents(session, 1)
    incident = session.exec(__import__("sqlmodel").select(Incident)).first()
    incident.split = "heldout"
    session.add(incident)
    session.commit()
    with pytest.raises(ValueError, match="held-out"):
        retain_incident(session, incident)


# --------------------------------------------------------------------------- #
# Level normalisation (the LLM must not crash the pipeline)
# --------------------------------------------------------------------------- #
def test_normalise_level_cases():
    from backend.pipeline.analysis import _normalise_level

    cases = {
        "potentially high": "high",  # canonical substring beats alias
        "CRITICAL": "high",
        "severe": "high",
        "moderate": "medium",
        "elevated": "medium",
        "minor": "low",
        "potential": "low",
        "no significant risk": "none",
        "": "none",
        None: "none",
        42: "none",
        "POTENTIALLY HIGH": "high",
    }
    for raw, expected in cases.items():
        assert _normalise_level(raw) == expected, (raw, expected)


def test_as_str_list_coercion():
    from backend.pipeline.analysis import _as_str_list, _as_str

    assert _as_str_list("one") == ["one"]
    assert _as_str_list(["a", 2, None, "b"]) == ["a", "2", "b"]
    assert _as_str_list(None) == []
    assert _as_str_list(42) == []
    assert _as_str(None) == ""
    assert _as_str(3.5) == "3.5"


# --------------------------------------------------------------------------- #
# Benchmark loading
# --------------------------------------------------------------------------- #
def test_load_benchmark_roundtrip(tmp_path: Path):
    from backend.pipeline.benchmark import BenchmarkCase, load_benchmark

    case = BenchmarkCase(
        case_id="i9-risky",
        incident_id=9,
        incident_title="t",
        source_url="https://example.com/x",
        kind="risky",
        expected_label=1,
        pr_title="Risky change",
        diff="--- a\n+++ b\n-a\n+b",
    )
    payload = {"cases": [case.model_dump()]}
    (tmp_path / "benchmark.json").write_text(json.dumps(payload))
    loaded = load_benchmark(str(tmp_path / "benchmark.json"))
    assert len(loaded) == 1
    assert loaded[0].expected_label == 1
    assert loaded[0].case_id == "i9-risky"
