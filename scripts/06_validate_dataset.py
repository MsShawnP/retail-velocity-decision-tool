"""Comprehensive validation of the cinderhaven_product_master.db dataset.

Walks the database, runs invariant and behavioral checks, and prints a
report. Intended to be run after all generation scripts complete.
"""

import sqlite3
import statistics
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"

EXPECTED_COUNTS = {
    "product_master":   (90, 90),
    "stores":           (895, 910),
    "distribution_log": (12_000, 13_500),
    "sku_costs":        (90, 90),
    "promotions":       (90, 160),    # SKU-level rows
    "scan_data":        (900_000, 1_400_000),
}

REGIONAL_CHAINS = "('Green Basket Market','Harbor Fresh','Prairie Provisions','Mountain Pantry Co','Southside Grocers')"

PASS_COUNT = 0
FAIL_COUNT = 0


def section(n: int, title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {n}. {title}")
    print("=" * 70)


def emit(label: str, ok: bool, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    flag = "PASS" if ok else "FAIL"
    PASS_COUNT += int(ok)
    FAIL_COUNT += int(not ok)
    suffix = f"  -- {detail}" if detail else ""
    print(f"  [{flag}] {label}{suffix}")


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print(f"Validating {DB_PATH}\n")

    # --- 1. Tables and row counts ---
    section(1, "Table existence and row counts")
    tables = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    for tbl, (lo, hi) in EXPECTED_COUNTS.items():
        if tbl not in tables:
            emit(f"{tbl}: MISSING", False)
            continue
        n = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        emit(f"{tbl}: {n:,} rows  (expected {lo:,}-{hi:,})", lo <= n <= hi)
    n_promo_ids = cur.execute("SELECT COUNT(DISTINCT promo_id) FROM promotions").fetchone()[0]
    emit(f"promotions: {n_promo_ids} distinct promo_ids  (expected 70-80)",
         70 <= n_promo_ids <= 80)

    # --- 2. Referential integrity ---
    section(2, "Referential integrity")
    orphan_skus = cur.execute("""
        SELECT COUNT(*) FROM scan_data
        WHERE sku NOT IN (SELECT sku FROM product_master)
    """).fetchone()[0]
    emit(f"scan_data SKUs all in product_master: {orphan_skus} orphans",
         orphan_skus == 0)

    orphan_stores = cur.execute("""
        SELECT COUNT(*) FROM scan_data
        WHERE store_id NOT IN (SELECT store_id FROM stores)
    """).fetchone()[0]
    emit(f"scan_data store_ids all in stores: {orphan_stores} orphans",
         orphan_stores == 0)

    promo_orphans = cur.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT p.promo_id, p.sku, p.retailer FROM promotions p
            WHERE NOT EXISTS (
                SELECT 1 FROM distribution_log dl
                JOIN stores s ON dl.store_id = s.store_id
                WHERE dl.sku = p.sku
                  AND (s.retailer = p.retailer
                       OR (p.retailer = 'Regional' AND s.retailer IN {REGIONAL_CHAINS}))
            )
        )
    """).fetchone()[0]
    emit(f"promo (SKU, retailer) combos all valid: {promo_orphans} orphans",
         promo_orphans == 0)

    # --- 3. scan_data within auth window ---
    section(3, "scan_data rows within authorization windows")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dl_sku_store ON distribution_log(sku, store_id)")
    invalid = cur.execute("""
        SELECT COUNT(*) FROM scan_data d
        WHERE NOT EXISTS (
            SELECT 1 FROM distribution_log dl
            WHERE dl.sku = d.sku AND dl.store_id = d.store_id
              AND dl.authorized_date <= DATE(d.week_ending, '-5 days')
              AND (dl.deauthorized_date IS NULL
                   OR dl.deauthorized_date > DATE(d.week_ending, '-5 days'))
        )
    """).fetchone()[0]
    emit(f"scan_data rows outside any auth window: {invalid}", invalid == 0)

    # --- 4. Annualized wholesale revenue ---
    section(4, "Annualized wholesale revenue")
    total_2yr = cur.execute("SELECT SUM(dollars_sold) FROM scan_data").fetchone()[0] or 0
    annual = total_2yr / 2
    emit(f"Annual wholesale revenue: ${annual:,.0f}  (target $23M-$27M)",
         23_000_000 <= annual <= 27_000_000)
    print(f"         2-year total: ${total_2yr:,.0f}")

    # --- 5. Velocity distribution ---
    section(5, "Velocity distribution (avg units/week per SKU x store)")
    avgs = [r[0] for r in cur.execute("""
        SELECT AVG(units_sold) FROM scan_data GROUP BY sku, store_id
    """).fetchall() if r[0] is not None]
    print(f"  n (sku x store pairs): {len(avgs):>10,}")
    if avgs:
        cuts = statistics.quantiles(avgs, n=100)
        for p in (10, 25, 50, 75, 90):
            print(f"  p{p:<3}                 : {cuts[p-1]:>10.2f}  units/wk")
        print(f"  mean                : {statistics.mean(avgs):>10.2f}")
        print(f"  max                 : {max(avgs):>10.2f}")

    # --- 6. Seasonality ---
    section(6, "Seasonality")
    for line, peak_months, off_months, peak_label, off_label in [
        ("Artisan Sauces",       "(10,11,12,1,2)", "(6,7,8)",   "Oct-Feb", "Jun-Aug"),
        ("Specialty Condiments", "(5,6,7,8)",      "(12,1,2)",  "May-Aug", "Dec-Feb"),
    ]:
        peak, off = cur.execute(f"""
            SELECT
              AVG(CASE WHEN CAST(strftime('%m', d.week_ending) AS INTEGER) IN {peak_months}
                       THEN d.units_sold END),
              AVG(CASE WHEN CAST(strftime('%m', d.week_ending) AS INTEGER) IN {off_months}
                       THEN d.units_sold END)
            FROM scan_data d
            JOIN product_master pm ON d.sku = pm.sku
            WHERE pm.product_line = ?
        """, (line,)).fetchone()
        ratio = peak / off if off else 0
        print(f"  {line:<22} {peak_label} avg={peak:.2f}  {off_label} avg={off:.2f}  ratio={ratio:.2f}x")
        emit(f"{line}: {peak_label} > {off_label}", peak > off)

    # --- 7. Promo lift ---
    section(7, "Promo lift (during vs 4 weeks pre-promo, at affected retailer stores)")
    print(f"  {'Type':<10} {'Pre-4wk':>10} {'During':>10} {'Lift':>10}")
    for ptype in ("TPR", "Display", "Feature", "BOGO"):
        pre, during = cur.execute(f"""
            WITH promos AS (
                SELECT DISTINCT promo_id, sku, retailer, start_week, end_week
                FROM promotions WHERE promo_type = ?
            ),
            affected AS (
                SELECT p.sku, p.start_week, p.end_week, s.store_id
                FROM promos p
                JOIN stores s ON s.retailer = p.retailer
                            OR (p.retailer = 'Regional' AND s.retailer IN {REGIONAL_CHAINS})
            )
            SELECT
              AVG(CASE WHEN d.week_ending BETWEEN DATE(a.start_week, '-28 days')
                                              AND DATE(a.start_week, '-1 days')
                       THEN d.units_sold END),
              AVG(CASE WHEN d.week_ending BETWEEN a.start_week AND a.end_week
                       THEN d.units_sold END)
            FROM affected a
            JOIN scan_data d ON d.sku = a.sku AND d.store_id = a.store_id
        """, (ptype,)).fetchone()
        if pre and during and pre > 0:
            lift = during / pre
            print(f"  {ptype:<10} {pre:>10.2f} {during:>10.2f} {lift:>9.2f}x")
            emit(f"{ptype} shows lift", lift > 1.0)
        else:
            print(f"  {ptype:<10} {(pre or 0):>10.2f} {(during or 0):>10.2f}      n/a")
            emit(f"{ptype} shows lift", False, "no data")

    # --- 8. Post-promo dip ---
    section(8, "Post-promo dip (3 weeks after vs 4 weeks before)")
    print(f"  {'Type':<10} {'Pre-4wk':>10} {'Post-3wk':>10} {'Ratio':>10}")
    for ptype in ("TPR", "Display", "Feature", "BOGO"):
        pre, post = cur.execute(f"""
            WITH promos AS (
                SELECT DISTINCT promo_id, sku, retailer, start_week, end_week
                FROM promotions WHERE promo_type = ?
            ),
            affected AS (
                SELECT p.sku, p.start_week, p.end_week, s.store_id
                FROM promos p
                JOIN stores s ON s.retailer = p.retailer
                            OR (p.retailer = 'Regional' AND s.retailer IN {REGIONAL_CHAINS})
            )
            SELECT
              AVG(CASE WHEN d.week_ending BETWEEN DATE(a.start_week, '-28 days')
                                              AND DATE(a.start_week, '-1 days')
                       THEN d.units_sold END),
              AVG(CASE WHEN d.week_ending BETWEEN DATE(a.end_week, '+7 days')
                                              AND DATE(a.end_week, '+21 days')
                       THEN d.units_sold END)
            FROM affected a
            JOIN scan_data d ON d.sku = a.sku AND d.store_id = a.store_id
        """, (ptype,)).fetchone()
        if pre and post and pre > 0:
            ratio = post / pre
            print(f"  {ptype:<10} {pre:>10.2f} {post:>10.2f} {ratio:>9.2f}x")
            emit(f"{ptype} shows post-promo dip", ratio < 1.0)
        else:
            print(f"  {ptype:<10} {(pre or 0):>10.2f} {(post or 0):>10.2f}      n/a")
            emit(f"{ptype} shows post-promo dip", False, "no data")

    # --- 9. Launch ramp ---
    section(9, "Launch ramp (late-launch SKUs: weeks 1-4 vs week 13+)")
    early, late = cur.execute("""
        WITH launches AS (
            SELECT sku, MIN(authorized_date) AS launch_date
            FROM distribution_log GROUP BY sku
        )
        SELECT
          AVG(CASE WHEN julianday(d.week_ending) - julianday(l.launch_date) BETWEEN 0 AND 27
                   THEN d.units_sold END),
          AVG(CASE WHEN julianday(d.week_ending) - julianday(l.launch_date) >= 84
                   THEN d.units_sold END)
        FROM scan_data d
        JOIN launches l ON d.sku = l.sku
        WHERE l.launch_date > '2024-05-06'
    """).fetchone()
    if early and late:
        print(f"  Weeks 1-4 avg : {early:>10.2f}")
        print(f"  Week 13+ avg  : {late:>10.2f}")
        print(f"  Ramp ratio    : {late/early:>10.2f}x")
        emit("Late-launch ramp shows growth (week 13+ > weeks 1-4)", late > early)
    else:
        emit("Launch ramp", False, f"early={early}, late={late}")

    # Note: also compute for healthy launches only (excluding failed launches)
    healthy = cur.execute("""
        WITH launches AS (
            SELECT sku, MIN(authorized_date) AS launch_date,
                   MAX(CASE WHEN deauthorized_date IS NOT NULL THEN 1 ELSE 0 END) AS any_deauth
            FROM distribution_log GROUP BY sku
        )
        SELECT
          AVG(CASE WHEN julianday(d.week_ending) - julianday(l.launch_date) BETWEEN 0 AND 27
                   THEN d.units_sold END),
          AVG(CASE WHEN julianday(d.week_ending) - julianday(l.launch_date) >= 84
                   THEN d.units_sold END)
        FROM scan_data d
        JOIN launches l ON d.sku = l.sku
        WHERE l.launch_date > '2024-05-06' AND l.any_deauth = 0
    """).fetchone()
    if healthy[0] and healthy[1]:
        print(f"  (excluding failed launches)  weeks 1-4: {healthy[0]:.2f}  week 13+: {healthy[1]:.2f}  "
              f"ratio: {healthy[1]/healthy[0]:.2f}x")

    # --- 10. Decline pattern ---
    section(10, "Decline pattern (deauthorized SKU x stores: last 8wk vs prior 8wk)")
    last_8, prior_8 = cur.execute("""
        SELECT
          AVG(CASE WHEN julianday(dl.deauthorized_date) - julianday(d.week_ending) BETWEEN 0 AND 56
                   THEN d.units_sold END),
          AVG(CASE WHEN julianday(dl.deauthorized_date) - julianday(d.week_ending) BETWEEN 57 AND 112
                   THEN d.units_sold END)
        FROM scan_data d
        JOIN distribution_log dl ON dl.sku = d.sku AND dl.store_id = d.store_id
        WHERE dl.deauthorized_date IS NOT NULL
    """).fetchone()
    if last_8 and prior_8:
        print(f"  Last 8 weeks before deauth : {last_8:>10.2f}")
        print(f"  Prior 8 weeks              : {prior_8:>10.2f}")
        print(f"  Ratio                      : {last_8/prior_8:>10.2f}x")
        emit("Decline shows lower velocity in last 8wk", last_8 < prior_8)
    else:
        emit("Decline pattern", False, f"last_8={last_8}, prior_8={prior_8}")

    # --- Summary ---
    print(f"\n{'=' * 70}")
    print(f"  Summary: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print("=" * 70)

    con.close()


if __name__ == "__main__":
    main()
