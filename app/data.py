"""Cinderhaven Velocity Tool -- data layer.

All database queries live here. Every function that was decorated with
``@st.cache_data`` in velocity_tool.py is now decorated with
``@cache.memoize(timeout=3600)`` using flask-caching with FileSystemCache.

SQL queries and DataFrame logic are kept IDENTICAL to the Streamlit version.
"""

from __future__ import annotations

import pandas as pd
from flask_caching import Cache

from constants import (
    REGIONAL_CHAINS,
    THRESHOLDS,
    VOLUME_TIER_MULT,
)
from db import get_pool, get_raw_conn

# ============================================================
# Cache setup (FileSystemCache, 1-hour default)
# ============================================================

cache = Cache(config={
    "CACHE_TYPE": "FileSystemCache",
    "CACHE_DIR": "/tmp/dash-cache",
    "CACHE_DEFAULT_TIMEOUT": 3600,
})


def init_cache(app) -> None:
    """Bind the cache to a Flask/Dash server instance."""
    cache.init_app(app)


# ============================================================
# Helpers
# ============================================================

def _return_conn(conn) -> None:
    """Return a raw connection to the pool after pd.read_sql finishes."""
    try:
        get_pool().putconn(conn)
    except Exception:
        pass


def retailer_clause(retailer: str) -> tuple[str, list]:
    """Return (sql_clause, params) for a stores-table filter on retailer."""
    if retailer == "All Retailers":
        return ("1=1", [])
    if retailer == "Regional":
        ph = ",".join("%s" for _ in REGIONAL_CHAINS)
        return (f"s.retailer IN ({ph})", list(REGIONAL_CHAINS))
    return ("s.retailer = %s", [retailer])


def _promo_to_scan_weeks(start_week: str, end_week: str) -> list[str]:
    """Saturday-aligned helper: scan_data uses week-ending-Saturday, promotions
    table uses Monday week-start. Shifting promo dates by +5 days lines them up
    with the corresponding scan week."""
    s = pd.to_datetime(start_week) + pd.Timedelta(days=5)
    e = pd.to_datetime(end_week) + pd.Timedelta(days=5)
    out = []
    cur = s
    while cur <= e:
        out.append(cur.date().isoformat())
        cur += pd.Timedelta(days=7)
    return out


# ============================================================
# Utility lookups
# ============================================================

@cache.memoize(timeout=3600)
def get_product_lines() -> list[str]:
    conn = get_raw_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT product_line FROM dim_products ORDER BY product_line"
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        _return_conn(conn)


@cache.memoize(timeout=3600)
def get_skus_for_line(product_line: str) -> list[tuple[str, str]]:
    """Return [(sku, product_name), ...] for one product line."""
    conn = get_raw_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT sku, product_name FROM dim_products "
            "WHERE product_line = %s ORDER BY sku",
            (product_line,),
        )
        return cur.fetchall()
    finally:
        _return_conn(conn)


@cache.memoize(timeout=3600)
def get_latest_week() -> str:
    conn = get_raw_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(week_ending) FROM stg_scan_data")
        return cur.fetchone()[0]
    finally:
        _return_conn(conn)


@cache.memoize(timeout=3600)
def get_promo_skus(retailer: str) -> list[str]:
    conn = get_raw_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT sku FROM stg_promotions WHERE retailer = %s ORDER BY sku",
            (retailer,),
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        _return_conn(conn)


# ============================================================
# Story data functions
# ============================================================

@cache.memoize(timeout=3600)
def get_monday_morning_summary(protagonist: str, n_show: int = 18) -> pd.DataFrame:
    """52wk vs prior-52wk units & dollars per SKU.

    Builds a CEO-style pivot summary: a mix of the highest-volume SKUs (the
    ones that show up in any executive report) and a few weak performers
    so the YoY range looks like a real list -- not just a green-arrows
    cherry-pick. Sorted by YoY unit change descending (best on top), with
    the protagonist guaranteed to land in the top half so its +15% reads as
    "yet another healthy SKU" rather than a standout.
    """
    latest = get_latest_week()
    conn = get_raw_conn()
    try:
        sql = """
            SELECT * FROM (
                SELECT pm.sku, pm.product_name, pm.product_line,
                       SUM(CASE WHEN (%s::date - d.week_ending::date) < 364
                                THEN d.units_sold ELSE 0 END) AS units_cur,
                       SUM(CASE WHEN (%s::date - d.week_ending::date) >= 364
                                 AND (%s::date - d.week_ending::date) < 728
                                THEN d.units_sold ELSE 0 END) AS units_prior,
                       SUM(CASE WHEN (%s::date - d.week_ending::date) < 364
                                THEN d.dollars_sold ELSE 0 END) AS dollars_cur,
                       SUM(CASE WHEN (%s::date - d.week_ending::date) >= 364
                                 AND (%s::date - d.week_ending::date) < 728
                                THEN d.dollars_sold ELSE 0 END) AS dollars_prior
                FROM stg_scan_data d JOIN dim_products pm ON d.sku = pm.sku
                GROUP BY pm.sku, pm.product_name, pm.product_line
            ) sub WHERE units_prior > 0
        """
        df = pd.read_sql(sql, conn, params=[latest] * 6)
    finally:
        _return_conn(conn)
    df["units_yoy_pct"] = (df["units_cur"] - df["units_prior"]) / df["units_prior"] * 100
    df["dollars_yoy_pct"] = (df["dollars_cur"] - df["dollars_prior"]) / df["dollars_prior"] * 100

    # Stratified sample so the YoY column shows a realistic spread
    n_winners = (n_show + 1) // 2
    n_losers = n_show - n_winners
    winners_pool = df[df["units_yoy_pct"] > 0].nlargest(n_winners * 2, "units_cur")
    winners = winners_pool.nlargest(n_winners, "units_cur").copy()
    if protagonist not in set(winners["sku"]):
        prot = df[df["sku"] == protagonist]
        if not prot.empty:
            winners = pd.concat([winners.iloc[:n_winners - 1], prot], ignore_index=True)
    losers = df[df["units_yoy_pct"] <= 0].nlargest(n_losers, "units_cur")
    out = pd.concat([winners, losers], ignore_index=True)
    return out.sort_values("units_yoy_pct", ascending=False).reset_index(drop=True)


@cache.memoize(timeout=3600)
def get_sku_weekly_velocity(sku: str) -> pd.DataFrame:
    """Per-week total + baseline velocity (units / store-week). Promo flag set
    from the union of all promo windows on this SKU regardless of retailer."""
    conn = get_raw_conn()
    try:
        promos = pd.read_sql(
            "SELECT start_week, end_week FROM stg_promotions WHERE sku=%s",
            conn, params=[sku],
        )
    finally:
        _return_conn(conn)
    promo_set: set[str] = set()
    for _, r in promos.iterrows():
        promo_set.update(_promo_to_scan_weeks(r["start_week"], r["end_week"]))

    conn2 = get_raw_conn()
    try:
        df = pd.read_sql(
            """
            SELECT week_ending,
                   AVG(units_sold) AS velocity,
                   COUNT(*) AS doors,
                   SUM(units_sold) AS units_total,
                   SUM(dollars_sold) AS dollars_total
            FROM stg_scan_data WHERE sku=%s
            GROUP BY week_ending ORDER BY week_ending
            """,
            conn2, params=[sku],
        )
    finally:
        _return_conn(conn2)
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    df["on_promo"] = df["week_ending"].dt.date.astype(str).isin(promo_set)
    # baseline_v: velocity in non-promo weeks only (NaN on promo weeks so the
    # plotted line breaks rather than connecting through the spike)
    df["baseline_v"] = df["velocity"].where(~df["on_promo"])
    return df


@cache.memoize(timeout=3600)
def get_promo_hangover_data(sku: str) -> pd.DataFrame:
    """For each promo on the SKU, compute pre / during / post velocity at the
    promo's retailer. Pre = 4 weeks before start. Post = 4 weeks after end."""
    conn = get_raw_conn()
    try:
        promos = pd.read_sql(
            """
            SELECT promo_id, retailer, start_week, end_week, duration_weeks,
                   discount_depth_pct, promo_type
            FROM stg_promotions WHERE sku=%s ORDER BY start_week
            """,
            conn, params=[sku],
        )
    finally:
        _return_conn(conn)
    rows = []
    for _, p in promos.iterrows():
        ret = p["retailer"]
        ret_clause, ret_params = retailer_clause(ret)
        is_agg = ret in ("UNFI", "DTC")
        # Saturday-align the promo dates
        start_we = (pd.to_datetime(p["start_week"]) + pd.Timedelta(days=5)).date().isoformat()
        end_we   = (pd.to_datetime(p["end_week"])   + pd.Timedelta(days=5)).date().isoformat()
        pre_start  = (pd.to_datetime(p["start_week"]) + pd.Timedelta(days=5) - pd.Timedelta(weeks=4)).date().isoformat()
        pre_end    = (pd.to_datetime(p["start_week"]) + pd.Timedelta(days=5) - pd.Timedelta(days=1)).date().isoformat()
        post_start = (pd.to_datetime(p["end_week"])   + pd.Timedelta(days=5) + pd.Timedelta(days=7)).date().isoformat()
        post_end   = (pd.to_datetime(p["end_week"])   + pd.Timedelta(days=5) + pd.Timedelta(weeks=4)).date().isoformat()

        conn_inner = get_raw_conn()
        try:
            cur = conn_inner.cursor()

            def _avg_vel(start: str, end: str) -> float | None:
                sql = f"""
                    SELECT AVG(d.units_sold)
                    FROM stg_scan_data d
                    JOIN stg_stores s ON d.store_id = s.store_id
                    WHERE d.sku = %s AND {ret_clause} AND s.is_aggregated_channel = %s
                      AND d.week_ending BETWEEN %s AND %s
                """
                cur.execute(sql, [sku] + ret_params + [is_agg, start, end])
                r = cur.fetchone()[0]
                return float(r) if r is not None else None

            pre_v   = _avg_vel(pre_start, pre_end)
            promo_v = _avg_vel(start_we, end_we)
            post_v  = _avg_vel(post_start, post_end)

            # Doors and incremental dollars
            doors_sql = f"""
                SELECT COUNT(DISTINCT d.store_id)
                FROM stg_scan_data d JOIN stg_stores s ON d.store_id = s.store_id
                WHERE d.sku = %s AND {ret_clause} AND s.is_aggregated_channel = %s
                  AND d.week_ending BETWEEN %s AND %s
            """
            cur.execute(doors_sql, [sku] + ret_params + [is_agg, start_we, end_we])
            doors = cur.fetchone()[0] or 0
        finally:
            _return_conn(conn_inner)

        rows.append({
            "promo_id": p["promo_id"], "retailer": ret,
            "start_week": p["start_week"], "end_week": p["end_week"],
            "duration_weeks": p["duration_weeks"],
            "discount_depth_pct": p["discount_depth_pct"],
            "promo_type": p["promo_type"],
            "pre_v": pre_v, "promo_v": promo_v, "post_v": post_v,
            "doors": doors,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Lift, dip, and per-promo hangover (post minus pre, the residual damage)
    df["lift_pct"] = (df["promo_v"] - df["pre_v"]) / df["pre_v"] * 100
    df["dip_pct"]  = (df["post_v"] - df["pre_v"]) / df["pre_v"] * 100
    return df


@cache.memoize(timeout=3600)
def get_sku_trade_spend(sku: str) -> float:
    """Total trade spend on a SKU summed over all promo (sku, week, retailer)
    triples. Trade $ = scan dollars in that promo week * retailer trade %."""
    conn = get_raw_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT trade_spend_pct_walmart, trade_spend_pct_costco,
                      trade_spend_pct_whole_foods, trade_spend_pct_regional,
                      trade_spend_pct_unfi, trade_spend_pct_dtc
               FROM stg_sku_costs WHERE sku=%s""",
            [sku],
        )
        costs = cur.fetchone()
        if costs is None:
            return 0.0
        pct = {
            "Walmart":     costs[0] or 0.0,
            "Costco":      costs[1] or 0.0,
            "Whole Foods": costs[2] or 0.0,
            "UNFI":        costs[4] or 0.0,
            "DTC":         costs[5] or 0.0,
        }
        regional_pct = costs[3] or 0.0

        # Promo (week, retailer) set
        cur.execute(
            "SELECT retailer, start_week, end_week FROM stg_promotions WHERE sku=%s",
            [sku],
        )
        promo_rows = cur.fetchall()
        promo_index: dict[str, set[str]] = {}  # retailer -> set of week_ending
        for ret, sw, ew in promo_rows:
            for wk in _promo_to_scan_weeks(sw, ew):
                promo_index.setdefault(ret, set()).add(wk)

        # Total scan dollars by (week, retailer) for this SKU
        cur.execute(
            """
            SELECT d.week_ending, s.retailer, SUM(d.dollars_sold)
            FROM stg_scan_data d JOIN stg_stores s ON d.store_id = s.store_id
            WHERE d.sku = %s
            GROUP BY d.week_ending, s.retailer
            """,
            [sku],
        )
        scan_rows = cur.fetchall()
    finally:
        _return_conn(conn)

    total = 0.0
    for wk, ret, dollars in scan_rows:
        if ret not in promo_index or wk not in promo_index[ret]:
            continue
        if ret in REGIONAL_CHAINS:
            tp = regional_pct
        else:
            tp = pct.get(ret, 0.0)
        total += (dollars or 0.0) * tp
    return total


@cache.memoize(timeout=3600)
def get_walmart_trajectory(sku: str) -> pd.DataFrame:
    """Trailing 13-week rolling avg of Walmart-only weekly velocity."""
    conn = get_raw_conn()
    try:
        df = pd.read_sql(
            """
            SELECT d.week_ending, AVG(d.units_sold) AS velocity
            FROM stg_scan_data d JOIN stg_stores s ON d.store_id = s.store_id
            WHERE d.sku = %s AND s.retailer = 'Walmart'
            GROUP BY d.week_ending ORDER BY d.week_ending
            """,
            conn, params=[sku],
        )
    finally:
        _return_conn(conn)
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    df["t13"] = df["velocity"].rolling(window=13, min_periods=4).mean()
    return df


@cache.memoize(timeout=3600)
def get_sku_revenue_at_risk(sku: str) -> dict:
    """Annual revenue at the protagonist's current Walmart distribution
    (doors * current velocity * wholesale * 52). What's "at risk" if the SKU
    crosses the delisting threshold and Walmart drops it in the next review."""
    conn = get_raw_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT d.store_id),
                   AVG(d.units_sold),
                   SUM(d.dollars_sold)
            FROM stg_scan_data d JOIN stg_stores s ON d.store_id = s.store_id
            WHERE d.sku = %s AND s.retailer = 'Walmart'
              AND ((SELECT MAX(week_ending) FROM stg_scan_data)::date - d.week_ending::date) < 91
            """,
            [sku],
        )
        row = cur.fetchone()
        walmart_doors = row[0] or 0
        walmart_v     = row[1] or 0.0
        walmart_q     = row[2] or 0.0  # last 13wk dollars at walmart

        # Annualize: take the trailing 13wk avg velocity and project a year forward
        annual_units_walmart = walmart_v * walmart_doors * 52
        # SKU wholesale at walmart for revenue conversion
        cur.execute(
            """SELECT wholesale_walmart, cogs_per_unit FROM stg_sku_costs WHERE sku=%s""",
            [sku],
        )
        cost_row = cur.fetchone()
    finally:
        _return_conn(conn)
    wholesale_walmart = cost_row[0] or 0
    cogs              = cost_row[1] or 0
    annual_rev_walmart = annual_units_walmart * wholesale_walmart
    annual_margin_walmart = annual_units_walmart * (wholesale_walmart - cogs)

    return {
        "walmart_doors": walmart_doors,
        "walmart_v_t13": walmart_v,
        "walmart_dollars_t13": walmart_q,
        "annual_rev_walmart": annual_rev_walmart,
        "annual_margin_walmart": annual_margin_walmart,
        "wholesale_walmart": wholesale_walmart,
        "cogs": cogs,
    }


@cache.memoize(timeout=3600)
def get_sku_costs(sku: str) -> dict:
    """Return wholesale_walmart and cogs_per_unit for a SKU.

    Used by the Story narrative (Section 3) to compute margin per unit
    without duplicating the raw SQL that already lives in
    get_sku_revenue_at_risk.
    """
    conn = get_raw_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT wholesale_walmart, cogs_per_unit FROM stg_sku_costs WHERE sku=%s",
            [sku],
        )
        row = cur.fetchone()
    finally:
        _return_conn(conn)
    ws = (row[0] or 0) if row else 0
    cogs = (row[1] or 0) if row else 0
    return {"wholesale_walmart": ws, "cogs_per_unit": cogs}


@cache.memoize(timeout=3600)
def get_category_avg_velocity(product_line: str) -> float:
    """Recent 13wk units/store-week for the product line -- used as the
    'replacement SKU could earn this much' benchmark."""
    conn = get_raw_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT AVG(d.units_sold)
            FROM stg_scan_data d JOIN dim_products pm ON d.sku = pm.sku
            WHERE pm.product_line = %s
              AND ((SELECT MAX(week_ending) FROM stg_scan_data)::date - d.week_ending::date) < 91
            """,
            [product_line],
        )
        row = cur.fetchone()
    finally:
        _return_conn(conn)
    return row[0] or 0.0


# ============================================================
# Bottom subsection: "What the rest of the portfolio looks like"
# ============================================================

@cache.memoize(timeout=3600)
def get_top_demand_4wk() -> pd.DataFrame:
    """Top 10 SKUs by projected next-4-week case demand."""
    conn = get_raw_conn()
    try:
        df = pd.read_sql(
            """
            SELECT pm.sku, pm.product_name,
                   SUM(d.units_sold) * 1.0 / NULLIF(pm.case_pack_qty, 0) AS cases_4wk
            FROM stg_scan_data d JOIN dim_products pm ON d.sku = pm.sku
            WHERE ((SELECT MAX(week_ending) FROM stg_scan_data)::date - d.week_ending::date) < 28
            GROUP BY pm.sku, pm.product_name, pm.case_pack_qty
            ORDER BY cases_4wk DESC LIMIT 10
            """,
            conn,
        )
    finally:
        _return_conn(conn)
    return df.dropna(subset=["cases_4wk"]).reset_index(drop=True)


@cache.memoize(timeout=3600)
def get_top_velocity_per_door() -> pd.DataFrame:
    """Top 10 retailer chains by avg units/door/week over the trailing 13 weeks."""
    conn = get_raw_conn()
    try:
        df = pd.read_sql(
            """
            SELECT s.retailer AS chain,
                   AVG(d.units_sold) AS vel_per_door,
                   COUNT(DISTINCT d.store_id) AS active_doors
            FROM stg_scan_data d JOIN stg_stores s ON d.store_id = s.store_id
            WHERE ((SELECT MAX(week_ending) FROM stg_scan_data)::date - d.week_ending::date) < 91
              AND s.is_aggregated_channel = false
            GROUP BY s.retailer
            ORDER BY vel_per_door DESC LIMIT 10
            """,
            conn,
        )
    finally:
        _return_conn(conn)
    return df


@cache.memoize(timeout=3600)
def get_bottom_stores_below_threshold(threshold: float = 2.0) -> pd.DataFrame:
    """Bottom 10 Walmart stores by per-SKU avg velocity, with their gap below
    the threshold. Returns the worst stores even if all are above threshold --
    the chart still shows the tail of the distribution. The 'gap' column is
    threshold - velocity (positive = below the line, negative = above)."""
    conn = get_raw_conn()
    try:
        df = pd.read_sql(
            """
            SELECT d.store_id, AVG(d.units_sold) AS vel
            FROM stg_scan_data d JOIN stg_stores s ON d.store_id = s.store_id
            WHERE s.retailer = 'Walmart'
              AND ((SELECT MAX(week_ending) FROM stg_scan_data)::date - d.week_ending::date) < 91
            GROUP BY d.store_id
            ORDER BY vel ASC LIMIT 10
            """,
            conn,
        )
    finally:
        _return_conn(conn)
    df["gap"] = threshold - df["vel"]
    df["threshold"] = threshold
    return df


@cache.memoize(timeout=3600)
def get_top_elasticity_skus() -> pd.DataFrame:
    """Top 10 SKUs by avg promo lift / discount-depth ratio (elasticity)."""
    conn = get_raw_conn()
    try:
        df = pd.read_sql(
            """
            WITH promo_pairs AS (
                SELECT p.sku, p.start_week, p.end_week, p.discount_depth_pct,
                       AVG(CASE WHEN sd.week_ending BETWEEN p.start_week AND p.end_week
                                THEN sd.units_sold END) AS promo_v,
                       AVG(CASE WHEN sd.week_ending BETWEEN (p.start_week::date - interval '28 days')::date
                                                  AND (p.start_week::date - interval '1 days')::date
                                THEN sd.units_sold END) AS pre_v
                FROM stg_promotions p JOIN stg_scan_data sd ON sd.sku = p.sku
                WHERE sd.week_ending BETWEEN (p.start_week::date - interval '28 days')::date
                                         AND (p.end_week::date + interval '1 days')::date
                GROUP BY p.promo_id, p.sku, p.start_week, p.end_week, p.discount_depth_pct
            )
            SELECT * FROM (
                SELECT pm.sku, pm.product_name,
                       AVG((pp.promo_v - pp.pre_v) / NULLIF(pp.pre_v, 0)
                           / NULLIF(pp.discount_depth_pct, 0)) AS elasticity,
                       COUNT(*) AS n_promos
                FROM promo_pairs pp JOIN dim_products pm ON pp.sku = pm.sku
                WHERE pp.pre_v > 0 AND pp.discount_depth_pct > 0
                GROUP BY pm.sku, pm.product_name
            ) sub WHERE n_promos >= 1 AND elasticity IS NOT NULL
            ORDER BY elasticity DESC LIMIT 10
            """,
            conn,
        )
    finally:
        _return_conn(conn)
    return df


# ============================================================
# Decision data functions
# ============================================================

@cache.memoize(timeout=3600)
def get_shelf_defense_data(retailer: str, product_line: str | None) -> pd.DataFrame:
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stg_stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = false
        ),
        agg AS (
            SELECT
              d.sku,
              AVG(CASE WHEN (%s::date - d.week_ending::date) < 56
                       THEN d.units_sold END) AS current_v,
              AVG(CASE WHEN (%s::date - d.week_ending::date) >= 56
                        AND (%s::date - d.week_ending::date) < 112
                       THEN d.units_sold END) AS trailing_v
            FROM stg_scan_data d
            JOIN ret_stores rs ON d.store_id = rs.store_id
            WHERE (%s::date - d.week_ending::date) < 112
            GROUP BY d.sku
        )
        SELECT pm.sku, pm.product_name, pm.product_line,
               agg.current_v, agg.trailing_v
        FROM agg JOIN dim_products pm ON agg.sku = pm.sku
        ORDER BY pm.sku
    """
    conn = get_raw_conn()
    try:
        df = pd.read_sql(sql, conn, params=ret_params + [latest, latest, latest, latest])
    finally:
        _return_conn(conn)
    if product_line:
        df = df[df["product_line"] == product_line]
    return df.dropna(subset=["current_v"]).reset_index(drop=True)


@cache.memoize(timeout=3600)
def get_production_data(retailer: str, product_line: str | None) -> pd.DataFrame:
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id, s.is_aggregated_channel FROM stg_stores s
            WHERE {ret_sql}
        ),
        physical AS (
            SELECT d.sku,
              AVG(CASE WHEN (%s::date - d.week_ending::date) < 28
                       THEN d.units_sold END) AS phys_v_recent,
              AVG(CASE WHEN (%s::date - d.week_ending::date) >= 28
                        AND (%s::date - d.week_ending::date) < 56
                       THEN d.units_sold END) AS phys_v_prior,
              COUNT(DISTINCT CASE WHEN (%s::date - d.week_ending::date) < 28
                                   THEN d.store_id END) AS doors
            FROM stg_scan_data d
            JOIN ret_stores rs ON d.store_id = rs.store_id AND rs.is_aggregated_channel = false
            WHERE (%s::date - d.week_ending::date) < 56
            GROUP BY d.sku
        ),
        all_chan AS (
            SELECT d.sku,
              SUM(CASE WHEN (%s::date - d.week_ending::date) < 28
                       THEN d.units_sold END) AS sum_recent,
              SUM(CASE WHEN (%s::date - d.week_ending::date) BETWEEN 364 AND 392
                       THEN d.units_sold END) AS sum_ly_current,
              SUM(CASE WHEN (%s::date - d.week_ending::date) BETWEEN 336 AND 364
                       THEN d.units_sold END) AS sum_ly_forward
            FROM stg_scan_data d
            JOIN ret_stores rs ON d.store_id = rs.store_id
            WHERE (%s::date - d.week_ending::date) < 393
            GROUP BY d.sku
        )
        SELECT pm.sku, pm.product_name, pm.product_line, pm.case_pack_qty,
               COALESCE(p.doors, 0) AS doors,
               p.phys_v_recent, p.phys_v_prior,
               a.sum_recent, a.sum_ly_current, a.sum_ly_forward
        FROM all_chan a
        JOIN dim_products pm ON a.sku = pm.sku
        LEFT JOIN physical p ON a.sku = p.sku
        WHERE a.sum_recent > 0
        ORDER BY a.sum_recent DESC
    """
    params = ret_params + [latest] * 9
    conn = get_raw_conn()
    try:
        df = pd.read_sql(sql, conn, params=params)
    finally:
        _return_conn(conn)
    if product_line:
        df = df[df["product_line"] == product_line].reset_index(drop=True)

    df["weekly_units"] = (df["sum_recent"] / 4).round(0)
    df["weekly_cases"] = (df["weekly_units"] / df["case_pack_qty"]).round(2)

    sf = df["sum_ly_forward"] / df["sum_ly_current"].replace(0, pd.NA)
    sf = sf.where(sf.notna(), 1.0).clip(lower=0.5, upper=2.0)
    df["seasonal_factor"] = sf
    df["forecast_4w_units"] = (df["weekly_units"] * sf * 4).round(0)
    df["forecast_4w_cases"] = (df["forecast_4w_units"] / df["case_pack_qty"]).round(2)

    trend = (df["phys_v_recent"] - df["phys_v_prior"]) / df["phys_v_prior"].replace(0, pd.NA) * 100
    df["trend_pct"] = trend

    accel_pct = THRESHOLDS["production_trend_accel"] * 100
    decel_pct = THRESHOLDS["production_trend_decel"] * 100

    def status(t: float) -> str:
        if pd.isna(t):
            return "Stable"
        if t > accel_pct:
            return "Accelerating"
        if t < decel_pct:
            return "Decelerating"
        return "Stable"

    df["status"] = df["trend_pct"].apply(status)
    return df


@cache.memoize(timeout=3600)
def get_promo_roi_data(retailer: str, sku_filter: str | None) -> pd.DataFrame:
    ret_sql, ret_params = retailer_clause(retailer)
    is_agg = retailer in ("UNFI", "DTC")

    sku_clause = ""
    sku_params: list = []
    if sku_filter:
        sku_clause = "AND p.sku = %s"
        sku_params = [sku_filter]

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stg_stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = %s
        ),
        promo_list AS (
            SELECT promo_id, sku, retailer, start_week, end_week,
                   duration_weeks, discount_depth_pct, promo_type, store_scope
            FROM stg_promotions p
            WHERE p.retailer = %s {sku_clause}
        ),
        sku_store_first_scan AS (
            SELECT sku, store_id, MIN(week_ending) AS first_scan
            FROM stg_scan_data
            GROUP BY sku, store_id
        ),
        qualified_pairs AS (
            SELECT p.promo_id, p.sku, sf.store_id
            FROM promo_list p
            JOIN sku_store_first_scan sf ON sf.sku = p.sku
            JOIN ret_stores rs ON sf.store_id = rs.store_id
            WHERE sf.first_scan <= (p.start_week::date - interval '28 days')::date
        )
        SELECT
            p.promo_id, p.sku, p.retailer, p.start_week, p.end_week,
            p.duration_weeks, p.discount_depth_pct, p.promo_type, p.store_scope,
            pm.product_name, pm.product_line, sc.wholesale_price,
            (SELECT AVG(d.units_sold) FROM stg_scan_data d
             JOIN qualified_pairs qp ON qp.sku = d.sku AND qp.store_id = d.store_id
             WHERE qp.promo_id = p.promo_id
               AND d.week_ending BETWEEN (p.start_week::date - interval '28 days')::date
                                     AND (p.start_week::date - interval '1 days')::date
            ) AS baseline_v,
            (SELECT AVG(d.units_sold) FROM stg_scan_data d
             JOIN qualified_pairs qp ON qp.sku = d.sku AND qp.store_id = d.store_id
             WHERE qp.promo_id = p.promo_id
               AND d.week_ending BETWEEN p.start_week AND p.end_week
            ) AS promo_v,
            (SELECT AVG(d.units_sold) FROM stg_scan_data d
             JOIN qualified_pairs qp ON qp.sku = d.sku AND qp.store_id = d.store_id
             WHERE qp.promo_id = p.promo_id
               AND d.week_ending BETWEEN (p.end_week::date + interval '7 days')::date
                                     AND (p.end_week::date + interval '21 days')::date
            ) AS post_v,
            (SELECT COUNT(DISTINCT qp.store_id) FROM qualified_pairs qp
             WHERE qp.promo_id = p.promo_id
            ) AS doors
        FROM promo_list p
        JOIN dim_products pm ON p.sku = pm.sku
        JOIN stg_sku_costs sc ON p.sku = sc.sku
        ORDER BY p.start_week DESC
    """
    conn = get_raw_conn()
    try:
        df = pd.read_sql(sql, conn, params=ret_params + [is_agg, retailer] + sku_params)
    finally:
        _return_conn(conn)
    if df.empty:
        return df

    bv, pv, pov = df["baseline_v"], df["promo_v"], df["post_v"]
    df["lift_pct"] = (pv - bv) / bv * 100
    df["dip_pct"] = (pov - bv) / bv * 100
    df["incremental_units"] = ((pv - bv) * df["doors"] * df["duration_weeks"]).round(0)
    df["incremental_revenue"] = (
        df["incremental_units"] * df["wholesale_price"] * (1 - df["discount_depth_pct"])
    ).round(0)
    df["promo_cost"] = (
        bv * df["doors"] * df["duration_weeks"] * df["wholesale_price"] * df["discount_depth_pct"]
    ).round(0)
    df["roi_pct"] = (
        (df["incremental_revenue"] - df["promo_cost"]) / df["promo_cost"].replace(0, pd.NA) * 100
    )
    return df


@cache.memoize(timeout=3600)
def get_promo_weekly_velocity(promo_id: str, sku: str, retailer: str) -> pd.DataFrame:
    ret_sql, ret_params = retailer_clause(retailer)
    is_agg = retailer in ("UNFI", "DTC")

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stg_stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = %s
        ),
        prom AS (
            SELECT start_week, end_week FROM stg_promotions
            WHERE promo_id = %s AND sku = %s
            LIMIT 1
        )
        SELECT d.week_ending, AVG(d.units_sold) AS velocity
        FROM stg_scan_data d, prom
        WHERE d.sku = %s
          AND d.store_id IN (SELECT store_id FROM ret_stores)
          AND d.week_ending BETWEEN (prom.start_week::date - interval '28 days')::date
                                AND (prom.end_week::date + interval '28 days')::date
        GROUP BY d.week_ending ORDER BY d.week_ending
    """
    conn = get_raw_conn()
    try:
        return pd.read_sql(sql, conn, params=ret_params + [is_agg, promo_id, sku, sku])
    finally:
        _return_conn(conn)


@cache.memoize(timeout=3600)
def get_expansion_data(focus_sku: str, retailer: str | None) -> pd.DataFrame:
    """Stores where focus_sku is NOT authorized but same-line SKUs perform well."""
    latest = get_latest_week()

    # Determine retailer filter for stores
    if retailer is None or retailer == "All Retailers":
        ret_sql, ret_params = "1=1", []
    elif retailer == "Regional":
        ph = ",".join("%s" for _ in REGIONAL_CHAINS)
        ret_sql, ret_params = f"s.retailer IN ({ph})", list(REGIONAL_CHAINS)
    else:
        ret_sql, ret_params = "s.retailer = %s", [retailer]

    sql = f"""
        WITH focus AS (SELECT product_line FROM dim_products WHERE sku = %s),
        target_stores AS (
            SELECT s.store_id, s.retailer, s.region, s.state, s.volume_tier
            FROM stg_stores s
            WHERE s.is_aggregated_channel = false
              AND ({ret_sql})
              AND s.store_id NOT IN (
                  SELECT store_id FROM fct_distribution
                  WHERE sku = %s
                    AND (deauthorized_date IS NULL OR deauthorized_date > %s)
              )
        ),
        peer_perf AS (
            SELECT d.store_id,
                   COUNT(DISTINCT d.sku) AS n_similar,
                   AVG(sd.units_sold) AS avg_velocity
            FROM fct_distribution d
            JOIN dim_products pm ON d.sku = pm.sku
            JOIN stg_scan_data sd ON sd.sku = d.sku AND sd.store_id = d.store_id
            WHERE pm.product_line = (SELECT product_line FROM focus)
              AND d.sku != %s
              AND (d.deauthorized_date IS NULL OR d.deauthorized_date > %s)
              AND (%s::date - sd.week_ending::date) < 56
            GROUP BY d.store_id
        )
        SELECT ts.store_id, ts.retailer, ts.region, ts.state, ts.volume_tier,
               p.n_similar, p.avg_velocity
        FROM target_stores ts
        JOIN peer_perf p ON ts.store_id = p.store_id
        ORDER BY p.avg_velocity DESC
    """
    params = [focus_sku] + ret_params + [focus_sku, latest, focus_sku, latest, latest]
    conn = get_raw_conn()
    try:
        df = pd.read_sql(sql, conn, params=params)
    finally:
        _return_conn(conn)
    if df.empty:
        return df

    df["tier_mult"] = df["volume_tier"].map(VOLUME_TIER_MULT).fillna(1.0)
    df["score"] = (df["avg_velocity"] * df["tier_mult"]).round(2)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    return df


@cache.memoize(timeout=3600)
def get_pruning_data(retailer: str, product_line: str | None) -> pd.DataFrame:
    """Per (sku, store) currently authorized at retailer: 13-week avg velocity.

    Named get_pruning_data in the Dash layer; identical to get_pruning_pairs
    in velocity_tool.py.
    """
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()

    pl_clause = "AND pm.product_line = %s" if product_line else ""
    pl_params = [product_line] if product_line else []

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id, s.retailer, s.region, s.state, s.volume_tier
            FROM stg_stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = false
        ),
        active AS (
            SELECT d.sku, d.store_id
            FROM fct_distribution d
            WHERE d.store_id IN (SELECT store_id FROM ret_stores)
              AND (d.deauthorized_date IS NULL OR d.deauthorized_date > %s)
        )
        SELECT
            a.sku, a.store_id,
            rs.retailer, rs.region, rs.state, rs.volume_tier,
            pm.product_name, pm.product_line,
            sc.wholesale_price,
            AVG(sd.units_sold) AS velocity
        FROM active a
        JOIN ret_stores rs ON a.store_id = rs.store_id
        JOIN dim_products pm ON a.sku = pm.sku
        JOIN stg_sku_costs sc ON a.sku = sc.sku
        LEFT JOIN stg_scan_data sd ON sd.sku = a.sku AND sd.store_id = a.store_id
                              AND (%s::date - sd.week_ending::date) < 91
        WHERE 1=1 {pl_clause}
        GROUP BY a.sku, a.store_id
    """
    params = ret_params + [latest, latest] + pl_params
    conn = get_raw_conn()
    try:
        df = pd.read_sql(sql, conn, params=params)
    finally:
        _return_conn(conn)
    return df.dropna(subset=["velocity"]).reset_index(drop=True)


@cache.memoize(timeout=3600)
def get_rationalization_data(retailer: str, product_line: str | None) -> pd.DataFrame:
    """Per-SKU 13-week velocity, margin, and door count at the chosen retailer."""
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stg_stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = false
        )
        SELECT pm.sku, pm.product_name, pm.product_line,
               sc.wholesale_price, sc.cogs_per_unit,
               AVG(sd.units_sold) AS velocity,
               COUNT(DISTINCT sd.store_id) AS doors
        FROM stg_scan_data sd
        JOIN ret_stores rs ON sd.store_id = rs.store_id
        JOIN dim_products pm ON sd.sku = pm.sku
        JOIN stg_sku_costs sc ON sd.sku = sc.sku
        WHERE (%s::date - sd.week_ending::date) < 91
        GROUP BY pm.sku, pm.product_name, pm.product_line,
                 sc.wholesale_price, sc.cogs_per_unit
    """
    conn = get_raw_conn()
    try:
        df = pd.read_sql(sql, conn, params=ret_params + [latest])
    finally:
        _return_conn(conn)
    if product_line:
        df = df[df["product_line"] == product_line]
    df = df.dropna(subset=["velocity"]).reset_index(drop=True)
    if df.empty:
        return df

    df["margin_per_unit"] = (df["wholesale_price"] - df["cogs_per_unit"]).round(2)
    df["margin_per_sw"] = (df["velocity"] * df["margin_per_unit"]).round(2)
    df["revenue_per_sw"] = (df["velocity"] * df["wholesale_price"]).round(2)
    df["weekly_total_margin"] = (df["margin_per_sw"] * df["doors"]).round(0)
    return df


@cache.memoize(timeout=3600)
def get_launch_data() -> pd.DataFrame:
    """One row per SKU launched in the last 52 weeks, with window averages."""
    latest = get_latest_week()

    sql = """
        WITH launches AS (
            SELECT sku, MIN(authorized_date) AS launch_date
            FROM fct_distribution
            GROUP BY sku
            HAVING MIN(authorized_date) >= (%s::date - interval '364 days')::date
        ),
        phys_stores AS (
            SELECT store_id FROM stg_stores WHERE is_aggregated_channel = false
        )
        SELECT pm.sku, pm.product_name, pm.product_line, l.launch_date,
            AVG(CASE WHEN (sd.week_ending::date - l.launch_date::date) BETWEEN 0 AND 27
                     THEN sd.units_sold END) AS v_w14,
            AVG(CASE WHEN (sd.week_ending::date - l.launch_date::date) BETWEEN 28 AND 55
                     THEN sd.units_sold END) AS v_w58,
            AVG(CASE WHEN (sd.week_ending::date - l.launch_date::date) BETWEEN 56 AND 90
                     THEN sd.units_sold END) AS v_w913,
            AVG(CASE WHEN (sd.week_ending::date - l.launch_date::date) >= 91
                     THEN sd.units_sold END) AS v_w14plus,
            AVG(CASE WHEN (%s::date - sd.week_ending::date) < 28
                     THEN sd.units_sold END) AS v_current
        FROM stg_scan_data sd
        JOIN launches l ON sd.sku = l.sku
        JOIN phys_stores ps ON sd.store_id = ps.store_id
        JOIN dim_products pm ON sd.sku = pm.sku
        GROUP BY pm.sku, pm.product_name, pm.product_line, l.launch_date
        ORDER BY l.launch_date DESC
    """
    conn = get_raw_conn()
    try:
        df = pd.read_sql(sql, conn, params=[latest, latest])
    finally:
        _return_conn(conn)
    if df.empty:
        return df

    latest_d = pd.to_datetime(latest)
    launch_d = pd.to_datetime(df["launch_date"])
    df["weeks_since_launch"] = ((latest_d - launch_d).dt.days // 7).astype(int)
    return df


@cache.memoize(timeout=3600)
def get_launch_weekly(sku: str) -> pd.DataFrame:
    sql = """
        WITH phys_stores AS (
            SELECT store_id FROM stg_stores WHERE is_aggregated_channel = false
        ),
        launch AS (
            SELECT MIN(authorized_date) AS launch_date
            FROM fct_distribution WHERE sku = %s
        )
        SELECT sd.week_ending, AVG(sd.units_sold) AS velocity,
               (SELECT launch_date FROM launch) AS launch_date
        FROM stg_scan_data sd
        JOIN phys_stores ps ON sd.store_id = ps.store_id
        WHERE sd.sku = %s
          AND sd.week_ending >= (SELECT launch_date FROM launch)
        GROUP BY sd.week_ending
        ORDER BY sd.week_ending
    """
    conn = get_raw_conn()
    try:
        return pd.read_sql(sql, conn, params=[sku, sku])
    finally:
        _return_conn(conn)


@cache.memoize(timeout=3600)
def get_pricing_data(retailer: str, sku_filter: str | None,
                     product_line_filter: str | None) -> pd.DataFrame:
    """Per-SKU baseline / promo / post-promo velocity at one retailer.

    Named get_pricing_data in the Dash layer; identical to
    get_pricing_power_data in velocity_tool.py.
    """
    ret_sql, ret_params = retailer_clause(retailer)
    is_agg = retailer in ("UNFI", "DTC")

    sku_clause = ""
    sku_params: list = []
    if sku_filter:
        sku_clause = "AND sd.sku = %s"
        sku_params = [sku_filter]

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stg_stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = %s
        ),
        sku_promos AS (
            SELECT sku, start_week, end_week, discount_depth_pct
            FROM stg_promotions WHERE retailer = %s
        ),
        promo_window AS (
            SELECT DISTINCT sp.sku, sd.week_ending
            FROM sku_promos sp
            JOIN stg_scan_data sd ON sd.sku = sp.sku
            JOIN ret_stores rs ON sd.store_id = rs.store_id
            WHERE sd.week_ending BETWEEN sp.start_week AND sp.end_week
        ),
        post_window AS (
            SELECT DISTINCT sp.sku, sd.week_ending
            FROM sku_promos sp
            JOIN stg_scan_data sd ON sd.sku = sp.sku
            JOIN ret_stores rs ON sd.store_id = rs.store_id
            WHERE sd.week_ending BETWEEN (sp.end_week::date + interval '7 days')::date
                                     AND (sp.end_week::date + interval '28 days')::date
        ),
        metrics AS (
            SELECT sd.sku,
                AVG(CASE WHEN EXISTS (SELECT 1 FROM promo_window pw
                                       WHERE pw.sku = sd.sku AND pw.week_ending = sd.week_ending)
                         THEN sd.units_sold END) AS promo_v,
                AVG(CASE WHEN EXISTS (SELECT 1 FROM post_window pow
                                       WHERE pow.sku = sd.sku AND pow.week_ending = sd.week_ending)
                         THEN sd.units_sold END) AS post_v,
                AVG(CASE WHEN NOT EXISTS (SELECT 1 FROM promo_window pw
                                           WHERE pw.sku = sd.sku AND pw.week_ending = sd.week_ending)
                          AND NOT EXISTS (SELECT 1 FROM post_window pow
                                           WHERE pow.sku = sd.sku AND pow.week_ending = sd.week_ending)
                         THEN sd.units_sold END) AS baseline_v
            FROM stg_scan_data sd
            JOIN ret_stores rs ON sd.store_id = rs.store_id
            WHERE sd.sku IN (SELECT DISTINCT sku FROM sku_promos)
              {sku_clause}
            GROUP BY sd.sku
        ),
        discount_avg AS (
            SELECT sku, AVG(discount_depth_pct) AS avg_discount, COUNT(*) AS n_promos
            FROM sku_promos GROUP BY sku
        )
        SELECT pm.sku, pm.product_name, pm.product_line,
               m.baseline_v, m.promo_v, m.post_v,
               d.avg_discount, d.n_promos
        FROM metrics m
        JOIN dim_products pm ON m.sku = pm.sku
        JOIN discount_avg d ON m.sku = d.sku
        ORDER BY pm.sku
    """
    conn = get_raw_conn()
    try:
        df = pd.read_sql(sql, conn, params=ret_params + [is_agg, retailer] + sku_params)
    finally:
        _return_conn(conn)
    if df.empty:
        return df
    if product_line_filter:
        df = df[df["product_line"] == product_line_filter].reset_index(drop=True)
    df = df.dropna(subset=["baseline_v", "promo_v"])
    df = df[df["baseline_v"] > 0].reset_index(drop=True)
    if df.empty:
        return df

    df["lift_pct"] = (df["promo_v"] - df["baseline_v"]) / df["baseline_v"]
    df["elasticity"] = df["lift_pct"] / df["avg_discount"].replace(0, pd.NA)
    df["recovery_ratio"] = df["post_v"] / df["baseline_v"]

    full_floor = THRESHOLDS["pricing_full_recovery"]
    slow_floor = THRESHOLDS["pricing_slow_recovery"]

    def recovery_label(r: float) -> str:
        if pd.isna(r):
            return "Slow Recovery"
        if r >= full_floor:
            return "Full Recovery"
        if r >= slow_floor:
            return "Partial Recovery"
        return "Slow Recovery"

    df["recovery_status"] = df["recovery_ratio"].apply(recovery_label)
    df = df.sort_values("elasticity", ascending=False).reset_index(drop=True)
    return df


# ============================================================
# Cache warming
# ============================================================

def warm_default_view() -> None:
    """Synchronously warm the default view (Shelf Defense + Walmart) so the
    first page load has data immediately.  Called before the background thread."""
    import logging
    log = logging.getLogger("warm_cache")

    get_product_lines()
    get_latest_week()
    get_shelf_defense_data("Walmart", None)
    log.info("default view warmed")


def warm_cache() -> None:
    """Pre-call every retailer × mode combination so dropdown switches
    never hit a cold cache.  Runs in a background thread after the default
    view is already warm."""
    import logging
    import time
    log = logging.getLogger("warm_cache")

    from constants import (
        ALL_PHYSICAL_OR_AGG,
        PHYSICAL_RETAILERS,
        PROTAGONIST_SKU,
    )

    # Small delay to let the worker finish booting and serve the first request
    time.sleep(2)

    calls: list[tuple[str, callable]] = [
        ("launch_data", lambda: get_launch_data()),
    ]

    # Shelf defense + pruning: physical retailers only (Walmart already warmed)
    for ret in PHYSICAL_RETAILERS:
        if ret != "Walmart":
            calls.append((f"shelf_defense({ret})", lambda r=ret: get_shelf_defense_data(r, None)))
        calls.append((f"pruning({ret})", lambda r=ret: get_pruning_data(r, None)))

    # Production + rationalization: physical retailers + "All Retailers"
    for ret in ["All Retailers"] + PHYSICAL_RETAILERS:
        calls.append((f"production({ret})",      lambda r=ret: get_production_data(r, None)))
        calls.append((f"rationalization({ret})", lambda r=ret: get_rationalization_data(r, None)))

    # Promo ROI + pricing: all physical + aggregated channels
    for ret in ALL_PHYSICAL_OR_AGG:
        calls.append((f"promo_roi({ret})", lambda r=ret: get_promo_roi_data(r, None)))
        calls.append((f"pricing({ret})",   lambda r=ret: get_pricing_data(r, None, None)))

    # Expansion: protagonist SKU across all retailer options
    for ret in [None] + PHYSICAL_RETAILERS:
        label = ret or "All"
        calls.append((f"expansion({label})", lambda r=ret: get_expansion_data(PROTAGONIST_SKU, r)))

    # Story mode helpers (SKU-specific, not retailer-varied)
    calls.extend([
        ("monday_summary",        lambda: get_monday_morning_summary(PROTAGONIST_SKU)),
        ("sku_velocity",          lambda: get_sku_weekly_velocity(PROTAGONIST_SKU)),
        ("sku_trade_spend",       lambda: get_sku_trade_spend(PROTAGONIST_SKU)),
        ("promo_hangover",        lambda: get_promo_hangover_data(PROTAGONIST_SKU)),
        ("sku_costs",             lambda: get_sku_costs(PROTAGONIST_SKU)),
        ("walmart_trajectory",    lambda: get_walmart_trajectory(PROTAGONIST_SKU)),
        ("revenue_at_risk",       lambda: get_sku_revenue_at_risk(PROTAGONIST_SKU)),
        ("category_avg_velocity", lambda: get_category_avg_velocity("Specialty Condiments")),
        ("top_demand_4wk",        lambda: get_top_demand_4wk()),
        ("top_velocity_per_door", lambda: get_top_velocity_per_door()),
        ("bottom_stores",         lambda: get_bottom_stores_below_threshold(threshold=2.0)),
        ("top_elasticity_skus",   lambda: get_top_elasticity_skus()),
    ])

    for name, fn in calls:
        try:
            fn()
            log.info("warmed %s", name)
        except Exception:
            log.warning("warm_cache: %s failed", name, exc_info=True)

    log.info("cache fully warmed (%d entries)", len(calls))
