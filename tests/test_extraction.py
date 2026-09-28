"""Extraction honesty tests: the LLM must not be able to invent facts.

These exercise the schema validators that enforce "null when not stated" and
the list-cleaning rules - without calling any model.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas.pipeline import ChangeFact, IncidentExtraction, RiskVerdict


def test_extraction_nulls_unstated_fields():
    e = IncidentExtraction(
        title="Database outage",
        org="null",
        service_or_component="unknown",
        severity="",
        trigger_change="n/a",
        root_cause=None,
    )
    assert e.org is None
    assert e.service_or_component is None
    assert e.severity is None
    assert e.trigger_change is None
    assert e.root_cause is None


def test_extraction_rejects_missing_title():
    # Empty title normalises to None, which then fails min_length.
    with pytest.raises(ValidationError):
        IncidentExtraction(title="", root_cause="x")
    with pytest.raises(ValidationError):
        IncidentExtraction(title="ab", root_cause="x")


def test_extraction_cleans_lists():
    e = IncidentExtraction(
        title="the title here",
        root_cause="r",
        symptoms="single string symptom",
        failed_fixes=["", "restart", None, "  rollback  "],
    )
    assert e.symptoms == ["single string symptom"]
    assert e.failed_fixes == ["restart", "rollback"]


def test_extraction_rejects_bad_confidence():
    with pytest.raises(ValidationError):
        IncidentExtraction(title="t", root_cause="r", extraction_confidence=1.5)


def test_change_fact_defaults_are_empty_not_invented():
    f = ChangeFact()
    assert f.files == []
    assert f.config_keys == []
    assert f.summary == ""
    assert f.change_category == "other"


def test_risk_verdict_confidence_bounds():
    v = RiskVerdict(level="high", confidence=0.5)
    assert v.evidence_count == 0
    assert v.learned_from_feedback == []
    with pytest.raises(ValidationError):
        RiskVerdict(level="high", confidence=2.0)
    with pytest.raises(ValidationError):
        RiskVerdict(level="catastrophic", confidence=0.5)
