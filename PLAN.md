# Plan — Cinderhaven Velocity Decision Tool

## Current Goal (2026-05-16)

Harden the live demo and close universal gaps vs. competitors, then build
the highest-leverage feature (competitive benchmarking).

**Audience:** Cold-landing CEO of a $20-25M food company checking the link
from their phone or laptop after receiving a pitch email. Zero onboarding
tolerance. Needs to see portfolio health in <30 seconds.

**Strategic position:** Only open-source prescriptive decision tool in the
retail/CPG analytics space. Broadest decision coverage at any price point.
Main vulnerabilities: no mobile support, no category benchmarking, cold-load
latency on first daily visit.

---

## Completed Work

### Portfolio Health Dashboard (2026-05-15) ✓

- [x] A1: Remove Story mode
- [x] A2: Portfolio health data layer (`get_portfolio_summary()`)
- [x] A3: Portfolio health landing page (KPIs, risk cards, status bar)
- [x] A4: Drill-down navigation (risk cards → decision modes)
- [x] B1: Narrative "so what" insights on all 8 decision modes
- [x] B2: Time-series trend charts (Shelf Defense, Production, Launch)
- [x] C: End-to-end polish

### Infrastructure (2026-05-13–15) ✓

- [x] Connection management refactor (context manager)
- [x] Health check endpoint + fly.toml check config
- [x] CI pipeline (ruff lint + pytest, 26 tests)
- [x] Retailer pitch export (Excel + PDF)
- [x] README updated, LICENSE restored
- [x] Persistent cache volume, single-worker config

---

## Next Moves (from Audit Phase 4)

### Move 5: Production Hardening v2 — DONE ✓

- [x] Pin all dependency versions with ceilings in `app/requirements.txt`
- [x] Move `_get_sku_meta()` from `decisions/expansion.py` to `data.py` with
      `@cache.memoize` — fixes architecture bypass + adds caching
- [x] Replace `dangerously_allow_html` in all files with Dash `html.Span`/
      `html.B` components (8 callers + 5 direct usages across 7 files)
- [x] Add Sentry SDK integration (opt-in via SENTRY_DSN env var)
- [x] Fix pre-existing bug: undefined `n_total` in rationalization.py

### Move 6: Cold-Load Performance — DONE ✓

- [x] Add `get_portfolio_summary()` to `warm_default_view()` in `data.py`
      so the landing page is pre-cached before the app serves traffic
- [x] Verify first-visitor load time is <3 seconds with warm cache — HTML 0.4s, full render ~3s

### Move 7: Mobile Responsiveness — DONE ✓

- [x] Add `@media (max-width: 767.98px)` breakpoints to `assets/style.css`
- [x] Stack `.dash-body` vertically on narrow screens (chart below grid)
- [x] Collapse sidebar into toggle button on mobile widths
      (dbc.Collapse + clientside callback)
- [x] AG Grid height auto on narrow screens via CSS override
- [x] Bootstrap responsive columns: `xs=12, md=3` / `xs=12, md=9`
- [x] Metric cards + risk cards wrap into 2×2 grid on mobile
- [x] Verify on iPhone SE / Pixel viewport sizes — CSS breakpoint at 767.98px covers both (375px, 393px)

### Move 8: Competitive Benchmarking — DONE ✓

Large effort, very high impact. Transforms the tool from "here's your data"
to "here's your data in context" — the #1 thing every paid tool charges for.

- [x] Design category field in `dim_products` (product_line → market category)
- [x] Generate synthetic category-level velocity averages (by retailer × week)
      `stg_category_benchmarks` table: 2,492 rows across 3 categories × 8 retailers
- [x] New data function: `get_category_benchmark(retailer, product_line)`
      Plus `get_category_benchmark_weekly(retailer, category, weeks)` for trends
- [x] Add benchmark reference lines to Shelf Defense chart ("category avg")
      Blue dotted vline on bar chart, hline on trend chart, metric card, insight text
- [x] Add benchmark comparison to Production Planning (metric card)
- [x] Add benchmark KPI card to Portfolio Health landing page
- [ ] Consider standalone "How do I compare?" decision mode (deferred — Move 10)

Done when: At-risk SKUs in Shelf Defense show whether they're below the
category average too (not just below the retailer threshold). A prospect
sees how Cinderhaven performs relative to its competitive set. ✓ DONE

### Move 9: Test Coverage Expansion — DONE ✓

Medium effort. Strengthens "production-quality code" signal for technical
evaluators.

- [x] Data function shape tests (mock DB, assert column names + types)
- [x] Callback dispatch tests (verify mode routing logic)
- [x] Pitch export edge case tests (empty DataFrames)
- [x] Edge case tests (empty retailer, NaN values, zero-row data)
- [x] Chart helper tests (layout structure, hbar padding, annotations)
- [x] Category benchmark graceful degradation tests

Done when: Test count is 50+ with coverage on the surfaces where bugs
historically appeared (data functions, callbacks, edge cases). ✓ 80 tests

---

### Move 10: Data Integrity & Calculation Correctness — DONE ✓

`/improve` pass focused on reconciliation with Postgres and calculation/assumption correctness.
3-agent deep audit (data integrity, calculation correctness, assumption audit).

- [x] Fix forecast rounding (premature .round(2) on cases)
- [x] Promo baseline guard — return excluded count, show in UI
- [x] Pricing elasticity guard — use min_discount threshold
- [x] Seasonal factor — read clip bounds from THRESHOLDS dict
- [x] Production trend status — detect zero/NaN prior → Accelerating
- [x] Promo exclusion transparency in UI
- [x] Pricing "Insufficient data" verdict for NaN elasticity
- [x] Shelf defense current_v null detection before fillna
- [x] Regional benchmark fallback with logging
- [x] Rationalization wholesale_price null guard
- [x] Launch classifier dead branch cleanup
- [x] Scan data grain validation check (new)
- [x] Cost completeness validation check (new)
- [x] Portfolio health label clarity
- [x] Missing threshold constants added to THRESHOLDS dict
- [x] Expansion "All equivalent" tier
- [x] Unused import cleanup

Done when: All 17 findings fixed, 163 tests passing, no new lint issues. ✓

### Move 11: Mart Layer Migration — DONE ✓

Migrate all SQL reads from staging tables to dbt mart equivalents. Prevent
reload_postgres.py from overwriting canonical platform tables.

- [x] Disable reload_postgres.py with hard guard
- [x] Add margin_per_unit, margin_pct to dim_products mart (dbt model + schema)
- [x] Repoint stg_stores → dim_stores (chain_name → retailer)
- [x] Repoint stg_scan_data → fct_scan_data
- [x] Repoint stg_promotions → fct_promotions (retailer_id → retailer)
- [x] Remove stg_sku_costs JOINs — read costs from dim_products
- [x] Delete Python margin re-derivation — read mart margin_per_unit
- [x] Update validation.py, seed_benchmarks.py, test files
- [x] Reorder search_path: public_marts first
- [x] Verify: 929 SQL comparisons, zero drifts at 1e-10

Done when: No stg_* reads for shared data, margin from mart, verified parity. ✓

---

## Improvement History

### 2026-05-22 — Improvement pass
- **Trigger:** User-initiated `/improve` focused on data reconciliation and calculation correctness
- **What was reviewed:** Calculation chains (production, promo ROI, pricing, expansion), data contract validation, assumption hardcoding, UI transparency
- **What was fixed:** 17 findings — 5 critical, 8 important, 4 nice-to-have (see Move 10)
- **Deferred:** None — all findings addressed
- **Next review:** 2026-06-22

---

## Out of Scope

- ML-based forecasting (seasonal factor is honest for synthetic data)
- Alerting/notifications (pull-only is fine for portfolio demo)
- Real data connectivity (productization decision, not portfolio decision)
- New decision modes (9 is comprehensive enough)
- Cache warming redesign (current pattern works)
