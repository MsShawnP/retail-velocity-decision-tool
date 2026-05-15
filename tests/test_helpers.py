"""Tests for data-layer helper functions that don't need a database."""

from __future__ import annotations

from constants import REGIONAL_CHAINS
from data import retailer_clause, _promo_to_scan_weeks


# ============================================================
# retailer_clause
# ============================================================

class TestRetailerClause:
    def test_all_retailers(self):
        sql, params = retailer_clause("All Retailers")
        assert sql == "1=1"
        assert params == []

    def test_regional_expands_chains(self):
        sql, params = retailer_clause("Regional")
        assert "IN" in sql
        assert len(params) == len(REGIONAL_CHAINS)
        for chain in REGIONAL_CHAINS:
            assert chain in params

    def test_single_retailer(self):
        sql, params = retailer_clause("Walmart")
        assert sql == "s.retailer = %s"
        assert params == ["Walmart"]


# ============================================================
# _promo_to_scan_weeks
# ============================================================

class TestPromoToScanWeeks:
    def test_single_week(self):
        result = _promo_to_scan_weeks("2025-01-06", "2025-01-06")
        assert len(result) == 1
        assert result[0] == "2025-01-11"

    def test_two_weeks(self):
        result = _promo_to_scan_weeks("2025-01-06", "2025-01-13")
        assert len(result) == 2
        assert result[0] == "2025-01-11"
        assert result[1] == "2025-01-18"

    def test_empty_on_reversed_dates(self):
        result = _promo_to_scan_weeks("2025-02-01", "2025-01-01")
        assert result == []
