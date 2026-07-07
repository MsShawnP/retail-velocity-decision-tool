# Decisions

## 2026-05-13: Persistent Fly volume for cache instead of /tmp

**Decision:** Mount a 1GB Fly volume at `/cache` and point FileSystemCache there instead of `/tmp/dash-cache`.

**Why:** `/tmp` is wiped on every deploy and machine restart. With `auto_stop_machines` (now off) or any redeploy, the cache was lost and all ~60 queries had to re-run against Postgres. Weekly scan data doesn't change fast enough to justify re-querying on every boot.

**Tradeoff:** Volume costs ~$0.15/GB/month (negligible). Volume is pinned to one machine in one region — fine for a single-machine portfolio tool, would need rethinking for multi-region.

## 2026-05-13: Single gunicorn worker with 4 threads

**Decision:** Changed from 2 workers × 2 threads to 1 worker × 4 threads.

**Why:** Each worker independently ran `warm_cache()`, doubling the DB load (~120 concurrent queries). With FileSystemCache shared on disk, only one worker's warming is needed. Single worker eliminates the duplication while 4 threads maintain concurrency.

**Tradeoff:** No process-level isolation — a segfault kills the only worker. Acceptable for a portfolio tool.

## 2026-05-13: Machine always-on (auto_stop_machines = off)

**Decision:** Set `auto_stop_machines = 'off'` and `min_machines_running = 1` in fly.toml.

**Why:** With auto-stop, every idle timeout killed the machine, wiped `/tmp`, and forced a full cold-cache rebuild on the next visit. Even with the persistent volume, machine stop/start adds latency. Always-on keeps the process warm.

**Tradeoff:** ~$3-5/month for a shared-cpu-1x 1GB machine running continuously.

## 2026-05-14: Connection pool maxconn=10

**Decision:** Increased `ThreadedConnectionPool` maxconn from 4 to 10 in `app/db.py`.

**Why:** 4 gunicorn threads + 1 warm_cache background thread = 5 potential concurrent consumers. maxconn=4 caused "connection pool exhausted" errors on tab switching when warm_cache was running simultaneously.

**Tradeoff:** 10 connections to Fly Postgres is well within limits. Slight memory overhead per idle connection (~5MB each), negligible on the 1GB machine.

## 2026-05-14: Create fct_distribution directly on production DB

**Decision:** Created the `fct_distribution` table via direct SQL on the Fly Postgres instance rather than running dbt.

**Why:** The dbt model existed (Cinderhaven Data Platform `models/marts/fct_distribution.sql`) but was never materialized. The dbt profile points at localhost, not the remote Fly Postgres. Running `CREATE TABLE fct_distribution AS SELECT ...` directly was the fastest path to unblocking pruning, expansion, and Story mode — all of which depend on this table.

**Tradeoff:** Table won't auto-refresh when dbt runs. Acceptable for now — distribution data changes infrequently. Will need a proper dbt materialization path when the data platform CI pipeline runs against production.

## 2026-05-13: Side-by-side layout (grid left, chart right)

**Decision:** Restructured all 8 decision modes from vertical stacking to a viewport-fitting flex layout with data grid on the left and chart/narrative on the right.

**Why:** User feedback — charts and insights were below the fold, requiring scrolling. The tool's value is the insight paired with the data; both need to be visible simultaneously.

**Tradeoff:** Less vertical space for each panel. AG Grid now uses internal scrollbars (`domLayout: "normal"`) instead of expanding to show all rows.

## 2026-05-15: Replace Story mode with portfolio health dashboard

**Decision:** Deleted the 5-section Story mode entirely and replaced it with a portfolio health landing page that aggregates risk indicators across all decision areas. Decision modes became the narrative building blocks — each got a "so what" insight and (where applicable) trend charts.

**Why:** The Story mode was a guided walkthrough of one protagonist SKU. A cold-landing CEO doesn't want a tour — they want to see their portfolio's health instantly and drill into what matters. The decision modes already had the data; they just needed narrative framing.

**Tradeoff:** Lost the linear storytelling arc. Gained a tool that hooks within 30 seconds by surfacing what's interesting (at-risk clusters, production spikes, launch failures) and letting the user pull rather than push.

## 2026-05-17: Threshold recalibration — data-driven from live velocity distributions

**Decision:** Queried the rebuilt Cinderhaven dataset for velocity percentiles (p5–p90) per retailer and recalibrated all thresholds to produce ~10-20% at-risk classifications.

**Values changed:**
- Walmart: 2.0 → 5.0 (was p10 of distribution; 0% were at risk before)
- Costco: 5.0 → 27.0 (velocities ranged 24–68; old threshold was meaningless)
- Whole Foods: 1.5 → 2.5 (only 2.8% at risk before)
- Regional: 1.0 → 2.0 (proportional)
- Launch benchmark: 2.0 → 4.0
- Production trend: ±10% → ±15% (48% were "Accelerating" at ±10%)

**Why:** The dataset rebuild changed velocity distributions entirely. Original thresholds were calibrated for a different dataset and produced zero at-risk classifications for 2 of 4 retailers.

**Tradeoff:** These thresholds are tuned to the synthetic Cinderhaven data. A real client deployment would need its own calibration pass.

## 2026-05-17: fillna(0) instead of dropna for zero-velocity SKUs

**Decision:** Changed shelf defense, pruning, and rationalization queries from `dropna(subset=["current_v"])` to `df["current_v"] = df["current_v"].fillna(0)`.

**Why:** `dropna` silently removed SKUs with zero scan velocity. These are exactly the SKUs that should show as "At Risk" — dropping them hid the most important signal. `fillna(0)` keeps them visible and classified correctly.

**Tradeoff:** None meaningful. Zero velocity is a real data point, not missing data.

## 2026-05-17: Scale Fly Postgres from 256MB to 1GB

**Decision:** Scaled the Fly Postgres machine from shared-cpu-1x 256MB to 1GB.

**Why:** The calibration query (correlated subqueries on stg_scan_data) OOM'd the 256MB instance. Needed headroom for analytical queries against 4000+ row scan data.

**Tradeoff:** Cost increase ~$9/mo. Can downscale once one-time analytical queries are done.

## 2026-05-15: Trend charts use base_chart_layout with yaxis autorange override

**Decision:** Reused the existing `base_chart_layout()` helper for all 3 new trend charts but overrode `yaxis.autorange = True` in each.

**Why:** `base_chart_layout` defaults to `autorange="reversed"` because it was designed for horizontal bar charts (labels top-to-bottom). Time-series charts need standard ascending y-axis. Overriding one property is simpler than creating a second layout helper.

**Tradeoff:** Each trend chart needs a 1-line override. Acceptable until there are enough time-series charts to justify a `time_series_layout()` helper.

## 2026-05-16: Mobile sidebar starts collapsed

**Decision:** Changed `dbc.Collapse(is_open=False)` for the sidebar on mobile, with a CSS override forcing it always-visible on desktop (`min-width: 768px`).

**Why:** User tested on mobile and said "idk what the sidebar is" — the full filter panel rendered above the dashboard content, pushing the actual data below the fold. Starting collapsed lets users see the dashboard immediately; the "☰ Show Filters & Navigation" button is clear enough to find when needed.

**Tradeoff:** One extra tap to access filters on mobile. Worth it — the dashboard content is what hooks a prospect, not the filter dropdowns.

## 2026-05-16: Explicit y-axis range on trend charts instead of autorange

**Decision:** Replaced `yaxis.autorange = True` with computed explicit ranges that include data traces AND reference lines (threshold, category avg).

**Why:** Plotly's autorange only considers scatter trace data, not `add_hline` shapes. With data at ~2.5–3.0, autorange set the y-axis to ~2.3–3.2, cutting off the threshold (2.00) and category avg (7.19) reference lines entirely.

**Tradeoff:** Slightly more code per trend chart (5 lines to compute range). The alternative — adding invisible traces at reference values to influence autorange — felt hackier.

## 2026-05-22: Accept mobile breakpoint divergence from design system (#13)

**Decision:** Keep the CSS mobile breakpoint at 768px instead of the Lailara Design System's 640px.

**Why:** This tool is used by retail analysts on desktop. Mobile traffic is effectively zero. Changing the breakpoint would require visually verifying all 9 decision modes at the new width — real QA work for a use case that doesn't exist.

**Revisit when:** The tool needs to support mobile or tablet use (e.g., buyers pulling it up during in-store meetings). At that point, change `@media (max-width: 767.98px)` to `639.98px` in `app/assets/style.css` and verify all decision modes at the new breakpoint.

## 2026-06-03: Velocity tool reads from dbt mart layer, not staging tables

**Decision:** All SQL queries in data.py read from mart-layer tables (dim_stores, fct_scan_data, fct_promotions, dim_products) instead of staging tables (stg_stores, stg_scan_data, stg_promotions, stg_sku_costs). search_path is public_marts first.

**Why:** Staging tables are dbt's internal implementation. The mart layer is the contracted surface — column names, types, and semantics are documented in schema.yml with tests. Reading staging directly couples the tool to dbt internals and bypasses any mart-level transformations (e.g., retailer_id → retailer_name join).

**Scope:** All SQL in app/data.py, app/validation.py, app/seed_benchmarks.py. Does NOT apply to stg_category_benchmarks (Velocity-specific local seed, not a platform table).

**Do not:** Add new queries that read stg_* or raw.* tables for shared data. If a field is missing from the mart, add it to the dbt model — do not work around by reading staging.

## 2026-06-03: stg_category_benchmarks stays local — not migrated to dbt

**Decision:** Keep stg_category_benchmarks as a Velocity-specific table created by seed_benchmarks.py, not a dbt model.

**Why:** The table contains synthetic category benchmarks — Cinderhaven's own scan velocity multiplied by hardcoded factors to approximate category averages. This is Velocity-specific seed data, not a shared platform definition. The mart dim_category_benchmarks is a different model (product-line summary aggregates). Migrating synthetic multipliers into dbt would pollute the platform with tool-specific assumptions.

**Scope:** seed_benchmarks.py creates/populates the table. data.py reads it with graceful fallback (try/except). It lives in public_staging schema by default.

**Do not:** Load this table via reload_postgres.py (disabled) or any process that overwrites platform-managed tables.

## 2026-06-03: reload_postgres.py disabled with hard guard

**Decision:** Added a _guard() function that exits with a clear message before any code runs. The file body is intact but unreachable.

**Why:** The script DROP/CREATEs 7 canonical tables (dim_products, stg_stores, stg_scan_data, etc.) from a local SQLite file. If run after Dagster/dbt has updated those tables, it overwrites authoritative data. No live process depends on it — it was a legacy manual loader.

**Scope:** reload_postgres.py only. Do not delete the file (kept for reference).

**Do not:** Remove the guard or bypass it. If data needs reloading, use the Dagster/dbt pipeline.

## 2026-05-22: Accept pool.getconn() having no timeout (#32)

**Decision:** Leave `psycopg2.pool.ThreadedConnectionPool.getconn()` without a timeout. If all 10 connections are in use, the 11th caller blocks indefinitely.

**Why:** With 1 gunicorn worker and synchronous Dash callbacks, exhausting 10 connections requires 10 simultaneous in-flight queries — effectively impossible. The `statement_timeout=30000` already bounds how long any single connection is held (30s max), so even a worst-case block is self-correcting.

**Revisit when:** Scaling to multiple gunicorn workers or adding async query patterns. Multiple workers sharing the same pool makes exhaustion realistic. Fix by wrapping `getconn()` in a `threading.Timer` or switching to SQLAlchemy's pool (which has native `pool_timeout`).
