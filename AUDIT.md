# Project Audit — Cinderhaven Velocity Decision Tool

Completed: 2026-05-16 (second full audit)

---

## Phase 1: Baseline

Dash app deployed on Fly.io at retail-velocity-decision-tool.fly.dev. Backed by
Postgres (also on Fly.io). Modular codebase: **6,520 lines** across 16 Python
modules in `app/`, plus 402 lines of tests across 6 test files (26 tests).

**9 decision views:** Portfolio Health (default landing) + 8 decision modes
(Shelf Defense, Production Planning, Promo ROI, Distribution Expansion,
Distribution Pruning, SKU Rationalization, Launch Health, Pricing Power).

**Architecture:** Dash + Bootstrap + AG Grid | Postgres via psycopg2 PID-aware
ThreadedConnectionPool (maxconn=10) | flask-caching FileSystemCache on
persistent Fly volume (24h TTL) | Gunicorn 1 worker / 4 gthread threads /
120s timeout | shared-cpu-1x 1GB RAM, always-on.

**Recent completions (since last audit 2026-05-15):**
- Story mode removed, replaced with portfolio health dashboard
- Narrative "so what" insights on all 8 decision modes
- Trend charts on 3 modes (Shelf Defense, Production, Launch)
- Retailer pitch export (Excel + PDF)
- Inline styles partially extracted to CSS classes

---

## Phase 2: Internal Review (ranked by leverage)

### Prior audit findings — all resolved

1. ~~Connection management leak risk~~ — **Fixed** (context manager)
2. ~~README stale~~ — **Fixed** (Streamlit → Dash)
3. ~~No health check~~ — **Fixed** (/health endpoint + fly.toml check)
4. ~~No tests~~ — **Fixed** (26 tests, 6 modules)
5. ~~No CI~~ — **Fixed** (ruff + pytest on push/PR)
6. ~~License removed~~ — **Fixed** (MIT restored)
7. ~~`_return_conn` swallowed errors~~ — **Fixed** (eliminated)
8. ~~fly.toml redundant memory fields~~ — **Fixed**

### New findings

1. **Portfolio health cold-load performance (HIGH).** `get_portfolio_summary()`
   triggers 7+ cached queries on first load (one per retailer for shelf risk,
   plus production, rationalization, launch). With 24h cache TTL, the first
   visitor of the day waits 10-15s. This is the landing page — the first
   impression for every prospect.

2. **Expansion module bypasses data layer (MEDIUM-HIGH).** `expansion.py`
   imports `from db import get_conn` directly for `_get_sku_meta()`. Every
   other module routes through `data.py` with caching. Breaks the architecture
   contract and hits Postgres uncached on every render.

3. **Test coverage: only classifiers tested (MEDIUM-HIGH).** 26 tests cover
   classifiers, constants, portfolio shape, and health endpoint. Zero coverage
   on: 10 data functions (not even shape assertions), dispatch callback logic,
   pitch export (Excel/PDF generation), edge cases (empty retailer, None
   handling). The untested surface is where bugs live (as FAILURES.md proves).

4. **Inline styles still prevalent (MEDIUM).** 92 `style={...}` occurrences
   across 12 files despite the CSS extraction pass. Key offenders:
   rationalization.py (20), layout.py (20), pruning.py (11).

5. **`dangerously_allow_html` in 3 files (LOW-MEDIUM).** Status legends use
   `dcc.Markdown(text, dangerously_allow_html=True)`. No actual XSS vector
   (all content is server-side constants), but the flag is a red flag for
   security auditors reviewing the repo.

6. **Cache warming races with requests (LOW-MEDIUM).** Background thread
   runs ~60 queries competing for the same connection pool. Mitigated by
   `warm_default_view()` but mode-switching during warming can be slow.

7. **No dependency version pins (LOW-MEDIUM).** Floor pins only
   (`dash>=3.0`), no lock file. Docker builds are non-reproducible. Already
   caused a Plotly type error requiring a workaround in `charts.py`.

8. **No error monitoring (LOW-MEDIUM).** Only stdout logging from
   warm_cache. No Sentry, no structured logging, no alerting. Invisible
   failures for a prospect-facing demo.

9. **No mobile/responsive handling (LOW).** Side-by-side layout uses
   `display: flex` without breakpoints. AG Grid with fixed columns won't
   reflow. Broken on phone screens — table stakes gap vs. every competitor.

10. **Dockerfile lacks HEALTHCHECK (LOW).** Fly handles it via fly.toml, but
    no portability to other platforms.

---

## Phase 3: Landscape Scan

**14 comparables evaluated** (7 commercial SaaS, 2 pitch tools, 5 OSS/misc).

### Commercial SaaS

| Tool | Target | Prescriptive? | Price |
|------|--------|---------------|-------|
| Byzzer (NielsenIQ) | Emerging CPG ($1-50M) | Alerts, not actions | Mid-4-figures/yr |
| Bedrock Analytics | $5M-$60B+ CPG | Hybrid (AI decks) | Custom |
| Crisp | Regional-to-mid CPG | Yes (AI agents) | ~$1,500/mo+ |
| Alloy.ai | Mid-market+ CPG | Yes (order recs) | Enterprise |
| SPINS (Ignite/Liftoff) | Full spectrum | Hybrid + consulting | Free → custom |
| Stackline | Large brands (7K+) | Mostly descriptive | $5K/mo+ |
| Daasity | DTC/omnichannel | Descriptive | Demo-based |

### Positioning

**Cinderhaven is unique in:**
- Only open-source prescriptive decision tool in this space (no OSS competitor)
- Broadest decision coverage (9 modes) at the emerging-brand price point
- Distribution pruning and launch health tracking have no direct equivalent
- Combines velocity + shelf defense + promo ROI + production planning in one view

**Gaps vs. landscape:**
1. **Competitive benchmarking** — every paid tool offers category context
2. **Mobile responsiveness** — every SaaS competitor works on phones
3. **Real-time data connectivity** — commercial tools ingest live retailer data
4. **ML-based forecasting** — Crisp and Alloy.ai use multi-variable models
5. **Alerting/notifications** — Byzzer sends weekly alerts; Cinderhaven is pull-only

**Market signal:** Sharp pricing cliff between free (SPINS Ignite) and
$1,500+/month (Crisp, Byzzer, Bedrock). Specialty food CEOs at $15-25M can't
justify $18-60K/year for analytics SaaS. Cinderhaven occupies this gap as a
proof of decision framework.

---

## Phase 4: Ranked Next Moves

| # | Move | Status | Effort | Description |
|---|------|--------|--------|-------------|
| 1 | Production fixes (v1) | **Done** | — | README, connection refactor, health check, license, fly.toml |
| 2 | Basic CI + tests | **Done** | — | pytest (26 tests) + ruff + GitHub Actions CI |
| 3 | Portfolio health dashboard | **Done** | — | Landing page, risk cards, drill-down, narrative insights, trend charts |
| 4 | Retailer pitch export | **Done** | — | Multi-sheet Excel + branded PDF export |
| 5 | **Production hardening (v2)** | **Next** | Small | Pin deps, fix expansion data-layer bypass, replace dangerously_allow_html, add error monitoring |
| 6 | **Cold-load performance** | Planned | Small | Add `get_portfolio_summary()` to `warm_default_view()` so landing page is pre-cached at boot |
| 7 | **Mobile responsiveness** | Planned | Medium | CSS breakpoints, stacked layout on narrow screens, collapsible sidebar |
| 8 | **Competitive benchmarking** | Planned | Large | New synthetic category data, benchmark reference lines in Shelf Defense + Production, possible new mode |
| 9 | **Test coverage expansion** | Planned | Medium | Data function shape tests, callback dispatch tests, pitch export tests |

### Move 5 detail: Production Hardening v2

- Pin all deps with version ceilings (`dash>=3.0,<4.0`, etc.)
- Move `_get_sku_meta()` from expansion.py to data.py with `@cache.memoize`
- Replace `dangerously_allow_html` with Dash `html.Span` components (3 files)
- Add Sentry free tier or Fly log drain for error visibility

### Move 6 detail: Cold-Load Performance

- Add `get_portfolio_summary()` to `warm_default_view()` (synchronous, before
  traffic). First visitor gets cached landing page immediately.
- Long-term: materialize portfolio metrics as a DB view (one query vs. seven).

### Move 7 detail: Mobile Responsiveness

- `@media (max-width: 768px)` breakpoints in style.css
- Stack `.dash-body` vertically (chart below grid)
- Collapse sidebar into top bar or hamburger on mobile
- AG Grid `domLayout: "autoHeight"` on narrow screens

### Move 8 detail: Competitive Benchmarking

- New synthetic data: category-level velocity averages by retailer × week
- `dim_categories` table or extend `dim_products` with category membership
- New data function: `get_category_benchmark(retailer, category)`
- Benchmark reference lines on Shelf Defense and Production charts
- Transforms tool from "here's your data" to "here's your data in context"

---

## What NOT to do

- **Alerting/notifications** — pull-only is fine for a portfolio demo
- **ML forecasting** — seasonal-factor approach is honest for synthetic data
- **Real data connectivity** — productization decision, not portfolio decision
- **Cache warming redesign** — current pattern works, not worth the refactor
