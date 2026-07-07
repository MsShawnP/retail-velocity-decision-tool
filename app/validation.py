"""Startup data contract validation.

Runs 7 SQL checks against the database to verify that the schema and data
meet the assumptions the decision-mode calculations depend on. Called once
at app boot; logs results but does not block startup so the app remains
accessible for debugging.
"""

from __future__ import annotations

import logging

import psycopg2

from constants import (
    PHYSICAL_RETAILERS,
    REGIONAL_CHAINS,
)
from db import get_conn

log = logging.getLogger("validation")

EXPECTED_RETAILERS = (
    (set(PHYSICAL_RETAILERS) | set(REGIONAL_CHAINS) | {"UNFI", "DTC"})
    - {"Regional"}
)


def validate_data_contract() -> dict[str, tuple[bool, str]]:
    """Run all data contract checks and return results.

    Returns a dict of {check_name: (passed: bool, detail: str)}.
    """
    results: dict[str, tuple[bool, str]] = {}

    with get_conn() as conn:
        cur = conn.cursor()

        # 1. All 6 tables exist and have >0 rows
        tables = [
            "fct_scan_data", "dim_stores", "dim_products",
            "fct_promotions", "fct_distribution",
        ]
        for table in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                count = cur.fetchone()[0]
                if count > 0:
                    results[f"table_{table}"] = (True, f"{count:,} rows")
                else:
                    results[f"table_{table}"] = (False, "table exists but is empty")
            except psycopg2.Error as exc:
                results[f"table_{table}"] = (False, f"missing or inaccessible: {exc}")

        # 2. Data coverage spans >=392 days (required for seasonal factor)
        try:
            cur.execute(
                "SELECT MIN(week_ending), MAX(week_ending),"
                " (MAX(week_ending)::date - MIN(week_ending)::date)"
                " FROM fct_scan_data"
            )
            row = cur.fetchone()
            min_d, max_d, span = row
            if span and span >= 392:
                results["date_coverage"] = (
                    True, f"{min_d} to {max_d} ({span} days)"
                )
            else:
                results["date_coverage"] = (
                    False,
                    f"{min_d} to {max_d} ({span} days) — need >=392 for seasonal factor",
                )
        except psycopg2.Error as exc:
            results["date_coverage"] = (False, str(exc))

        # 3. No zero/null case_pack_qty in dim_products
        try:
            cur.execute(
                "SELECT COUNT(*) FROM dim_products"
                " WHERE case_pack_qty IS NULL OR case_pack_qty = 0"
            )
            bad = cur.fetchone()[0]
            if bad == 0:
                results["case_pack_qty"] = (True, "all products have valid case_pack_qty")
            else:
                results["case_pack_qty"] = (
                    False, f"{bad} products with null/zero case_pack_qty"
                )
        except psycopg2.Error as exc:
            results["case_pack_qty"] = (False, str(exc))

        # 4. Volume tier values are all in {A, B, C}
        try:
            cur.execute(
                "SELECT DISTINCT volume_tier FROM dim_stores"
                " WHERE volume_tier NOT IN ('A', 'B', 'C')"
            )
            bad_tiers = [r[0] for r in cur.fetchall()]
            if not bad_tiers:
                results["volume_tiers"] = (True, "all tiers are A/B/C")
            else:
                results["volume_tiers"] = (
                    False, f"unexpected tiers: {bad_tiers}"
                )
        except psycopg2.Error as exc:
            results["volume_tiers"] = (False, str(exc))

        # 5. Retailer names match expected constants
        try:
            cur.execute("SELECT DISTINCT retailer FROM dim_stores")
            db_retailers = {r[0] for r in cur.fetchall()}
            missing = EXPECTED_RETAILERS - db_retailers
            if not missing:
                results["retailer_names"] = (
                    True, f"{len(db_retailers)} retailers found"
                )
            else:
                results["retailer_names"] = (
                    False, f"missing from DB: {sorted(missing)}"
                )
        except psycopg2.Error as exc:
            results["retailer_names"] = (False, str(exc))

        # 6. Every scanned SKU has a matching cost row
        try:
            cur.execute(
                "SELECT COUNT(*) FROM ("
                "  SELECT DISTINCT sku FROM fct_scan_data"
                "  EXCEPT SELECT sku FROM dim_products"
                ") orphans"
            )
            orphans = cur.fetchone()[0]
            if orphans == 0:
                results["sku_cost_coverage"] = (True, "all scanned SKUs have costs")
            else:
                results["sku_cost_coverage"] = (
                    False, f"{orphans} SKUs in scan data without cost records"
                )
        except psycopg2.Error as exc:
            results["sku_cost_coverage"] = (False, str(exc))

        # 7. fct_scan_data grain: each (store_id, week_ending, sku) should be unique
        try:
            cur.execute(
                "SELECT COUNT(*) FROM ("
                "  SELECT store_id, week_ending, sku"
                "  FROM fct_scan_data"
                "  GROUP BY store_id, week_ending, sku"
                "  HAVING COUNT(*) > 1"
                ") dupes"
            )
            dupes = cur.fetchone()[0]
            if dupes == 0:
                results["scan_data_grain"] = (
                    True, "scan data is unique per (store, week, sku)"
                )
            else:
                results["scan_data_grain"] = (
                    False,
                    f"{dupes} duplicate (store, week, sku) combos — "
                    "AVG velocity may be diluted",
                )
        except psycopg2.Error as exc:
            results["scan_data_grain"] = (False, str(exc))

        # 8. No null wholesale_price or cogs_per_unit in dim_products
        try:
            cur.execute(
                "SELECT COUNT(*) FROM dim_products"
                " WHERE wholesale_price IS NULL OR cogs_per_unit IS NULL"
            )
            null_costs = cur.fetchone()[0]
            if null_costs == 0:
                results["cost_completeness"] = (
                    True, "all SKU costs have wholesale_price and cogs_per_unit"
                )
            else:
                results["cost_completeness"] = (
                    False,
                    f"{null_costs} SKU cost records with null price or COGS",
                )
        except psycopg2.Error as exc:
            results["cost_completeness"] = (False, str(exc))

        # 9. fct_distribution has valid authorized_dates
        try:
            cur.execute(
                "SELECT COUNT(*),"
                " COUNT(*) FILTER (WHERE authorized_date IS NULL)"
                " FROM fct_distribution"
            )
            total, null_dates = cur.fetchone()
            if total > 0 and null_dates == 0:
                results["distribution_dates"] = (
                    True, f"{total:,} distribution records, all with dates"
                )
            elif total > 0:
                results["distribution_dates"] = (
                    False,
                    f"{null_dates}/{total} records missing authorized_date",
                )
            else:
                results["distribution_dates"] = (
                    False, "fct_distribution is empty"
                )
        except psycopg2.Error as exc:
            results["distribution_dates"] = (False, str(exc))

    return results


def log_validation_results(results: dict[str, tuple[bool, str]]) -> None:
    """Log validation results at appropriate severity levels."""
    passed = sum(1 for ok, _ in results.values() if ok)
    total = len(results)

    for name, (ok, detail) in results.items():
        if ok:
            log.info("  ✓ %s: %s", name, detail)
        else:
            log.warning("  ✗ %s: %s", name, detail)

    if passed == total:
        log.info("Data contract: %d/%d checks passed", passed, total)
    else:
        log.warning(
            "Data contract: %d/%d checks passed — see warnings above",
            passed, total,
        )
