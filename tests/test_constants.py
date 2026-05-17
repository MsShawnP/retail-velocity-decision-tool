"""Smoke tests for constants.py — palette, thresholds, decision lists."""

from constants import (
    DECISIONS,
    DECISION_TITLES,
    NAVY,
    PHYSICAL_RETAILERS,
    RETAILER_THRESHOLDS,
    THRESHOLDS,
)


def test_nine_decisions():
    assert len(DECISIONS) == 9


def test_every_decision_has_a_title():
    for d in DECISIONS:
        assert d in DECISION_TITLES, f"Missing title for: {d}"


def test_thresholds_are_numeric():
    for key, val in THRESHOLDS.items():
        assert isinstance(val, (int, float)), f"{key} is {type(val)}"


def test_retailer_thresholds_cover_physical():
    for r in PHYSICAL_RETAILERS:
        assert r in RETAILER_THRESHOLDS, f"Missing threshold for {r}"


def test_navy_is_hex():
    assert NAVY.startswith("#")
    assert len(NAVY) == 7
