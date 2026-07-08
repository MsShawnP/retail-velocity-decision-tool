"""Tests for the promo ROI calculation chain.

Covers: baseline_v > 0 guard, lift_pct, dip_pct, incremental_units,
incremental_revenue, promo_cost, roi_pct, and roi_tier classification.
All run without a database — operates on synthetic DataFrames.
"""

from __future__ import annotations

import pandas as pd
import pytest

from calcs import apply_promo_calcs as _raw_apply_promo_calcs


def _apply_promo_calcs(df):
    result, _ = _raw_apply_promo_calcs(df)
    return result
from constants import THRESHOLDS
from decisions.promo_roi import _roi_tier


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
        "cogs_per_unit": 3.00,
        "margin_per_unit": 2.00,
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

    def test_exclusion_count_returned(self):
        df = pd.DataFrame([
            _promo_row(promo_id="P001", baseline_v=0.0),
            _promo_row(promo_id="P002", baseline_v=10.0),
        ])
        _, n_excluded = _raw_apply_promo_calcs(df)
        assert n_excluded == 1


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
    def test_markdown_charged_on_all_promo_units(self):
        # The markdown is the discount given on EVERY unit sold during the
        # promo (promo_v), not just the baseline units.
        df = _apply_promo_calcs(pd.DataFrame([
            _promo_row(baseline_v=10.0, promo_v=15.0, doors=100,
                       duration_weeks=2, wholesale_price=5.0,
                       discount_depth_pct=0.20)
        ]))
        expected = round(15.0 * 100 * 2 * 5.0 * 0.20)  # promo_v, not baseline_v
        assert df["promo_cost"].iloc[0] == expected


class TestIncrementalContribution:
    def test_nets_cogs_at_promo_price(self):
        df = _apply_promo_calcs(pd.DataFrame([
            _promo_row(baseline_v=10.0, promo_v=20.0, doors=100,
                       duration_weeks=2, wholesale_price=5.0,
                       discount_depth_pct=0.10, cogs_per_unit=3.0)
        ]))
        incr_units = (20.0 - 10.0) * 100 * 2            # 2000
        promo_price = 5.0 * (1 - 0.10)                  # 4.5
        expected = round(incr_units * (promo_price - 3.0))  # 2000 * 1.5 = 3000
        assert df["incremental_contribution"].iloc[0] == expected

    def test_falls_back_to_default_margin_without_cogs(self):
        from constants import PROMO_DEFAULT_GROSS_MARGIN
        row = _promo_row(baseline_v=10.0, promo_v=20.0, doors=100,
                         duration_weeks=2, wholesale_price=5.0,
                         discount_depth_pct=0.10)
        del row["cogs_per_unit"]
        del row["margin_per_unit"]
        df = _apply_promo_calcs(pd.DataFrame([row]))
        incr_units = (20.0 - 10.0) * 100 * 2
        promo_price = 5.0 * (1 - 0.10)
        unit_cost = 5.0 * (1 - PROMO_DEFAULT_GROSS_MARGIN)
        expected = round(incr_units * (promo_price - unit_cost))
        assert df["incremental_contribution"].iloc[0] == expected


class TestROI:
    def test_margin_based_positive_roi(self):
        # incr units 2000, promo_price 4.5, cogs 3.0 -> contribution 3000;
        # markdown 20*100*2*5*0.10 = 2000; roi = (3000-2000)/2000 = 50%.
        df = _apply_promo_calcs(pd.DataFrame([
            _promo_row(baseline_v=10.0, promo_v=20.0, doors=100,
                       duration_weeks=2, wholesale_price=5.0,
                       discount_depth_pct=0.10, cogs_per_unit=3.0)
        ]))
        assert df["roi_pct"].iloc[0] == pytest.approx(50.0)

    def test_margin_roi_below_gross_revenue_roi(self):
        # Netting COGS and charging markdown on all units must not inflate:
        # margin ROI is strictly below the old revenue-based ROI.
        row = _promo_row(baseline_v=10.0, promo_v=20.0, doors=100,
                         duration_weeks=2, wholesale_price=5.0,
                         discount_depth_pct=0.10, cogs_per_unit=3.0)
        df = _apply_promo_calcs(pd.DataFrame([row]))
        incr_units = (20.0 - 10.0) * 100 * 2
        promo_price = 5.0 * (1 - 0.10)
        old_revenue_roi = (
            (incr_units * promo_price - 10.0 * 100 * 2 * 5.0 * 0.10)
            / (10.0 * 100 * 2 * 5.0 * 0.10) * 100
        )
        assert df["roi_pct"].iloc[0] < old_revenue_roi

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
