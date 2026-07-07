# Project Audit — Cinderhaven Velocity Decision Tool

## Phase 1: Baseline Assessment
**Date:** 2026-05-17
**Project:** Cinderhaven Velocity Decision Tool
**Audit focus:** Data source changed substantially — verify math/analysis integrity

### What Was Intended

A prescriptive decision tool for specialty food CEOs scaling into national
retail ($15M–$50M). The tool takes weekly velocity reports and converts them
into actionable decisions across 9 areas: portfolio health, shelf defense,
production planning, promo ROI, distribution expansion, distribution pruning,
SKU rationalization, launch health, and pricing power. Flagship portfolio piece
for a decision-framework consulting practice.

### What Exists Today

Fully deployed Dash application at velocity.lailarallc.com.
9 decision modes operational. Portfolio health landing page with drill-down
navigation. Narrative "so what" insights on every decision mode. Time-series
trend charts on shelf defense, production, and launch health. Retailer pitch
export (Excel + PDF). CI pipeline with 26 tests. Deployed on Fly.io with
Postgres backend.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Dash 3.x + Dash Bootstrap Components + AG Grid |
| Charts | Plotly (SVG, Economist style) |
| Data | Pandas, psycopg2 ThreadedConnectionPool (maxconn=10) |
| Database | Postgres on Fly.io |
| Cache | flask-caching FileSystemCache on persistent Fly volume |
| Server | Gunicorn (1 worker, 4 gthread threads, 120s timeout) |
| Hosting | Fly.io (shared-cpu-1x, 1GB RAM, always-on) |
| CI | GitHub Actions (pytest + ruff) |
| Export | openpyxl, xlsxwriter, fpdf2 |

### Project Health Indicators

| Indicator | Status |
|-----------|--------|
| Activity | Active — 101 commits over 14 days, most recent today |
| Documentation | Good — README, PLAN, DECISIONS, FAILURES, HANDOFF all current |
| Test coverage | Partial — 26 tests across 6 modules; classifiers and helpers covered, but no integration tests against live data |
| Dependencies | Current — all pinned to recent versions |
| Deployment | Live and healthy on Fly.io |

### Codebase Shape

- **~7,350 lines** across 15 Python modules + CSS + tests
- **12 data query functions** in data.py (all SQL against Postgres)
- **9 decision modules** in app/decisions/
- **20+ hardcoded thresholds** in constants.py
- **6 database tables** depended on: stg_scan_data, stg_stores, stg_promotions, dim_products, stg_sku_costs, fct_distribution

### Gap Analysis

The prior audit (2026-05-15) addressed connection management, README staleness,
health checks, CI, tests, and inline styles. Moves 1–2 were completed. The
project's code infrastructure is solid.

**The critical gap now is data-layer integrity.** The dataset was substantially
changed, and every calculation in the tool depends on assumptions about data
shape, scale, column semantics, and value distributions. Specifically:

1. **Threshold calibration.** Retailer thresholds (Walmart 2.0, Costco 5.0,
   Whole Foods 1.5, Regional 1.0) were tuned to the original dataset. If SKU
   count, store count, or velocity distributions shifted, these thresholds may
   produce nonsensical classifications (everything "At Risk" or everything "Safe").

2. **Time window alignment.** Multiple queries use hardcoded day offsets (28, 56,
   91, 112, 364, 392 days). If the new dataset covers a different time range or
   has gaps, these windows may return empty or misleading results.

3. **Column/table contract.** All 12 data functions depend on specific columns in
   6 tables. If the rebuild renamed columns, changed types, or dropped tables
   (especially fct_distribution which was manually created), queries will fail
   or return wrong results.

4. **Semantic drift.** Values like `is_aggregated_channel`, `volume_tier` (A/B/C),
   `case_pack_qty`, `wholesale_price`, and `cogs_per_unit` are used in formulas.
   If their meaning or scale changed, the math produces valid-looking but wrong
   numbers.

5. **Classifier boundary effects.** The launch health benchmark (2.0 u/s/w),
   pruning quantile (bottom 20%), and rationalization medians are all
   data-dependent. A different dataset shifts these boundaries and changes which
   SKUs land in which buckets.

### Audit Motivation

Data source was substantially rebuilt. Need to verify that the math, analysis
logic, classifiers, and thresholds still produce sensible results with the new
data — or identify where recalibration is needed.

---

## Phase 2: Internal Review
**Date:** 2026-05-17
**Dimensions reviewed:** All 8, weighted toward math/analysis integrity
**Focus:** Does the analysis still produce correct results after the data source rebuild?

### Top Opportunities (by leverage)

| # | Finding | Dimension | Impact | Effort | Leverage | Severity |
|---|---------|-----------|--------|--------|----------|----------|
| 1 | No startup data contract validation — schema/table changes fail silently at runtime | Architecture | 5 | 2 | 2.5 | Critical |
| 2 | Division by zero in promo ROI `lift_pct` when `baseline_v = 0` | Code quality | 5 | 1 | 5.0 | Critical |
| 3 | Seasonal factor breaks silently if data < 392 days (production forecast wrong) | Code quality | 5 | 2 | 2.5 | Critical |
| 4 | `fct_distribution` may not exist after rebuild — 3 decision modes depend on it | Architecture | 5 | 1 | 5.0 | Critical |
| 5 | Zero test coverage on 6 of 8 calculation chains (production, promo, pricing, pruning, rationalization, expansion) | Tests | 5 | 3 | 1.7 | Critical |
| 6 | Shelf defense `trend_pct` division by zero unguarded (trailing_v = 0) | Code quality | 4 | 1 | 4.0 | Important |
| 7 | Launch health hardcodes `threshold = 2.0` instead of reading from constants | Code quality | 3 | 1 | 3.0 | Important |
| 8 | Retailer names in constants not validated against actual DB values at startup | Architecture | 4 | 2 | 2.0 | Important |
| 9 | 24h cache TTL masks data quality issues during validation period | Performance | 3 | 1 | 3.0 | Important |
| 10 | Pitch export hardcodes `threshold=2.0` for launch classification — doesn't match UI | UX | 3 | 1 | 3.0 | Important |
| 11 | AG Grid `.2f` format loses precision at extremes (0.001→"0.00", 1000→"1000.00") | UX | 3 | 2 | 1.5 | Minor |
| 12 | PDF export truncates at 50 rows with no warning | UX | 2 | 1 | 2.0 | Minor |
| 13 | Portfolio health `round()` inconsistency (line 31 vs 60) | Code quality | 1 | 1 | 1.0 | Minor |

### Detailed Findings

#### Math & Calculation Correctness

**CRITICAL — Division-by-zero bugs (2 locations):**

1. [data.py:486](app/data.py:486) — Promo ROI `lift_pct = (pv - bv) / bv * 100`.
   No guard on `baseline_v = 0`. Unlike pricing power (line 819, which filters
   `baseline_v > 0`), promo ROI only does `dropna()`. A zero baseline produces
   infinity. **Fix:** Add `df = df[df["baseline_v"] > 0]` before computation.

2. [shelf_defense.py:47](app/decisions/shelf_defense.py:47) — `trend_pct =
   (current_v - trailing_v) / trailing_v * 100`. No `.replace(0, pd.NA)` guard.
   Production trend (data.py:398) has this guard; shelf defense doesn't.
   **Fix:** Add `.replace(0, pd.NA)` to trailing_v denominator.

**CRITICAL — Seasonal factor silent failure:**

3. [data.py:362-366](app/data.py:362) — Production forecast uses `sum_ly_forward /
   sum_ly_current` for seasonal adjustment. Requires 392+ days of history. If new
   dataset is shorter, both sums are NULL, `seasonal_factor` defaults to 1.0 for
   every SKU, and 4-week forecasts ignore seasonality entirely. No warning logged.

**IMPORTANT — Hardcoded threshold divergence:**

4. [launch_health.py:83](app/decisions/launch_health.py:83) and
   [pitch_export.py:61](app/pitch_export.py:61) — Both hardcode `threshold = 2.0`
   instead of reading from `RETAILER_THRESHOLDS`. If the constant changes, these
   locations stay stale. The pitch export also uses this hardcoded value, meaning
   exported classifications can differ from what the UI showed.

5. [data.py:161](app/data.py:161) — Portfolio summary also hardcodes `launch_thr =
   2.0` for launch classification. Same divergence risk.

**SOUND — Correctly guarded divisions:**

- Production trend (data.py:398): `.replace(0, pd.NA)` ✓
- Seasonal factor (data.py:392): `.replace(0, pd.NA)` + `.clip(0.5, 2.0)` ✓
- ROI percentage (data.py:496): `.replace(0, pd.NA)` ✓
- Elasticity (data.py:824): `.replace(0, pd.NA)` ✓
- All percentage displays match their calculation (no double-×100 bugs found)

#### Architecture & Data Contract

**CRITICAL — No startup validation:**

6. All 12 query functions assume 6 specific tables with specific columns exist.
   If the data rebuild dropped `fct_distribution` (which was created via direct
   SQL, not dbt — per DECISIONS.md), three decision modes fail: Launch Health,
   Expansion, and Pruning. No check at startup; failure happens on first user click.

   **Required table.column contract (35 columns across 6 tables):**

   | Table | Critical Columns |
   |-------|-----------------|
   | stg_scan_data | sku, store_id, week_ending (DATE), units_sold (NUMERIC) |
   | stg_stores | store_id, retailer, is_aggregated_channel (BOOL), volume_tier (A/B/C) |
   | dim_products | sku, product_name, product_line, case_pack_qty (>0) |
   | stg_sku_costs | sku, wholesale_price, cogs_per_unit |
   | stg_promotions | promo_id, sku, retailer, start_week, end_week, duration_weeks (>0), discount_depth_pct |
   | fct_distribution | sku, store_id, authorized_date (DATE), deauthorized_date (nullable DATE) |

7. `REGIONAL_CHAINS` in constants.py lists 5 chain names. If the rebuilt dataset
   uses different names, `retailer_clause("Regional")` silently returns 0 rows.
   No validation that constant values match actual DB retailer values.

8. `VOLUME_TIER_MULT` maps A/B/C to multipliers. If a store has `volume_tier = "D"`
   or NULL, expansion scoring silently uses `fillna(1.0)` — wrong but not loud.

#### Tests

**CRITICAL — 6 of 8 calculation chains have zero test coverage:**

| Decision Mode | Calculation Chain | Tested? |
|--------------|-------------------|---------|
| Shelf Defense | velocity windows → trend % → status | Classifier only (3 tests) |
| Production | weekly units → seasonal factor → forecast → trend | **NONE** |
| Promo ROI | baseline/promo/post velocity → lift → cost → ROI | **NONE** |
| Expansion | peer velocity × tier multiplier → score → tertile | **NONE** |
| Pruning | 13w velocity → p20 threshold → shelf cost → severity | **NONE** |
| Rationalization | margin → quadrant (median-based) → cut projection | Fake test (tests toy function, not real code) |
| Launch Health | window averages → retention → status | Classifier only (5 tests) |
| Pricing Power | lift → elasticity → recovery ratio → verdict | **NONE** |

The existing tests use synthetic DataFrames and mocks. **No test runs actual SQL
or validates that query results have expected columns.** A schema change in the
rebuilt data would go completely undetected by CI.

**Most dangerous untested path:** Production seasonal factor clipping. If
`sum_ly_current = 0` for many SKUs, the factor silently becomes 1.0 (no
seasonality). If many ratios exceed 2.0, the clip suppresses them. Neither case
is logged or surfaced. This directly corrupts the 4-week forecast number shown
to CEOs.

#### Performance

9. **24h cache TTL** (data.py:34) is appropriate for stable data but dangerous
   during validation. After a data rebuild, the first query seeds the cache; if
   results look wrong, clearing cache requires a deploy or manual intervention.
   **Fix:** Reduce to 3-6h during validation, or add a cache-clear endpoint.

#### UX & Display

10. AG Grid formatters use `.2f` throughout. Values near zero (0.001) display as
    "0.00" — looks like no velocity. Values > 1000 (e.g., total units) display as
    "1000.00" — too wide for columns. No adaptive formatting.

11. Shelf Defense chart shows only top 15 weakest SKUs (shelf_defense.py:207).
    If dataset grows, users don't see the full picture. No truncation indicator.

12. PDF export silently truncates at 50 rows (pitch_export.py:297). Excel shows
    all rows. No warning on the PDF that data was cut.

13. Metric cards use fixed `font-size: 1.5rem`. Large numbers overflow the card.

#### Security

14. All SQL queries use parameterized inputs — no injection risk. The one exception
    is `weeks` parameter interpolated as `int()` in time-series queries
    (data.py:235), which is safe due to the int cast but inconsistent.

#### Documentation

15. No documentation of data contract requirements (which tables, columns, types,
    value ranges must exist). README describes the dataset but not the schema
    contract the app enforces.

### Pre-Deploy Data Validation Queries

Run these against the rebuilt database before declaring the data layer safe:

```sql
-- 1. Data coverage (must span >392 days for seasonal factors)
SELECT MIN(week_ending), MAX(week_ending),
       (MAX(week_ending)::date - MIN(week_ending)::date) AS days_covered
FROM stg_scan_data;

-- 2. Critical table existence and row counts
SELECT 'stg_scan_data' AS tbl, COUNT(*) FROM stg_scan_data
UNION ALL SELECT 'stg_stores', COUNT(*) FROM stg_stores
UNION ALL SELECT 'dim_products', COUNT(*) FROM dim_products
UNION ALL SELECT 'stg_sku_costs', COUNT(*) FROM stg_sku_costs
UNION ALL SELECT 'stg_promotions', COUNT(*) FROM stg_promotions
UNION ALL SELECT 'fct_distribution', COUNT(*) FROM fct_distribution;

-- 3. Null/zero checks on critical columns
SELECT COUNT(*) FROM dim_products WHERE case_pack_qty IS NULL OR case_pack_qty = 0;
SELECT COUNT(*) FROM stg_stores WHERE volume_tier NOT IN ('A', 'B', 'C');
SELECT COUNT(*) FROM stg_scan_data WHERE units_sold IS NULL;

-- 4. Retailer name consistency
SELECT DISTINCT retailer FROM stg_stores ORDER BY retailer;
-- Must include: Walmart, Costco, Whole Foods, Green Basket Market,
-- Harbor Fresh, Prairie Provisions, Mountain Pantry Co, Southside Grocers,
-- UNFI, DTC

-- 5. fct_distribution integrity
SELECT COUNT(*), COUNT(DISTINCT sku), COUNT(*) FILTER (WHERE authorized_date IS NULL)
FROM fct_distribution;

-- 6. Price data completeness (every scanned SKU must have costs)
SELECT COUNT(*) FROM (
    SELECT DISTINCT sku FROM stg_scan_data
    EXCEPT SELECT sku FROM stg_sku_costs
) orphans;

-- 7. Promotion data range
SELECT MIN(start_week), MAX(end_week), COUNT(*),
       COUNT(*) FILTER (WHERE duration_weeks IS NULL OR duration_weeks = 0)
FROM stg_promotions;
```

### Summary

The code is structurally solid — no SQL injection, correct joins, mostly sound
formulas. But the tool is **fragile against data source changes** because:
(a) two division-by-zero bugs exist in live code paths, (b) seasonal forecasting
fails silently without 53+ weeks of history, (c) no startup validation checks
that the database contract is satisfied, and (d) 75% of calculation chains have
zero test coverage. The biggest risk isn't a crash — it's **silently wrong
numbers shown to CEOs making real decisions.**

---

## Phase 3: Landscape Scan
**Date:** 2026-05-17
**Category:** Prescriptive retail velocity analytics for emerging/scaling CPG
brands ($15M–$50M)
**Update from:** Prior scan (2026-05-15, 9 comparables)

### Competitors / Similar Projects

| # | Name | Type | Description | Traction |
|---|------|------|-------------|----------|
| 1 | Byzzer (NIQ) | Commercial | Pre-built reports for emerging CPG brands off NIQ's 60K-brand panel. Promo lift, pricing elasticity, assortment, launch tracking. New AI "Stories" for buyer decks. | Free tier + paid. NIQ backing. |
| 2 | Bedrock Analytics | Commercial | Converts syndicated data (Nielsen, SPINS, Circana) into AI-narrated buyer presentations with avatar guides. Pricing, distribution gaps, promo eval. | 350+ product categories. |
| 3 | Crisp | Commercial | Real-time retail data + AI agents for CPG. Closed $26M Series B1 (Dec 2025, $127M total). Launched AI Master Data (Feb 2026) and AI Agents (Feb 2026 GA). | Most active mover in category. |
| 4 | Alloy.ai | Commercial | Demand sensing + inventory intelligence. 850+ connectors, daily POS normalization. Stockout prevention, phantom inventory, promo performance. | $1,531–$4,463/mo, 1-year min. |
| 5 | Retail Velocity | Commercial | Enterprise POS data collection/normalization since 1994. Data infrastructure layer, not prescriptive analytics. | Now emphasizing agentic AI readiness. |
| 6 | Circana Liquid Data Go | Commercial (NEW) | Self-serve CPG analytics for small/midsize brands. Pricing simulation, elasticity, promo strategy, assortment optimization. 15% more market coverage than legacy Nielsen. | Directly targeting $15M–$50M band. |
| 7 | Circana Complete Why | Commercial (NEW) | Enterprise causal analytics: 60 sales drivers per product/market at store-week level. AI-enabled attribution. Launched March 2026. | U.S. only; EMEA late 2026. |
| 8 | Tastewise | Commercial (NEW) | Food-specific AI translating consumer demand signals (social, menus, recipes) into commercialization strategy. Leading-indicator complement, not scan-data-based. | Food industry focus. |
| 9 | Snowflake Retail Data Cloud | Platform | Data infrastructure, not analytics app. 2026 emphasis on agentic AI workflows. Crisp is certified partner. | Platform play. |
| 10 | SymphonyAI CINDE | Commercial | Enterprise AI-native CPG suite: demand forecasting, commercial analytics, supply chain. Not for emerging brands. | Enterprise tier. |
| 11–13 | OSS dashboards | OSS | grocery-dashboard, cpg-analytics-dashboard, retail-analytics on GitHub. | Abandoned/negligible activity. |

### Feature Matrix

| Feature | Cinderhaven | Byzzer | Bedrock | Crisp | Alloy | Circana LDG | Circana CW |
|---------|------------|--------|---------|-------|-------|-------------|------------|
| Portfolio health overview | ✅ | 🟡 | ❌ | ❌ | 🟡 | 🟡 | ❌ |
| Shelf defense / delisting risk | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | 🟡 |
| Production planning / forecast | ✅ | ❌ | ❌ | 🟡 | ✅ | ❌ | ❌ |
| Promo ROI analysis | ✅ | ✅ | ✅ | 🟡 | ✅ | ✅ | ✅ |
| Distribution expansion | ✅ | ❌ | 🟡 | ❌ | ❌ | 🟡 | ❌ |
| Distribution pruning | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| SKU rationalization | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | 🟡 |
| Launch health tracking | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Pricing power / elasticity | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Buyer presentation export | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| AI-generated narratives | 🟡 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Competitive benchmarking | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Data harmonization layer | ❌ | ➖ | ➖ | ✅ | ✅ | ➖ | ➖ |
| Multi-retailer data ingest | ❌ | ➖ | ✅ | ✅ | ✅ | ➖ | ➖ |
| Data quality / validation | ❌ | ❌ | ❌ | 🟡 | 🟡 | ❌ | ❌ |
| Real-time / daily data | ❌ | ❌ | ❌ | ✅ | ✅ | 🟡 | ❌ |
| AI agents / automation | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Open source / self-hosted | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Store-level drill-down | ✅ | ❌ | ❌ | 🟡 | ✅ | ❌ | ✅ |
| Causal attribution (60+ drivers) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

### Landscape Position

#### Table Stakes (standard in category)

These are features most competitors offer — any gaps here are notable:

- **Promo ROI analysis** — Cinderhaven has this. ✅
- **Pricing / elasticity** — Cinderhaven has this. ✅
- **Competitive benchmarking** — Cinderhaven does NOT have this. ❌ Every
  commercial tool offers it. This remains the most visible gap vs. the paid
  landscape.
- **Data harmonization / multi-source ingest** — Cinderhaven does NOT have this.
  ❌ Crisp and Alloy both treat this as a core product feature. Not critical
  for a portfolio piece (single synthetic dataset), but would be for a real
  deployment.

#### Where Cinderhaven Is Stronger

- **Decision breadth.** 9 prescriptive decision areas in one tool. No single
  competitor covers all 9. Byzzer covers 4, Circana LDG covers 3, Alloy covers
  2. Cinderhaven is the only tool that integrates shelf defense, distribution
  pruning, production planning, and launch health into a single interface.
- **Prescriptive framing.** Every view answers a specific CEO question ("Should I
  promote this SKU again?"), not just "here's your data." Commercial tools are
  moving toward this but most still present dashboards, not decisions.
- **Store-level granularity.** Drill-down to individual store × SKU performance.
  Most emerging-brand tools aggregate to retailer or region level.
- **Open source + deployed.** No OSS project in the scan approaches this
  sophistication. The abandoned GitHub dashboards confirm Cinderhaven is unique
  in the open-source CPG analytics space.

#### Where Cinderhaven Is Weaker

- **No competitive benchmarking.** Every commercial tool offers category-level
  comparisons. Cinderhaven only analyzes its own portfolio.
- **No data quality layer.** No validation that incoming data is complete,
  consistent, or plausible. Phase 2 of this audit confirmed this is the #1
  internal risk. No competitor does this well either — Crisp's AI Master Data
  is the closest, focused on classification rather than anomaly detection.
- **No multi-source data ingest.** Hardcoded to one Postgres schema. Real-world
  CPG companies get scan data in different formats from every retailer.
- **No AI/ML forecasting.** Production planning uses a simple seasonal factor
  (LY ratio clipped to 0.5–2.0). Alloy claims +35% forecast accuracy with ML.
- **Static narratives.** "So what" insights are template strings with data
  interpolation, not AI-generated analysis. Byzzer and Bedrock use LLMs.

#### Unique Differentiators

- **Distribution pruning** — No other tool in the scan offers a dedicated
  "which stores aren't earning their shelf space" analysis with severity
  scoring by SKU and by store.
- **Shelf defense with retailer-specific thresholds** — Explicit delisting-risk
  classification calibrated per retailer channel (Walmart 2.0, Costco 5.0,
  etc.). Other tools may surface velocity trends but don't frame them as
  shelf-loss risk.
- **Combined portfolio health → decision drill-down** — Landing page surfaces
  risk across all 9 areas, then one click goes to the relevant decision mode.
  Commercial tools silo their features into separate reports/modules.

#### Category Trends (2026)

1. **Agentic AI is the headline.** Crisp (AI Agents, Feb 2026 GA), Snowflake
   (agentic workflows), Retail Velocity (trend piece) all name autonomous
   AI agents as the defining capability shift. The framing: data harmonization
   is table stakes; autonomous reasoning on the data is the product.
2. **Data harmonization is now a product.** Crisp's AI Master Data treats SKU
   classification and cross-retailer attribute standardization as a sellable
   feature. This is the layer Cinderhaven is missing for real-world use.
3. **Causal attribution over correlation.** Circana Complete Why models 60
   sales drivers per product/market at store-week level. The bar for "why did
   velocity change?" is rising beyond simple trend comparisons.
4. **Self-serve for SMBs.** Circana Liquid Data Go and Byzzer's free tier
   signal that the $15M–$50M segment is being actively courted by incumbents.
   The competitive window for prescriptive-decision positioning is narrowing.
5. **Nobody does data validation well.** No tool in the scan explicitly
   validates scan data integrity before running analytics. This is a
   differentiation opportunity — and directly relevant to the current audit.

### Summary

Cinderhaven remains unique in combining 9 prescriptive decision areas, store-
level granularity, and open-source deployment. No OSS project approaches it,
and no single commercial tool covers the same breadth. The competitive gap has
narrowed since the prior scan: Circana Liquid Data Go now directly targets the
same audience, and Crisp's AI agents represent a paradigm shift. The biggest
strategic gap is competitive benchmarking (table stakes in the category). The
biggest technical gap — and a potential differentiator — is data quality
validation, which no competitor does well and which this audit's Phase 2
confirmed is the tool's #1 internal risk.

---

## Phase 4: Differentiation & Next Moves
**Date:** 2026-05-17

### Cross-Reference Summary

The internal review (Phase 2) and landscape scan (Phase 3) converge on one
finding: **data integrity is simultaneously the tool's biggest internal risk
and an unoccupied competitive position.** No competitor validates scan data
before running analytics. Cinderhaven doesn't either — but fixing that internal
weakness would create an external differentiator. This is rare: most fixes are
pure hygiene. This one is both hygiene and strategy.

The second convergence is around **threshold calibration and the data rebuild.**
Phase 2 found that retailer thresholds, time windows, and classifier boundaries
are all data-dependent — and none are validated against the actual data at
startup. Phase 3 confirmed that Cinderhaven's unique strength (9 prescriptive
decision areas with store-level granularity) depends entirely on those
calculations being correct. If the rebuilt data produces silently wrong numbers,
the tool's entire value proposition is compromised. The division-by-zero bugs,
untested calculation chains, and missing schema validation aren't just code
quality issues — they're threats to the portfolio piece's credibility.

The third pattern is a strategic sequencing constraint. The tempting moves
(competitive benchmarking, AI narratives, data harmonization) all require a
trustworthy data layer first. Competitive benchmarking needs synthetic
competitor data that interacts with the same calculations. AI narratives need
correct numbers to narrate. Multi-source ingest needs schema validation to catch
format mismatches. **Everything strategic depends on the foundation being solid.**

### Ranked Next Moves

| # | Move | Category | Strategic | Internal | Effort | Score | Description |
|---|------|----------|-----------|----------|--------|-------|-------------|
| 1 | Data contract validation at startup | Foundational | 3 | 5 | 2 | 4.0 | Run the 7 SQL checks from Phase 2 on app boot. Fail loudly if tables/columns/ranges are wrong. Prevents every silent-failure scenario. |
| 2 | Fix division-by-zero bugs (2 locations) | Foundational | 1 | 5 | 1 | 6.0 | Add `baseline_v > 0` guard in promo ROI (data.py:486) and `.replace(0, pd.NA)` in shelf defense trend (shelf_defense.py:47). Trivial fix, prevents wrong numbers. |
| 3 | Threshold recalibration against new data | Double down | 4 | 5 | 2 | 4.5 | Query the rebuilt dataset for velocity distributions per retailer. Verify that current thresholds (2.0/5.0/1.5/1.0) still produce sensible At Risk / Safe splits. Adjust if needed. |
| 4 | Calculation chain test coverage | Foundational | 2 | 5 | 3 | 2.3 | Add tests for the 6 untested chains: production forecast, promo ROI, pricing elasticity, expansion scoring, pruning severity, rationalization quadrants. Focus on edge cases (zero, NaN, boundary values). |
| 5 | Seasonal factor validation | Double down | 3 | 5 | 1 | 8.0 | Check if rebuilt data spans 392+ days. If not, log a warning and document that seasonal forecasts are inactive. Prevents the worst silent-failure scenario (wrong production forecasts shown to CEOs). |
| 6 | Consolidate hardcoded threshold=2.0 | Foundational | 1 | 4 | 1 | 5.0 | Replace the 3 hardcoded `2.0` values (launch_health.py:83, pitch_export.py:61, data.py:161) with reads from constants. One source of truth. |
| 7 | Data quality dashboard (new decision area) | Leapfrog | 5 | 4 | 4 | 2.3 | Add a 10th decision mode: "Is my data trustworthy?" Surface coverage gaps, stale weeks, missing SKU costs, retailer-name mismatches. No competitor does this. Turns the audit's #1 risk into a feature. |
| 8 | Competitive benchmarking (synthetic) | Close gap | 5 | 2 | 5 | 1.4 | Add synthetic competitor data and a category-comparison view. Closes the biggest feature gap vs. every commercial tool. Requires new data generation — highest effort. |
| 9 | AI-generated narrative insights | Close gap | 4 | 2 | 3 | 2.0 | Replace template "so what" strings with LLM-generated analysis using the Claude API. Matches Byzzer/Bedrock. Depends on correct numbers (Moves 1–6 first). |
| 10 | Adaptive number formatting | Double down | 2 | 3 | 2 | 2.5 | Replace fixed `.2f` formatters with magnitude-aware formatting (0.001→"<0.01", 1234→"1,234"). Prevents false zeros and column overflow. |
| 11 | Cache TTL reduction for validation period | Foundational | 1 | 3 | 1 | 4.0 | Reduce from 24h to 6h during data validation. Add a manual cache-clear endpoint. Trivial config change. |
| 12 | PDF export truncation warning | Double down | 2 | 2 | 1 | 4.0 | Add "Showing 50 of N rows" footer to PDF when truncated. Small fix, prevents confusion in buyer meetings. |

### Recommended Sequence

**Batch 1 — Immediate (before redeploying with new data):**
Moves 2, 5, 6, 11 — all effort=1, no dependencies. Fix the division-by-zero
bugs, validate seasonal data coverage, consolidate hardcoded thresholds, reduce
cache TTL. These are one-line or few-line changes that prevent the worst silent
failures. Do all four before touching anything else.

**Batch 2 — This week (data trust foundation):**
Moves 1, 3 — startup data contract validation and threshold recalibration.
Run the 7 SQL checks against the rebuilt database. Verify that shelf defense
thresholds still produce a sensible distribution of At Risk / Warning / Safe.
Adjust thresholds if distributions shifted. This is the audit's core purpose.

**Batch 3 — Next sprint (test harness):**
Move 4 — calculation chain tests. Write tests for the 6 untested decision
modes. Focus on the production forecast chain (seasonal factor clipping,
case_pack_qty division) and promo ROI chain (baseline=0, cost=0 edge cases).
These tests protect against future data source changes.

**Batch 4 — Strategic (feature work, after foundation is solid):**
Moves 7, 10, 12 — data quality dashboard, adaptive formatting, PDF truncation
warning. Move 7 is the highest-leverage strategic move: it turns the audit's
#1 finding into a visible differentiator that no competitor offers.

**Batch 5 — Horizon (requires new data or dependencies):**
Moves 8, 9 — competitive benchmarking and AI narratives. Both require
substantial new work (synthetic competitor data, Claude API integration) and
should only start after the data foundation is trustworthy.

### What NOT to Do

1. **Don't build competitive benchmarking now.** It's the most visible gap, but
   it requires new synthetic data, new SQL, and new UI — the highest-effort move
   on the board. And it depends on the calculation layer being correct. Fix the
   foundation first; benchmarking is a Batch 5 project.

2. **Don't chase AI agents.** Crisp raised $127M to build this. The category
   trend is real but the investment required is disproportionate for a portfolio
   piece. The prescriptive-decision framing already does most of what "agents"
   promise — it tells you what to do — without the infrastructure cost.

3. **Don't add multi-retailer data ingest.** This is table stakes for a
   production SaaS product but irrelevant for a portfolio piece running on
   synthetic data. The effort is enormous (schema mapping, format detection,
   error handling) and the payoff is zero for the current use case.

4. **Don't add real-time / daily data.** Weekly cadence matches how specialty
   food CEOs actually review velocity reports. Daily data is a Crisp/Alloy
   feature for supply-chain operators, not a CEO decision tool. Building this
   would chase a competitor's strength with no audience benefit.

5. **Don't refactor the cache architecture.** The 24h TTL with persistent
   volume is fine for production. The only change needed is a temporary TTL
   reduction during the validation period (Move 11) and eventually a manual
   flush endpoint. A full cache redesign is unnecessary complexity.
