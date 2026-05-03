"""Generate the `distribution_log` table.

Records which SKUs are authorized in which stores, when authorization began,
and (for the few that have lost shelf space) when it was revoked. Coverage
follows a top/mid/long-tail breakdown so the resulting velocity data has a
realistic head-and-tail shape.
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"
SEED = 42

WEEK_1 = date(2024, 5, 6)
TOTAL_WEEKS = 104

REGIONAL_CHAINS = [
    "Green Basket Market",
    "Harbor Fresh",
    "Prairie Provisions",
    "Mountain Pantry Co",
    "Southside Grocers",
]

# Earliest deauthorization week — guarantees ~3 months of chargeback history
# (chargebacks start 2024-12) before any SKU is dropped for data-quality issues.
# WEEK_1 = 2024-05-06; week 44 starts 2025-03-03.
EARLIEST_DEAUTH_WEEK = 44

# Retailer-specific deauthorization aggression:
#   Walmart / Costco hammer problem SKUs harder than the natural-channel banners.
#   Whole Foods / Regional are slower to delist (smaller chains, more curated assortment).
#   UNFI is a distributor, sits in the middle, but is modeled as an aggregated
#   channel so doesn't have per-store deauths in this dataset.
RETAILER_DEAUTH_MULT = {
    "Walmart":     1.5,
    "Costco":      1.5,
    "Whole Foods": 0.7,
    "Regional":    0.7,
}


def week_start(w: int) -> date:
    return WEEK_1 + timedelta(weeks=w - 1)


def stores_for_token(token: str, stores_by_retailer: dict) -> list:
    """Map an active_retailers token to a list of physical store_ids."""
    if token == "Walmart":
        return list(stores_by_retailer.get("Walmart", []))
    if token == "Whole Foods":
        return list(stores_by_retailer.get("Whole Foods", []))
    if token == "Costco":
        return list(stores_by_retailer.get("Costco", []))
    if token == "Regional":
        pool = []
        for c in REGIONAL_CHAINS:
            pool.extend(stores_by_retailer.get(c, []))
        return pool
    return []


def gtin_invalid(gtin: str | None) -> bool:
    """Return True if the GTIN-14 is missing, malformed, or fails the
    Cinderhaven audit's check-digit algorithm (weights 1,3 alternating from
    the leftmost digit)."""
    if not gtin or len(gtin) != 14 or not gtin.isdigit():
        return True
    d = [int(c) for c in gtin]
    s = sum(d[i] * (1 if (12 - i) % 2 == 0 else 3) for i in range(13))
    return (10 - s % 10) % 10 != d[13]


def upc_missing(upc: str | None) -> bool:
    if upc is None:
        return True
    s = str(upc).strip()
    return s == "" or s in ("TBD", "N/A", "0", "00000000000", "000000000000")


def compute_defect_count(row: tuple) -> int:
    """Count product-master data quality issues for one SKU row.

    Row tuple: (gtin14, upc, case_length_in, case_width_in, case_height_in,
                brand_owner, country_of_origin)
    """
    gtin, upc, l, w, h, brand, country = row
    n = 0
    if gtin_invalid(gtin):
        n += 1
    if upc_missing(upc):
        n += 1
    if l is None or w is None or h is None:
        n += 1
    if brand is None or str(brand).strip() == "":
        n += 1
    if country is None or str(country).strip() == "":
        n += 1
    return n


def setup_delay_weeks(defect_count: int, rng: random.Random) -> int:
    """Time-to-shelf delay (in weeks) caused by dirty product master data.

    0 issues -> 0 weeks (clean SKUs go through item setup on schedule)
    1-2     -> 2-6 weeks (one or two corrections needed)
    3+      -> 4-12 weeks (multi-issue SKUs sit in retailer purgatory)
    """
    if defect_count == 0:
        return 0
    if defect_count <= 2:
        return rng.randint(2, 6)
    return rng.randint(4, 12)


def deauth_count_for_sku(defect_count: int, n_stores: int, rng: random.Random) -> int:
    """How many of this SKU's physical authorizations get deauthorized.

    Calibrated against this dataset (~39 clean / 50 minor SKUs) to land total
    deauths in the 40-80 range, with the gradient by defect bucket the audit
    report depends on:

      Clean (0)   -> 0-2 stores lost, mostly 0 (category resets only).
      Minor (1-2) -> 1-5 stores lost, occasionally more.
      Moderate    -> 5-15 stores (heavy delist).
      Severe (5+) -> 10-30 stores (the auditor's worst-offender narrative).
    """
    if defect_count == 0:
        # 55% of clean SKUs see no deauth at all. The remaining 45% lose one
        # store (category reset / seasonal delist) — keeps clean share of total
        # deauths in the 15-25% audit-target range without polluting Spearman.
        if rng.random() < 0.55:
            return 0
        return 1
    if defect_count == 1:
        # All 1-defect SKUs lose 1-2 stores.
        return min(n_stores, rng.randint(1, 2))
    if defect_count == 2:
        # All 2-defect SKUs lose 2-3 stores.
        return min(n_stores, rng.randint(2, 3))
    if defect_count <= 4:
        # Moderate-defect SKUs lose 4-8 stores.
        return min(n_stores, rng.randint(4, 8))
    # Severe (5+ defects) — the audit's worst-offender narrative.
    return min(n_stores, rng.randint(6, 12))


def retailer_category(retailer: str) -> str:
    """Group physical retailers by deauth-tolerance category."""
    if retailer in ("Walmart", "Costco", "Whole Foods"):
        return retailer
    return "Regional"


def weighted_sample_without_replacement(items: list, weights: list[float], k: int,
                                        rng: random.Random) -> list:
    """Sample k distinct items from `items` weighted by `weights` (no replacement).

    Uses the Efraimidis-Spirakis trick: u^(1/w) keys, sort, take top-k.
    """
    if k <= 0 or not items:
        return []
    keyed = [(rng.random() ** (1.0 / max(w, 1e-9)), it) for it, w in zip(items, weights)]
    keyed.sort(reverse=True)
    return [it for _, it in keyed[:min(k, len(items))]]


def main():
    random.seed(SEED)
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    products = cur.execute(
        "SELECT sku, active_retailers FROM product_master ORDER BY sku"
    ).fetchall()

    # Per-SKU data quality defects from product_master — drive realistic
    # time-to-shelf delays on the authorized_date below.
    defect_rows = cur.execute("""
        SELECT sku, gtin14, upc, case_length_in, case_width_in, case_height_in,
               brand_owner, country_of_origin
        FROM product_master
    """).fetchall()
    sku_defect_count = {
        sku: compute_defect_count(rest) for sku, *rest in
        ((r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in defect_rows)
    }
    # Pre-pick the random delay per SKU so the delay is stable across the
    # sku's many rows. Use a separate Random instance seeded deterministically
    # so existing seeds for the rest of the script aren't disturbed.
    delay_rng = random.Random(SEED + 1)
    sku_setup_delay = {
        sku: setup_delay_weeks(n, delay_rng) for sku, n in sku_defect_count.items()
    }

    stores_by_retailer: dict = {}
    for sid, ret in cur.execute(
        "SELECT store_id, retailer FROM stores WHERE is_aggregated_channel = 0"
    ).fetchall():
        stores_by_retailer.setdefault(ret, []).append(sid)

    # --- Tier assignment (90 SKUs total) ---
    sku_list = [s for s, _ in products]
    shuffled = list(sku_list)
    random.shuffle(shuffled)
    top_skus = set(shuffled[:18])         # top performers
    mid_skus = set(shuffled[18:18 + 45])  # mid-tier
    long_tail_skus = set(shuffled[18 + 45:])  # long-tail

    # --- Newer launches: 9 SKUs, somewhere in the last 40 weeks (weeks 65-100) ---
    new_pool = list(sku_list)
    random.shuffle(new_pool)
    new_skus = {sku: random.randint(65, 100) for sku in new_pool[:9]}

    # Reverse map: store_id -> retailer category, for retailer-specific deauth math.
    store_retailer = {
        sid: ret
        for ret, sids in stores_by_retailer.items()
        for sid in sids
    }

    rows = []

    for sku, active in products:
        if not active:
            continue
        tokens = [t.strip() for t in active.split(";")]

        # Base launch week from the original logic (week 1 for legacy SKUs,
        # 65-100 for the 9 new launches), plus the time-to-shelf delay caused
        # by product-master data quality issues at this SKU.
        base_launch_week = new_skus.get(sku, 1)
        delay = sku_setup_delay.get(sku, 0)
        launch_week = min(base_launch_week + delay, TOTAL_WEEKS - 4)
        auth_date = week_start(launch_week).isoformat()

        if sku in top_skus:
            coverage = random.uniform(0.80, 1.00)
        elif sku in mid_skus:
            coverage = random.uniform(0.40, 0.70)
        else:
            coverage = random.uniform(0.10, 0.30)

        # Aggregated channels: one row per channel, no deauthorization
        if "UNFI" in tokens:
            rows.append((sku, "UNFI-AGG", auth_date, None))
        if "DTC" in tokens:
            rows.append((sku, "DTC-AGG", auth_date, None))

        # Physical retailer authorizations
        for tok in tokens:
            pool = stores_for_token(tok, stores_by_retailer)
            if not pool:
                continue
            n = max(1, int(round(len(pool) * coverage)))
            n = min(n, len(pool))
            for sid in random.sample(pool, n):
                rows.append((sku, sid, auth_date, None))

    # --- Defect-driven deauthorizations -------------------------------------
    # Per SKU: pick a deauth count from the SKU's defect bucket. Then weight
    # WHICH physical stores get deauthed by the retailer's tolerance — Walmart
    # and Costco are 1.5x more likely to drop a problem SKU than Whole Foods
    # or Regional. Deauth dates are dispersed across [launch + 12w, week 100],
    # always after at least ~3 months of chargeback history (chargebacks start
    # 2024-12; week 44 = 2025-03-03).
    deauth_rng = random.Random(SEED + 2)

    physical_rows_by_sku: dict[str, list[int]] = {}
    for i, (sku, sid, _ad, _dd) in enumerate(rows):
        if sid in ("UNFI-AGG", "DTC-AGG"):
            continue
        physical_rows_by_sku.setdefault(sku, []).append(i)

    chosen_set: set[int] = set()
    for sku, idxs in physical_rows_by_sku.items():
        dc = sku_defect_count.get(sku, 0)
        n_deauth = deauth_count_for_sku(dc, len(idxs), deauth_rng)
        if n_deauth <= 0:
            continue
        weights = []
        for i in idxs:
            ret = store_retailer.get(rows[i][1])
            cat = retailer_category(ret) if ret else "Regional"
            weights.append(RETAILER_DEAUTH_MULT.get(cat, 1.0))
        chosen = weighted_sample_without_replacement(idxs, weights, n_deauth, deauth_rng)
        for j in chosen:
            chosen_set.add(j)

    # Apply deauthorization dates per chosen row.
    for i in chosen_set:
        sku_, sid_, ad_, _ = rows[i]
        auth_d = date.fromisoformat(ad_)
        auth_w = ((auth_d - WEEK_1).days // 7) + 1
        # Need auth + 12 weeks AND chargeback history of 2-3 months.
        min_w = max(auth_w + 12, EARLIEST_DEAUTH_WEEK)
        max_w = TOTAL_WEEKS - 4  # week 100
        if min_w >= max_w:
            min_w = max(1, max_w - 4)
        deauth_week = deauth_rng.randint(min_w, max_w)
        deauth_date = week_start(deauth_week).isoformat()
        rows[i] = (sku_, sid_, ad_, deauth_date)

    # --- Write to DB ---
    cur.execute("DROP TABLE IF EXISTS distribution_log")
    cur.execute("""
        CREATE TABLE distribution_log (
            sku                TEXT NOT NULL,
            store_id           TEXT NOT NULL,
            authorized_date    TEXT NOT NULL,
            deauthorized_date  TEXT,
            PRIMARY KEY (sku, store_id, authorized_date)
        )
    """)
    cur.execute("CREATE INDEX idx_distlog_sku ON distribution_log(sku)")
    cur.execute("CREATE INDEX idx_distlog_store ON distribution_log(store_id)")
    cur.executemany(
        "INSERT INTO distribution_log (sku, store_id, authorized_date, deauthorized_date) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    con.commit()

    # --- Summary ---
    print(f"Total rows inserted: {len(rows)}\n")

    # Defect-driven setup delay breakdown
    from collections import Counter
    defect_buckets = Counter(
        (0 if n == 0 else (1 if n <= 2 else 2)) for n in sku_defect_count.values()
    )
    delays_applied = sum(1 for d in sku_setup_delay.values() if d > 0)
    print("Time-to-shelf delays from product-master defects:")
    print(f"  0 issues  -> on schedule:    {defect_buckets[0]} SKUs")
    print(f"  1-2 issues -> 2-6 wk delay:  {defect_buckets[1]} SKUs")
    print(f"  3+ issues  -> 4-12 wk delay: {defect_buckets[2]} SKUs")
    print(f"  Total SKUs with delayed onboarding: {delays_applied}")
    if delays_applied:
        delay_values = [d for d in sku_setup_delay.values() if d > 0]
        print(f"  Avg delay (delayed SKUs): {sum(delay_values)/len(delay_values):.1f} weeks")
    print()

    print("Rows by retailer:")
    for ret, c in cur.execute("""
        SELECT s.retailer, COUNT(*)
        FROM distribution_log d
        JOIN stores s ON d.store_id = s.store_id
        GROUP BY s.retailer
        ORDER BY COUNT(*) DESC
    """).fetchall():
        print(f"  {ret:<25} {c}")

    deauth_count = cur.execute(
        "SELECT COUNT(*) FROM distribution_log WHERE deauthorized_date IS NOT NULL"
    ).fetchone()[0]
    print(f"\nDeauthorized rows: {deauth_count}")

    new_sku_count = cur.execute(
        "SELECT COUNT(DISTINCT sku) FROM distribution_log "
        f"WHERE authorized_date > '{WEEK_1.isoformat()}'"
    ).fetchone()[0]
    print(f"SKUs launched after week 1: {new_sku_count}\n")

    print("SKUs launched after week 1 (sku, launch date):")
    for sku, ad in cur.execute("""
        SELECT sku, MIN(authorized_date)
        FROM distribution_log
        WHERE authorized_date > ?
        GROUP BY sku
        ORDER BY MIN(authorized_date)
    """, (WEEK_1.isoformat(),)).fetchall():
        print(f"  {sku}  ->  {ad}")

    print("\nSKUs with deauthorizations (sku, # stores lost):")
    for sku, c in cur.execute("""
        SELECT sku, COUNT(*)
        FROM distribution_log
        WHERE deauthorized_date IS NOT NULL
        GROUP BY sku
        ORDER BY COUNT(*) DESC
    """).fetchall():
        print(f"  {sku}  ->  {c} stores")

    # Defect-rate gradient: confirms data-quality drives delistings, not noise.
    print("\nDeauthorization rate by defect severity:")
    bucket_totals: dict[int, list[int]] = {0: [0, 0], 1: [0, 0], 2: [0, 0], 3: [0, 0]}
    for sku, sid, _ad, dd in rows:
        if sid in ("UNFI-AGG", "DTC-AGG"):
            continue
        dc = sku_defect_count.get(sku, 0)
        b = 0 if dc == 0 else (1 if dc <= 2 else (2 if dc <= 4 else 3))
        bucket_totals[b][0] += 1
        if dd is not None:
            bucket_totals[b][1] += 1
    labels = {
        0: "Clean (0 defects)         target 0-2%",
        1: "Minor (1-2 defects)       target 3-8%",
        2: "Moderate (3-4 defects)    target 10-20%",
        3: "Severe (5+ defects)       target 20-40%",
    }
    for b in (0, 1, 2, 3):
        total, deauths = bucket_totals[b]
        pct = (100.0 * deauths / total) if total else 0.0
        print(f"  {labels[b]:<48} {deauths:>4}/{total:<5}  {pct:>5.1f}%")
    n_clean_deauths = bucket_totals[0][1]
    total_deauths = sum(b[1] for b in bucket_totals.values())
    if total_deauths:
        share = 100.0 * n_clean_deauths / total_deauths
        print(f"\n  Clean-SKU share of all deauths (target 20-30%): {share:.1f}%")

    print("\nTier assignment summary:")
    print(f"  Top performers (~80-100% coverage):  {len(top_skus)} SKUs")
    print(f"  Mid-tier       (~40-70% coverage):   {len(mid_skus)} SKUs")
    print(f"  Long-tail      (~10-30% coverage):   {len(long_tail_skus)} SKUs")

    con.close()


if __name__ == "__main__":
    main()
