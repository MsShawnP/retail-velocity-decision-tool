"""Cinderhaven canonical data regression tests.

Verifies the baked SQLite artifact matches the Cinderhaven data contract.
If data-gen scripts are re-run, these tests catch accidental drift.

Canonical contract (target):
    - 50 SKUs, 5 product lines, 6 retailers
    - Retailers: Walmart, Costco, Whole Foods, Sprouts, Kroger, Regional Group

Current state (this repo):
    - 90 SKUs across 3 product lines (Artisan Sauces, Specialty Condiments,
      Pantry Staples).  TODO: migrate to 50 SKUs / 5 product lines.
    - Retailers: Walmart, Costco, Whole Foods, + regional independents + UNFI + DTC.
      TODO: add Kroger and Sprouts channels.
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
        """Current dataset has 90 SKUs.  TODO: converge to canonical 50."""
        (count,) = db.execute("SELECT COUNT(DISTINCT sku) FROM product_master").fetchone()
        assert count == 90, f"Expected 90 SKUs (current), got {count}"

    # ------------------------------------------------------------------
    # Product lines
    # ------------------------------------------------------------------

    def test_product_line_count(self, db):
        """Current dataset has 3 product lines.  TODO: expand to canonical 5."""
        (count,) = db.execute(
            "SELECT COUNT(DISTINCT product_line) FROM product_master"
        ).fetchone()
        assert count == 3, f"Expected 3 product lines (current), got {count}"

    def test_product_line_names(self, db):
        rows = db.execute(
            "SELECT DISTINCT product_line FROM product_master ORDER BY product_line"
        ).fetchall()
        names = {r[0] for r in rows}
        expected = {"Artisan Sauces", "Specialty Condiments", "Pantry Staples"}
        assert names == expected, f"Product line mismatch: {names}"

    # ------------------------------------------------------------------
    # Retailers
    # ------------------------------------------------------------------

    def test_retailer_count(self, db):
        """Stores table has 10 distinct retailer channels."""
        (count,) = db.execute("SELECT COUNT(DISTINCT retailer) FROM stores").fetchone()
        assert count == 10, f"Expected 10 retailers, got {count}"

    def test_core_retailers_present(self, db):
        """Walmart, Costco, and Whole Foods must always be present."""
        rows = db.execute("SELECT DISTINCT retailer FROM stores").fetchall()
        retailers = {r[0] for r in rows}
        for name in ("Walmart", "Costco", "Whole Foods"):
            assert name in retailers, f"Core retailer {name!r} missing from stores"

    def test_kroger_sprouts_missing_note(self, db):
        """Kroger and Sprouts are NOT yet in this dataset.  TODO: add them."""
        rows = db.execute("SELECT DISTINCT retailer FROM stores").fetchall()
        retailers = {r[0] for r in rows}
        # This test documents the gap -- it passes because they're absent.
        assert "Kroger" not in retailers, "Kroger now present -- update canonical counts"
        assert "Sprouts" not in retailers, "Sprouts now present -- update canonical counts"

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
