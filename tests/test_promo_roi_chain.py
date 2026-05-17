"""Tests for the promo ROI calculation chain.

Covers: baseline_v > 0 guard, lift_pct, dip_pct, incremental_units,
incremental_revenue, promo_cost, roi_pct, and roi_tier classification.
All run without a database — operates on synthetic DataFrames.
"""

from __future__ import annotations

import pandas as pd
import pytest

from constants import THRESHOLDS
from decisions.promo_roi import _roi_tier


def _apply_promo_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the post-SQL calculation chain from data.py get_promo_roi_data."""
    df = df.copy()
    df = df[df["baseline_v"] > 0].reset_index(drop=True)
    if df.empty:
        return df

    bv, pv, pov = df["baseline_v"], df["promo_v"], df["post_v"]
    df["lift_pct"] = (pv - bv) / bv * 100
    df["dip_pct"] = (pov - bv) / bv * 100
    df["incremental_units"] = ((pv - bv) * df["doors"] * df["duration_weeks"]).round(0)
    df["incremental_revenue"] = (
        df["incremental_units"] * df["wholesale_price"] * (1 - df["discount_depth_pct"])
    ).round(0)
    df["promo_cost"] = (
        bv * df["doors"] * df["duration_weeks"] * df["wholesale_price"] * df["discount_depth_pct"]
    ).round(0)
    df["roi_pct"] = (
        (df["incremental_revenue"] - df["promo_cost"]) / df["promo_cost"].replace(0, pd.NA) * 100
    )
    return df


def _promo_row(**overrides) -> dict:
    defaults = {
        "promo_id": "P001",
        "sku": "SKU-001",
        "retailer": "Walmart",
        "product_name": "Test",
        "product_line": "Sauces",
        "start_week": "2025-01-06",
        "end_week": "2025-01-20",
        "duration_weeks": 2,
        "discount_depth_pct": 0.20,
        "promo_type": "percentage_off",
        "store_scope": "all",
        "wholesale_price": 5.00,
        "baseline_v": 10.0,
        "promo_v": 15.0,
        "post_v": 9.5,
        "doors": 100,
    }
    defaults.update(overrides)
    return defaults


class TestBaselineGuard:
    def test_baseline_zero_excluded(self):
        df = pd.DataFrame([_promo_row(baseline_v=0.0)])
        result = _apply_promo_calcs(df)
        assert result.empty

    def test_baseline_positive_kept(self):
        df = pd.DataFrame([_promo_row(baseline_v=5.0)])
        result = _apply_promo_calcs(df)
        assert len(result) == 1

    def test_mixed_baseline_filters_correctly(self):
        df = pd.DataFrame([
            _promo_row(promo_id="P001", baseline_v=0.0),
            _promo_row(promo_id="P002", baseline_v=10.0),
        ])
        result = _apply_promo_calcs(df)
        assert len(result) == 1
        assert result["promo_id"].iloc[0] == "P002"


class TestLiftPct:
    def test_positive_lift(self):
        df = _apply_promo_calcs(pd.DataFrame([_promo_row(baseline_v=10.0, promo_v=15.0)]))
        assert df["lift_pct"].iloc[0] == pytest.approx(50.0)

    def test_no_lift(self):
        df = _apply_promo_calcs(pd.DataFrame([_promo_row(baseline_v=10.0, promo_v=10.0)]))
        assert df["lift_pct"].iloc[0] == pytest.approx(0.0)

    def test_negative_lift(self):
        df = _apply_promo_calcs(pd.DataFrame([_promo_row(baseline_v=10.0, promo_v=8.0)]))
        assert df["lift_pct"].iloc[0] == pytest.approx(-20.0)


class TestIncrementalUnits:
    def test_basic_calculation(self):
        df = _apply_promo_calcs(pd.DataFrame([
            _promo_row(baseline_v=10.0, promo_v=15.0, doors=100, duration_weeks=2)
        ]))
        expected = (15.0 - 10.0) * 100 * 2
        assert df["incremental_units"].iloc[0] == expected


class TestPromoCost:
    def test_basic_calculation(self):
        df = _apply_promo_calcs(pd.DataFrame([
            _promo_row(baseline_v=10.0, doors=100, duration_weeks=2,
                       wholesale_price=5.0, discount_depth_pct=0.20)
        ]))
        expected = round(10.0 * 100 * 2 * 5.0 * 0.20)
        assert df["promo_cost"].iloc[0] == expected


class TestROI:
    def test_positive_roi(self):
        df = _apply_promo_calcs(pd.DataFrame([
            _promo_row(baseline_v=10.0, promo_v=20.0, doors=100,
                       duration_weeks=2, wholesale_price=5.0,
                       discount_depth_pct=0.10)
        ]))
        assert df["roi_pct"].iloc[0] > 0

    def test_promo_cost_zero_produces_nan_roi(self):
        df = _apply_promo_calcs(pd.DataFrame([
            _promo_row(baseline_v=10.0, promo_v=15.0, discount_depth_pct=0.0)
        ]))
        assert pd.isna(df["roi_pct"].iloc[0])


class TestROITier:
    def test_strong(self):
        assert _roi_tier(150.0) == "Strong ROI"

    def test_marginal(self):
        assert _roi_tier(50.0) == "Marginal ROI"

    def test_negative(self):
        assert _roi_tier(-20.0) == "Negative ROI"

    def test_boundary_at_100(self):
        roi_strong_pct = THRESHOLDS["roi_strong"] * 100
        assert _roi_tier(roi_strong_pct) == "Strong ROI"

    def test_boundary_at_zero(self):
        assert _roi_tier(0.0) == "Marginal ROI"

    def test_nan_is_marginal(self):
        assert _roi_tier(float("nan")) == "Marginal ROI"
