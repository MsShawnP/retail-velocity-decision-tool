"""Cinderhaven canonical data regression tests.

Verifies the baked SQLite artifact matches the Cinderhaven data contract.
If data-gen scripts are re-run, these tests catch accidental drift.

Canonical contract:
    - 50 SKUs, 5 product lines, 6 retailers
    - Retailers: Walmart, Costco, Whole Foods, Sprouts, Kroger, Regional Group
    - 123 promotions (16 Regional Group); 9,992 distribution authorizations;
      66 retailer requirements (53 required); cy2025 (trailing-52w) scan
      revenue == $32,323,139.62 (VERIFIED-AGAINST-PRODUCTION 2026-07-29).

These row/aggregate guards were added after a mirror-vs-live drift audit
(2026-08-01) that resynced the fixture from live Postgres. The promotions
count is 16 for Regional Group at the *raw* level; the Promo-ROI view derives
a smaller ROI-qualified subset (13) at query time — that is not drift.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"


@pytest.fixture(scope="module")
def db():
    """Return a read-only connection to the baked SQLite artifact.

    The 165 MB artifact is gitignored and absent in CI, so skip these drift
    guards when it isn't present. They run locally and wherever the baked data
    is available.
    """
    if not DB_PATH.exists():
        pytest.skip(f"Baked data artifact not present: {DB_PATH}")
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

    # ------------------------------------------------------------------
    # Promotions (raw promo list, not the ROI-qualified view)
    # ------------------------------------------------------------------

    def test_promotions_total(self, db):
        """Canonical: 123 promotions total."""
        (count,) = db.execute("SELECT COUNT(*) FROM promotions").fetchone()
        assert count == 123, f"Expected 123 promotions (canonical), got {count}"

    def test_promotions_by_retailer(self, db):
        """Canonical per-retailer promo counts; Regional Group is 16 at the raw
        level (the Promo-ROI view qualifies a 13-row subset at query time)."""
        rows = db.execute(
            "SELECT retailer, COUNT(*) FROM promotions GROUP BY retailer"
        ).fetchall()
        counts = dict(rows)
        expected = {
            "Costco": 22,
            "Kroger": 16,
            "Regional Group": 16,
            "Sprouts": 24,
            "Walmart": 25,
            "Whole Foods": 20,
        }
        assert counts == expected, f"Promo-by-retailer drift: {counts}"

    # ------------------------------------------------------------------
    # Distribution authorizations
    # ------------------------------------------------------------------

    def test_distribution_total(self, db):
        """Canonical: 9,992 distribution authorizations (9,943 cy2023 + 49 in 2025)."""
        (count,) = db.execute("SELECT COUNT(*) FROM distribution_log").fetchone()
        assert count == 9992, f"Expected 9,992 distribution rows (canonical), got {count}"

    # ------------------------------------------------------------------
    # Retailer requirements
    # ------------------------------------------------------------------

    def test_retailer_requirements(self, db):
        """Canonical: 66 retailer-requirement rows, 53 of them required."""
        (total,) = db.execute("SELECT COUNT(*) FROM retailer_requirements").fetchone()
        (required,) = db.execute(
            "SELECT COUNT(*) FROM retailer_requirements WHERE required = 1"
        ).fetchone()
        assert total == 66, f"Expected 66 retailer_requirements rows, got {total}"
        assert required == 53, f"Expected 53 required rows, got {required}"

    # ------------------------------------------------------------------
    # Scan revenue (verified against production)
    # ------------------------------------------------------------------

    def test_cy2025_scan_revenue(self, db):
        """Canonical: cy2025 (trailing-52w, scan ends 2025-12-27) scan revenue
        == $32,323,139.62, VERIFIED-AGAINST-PRODUCTION 2026-07-29. Guard within $1."""
        (rev,) = db.execute(
            "SELECT SUM(CAST(dollars_sold AS REAL)) FROM scan_data "
            "WHERE week_ending >= '2025-01-01'"
        ).fetchone()
        assert abs(rev - 32_323_139.62) < 1.0, (
            f"cy2025 scan revenue drift: got {rev:,.2f}, expected 32,323,139.62"
        )
