# Handoff — Retail Velocity Decision Tool

## Session ended: 2026-05-14 ~1:55pm ET

### Status: App deployed and serving — needs browser verification

### What shipped this session
- Fixed `get_pruning_data` GROUP BY error — added 7 missing non-aggregated columns (PR #4, merged)
- Connection pool maxconn increased from 4 to 10 (shipped in prior session commit `bbd84e9`)
- `fct_distribution` table created on production Fly Postgres (12,507 rows, shipped prior session via SSH)
- Deployed version 30 to Fly.io — machine `5683e221ce00d8` running in `iad`
- Cache fully populated: 95 files in `/cache/dash/` on persistent volume
- App serving HTTP 200 (verified via SSH localhost hit)
- Cleaned up temp `create_fct.py` script
- PR #1 created for refactor-older-cinderhaven-projects (SQLite-to-Postgres migration)

### What was fixed across both sessions (cumulative)
- Streamlit-to-Dash rewrite fully deployed
- Side-by-side layout (grid left, chart right) for all 8 decision modes
- Background cache warming for all retailer × mode combinations
- Persistent Fly volume at `/cache` (survives deploys)
- 1 gunicorn worker + 4 threads + 120s timeout
- Machine always-on (`auto_stop_machines = 'off'`)
- Boolean type mismatch in `get_promo_hangover_data` (`is_agg` int → Python bool)
- `fct_distribution` table created (was never materialized by dbt)
- Connection pool maxconn 4 → 10
- Pruning SQL GROUP BY error fixed

### What needs verification — do this first next session

1. **Open https://retail-velocity-decision-tool.fly.dev/ in a real browser.** WebFetch can't test Dash's JS SPA. Verify:
   - All 8 decision mode tabs load with data grids and charts
   - Dropdown switching is instant (data is cached)
   - **Story mode (Charred Scallion Relish) loads end-to-end** — user has never seen this work
2. If any tab fails, check `fly logs --app retail-velocity-decision-tool --no-tail` for the specific error

### Known risks
- `fct_distribution` was created via direct SQL, not dbt. Won't auto-refresh. Distribution data changes infrequently, so acceptable for now.
- Cache TTL is 24h. After expiry, warm_cache re-runs on next boot/visit. Persistent volume means cache survives deploys but not TTL expiry.
- Fly machine occasionally stops unexpectedly despite `auto_stop_machines = 'off'`. May need a health check endpoint or Fly uptime monitor.

### Architecture notes
- Cache: `flask-caching` FileSystemCache at `/cache/dash` (Fly volume, 1GB, persists across deploys)
- DB: Postgres via psycopg2, PID-aware ThreadedConnectionPool (maxconn=10)
- Deploy: `fly deploy` from local, Dockerfile builds from `app/` directory
- Gunicorn: 1 worker, gthread class, 4 threads, 120s timeout
- Machine: shared-cpu-1x, 1GB RAM, iad region, always-on

---

## Session ended: 2026-05-13 ~8:30pm ET (prior session)

### Status: BLOCKED on performance — resolved in 2026-05-14 session above
