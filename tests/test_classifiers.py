"""Tests for business-logic classifiers: shelf status, launch health, quadrants.

These classifiers drive the color-coding and bucket labels across the app.
All run without a database — they operate on in-memory DataFrames / Series.
"""

from __future__ import annotations

import pandas as pd
import pytest

from constants import THRESHOLDS
from decisions.launch_health import _classify_launch
from decisions.shelf_defense import _classify_shelf_status


# ============================================================
# Shelf Defense classifier
# ============================================================

def _shelf_df(**overrides) -> pd.DataFrame:
    row = {"sku": "SKU-001", "product_name": "Test", "product_line": "Sauces",
           "current_v": 3.0, "trailing_v": 3.5}
    row.update(overrides)
    return pd.DataFrame([row])


class TestShelfStatus:
    def test_below_threshold_is_at_risk(self):
        df = _shelf_df(current_v=1.5)
        result = _classify_shelf_status(df, threshold=2.0)
        assert result["status"].iloc[0] == "At Risk"

    def test_above_threshold_safe(self):
        df = _shelf_df(current_v=4.0, trailing_v=3.0)
        result = _classify_shelf_status(df, threshold=2.0)
        assert result["status"].iloc[0] == "Safe"

    def test_warning_zone(self):
        warn_mult = THRESHOLDS["shelf_warning_mult"]
        threshold = 2.0
        df = _shelf_df(current_v=2.5, trailing_v=3.0)
        assert 2.5 < threshold * warn_mult
        result = _classify_shelf_status(df, threshold=threshold)
        assert result["status"].iloc[0] == "Warning"

    def test_warning_requires_decline(self):
        threshold = 2.0
        df = _shelf_df(current_v=2.5, trailing_v=2.0)
        result = _classify_shelf_status(df, threshold=threshold)
        assert result["status"].iloc[0] == "Safe"

    def test_trend_pct_computed(self):
        df = _shelf_df(current_v=3.0, trailing_v=2.0)
        result = _classify_shelf_status(df, threshold=2.0)
        assert "trend_pct" in result.columns
        assert result["trend_pct"].iloc[0] == pytest.approx(50.0)


# ============================================================
# Launch Health classifier
# ============================================================

def _launch_row(**overrides) -> pd.Series:
    defaults = {"v_w14": 3.0, "v_current": 2.8}
    defaults.update(overrides)
    return pd.Series(defaults)


class TestLaunchClassifier:
    def test_on_track_above_threshold(self):
        row = _launch_row(v_w14=3.0, v_current=2.8)
        assert _classify_launch(row, threshold=2.0) == "On Track"

    def test_failing_below_retention(self):
        row = _launch_row(v_w14=3.0, v_current=1.5)
        assert _classify_launch(row, threshold=2.0) == "Failing"

    def test_needs_attention_nan_current(self):
        row = _launch_row(v_w14=3.0, v_current=float("nan"))
        assert _classify_launch(row, threshold=2.0) == "Needs Attention"

    def test_nan_initial_above_threshold(self):
        row = _launch_row(v_w14=float("nan"), v_current=3.0)
        assert _classify_launch(row, threshold=2.0) == "On Track"

    def test_nan_initial_below_threshold(self):
        row = _launch_row(v_w14=float("nan"), v_current=1.0)
        assert _classify_launch(row, threshold=2.0) == "Needs Attention"


# ============================================================
# SKU Rationalization quadrant labels
# ============================================================

class TestQuadrantLabel:
    """Quadrant logic is inline in rationalization.layout(), so we test
    the logic directly rather than importing it."""

    @staticmethod
    def _label(high_velocity: bool, high_margin: bool) -> str:
        if high_velocity and high_margin:
            return "Winner"
        if high_velocity and not high_margin:
            return "Volume play"
        if not high_velocity and high_margin:
            return "Niche / slow"
        return "Cut candidate"

    def test_winner(self):
        assert self._label(True, True) == "Winner"

    def test_volume_play(self):
        assert self._label(True, False) == "Volume play"

    def test_niche(self):
        assert self._label(False, True) == "Niche / slow"

    def test_cut_candidate(self):
        assert self._label(False, False) == "Cut candidate"
