"""Generate the `promotions` table.

Builds ~75 promotional events across the 104-week window, with retailer mix,
promo type mix, seasonal concentration, and a few line-level promos that span
multiple SKUs in the same product line.
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"
SEED = 42

WEEK_1 = date(2024, 5, 6)
TOTAL_WEEKS = 104

REGIONAL_CHAIN_NAMES = {
    "Green Basket Market", "Harbor Fresh", "Prairie Provisions",
    "Mountain Pantry Co", "Southside Grocers",
}

# Retailer-specific promo "personality": frequency, type mix, depth ranges,
# duration. Each retailer behaves differently in real life — Walmart runs many
# shallow weekly TPRs, Costco runs occasional but deep MVMs, etc. The numbers
# below approximate those patterns.
RETAILER_PROMO_PROFILE = {
    "Walmart": {  # frequent, shallow, mostly TPR / Display
        "n_promos": 28,
        "type_weights": [("TPR", 50), ("Display", 30), ("Feature", 15), ("BOGO", 5)],
        "depth_overrides": {
            "TPR":     (0.15, 0.20),
            "Display": (0.10, 0.15),
            "Feature": (0.18, 0.25),
            "BOGO":    (0.50, 0.50),
        },
        "duration_weights": [(1, 60), (2, 35), (3, 5), (4, 0)],
    },
    "Costco": {  # infrequent, deep — Member Value events drive the mix
        "n_promos": 11,
        "type_weights": [("Feature", 40), ("BOGO", 30), ("TPR", 20), ("Display", 10)],
        "depth_overrides": {
            "TPR":     (0.25, 0.32),
            "Display": (0.15, 0.20),
            "Feature": (0.30, 0.45),
            "BOGO":    (0.50, 0.50),
        },
        "duration_weights": [(1, 30), (2, 50), (3, 15), (4, 5)],
    },
    "Whole Foods": {  # moderate cadence, moderate depth, ad-circular heavy
        "n_promos": 16,
        "type_weights": [("TPR", 35), ("Feature", 30), ("Display", 25), ("BOGO", 10)],
        "depth_overrides": {
            "TPR":     (0.15, 0.22),
            "Display": (0.10, 0.15),
            "Feature": (0.20, 0.28),
            "BOGO":    (0.50, 0.50),
        },
        "duration_weights": [(1, 40), (2, 40), (3, 15), (4, 5)],
    },
    "Regional": {  # sporadic, varied depth
        "n_promos": 9,
        "type_weights": [("TPR", 40), ("Display", 25), ("Feature", 25), ("BOGO", 10)],
        "depth_overrides": {
            "TPR":     (0.12, 0.22),
            "Display": (0.08, 0.15),
            "Feature": (0.18, 0.30),
            "BOGO":    (0.50, 0.50),
        },
        "duration_weights": [(1, 35), (2, 40), (3, 15), (4, 10)],
    },
    "UNFI": {   # distributor — uses TPR-equivalent allowances
        "n_promos": 6,
        "type_weights": [("TPR", 60), ("Feature", 25), ("Display", 15), ("BOGO", 0)],
        "depth_overrides": {
            "TPR":     (0.10, 0.18),
            "Display": (0.08, 0.12),
            "Feature": (0.15, 0.22),
            "BOGO":    (0.50, 0.50),
        },
        "duration_weights": [(1, 25), (2, 50), (3, 20), (4, 5)],
    },
    "DTC": {    # email/holiday-driven flash sales
        "n_promos": 5,
        "type_weights": [("TPR", 50), ("Feature", 30), ("BOGO", 20), ("Display", 0)],
        "depth_overrides": {
            "TPR":     (0.18, 0.28),
            "Display": (0.10, 0.15),
            "Feature": (0.25, 0.35),
            "BOGO":    (0.50, 0.50),
        },
        "duration_weights": [(1, 70), (2, 25), (3, 5), (4, 0)],
    },
}

# Seasonal pull: Q4 heaviest, summer next, then spring & BTS, with some off-peak
SEASON_WEIGHTS = [
    ("Q4",      32),  # Nov-Dec
    ("Summer",  22),  # Jun-Jul
    ("Spring",  17),  # Mar-Apr
    ("BTS",     16),  # Aug-Sep
    ("Offpeak", 13),  # everything else
]


def week_start(w: int) -> date:
    return WEEK_1 + timedelta(weeks=w - 1)


def season_for_date(d: date) -> str:
    m = d.month
    if m in (11, 12): return "Q4"
    if m in (6, 7):   return "Summer"
    if m in (8, 9):   return "BTS"
    if m in (3, 4):   return "Spring"
    return "Offpeak"


def weighted_choice(items):
    keys = [k for k, _ in items]
    weights = [w for _, w in items]
    return random.choices(keys, weights=weights, k=1)[0]


def main():
    random.seed(SEED)
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # --- Build SKU → set of retailer categories (only currently-active dist) ---
    products = cur.execute("SELECT sku, product_line FROM product_master ORDER BY sku").fetchall()
    sku_to_line = {sku: pl for sku, pl in products}

    sku_retailers: dict = {}
    for sku, store_ret in cur.execute("""
        SELECT DISTINCT d.sku, s.retailer
        FROM distribution_log d
        JOIN stores s ON d.store_id = s.store_id
        WHERE d.deauthorized_date IS NULL
    """).fetchall():
        if store_ret in ("Walmart", "Costco", "Whole Foods", "UNFI", "DTC"):
            cat = store_ret
        elif store_ret in REGIONAL_CHAIN_NAMES:
            cat = "Regional"
        else:
            continue
        sku_retailers.setdefault(sku, set()).add(cat)

    # --- Group weeks by season ---
    weeks_by_season: dict = {"Q4": [], "Summer": [], "BTS": [], "Spring": [], "Offpeak": []}
    for w in range(1, TOTAL_WEEKS + 1):
        weeks_by_season[season_for_date(week_start(w))].append(w)

    # --- Pick SKUs that get NO promos (long-tail, ~12 SKUs) ---
    all_skus = list(sku_to_line.keys())
    random.shuffle(all_skus)
    no_promo_skus = set(all_skus[:12])

    # --- Build per-retailer promo plan ---
    # Each retailer contributes its configured n_promos with its own type/depth
    # mix. promo_plan is a list of (retailer, promo_type) tuples we will then
    # iterate to assign weeks, SKUs, etc.
    promo_plan: list[tuple[str, str]] = []
    for retailer, profile in RETAILER_PROMO_PROFILE.items():
        n = profile["n_promos"]
        type_counts: dict = {}
        total_w = sum(w for _, w in profile["type_weights"])
        for ptype, w in profile["type_weights"]:
            type_counts[ptype] = round(n * w / total_w)
        # Adjust to match exact n
        diff = n - sum(type_counts.values())
        if diff != 0:
            # Add/remove from the highest-weighted type
            most = max(profile["type_weights"], key=lambda kv: kv[1])[0]
            type_counts[most] += diff
        for ptype, c in type_counts.items():
            promo_plan.extend([(retailer, ptype)] * c)
    random.shuffle(promo_plan)
    n_promos = len(promo_plan)

    promo_rows = []

    for i, (retailer, promo_type) in enumerate(promo_plan, start=1):
        profile = RETAILER_PROMO_PROFILE[retailer]

        # Eligible SKUs for this retailer (excluding no-promo set)
        candidates = [s for s, rets in sku_retailers.items()
                      if retailer in rets and s not in no_promo_skus]
        if not candidates:
            # Fall back: pick any retailer with eligible candidates
            for fb in RETAILER_PROMO_PROFILE:
                fb_cands = [s for s, rets in sku_retailers.items()
                            if fb in rets and s not in no_promo_skus]
                if fb_cands:
                    retailer = fb
                    candidates = fb_cands
                    profile = RETAILER_PROMO_PROFILE[fb]
                    break
            if not candidates:
                continue

        duration = weighted_choice(profile["duration_weights"])
        season = weighted_choice(SEASON_WEIGHTS)
        wk = random.choice(weeks_by_season[season])
        if wk + duration - 1 > TOTAL_WEEKS:
            wk = TOTAL_WEEKS - duration + 1

        start = week_start(wk).isoformat()
        end = week_start(wk + duration - 1).isoformat()

        lo, hi = profile["depth_overrides"][promo_type]
        discount = round(random.uniform(lo, hi), 3)
        scope = "all" if random.random() < 0.7 else "subset"

        # Line promo (~25%) → 3-5 SKUs from same product line, else single SKU
        skus_for_promo = []
        if random.random() < 0.25:
            random.shuffle(candidates)
            for seed_sku in candidates:
                pl = sku_to_line[seed_sku]
                pl_candidates = [s for s in candidates if sku_to_line[s] == pl]
                if len(pl_candidates) >= 3:
                    n = random.randint(3, min(5, len(pl_candidates)))
                    skus_for_promo = random.sample(pl_candidates, n)
                    break
        if not skus_for_promo:
            skus_for_promo = [random.choice(candidates)]

        promo_id = f"PROMO-{i:04d}"
        for sku in skus_for_promo:
            promo_rows.append((
                promo_id, sku, retailer, scope, start, end,
                duration, discount, promo_type,
            ))

    # --- Write to DB ---
    cur.execute("DROP TABLE IF EXISTS promotions")
    cur.execute("""
        CREATE TABLE promotions (
            promo_id            TEXT NOT NULL,
            sku                 TEXT NOT NULL,
            retailer            TEXT NOT NULL,
            store_scope         TEXT NOT NULL,
            start_week          TEXT NOT NULL,
            end_week            TEXT NOT NULL,
            duration_weeks      INTEGER NOT NULL,
            discount_depth_pct  REAL NOT NULL,
            promo_type          TEXT NOT NULL,
            PRIMARY KEY (promo_id, sku)
        )
    """)
    cur.execute("CREATE INDEX idx_promo_sku ON promotions(sku)")
    cur.execute("CREATE INDEX idx_promo_retailer ON promotions(retailer)")
    cur.executemany("""
        INSERT INTO promotions
            (promo_id, sku, retailer, store_scope, start_week, end_week,
             duration_weeks, discount_depth_pct, promo_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, promo_rows)
    con.commit()

    # --- Summary ---
    n_events = cur.execute("SELECT COUNT(DISTINCT promo_id) FROM promotions").fetchone()[0]
    n_rows = cur.execute("SELECT COUNT(*) FROM promotions").fetchone()[0]
    print(f"Total promo events (distinct promo_id): {n_events}")
    print(f"Total promo rows (sku-level entries):   {n_rows}\n")

    print("Events by promo type:")
    for t, c in cur.execute("""
        SELECT promo_type, COUNT(DISTINCT promo_id)
        FROM promotions GROUP BY promo_type
        ORDER BY COUNT(DISTINCT promo_id) DESC
    """).fetchall():
        pct = 100 * c / n_events
        print(f"  {t:<10} {c:>3}  ({pct:.1f}%)")

    print("\nEvents by retailer:")
    for r, c in cur.execute("""
        SELECT retailer, COUNT(DISTINCT promo_id)
        FROM promotions GROUP BY retailer
        ORDER BY COUNT(DISTINCT promo_id) DESC
    """).fetchall():
        pct = 100 * c / n_events
        print(f"  {r:<12} {c:>3}  ({pct:.1f}%)")

    print("\nEvents by quarter:")
    quarter_counts: dict = {}
    for _, start in cur.execute("SELECT DISTINCT promo_id, start_week FROM promotions").fetchall():
        y, m, _ = map(int, start.split("-"))
        q = (m - 1) // 3 + 1
        key = f"{y} Q{q}"
        quarter_counts[key] = quarter_counts.get(key, 0) + 1
    for k in sorted(quarter_counts):
        print(f"  {k}: {quarter_counts[k]}")

    print("\nAverage discount depth by promo type:")
    for t, avg in cur.execute("""
        SELECT promo_type, AVG(discount_depth_pct)
        FROM promotions GROUP BY promo_type ORDER BY promo_type
    """).fetchall():
        print(f"  {t:<10} {avg*100:5.2f}%")

    print("\nDuration distribution:")
    for dur, c in cur.execute("""
        SELECT duration_weeks, COUNT(DISTINCT promo_id)
        FROM promotions GROUP BY duration_weeks ORDER BY duration_weeks
    """).fetchall():
        print(f"  {dur} week(s): {c}")

    print("\nLine promos vs single-SKU promos:")
    for n_skus, c in cur.execute("""
        SELECT n_skus, COUNT(*) FROM (
            SELECT promo_id, COUNT(*) AS n_skus FROM promotions GROUP BY promo_id
        ) GROUP BY n_skus ORDER BY n_skus
    """).fetchall():
        label = "single-SKU" if n_skus == 1 else f"{n_skus}-SKU line promo"
        print(f"  {label}: {c}")

    print(f"\nSKUs with no promos: {len(no_promo_skus)}")
    skus_with_promos = cur.execute("SELECT COUNT(DISTINCT sku) FROM promotions").fetchone()[0]
    print(f"SKUs with at least one promo: {skus_with_promos}")

    con.close()


if __name__ == "__main__":
    main()
