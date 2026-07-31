"""Tests for get_portfolio_summary — mocks all underlying data functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


EXPECTED_KEYS = {
    "latest_week",
    "total_skus",
    "total_retailers",
    "total_doors",
    "total_product_lines",
    "weekly_units",
    "forecast_4w_cases",
    "shelf_at_risk",
    "shelf_warning",
    "shelf_at_risk_revenue",
    "prod_accelerating",
    "prod_decelerating",
    "prod_stable",
    "launches_total",
    "launches_on_track",
    "launches_failing",
    "launches_attention",
    "total_weekly_margin",
}


def _fake_prod_df():
    return pd.DataFrame([
        {"sku": "A", "weekly_units": 100, "forecast_4w_cases": 40, "status": "Accelerating"},
        {"sku": "B", "weekly_units": 200, "forecast_4w_cases": 80, "status": "Stable"},
        {"sku": "C", "weekly_units": 50, "forecast_4w_cases": 20, "status": "Decelerating"},
    ])


def _fake_shelf_df():
    return pd.DataFrame([
        {"sku": "A", "current_v": 1.5, "trailing_v": 3.0},
        {"sku": "B", "current_v": 4.0, "trailing_v": 5.0},
    ])


def _fake_launch_df():
    return pd.DataFrame([
        {"v_w14": 3.0, "v_current": 3.0, "weeks_since_launch": 10},
        {"v_w14": 2.5, "v_current": 1.0, "weeks_since_launch": 20},
    ])


def _fake_rat_df():
    return pd.DataFrame([
        {"sku": "A", "weekly_total_margin": 500.0, "revenue_per_sw": 20.0, "doors": 10},
        {"sku": "B", "weekly_total_margin": 300.0, "revenue_per_sw": 15.0, "doors": 10},
    ])


@pytest.fixture()
def portfolio_summary():
    with (
        # get_portfolio_summary serves a baked JSON snapshot when present, which
        # pre-empts the mocked data seams below. Force the computation path so the
        # aggregation logic is what's exercised.
        patch("data._load_baked_json", return_value=None),
        patch("data.get_conn") as mock_conn,
        patch("data.get_latest_week", return_value="2025-03-15"),
        patch("data.get_production_data", return_value=_fake_prod_df()),
        patch("data.get_shelf_defense_data", return_value=_fake_shelf_df()),
        patch("data.get_launch_data", return_value=_fake_launch_df()),
        patch("data.get_rationalization_data", return_value=_fake_rat_df()),
        patch("data.get_product_lines", return_value=["Condiments", "Sauces"]),
    ):
        cursor = MagicMock()
        cursor.fetchone.return_value = (150,)
        mock_conn.return_value.__enter__ = lambda s: MagicMock(cursor=lambda: cursor)
        mock_conn.return_value.__exit__ = lambda s, *a: None

        from data import get_portfolio_summary
        return get_portfolio_summary.__wrapped__()


class TestPortfolioSummaryShape:
    def test_all_keys_present(self, portfolio_summary):
        assert set(portfolio_summary.keys()) == EXPECTED_KEYS

    def test_all_values_are_int_or_str(self, portfolio_summary):
        for key, val in portfolio_summary.items():
            assert isinstance(val, (int, str)), f"{key} is {type(val)}"


class TestPortfolioSummaryCounts:
    def test_total_skus_from_production(self, portfolio_summary):
        assert portfolio_summary["total_skus"] == 3

    def test_production_status_counts(self, portfolio_summary):
        assert portfolio_summary["prod_accelerating"] == 1
        assert portfolio_summary["prod_decelerating"] == 1
        assert portfolio_summary["prod_stable"] == 1

    def test_weekly_units_summed(self, portfolio_summary):
        assert portfolio_summary["weekly_units"] == 350

    def test_shelf_at_risk_uses_threshold(self, portfolio_summary):
        assert portfolio_summary["shelf_at_risk"] >= 1

    def test_launches_total(self, portfolio_summary):
        assert portfolio_summary["launches_total"] == 2

    def test_total_weekly_margin(self, portfolio_summary):
        assert portfolio_summary["total_weekly_margin"] == 800


class TestShelfRiskBreakdownScoping:
    """data._shelf_risk_breakdown is the single source for the at-risk count
    (Shelf Risk card) and the dollarized headline. Revenue must be scoped to
    the retailer where each SKU is at risk: a SKU healthy at Walmart (many
    doors) but below threshold only at Sprouts (few doors) contributes only its
    Sprouts revenue, not its full cross-retailer revenue.
    """

    @staticmethod
    def _shelf(ret, _pl):
        # SKU A: healthy at Walmart (10.0 >= 2.5), at risk at Sprouts (0.5 < 1.5).
        if ret == "Walmart":
            return pd.DataFrame([{"sku": "A", "current_v": 10.0, "trailing_v": 10.0}])
        if ret == "Sprouts":
            return pd.DataFrame([{"sku": "A", "current_v": 0.5, "trailing_v": 1.0}])
        return pd.DataFrame(columns=["sku", "current_v", "trailing_v"])

    @staticmethod
    def _rat(ret, _pl):
        # Walmart revenue is large (500 doors) and MUST be excluded; A is safe there.
        if ret == "Walmart":
            return pd.DataFrame([{"sku": "A", "revenue_per_sw": 20.0, "doors": 500}])
        if ret == "Sprouts":
            return pd.DataFrame([{"sku": "A", "revenue_per_sw": 3.0, "doors": 10}])
        return pd.DataFrame(columns=["sku", "revenue_per_sw", "doors"])

    def test_revenue_scoped_to_at_risk_retailer(self):
        with (
            patch("data.get_shelf_defense_data", side_effect=self._shelf),
            patch("data.get_rationalization_data", side_effect=self._rat),
        ):
            from data import _shelf_risk_breakdown
            at_risk, _warning, revenue = _shelf_risk_breakdown()

        assert at_risk == {"A"}  # unique across retailers
        # Sprouts only: 3.0 * 10 = 30. NOT Walmart's 20.0 * 500 = 10_000.
        assert revenue == pytest.approx(30.0)


class TestRiskCardEmptyState:
    """A risk card with total == 0 (e.g. no active launches) must show a
    neutral empty state, not a red '0 of 0 SKUs (0%)' that reads as broken.
    """

    def test_zero_total_shows_empty_state(self):
        from decisions.portfolio_health import _risk_card

        card = _risk_card("Launch Health", 0, 0, "#c00", "No SKUs launched.", "launch")
        # children: [title, count, subtitle, detail]
        count_div, subtitle_div = card.children[1], card.children[2]
        assert count_div.children == "—"
        assert "0 of 0" not in subtitle_div.children
        assert subtitle_div.children == "None to track"

    def test_nonzero_total_shows_count(self):
        from decisions.portfolio_health import _risk_card

        card = _risk_card("Shelf Risk", 28, 50, "#c00", "detail", "shelf")
        count_div, subtitle_div = card.children[1], card.children[2]
        assert count_div.children == "28"
        assert subtitle_div.children == "of 50 SKUs (56%)"
