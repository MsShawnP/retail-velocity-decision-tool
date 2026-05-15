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

**Why:** The dbt model existed (`cinderhaven-data-platform/models/marts/fct_distribution.sql`) but was never materialized. The dbt profile points at localhost, not the remote Fly Postgres. Running `CREATE TABLE fct_distribution AS SELECT ...` directly was the fastest path to unblocking pruning, expansion, and Story mode — all of which depend on this table.

**Tradeoff:** Table won't auto-refresh when dbt runs. Acceptable for now — distribution data changes infrequently. Will need a proper dbt materialization path when the data platform CI pipeline runs against production.

## 2026-05-13: Side-by-side layout (grid left, chart right)

**Decision:** Restructured all 8 decision modes from vertical stacking to a viewport-fitting flex layout with data grid on the left and chart/narrative on the right.

**Why:** User feedback — charts and insights were below the fold, requiring scrolling. The tool's value is the insight paired with the data; both need to be visible simultaneously.

**Tradeoff:** Less vertical space for each panel. AG Grid now uses internal scrollbars (`domLayout: "normal"`) instead of expanding to show all rows.

## 2026-05-15: Replace Story mode with portfolio health dashboard

**Decision:** Deleted the 5-section Story mode entirely and replaced it with a portfolio health landing page that aggregates risk indicators across all decision areas. Decision modes became the narrative building blocks — each got a "so what" insight and (where applicable) trend charts.

**Why:** The Story mode was a guided walkthrough of one protagonist SKU. A cold-landing CEO doesn't want a tour — they want to see their portfolio's health instantly and drill into what matters. The decision modes already had the data; they just needed narrative framing.

**Tradeoff:** Lost the linear storytelling arc. Gained a tool that hooks within 30 seconds by surfacing what's interesting (at-risk clusters, production spikes, launch failures) and letting the user pull rather than push.

## 2026-05-15: Trend charts use base_chart_layout with yaxis autorange override

**Decision:** Reused the existing `base_chart_layout()` helper for all 3 new trend charts but overrode `yaxis.autorange = True` in each.

**Why:** `base_chart_layout` defaults to `autorange="reversed"` because it was designed for horizontal bar charts (labels top-to-bottom). Time-series charts need standard ascending y-axis. Overriding one property is simpler than creating a second layout helper.

**Tradeoff:** Each trend chart needs a 1-line override. Acceptable until there are enough time-series charts to justify a `time_series_layout()` helper.
