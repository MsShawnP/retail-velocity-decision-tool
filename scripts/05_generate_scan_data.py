"""Generate the `scan_data` table — weekly unit sales for every authorized
SKU x store x week.

Layered model:
  1. Per-SKU base velocity (top/mid/long-tail tier)
  2. Store retailer + volume tier multipliers (Costco bulk, etc.)
  3. Aggregated channel handling for UNFI-AGG and DTC-AGG
  4. Subcategory seasonality scaled by per-SKU seasonality_strength
  5. Per-SKU organic trend (growing / declining / plateau-then-decline)
  6. Cannibalization: new launches dent older same-line SKUs for 8-16 wk
  7. Promo lifts (with muted lift on dirty-data SKUs ~65% of the time)
  8. Launch ramp + pre-deauth decline + post-promo dip
  9. UNFI bulk-order cycle (lumpy 4-6 week peaks at the agg channel)
 10. DTC marketing spikes (6-8 weeks/year, 2-3x baseline)
 11. Stockouts: ~12 (sku, store) episodes of 1-3 weeks at zero units
 12. Multiplicative weekly noise
 13. Retailer-specific wholesale price for revenue calc

Note: this script also UPDATES distribution_log to deauthorize the 2 failed
launch SKUs at a date 16-24 weeks past their launch — that is what makes
"failed launch then deauthorized" consistent across tables.
"""

import random
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"
SEED = 42

WEEK_1_START = date(2024, 5, 6)   # Monday
WEEK_1_END = date(2024, 5, 11)    # Saturday
TOTAL_WEEKS = 104

# Monthly seasonality multipliers per product line (1=Jan ... 12=Dec)
SAUCE_MONTHLY = {
    1: 1.30, 2: 1.20, 3: 1.00, 4: 0.95, 5: 0.90, 6: 0.80,
    7: 0.75, 8: 0.85, 9: 1.00, 10: 1.25, 11: 1.35, 12: 1.40,
}
COND_MONTHLY = {
    1: 0.85, 2: 0.80, 3: 0.95, 4: 1.05, 5: 1.35, 6: 1.45,
    7: 1.50, 8: 1.40, 9: 1.10, 10: 0.95, 11: 0.90, 12: 0.80,
}
PANTRY_MONTHLY = {
    1: 0.95, 2: 0.95, 3: 1.00, 4: 1.00, 5: 1.00, 6: 1.00,
    7: 1.00, 8: 1.00, 9: 1.05, 10: 1.05, 11: 1.15, 12: 1.20,
}
LINE_SEASONALITY = {
    "Artisan Sauces":       SAUCE_MONTHLY,
    "Specialty Condiments": COND_MONTHLY,
    "Pantry Staples":       PANTRY_MONTHLY,
}

REGIONAL_CHAIN_NAMES = {
    "Green Basket Market", "Harbor Fresh", "Prairie Provisions",
    "Mountain Pantry Co", "Southside Grocers",
}

RETAILER_MULT = {
    "Walmart":     1.0,
    "Costco":      3.0,
    "Whole Foods": 0.8,
    # All regional chains
    **{c: 0.7 for c in REGIONAL_CHAIN_NAMES},
}

VOLUME_TIER_MULT = {"A": 1.3, "B": 1.0, "C": 0.7}

PROMO_LIFT_RANGES = {
    "TPR":     (1.8, 2.5),
    "Display": (1.5, 2.0),
    "Feature": (2.0, 3.0),
    "BOGO":    (2.5, 3.5),
}

# UNFI is a distributor, not direct retail — sized at ~15-20% of total business
# (~$4-5M/yr wholesale). 70 equivalent doors lands UNFI in that range given the
# tier'd base velocities below.
UNFI_EQUIVALENT_DOORS = 70

# Direct-to-consumer wholesale-equivalent revenue, split by SKU base velocity.
DTC_ANNUAL_REVENUE = 800_000

# Global multiplier on per-SKU base velocities to land total wholesale revenue
# at ~$23-27M/yr (Cinderhaven's actual scale). Scales physical retail and UNFI
# proportionally; DTC is driven by DTC_ANNUAL_REVENUE and is unaffected.
# Bumped from 0.62 to 0.66 to offset the ~5% revenue reduction from the
# retailer-specific wholesale prices added to sku_costs.
VELOCITY_SCALE = 0.66


# --- Defect detection (mirrors scripts 02 / 02b) ---

def gtin_invalid(gtin: str | None) -> bool:
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


def date_to_week(d_str):
    if d_str is None:
        return None
    d = date.fromisoformat(d_str) if isinstance(d_str, str) else d_str
    return ((d - WEEK_1_START).days // 7) + 1


def main():
    random.seed(SEED)
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = OFF")
    cur = con.cursor()

    # --- Load reference data ---
    products = {
        sku: (pl, subc)
        for sku, pl, subc in cur.execute(
            "SELECT sku, product_line, subcategory FROM product_master"
        ).fetchall()
    }

    # Retailer-specific wholesale prices, indexed by retailer category so we
    # can look up the right contract price for each store row.
    wholesale: dict[str, dict[str, float]] = {}
    for sku, w_walmart, w_costco, w_wf, w_regional, w_unfi, w_dtc, w_base in cur.execute("""
        SELECT sku, wholesale_walmart, wholesale_costco, wholesale_whole_foods,
               wholesale_regional, wholesale_unfi, wholesale_dtc, wholesale_price
        FROM sku_costs
    """).fetchall():
        wholesale[sku] = {
            "Walmart":     w_walmart,
            "Costco":      w_costco,
            "Whole Foods": w_wf,
            "Regional":    w_regional,
            "UNFI":        w_unfi,
            "DTC":         w_dtc,
            "_base":       w_base,
        }
    stores = {
        sid: (ret, vt, bool(is_agg))
        for sid, ret, vt, is_agg in cur.execute(
            "SELECT store_id, retailer, volume_tier, is_aggregated_channel FROM stores"
        ).fetchall()
    }

    def wholesale_for(sku: str, store_retailer: str) -> float:
        """Return the retailer-specific wholesale price for a SKU at a store."""
        if store_retailer in REGIONAL_CHAIN_NAMES:
            cat = "Regional"
        else:
            cat = store_retailer
        return wholesale[sku].get(cat, wholesale[sku]["_base"])

    # Per-SKU defect map for the dirty-data promo muting layer plus the
    # full integer count for the time-to-shelf delay logic below.
    defect_rows = cur.execute("""
        SELECT sku, gtin14, upc, case_length_in, case_width_in, case_height_in,
               brand_owner, country_of_origin
        FROM product_master
    """).fetchall()
    sku_has_defects: dict[str, bool] = {}
    sku_defect_count: dict[str, int] = {}
    for sku_, gtin, upc, l, ww, h, brand, country in defect_rows:
        n = 0
        if gtin_invalid(gtin):
            n += 1
        if upc_missing(upc):
            n += 1
        if l is None or ww is None or h is None:
            n += 1
        if brand is None or str(brand).strip() == "":
            n += 1
        if country is None or str(country).strip() == "":
            n += 1
        sku_defect_count[sku_] = n
        sku_has_defects[sku_] = n > 0

    dist_rows = cur.execute(
        "SELECT sku, store_id, authorized_date, deauthorized_date FROM distribution_log"
    ).fetchall()

    # --- Time-to-shelf delay (defect-driven) -----------------------------
    # The gap between authorized_date and the first scan_data row for a
    # (SKU, store) pair varies with the SKU's defect count. Clean SKUs hit the
    # shelf in 3-7 days; severe-defect SKUs sit in distribution purgatory for
    # 6-12 weeks before any scan shows up.
    #
    # Independent RNGs (SEED + 7 / + 8) so the existing seed sequence for the
    # rest of this script's randomness — base velocities, promo lifts, etc.
    # — is not disturbed.
    delay_rng = random.Random(SEED + 8)

    def delay_days_for(dc: int) -> int:
        if dc == 0:
            return delay_rng.randint(3, 7)
        if dc <= 2:
            return delay_rng.randint(14, 42)
        if dc <= 4:
            return delay_rng.randint(28, 56)
        return delay_rng.randint(42, 84)

    sku_store_delay_days: dict[tuple[str, str], int] = {}
    for sku_, sid_, _ad, _dd in dist_rows:
        sku_store_delay_days[(sku_, sid_)] = delay_days_for(sku_defect_count.get(sku_, 0))

    # --- Ghost pairs: authorized but never made it to shelf --------------
    # 2-3 of the worst-defect SKUs (by defect count, descending) at 3-5
    # specific physical stores each emit NO scan_data at all. The audit
    # narrative: data was so dirty the retailer gave up before ever scanning
    # the item. We pick the worst-available SKUs even if no SKU hits 5+ defects
    # so the narrative still has supporting evidence in the data.
    ghost_rng = random.Random(SEED + 7)
    physical_stores_by_sku: dict[str, list[str]] = {}
    for sku_, sid_, _ad, _dd in dist_rows:
        if sid_ in ("UNFI-AGG", "DTC-AGG"):
            continue
        physical_stores_by_sku.setdefault(sku_, []).append(sid_)
    severe_skus = sorted(
        [s for s, n in sku_defect_count.items()
         if n >= 2 and len(physical_stores_by_sku.get(s, [])) >= 3],
        key=lambda s: (-sku_defect_count[s], s),
    )
    ghost_skus = severe_skus[: ghost_rng.randint(2, 3)]
    ghost_pairs: set[tuple[str, str]] = set()
    for gs in ghost_skus:
        candidates = physical_stores_by_sku.get(gs, [])
        n_stores = ghost_rng.randint(3, 5)
        chosen = ghost_rng.sample(candidates, min(n_stores, len(candidates)))
        for sid_ in chosen:
            ghost_pairs.add((gs, sid_))

    # --- Tier inference: rank SKUs by # of distribution rows ---
    sku_row_counts = defaultdict(int)
    for sku, _, _, _ in dist_rows:
        sku_row_counts[sku] += 1

    sku_tier = {}
    for i, (sku, _) in enumerate(
        sorted(sku_row_counts.items(), key=lambda kv: -kv[1])
    ):
        sku_tier[sku] = "top" if i < 18 else ("mid" if i < 18 + 45 else "longtail")

    # Cover the (rare) SKU with no distribution rows at all
    for sku in products:
        sku_tier.setdefault(sku, "longtail")

    # --- Per-SKU base velocity (units / store / week) ---
    base_velocity = {}
    for sku, tier in sku_tier.items():
        if tier == "top":
            base_velocity[sku] = random.uniform(8, 15) * VELOCITY_SCALE
        elif tier == "mid":
            base_velocity[sku] = random.uniform(3, 7) * VELOCITY_SCALE
        else:
            base_velocity[sku] = random.uniform(0.5, 2) * VELOCITY_SCALE

    # --- Per-SKU launch week (min authorized_date) ---
    sku_launch_week = {}
    for sku, _, ad, _ in dist_rows:
        wk = date_to_week(ad)
        if sku not in sku_launch_week or wk < sku_launch_week[sku]:
            sku_launch_week[sku] = wk

    # "Newer SKU" candidates are those launched in the back half of the window
    # (week 60+). Threshold is intentionally above the upper bound (12 weeks)
    # of the data-quality setup delay added in script 02 — without this guard,
    # week-1 SKUs whose authorization slipped a few weeks would falsely qualify
    # as "newer launches" and be eligible for the failed-launch picks.
    late_launch_skus = [s for s, lw in sku_launch_week.items() if lw > 60]

    # Pick 2 "failed launches" — they will stall and then get partially
    # deauthorized. Selection is WEIGHTED BY DEFECT COUNT: a failed launch in
    # this dataset reflects data-quality problems (the chargeback narrative),
    # not random bad luck. Without this weighting the 2 failed launches were
    # often clean SKUs, drowning out the defect-vs-deauth signal the audit
    # report relies on.
    # Exclude ghost SKUs so the "never made it to shelf" SKUs don't double up
    # as "stalled then deauthed" — those are different audit narratives.
    failed_candidates = [s for s in sorted(late_launch_skus) if s not in ghost_skus]
    failed_launch_skus: set[str] = set()
    if failed_candidates:
        weights = [1 + 5 * sku_defect_count.get(s, 0) for s in failed_candidates]
        # Sample 2 distinct SKUs weighted by defect count
        attempts = 0
        while len(failed_launch_skus) < min(2, len(failed_candidates)) and attempts < 50:
            pick = random.choices(failed_candidates, weights=weights, k=1)[0]
            failed_launch_skus.add(pick)
            attempts += 1

    # --- Update distribution_log to deauthorize failed-launch SKUs ---
    # Only deauth a fraction of the SKU's stores so the contribution to total
    # deauths stays within audit-target range (40-80 pairs). The remaining
    # stores keep their stalled scan_data without a deauth_date, representing
    # "still on shelf, just not selling" — a slower-burning failure mode.
    failed_deauth_week = {}
    for sku in sorted(failed_launch_skus):
        lw = sku_launch_week[sku]
        deauth_w = min(TOTAL_WEEKS, lw + random.randint(16, 24))
        failed_deauth_week[sku] = deauth_w
        deauth_date = (WEEK_1_START + timedelta(weeks=deauth_w - 1)).isoformat()
        # Cap failed-launch deauths at 5-15 stores (absolute, not fraction).
        # Failed launches at every Walmart and Costco store would be 200+ pairs
        # — way more than the audit-target deauth volume. The remaining stores
        # keep stalled scan_data without a deauth, modeling "still on shelf,
        # underperforming" rather than "officially dropped."
        active_rows = cur.execute(
            "SELECT rowid FROM distribution_log "
            "WHERE sku = ? AND deauthorized_date IS NULL "
            "AND store_id NOT IN ('UNFI-AGG','DTC-AGG')",
            (sku,)
        ).fetchall()
        if active_rows:
            n_deauth = min(len(active_rows), random.randint(3, 8))
            chosen_rowids = random.sample([r[0] for r in active_rows], n_deauth)
            cur.executemany(
                "UPDATE distribution_log SET deauthorized_date = ? WHERE rowid = ?",
                [(deauth_date, rid) for rid in chosen_rowids],
            )
    con.commit()

    # Reload dist_rows after updating failed launches
    dist_rows = cur.execute(
        "SELECT sku, store_id, authorized_date, deauthorized_date FROM distribution_log"
    ).fetchall()

    # --- Build (sku, store_id) → list of promo intervals  ---
    sku_authorized_stores = defaultdict(set)
    for sku, sid, _, _ in dist_rows:
        sku_authorized_stores[sku].add(sid)

    # Group physical stores by retailer category
    stores_by_cat = defaultdict(list)
    for sid, (ret, _vt, is_agg) in stores.items():
        if is_agg:
            continue
        cat = ret if ret in ("Walmart", "Costco", "Whole Foods", "UNFI", "DTC") else "Regional"
        stores_by_cat[cat].append(sid)
    # Aggregated channels are reachable as their own retailer label
    stores_by_cat["UNFI"].append("UNFI-AGG")
    stores_by_cat["DTC"].append("DTC-AGG")

    promo_rows = cur.execute("""
        SELECT promo_id, sku, retailer, store_scope, start_week, end_week,
               duration_weeks, discount_depth_pct, promo_type
        FROM promotions
    """).fetchall()

    # Build per-(sku, store_id) authorization windows so we can guard against
    # stranded promos: a promo that runs while the SKU is not yet authorized
    # (or is already deauthorized) at a given store should not produce lift.
    sku_store_windows = defaultdict(list)  # (sku, sid) -> [(auth_w, last_active_w), ...]
    for sku, sid, ad, dd in dist_rows:
        aw = date_to_week(ad)
        last_active = (date_to_week(dd) - 1) if dd else TOTAL_WEEKS
        sku_store_windows[(sku, sid)].append((aw, last_active))

    # (sku, store_id) -> [(start_w, end_w, type, discount, dip_end_w)]
    sku_store_promos = defaultdict(list)
    stranded_promos = 0  # promos with zero in-window stores after the guard
    promo_eligible_counts = []  # per-promo (eligible_pre, eligible_post) for reporting

    for promo_id, sku, retailer, scope, sw_str, ew_str, _dur, disc, ptype in promo_rows:
        sw = date_to_week(sw_str)
        ew = date_to_week(ew_str)
        eligible = [s for s in stores_by_cat.get(retailer, []) if s in sku_authorized_stores[sku]]
        if scope == "subset" and eligible:
            n = max(1, int(round(len(eligible) * random.uniform(0.30, 0.50))))
            eligible = random.sample(eligible, min(n, len(eligible)))

        # Stranded-promo guard: keep only stores where the SKU's authorization
        # window overlaps the promo period [sw, ew].
        in_window = []
        for sid in eligible:
            for aw, last_active in sku_store_windows.get((sku, sid), []):
                if aw <= ew and last_active >= sw:
                    in_window.append(sid)
                    break

        promo_eligible_counts.append((promo_id, sku, len(eligible), len(in_window)))
        if not in_window:
            stranded_promos += 1
            continue

        dip_end = ew + random.choice([2, 3])
        for sid in in_window:
            sku_store_promos[(sku, sid)].append((sw, ew, ptype, disc, dip_end))

    # --- Decline-end factor per (sku, store_id) for non-failed-launch deauths ---
    # Pre-pick once so the decline curve is monotonic noise-aside.
    decline_end_factor = {}
    for sku, sid, _ad, dd in dist_rows:
        if dd and sku not in failed_launch_skus:
            decline_end_factor[(sku, sid)] = random.uniform(0.4, 0.6)

    # --- DTC dollar split: weight by base velocity ---
    dtc_skus = {sku for sku, sid, _, _ in dist_rows if sid == "DTC-AGG"}
    dtc_base_total = sum(base_velocity[s] for s in dtc_skus) or 1.0
    dtc_weekly_total = DTC_ANNUAL_REVENUE / 52
    dtc_weekly_dollars = {
        s: dtc_weekly_total * base_velocity[s] / dtc_base_total for s in dtc_skus
    }

    # --- Pre-compute week dates and months ---
    week_end_iso = [(WEEK_1_END + timedelta(weeks=w - 1)).isoformat() for w in range(1, TOTAL_WEEKS + 1)]
    week_month = [(WEEK_1_END + timedelta(weeks=w - 1)).month for w in range(1, TOTAL_WEEKS + 1)]

    # --- Per-SKU organic velocity trend ---------------------------------
    # 15% growing, 10% declining, 10% plateau-then-decline, rest stable.
    sku_list = list(products.keys())
    trend_pool = list(sku_list)
    random.shuffle(trend_pool)
    n_total = len(trend_pool)
    n_growing = round(n_total * 0.15)
    n_declining = round(n_total * 0.10)
    n_plateau = round(n_total * 0.10)

    sku_organic_trend: dict[str, tuple[str, float]] = {}
    for s in trend_pool[:n_growing]:
        sku_organic_trend[s] = ("growing", random.uniform(0.10, 0.25))
    for s in trend_pool[n_growing:n_growing + n_declining]:
        sku_organic_trend[s] = ("declining", random.uniform(0.15, 0.30))
    for s in trend_pool[n_growing + n_declining:n_growing + n_declining + n_plateau]:
        sku_organic_trend[s] = ("plateau_decline", random.uniform(0.15, 0.30))

    def organic_trend_factor(sku: str, week: int) -> float:
        info = sku_organic_trend.get(sku)
        if info is None:
            return 1.0
        pattern, mag = info
        progress = (week - 1) / max(1, TOTAL_WEEKS - 1)  # 0..1 across the window
        if pattern == "growing":
            # Starts at (1 - mag/2), ends at (1 + mag/2). Centered on 1.0.
            return 1.0 + mag * (progress - 0.5)
        if pattern == "declining":
            return 1.0 - mag * (progress - 0.5)
        # plateau_decline: flat first half, then decline in second half
        if progress < 0.5:
            return 1.0
        half = (progress - 0.5) * 2  # 0..1 across the second half
        return 1.0 - mag * half

    # --- Per-SKU seasonality strength -----------------------------------
    # Most SKUs respond normally to category seasonality; some are highly
    # seasonal (1.4-1.7x), some are aseasonal (0.2-0.5x).
    sku_seasonality_strength: dict[str, float] = {}
    for s in sku_list:
        r = random.random()
        if r < 0.10:
            sku_seasonality_strength[s] = random.uniform(0.20, 0.50)
        elif r < 0.25:
            sku_seasonality_strength[s] = random.uniform(1.40, 1.70)
        else:
            sku_seasonality_strength[s] = random.uniform(0.85, 1.15)

    # --- Cannibalization periods ---------------------------------------
    # When a new SKU launches (lw > 60), it dents older same-line SKUs by
    # 5-15% for 8-16 weeks.
    cannibalization_periods: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    for new_sku, lw in sku_launch_week.items():
        if lw <= 60:
            continue
        new_pl = products.get(new_sku, ("", ""))[0]
        targets = [
            t for t, lw_t in sku_launch_week.items()
            if t != new_sku and products.get(t, ("", ""))[0] == new_pl and lw_t < lw
        ]
        if not targets:
            continue
        n_targets = min(len(targets), random.randint(2, 4))
        chosen = random.sample(targets, n_targets)
        for tgt in chosen:
            duration = random.randint(8, 16)
            factor = random.uniform(0.85, 0.95)
            cannibalization_periods[tgt].append((lw, lw + duration, factor))

    # --- UNFI bulk-order weeks -----------------------------------------
    # Distributor cadence: bulk order every 4-6 weeks. Multipliers are tuned
    # so the long-run average is ~1.0 and the existing UNFI revenue holds.
    unfi_bulk_weeks: set[int] = set()
    nxt = random.randint(2, 5)
    while nxt <= TOTAL_WEEKS:
        unfi_bulk_weeks.add(nxt)
        nxt += random.randint(4, 6)

    # --- DTC marketing spike weeks -------------------------------------
    # 6-8 randomly placed spike weeks across the 104-week window, biased
    # to land near holiday windows for realism.
    dtc_holiday_weeks = [w for w in range(1, TOTAL_WEEKS + 1)
                         if week_month[w - 1] in (3, 5, 11, 12)]
    n_spikes = random.randint(6, 8)
    spike_pool = list(dtc_holiday_weeks) if dtc_holiday_weeks else list(range(1, TOTAL_WEEKS + 1))
    random.shuffle(spike_pool)
    dtc_spike_weeks: set[int] = set(spike_pool[:n_spikes])

    # --- Stockout episodes ---------------------------------------------
    # 12 (sku, store) pairs each lose 1-3 weeks of velocity to a stockout.
    # Restricted to physical stores with a long enough activity window.
    stockout_blocks: set[tuple[str, str, int]] = set()
    physical_pairs = [(sku, sid) for (sku, sid), windows in sku_store_windows.items()
                      if not stores[sid][2]
                      and any(la - aw >= 8 for aw, la in windows)]
    random.shuffle(physical_pairs)
    for sku, sid in physical_pairs[:14]:
        windows = sku_store_windows.get((sku, sid), [])
        if not windows:
            continue
        aw, la = windows[0]
        duration = random.randint(1, 3)
        if la - aw < duration + 4:
            continue
        start = random.randint(aw + 4, la - duration)
        for wk in range(start, start + duration):
            stockout_blocks.add((sku, sid, wk))

    # --- Build scan_data ---
    cur.execute("DROP TABLE IF EXISTS scan_data")
    cur.execute("""
        CREATE TABLE scan_data (
            sku          TEXT NOT NULL,
            store_id     TEXT NOT NULL,
            week_ending  TEXT NOT NULL,
            units_sold   INTEGER NOT NULL,
            dollars_sold REAL NOT NULL,
            PRIMARY KEY (sku, store_id, week_ending)
        )
    """)

    BATCH = 100_000
    buffer = []
    n_rows_total = 0

    insert_sql = (
        "INSERT INTO scan_data (sku, store_id, week_ending, units_sold, dollars_sold) "
        "VALUES (?, ?, ?, ?, ?)"
    )

    for sku, sid, ad, dd in dist_rows:
        # Ghost pair: authorized but never made it to shelf — skip entirely.
        if (sku, sid) in ghost_pairs:
            continue

        product_line, _subc = products[sku]
        seasonality = LINE_SEASONALITY[product_line]
        store_ret, store_vt, is_agg = stores[sid]
        ws_price = wholesale_for(sku, store_ret)

        auth_w = date_to_week(ad)
        deauth_w = date_to_week(dd) if dd else None

        # Defect-driven time-to-first-scan delay. Convert auth_date + delay_days
        # into the first week_ending that lands on or after that target.
        delay_days = sku_store_delay_days.get((sku, sid), 0)
        target_d = date.fromisoformat(ad) + timedelta(days=delay_days)
        delta = (target_d - WEEK_1_END).days
        first_w = 1 if delta <= 0 else (delta + 6) // 7 + 1
        first_w = max(first_w, 1)

        last_w = min(TOTAL_WEEKS, (deauth_w - 1) if deauth_w else TOTAL_WEEKS)
        if first_w > last_w:
            continue

        sku_base = base_velocity[sku]
        is_failed = sku in failed_launch_skus
        sku_launch = sku_launch_week.get(sku, 1)
        sku_dirty = sku_has_defects.get(sku, False)
        season_strength = sku_seasonality_strength.get(sku, 1.0)
        cannib_list = cannibalization_periods.get(sku, [])

        # Base velocity per week for this (sku, store) pair
        if is_agg:
            if sid == "UNFI-AGG":
                base_per_week = sku_base * UNFI_EQUIVALENT_DOORS
            else:  # DTC-AGG
                base_per_week = dtc_weekly_dollars.get(sku, 0.0) / max(ws_price, 1.0)
        else:
            ret_mult = RETAILER_MULT.get(store_ret, 1.0)
            tier_mult = VOLUME_TIER_MULT.get(store_vt, 1.0)
            base_per_week = sku_base * ret_mult * tier_mult

        promos = sku_store_promos.get((sku, sid), [])
        decline_floor = decline_end_factor.get((sku, sid))

        for w in range(first_w, last_w + 1):
            # Stockout: zero this week and skip the rest of the math
            if (sku, sid, w) in stockout_blocks:
                buffer.append((sku, sid, week_end_iso[w - 1], 0, 0.0))
                if len(buffer) >= BATCH:
                    cur.executemany(insert_sql, buffer)
                    n_rows_total += len(buffer)
                    buffer.clear()
                continue

            # Seasonality scaled by per-SKU strength
            seasonal_raw = seasonality[week_month[w - 1]]
            seasonal = 1.0 + (seasonal_raw - 1.0) * season_strength

            # Organic trend (growing / declining / plateau-then-decline)
            trend = organic_trend_factor(sku, w)

            # Cannibalization from newer SKUs in the same line
            cannib = 1.0
            for cs, ce, cf in cannib_list:
                if cs <= w <= ce:
                    cannib = cf
                    break

            # Launch ramp
            if sku_launch > 1:
                wsl = w - sku_launch + 1
                if is_failed:
                    if wsl <= 4:
                        ramp = random.uniform(0.30, 0.50)
                    else:
                        ramp = random.uniform(0.40, 0.50)
                else:
                    if wsl <= 4:
                        ramp = random.uniform(0.30, 0.50)
                    elif wsl <= 8:
                        ramp = random.uniform(0.50, 0.70)
                    elif wsl <= 13:
                        ramp = random.uniform(0.70, 0.90)
                    else:
                        ramp = 1.0
            else:
                ramp = 1.0

            # Pre-deauth decline (skip for failed launches; their stall IS the trajectory)
            decline = 1.0
            if decline_floor is not None and deauth_w is not None:
                weeks_to_deauth = deauth_w - w
                if 0 < weeks_to_deauth <= 10:
                    progress = (10 - weeks_to_deauth) / 10
                    decline = 1.0 - progress * (1.0 - decline_floor)

            # Promo lift / post-promo dip (with dirty-data muting)
            promo_mult = 1.0
            promo_active = False
            promo_discount = 0.0
            for sw, ew, ptype, disc, dip_end in promos:
                if sw <= w <= ew:
                    lo, hi = PROMO_LIFT_RANGES[ptype]
                    raw_lift = random.uniform(lo, hi)
                    if sku_dirty and random.random() < 0.65:
                        # Dirty data screws up shelf execution: shoppers can't
                        # find or scan the item, so the lift is muted.
                        raw_lift = 1.0 + (raw_lift - 1.0) * random.uniform(0.30, 0.55)
                    promo_mult = raw_lift
                    promo_active = True
                    promo_discount = disc
                    break
                if ew < w <= dip_end:
                    promo_mult = random.uniform(0.70, 0.85)
                    break

            # Aggregated-channel cycles
            agg_cycle = 1.0
            if sid == "UNFI-AGG":
                if w in unfi_bulk_weeks:
                    agg_cycle = random.uniform(2.2, 2.8)
                else:
                    agg_cycle = random.uniform(0.55, 0.80)
            elif sid == "DTC-AGG" and w in dtc_spike_weeks:
                agg_cycle = random.uniform(2.0, 3.0)

            noise = random.uniform(0.75, 1.25)

            v = (base_per_week * seasonal * trend * cannib
                 * ramp * decline * promo_mult * agg_cycle * noise)
            units = max(0, int(round(v)))

            effective_price = ws_price * (1 - promo_discount) if promo_active else ws_price
            dollars = round(units * effective_price, 2)

            buffer.append((sku, sid, week_end_iso[w - 1], units, dollars))

            if len(buffer) >= BATCH:
                cur.executemany(insert_sql, buffer)
                n_rows_total += len(buffer)
                buffer.clear()

    if buffer:
        cur.executemany(insert_sql, buffer)
        n_rows_total += len(buffer)
        buffer.clear()

    cur.execute("CREATE INDEX idx_scan_sku ON scan_data(sku)")
    cur.execute("CREATE INDEX idx_scan_store ON scan_data(store_id)")
    cur.execute("CREATE INDEX idx_scan_week ON scan_data(week_ending)")
    con.commit()

    # --- Summary ---
    print(f"Total scan_data rows inserted: {n_rows_total:,}\n")

    print(f"Failed-launch SKUs (stalled & deauthorized): {sorted(failed_launch_skus)}")
    for sku in sorted(failed_launch_skus):
        lw = sku_launch_week[sku]
        dw = failed_deauth_week[sku]
        launch_d = (WEEK_1_END + timedelta(weeks=lw - 1)).isoformat()
        deauth_d = (WEEK_1_START + timedelta(weeks=dw - 1)).isoformat()
        print(f"  {sku}: launched week {lw} ({launch_d}) -> deauthorized week {dw} ({deauth_d})")

    print(f"\nGhost SKUs (authorized, NO scan data): {sorted(ghost_skus)}")
    by_ghost: dict[str, list[str]] = {}
    for sku, sid in sorted(ghost_pairs):
        by_ghost.setdefault(sku, []).append(sid)
    for sku, sids in by_ghost.items():
        print(f"  {sku}: {len(sids)} stores never scanned ({sku_defect_count[sku]} defects)")

    print("\nFirst-scan gap from auth_date (sample by defect bucket):")
    bucket_gaps: dict[int, list[int]] = {0: [], 1: [], 2: [], 3: []}
    for (sku, sid), delay in sku_store_delay_days.items():
        if (sku, sid) in ghost_pairs:
            continue
        dc = sku_defect_count.get(sku, 0)
        b = 0 if dc == 0 else (1 if dc <= 2 else (2 if dc <= 4 else 3))
        bucket_gaps[b].append(delay)
    labels = {0: "Clean (0)", 1: "Minor (1-2)", 2: "Moderate (3-4)", 3: "Severe (5+)"}
    for b in (0, 1, 2, 3):
        vals = bucket_gaps[b]
        if vals:
            print(f"  {labels[b]:<16} n={len(vals):>5}  delay days mean={sum(vals)/len(vals):>5.1f}  min={min(vals)}  max={max(vals)}")

    print("\nUnits sold by retailer category:")
    rows = cur.execute("""
        SELECT
            CASE
                WHEN s.is_aggregated_channel = 1 THEN s.retailer || ' (agg)'
                WHEN s.retailer IN ('Walmart','Costco','Whole Foods') THEN s.retailer
                ELSE 'Regional'
            END AS cat,
            COUNT(*) AS rows,
            SUM(d.units_sold) AS units,
            ROUND(SUM(d.dollars_sold), 0) AS dollars
        FROM scan_data d JOIN stores s ON d.store_id = s.store_id
        GROUP BY cat ORDER BY units DESC
    """).fetchall()
    print(f"  {'Category':<18} {'Rows':>10} {'Units':>14} {'$ (2yr ws)':>14} {'$ (annual)':>14} {'% of total':>10}")
    total_dollars = sum(d for _, _, _, d in rows)
    for cat, n, u, dol in rows:
        annual = dol / 2.0
        pct = 100.0 * dol / total_dollars if total_dollars else 0
        print(f"  {cat:<18} {n:>10,} {u:>14,} {dol:>14,.0f} {annual:>14,.0f} {pct:>9.1f}%")
    print(f"  {'TOTAL':<18} {'':>10} {'':>14} {total_dollars:>14,.0f} {total_dollars/2:>14,.0f}")

    print("\nUnits sold by tier:")
    tier_units = defaultdict(int)
    tier_rows = defaultdict(int)
    sku_tier_rows = cur.execute("SELECT sku, SUM(units_sold), COUNT(*) FROM scan_data GROUP BY sku").fetchall()
    for sku, u, n in sku_tier_rows:
        tier_units[sku_tier[sku]] += u or 0
        tier_rows[sku_tier[sku]] += n
    for tier in ("top", "mid", "longtail"):
        print(f"  {tier:<10} units={tier_units[tier]:>12,}  rows={tier_rows[tier]:>10,}")

    print("\nWeekly dollars sold (head and tail of the time window):")
    rows = cur.execute("""
        SELECT week_ending, SUM(units_sold), ROUND(SUM(dollars_sold), 0)
        FROM scan_data GROUP BY week_ending ORDER BY week_ending
    """).fetchall()
    for r in rows[:3]:
        print(f"  {r[0]}  units={r[1]:>8,}  $={r[2]:>12,.0f}")
    print("  ...")
    for r in rows[-3:]:
        print(f"  {r[0]}  units={r[1]:>8,}  $={r[2]:>12,.0f}")

    print(f"\nStranded promos (no in-window stores after guard): {stranded_promos}")
    partially_pruned = sum(1 for _, _, pre, post in promo_eligible_counts if 0 < post < pre)
    print(f"Promos partially pruned by guard:               {partially_pruned}")

    print("\nPromo lift spot-check (10 sample promos at affected retailer stores):")
    print(f"  {'Promo':<12} {'SKU':<10} {'Retailer':<14} {'Type':<8} {'Baseline':>10} {'OnPromo':>10} {'Lift':>7}")
    spot_rows = cur.execute("""
        SELECT pd.promo_id, pd.sku, pd.retailer, pd.promo_type,
            (SELECT AVG(d.units_sold) FROM scan_data d
             JOIN stores s ON d.store_id = s.store_id
             WHERE d.sku = pd.sku
               AND (s.retailer = pd.retailer
                    OR (pd.retailer = 'Regional' AND s.retailer IN
                        ('Green Basket Market','Harbor Fresh','Prairie Provisions','Mountain Pantry Co','Southside Grocers')))
               AND d.week_ending NOT BETWEEN pd.start_week AND pd.end_week) AS base_avg,
            (SELECT AVG(d.units_sold) FROM scan_data d
             JOIN stores s ON d.store_id = s.store_id
             WHERE d.sku = pd.sku
               AND (s.retailer = pd.retailer
                    OR (pd.retailer = 'Regional' AND s.retailer IN
                        ('Green Basket Market','Harbor Fresh','Prairie Provisions','Mountain Pantry Co','Southside Grocers')))
               AND d.week_ending BETWEEN pd.start_week AND pd.end_week) AS promo_avg
        FROM (SELECT DISTINCT promo_id, sku, retailer, start_week, end_week, promo_type FROM promotions) pd
        WHERE pd.retailer NOT IN ('UNFI', 'DTC')
        ORDER BY pd.promo_id LIMIT 10
    """).fetchall()
    for promo_id, sku, ret, ptype, base, on in spot_rows:
        if base and on and base > 0:
            print(f"  {promo_id:<12} {sku:<10} {ret:<14} {ptype:<8} {base:>10.2f} {on:>10.2f} {on/base:>6.2f}x")
        else:
            print(f"  {promo_id:<12} {sku:<10} {ret:<14} {ptype:<8} {(base or 0):>10.2f} {(on or 0):>10.2f}    n/a")

    con.close()


if __name__ == "__main__":
    main()
