# Handoff — Retail Velocity Decision Tool

## 2026-06-03 22:15

**What changed:** Repoint Velocity tool to dbt mart layer — stg_stores→dim_stores, stg_scan_data→fct_scan_data, stg_promotions→fct_promotions, stg_sku_costs removed (merged into dim_products). margin_per_unit promoted from Python re-derivation to dim_products mart column. stg_category_benchmarks kept local (Velocity-specific synthetic seed data). search_path reordered to public_marts first. reload_postgres.py disabled with hard guard.

**Why:** The legacy reload_postgres.py could overwrite canonical platform tables with stale SQLite copies. Neutralized that risk, then migrated all reads to the contracted dbt mart surface so the tool consumes the same SSOT as every other platform consumer.

**State:** All SQL reads use mart tables. 929 SQL comparisons against live Postgres: zero drifts. 164 tests passing (6 pre-existing portfolio failures unrelated). reload_postgres.py guarded. dbt dim_products has new margin_per_unit/margin_pct columns (materialized). stg_category_benchmarks unchanged (local seed).

**Next:** Re-bake views against live Postgres with populated scan data to get non-empty baked artifacts, then redeploy to Fly.io.

---

## Session ended: 2026-05-22 (wrapped)

### Status: `/improve` pass complete + `/ce:compound` documented + deployed

### What shipped this session
- **Deployed prior code review fixes** to Fly.io
- **`/improve` pass** — 3-agent deep audit focused on data reconciliation with Postgres and calculation/assumption correctness
- **17 fixes across 10 files:**
  - 5 CRITICAL: forecast rounding, promo baseline guard, pricing elasticity guard, seasonal factor hardcoding, production trend status
  - 8 IMPORTANT: promo exclusion UI transparency, pricing "Insufficient data" verdict, shelf defense null detection, regional benchmark fallback, rationalization null guard, launch classifier cleanup, 2 new validation checks
  - 4 NICE TO HAVE: portfolio health label, threshold constants, expansion "All equivalent" tier, unused import cleanup
- **3 new tests** added (163 total, all passing)
- **Return type changes:** `apply_promo_calcs` → `tuple[DataFrame, int]`, production status → row-based function

### Files changed
- `app/calcs.py` — forecast rounding, trend status, promo return type, elasticity guard, seasonal clip, launch classifier, expansion tier
- `app/constants.py` — 6 new threshold constants
- `app/data.py` — promo return type, shelf defense, regional fallback, rationalization guard, validation friendly names, removed unused import
- `app/validation.py` — 2 new data contract checks (scan grain, cost completeness)
- `app/decisions/production.py` — display rounding fix
- `app/decisions/promo_roi.py` — exclusion transparency
- `app/decisions/pricing_power.py` — "Insufficient data" verdict + styling
- `app/decisions/expansion.py` — "All equivalent" tier
- `app/decisions/portfolio_health.py` — label clarity
- `tests/` — 4 test files updated for new behavior + 3 new tests

### Tests
- 163 tests passing. No regressions.

### Known risks (carried forward)
- `fct_distribution` created via direct SQL, not dbt. Won't auto-refresh.
- Cache TTL is 24h. Persistent volume survives deploys but not TTL expiry.
- Fly machine occasionally stops unexpectedly despite `auto_stop_machines = 'off'`.

### Commits this session
- `ca7ce07` — Fix 17 data integrity and calculation correctness issues from /improve audit
- `60f1bd2` — Add Dockerfile and fly.toml for reproducible deploys
- `aa946ef` — Add solution doc for calculation correctness fixes and CLAUDE.md

### Next concrete action
1. Next `/improve` due: 2026-06-22
2. Next dep audit due: 2026-07-22
3. Threshold recalibration deferred (prior session analysis showed all thresholds below p10)

### Architecture notes
- Cache: `flask-caching` FileSystemCache at `/cache/dash` (Fly volume, 1GB)
- DB: Postgres via psycopg2, PID-aware ThreadedConnectionPool (maxconn=10)
- Deploy: `fly deploy` from local, Dockerfile builds from `app/` directory
- Tests: 163 tests across 7+ modules, CI via GitHub Actions (ruff + pytest)
- Live: https://velocity.lailarallc.com/

---

## Session ended: 2026-05-20 (prior session)

### Status: Post-Lailara DS v2 QA — 13 review findings fixed + deployed

### What shipped
- 13 bugs fixed from multi-agent code review (scoped to DS v2 migration diff)
- Key fixes: AG Grid autoHeight, pitch_export hex parsing, promo NaN guards, chart margins

### Commits
- `acd5228` — Fix 13 bugs from multi-agent code review
