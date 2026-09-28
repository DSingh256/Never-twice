"""Tests for the ablation's metrics aggregation (computed, never asserted)."""

from __future__ import annotations

import pytest

from backend.pipeline.ablation import _prf


def test_prf_perfect():
    m = _prf(tp=4, fp=0, fn=0, tn=6)
    assert m["accuracy"] == 1.0
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["false_positive_rate"] == 0.0


def test_prf_known_matrix():
    m = _prf(tp=3, fp=1, fn=2, tn=4)
    assert m["accuracy"] == pytest.approx(7 / 10)
    assert m["precision"] == pytest.approx(3 / 4)
    assert m["recall"] == pytest.approx(3 / 5)
    assert m["false_positive_rate"] == pytest.approx(1 / 5)
    assert 0 <= m["f1"] <= 1


def test_prf_empty_is_zero_not_crash():
    m = _prf(tp=0, fp=0, fn=0, tn=0)
    assert m["accuracy"] == 0.0
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0
