"""Tests for pitch export display-DataFrame builders (no DB needed)."""

from __future__ import annotations

import pandas as pd

from pitch_export import _display_shelf, _display_production, _display_rationalization, _display_launch


class TestDisplayShelf:
    def test_columns_present(self):
        df = pd.DataFrame([{
            "sku": "SKU-001", "product_name": "Test", "product_line": "Sauces",
            "current_v": 3.0, "trailing_v": 2.5, "trend_pct": 20.0, "status": "Safe",
        }])
        result = _display_shelf(df, threshold=2.0)
        assert "SKU" in result.columns
        assert "Status" in result.columns
        assert "Threshold" in result.columns
        assert result["Threshold"].iloc[0] == 2.0

    def test_rounding(self):
        df = pd.DataFrame([{
            "sku": "SKU-001", "product_name": "Test", "product_line": "Sauces",
            "current_v": 3.1415, "trailing_v": 2.7182, "trend_pct": 15.678, "status": "Safe",
        }])
        result = _display_shelf(df, threshold=2.0)
        assert result["Current Velocity"].iloc[0] == 3.14
        assert result["Trend %"].iloc[0] == 15.68


class TestDisplayProduction:
    def test_columns_present(self):
        df = pd.DataFrame([{
            "sku": "SKU-001", "product_name": "Test", "doors": 50,
            "weekly_units": 100.4, "weekly_cases": 8.3, "forecast_4w_cases": 33.2,
            "trend_pct": 5.0, "status": "Stable",
        }])
        result = _display_production(df)
        assert "4-Wk Forecast (cases)" in result.columns
        assert result["Weekly Units"].iloc[0] == 100
        assert result["Status"].iloc[0] == "Stable"


class TestDisplayRationalization:
    def test_columns_present(self):
        df = pd.DataFrame([{
            "sku": "SKU-001", "product_name": "Test",
            "velocity": 3.5, "margin_per_sw": 1.25, "weekly_total_margin": 62.5,
            "quadrant": "Winner",
        }])
        result = _display_rationalization(df)
        assert "Quadrant" in result.columns
        assert result["Velocity"].iloc[0] == 3.5


class TestDisplayLaunch:
    def test_columns_present(self):
        df = pd.DataFrame([{
            "sku": "SKU-NEW", "product_name": "New Item",
            "launch_date": "2025-06-01", "weeks_since": 12,
            "v_w14": 3.0, "v_current": 2.8, "status": "On Track",
        }])
        result = _display_launch(df)
        assert "Launch Date" in result.columns
        assert result["Status"].iloc[0] == "On Track"
