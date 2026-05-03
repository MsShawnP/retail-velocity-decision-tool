"""Generate the `sku_costs` table.

For each SKU in product_master, derive a wholesale price from MSRP and a
COGS that produces a realistic gross margin for the SKU's product line.
Trade-spend rates are set per channel within typical specialty-food ranges.
"""

import random
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"
SEED = 42

# Gross margin targets by product line (margin = (wholesale - cogs) / wholesale)
MARGIN_RANGES = {
    "Artisan Sauces":       (0.40, 0.45),
    "Specialty Condiments": (0.50, 0.55),
    "Pantry Staples":       (0.35, 0.40),
}

# Trade spend ranges by channel
TRADE_SPEND = {
    "walmart":     (0.18, 0.25),
    "costco":      (0.15, 0.20),
    "whole_foods": (0.10, 0.15),
    "regional":    (0.08, 0.12),
    "unfi":        (0.12, 0.18),
    "dtc":         (0.00, 0.00),
}

# Retailer-specific wholesale price multipliers, applied to the base
# wholesale_price. Reflects negotiating leverage: Walmart and UNFI get the
# best (lowest) prices because of volume; DTC charges the most because there's
# no retailer margin between Cinderhaven and the consumer.
WHOLESALE_RETAILER_MULT = {
    "walmart":     0.92,
    "costco":      0.95,
    "whole_foods": 1.00,  # baseline reference
    "regional":    1.05,
    "unfi":        0.88,
    "dtc":         1.50,
}


def main():
    random.seed(SEED)
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    products = cur.execute(
        "SELECT sku, product_line, msrp FROM product_master ORDER BY sku"
    ).fetchall()

    cur.execute("DROP TABLE IF EXISTS sku_costs")
    cur.execute("""
        CREATE TABLE sku_costs (
            sku                           TEXT PRIMARY KEY,
            cogs_per_unit                 REAL NOT NULL,
            landed_cost_per_unit          REAL NOT NULL,
            wholesale_price               REAL NOT NULL,
            wholesale_walmart             REAL NOT NULL,
            wholesale_costco              REAL NOT NULL,
            wholesale_whole_foods         REAL NOT NULL,
            wholesale_regional            REAL NOT NULL,
            wholesale_unfi                REAL NOT NULL,
            wholesale_dtc                 REAL NOT NULL,
            trade_spend_pct_walmart       REAL NOT NULL,
            trade_spend_pct_costco        REAL NOT NULL,
            trade_spend_pct_whole_foods   REAL NOT NULL,
            trade_spend_pct_regional      REAL NOT NULL,
            trade_spend_pct_unfi          REAL NOT NULL,
            trade_spend_pct_dtc           REAL NOT NULL
        )
    """)

    rows = []
    for sku, product_line, msrp in products:
        # Wholesale: 45-55% of MSRP, with per-SKU variation
        wholesale_pct = random.uniform(0.45, 0.55)
        wholesale_price = round(msrp * wholesale_pct, 2)

        # COGS: derive from wholesale to hit a target gross margin
        margin_lo, margin_hi = MARGIN_RANGES[product_line]
        target_margin = random.uniform(margin_lo, margin_hi)
        cogs = round(wholesale_price * (1 - target_margin), 4)

        # Landed cost: COGS + 8-12% freight/warehousing
        freight_pct = random.uniform(0.08, 0.12)
        landed = round(cogs * (1 + freight_pct), 4)

        ts = {ch: round(random.uniform(lo, hi), 4) for ch, (lo, hi) in TRADE_SPEND.items()}

        # Retailer-specific wholesale prices (apply per-retailer multiplier
        # plus a small ±2% per-SKU jitter so contracts aren't lockstep)
        ws = {
            ch: round(wholesale_price * mult * random.uniform(0.98, 1.02), 2)
            for ch, mult in WHOLESALE_RETAILER_MULT.items()
        }

        rows.append((
            sku,
            cogs,
            landed,
            wholesale_price,
            ws["walmart"], ws["costco"], ws["whole_foods"],
            ws["regional"], ws["unfi"], ws["dtc"],
            ts["walmart"], ts["costco"], ts["whole_foods"],
            ts["regional"], ts["unfi"], ts["dtc"],
        ))

    cur.executemany(
        "INSERT INTO sku_costs ("
        "sku, cogs_per_unit, landed_cost_per_unit, wholesale_price, "
        "wholesale_walmart, wholesale_costco, wholesale_whole_foods, "
        "wholesale_regional, wholesale_unfi, wholesale_dtc, "
        "trade_spend_pct_walmart, trade_spend_pct_costco, trade_spend_pct_whole_foods, "
        "trade_spend_pct_regional, trade_spend_pct_unfi, trade_spend_pct_dtc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()

    # --- Summary ---
    total = cur.execute("SELECT COUNT(*) FROM sku_costs").fetchone()[0]
    print(f"Total rows inserted: {total}\n")

    print("Average gross margin by product line:")
    for pl, avg_margin, n in cur.execute("""
        SELECT pm.product_line,
               AVG((c.wholesale_price - c.cogs_per_unit) / c.wholesale_price),
               COUNT(*)
        FROM sku_costs c
        JOIN product_master pm ON c.sku = pm.sku
        GROUP BY pm.product_line
        ORDER BY pm.product_line
    """).fetchall():
        print(f"  {pl:<22} {avg_margin*100:5.2f}%  (n={n})")

    print("\nAverage trade spend by channel:")
    for ch, col in [
        ("Walmart",     "trade_spend_pct_walmart"),
        ("Costco",      "trade_spend_pct_costco"),
        ("Whole Foods", "trade_spend_pct_whole_foods"),
        ("Regional",    "trade_spend_pct_regional"),
        ("UNFI",        "trade_spend_pct_unfi"),
        ("DTC",         "trade_spend_pct_dtc"),
    ]:
        avg = cur.execute(f"SELECT AVG({col}) FROM sku_costs").fetchone()[0]
        print(f"  {ch:<12} {avg*100:5.2f}%")

    print("\nAverage cost metrics by product line:")
    for pl, avg_cogs, avg_landed, avg_ws, avg_msrp in cur.execute("""
        SELECT pm.product_line,
               AVG(c.cogs_per_unit),
               AVG(c.landed_cost_per_unit),
               AVG(c.wholesale_price),
               AVG(pm.msrp)
        FROM sku_costs c
        JOIN product_master pm ON c.sku = pm.sku
        GROUP BY pm.product_line
        ORDER BY pm.product_line
    """).fetchall():
        print(f"  {pl:<22} cogs=${avg_cogs:.2f}  landed=${avg_landed:.2f}  ws=${avg_ws:.2f}  msrp=${avg_msrp:.2f}")

    print("\nAvg retailer-specific wholesale price (vs base):")
    avg_base = cur.execute("SELECT AVG(wholesale_price) FROM sku_costs").fetchone()[0]
    for ch, col in [
        ("Walmart",     "wholesale_walmart"),
        ("Costco",      "wholesale_costco"),
        ("Whole Foods", "wholesale_whole_foods"),
        ("Regional",    "wholesale_regional"),
        ("UNFI",        "wholesale_unfi"),
        ("DTC",         "wholesale_dtc"),
    ]:
        avg = cur.execute(f"SELECT AVG({col}) FROM sku_costs").fetchone()[0]
        print(f"  {ch:<12} ${avg:.2f}  ({avg/avg_base:.2%} of base)")

    print("\nSample rows:")
    for r in cur.execute("""
        SELECT c.sku, pm.product_line, pm.msrp, c.cogs_per_unit, c.wholesale_price,
               c.wholesale_walmart, c.wholesale_unfi, c.wholesale_dtc
        FROM sku_costs c JOIN product_master pm ON c.sku = pm.sku
        ORDER BY c.sku LIMIT 6
    """).fetchall():
        print(f"  {r}")

    con.close()


if __name__ == "__main__":
    main()
