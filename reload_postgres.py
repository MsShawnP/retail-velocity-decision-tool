"""Reload Postgres tables from the SQLite source database.

Requires: fly proxy 15432:5432 --app cinderhaven-db running in background.
"""
import os
import sqlite3
import psycopg2
import io
import csv
import sys

SQLITE_PATH = r"C:\Users\mssha\projects\active\cinderhaven-data\data\cinderhaven_product_master.db"
PG_DSN = os.environ.get("DATABASE_URL", "postgres://localhost:15432/cinderhaven")

CATEGORY_MAP = {
    "Artisan Sauces": "Sauces & Marinades",
    "Specialty Condiments": "Condiments & Dressings",
    "Pantry Staples": "Dry Grocery & Baking",
}

BENCHMARK_MULTIPLIERS = {
    "Sauces & Marinades": 0.92,
    "Condiments & Dressings": 1.22,
    "Dry Grocery & Baking": 1.35,
}

RETAILER_ADJUSTMENTS = {
    "Walmart": 1.0,
    "Costco": 0.85,
    "Whole Foods": 1.10,
}

TABLE_DEFINITIONS = {
    "stg_stores": {
        "source": "stores",
        "create": """
            CREATE TABLE stg_stores (
                store_id TEXT PRIMARY KEY,
                retailer TEXT NOT NULL,
                chain_name TEXT,
                region TEXT,
                state TEXT,
                volume_tier TEXT,
                is_aggregated_channel BOOLEAN NOT NULL DEFAULT false
            )
        """,
        "columns": ["store_id", "retailer", "chain_name", "region", "state", "volume_tier", "is_aggregated_channel"],
        "transforms": {"is_aggregated_channel": lambda v: v == 1},
    },
    "stg_scan_data": {
        "source": "scan_data",
        "create": """
            CREATE TABLE stg_scan_data (
                sku TEXT NOT NULL,
                store_id TEXT NOT NULL,
                week_ending DATE NOT NULL,
                units_sold INTEGER NOT NULL,
                dollars_sold REAL
            )
        """,
        "columns": ["sku", "store_id", "week_ending", "units_sold", "dollars_sold"],
        "transforms": {},
    },
    "dim_products": {
        "source": "product_master",
        "create": """
            CREATE TABLE dim_products (
                sku TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                product_line TEXT NOT NULL,
                subcategory TEXT,
                gtin14 TEXT,
                upc TEXT,
                case_pack_qty INTEGER,
                unit_weight_lbs REAL,
                case_weight_lbs REAL,
                case_length_in REAL,
                case_width_in REAL,
                case_height_in REAL,
                msrp REAL,
                serving_size TEXT,
                calories_per_serving REAL,
                total_fat_g REAL,
                sodium_mg INTEGER,
                total_carb_g REAL,
                protein_g REAL,
                brand_owner TEXT,
                country_of_origin TEXT,
                active_retailers TEXT,
                oneworldsync_status TEXT,
                last_updated TEXT,
                updated_by TEXT,
                category TEXT
            )
        """,
        "columns": ["sku", "product_name", "product_line", "subcategory", "gtin14", "upc",
                     "case_pack_qty", "unit_weight_lbs", "case_weight_lbs", "case_length_in",
                     "case_width_in", "case_height_in", "msrp", "serving_size",
                     "calories_per_serving", "total_fat_g", "sodium_mg", "total_carb_g",
                     "protein_g", "brand_owner", "country_of_origin", "active_retailers",
                     "oneworldsync_status", "last_updated", "updated_by"],
        "transforms": {},
    },
    "stg_sku_costs": {
        "source": "sku_costs",
        "create": """
            CREATE TABLE stg_sku_costs (
                sku TEXT PRIMARY KEY,
                cogs_per_unit REAL,
                landed_cost_per_unit REAL,
                wholesale_price REAL,
                wholesale_walmart REAL,
                wholesale_costco REAL,
                wholesale_whole_foods REAL,
                wholesale_regional REAL,
                wholesale_unfi REAL,
                wholesale_kehe REAL,
                wholesale_dtc REAL,
                trade_spend_pct_walmart REAL,
                trade_spend_pct_costco REAL,
                trade_spend_pct_whole_foods REAL,
                trade_spend_pct_regional REAL,
                trade_spend_pct_unfi REAL,
                trade_spend_pct_kehe REAL,
                trade_spend_pct_dtc REAL
            )
        """,
        "columns": ["sku", "cogs_per_unit", "landed_cost_per_unit", "wholesale_price",
                     "wholesale_walmart", "wholesale_costco", "wholesale_whole_foods",
                     "wholesale_regional", "wholesale_unfi", "wholesale_kehe", "wholesale_dtc",
                     "trade_spend_pct_walmart", "trade_spend_pct_costco",
                     "trade_spend_pct_whole_foods", "trade_spend_pct_regional",
                     "trade_spend_pct_unfi", "trade_spend_pct_kehe", "trade_spend_pct_dtc"],
        "transforms": {},
    },
    "stg_promotions": {
        "source": "promotions",
        "create": """
            CREATE TABLE stg_promotions (
                promo_id TEXT,
                sku TEXT NOT NULL,
                retailer TEXT NOT NULL,
                store_scope TEXT,
                start_week DATE,
                end_week DATE,
                duration_weeks INTEGER,
                discount_depth_pct REAL,
                promo_type TEXT,
                promo_cost REAL,
                funding_mechanism TEXT
            )
        """,
        "columns": ["promo_id", "sku", "retailer", "store_scope", "start_week", "end_week",
                     "duration_weeks", "discount_depth_pct", "promo_type", "promo_cost",
                     "funding_mechanism"],
        "transforms": {},
    },
    "stg_price_history": {
        "source": "price_history",
        "create": """
            CREATE TABLE stg_price_history (
                sku TEXT NOT NULL,
                retailer TEXT NOT NULL,
                effective_date DATE,
                wholesale_price REAL
            )
        """,
        "columns": ["sku", "retailer", "effective_date", "wholesale_price"],
        "transforms": {},
    },
    "fct_distribution": {
        "source": "distribution_log",
        "create": """
            CREATE TABLE fct_distribution (
                sku TEXT NOT NULL,
                store_id TEXT NOT NULL,
                authorized_date DATE,
                deauthorized_date DATE
            )
        """,
        "columns": ["sku", "store_id", "authorized_date", "deauthorized_date"],
        "transforms": {},
    },
}


def load_table(sqlite_conn, pg_conn, table_name, table_def):
    source = table_def["source"]
    columns = table_def["columns"]
    transforms = table_def.get("transforms", {})

    print(f"\n--- {table_name} (from {source}) ---")

    cur = pg_conn.cursor()
    try:
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
    except psycopg2.errors.WrongObjectType:
        pg_conn.rollback() if not pg_conn.autocommit else None
        cur.execute(f"DROP VIEW IF EXISTS {table_name} CASCADE")
    try:
        cur.execute(f"DROP VIEW IF EXISTS {table_name} CASCADE")
    except psycopg2.errors.WrongObjectType:
        pass
    cur.execute(table_def["create"])

    rows = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM [{source}]").fetchall()
    print(f"  Read {len(rows)} rows from SQLite")

    if not rows:
        print("  (empty table, skipping)")
        return

    if transforms:
        transformed = []
        for row in rows:
            new_row = list(row)
            for col_name, fn in transforms.items():
                idx = columns.index(col_name)
                new_row[idx] = fn(row[idx])
            transformed.append(new_row)
        rows = transformed

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter='\t', lineterminator='\n')
    for row in rows:
        writer.writerow(['' if v is None else v for v in row])
    buf.seek(0)

    cur.copy_from(buf, table_name, columns=columns, null='')
    print(f"  Loaded {len(rows)} rows into Postgres")

    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
    print(f"  Verified: {cur.fetchone()[0]} rows")


def add_category_column(pg_conn):
    print("\n--- Adding category column to dim_products ---")
    cur = pg_conn.cursor()
    for product_line, category in CATEGORY_MAP.items():
        cur.execute(
            "UPDATE dim_products SET category = %s WHERE product_line = %s",
            (category, product_line),
        )
        print(f"  {product_line} -> {category}")

    cur.execute("SELECT COUNT(*) FROM dim_products WHERE category IS NOT NULL")
    print(f"  {cur.fetchone()[0]} products categorized")


def seed_benchmarks(pg_conn):
    print("\n--- Seeding stg_category_benchmarks ---")
    cur = pg_conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stg_category_benchmarks (
            category     TEXT    NOT NULL,
            retailer     TEXT    NOT NULL,
            week_ending  DATE    NOT NULL,
            avg_velocity NUMERIC(10, 4) NOT NULL,
            PRIMARY KEY (category, retailer, week_ending)
        )
    """)
    cur.execute("DELETE FROM stg_category_benchmarks")

    cur.execute("""
        SELECT DISTINCT s.retailer
        FROM stg_stores s
        WHERE s.is_aggregated_channel = false
          AND s.retailer NOT IN ('UNFI', 'DTC')
    """)
    retailers = [r[0] for r in cur.fetchall()]
    print(f"  Retailers: {retailers}")

    total = 0
    for category, mult in BENCHMARK_MULTIPLIERS.items():
        for retailer in retailers:
            ret_adj = RETAILER_ADJUSTMENTS.get(retailer, 1.05)
            final_mult = mult * ret_adj

            cur.execute("""
                INSERT INTO stg_category_benchmarks
                    (category, retailer, week_ending, avg_velocity)
                SELECT
                    %s AS category,
                    %s AS retailer,
                    d.week_ending,
                    AVG(d.units_sold) * %s AS avg_velocity
                FROM stg_scan_data d
                JOIN stg_stores s ON d.store_id = s.store_id
                JOIN dim_products pm ON d.sku = pm.sku
                WHERE pm.category = %s
                  AND s.retailer = %s
                  AND s.is_aggregated_channel = false
                GROUP BY d.week_ending
                ON CONFLICT (category, retailer, week_ending)
                DO UPDATE SET avg_velocity = EXCLUDED.avg_velocity
            """, (category, retailer, final_mult, category, retailer))
            rows = cur.rowcount
            total += rows
            print(f"  {category} x {retailer}: {rows} weeks")

    print(f"  Total: {total} benchmark rows")


def create_indexes(pg_conn):
    print("\n--- Creating indexes ---")
    cur = pg_conn.cursor()
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_scan_data_store ON stg_scan_data(store_id)",
        "CREATE INDEX IF NOT EXISTS idx_scan_data_sku ON stg_scan_data(sku)",
        "CREATE INDEX IF NOT EXISTS idx_scan_data_week ON stg_scan_data(week_ending)",
        "CREATE INDEX IF NOT EXISTS idx_scan_data_sku_store ON stg_scan_data(sku, store_id)",
        "CREATE INDEX IF NOT EXISTS idx_stores_retailer ON stg_stores(retailer)",
        "CREATE INDEX IF NOT EXISTS idx_fct_dist_sku ON fct_distribution(sku)",
        "CREATE INDEX IF NOT EXISTS idx_fct_dist_store ON fct_distribution(store_id)",
        "CREATE INDEX IF NOT EXISTS idx_promos_sku ON stg_promotions(sku)",
        "CREATE INDEX IF NOT EXISTS idx_benchmarks_cat_ret ON stg_category_benchmarks(category, retailer)",
    ]
    for idx in indexes:
        name = idx.split("idx_")[1].split(" ")[0]
        cur.execute(idx)
        print(f"  Created idx_{name}")


def main():
    print("Connecting to SQLite...")
    sqlite_conn = sqlite3.connect(SQLITE_PATH)

    print("Connecting to Postgres (via fly proxy)...")
    try:
        pg_conn = psycopg2.connect(PG_DSN)
    except Exception as e:
        print(f"ERROR: Cannot connect to Postgres: {e}")
        print("Make sure 'fly proxy 15432:5432 --app cinderhaven-db' is running.")
        sys.exit(1)

    pg_conn.autocommit = True

    for table_name, table_def in TABLE_DEFINITIONS.items():
        load_table(sqlite_conn, pg_conn, table_name, table_def)

    add_category_column(pg_conn)
    seed_benchmarks(pg_conn)
    create_indexes(pg_conn)

    print("\n=== All tables loaded successfully ===")
    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
