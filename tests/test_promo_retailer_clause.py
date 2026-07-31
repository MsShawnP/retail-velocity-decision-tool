"""Regression: Regional promotions must not be dropped by a literal match.

fct_promotions stores the chain name ("Regional Group"), while the UI label
is "Regional". A literal ``retailer = 'Regional'`` filter matches nothing —
this dropped all 16 Regional promos from Promo ROI and Pricing Power until
2026-07-31. ``promo_retailer_clause`` must map the label to REGIONAL_CHAINS
exactly like ``retailer_clause`` does for stores.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from constants import REGIONAL_CHAINS  # noqa: E402
from data import promo_retailer_clause, retailer_clause  # noqa: E402


class TestPromoRetailerClause:
    def test_regional_maps_to_chain_names(self):
        clause, params = promo_retailer_clause("Regional")
        assert "IN (" in clause
        assert params == list(REGIONAL_CHAINS)
        assert "Regional Group" in params
        # The raw UI label must never be a bind parameter for Regional.
        assert "Regional" not in params or "Regional" in REGIONAL_CHAINS

    def test_regional_respects_column_prefix(self):
        clause, params = promo_retailer_clause("Regional", column="p.retailer")
        assert clause.startswith("p.retailer IN (")
        assert params == list(REGIONAL_CHAINS)

    def test_all_retailers_is_passthrough(self):
        clause, params = promo_retailer_clause("All Retailers")
        assert clause == "1=1"
        assert params == []

    def test_named_retailer_binds_verbatim(self):
        clause, params = promo_retailer_clause("Walmart", column="p.retailer")
        assert clause == "p.retailer = %s"
        assert params == ["Walmart"]

    def test_mirrors_store_clause_semantics(self):
        """Store-side and promo-side filters must agree on the Regional set."""
        _, store_params = retailer_clause("Regional")
        _, promo_params = promo_retailer_clause("Regional")
        assert store_params == promo_params
