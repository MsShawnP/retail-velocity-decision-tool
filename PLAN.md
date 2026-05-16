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
- [ ] Verify first-visitor load time is <3 seconds with warm cache (requires deploy)

### Move 7: Mobile Responsiveness

Medium effort. Closes the one gap shared with every competitor.

- [ ] Add `@media (max-width: 768px)` breakpoints to `assets/style.css`
- [ ] Stack `.dash-body` vertically on narrow screens (chart below grid)
- [ ] Collapse sidebar into a top bar or hamburger on mobile widths
- [ ] Set AG Grid `domLayout: "autoHeight"` on narrow screens
- [ ] Test on iPhone SE / Pixel viewport sizes

Done when: The tool is readable and navigable on a phone — not a full
responsive redesign, just "not broken."

### Move 8: Competitive Benchmarking

Large effort, very high impact. Transforms the tool from "here's your data"
to "here's your data in context" — the #1 thing every paid tool charges for.

- [ ] Design `dim_categories` or category field in `dim_products`
- [ ] Generate synthetic category-level velocity averages (by retailer × week)
- [ ] New data function: `get_category_benchmark(retailer, category)`
- [ ] Add benchmark reference lines to Shelf Defense chart ("category avg")
- [ ] Add benchmark comparison to Production Planning
- [ ] Consider standalone "How do I compare?" decision mode

Done when: At-risk SKUs in Shelf Defense show whether they're below the
category average too (not just below the retailer threshold). A prospect
sees how Cinderhaven performs relative to its competitive set.

### Move 9: Test Coverage Expansion

Medium effort. Strengthens "production-quality code" signal for technical
evaluators.

- [ ] Data function shape tests (mock DB, assert column names + types)
- [ ] Callback dispatch tests (verify mode routing logic)
- [ ] Pitch export tests (Excel + PDF generate without error)
- [ ] Edge case tests (empty retailer, None product_line, zero-row data)

Done when: Test count is 50+ with coverage on the surfaces where bugs
historically appeared (data functions, callbacks, edge cases).

---

## Out of Scope

- ML-based forecasting (seasonal factor is honest for synthetic data)
- Alerting/notifications (pull-only is fine for portfolio demo)
- Real data connectivity (productization decision, not portfolio decision)
- New decision modes (9 is comprehensive enough)
- Cache warming redesign (current pattern works)
