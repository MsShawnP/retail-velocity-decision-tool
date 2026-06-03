"""Tests for data-layer helper functions that don't need a database."""

from __future__ import annotations

from constants import REGIONAL_CHAINS
from data import retailer_clause


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
