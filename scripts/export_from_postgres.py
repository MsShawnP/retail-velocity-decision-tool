"""Export the Cinderhaven SSOT tables from Postgres into RVDT's local SQLite mirror.

RVDT runs against Postgres marts in production; this SQLite artifact
(``data/cinderhaven_product_master.db``) is the offline fixture the canonical
regression tests read when a database isn't reachable. This script regenerates
that fixture as a faithful snapshot of the live ``raw.*`` tables.

It is the forward counterpart to the (disabled) legacy ``reload_postgres.py``,
and follows the same pattern as product-data-health-audit's
``scripts/export_from_postgres.py`` — one SELECT per mirror table, retailer
codes resolved to display names via ``raw.retailers``, values stored to match
the fixture's existing column affinities (TEXT everywhere except
``price_history.wholesale_price`` REAL and ``retailer_requirements.required``
INTEGER).

Writes atomically: builds ``<out>.tmp`` then ``os.replace`` onto the target, so
a failed run never leaves a half-written mirror and never disturbs sibling
``.bak`` backups. It does NOT create its own backup — snapshot the existing
mirror yourself first if you need a rollback.

Usage:
    flyctl proxy 5434:5432 -a cinderhaven-db      # in another terminal
    POSTGRES_PASSWORD=... python scripts/export_from_postgres.py
    # or: DATABASE_URL=postgresql://... python scripts/export_from_postgres.py
    # override target: RVDT_SQLITE_OUT=/tmp/mirror.db python scripts/export_from_postgres.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import psycopg2

PGPORT = os.environ.get("PGPORT", "5434")
PGPASS = os.environ.get("POSTGRES_PASSWORD", "")
PGUSER = os.environ.get("PGUSER", "postgres")
PGHOST = os.environ.get("PGHOST", "127.0.0.1")
PGDB = os.environ.get("PGDATABASE", "cinderhaven")
# DATABASE_URL, if set, is supplied by the operator's environment — never
# construct a URL-with-password literal in source (secret-scanner false
# positives, and it's a bad habit). Otherwise connect via discrete keyword
# args below.
DB_URL = os.environ.get("DATABASE_URL", "")

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("RVDT_SQLITE_OUT", ROOT / "data" / "cinderhaven_product_master.db"))

# One entry per mirror table, in dependency-free order. Each carries the exact
# CREATE (matching the existing fixture's affinities), the source SELECT, and a
# list of (column, kind) used to coerce each value on the way in.
TABLES = {
    "product_master": {
        "create": '''CREATE TABLE [product_master] ("sku" TEXT, "product_name" TEXT, "product_line" TEXT, "subcategory" TEXT, "gtin14" TEXT, "upc" TEXT, "case_pack_qty" TEXT, "unit_weight_lbs" TEXT, "case_weight_lbs" TEXT, "case_length_in" TEXT, "case_width_in" TEXT, "case_height_in" TEXT, "msrp" TEXT, "brand_owner" TEXT, "country_of_origin" TEXT, "last_updated" TEXT)''',
        "select": """
            SELECT sku, product_name, product_line, subcategory, gtin14, upc,
                   case_pack_qty, unit_weight_lbs, case_weight_lbs,
                   case_length_in, case_width_in, case_height_in, msrp,
                   brand_owner, country_of_origin, last_updated
            FROM raw.product_master
        """,
        "kinds": ["text"] * 16,
    },
    "sku_costs": {
        "create": '''CREATE TABLE [sku_costs] ("sku" TEXT, "cogs_per_unit" TEXT, "landed_cost_per_unit" TEXT, "wholesale_price" TEXT, "wholesale_walmart" TEXT, "wholesale_costco" TEXT, "wholesale_whole_foods" TEXT, "wholesale_sprouts" TEXT, "wholesale_regional" TEXT, "wholesale_unfi" TEXT, "wholesale_kehe" TEXT, "wholesale_dtc" TEXT, "trade_spend_pct_walmart" TEXT, "trade_spend_pct_costco" TEXT, "trade_spend_pct_whole_foods" TEXT, "trade_spend_pct_sprouts" TEXT, "trade_spend_pct_kroger" TEXT, "trade_spend_pct_regional" TEXT, "trade_spend_pct_unfi" TEXT, "trade_spend_pct_kehe" TEXT, "trade_spend_pct_dtc" TEXT)''',
        "select": """
            SELECT sku, cogs_per_unit, landed_cost_per_unit, wholesale_price,
                   wholesale_walmart, wholesale_costco, wholesale_whole_foods,
                   wholesale_sprouts, wholesale_regional, wholesale_unfi,
                   wholesale_kehe, wholesale_dtc,
                   trade_spend_pct_walmart, trade_spend_pct_costco,
                   trade_spend_pct_whole_foods, trade_spend_pct_sprouts,
                   trade_spend_pct_kroger, trade_spend_pct_regional,
                   trade_spend_pct_unfi, trade_spend_pct_kehe, trade_spend_pct_dtc
            FROM raw.sku_costs
        """,
        "kinds": ["text"] * 21,
    },
    "stores": {
        "create": '''CREATE TABLE [stores] ("store_id" TEXT, "retailer" TEXT, "retailer_id" TEXT, "region" TEXT, "state" TEXT, "volume_tier" TEXT, "chain_name" TEXT)''',
        "select": """
            SELECT s.store_id, r.name AS retailer, s.retailer_id,
                   s.region, s.state, s.volume_tier, s.chain_name
            FROM raw.stores s
            JOIN raw.retailers r ON s.retailer_id = r.retailer_id
        """,
        "kinds": ["text"] * 7,
    },
    "scan_data": {
        "create": '''CREATE TABLE [scan_data] ("sku" TEXT, "store_id" TEXT, "week_ending" TEXT, "units_sold" TEXT, "dollars_sold" TEXT)''',
        "select": """
            SELECT sku, store_id, week_ending, units_sold, dollars_sold
            FROM raw.scan_data
        """,
        "kinds": ["text"] * 5,
    },
    "chargebacks": {
        "create": '''CREATE TABLE [chargebacks] ("chargeback_id" TEXT, "month" TEXT, "retailer" TEXT, "reason" TEXT, "amount" TEXT, "sku" TEXT, "triggered_by_field" TEXT)''',
        "select": """
            SELECT c.chargeback_id, TO_CHAR(c.month, 'YYYY-MM') AS month,
                   r.name AS retailer, c.reason, c.amount, c.sku, c.triggered_by_field
            FROM raw.retailer_chargebacks c
            JOIN raw.retailers r ON c.retailer_id = r.retailer_id
        """,
        "kinds": ["text"] * 7,
    },
    "promotions": {
        "create": '''CREATE TABLE [promotions] ("promo_id" TEXT, "sku" TEXT, "retailer" TEXT, "start_week" TEXT, "end_week" TEXT, "discount_depth_pct" TEXT, "promo_type" TEXT, "promo_cost" TEXT, "funding_mechanism" TEXT)''',
        "select": """
            SELECT p.promo_id, p.sku, r.name AS retailer, p.start_week, p.end_week,
                   p.discount_depth_pct, p.promo_type, p.promo_cost, p.funding_mechanism
            FROM raw.promotions p
            JOIN raw.retailers r ON p.retailer_id = r.retailer_id
        """,
        "kinds": ["text"] * 9,
    },
    "distribution_log": {
        "create": '''CREATE TABLE [distribution_log] ("sku" TEXT, "store_id" TEXT, "authorized_date" TEXT, "deauthorized_date" TEXT)''',
        "select": """
            SELECT sku, store_id, authorized_date, deauthorized_date
            FROM raw.distribution_log
        """,
        "kinds": ["text"] * 4,
    },
    "price_history": {
        "create": '''CREATE TABLE price_history (
            sku             TEXT NOT NULL,
            retailer        TEXT NOT NULL,
            effective_date  TEXT NOT NULL,
            wholesale_price REAL NOT NULL,
            PRIMARY KEY (sku, retailer, effective_date)
        )''',
        "select": """
            SELECT p.sku, r.name AS retailer, p.effective_date, p.wholesale_price
            FROM raw.price_history p
            JOIN raw.retailers r ON p.retailer_id = r.retailer_id
        """,
        "kinds": ["text", "text", "text", "real"],
    },
    "retailer_requirements": {
        "create": '''CREATE TABLE "retailer_requirements" (
            "retailer" TEXT,
            "field" TEXT,
            "required" INTEGER,
            "notes" TEXT
        )''',
        "select": """
            SELECT r.name AS retailer, rr.field, rr.required, rr.notes
            FROM raw.retailer_requirements rr
            JOIN raw.retailers r ON rr.retailer_id = r.retailer_id
        """,
        "kinds": ["text", "text", "int", "text"],
    },
}


def _coerce(value, kind):
    if value is None:
        return None
    if kind == "text":
        return str(value)
    if kind == "real":
        return float(value)
    if kind == "int":
        return int(value)  # bool -> 0/1
    raise ValueError(f"unknown kind {kind!r}")


def export():
    if not PGPASS and "DATABASE_URL" not in os.environ:
        print("Set POSTGRES_PASSWORD or DATABASE_URL.", file=sys.stderr)
        sys.exit(1)

    print("Connecting to Postgres...")
    if DB_URL:
        pg = psycopg2.connect(DB_URL, connect_timeout=8)
    else:
        pg = psycopg2.connect(
            host=PGHOST, port=PGPORT, dbname=PGDB,
            user=PGUSER, password=PGPASS, connect_timeout=8,
        )
    pg.set_session(readonly=True)
    cur = pg.cursor()
    cur.execute("SET search_path = raw, public")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    sl = sqlite3.connect(str(tmp))
    sl.execute("PRAGMA journal_mode=WAL")
    sl.execute("PRAGMA synchronous=NORMAL")

    for name, spec in TABLES.items():
        cur.execute(spec["select"])
        kinds = spec["kinds"]
        ncols = len(kinds)
        sl.execute(f"DROP TABLE IF EXISTS [{name}]")
        sl.execute(spec["create"])
        placeholders = ", ".join(["?"] * ncols)
        insert = f"INSERT INTO [{name}] VALUES ({placeholders})"
        total = 0
        while True:
            rows = cur.fetchmany(10_000)
            if not rows:
                break
            clean = [tuple(_coerce(v, kinds[i]) for i, v in enumerate(row)) for row in rows]
            sl.executemany(insert, clean)
            total += len(rows)
        sl.commit()
        print(f"  {name}: {total:,} rows")

    sl.execute("ANALYZE")
    # Collapse the WAL back into the main file so the swapped mirror is a single
    # self-contained file (no -wal/-shm sidecars trailing the temp name).
    sl.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    sl.execute("PRAGMA journal_mode=DELETE")
    sl.close()
    pg.close()

    os.replace(tmp, OUT)
    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"\nExported to {OUT} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    export()
