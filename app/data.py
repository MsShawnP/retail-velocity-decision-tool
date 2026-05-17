"""Cinderhaven Velocity Tool -- data layer.

All database queries live here. Every function uses flask-caching with
FileSystemCache for memoization. All database connections use the
``get_conn()`` context manager from ``db.py`` to guarantee connections
are returned to the pool on exit.
"""

from __future__ import annotations

import os

import pandas as pd
from flask_caching import Cache

from constants import (
    LAUNCH_BENCHMARK,
    PHYSICAL_RETAILERS,
    REGIONAL_CHAINS,
    RETAILER_THRESHOLDS,
    THRESHOLDS,
    VOLUME_TIER_MULT,
)
from db import get_conn

# ============================================================
# Cache setup (FileSystemCache, 1-hour default)
# ============================================================

_CACHE_DIR = "/cache/dash" if os.path.isdir("/cache") else "/tmp/dash-cache"

cache = Cache(config={
    "CACHE_TYPE": "FileSystemCache",
    "CACHE_DIR": _CACHE_DIR,
    "CACHE_DEFAULT_TIMEOUT": 21600,
})


def init_cache(app) -> None:
    """Bind the cache to a Flask/Dash server instance."""
    cache.init_app(app)


# ============================================================
# Helpers
# ============================================================

def retailer_clause(retailer: str) -> tuple[str, list]:
    """Return (sql_clause, params) for a stores-table filter on retailer."""
    if retailer == "All Retailers":
        return ("1=1", [])
    if retailer == "Regional":
        ph = ",".join("%s" for _ in REGIONAL_CHAINS)
        return (f"s.retailer IN ({ph})", list(REGIONAL_CHAINS))
    return ("s.retailer = %s", [retailer])


# ============================================================
# Utility lookups
# ============================================================

@cache.memoize(timeout=3600)
def get_product_lines() -> list[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT product_line FROM dim_products ORDER BY product_line"
        )
        return [r[0] for r in cur.fetchall()]


@cache.memoize(timeout=3600)
def get_skus_for_line(product_line: str) -> list[tuple[str, str]]:
    """Return [(sku, product_name), ...] for one product line."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT sku, product_name FROM dim_products "
            "WHERE product_line = %s ORDER BY sku",
            (product_line,),
        )
        return cur.fetchall()


@cache.memoize(timeout=3600)
def get_latest_week() -> str:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(week_ending) FROM stg_scan_data")
        return cur.fetchone()[0]


@cache.memoize(timeout=3600)
def get_promo_skus(retailer: str) -> list[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT sku FROM stg_promotions WHERE retailer = %s ORDER BY sku",
            (retailer,),
        )
        return [r[0] for r in cur.fetchall()]


# ============================================================
# Portfolio-level aggregation
# ============================================================

@cache.memoize(timeout=3600)
def get_portfolio_summary() -> dict:
    """Aggregate portfolio-wide metrics by composing decision-mode queries.

    Returns a flat dict with counts, totals, and status distributions
    suitable for the portfolio health landing page.
    """
    latest = get_latest_week()

    # -- Total physical doors across all retailers --
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM stg_stores"
            " WHERE is_aggregated_channel = false"
        )
        total_doors = cur.fetchone()[0]

    # -- Production: active SKUs + trend distribution --
    prod = get_production_data("All Retailers", None)
    total_skus = len(prod)
    prod_accel = int((prod["status"] == "Accelerating").sum())
    prod_decel = int((prod["status"] == "Decelerating").sum())
    prod_stable = total_skus - prod_accel - prod_decel
    weekly_units = int(prod["weekly_units"].sum())
    forecast_4w_cases = int(prod["forecast_4w_cases"].sum())

    # -- Shelf risk: per-retailer classification, count unique at-risk SKUs --
    at_risk_skus: set[str] = set()
    warning_skus: set[str] = set()
    shelf_warn_mult = THRESHOLDS["shelf_warning_mult"]
    for ret in PHYSICAL_RETAILERS:
        shelf = get_shelf_defense_data(ret, None)
        if shelf.empty:
            continue
        thr = RETAILER_THRESHOLDS.get(ret, 2.0)
        warn_upper = thr * shelf_warn_mult
        for _, row in shelf.iterrows():
            c, t = row["current_v"], row["trailing_v"]
            if c < thr:
                at_risk_skus.add(row["sku"])
            elif c < warn_upper and pd.notna(t) and t > c:
                warning_skus.add(row["sku"])
    warning_skus -= at_risk_skus

    # -- Launch health --
    launches = get_launch_data()
    n_launches = len(launches)
    launch_on_track = 0
    launch_failing = 0
    launch_attention = 0
    if not launches.empty:
        on_track_ret = THRESHOLDS["launch_on_track"]
        failing_floor = THRESHOLDS["launch_failing"]
        launch_thr = LAUNCH_BENCHMARK
        for _, row in launches.iterrows():
            initial, current = row["v_w14"], row["v_current"]
            if pd.isna(current):
                launch_attention += 1
            elif pd.isna(initial):
                if current >= launch_thr:
                    launch_on_track += 1
                else:
                    launch_attention += 1
            elif current >= launch_thr:
                if current < initial * on_track_ret:
                    launch_attention += 1
                else:
                    launch_on_track += 1
            elif (current < initial * on_track_ret
                  or current < launch_thr * failing_floor):
                launch_failing += 1
            else:
                launch_attention += 1

    # -- Rationalization: total weekly margin --
    rat = get_rationalization_data("All Retailers", None)
    total_weekly_margin = (
        int(rat["weekly_total_margin"].sum()) if not rat.empty else 0
    )

    return {
        "latest_week": latest,
        "total_skus": total_skus,
        "total_retailers": len(PHYSICAL_RETAILERS),
        "total_doors": total_doors,
        "total_product_lines": len(get_product_lines()),
        "weekly_units": weekly_units,
        "forecast_4w_cases": forecast_4w_cases,
        "shelf_at_risk": len(at_risk_skus),
        "shelf_warning": len(warning_skus),
        "prod_accelerating": prod_accel,
        "prod_decelerating": prod_decel,
        "prod_stable": prod_stable,
        "launches_total": n_launches,
        "launches_on_track": launch_on_track,
        "launches_failing": launch_failing,
        "launches_attention": launch_attention,
        "total_weekly_margin": total_weekly_margin,
    }


# ============================================================
# Time-series data for trend charts
# ============================================================

@cache.memoize(timeout=3600)
def get_weekly_velocity_trend(
    retailer: str, skus: list[str], weeks: int = 12,
) -> pd.DataFrame:
    """Weekly avg velocity per SKU over the last *weeks* weeks.

    Returns columns: sku, product_name, week_ending, avg_velocity.
    """
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()
    ph = ",".join(["%s"] * len(skus))
    sql = f"""
        WITH ret_stores AS (
            SELECT store_id FROM stg_stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = false
        )
        SELECT d.sku, pm.product_name, d.week_ending,
               AVG(d.units_sold) AS avg_velocity
        FROM stg_scan_data d
        JOIN ret_stores rs ON d.store_id = rs.store_id
        JOIN dim_products pm ON d.sku = pm.sku
        WHERE d.sku IN ({ph})
          AND d.week_ending > (%s::date - interval '{int(weeks * 7)} days')::date
        GROUP BY d.sku, pm.product_name, d.week_ending
        ORDER BY d.week_ending, d.sku
    """
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=ret_params + skus + [latest])


@cache.memoize(timeout=3600)
def get_weekly_total_units(retailer: str, weeks: int = 12) -> pd.DataFrame:
    """Total units per week across all SKUs for a retailer scope.

    Returns columns: week_ending, total_units.
    """
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()
    sql = f"""
        WITH ret_stores AS (
            SELECT store_id FROM stg_stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = false
        )
        SELECT d.week_ending, SUM(d.units_sold) AS total_units
        FROM stg_scan_data d
        JOIN ret_stores rs ON d.store_id = rs.store_id
        WHERE d.week_ending > (%s::date - interval '{int(weeks * 7)} days')::date
        GROUP BY d.week_ending
        ORDER BY d.week_ending
    """
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=ret_params + [latest])


@cache.memoize(timeout=3600)
def get_launch_velocity_curve(sku: str) -> pd.DataFrame:
    """Weekly avg velocity since launch for a single SKU (physical stores).

    Returns columns: week_ending, avg_velocity, weeks_since_launch.
    """
    sql = """
        WITH launch AS (
            SELECT MIN(authorized_date) AS launch_date
            FROM fct_distribution WHERE sku = %s
        ),
        phys_stores AS (
            SELECT store_id FROM stg_stores WHERE is_aggregated_channel = false
        )
        SELECT sd.week_ending,
               AVG(sd.units_sold) AS avg_velocity,
               (sd.week_ending::date
                - (SELECT launch_date FROM launch)::date) / 7 AS weeks_since_launch
        FROM stg_scan_data sd
        JOIN phys_stores ps ON sd.store_id = ps.store_id
        WHERE sd.sku = %s
          AND sd.week_ending >= (SELECT launch_date FROM launch)
        GROUP BY sd.week_ending
        ORDER BY sd.week_ending
    """
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=[sku, sku])


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
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=ret_params + [latest, latest, latest, latest])
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
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if product_line:
        df = df[df["product_line"] == product_line].reset_index(drop=True)

    df["weekly_units"] = (df["sum_recent"] / 4).round(0)
    df["weekly_cases"] = (df["weekly_units"] / df["case_pack_qty"]).round(2)

    sf = df["sum_ly_forward"] / df["sum_ly_current"].replace(0, pd.NA)
    n_defaulted = int(sf.isna().sum())
    sf = sf.where(sf.notna(), 1.0).clip(lower=0.5, upper=2.0)
    df["seasonal_factor"] = sf
    if n_defaulted > len(df) // 2:
        import logging
        logging.getLogger("data").warning(
            "Seasonal adjustment inactive for %d/%d SKUs — "
            "dataset may not span a full year",
            n_defaulted, len(df),
        )
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
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=ret_params + [is_agg, retailer] + sku_params)
    if df.empty:
        return df

    df = df[df["baseline_v"] > 0].reset_index(drop=True)
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
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=ret_params + [is_agg, promo_id, sku, sku])


@cache.memoize(timeout=3600)
def get_expansion_data(focus_sku: str, retailer: str | None) -> pd.DataFrame:
    """Stores where focus_sku is NOT authorized but same-line SKUs perform well."""
    latest = get_latest_week()

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
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=params)
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
        GROUP BY a.sku, a.store_id,
                 rs.retailer, rs.region, rs.state, rs.volume_tier,
                 pm.product_name, pm.product_line,
                 sc.wholesale_price
    """
    params = ret_params + [latest, latest] + pl_params
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=params)
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
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=ret_params + [latest])

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
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=[latest, latest])
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
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=[sku, sku])


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
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=ret_params + [is_agg, retailer] + sku_params)
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
    """Pre-call every retailer x mode combination so dropdown switches
    never hit a cold cache.  Runs in a background thread after the default
    view is already warm."""
    import logging
    import time
    log = logging.getLogger("warm_cache")

    from constants import (
        ALL_PHYSICAL_OR_AGG,
        PHYSICAL_RETAILERS,
    )

    time.sleep(2)

    calls: list[tuple[str, callable]] = [
        ("launch_data", lambda: get_launch_data()),
    ]

    for ret in PHYSICAL_RETAILERS:
        if ret != "Walmart":
            calls.append((f"shelf_defense({ret})", lambda r=ret: get_shelf_defense_data(r, None)))
        calls.append((f"pruning({ret})", lambda r=ret: get_pruning_data(r, None)))

    for ret in ["All Retailers"] + PHYSICAL_RETAILERS:
        calls.append((f"production({ret})",      lambda r=ret: get_production_data(r, None)))
        calls.append((f"rationalization({ret})", lambda r=ret: get_rationalization_data(r, None)))

    for ret in ALL_PHYSICAL_OR_AGG:
        calls.append((f"promo_roi({ret})", lambda r=ret: get_promo_roi_data(r, None)))
        calls.append((f"pricing({ret})",   lambda r=ret: get_pricing_data(r, None, None)))

    lines = get_product_lines()
    if lines:
        pairs = get_skus_for_line(lines[0])
        if pairs:
            first_sku = pairs[0][0]
            for ret in [None] + PHYSICAL_RETAILERS:
                label = ret or "All"
                calls.append((f"expansion({label})", lambda r=ret: get_expansion_data(first_sku, r)))

    for name, fn in calls:
        try:
            fn()
            log.info("warmed %s", name)
        except Exception:
            log.warning("warm_cache: %s failed", name, exc_info=True)

    log.info("cache fully warmed (%d entries)", len(calls))
