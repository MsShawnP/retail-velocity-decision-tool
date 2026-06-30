"""Cinderhaven canonical data regression tests.

Verifies the baked SQLite artifact matches the Cinderhaven data contract.
If data-gen scripts are re-run, these tests catch accidental drift.

Canonical contract:
    - 50 SKUs, 5 product lines, 6 retailers
    - Retailers: Walmart, Costco, Whole Foods, Sprouts, Kroger, Regional Group
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"


@pytest.fixture(scope="module")
def db():
    """Return a read-only connection to the baked SQLite artifact."""
    assert DB_PATH.exists(), f"Baked data artifact not found: {DB_PATH}"
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    yield conn
    conn.close()


class TestCinderhavenCanonicalRegression:
    """Guard-rails for the baked Cinderhaven dataset."""

    # ------------------------------------------------------------------
    # SKU counts
    # ------------------------------------------------------------------

    def test_sku_count(self, db):
        """Canonical: 50 SKUs."""
        (count,) = db.execute("SELECT COUNT(DISTINCT sku) FROM product_master").fetchone()
        assert count == 50, f"Expected 50 SKUs (canonical), got {count}"

    # ------------------------------------------------------------------
    # Product lines
    # ------------------------------------------------------------------

    def test_product_line_count(self, db):
        """Canonical: 5 product lines."""
        (count,) = db.execute(
            "SELECT COUNT(DISTINCT product_line) FROM product_master"
        ).fetchone()
        assert count == 5, f"Expected 5 product lines (canonical), got {count}"

    def test_product_line_names(self, db):
        rows = db.execute(
            "SELECT DISTINCT product_line FROM product_master ORDER BY product_line"
        ).fetchall()
        names = {r[0] for r in rows}
        expected = {"Artisan Sauces", "Pantry Staples", "Specialty Condiments", "Dried Goods", "Snack Bites"}
        assert names == expected, f"Product line mismatch: {names}"

    # ------------------------------------------------------------------
    # Retailers
    # ------------------------------------------------------------------

    def test_retailer_count(self, db):
        """Stores table has 6 distinct retailer channels (canonical)."""
        (count,) = db.execute("SELECT COUNT(DISTINCT retailer) FROM stores").fetchone()
        assert count == 6, f"Expected 6 retailers, got {count}"

    def test_all_canonical_retailers_present(self, db):
        """All 6 canonical retailers must be present."""
        rows = db.execute("SELECT DISTINCT retailer FROM stores").fetchall()
        retailers = {r[0] for r in rows}
        for name in ("Walmart", "Costco", "Whole Foods", "Kroger", "Sprouts", "Regional Group"):
            assert name in retailers, f"Canonical retailer {name!r} missing from stores"

    # ------------------------------------------------------------------
    # Table existence
    # ------------------------------------------------------------------

    def test_expected_tables_exist(self, db):
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        tables = {r[0] for r in rows}
        required = {
            "product_master",
            "stores",
            "sku_costs",
            "scan_data",
            "chargebacks",
            "promotions",
        }
        missing = required - tables
        assert not missing, f"Missing tables: {missing}"
