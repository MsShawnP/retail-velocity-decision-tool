# Handoff — Retail Velocity Decision Tool

## Session ended: 2026-05-15

### Status: PLAN.md complete — PR #8 open, ready for merge

### What shipped this session
- **A1: Removed Story mode** — deleted story.py and all story-specific code/callbacks/CSS/data functions
- **A2: Portfolio health data layer** — `get_portfolio_summary()` aggregates across decision areas
- **A3: Portfolio health landing page** — default view with KPIs, risk cards, status distribution
- **A4: Drill-down navigation** — risk cards click through to the corresponding decision mode
- **B1: Narrative insights** — all 8 decision modes now show a "so what" insight sentence
- **B2: Time-series trend charts** — Shelf Defense (at-risk velocity trend), Production (weekly demand), Launch Health (velocity curves since launch)
- **C: End-to-end polish** — full flow verified in browser, no regressions

### PR
- [#8 — Replace Story mode with portfolio health dashboard](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/8)
- Branch: `claude/elastic-kare-2125ea`

### What needs doing next
1. **Merge PR #8** and deploy to Fly.io
2. **Expansion initial-load bug** — SKU dropdown empty on first load because `prevent_initial_call=True` prevents population. Pre-existing, not a regression. Fix: populate SKU options server-side in layout or switch to `prevent_initial_call=False`.
3. **Competitive benchmarking** — explicitly out of scope (requires new synthetic data), but would be the natural next decision area
4. **`base_chart_layout` time-series helper** — if more trend charts are added, extract a `time_series_layout()` to avoid repeating the yaxis autorange override

### Known risks
- `fct_distribution` was created via direct SQL, not dbt. Won't auto-refresh.
- Cache TTL is 24h. Persistent volume survives deploys but not TTL expiry.
- Fly machine occasionally stops unexpectedly despite `auto_stop_machines = 'off'`.

### Architecture notes
- Cache: `flask-caching` FileSystemCache at `/cache/dash` (Fly volume, 1GB)
- DB: Postgres via psycopg2, PID-aware ThreadedConnectionPool (maxconn=10)
- Deploy: `fly deploy` from local, Dockerfile builds from `app/` directory
- New data functions: `get_portfolio_summary`, `get_weekly_velocity_trend`, `get_weekly_total_units`, `get_launch_velocity_curve`

---

## Session ended: 2026-05-13 ~8:30pm ET (prior session)

### Status: BLOCKED on performance — resolved in 2026-05-14 session above
