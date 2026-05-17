"""Pure calculation functions extracted from data.py.

Each function takes a DataFrame (as returned by a SQL query) and returns
it with computed columns added.  No database access, no caching — just
pandas math.  This makes the business logic independently testable.
"""

from __future__ import annotations

import pandas as pd

from constants import THRESHOLDS, VOLUME_TIER_MULT


def apply_production_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly units/cases, seasonal factor, 4-week forecast, trend & status."""
    df = df.copy()
    df["weekly_units"] = (df["sum_recent"] / 4).round(0)
    cpq = df["case_pack_qty"].replace(0, pd.NA)
    df["weekly_cases"] = (df["weekly_units"] / cpq).round(2)

    sf = df["sum_ly_forward"] / df["sum_ly_current"].replace(0, pd.NA)
    n_defaulted = int(sf.isna().sum())
    sf = sf.where(sf.notna(), 1.0).clip(lower=0.5, upper=2.0)
    df["seasonal_factor"] = sf
    df["forecast_4w_units"] = (df["weekly_units"] * sf * 4).round(0)
    df["forecast_4w_cases"] = (df["forecast_4w_units"] / cpq).round(2)

    trend = (
        (df["phys_v_recent"] - df["phys_v_prior"])
        / df["phys_v_prior"].replace(0, pd.NA) * 100
    )
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
    return df, n_defaulted


def apply_promo_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Baseline guard, lift/dip, incremental units/revenue, promo cost, ROI."""
    df = df.copy()
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


def apply_pricing_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Elasticity, recovery ratio, recovery status."""
    df = df.copy()
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
    return df


def apply_expansion_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Volume-tier-weighted score and tertile tier bucketing."""
    df = df.copy()
    df["tier_mult"] = df["volume_tier"].map(VOLUME_TIER_MULT).fillna(1.0)
    df["score"] = (df["avg_velocity"] * df["tier_mult"]).round(2)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    score_min = df["score"].min()
    score_max = df["score"].max()
    score_span = max(score_max - score_min, 1e-9)
    solid_floor = score_min + score_span / 3.0
    strongest_floor = score_min + 2.0 * score_span / 3.0

    def tier_label(s: float) -> str:
        if s >= strongest_floor:
            return "Strongest"
        if s >= solid_floor:
            return "Solid"
        return "Worth considering"

    df["tier"] = df["score"].apply(tier_label)
    return df
