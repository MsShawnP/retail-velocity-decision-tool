"""
One-off analysis script: find a "protagonist" SKU for the companion document.

Looks healthy in aggregate (YoY total volume flat/up), but baseline velocity
(non-promo weeks) is declining and promotional activity is masking the trend.
"""
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

DB = "data/cinderhaven_product_master.db"
TODAY = date(2026, 5, 5)
MOST_RECENT_WEEK = date(2026, 5, 2)

# 52/52 windows
LAST52_START  = date(2025, 5, 4)   # 52 weeks back from 2026-05-02
LAST52_END    = date(2026, 5, 2)
PRIOR52_START = date(2024, 5, 4)
PRIOR52_END   = date(2025, 5, 3)

# 26/26 windows for baseline trend
RECENT26_START = date(2025, 11, 3)
RECENT26_END   = date(2026, 5, 2)
PRIOR26_START  = date(2025, 5, 4)
PRIOR26_END    = date(2025, 11, 2)

LAUNCH_CUTOFF = date(2024, 11, 5)  # 18 months ago

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ---- product master & costs
products = {r["sku"]: dict(r) for r in cur.execute(
    "SELECT sku, product_name, product_line, subcategory, msrp FROM product_master")}

trade_pct = {}
for r in cur.execute("SELECT * FROM sku_costs"):
    trade_pct[r["sku"]] = {
        "Walmart":     r["trade_spend_pct_walmart"]     or 0,
        "Costco":      r["trade_spend_pct_costco"]      or 0,
        "Whole Foods": r["trade_spend_pct_whole_foods"] or 0,
        "UNFI":        r["trade_spend_pct_unfi"]        or 0,
        "DTC":         r["trade_spend_pct_dtc"]         or 0,
        # regional retailers all share the regional pct
        "_regional":   r["trade_spend_pct_regional"]    or 0,
    }
REGIONAL = {"Green Basket Market", "Harbor Fresh", "Mountain Pantry Co",
            "Prairie Provisions", "Southside Grocers"}

def trade_pct_for(sku, retailer):
    p = trade_pct.get(sku)
    if not p: return 0
    if retailer in REGIONAL: return p["_regional"]
    return p.get(retailer, 0)

# ---- store -> retailer
store_retailer = {r["store_id"]: r["retailer"] for r in cur.execute(
    "SELECT store_id, retailer FROM stores")}

# ---- promotions: build (sku, week) -> set of retailers on promo
promo_weeks = defaultdict(dict)  # sku -> {week_str: set(retailers)}
for r in cur.execute("SELECT sku, retailer, start_week, end_week FROM promotions"):
    # promo dates are Monday week-start; scan_data uses Saturday week-ending. shift +5d.
    sw = date.fromisoformat(r["start_week"]) + timedelta(days=5)
    ew = date.fromisoformat(r["end_week"])   + timedelta(days=5)
    w = sw
    while w <= ew:
        wk = w.isoformat()
        promo_weeks[r["sku"]].setdefault(wk, set()).add(r["retailer"])
        w += timedelta(days=7)

# ---- scan data aggregated per (sku, week, retailer) for trade spend,
#      and per (sku, week) for velocity
# Pull active store count per (sku, week) to compute velocity per store-week
# Velocity convention: units / active_store_week (sum over all retailers)

scan_rows = cur.execute("""
    SELECT sku, store_id, week_ending, units_sold, dollars_sold
    FROM scan_data
""")

# Pre-aggregate
sku_week_units    = defaultdict(lambda: defaultdict(float))   # sku -> wk -> units
sku_week_stores   = defaultdict(lambda: defaultdict(int))     # sku -> wk -> count of selling stores
sku_week_dollars_by_ret = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))  # sku -> wk -> ret -> $

for r in scan_rows:
    sku = r["sku"]; wk = r["week_ending"]
    ret = store_retailer.get(r["store_id"], "Unknown")
    sku_week_units[sku][wk]  += r["units_sold"]
    sku_week_stores[sku][wk] += 1
    sku_week_dollars_by_ret[sku][wk][ret] += r["dollars_sold"]

# ---- compute metrics per SKU
results = []

# pre-compute category totals (avg current velocity per product_line)
line_units_curr = defaultdict(float)
line_storeweeks_curr = defaultdict(float)

for sku, wkmap in sku_week_units.items():
    pl = products.get(sku, {}).get("product_line", "?")
    for wk, units in wkmap.items():
        if RECENT26_START.isoformat() <= wk <= RECENT26_END.isoformat():
            line_units_curr[pl] += units
            line_storeweeks_curr[pl] += sku_week_stores[sku][wk]

line_avg_velocity = {
    pl: (line_units_curr[pl] / line_storeweeks_curr[pl]) if line_storeweeks_curr[pl] else 0
    for pl in line_units_curr
}

for sku, wkmap in sku_week_units.items():
    if sku not in products: continue
    p = products[sku]
    pl = p["product_line"]

    units_last52 = units_prior52 = 0
    units_recent26 = units_prior26 = 0
    storeweeks_recent26 = storeweeks_prior26 = 0

    nonpromo_units_recent = nonpromo_sw_recent = 0
    nonpromo_units_prior  = nonpromo_sw_prior  = 0

    promo_wk_count_last52 = total_wk_count_last52 = 0
    promo_wk_count_recent26 = total_wk_count_recent26 = 0
    promo_wk_count_prior26  = total_wk_count_prior26  = 0

    trade_spend_total = 0.0

    first_week = min(wkmap.keys())

    for wk, units in wkmap.items():
        sw = sku_week_stores[sku][wk]
        on_promo = wk in promo_weeks.get(sku, {})

        if LAST52_START.isoformat() <= wk <= LAST52_END.isoformat():
            units_last52 += units
            total_wk_count_last52 += 1
            if on_promo: promo_wk_count_last52 += 1
        if PRIOR52_START.isoformat() <= wk <= PRIOR52_END.isoformat():
            units_prior52 += units

        if RECENT26_START.isoformat() <= wk <= RECENT26_END.isoformat():
            units_recent26 += units
            storeweeks_recent26 += sw
            total_wk_count_recent26 += 1
            if on_promo:
                promo_wk_count_recent26 += 1
            else:
                nonpromo_units_recent += units
                nonpromo_sw_recent    += sw

        if PRIOR26_START.isoformat() <= wk <= PRIOR26_END.isoformat():
            units_prior26 += units
            storeweeks_prior26 += sw
            total_wk_count_prior26 += 1
            if on_promo:
                promo_wk_count_prior26 += 1
            else:
                nonpromo_units_prior += units
                nonpromo_sw_prior    += sw

        # trade spend on this week if on promo
        if on_promo:
            promo_retailers = promo_weeks[sku][wk]
            for ret, dols in sku_week_dollars_by_ret[sku][wk].items():
                if ret in promo_retailers:
                    trade_spend_total += dols * trade_pct_for(sku, ret)

    # YoY total volume change
    yoy_pct = ((units_last52 - units_prior52) / units_prior52 * 100) if units_prior52 else None

    # Baseline velocity (units / store-week, non-promo weeks only)
    baseline_recent = (nonpromo_units_recent / nonpromo_sw_recent) if nonpromo_sw_recent else 0
    baseline_prior  = (nonpromo_units_prior  / nonpromo_sw_prior)  if nonpromo_sw_prior  else 0
    baseline_pct    = ((baseline_recent - baseline_prior) / baseline_prior * 100) if baseline_prior else None

    # Current overall velocity (recent 26)
    current_velocity = (units_recent26 / storeweeks_recent26) if storeweeks_recent26 else 0

    # Promo intensity
    promo_pct_last52   = (promo_wk_count_last52 / total_wk_count_last52 * 100) if total_wk_count_last52 else 0
    promo_pct_recent26 = (promo_wk_count_recent26 / total_wk_count_recent26 * 100) if total_wk_count_recent26 else 0
    promo_pct_prior26  = (promo_wk_count_prior26 / total_wk_count_prior26 * 100) if total_wk_count_prior26 else 0
    promo_increasing   = promo_pct_recent26 - promo_pct_prior26  # pp delta

    cat_avg = line_avg_velocity.get(pl, 0)
    vel_vs_cat = (current_velocity / cat_avg * 100) if cat_avg else 0

    is_new_launch = date.fromisoformat(first_week) >= LAUNCH_CUTOFF

    # gap score: looks-healthy minus actually-in-trouble
    # reward: positive YoY + heavy promo % + high promo delta + high trade spend
    # penalize: negative baseline trend (more negative = more dramatic)
    if yoy_pct is None or baseline_pct is None:
        gap_score = -999
    else:
        gap_score = (
            max(yoy_pct, -20)                          # cap downside contribution
            - baseline_pct                              # negative baseline boosts score
            + promo_pct_recent26 * 0.3
            + max(promo_increasing, 0) * 0.5
            + (trade_spend_total / 5000)                # scale trade $ in
        )
        # hard requirement: only score things that look healthy AND have declining baseline
        if yoy_pct < -5 or baseline_pct > 0:
            gap_score -= 100

    results.append({
        "sku": sku,
        "name": p["product_name"],
        "line": pl,
        "yoy_pct": yoy_pct,
        "units_last52": units_last52,
        "units_prior52": units_prior52,
        "baseline_recent": baseline_recent,
        "baseline_prior": baseline_prior,
        "baseline_pct": baseline_pct,
        "current_velocity": current_velocity,
        "cat_avg_velocity": cat_avg,
        "vel_vs_cat_pct": vel_vs_cat,
        "promo_pct_last52": promo_pct_last52,
        "promo_pct_recent26": promo_pct_recent26,
        "promo_pct_prior26": promo_pct_prior26,
        "promo_delta_pp": promo_increasing,
        "trade_spend": trade_spend_total,
        "first_week": first_week,
        "is_new_launch": is_new_launch,
        "gap_score": gap_score,
    })

# DEBUG: distribution of metrics
print("\n--- Distribution of YoY %, baseline %, promo %, trade $ ---")
import statistics
yoy = [r["yoy_pct"] for r in results if r["yoy_pct"] is not None]
base = [r["baseline_pct"] for r in results if r["baseline_pct"] is not None]
promo = [r["promo_pct_recent26"] for r in results]
ts = [r["trade_spend"] for r in results]
def stats(label, vals):
    if not vals: return
    vs = sorted(vals)
    print(f"  {label:<22}  min={vs[0]:.1f}  p25={vs[len(vs)//4]:.1f}  med={vs[len(vs)//2]:.1f}  p75={vs[3*len(vs)//4]:.1f}  max={vs[-1]:.1f}")
stats("YoY total %", yoy)
stats("Baseline %", base)
stats("Promo % recent26", promo)
stats("Trade $", ts)

print(f"\n  SKUs with YoY >= -5%:   {sum(1 for v in yoy if v >= -5)}")
print(f"  SKUs with baseline < 0: {sum(1 for v in base if v < 0)}")
print(f"  SKUs with promo% >= 20: {sum(1 for v in promo if v >= 20)}")
print(f"  SKUs with promo% >= 10: {sum(1 for v in promo if v >= 10)}")
print(f"  SKUs with trade$ >= 5k: {sum(1 for v in ts if v >= 5000)}")
print(f"  SKUs with trade$ >= 1k: {sum(1 for v in ts if v >= 1000)}")
print(f"  SKUs with trade$ > 0:   {sum(1 for v in ts if v > 0)}")

# Hard requirement: looks healthy AND baseline declining (the core pattern).
# Promo activity / trade $ contribute via gap_score rather than a hard cut,
# so we still surface a top 5.
candidates = [r for r in results
              if r["yoy_pct"] is not None and r["baseline_pct"] is not None
              and r["yoy_pct"] >= -5            # flat or up YoY (looks healthy)
              and r["baseline_pct"] < -5]       # baseline meaningfully declining

# Re-rank: emphasize the gap and burn $; keep promo as soft signal
for r in candidates:
    r["gap_score"] = (
        r["yoy_pct"]                          # YoY pop
        - r["baseline_pct"]                   # baseline drop magnitude
        + r["promo_pct_recent26"] * 0.5
        + max(r["promo_delta_pp"], 0) * 0.7
        + (r["trade_spend"] / 2000)
        + (5 if r["is_new_launch"] else 0)
    )

candidates.sort(key=lambda r: r["gap_score"], reverse=True)

print(f"\nTotal SKUs analyzed: {len(results)}")
print(f"Candidates matching protagonist pattern: {len(candidates)}\n")

print("="*120)
print("TOP 5 PROTAGONIST CANDIDATES")
print("="*120)

for i, r in enumerate(candidates[:5], 1):
    launch_tag = "  [NEW LAUNCH <=18mo]" if r["is_new_launch"] else ""
    print(f"\n#{i}  {r['sku']}  |  {r['name']}  |  {r['line']}{launch_tag}")
    print(f"     First week of sales: {r['first_week']}")
    print(f"     YoY total volume:    {r['units_prior52']:>10,.0f} -> {r['units_last52']:>10,.0f} units   ({r['yoy_pct']:+.1f}%)")
    print(f"     Baseline velocity:   {r['baseline_prior']:.2f} -> {r['baseline_recent']:.2f} units/store-week ({r['baseline_pct']:+.1f}%)")
    print(f"     Current velocity:    {r['current_velocity']:.2f} u/store-wk   |  {r['line']} avg: {r['cat_avg_velocity']:.2f}  ({r['vel_vs_cat_pct']:.0f}% of cat)")
    print(f"     Promo week %:        prior 26w {r['promo_pct_prior26']:.0f}% -> recent 26w {r['promo_pct_recent26']:.0f}%   ({r['promo_delta_pp']:+.0f} pp)")
    print(f"     Trade spend (life):  ${r['trade_spend']:>12,.0f}")
    print(f"     Gap score:           {r['gap_score']:.1f}")

# Also dump the rest of the top 15 in a compact table for context
print("\n" + "="*120)
print("Next 10 (for context):")
print(f"{'SKU':<10} {'NAME':<35} {'LINE':<22} {'YoY%':>7} {'Base%':>8} {'Promo%':>7} {'Trade$':>10} {'Vel':>6}  Launch")
for r in candidates[5:15]:
    print(f"{r['sku']:<10} {r['name'][:34]:<35} {r['line'][:21]:<22} "
          f"{r['yoy_pct']:>6.1f}% {r['baseline_pct']:>7.1f}% {r['promo_pct_recent26']:>6.0f}% "
          f"{r['trade_spend']:>10,.0f} {r['current_velocity']:>6.2f}  "
          f"{'NEW' if r['is_new_launch'] else ''}")
