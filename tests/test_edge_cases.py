"""Edge-case and boundary tests for classifiers, data helpers, and display funcs.

These verify the app handles degenerate inputs gracefully: empty DataFrames,
NaN values, None arguments, and zero-row results.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from constants import CATEGORY_MAP, REGIONAL_CHAINS, THRESHOLDS
from data import retailer_clause
from decisions.shelf_defense import _classify_shelf_status
from decisions.launch_health import _classify_launch
from pitch_export import _display_shelf, _display_production, _display_rationalization, _display_launch


# ============================================================
# Classifier edge cases
# ============================================================

class TestShelfClassifierEdgeCases:
    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame(columns=["sku", "product_name", "product_line", "current_v", "trailing_v"])
        result = _classify_shelf_status(df, threshold=2.0)
        assert len(result) == 0
        assert "status" in result.columns

    def test_nan_current_velocity_does_not_crash(self):
        """NaN velocity doesn't trigger At Risk (NaN < threshold is False),
        but the classifier must not crash."""
        df = pd.DataFrame([{
            "sku": "X", "product_name": "Test", "product_line": "Sauces",
            "current_v": float("nan"), "trailing_v": 3.0,
        }])
        result = _classify_shelf_status(df, threshold=2.0)
        assert result["status"].iloc[0] in ("At Risk", "Warning", "Safe")

    def test_zero_trailing_velocity(self):
        """Zero trailing velocity shouldn't cause division error in trend_pct."""
        df = pd.DataFrame([{
            "sku": "X", "product_name": "Test", "product_line": "Sauces",
            "current_v": 3.0, "trailing_v": 0.0,
        }])
        result = _classify_shelf_status(df, threshold=2.0)
        assert "trend_pct" in result.columns
        # Should not raise; trend_pct may be inf or nan but no crash


class TestLaunchClassifierEdgeCases:
    def test_both_nan_returns_needs_attention(self):
        row = pd.Series({"v_w14": float("nan"), "v_current": float("nan")})
        result = _classify_launch(row, threshold=2.0)
        assert result == "Needs Attention"

    def test_zero_threshold(self):
        """Zero threshold shouldn't crash the classifier."""
        row = pd.Series({"v_w14": 3.0, "v_current": 2.0})
        result = _classify_launch(row, threshold=0.0)
        assert result in ("On Track", "Needs Attention", "Failing")


# ============================================================
# retailer_clause edge cases
# ============================================================

class TestRetailerClauseEdgeCases:
    def test_unknown_retailer_treated_as_single(self):
        """A retailer name not in REGIONAL_CHAINS gets a simple WHERE clause."""
        sql, params = retailer_clause("Nonexistent Store")
        assert sql == "s.retailer = %s"
        assert params == ["Nonexistent Store"]

    def test_all_retailers_returns_no_params(self):
        sql, params = retailer_clause("All Retailers")
        assert params == []
        assert "1=1" in sql


# ============================================================
# Category map consistency
# ============================================================

class TestCategoryMap:
    def test_all_product_lines_have_categories(self):
        """Every product line in the map resolves to a non-empty category."""
        for pl, cat in CATEGORY_MAP.items():
            assert isinstance(cat, str) and len(cat) > 0

    def test_three_categories(self):
        assert len(CATEGORY_MAP) == 3

    def test_category_values_are_unique(self):
        cats = list(CATEGORY_MAP.values())
        assert len(cats) == len(set(cats))


# ============================================================
# Display function edge cases (pitch export)
# ============================================================

class TestDisplayEdgeCases:
    def test_display_shelf_empty(self):
        df = pd.DataFrame(columns=[
            "sku", "product_name", "product_line", "current_v", "trailing_v", "trend_pct", "status"
        ])
        result = _display_shelf(df, threshold=2.0)
        assert len(result) == 0

    def test_display_production_empty(self):
        df = pd.DataFrame(columns=[
            "sku", "product_name", "doors", "weekly_units", "weekly_cases",
            "forecast_4w_cases", "trend_pct", "status"
        ])
        result = _display_production(df)
        assert len(result) == 0

    def test_display_rationalization_empty(self):
        df = pd.DataFrame(columns=[
            "sku", "product_name", "velocity", "margin_per_sw",
            "weekly_total_margin", "quadrant"
        ])
        result = _display_rationalization(df)
        assert len(result) == 0

    def test_display_launch_empty(self):
        df = pd.DataFrame(columns=[
            "sku", "product_name", "launch_date", "weeks_since",
            "v_w14", "v_current", "status"
        ])
        result = _display_launch(df)
        assert len(result) == 0


# ============================================================
# get_category_benchmark error handling
# ============================================================

class TestCategoryBenchmarkGraceful:
    """The benchmark function must not crash when the table doesn't exist."""

    def test_returns_dataframe_on_table_missing(self):
        """Simulate the table not existing — function should return df with NA cols."""
        with (
            patch("data.get_latest_week", return_value="2025-03-15"),
            patch("data.get_conn") as mock_conn,
        ):
            cursor = MagicMock()
            conn_obj = MagicMock()
            conn_obj.cursor.return_value = cursor
            mock_conn.return_value.__enter__ = lambda s: conn_obj

            # First call: Cinderhaven data (returns a simple df)
            ch_df = pd.DataFrame([
                {"product_line": "Artisan Sauces", "cinderhaven_avg": 6.5},
            ])

            with patch("pandas.read_sql", side_effect=[ch_df, Exception("relation does not exist")]):
                from data import get_category_benchmark
                result = get_category_benchmark.__wrapped__("Walmart")

            assert not result.empty
            assert "category_avg" in result.columns

    def test_returns_empty_when_no_cinderhaven_data(self):
        """If Cinderhaven has no data for a retailer, return empty."""
        with (
            patch("data.get_latest_week", return_value="2025-03-15"),
            patch("data.get_conn") as mock_conn,
        ):
            conn_obj = MagicMock()
            mock_conn.return_value.__enter__ = lambda s: conn_obj

            empty_df = pd.DataFrame(columns=["product_line", "cinderhaven_avg"])
            with patch("pandas.read_sql", return_value=empty_df):
                from data import get_category_benchmark
                result = get_category_benchmark.__wrapped__("Nonexistent Retailer")

            assert result.empty
