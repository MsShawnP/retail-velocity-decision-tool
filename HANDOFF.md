# Handoff — Retail Velocity Decision Tool

## Last session: 2026-05-13

### What shipped
- Streamlit-to-Dash rewrite fully deployed to Fly.io
- Side-by-side layout (grid left, chart right) for all 8 decision modes
- Background cache warming for all retailer × mode combinations
- Persistent Fly volume at `/cache` so cache survives deploys
- 1 gunicorn worker + 4 threads + 120s timeout
- Machine set to always-on (`auto_stop_machines = 'off'`)
- Fixed `get_promo_hangover_data` boolean type mismatch (`is_agg` was int, Postgres column is boolean)

### What's broken — must fix next session

1. **All tabs must load instantaneously.** Currently the first load after a deploy or cache expiry is slow (each query hits remote Postgres). The persistent volume helps on subsequent visits, but the first warm is still painful. Consider pre-loading the "All" / default data for every dropdown on every mode so the most common views are always ready. The cache TTL is 24h — weekly data doesn't change faster than that.

2. **The Charred Scallion Relish story/report has never successfully loaded.** The user has not seen it work once. Known issues:
   - `get_promo_hangover_data` was hitting a `boolean = integer` type error on `is_aggregated_channel` — fixed in code but may not have been cached successfully yet
   - `get_pruning_data` fails with `relation "fct_distribution" does not exist` — this table may not exist in the current database schema. Needs investigation: is the table missing from dbt, or is the query referencing the wrong table name?
   - Story mode calls ~12 data functions sequentially. If any one fails, the whole page may error out. Need to check whether the Story layout handles partial failures or crashes entirely.

3. **"Connection pool exhausted" errors on tab switching.** User saw `Promo ROI query failed — Could not load promo ROI data for Walmart: connection pool exhausted`. Root cause: warm_cache background thread holds connections while user requests also need them. Pool is maxconn=4, worker has 4 threads + 1 warm_cache thread = 5 potential consumers. Fix: increase maxconn to 8 in `app/db.py` line 58, OR throttle warm_cache to sleep between queries and release connections, OR restructure warm_cache to use a single connection for all queries instead of checking out/returning per call.

### Specific next steps

1. **Fix connection pool exhaustion** — increase `maxconn` in `app/db.py` from 4 to 8, or restructure warm_cache to be less greedy with connections
2. SSH into Fly machine, check `/cache/dash` directory to confirm cache files exist and are being written
3. Investigate `fct_distribution` — does this table exist in the database? Run `\dt fct_*` or check dbt models
4. Load the Story tab manually and read the full error traceback from `fly logs`
5. Make warm_cache robust to individual query failures (it already catches exceptions, but confirm the Story-mode data functions all succeed)
6. Test every tab + every dropdown value in the browser and confirm instant switching
7. Consider whether the cache warming strategy needs rethinking — pre-compute at deploy time vs runtime warming

### Architecture notes
- Cache: `flask-caching` FileSystemCache at `/cache/dash` (Fly volume, 1GB, persists across deploys)
- DB: Postgres via psycopg2, PID-aware ThreadedConnectionPool (maxconn=4 — TOO LOW, needs increase)
- Deploy: `fly deploy` from local, Dockerfile builds from `app/` directory
- Gunicorn: 1 worker, gthread class, 4 threads, 120s timeout
