# Plan — Cinderhaven Velocity Decision Tool

## Goal (2026-05-15)

Replace the Story mode with a portfolio health dashboard as the default landing
page, and enhance the decision modes to tell a more compelling story when
prospects drill in.

**Audience:** Cold-landing CEO of a $20-25M food company. Lean org, velocity-
minded, zero onboarding tolerance. Already uses velocity for production planning
but is data-hungry for shelf defense, promo ROI, and other areas their current
system can't serve.

**Scope:**
- Remove story.py and all story UI (deep dive sidebar section, callbacks, etc.)
- Build a portfolio health overview as the new landing view: business-wide
  metrics, time-series trends, risk indicators across the portfolio
- Enhance decision modes with time-series charts, contextual insights, and
  "so what" narrative framing — the decision modes ARE the story chapters
- Clear drill-down paths from portfolio health into the relevant decision modes
- Existing Cinderhaven dataset only (no new synthetic data)

**Out of scope:**
- Competitive benchmarking (requires new synthetic data — separate workstream)
- New decision modes

**Done looks like:**
The tool tells a portfolio story from the moment you land. The health overview
hooks you by surfacing what's interesting (at-risk clusters, production spikes,
promo patterns). Each decision mode delivers a clear "here's what's happening
and what to do about it" narrative. No separate story mode needed because the
whole tool IS the story. A prospect walks away thinking "I need this for my
data."

**Key assumptions:**
- The Cinderhaven dataset was purpose-built for this tool and has realistic
  patterns worth discovering at the portfolio level (confirmed)
- Decision modes are narrative building blocks, not frozen — they can and
  should be enhanced to be more compelling (confirmed)

---

## Decomposition: Portfolio Health Dashboard

Goal: Replace Story mode with a portfolio health landing page and enhance
decision modes as narrative building blocks — so the whole tool tells the
portfolio story.

### Track A — Landing page (sequential)

- [x] A1: Remove Story mode
    - Depends on: none
    - Delete story.py. Remove all story references from callbacks.py
      (story_layout import, view=="story" branch, came-from-story back-button
      logic, enter_story callback), layout.py (_deep_dive_section, view-store
      "story" handling, came-from-story/scroll-to-section-5 stores), run.py
      (story_cbs import + registration), constants.py (PROTAGONIST_SKU), and
      CSS (.story-entry-btn, .back-to-story-btn). Remove story-only data
      functions from data.py (get_monday_morning_summary,
      get_sku_weekly_velocity, get_promo_hangover_data, get_sku_trade_spend,
      get_walmart_trajectory, get_sku_revenue_at_risk, get_sku_costs,
      get_category_avg_velocity, get_top_demand_4wk, get_top_velocity_per_door,
      get_bottom_stores_below_threshold, get_top_elasticity_skus).
    - Done when: story.py is gone, app starts cleanly, all 8 decision modes
      still work, no import errors.

- [x] A2: Portfolio health data layer
    - Depends on: none
    - New functions in data.py that aggregate across decision areas to produce
      portfolio-level metrics. Compose from existing queries where possible:
      get_shelf_defense_data("All Retailers"), get_production_data("All
      Retailers"), get_rationalization_data("All Retailers"),
      get_launch_data(). Return: total active SKUs, retailer count, at-risk
      counts by area (shelf-risk, decelerating, low-rationalization-score),
      accelerating counts, launch health summary. No new SQL if avoidable.
    - Done when: A `get_portfolio_summary()` function returns a dict of
      portfolio-wide metrics. Unit tests verify the shape and types.

- [x] A3: Portfolio health landing page
    - Depends on: A1, A2
    - New `decisions/portfolio_health.py` module with a `layout()` function
      that renders: KPI row (total SKUs, total retailers, total doors,
      latest week), risk indicator cards by decision area (at-risk shelf SKUs,
      decelerating production SKUs, underperforming rationalization scores,
      recent launches needing attention), and status distribution summary.
      Wire as the default view: dispatcher renders portfolio health when
      decision-picker value is a new "Portfolio Health" entry at index 0
      (existing modes shift to indices 1-8).
    - Done when: App launches to the portfolio health page. KPIs and risk
      cards render with real Cinderhaven data. Decision picker still switches
      to all 8 existing modes.

- [x] A4: Drill-down navigation
    - Depends on: A3
    - Risk indicator cards on the portfolio health page are clickable. Clicking
      one sets the decision-picker to the corresponding mode (e.g., clicking
      "3 at-risk SKUs" navigates to Shelf Defense). Use clientside callback
      or regular callback to update the decision-picker value.
    - Done when: Each risk card navigates to the correct decision mode.
      Browser test confirms the round-trip: land on portfolio → click a
      risk card → arrive at the right decision mode with data loaded.

### Track B — Decision mode enhancements (parallel, independent of A)

- [x] B1: Decision mode narrative framing
    - Depends on: none
    - Add a "so what" insight section to each of the 8 decision modes: a
      1-2 sentence contextual interpretation below the headline that frames
      the business implication. Example: Shelf Defense currently says "12 of
      45 SKUs are at risk" — add "These 12 SKUs represent $X in weekly
      revenue. Losing shelf space here shifts volume to competitors." Derive
      from existing data already available in each layout function.
    - Done when: Each mode shows a contextual insight that references
      specific numbers from the current filter selection. Visual QA confirms
      readability.

- [x] B2: Decision mode time-series additions
    - Depends on: none
    - Add trend visualizations to decision modes that currently show only
      point-in-time data. Candidates: Shelf Defense (velocity trend over
      last 12 weeks for at-risk SKUs), Production (trend line alongside
      the bar chart), Rationalization (score trend). Use existing weekly
      scan data — no new synthetic data.
    - Done when: At least 3 decision modes gain a time-series chart that
      uses real Cinderhaven data. Charts render without errors.

### Integration

- [x] C: End-to-end polish
    - Depends on: A4, B1, B2
    - Full flow verification in browser: land on portfolio health → read
      the KPIs → click a risk card → arrive at decision mode with narrative
      context → return to portfolio. Visual QA for layout consistency,
      loading states, and mobile-width degradation. Fix any regressions.
    - Done when: A prospect can walk through the tool cold and understand
      what Cinderhaven's portfolio looks like within 30 seconds of landing.

---

## Goal: Data Integrity Hardening (2026-05-17)

**Source:** Audit Phase 4 (2026-05-17)
**Category:** Foundational + Double down
**Priority:** P0 — must complete before redeploying with rebuilt dataset

### Objective

Ensure the tool's math, classifiers, and thresholds produce correct results
with the rebuilt dataset. Fix silent-failure paths, validate the data contract,
and recalibrate thresholds if distributions shifted.

### Success Criteria

- App boots with rebuilt data and logs validation results (pass/fail per table)
- No division-by-zero possible in any calculation path
- All thresholds read from constants.py (zero hardcoded duplicates)
- Seasonal factor is validated or explicitly disabled with a warning
- Velocity distributions confirm thresholds produce sensible classifications
- Tests cover the 6 previously untested calculation chains

---

## Decomposition: Data Integrity Hardening

Goal: Fix every silent-failure path identified in the audit so the tool
produces correct numbers — or fails loudly — with the rebuilt dataset.

### Batch 1 — Immediate fixes (no dependencies, all parallel)

- [x] B1-A: Fix division-by-zero in promo ROI
    - Depends on: none
    - In data.py:486, add `df = df[df["baseline_v"] > 0].reset_index(drop=True)`
      before the `lift_pct` calculation, matching the pattern already used in
      get_pricing_data (line 819). Also add the same guard for `dip_pct` on
      line 487 (same denominator).
    - Done when: `get_promo_roi_data()` returns no inf/NaN in lift_pct when
      called with test data that includes baseline_v = 0. Existing tests pass.

- [x] B1-B: Fix division-by-zero in shelf defense trend
    - Depends on: none
    - In shelf_defense.py:47, change `/ df["trailing_v"]` to
      `/ df["trailing_v"].replace(0, pd.NA)`, matching the pattern in
      data.py:398 (production trend).
    - Done when: `_classify_shelf_status()` produces NaN (not inf) for
      trend_pct when trailing_v is 0. Classification still works (NaN trend
      doesn't affect status assignment because the classifier checks
      `pd.notna(t)` separately). Existing tests pass.

- [x] B1-C: Validate seasonal data coverage
    - Depends on: none
    - In data.py `get_production_data()`, after computing `seasonal_factor`,
      add a check: if more than 50% of rows have `sf == 1.0` (the NaN
      fallback), log a warning: "Seasonal adjustment inactive for {n}/{total}
      SKUs — dataset may not span a full year." This surfaces the silent
      failure without changing behavior.
    - Done when: Running the app against a dataset with <392 days of history
      produces a logged warning. Running against a full-year dataset produces
      no warning. No behavior change to existing forecasts.

- [x] B1-D: Consolidate hardcoded threshold = 2.0
    - Depends on: none
    - Add `LAUNCH_BENCHMARK = 2.0` to constants.py (or reuse
      `RETAILER_THRESHOLDS["Walmart"]` — same value, but semantically it's
      a launch benchmark, not a retailer threshold; use a new constant).
    - Replace the 3 hardcoded values:
      - launch_health.py:83 → read from constants
      - pitch_export.py:61 → read from constants
      - data.py:161 → read from constants
    - Done when: `grep -rn "threshold = 2.0\|launch_thr = 2.0" app/` returns
      zero matches. All 3 files import from constants. App starts cleanly.

- [x] B1-E: Reduce cache TTL for validation period
    - Depends on: none
    - In data.py:34, change `CACHE_DEFAULT_TIMEOUT` from 86400 (24h) to
      21600 (6h). Add a comment noting this is reduced for the validation
      period and can return to 86400 once data is confirmed stable.
    - Done when: Cache config shows 21600. App restarts successfully.

### Batch 2 — Data contract validation (sequential)

- [x] B2-A: Startup data contract check function
    - Depends on: B1-E (cache reduction helps catch issues faster)
    - Create a new function `validate_data_contract()` in data.py (or a new
      `app/validation.py` module) that runs 7 SQL checks on boot:
      1. All 6 tables exist and have >0 rows
      2. stg_scan_data date range spans ≥392 days (for seasonal factor)
      3. dim_products has no case_pack_qty = 0 or NULL
      4. stg_stores volume_tier values are all in {A, B, C}
      5. stg_stores retailer values include all PHYSICAL_RETAILERS +
         REGIONAL_CHAINS + ["UNFI", "DTC"]
      6. Every SKU in stg_scan_data has a matching row in stg_sku_costs
      7. fct_distribution has >0 rows with non-null authorized_date
    - Return a dict of {check_name: (pass/fail, detail_message)}.
    - Done when: Function runs against the rebuilt DB and returns results for
      all 7 checks. Each check independently reports pass or fail with a
      human-readable message.

- [x] B2-B: Wire validation into app startup
    - Depends on: B2-A
    - Call `validate_data_contract()` in run.py after cache init but before
      `warm_default_view()`. Log results at INFO level (passes) and WARNING
      level (failures). Do NOT block startup on failures — log and continue
      so the app is still accessible for debugging. Print a summary line:
      "Data contract: 7/7 checks passed" or "Data contract: 5/7 checks
      passed — see warnings above."
    - Done when: App startup logs show validation results. A deliberately
      broken check (e.g., dropping a test table) produces a WARNING log.

- [x] B2-C: Threshold recalibration analysis
    - Depends on: B2-A (need the validation function to confirm data is
      queryable)
    - Run a one-time analysis (can be a script or notebook) against the
      rebuilt dataset:
      1. For each retailer in PHYSICAL_RETAILERS, query the velocity
         distribution: p10, p25, median, p75, p90 of current_v from
         get_shelf_defense_data().
      2. Compare against RETAILER_THRESHOLDS. A threshold should land
         roughly between p10 and p25 to flag the bottom ~15-25% as "At Risk."
         If >50% of SKUs are "At Risk" or <5% are, the threshold is miscalibrated.
      3. Check production trend distribution: what % are Accelerating /
         Decelerating / Stable? Should be roughly 15-30% / 15-30% / rest.
         If >80% are Stable, the ±10% threshold may be too loose.
      4. Check launch health: how many launches exist? If 0, document why
         (dataset may not have recent enough authorized_dates).
    - Done when: A report (printed to console or written to a markdown file)
      shows the distribution analysis for each retailer and decision area,
      with a recommendation of "keep" or "adjust to X" for each threshold.

### Batch 3 — Calculation chain tests

- [x] B3-A: Production forecast chain tests
    - Depends on: B1-A, B1-C (division fixes should be in place)
    - Add tests in tests/test_calculations.py (new file) covering:
      1. weekly_units = sum_recent / 4 (basic case)
      2. weekly_cases with case_pack_qty = 1, 6, 12
      3. seasonal_factor when sum_ly_current = 0 (should be 1.0)
      4. seasonal_factor clipping at 0.5 and 2.0 boundaries
      5. trend_pct when phys_v_prior = 0 (should be NaN → "Stable")
      6. forecast_4w_units = weekly_units × sf × 4
    - Use synthetic DataFrames, no DB connection needed.
    - Done when: 6+ tests pass covering the full production chain. pytest
      output shows all green.

- [x] B3-B: Promo ROI chain tests
    - Depends on: B1-A (division fix)
    - Add tests covering:
      1. lift_pct when baseline_v > 0 (normal case)
      2. baseline_v = 0 rows are excluded (post-fix behavior)
      3. incremental_units calculation (pv - bv) × doors × weeks
      4. promo_cost calculation
      5. roi_pct when promo_cost = 0 (should be NaN)
      6. roi_tier classification at boundaries (0%, 100%)
    - Done when: 6+ tests pass. pytest output shows all green.

- [x] B3-C: Remaining chain tests (pricing, expansion, pruning, rationalization)
    - Depends on: B1-B (shelf defense fix)
    - Add tests covering:
      1. Pricing: elasticity = lift_pct / avg_discount; recovery_ratio;
         verdict logic for negative elasticity
      2. Expansion: score = avg_velocity × tier_mult; tertile bucketing
         when all scores are identical
      3. Pruning: p20 quantile; shelf_cost = (median - velocity) × price;
         severity by SKU (≥50% → Critical) and by store (≥3 → Critical)
      4. Rationalization: margin_per_unit = wholesale - cogs; quadrant
         assignment using medians; cut candidate projection
    - Done when: 12+ tests pass across the 4 chains. pytest output shows
      all green. Total test count rises from 26 to ~50+.
