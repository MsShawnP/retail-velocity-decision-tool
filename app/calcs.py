"""Pure calculation functions extracted from data.py.

Each function takes a DataFrame (as returned by a SQL query) and returns
it with computed columns added.  No database access, no caching — just
pandas math.  This makes the business logic independently testable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from constants import PROMO_DEFAULT_GROSS_MARGIN, THRESHOLDS, VOLUME_TIER_MULT


def _ensure_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Coerce columns to float — handles psycopg2 Decimal objects."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def apply_production_calcs(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Weekly units/cases, seasonal factor, 4-week forecast, trend & status."""
    df = df.copy()
    df = _ensure_numeric(df, [
        "sum_recent", "case_pack_qty", "sum_ly_forward", "sum_ly_current",
        "phys_v_prior", "phys_v_recent",
    ])
    df["weekly_units"] = (df["sum_recent"] / 4).round(0)
    cpq = df["case_pack_qty"].replace(0, pd.NA)
    df["weekly_cases"] = (df["weekly_units"] / cpq).round(2)

    ly_fwd = pd.to_numeric(df["sum_ly_forward"], errors="coerce")
    ly_cur = pd.to_numeric(df["sum_ly_current"], errors="coerce").replace(0, np.nan)
    sf = ly_fwd / ly_cur
    n_defaulted = int(sf.isna().sum())
    clip_lo = THRESHOLDS["seasonal_clip_lower"]
    clip_hi = THRESHOLDS["seasonal_clip_upper"]
    sf = sf.fillna(1.0).clip(lower=clip_lo, upper=clip_hi)
    df["seasonal_factor"] = sf
    df["forecast_4w_units"] = (df["weekly_units"] * sf * 4).round(0)
    df["forecast_4w_cases"] = df["forecast_4w_units"] / cpq

    prior = df["phys_v_prior"]
    recent = df["phys_v_recent"]
    prior_safe = prior.replace(0, pd.NA)
    trend = (recent - prior) / prior_safe * 100
    df["trend_pct"] = trend

    accel_pct = THRESHOLDS["production_trend_accel"] * 100
    decel_pct = THRESHOLDS["production_trend_decel"] * 100

    def status(row: pd.Series) -> str:
        t = row["trend_pct"]
        if pd.isna(t):
            if pd.isna(row["phys_v_prior"]) or row["phys_v_prior"] == 0:
                if pd.notna(row["phys_v_recent"]) and row["phys_v_recent"] > 0:
                    return "Accelerating"
            return "Stable"
        if t > accel_pct:
            return "Accelerating"
        if t < decel_pct:
            return "Decelerating"
        return "Stable"

    df["status"] = df.apply(status, axis=1)
    return df, n_defaulted


def _promo_unit_cost(df: pd.DataFrame) -> pd.Series:
    """Per-unit COGS for the promo SKUs.

    Prefers the real cogs_per_unit, then derives cost from margin_per_unit
    (cost = wholesale - margin), and finally falls back to a documented
    default gross-margin assumption when neither is supplied (older baked
    snapshots). The live query joins dim_products, so real COGS is normally
    used and the fallback is only a safety net.
    """
    price = pd.to_numeric(df["wholesale_price"], errors="coerce")
    cost = pd.Series(np.nan, index=df.index, dtype="float64")
    if "cogs_per_unit" in df.columns:
        cost = pd.to_numeric(df["cogs_per_unit"], errors="coerce")
    if "margin_per_unit" in df.columns:
        derived = price - pd.to_numeric(df["margin_per_unit"], errors="coerce")
        cost = cost.where(cost.notna(), derived)
    fallback = price * (1 - PROMO_DEFAULT_GROSS_MARGIN)
    return cost.where(cost.notna(), fallback)


def apply_promo_calcs(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Baseline guard, lift/dip, incremental units, and MARGIN-based promo ROI.

    ROI is the net incremental contribution earned per dollar of promotional
    markdown — a true profit measure, not a revenue return. Two inflation
    traps are avoided:
      * COGS is netted (contribution, not gross revenue) so "Strong ROI"
        genuinely means the promo made money.
      * The markdown (promo cost) is charged on EVERY unit sold during the
        promo, not just the baseline units, so the denominator isn't
        understated.

    Returns (result_df, n_excluded) where n_excluded is the count of promos
    dropped because baseline_v <= 0 (insufficient pre-promo scan data).
    """
    df = df.copy()
    df = _ensure_numeric(df, [
        "baseline_v", "promo_v", "post_v", "doors", "duration_weeks",
        "wholesale_price", "discount_depth_pct", "cogs_per_unit", "margin_per_unit",
    ])
    n_excluded = int((df["baseline_v"].isna() | (df["baseline_v"] <= 0)).sum())
    df = df[df["baseline_v"] > 0].reset_index(drop=True)
    if df.empty:
        return df, n_excluded

    bv, pv, pov = df["baseline_v"], df["promo_v"], df["post_v"]
    df["lift_pct"] = (pv - bv) / bv * 100
    df["dip_pct"] = (pov - bv) / bv * 100
    df["incremental_units"] = ((pv - bv) * df["doors"] * df["duration_weeks"]).round(0)

    # Realized (discounted) price actually paid during the promo.
    promo_price = df["wholesale_price"] * (1 - df["discount_depth_pct"])
    df["incremental_revenue"] = (df["incremental_units"] * promo_price).round(0)

    # Contribution earned on each incremental unit, sold at the promo price
    # net of COGS. This is the profit the promo actually generated.
    unit_cost = _promo_unit_cost(df)
    df["incremental_contribution"] = (
        df["incremental_units"] * (promo_price - unit_cost)
    ).round(0)

    # Promo markdown = the discount given away on EVERY unit sold during the
    # promo (baseline + incremental), which is the real cost of running it.
    df["promo_cost"] = (
        pv * df["doors"] * df["duration_weeks"]
        * df["wholesale_price"] * df["discount_depth_pct"]
    ).round(0)

    # Margin-based ROI: net incremental contribution over the markdown spent.
    df["roi_pct"] = (
        (df["incremental_contribution"] - df["promo_cost"])
        / df["promo_cost"].replace(0, pd.NA) * 100
    )
    return df, n_excluded


def apply_pricing_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Elasticity, recovery ratio, recovery status."""
    df = df.copy()
    df = _ensure_numeric(df, ["baseline_v", "promo_v", "post_v", "avg_discount"])
    df = df.dropna(subset=["baseline_v", "promo_v"])
    df = df[df["baseline_v"] > 0].reset_index(drop=True)
    if df.empty:
        return df

    df["lift_pct"] = (df["promo_v"] - df["baseline_v"]) / df["baseline_v"]
    min_disc = THRESHOLDS["pricing_min_discount"]
    safe_disc = df["avg_discount"].where(df["avg_discount"] >= min_disc, pd.NA)
    df["elasticity"] = df["lift_pct"] / safe_disc
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


def classify_shelf_status(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Classify SKUs as At Risk / Warning / Safe based on velocity threshold."""
    df = df.copy()
    df = _ensure_numeric(df, ["current_v", "trailing_v"])
    df["trend_pct"] = (df["current_v"] - df["trailing_v"]) / df["trailing_v"].replace(0, pd.NA) * 100
    warn_mult = THRESHOLDS["shelf_warning_mult"]
    warn_upper = threshold * warn_mult

    def classify(row: pd.Series) -> str:
        c = row["current_v"]
        t = row["trailing_v"]
        if c < threshold:
            return "At Risk"
        if c < warn_upper and pd.notna(t) and t > c:
            return "Warning"
        return "Safe"

    df["status"] = df.apply(classify, axis=1)
    return df


def classify_launch(row: pd.Series, threshold: float) -> str:
    """Classify a single launch row as On Track / Needs Attention / Failing."""
    on_track_retention = THRESHOLDS["launch_on_track"]
    failing_floor = THRESHOLDS["launch_failing"]
    initial = row["v_w14"]
    current = row["v_current"]
    if pd.isna(current):
        return "Needs Attention"
    if pd.isna(initial):
        return "On Track" if current >= threshold else "Needs Attention"
    if current >= threshold:
        return "Needs Attention" if current < initial * on_track_retention else "On Track"
    # Below threshold: check severity
    if current < initial * on_track_retention or current < threshold * failing_floor:
        return "Failing"
    return "Needs Attention"


def classify_quadrant(row: pd.Series) -> str:
    """Assign a SKU to a rationalization quadrant based on velocity/margin flags."""
    if row["high_velocity"] and row["high_margin"]:
        return "Winner"
    if row["high_velocity"] and not row["high_margin"]:
        return "Volume play"
    if not row["high_velocity"] and row["high_margin"]:
        return "Niche / slow"
    return "Cut candidate"


def apply_expansion_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Volume-tier-weighted score and equal-interval tier bucketing.

    Tiers split the score RANGE into three equal intervals (min..max),
    not equal-count quantiles — so this is not a tertile/quantile split
    and a bucket can hold any number of SKUs.
    """
    df = df.copy()
    df["tier_mult"] = df["volume_tier"].map(VOLUME_TIER_MULT).fillna(1.0)
    df["score"] = (df["avg_velocity"] * df["tier_mult"]).round(2)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    score_min = df["score"].min()
    score_max = df["score"].max()
    score_span = score_max - score_min

    if score_span < 1e-9:
        df["tier"] = "All equivalent"
    else:
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
