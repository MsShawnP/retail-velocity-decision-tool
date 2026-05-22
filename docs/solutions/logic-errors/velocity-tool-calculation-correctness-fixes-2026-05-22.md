---
title: "Fix 17 data integrity and calculation correctness issues in velocity decision tool"
date: 2026-05-22
category: logic-errors
module: calcs
problem_type: logic_error
component: service_object
severity: critical
symptoms:
  - "Forecast values lost precision due to premature .round(2) before aggregation"
  - "Promo baseline guard silently dropped promotions without tracking exclusion count"
  - "Pricing elasticity risked division by near-zero discount denominators"
  - "Production trend status failed to detect acceleration when prior period was zero or NaN"
  - "NaN elasticity fell through to Stop promoting verdict instead of Insufficient data"
root_cause: logic_error
resolution_type: code_fix
tags:
  - data-integrity
  - calculation-correctness
  - edge-cases
  - guard-clauses
  - null-handling
  - rounding
  - threshold-consolidation
---

# Fix 17 data integrity and calculation correctness issues in velocity decision tool

## Problem

The calculation layer contained 17 data integrity and correctness bugs -- 5 critical -- where premature rounding, missing null guards, hardcoded magic numbers, and silent data drops produced incorrect forecasts, misleading pricing verdicts, and wrong trend classifications across the tool's 9 decision modes.

## Symptoms

- **Forecast drift**: `.round(2)` applied per-SKU in `calcs.py` before aggregation caused cumulative rounding error in production planning totals.
- **Silent promo exclusion**: Promotions with zero baseline velocity were quietly dropped from ROI analysis with no indication to the user.
- **Extreme elasticity values**: Near-zero discount denominators (e.g., 0.001) passed a bare `!= 0` guard and produced wildly inflated elasticity scores.
- **Wrong trend labels**: SKUs with zero or NaN prior velocity but positive current velocity were labeled "Stable" instead of "Accelerating".
- **Incorrect pricing verdict**: NaN elasticity fell through cascading if/else logic to "Stop promoting" -- the most severe recommendation.
- **Masked null shelf data**: `has_current_data` was evaluated after `fillna(0)`, so truly missing shelf data appeared as valid zeros.
- **Magic number fragility**: Six threshold values were hardcoded inline, invisible to configuration.
- **No upstream data quality checks**: Duplicate scan data rows and null cost fields could enter the pipeline undetected.

## What Didn't Work

- The existing 160-test suite did not catch these bugs because tests mocked at boundaries that matched the buggy behavior (e.g., tests expected a bare DataFrame return from `apply_promo_calcs`, not a tuple). (session history)
- A prior session (May 17) had already identified division-by-zero risks in promo ROI and shelf defense, fixing them with `.replace(0, pd.NA)` guards -- but the pricing elasticity near-zero case used a different pattern (`!= 0` instead of a minimum threshold) and was missed. (session history)
- The May 17 session also consolidated `LAUNCH_BENCHMARK` thresholds but left other hardcoded values (seasonal clip bounds, promo timing windows, pricing minimum discount) scattered across files. (session history)
- A `replace_all` edit during the fix pass missed one test file with a different mock response structure, requiring a manual follow-up.
- The fixes themselves introduced a new lint issue (unused `THRESHOLDS` import in `data.py`) -- multi-file refactors need a lint pass afterward.

## Solution

### 1. Forecast rounding (calcs.py)

Before:
```python
df["forecast_4w_cases"] = (df["forecast_4w_units"] / cpq).round(2)
```

After:
```python
df["forecast_4w_cases"] = df["forecast_4w_units"] / cpq
```

Display rounding moved to `production.py` at the presentation layer.

### 2. Promo baseline guard (calcs.py)

Before:
```python
def apply_promo_calcs(df) -> pd.DataFrame:
    df = df[df["baseline_v"] > 0]  # silent drop
```

After:
```python
def apply_promo_calcs(df) -> tuple[pd.DataFrame, int]:
    n_excluded = int((df["baseline_v"] <= 0).sum())
    df = df[df["baseline_v"] > 0]
    ...
    return df, n_excluded
```

UI now shows exclusion count in both empty-state and populated views.

### 3. Pricing elasticity guard (calcs.py)

Before: `if avg_discount != 0` (allows 0.001 through).

After: uses `THRESHOLDS["pricing_min_discount"]` (0.01) as minimum via `df["avg_discount"].where(df["avg_discount"] >= min_disc, pd.NA)`.

### 4. Seasonal factor hardcoding (calcs.py + constants.py)

Before: `np.clip(factor, 0.5, 2.0)` with magic numbers.

After: `np.clip(factor, THRESHOLDS["seasonal_clip_lower"], THRESHOLDS["seasonal_clip_upper"])` with values defined in `constants.py`.

### 5. Production trend status (calcs.py)

Before: simple float comparison `if t > accel_pct: return "Accelerating"`.

After: row-based function that checks for zero/NaN prior with positive current:
```python
def status(row):
    t = row["trend_pct"]
    if pd.isna(t):
        if pd.isna(row["phys_v_prior"]) or row["phys_v_prior"] == 0:
            if pd.notna(row["phys_v_recent"]) and row["phys_v_recent"] > 0:
                return "Accelerating"
        return "Stable"
    if t > accel_pct: return "Accelerating"
    if t < decel_pct: return "Decelerating"
    return "Stable"
```

### 6. Pricing NaN verdict (pricing_power.py)

Added `if pd.isna(row["elasticity"]): return "Insufficient data"` as the first check, with grey styling.

### 7. Shelf defense null detection (data.py)

Set `has_current_data` flag before `fillna(0)` so true nulls are detected.

### 8. New validation checks (validation.py)

- Scan data grain: detects duplicate `(store_id, week_ending, sku)` rows.
- Cost completeness: detects null `wholesale_price` or `cogs_per_unit`.

### 9. Constants consolidation (constants.py)

Added 6 threshold entries: `seasonal_clip_lower`, `seasonal_clip_upper`, `promo_baseline_days`, `promo_post_start_days`, `promo_post_end_days`, `pricing_min_discount`.

## Why This Works

The root cause across all 17 issues was mixing calculation logic with presentation concerns and using implicit assumptions instead of explicit guards:

- Rounding belongs at the display layer, not inside calculations that feed downstream aggregations.
- Functions that filter data must report what they filtered so the user can assess data completeness.
- Numeric guards need domain-meaningful thresholds (0.01 minimum discount), not bare zero checks.
- Null/NaN handling must happen before any transformation that masks nulls (like `fillna`), and NaN must be an explicit branch in decision logic.
- Magic numbers scattered across code become configuration drift risks; centralizing them in a `THRESHOLDS` dict makes them auditable.
- Upstream data quality issues must be caught at ingestion, not discovered as anomalies downstream.

## Prevention

1. **Rounding policy**: `.round()` never called inside `calcs.py`. All rounding at the presentation layer in decision modules.

2. **Return type discipline**: Any function that filters rows returns a count of excluded rows. Enforced via type annotations.

3. **Threshold registry**: All numeric thresholds live in `constants.py THRESHOLDS` dict. A prior session (May 17) consolidated `LAUNCH_BENCHMARK`; this session completed the pattern for seasonal, promo, and pricing thresholds. (session history)

4. **NaN-first branching**: In any decision/classification function, the first check is for NaN/null inputs.

5. **Null-before-fill ordering**: Any `fillna` call must have null-detection flags set beforehand.

6. **Edge case test matrix**: For trend classification and categorical logic, test matrix covers: zero prior, NaN prior, zero current, NaN current, equal values, and normal changes. This session added 3 tests for exactly these gaps.

7. **Post-refactor lint pass**: Run `ruff check` after any multi-file refactor before committing.

8. **Upstream validation at startup**: `validation.py` checks run at boot. A prior session (May 17) created the initial 7 checks; this session added 2 more (scan grain, cost completeness). Note from session history: the initial deploy of validation crashed because the call was not wrapped in try/except -- always make startup validation non-fatal. (session history)

## Related Issues

- Prior session (May 17) created `validation.py` with 7 data contract checks and 63 calculation chain tests across 3 new test files. This session extended that work with 2 new validation checks and 3 new tests (163 total). (session history)
- Prior session (May 17) ran threshold recalibration analysis showing all retailer velocity thresholds are below p10 for the current dataset. Recalibration was deferred and the analysis script was not committed. (session history)
- Prior session (May 20) found a broken SQL interval parameter in `get_category_benchmark_weekly()` where `interval '%s days'` cannot be parameterized by psycopg2, producing malformed SQL that was silently swallowed by `except Exception`. (session history)
