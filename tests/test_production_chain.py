"""Tests for the production forecast calculation chain.

Covers: weekly_units, weekly_cases, seasonal_factor (clipping, NaN default),
forecast_4w_units, trend_pct, and the Accelerating/Decelerating/Stable status.
All run without a database — operates on synthetic DataFrames.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from calcs import apply_production_calcs


def _apply(df: pd.DataFrame) -> pd.DataFrame:
    df, _ = apply_production_calcs(df)
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
        df = _apply(pd.DataFrame([_prod_row(sum_recent=2000)]))
        assert df["weekly_units"].iloc[0] == 500.0

    def test_weekly_cases_with_pack_qty(self):
        df = _apply(pd.DataFrame([_prod_row(sum_recent=2400, case_pack_qty=12)]))
        assert df["weekly_units"].iloc[0] == 600.0
        assert df["weekly_cases"].iloc[0] == 50.0

    def test_weekly_cases_pack_qty_1(self):
        df = _apply(pd.DataFrame([_prod_row(sum_recent=100, case_pack_qty=1)]))
        assert df["weekly_cases"].iloc[0] == df["weekly_units"].iloc[0]


class TestSeasonalFactor:
    def test_ratio_1_to_1(self):
        df = _apply(pd.DataFrame([_prod_row(sum_ly_current=1000, sum_ly_forward=1000)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(1.0)

    def test_defaults_to_1_when_ly_current_zero(self):
        df = _apply(pd.DataFrame([_prod_row(sum_ly_current=0, sum_ly_forward=500)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(1.0)

    def test_defaults_to_1_when_both_nan(self):
        df = _apply(pd.DataFrame([_prod_row(sum_ly_current=None, sum_ly_forward=None)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(1.0)

    def test_clips_at_upper_bound(self):
        df = _apply(pd.DataFrame([_prod_row(sum_ly_current=100, sum_ly_forward=500)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(2.0)

    def test_clips_at_lower_bound(self):
        df = _apply(pd.DataFrame([_prod_row(sum_ly_current=1000, sum_ly_forward=100)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(0.5)

    def test_within_bounds_passes_through(self):
        df = _apply(pd.DataFrame([_prod_row(sum_ly_current=1000, sum_ly_forward=1500)]))
        assert df["seasonal_factor"].iloc[0] == pytest.approx(1.5)


class TestForecast:
    def test_forecast_uses_seasonal_factor(self):
        df = _apply(pd.DataFrame([
            _prod_row(sum_recent=400, case_pack_qty=1, sum_ly_current=1000, sum_ly_forward=1500)
        ]))
        weekly = 400 / 4
        sf = 1.5
        expected = round(weekly * sf * 4)
        assert df["forecast_4w_units"].iloc[0] == expected


class TestSeasonalWindowAlignment:
    """The LY windows in get_production_data's SQL must be the exact 52-week
    (364-day) alias of the windows they scale. Weekly scans land on a 7-day
    grid aligned to the latest week, so:

        recent 4 weeks = days 0-27   -> ly_current must be days 364-391
        next 4 weeks   = days -28..-1 -> ly_forward must be days 336-363

    Guards two past regressions: 364-392/336-364 double-counted day 364 in
    both sums, and the 365-392/337-364 fix removed the overlap but sat one
    week too old — misassigning the year-ago week of the latest week (the
    seasonal peak when latest is late December) from ly_current into
    ly_forward, inflating the seasonal factor. The SQL is inline, so this
    inspects the source rather than executing the query.
    """

    @staticmethod
    def _window(name: str) -> tuple[int, int]:
        src = (
            Path(__file__).resolve().parent.parent / "app" / "data.py"
        ).read_text(encoding="utf-8")
        m = re.search(
            rf"BETWEEN (\d+) AND (\d+)\s+THEN d\.units_sold END\) AS {name}", src
        )
        assert m, f"could not locate the {name} window in app/data.py"
        return int(m.group(1)), int(m.group(2))

    def test_ly_current_is_exact_alias_of_recent_window(self):
        # recent = days 0-27; + 364 -> 364-391
        assert self._window("sum_ly_current") == (364, 391)

    def test_ly_forward_is_exact_alias_of_next_4_weeks(self):
        # next 4 weeks = days -28..-1; + 364 -> 336-363
        assert self._window("sum_ly_forward") == (336, 363)

    def test_windows_span_4_weeks_each_and_do_not_overlap(self):
        c_lo, c_hi = self._window("sum_ly_current")
        f_lo, f_hi = self._window("sum_ly_forward")
        assert c_hi - c_lo == 27  # 28 days inclusive = exactly 4 weekly scans
        assert f_hi - f_lo == 27
        assert f_hi < c_lo  # forward block strictly newer, no shared day
        assert c_lo - f_lo == 28  # contiguous: forward is current shifted 4 weeks


class TestTrendPct:
    def test_stable_when_no_change(self):
        df = _apply(pd.DataFrame([_prod_row(phys_v_recent=5.0, phys_v_prior=5.0)]))
        assert df["trend_pct"].iloc[0] == pytest.approx(0.0)
        assert df["status"].iloc[0] == "Stable"

    def test_accelerating(self):
        df = _apply(pd.DataFrame([_prod_row(phys_v_recent=6.0, phys_v_prior=5.0)]))
        assert df["trend_pct"].iloc[0] == pytest.approx(20.0)
        assert df["status"].iloc[0] == "Accelerating"

    def test_decelerating(self):
        df = _apply(pd.DataFrame([_prod_row(phys_v_recent=4.0, phys_v_prior=5.0)]))
        assert df["trend_pct"].iloc[0] == pytest.approx(-20.0)
        assert df["status"].iloc[0] == "Decelerating"

    def test_prior_zero_with_current_positive_is_accelerating(self):
        df = _apply(pd.DataFrame([_prod_row(phys_v_recent=5.0, phys_v_prior=0.0)]))
        assert pd.isna(df["trend_pct"].iloc[0])
        assert df["status"].iloc[0] == "Accelerating"

    def test_prior_zero_current_zero_is_stable(self):
        df = _apply(pd.DataFrame([_prod_row(phys_v_recent=0.0, phys_v_prior=0.0)]))
        assert df["status"].iloc[0] == "Stable"

    def test_prior_nan_with_current_positive_is_accelerating(self):
        df = _apply(pd.DataFrame([_prod_row(phys_v_recent=5.0, phys_v_prior=None)]))
        assert df["status"].iloc[0] == "Accelerating"

    def test_prior_nan_current_zero_is_stable(self):
        df = _apply(pd.DataFrame([_prod_row(phys_v_recent=0.0, phys_v_prior=None)]))
        assert df["status"].iloc[0] == "Stable"

    def test_boundary_at_10_percent(self):
        df = _apply(pd.DataFrame([_prod_row(phys_v_recent=5.5, phys_v_prior=5.0)]))
        assert df["trend_pct"].iloc[0] == pytest.approx(10.0)
        assert df["status"].iloc[0] == "Stable"
