"""Tests for the production forecast calculation chain.

Covers: weekly_units, weekly_cases, seasonal_factor (clipping, NaN default),
forecast_4w_units, trend_pct, and the Accelerating/Decelerating/Stable status.
All run without a database — operates on synthetic DataFrames.
"""

from __future__ import annotations

import pandas as pd
import pytest

from constants import THRESHOLDS


def _apply_production_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the post-SQL calculation chain from data.py get_production_data."""
    df = df.copy()
    df["weekly_units"] = (df["sum_recent"] / 4).round(0)
    df["weekly_cases"] = (df["weekly_units"] / df["case_pack_qty"]).round(2)

    sf = df["sum_ly_forward"] / df["sum_ly_current"].replace(0, pd.NA)
    sf = sf.where(sf.notna(), 1.0).clip(lower=0.5, upper=2.0)
    df["seasonal_factor"] = sf
    df["forecast_4w_units"] = (df["weekly_units"] * sf * 4).round(0)
    df["forecast_4w_cases"] = (df["forecast_4w_units"] / df["case_pack_qty"]).round(2)

    trend = (
        (df["phys_v_recent"] - df["phys_v_prior"])
        / df["phys_v_prior"].replace(0, pd.NA)
        * 100
    )
    df["trend_pct"] = trend

    accel_pct = THRESHOLDS["production_trend_accel"] * 100
    decel_pct = THRESHOLDS["production_trend_decel"] * 100

    def status(t: float) -> str:
        if pd.isna(t):
            return "Stable"
        if t > accel_pct:
            return "Accelerating"
        if t < decel_pct:
            return "Decelerating"
        return "Stable"

    df["status"] = df["trend_pct"].apply(status)
    return df


def _prod_row(**overrides) -> dict:
    defaults = {
        "sku": "SKU-001",
        "product_name": "Test",
        "product_line": "Sauces",
        "case_pack_qty": 6,
        "doors": 100,
        "phys_v_recent": 5.0,
        "phys_v_prior": 5.0,
        "sum_recent": 2000,
        "sum_ly_current": 1800,
        "sum_ly_forward": 1800,
    }
    defaults.update(overrides)
    return defaults


class TestWeeklyUnits:
    def test_basic_division(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_recent=2000)]))
        assert df["weekly_units"].iloc[0] == 500.0

    def test_weekly_cases_with_pack_qty(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_recent=2400, case_pack_qty=12)]))
        assert df["weekly_units"].iloc[0] == 600.0
        assert df["weekly_cases"].iloc[0] == 50.0

    def test_weekly_cases_pack_qty_1(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_recent=100, case_pack_qty=1)]))
        assert df["weekly_cases"].iloc[0] == df["weekly_units"].iloc[0]


class TestSeasonalFactor:
    def test_ratio_1_to_1(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_ly_current=1000, sum_ly_forward=1000)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(1.0)

    def test_defaults_to_1_when_ly_current_zero(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_ly_current=0, sum_ly_forward=500)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(1.0)

    def test_defaults_to_1_when_both_nan(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_ly_current=None, sum_ly_forward=None)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(1.0)

    def test_clips_at_upper_bound(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_ly_current=100, sum_ly_forward=500)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(2.0)

    def test_clips_at_lower_bound(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_ly_current=1000, sum_ly_forward=100)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(0.5)

    def test_within_bounds_passes_through(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(sum_ly_current=1000, sum_ly_forward=1500)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(1.5)


class TestForecast:
    def test_forecast_uses_seasonal_factor(self):
        df = _apply_production_calcs(pd.DataFrame([
            _prod_row(sum_recent=400, case_pack_qty=1, sum_ly_current=1000, sum_ly_forward=1500)
        ]))
        weekly = 400 / 4
        sf = 1.5
        expected = round(weekly * sf * 4)
        assert df["forecast_4w_units"].iloc[0] == expected


class TestTrendPct:
    def test_stable_when_no_change(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(phys_v_recent=5.0, phys_v_prior=5.0)]))
        assert df["trend_pct"].iloc[0] == pytest.approx(0.0)
        assert df["status"].iloc[0] == "Stable"

    def test_accelerating(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(phys_v_recent=6.0, phys_v_prior=5.0)]))
        assert df["trend_pct"].iloc[0] == pytest.approx(20.0)
        assert df["status"].iloc[0] == "Accelerating"

    def test_decelerating(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(phys_v_recent=4.0, phys_v_prior=5.0)]))
        assert df["trend_pct"].iloc[0] == pytest.approx(-20.0)
        assert df["status"].iloc[0] == "Decelerating"

    def test_prior_zero_produces_nan_and_stable(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(phys_v_recent=5.0, phys_v_prior=0.0)]))
        assert pd.isna(df["trend_pct"].iloc[0])
        assert df["status"].iloc[0] == "Stable"

    def test_prior_nan_produces_stable(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(phys_v_recent=5.0, phys_v_prior=None)]))
        assert df["status"].iloc[0] == "Stable"

    def test_boundary_at_10_percent(self):
        df = _apply_production_calcs(pd.DataFrame([_prod_row(phys_v_recent=5.5, phys_v_prior=5.0)]))
        assert df["trend_pct"].iloc[0] == pytest.approx(10.0)
        assert df["status"].iloc[0] == "Stable"
