"""Generate the `price_history` table — wholesale price changes over time
per (sku, retailer).

For each (sku, retailer) the SKU is authorized at:
  - Always one row at the SKU's launch date with the launch wholesale price
  - 20% chance of a single price increase 6-15 months after launch (+2-6%)
  - 10% chance of a price decrease 8-18 months after launch (-2-5%, volume
    discount or competitive pressure)

This is reference data — scan_data continues to use the current sku_costs
wholesale price for revenue calculation. Apps that need time-aware pricing
can join price_history.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"
SEED = 42

REGIONAL_CHAINS = (
    "Green Basket Market", "Harbor Fresh", "Prairie Provisions",
    "Mountain Pantry Co", "Southside Grocers",
)

# Map a stores.retailer value to the sku_costs.wholesale_<retailer> column
RETAILER_TO_COLUMN = {
    "Walmart": "wholesale_walmart",
    "Costco": "wholesale_costco",
    "Whole Foods": "wholesale_whole_foods",
    "UNFI": "wholesale_unfi",
    "DTC": "wholesale_dtc",
}
# All regional chains share the wholesale_regional price


def category_for_store_retailer(retailer: str) -> str | None:
    if retailer in RETAILER_TO_COLUMN:
        return retailer
    if retailer in REGIONAL_CHAINS:
        return "Regional"
    return None


def main() -> None:
    rng = random.Random(SEED)
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Per-SKU current retailer-specific wholesale prices
    cost_rows = cur.execute("""
        SELECT sku, wholesale_walmart, wholesale_costco, wholesale_whole_foods,
               wholesale_regional, wholesale_unfi, wholesale_dtc
        FROM sku_costs
    """).fetchall()
    sku_prices: dict[str, dict[str, float]] = {}
    for sku, w_walmart, w_costco, w_wf, w_regional, w_unfi, w_dtc in cost_rows:
        sku_prices[sku] = {
            "Walmart": w_walmart,
            "Costco": w_costco,
            "Whole Foods": w_wf,
            "Regional": w_regional,
            "UNFI": w_unfi,
            "DTC": w_dtc,
        }

    # SKU launch date per channel category, derived from distribution_log.
    # We use the earliest authorized_date the SKU saw in stores of that category.
    sku_channel_launch: dict[tuple[str, str], date] = {}
    for sku, store_retailer, ad in cur.execute("""
        SELECT d.sku, s.retailer, MIN(d.authorized_date)
        FROM distribution_log d JOIN stores s ON d.store_id = s.store_id
        GROUP BY d.sku, s.retailer
    """).fetchall():
        cat = category_for_store_retailer(store_retailer)
        if not cat or not ad:
            continue
        d = date.fromisoformat(ad)
        cur_d = sku_channel_launch.get((sku, cat))
        if cur_d is None or d < cur_d:
            sku_channel_launch[(sku, cat)] = d

    rows: list[tuple[str, str, str, float]] = []

    for (sku, cat), launch_d in sku_channel_launch.items():
        base_price = sku_prices[sku][cat]
        rows.append((sku, cat, launch_d.isoformat(), base_price))

        roll = rng.random()
        if roll < 0.20:
            # Price increase 6-15 months after launch, +2-6%
            delay_months = rng.randint(6, 15)
            change_d = launch_d + timedelta(days=delay_months * 30)
            new_price = round(base_price * rng.uniform(1.02, 1.06), 2)
            rows.append((sku, cat, change_d.isoformat(), new_price))
        elif roll < 0.30:
            # Price decrease 8-18 months after launch, -2 to -5%
            delay_months = rng.randint(8, 18)
            change_d = launch_d + timedelta(days=delay_months * 30)
            new_price = round(base_price * rng.uniform(0.95, 0.98), 2)
            rows.append((sku, cat, change_d.isoformat(), new_price))

    cur.execute("DROP TABLE IF EXISTS price_history")
    cur.execute("""
        CREATE TABLE price_history (
            sku             TEXT NOT NULL,
            retailer        TEXT NOT NULL,
            effective_date  TEXT NOT NULL,
            wholesale_price REAL NOT NULL,
            PRIMARY KEY (sku, retailer, effective_date)
        )
    """)
    cur.execute("CREATE INDEX idx_ph_sku ON price_history(sku)")
    cur.executemany(
        "INSERT INTO price_history (sku, retailer, effective_date, wholesale_price) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    con.commit()

    print(f"Inserted {len(rows):,} price_history rows.")
    n_initial = sum(1 for _, _, _, _ in rows)  # all rows
    n_skus = len({(s, c) for s, c, _, _ in rows})
    print(f"  Distinct (sku, retailer) pairs: {n_skus}")
    n_increase = sum(1 for s, c, d, _ in rows
                     if (s, c, d) not in {(s_, c_, sku_channel_launch[(s_, c_)].isoformat())
                                           for s_, c_ in sku_channel_launch})
    print(f"  Rows beyond initial price: {n_increase}")

    print("\nSample rows (one SKU at one retailer):")
    for r in cur.execute("""
        SELECT sku, retailer, effective_date, wholesale_price
        FROM price_history WHERE sku = (
            SELECT sku FROM price_history GROUP BY sku
            HAVING COUNT(*) >= 2 LIMIT 1
        ) ORDER BY effective_date LIMIT 6
    """).fetchall():
        print(f"  {r}")

    con.close()


if __name__ == "__main__":
    main()
