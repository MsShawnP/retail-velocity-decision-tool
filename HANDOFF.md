# Handoff — Retail Velocity Decision Tool

## Session ended: 2026-05-17

### Status: Data Integrity Hardening COMPLETE — all 3 batches shipped and deployed

### What shipped this session
- **PR #13/#14** — Batch 1: div-by-zero fixes (promo ROI, shelf defense trend), seasonal validation warning, threshold consolidation (3 hardcoded 2.0 → `LAUNCH_BENCHMARK`), cache TTL reduced 24h → 6h
- **PR #15** — Batch 2a + Batch 3 + review followups: startup data contract validation (7 SQL checks on boot), calculation chain tests (160 total), `calcs.py` extraction for testability, `dropna` → `fillna(0)` for zero-velocity SKU visibility, `get_latest_week()` empty-table guard
- **PR #16** — Batch 2b: threshold recalibration based on live velocity distributions. Retailer thresholds: Walmart 2.0→5.0, Costco 5.0→27.0, Whole Foods 1.5→2.5, Regional 1.0→2.0. Production trend ±10%→±15%. Launch benchmark 2.0→4.0.
- **DB scaled** from 256MB to 1GB to handle analytical queries

### PRs (all merged)
- [#13](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/13), [#14](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/14), [#15](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/15), [#16](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/16)

### What needs doing next
1. **Verify live classifications** — spot-check the deployed app to confirm the recalibrated thresholds produce sensible At Risk / Safe / Warning distributions
2. **Competitive benchmarking** — out of scope (requires new synthetic data), natural next decision area
3. **`base_chart_layout` time-series helper** — extract if more trend charts are added
4. **Cache TTL restoration** — currently 6h for validation period; return to 24h once data is confirmed stable

### Known risks
- `fct_distribution` was created via direct SQL, not dbt. Won't auto-refresh.
- Fly DB scaled to 1GB ($12/mo vs $3/mo) — could downscale once analytical queries are done.
- Fly machine occasionally stops unexpectedly despite `auto_stop_machines = 'off'`.

### Architecture notes
- Cache: `flask-caching` FileSystemCache at `/cache/dash` (Fly volume, 1GB)
- DB: Postgres via psycopg2, PID-aware ThreadedConnectionPool (maxconn=10)
- Deploy: `fly deploy` from local, Dockerfile builds from `app/` directory
- New data functions: `get_portfolio_summary`, `get_weekly_velocity_trend`, `get_weekly_total_units`, `get_launch_velocity_curve`

---

## Session ended: 2026-05-13 ~8:30pm ET (prior session)

### Status: BLOCKED on performance — resolved in 2026-05-14 session above
