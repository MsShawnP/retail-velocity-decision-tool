"""Tests for pricing power, expansion scoring, pruning severity, and
rationalization quadrant calculation chains.

All run without a database — operates on synthetic DataFrames.
"""

from __future__ import annotations

import pandas as pd
import pytest

from constants import THRESHOLDS, VOLUME_TIER_MULT
from decisions.pricing_power import _verdict


# ============================================================
# Pricing Power chain
# ============================================================

def _apply_pricing_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the post-SQL chain from data.py get_pricing_data."""
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


def _pricing_row(**overrides) -> dict:
    defaults = {
        "sku": "SKU-001",
        "product_name": "Test",
        "product_line": "Sauces",
        "baseline_v": 10.0,
        "promo_v": 15.0,
        "post_v": 9.8,
        "avg_discount": 0.20,
        "n_promos": 3,
    }
    defaults.update(overrides)
    return defaults


class TestPricingElasticity:
    def test_positive_elasticity(self):
        df = _apply_pricing_calcs(pd.DataFrame([
            _pricing_row(baseline_v=10.0, promo_v=15.0, avg_discount=0.20)
        ]))
        assert df["elasticity"].iloc[0] == pytest.approx(2.5)

    def test_zero_discount_produces_nan(self):
        df = _apply_pricing_calcs(pd.DataFrame([
            _pricing_row(baseline_v=10.0, promo_v=15.0, avg_discount=0.0)
        ]))
        assert pd.isna(df["elasticity"].iloc[0])

    def test_negative_elasticity(self):
        df = _apply_pricing_calcs(pd.DataFrame([
            _pricing_row(baseline_v=10.0, promo_v=8.0, avg_discount=0.20)
        ]))
        assert df["elasticity"].iloc[0] == pytest.approx(-1.0)


class TestRecoveryStatus:
    def test_full_recovery(self):
        df = _apply_pricing_calcs(pd.DataFrame([_pricing_row(baseline_v=10.0, post_v=9.6)]))
        assert df["recovery_status"].iloc[0] == "Full Recovery"

    def test_partial_recovery(self):
        df = _apply_pricing_calcs(pd.DataFrame([_pricing_row(baseline_v=10.0, post_v=8.5)]))
        assert df["recovery_status"].iloc[0] == "Partial Recovery"

    def test_slow_recovery(self):
        df = _apply_pricing_calcs(pd.DataFrame([_pricing_row(baseline_v=10.0, post_v=7.0)]))
        assert df["recovery_status"].iloc[0] == "Slow Recovery"

    def test_nan_post_v_is_slow(self):
        df = _apply_pricing_calcs(pd.DataFrame([_pricing_row(baseline_v=10.0, post_v=None)]))
        assert df["recovery_status"].iloc[0] == "Slow Recovery"


class TestVerdict:
    def test_promote_again(self):
        row = pd.Series({"elasticity": 2.0, "recovery_status": "Full Recovery"})
        assert _verdict(row) == "Promote again"

    def test_promote_cautiously(self):
        row = pd.Series({"elasticity": 1.5, "recovery_status": "Partial Recovery"})
        assert _verdict(row) == "Promote cautiously"

    def test_stop_promoting(self):
        row = pd.Series({"elasticity": 1.0, "recovery_status": "Slow Recovery"})
        assert _verdict(row) == "Stop promoting"

    def test_promo_backfired(self):
        row = pd.Series({"elasticity": -0.5, "recovery_status": "Full Recovery"})
        assert _verdict(row) == "Promo backfired"

    def test_nan_elasticity_uses_recovery(self):
        row = pd.Series({"elasticity": float("nan"), "recovery_status": "Full Recovery"})
        assert _verdict(row) == "Promote again"


# ============================================================
# Expansion scoring chain
# ============================================================

def _apply_expansion_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the post-SQL chain from data.py get_expansion_data."""
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


def _expansion_row(**overrides) -> dict:
    defaults = {
        "store_id": 1,
        "retailer": "Walmart",
        "region": "Northeast",
        "state": "NY",
        "volume_tier": "B",
        "n_similar": 3,
        "avg_velocity": 5.0,
    }
    defaults.update(overrides)
    return defaults


class TestExpansionScore:
    def test_tier_b_multiplier_is_1(self):
        df = _apply_expansion_calcs(pd.DataFrame([_expansion_row(volume_tier="B", avg_velocity=5.0)]))
        assert df["score"].iloc[0] == pytest.approx(5.0)

    def test_tier_a_boosts_score(self):
        df = _apply_expansion_calcs(pd.DataFrame([_expansion_row(volume_tier="A", avg_velocity=5.0)]))
        assert df["score"].iloc[0] == pytest.approx(6.5)

    def test_tier_c_reduces_score(self):
        df = _apply_expansion_calcs(pd.DataFrame([_expansion_row(volume_tier="C", avg_velocity=5.0)]))
        assert df["score"].iloc[0] == pytest.approx(3.5)

    def test_unknown_tier_defaults_to_1(self):
        df = _apply_expansion_calcs(pd.DataFrame([_expansion_row(volume_tier="D", avg_velocity=5.0)]))
        assert df["score"].iloc[0] == pytest.approx(5.0)


class TestExpansionTiers:
    def test_tertile_bucketing(self):
        rows = [
            _expansion_row(store_id=1, avg_velocity=10.0, volume_tier="B"),
            _expansion_row(store_id=2, avg_velocity=5.0, volume_tier="B"),
            _expansion_row(store_id=3, avg_velocity=1.0, volume_tier="B"),
        ]
        df = _apply_expansion_calcs(pd.DataFrame(rows))
        assert df["tier"].iloc[0] == "Strongest"
        assert df["tier"].iloc[-1] == "Worth considering"

    def test_all_identical_scores(self):
        rows = [
            _expansion_row(store_id=i, avg_velocity=5.0, volume_tier="B")
            for i in range(3)
        ]
        df = _apply_expansion_calcs(pd.DataFrame(rows))
        assert len(df["tier"].unique()) == 1
        assert df["tier"].iloc[0] == "Worth considering"


# ============================================================
# Pruning severity chain
# ============================================================

class TestPruningSeverityBySKU:
    def test_critical(self):
        crit_pct = THRESHOLDS["pruning_sku_critical"] * 100
        assert _sku_severity(crit_pct) == "Critical"
        assert _sku_severity(crit_pct + 10) == "Critical"

    def test_concerning(self):
        conc_pct = THRESHOLDS["pruning_sku_concerning"] * 100
        crit_pct = THRESHOLDS["pruning_sku_critical"] * 100
        mid = (conc_pct + crit_pct) / 2
        assert _sku_severity(mid) == "Concerning"

    def test_mild(self):
        conc_pct = THRESHOLDS["pruning_sku_concerning"] * 100
        assert _sku_severity(conc_pct - 5) == "Mild"


class TestPruningSeverityByStore:
    def test_critical(self):
        crit = THRESHOLDS["pruning_store_critical"]
        assert _store_severity(crit) == "Critical"
        assert _store_severity(crit + 1) == "Critical"

    def test_concerning(self):
        conc = THRESHOLDS["pruning_store_concerning"]
        assert _store_severity(conc) == "Concerning"

    def test_mild(self):
        assert _store_severity(0) == "Mild"


def _sku_severity(pct_below: float) -> str:
    """Reproduce pruning SKU severity from pruning.py."""
    crit_pct = THRESHOLDS["pruning_sku_critical"] * 100
    conc_pct = THRESHOLDS["pruning_sku_concerning"] * 100
    if pct_below >= crit_pct:
        return "Critical"
    if pct_below >= conc_pct:
        return "Concerning"
    return "Mild"


def _store_severity(n_below: int) -> str:
    """Reproduce pruning store severity from pruning.py."""
    store_crit = THRESHOLDS["pruning_store_critical"]
    store_conc = THRESHOLDS["pruning_store_concerning"]
    if n_below >= store_crit:
        return "Critical"
    if n_below >= store_conc:
        return "Concerning"
    return "Mild"


class TestShelfCost:
    def test_basic_shelf_cost(self):
        velocity = pd.Series([2.0, 5.0, 8.0])
        price = pd.Series([10.0, 10.0, 10.0])
        median_v = velocity.median()
        shelf_cost = ((median_v - velocity) * price).round(2)
        assert shelf_cost.iloc[0] == pytest.approx(30.0)
        assert shelf_cost.iloc[1] == pytest.approx(0.0)
        assert shelf_cost.iloc[2] == pytest.approx(-30.0)


# ============================================================
# Rationalization quadrant chain
# ============================================================

def _apply_rat_calcs(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the margin + quadrant chain from data.py and rationalization.py."""
    df = df.copy()
    df["margin_per_unit"] = (df["wholesale_price"] - df["cogs_per_unit"]).round(2)
    df["margin_per_sw"] = (df["velocity"] * df["margin_per_unit"]).round(2)
    df["revenue_per_sw"] = (df["velocity"] * df["wholesale_price"]).round(2)
    df["weekly_total_margin"] = (df["margin_per_sw"] * df["doors"]).round(0)

    median_velocity = df["velocity"].median()
    median_margin = df["margin_per_sw"].median()
    df["high_velocity"] = df["velocity"] > median_velocity
    df["high_margin"] = df["margin_per_sw"] > median_margin

    def quadrant(row: pd.Series) -> str:
        if row["high_velocity"] and row["high_margin"]:
            return "Winner"
        if row["high_velocity"] and not row["high_margin"]:
            return "Volume play"
        if not row["high_velocity"] and row["high_margin"]:
            return "Niche / slow"
        return "Cut candidate"

    df["quadrant"] = df.apply(quadrant, axis=1)
    return df


def _rat_row(**overrides) -> dict:
    defaults = {
        "sku": "SKU-001",
        "product_name": "Test",
        "product_line": "Sauces",
        "wholesale_price": 10.0,
        "cogs_per_unit": 6.0,
        "velocity": 5.0,
        "doors": 100,
    }
    defaults.update(overrides)
    return defaults


class TestMarginCalcs:
    def test_margin_per_unit(self):
        df = _apply_rat_calcs(pd.DataFrame([_rat_row(wholesale_price=10.0, cogs_per_unit=6.0)]))
        assert df["margin_per_unit"].iloc[0] == pytest.approx(4.0)

    def test_negative_margin(self):
        df = _apply_rat_calcs(pd.DataFrame([_rat_row(wholesale_price=5.0, cogs_per_unit=8.0)]))
        assert df["margin_per_unit"].iloc[0] == pytest.approx(-3.0)

    def test_margin_per_store_week(self):
        df = _apply_rat_calcs(pd.DataFrame([
            _rat_row(wholesale_price=10.0, cogs_per_unit=6.0, velocity=5.0)
        ]))
        assert df["margin_per_sw"].iloc[0] == pytest.approx(20.0)

    def test_weekly_total_margin(self):
        df = _apply_rat_calcs(pd.DataFrame([
            _rat_row(wholesale_price=10.0, cogs_per_unit=6.0, velocity=5.0, doors=100)
        ]))
        assert df["weekly_total_margin"].iloc[0] == 2000.0


class TestQuadrantAssignment:
    def test_four_quadrants(self):
        rows = [
            _rat_row(sku="A", velocity=10.0, wholesale_price=10.0, cogs_per_unit=2.0),
            _rat_row(sku="B", velocity=10.0, wholesale_price=10.0, cogs_per_unit=9.5),
            _rat_row(sku="C", velocity=1.0, wholesale_price=10.0, cogs_per_unit=2.0),
            _rat_row(sku="D", velocity=1.0, wholesale_price=10.0, cogs_per_unit=9.5),
        ]
        df = _apply_rat_calcs(pd.DataFrame(rows))
        quadrants = dict(zip(df["sku"], df["quadrant"]))
        assert quadrants["A"] == "Winner"
        assert quadrants["B"] == "Volume play"
        assert quadrants["C"] == "Niche / slow"
        assert quadrants["D"] == "Cut candidate"

    def test_all_identical_falls_to_one_quadrant(self):
        rows = [_rat_row(sku=f"S{i}") for i in range(4)]
        df = _apply_rat_calcs(pd.DataFrame(rows))
        assert len(df["quadrant"].unique()) == 1
