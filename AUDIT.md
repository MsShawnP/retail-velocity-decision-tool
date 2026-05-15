# Project Audit — Cinderhaven Velocity Decision Tool

Completed: 2026-05-15

## Phase 1: Baseline

Dash app deployed on Fly.io at retail-velocity-decision-tool.fly.dev. Backed by
Postgres (also on Fly.io). Modular codebase: ~7,600 lines across 15 modules.
8 decision modes + narrative Story mode, all feature-complete.

**Architecture:** Dash + Bootstrap + AG Grid | Postgres via psycopg2 pool
(maxconn=10) | flask-caching FileSystemCache on persistent Fly volume | Gunicorn
1 worker / 4 gthread threads / 120s timeout | shared-cpu-1x 1GB RAM, always-on.

## Phase 2: Internal Review (ranked by leverage)

1. **Connection management — leak risk (HIGH).** All 28 DB calls used
   `get_raw_conn()` + manual `try/finally` instead of the `get_conn()` context
   manager. Pool exhaustion risk on missed returns. **Fixed in Move 1.**
2. **README stale (HIGH).** Still referenced Streamlit in "Built with" and
   "Running locally" despite Dash migration. **Fixed in Move 1.**
3. **No health check endpoint (MEDIUM).** Fly machine occasionally stops;
   no liveness signal for restart. **Fixed in Move 1.**
4. **No tests (MEDIUM).** Zero test files, no pytest in requirements.
5. **No CI (MEDIUM).** No GitHub Actions, linting, or type checking.
6. **Inline styles everywhere (LOW-MEDIUM).** CSS classes exist in
   `assets/style.css` but most code sets styles inline.
7. **License removed (LOW).** MIT LICENSE deleted in Dash migration.
   **Restored in Move 1.**
8. **`_return_conn` swallowed errors (LOW).** Bare `except: pass` on pool
   return. **Eliminated in Move 1 (context manager handles cleanup).**
9. **`fly.toml` redundant memory fields (LOW).** Both `memory` and
   `memory_mb` set. **Fixed in Move 1.**

## Phase 3: Landscape Scan

**9 comparables evaluated** (4 OSS dashboards, 1 narrative portfolio, 4
commercial SaaS). Cinderhaven is unique in combining decision-mode UI,
integrated narrative storytelling, and a deployed open-source portfolio piece.
No OSS project in the scan approaches this sophistication.

**Key gaps vs. landscape:**
- Retailer pitch export (Byzzer + Bedrock both lead with this)
- Competitive benchmarking (every commercial tool offers it)
- Time-series trend views in decision modes (7/9 comparables)
- Forecasting in Production Planning (natural fit, partially exists in Story)

## Phase 4: Ranked Next Moves

| Move | Status | Description |
|------|--------|-------------|
| 1. Production fixes | **Done** | README, connection refactor, health check, license, fly.toml |
| 2. Basic CI + tests | Planned | pytest + ruff + GitHub Actions |
| 3. Retailer pitch export | Future | Export analysis as buyer deck |
