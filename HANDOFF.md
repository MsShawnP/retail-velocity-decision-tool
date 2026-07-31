# Handoff — Retail Velocity Decision Tool

## 2026-07-31 — /improve + /ce review + /ui review

**Started from:** User asked to run /improve, /ce code review, /ui review. Mid-session goal clarified: make it trustworthy for a cold CEO/CFO who grasps the purpose in <30s; Claude wrote all of this (verify, don't assume); DO NOT touch the Postgres SSOT.

**Did:** 4-agent ce review + ui-review-skill (live site) + 30s comprehension read. Fixed 16 commits, all with regression tests, 172→183 tests green, ruff clean, pre-commit secret scan clean. Confirmed the 2026-07-18 hardcoded-DB-password concern is already resolved (bake_views.py reads DATABASE_URL from env). Theme of the fixes: the tool leads with dollar figures and several were wrong (overstated at-risk headline; promo totals ~25% low; single-week promos $0; pricing mislabeling recent promos as failures). Also: Expansion crash on tied scores, pitch-export margin mislabel, seasonal double-count, pruning mislabel, UI AA contrast + on-brand dropdowns, demo-dataset labeling, and unified the duplicated at-risk classification into data._shelf_risk_breakdown.

**56% at-risk:** Investigated read-only from baked views — it's a truthful cross-retailer union (per-retailer rates 6-32%, avg ~17%). Per user: kept the number, did NOT tune thresholds, documented in DECISIONS 2026-07-31.

**State:** Working tree has PLAN.md/HANDOFF.md/review.yaml/.gitignore updates to commit. All 16 fix commits are LOCAL — nothing deployed. The live site (velocity.lailarallc.com) still shows the OLD behavior including the wrong dollar figures.

**Next:**
1. **DEPLOY** — push to main triggers CI auto-deploy to Fly. Until then the CFO sees none of these fixes. This is the top action.
2. After deploy, re-run `/ui review` against live to confirm the AA contrast + dropdown warnings clear (the tool audits the live site).
3. Deferred (own decisions): Launch Health N+1 seq-scans (bites when launches exist), get_pricing_data correlated-EXISTS on filtered path, fct_scan_data index (SSOT — out of scope this session).
4. Promo/portfolio baked views recompute duration+revenue correctly on load now, so no re-bake needed for those fixes; seasonal boundary fix is live-path only (minor, baked unaffected until next bake).

---

## 2026-06-03 22:20 (wrapped)

**Started from:** Tool reading staging tables directly; reload_postgres.py could overwrite canonical platform tables.

**Did:** Disabled reload_postgres.py with hard guard. Repointed all SQL reads from stg_* to dbt mart equivalents (dim_stores, fct_scan_data, fct_promotions, dim_products). Added margin_per_unit/margin_pct to dim_products mart. Removed stg_sku_costs JOINs and Python margin re-derivation. Verified via 929 SQL comparisons against live Postgres — zero drifts.

**State:** All reads use mart layer. 164 tests passing (6 pre-existing portfolio test failures from baked-data bypass — not caused by this session). reload_postgres.py guarded. stg_category_benchmarks kept local. Baked views are empty DataFrames (scan data query windows return no rows). Pre-existing unstaged: README.md, pitch_export.py, test_canonical_regression.py.

**Next:** Investigate why baked views return empty DataFrames (scan data date coverage vs query windows). Re-bake with populated data, redeploy to Fly.io. Fix the 6 portfolio test failures (mock _load_baked_json to return None). Review unstaged README.md/pitch_export.py changes.

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

## 2026-07-18 22:35

**Started from:** Reported empty promo/velocity data despite ~123 reseeded promos; hypothesis was fct_/dim_ layer not rebuilt from stg_. Diagnose → fix → deploy.

**Did:** Connected to cinderhaven-db via flyctl proxy; ran diagnostics. Disproved the hypothesis — fct_promotions=123, fct_scan_data=1.3M rows, promo dates sit inside scan coverage, Regional→Regional Group mapping is correct. Found the app serves baked JSON (data/baked_views/), not the live DB. Discovered fct_scan_data has ZERO indexes → promo_roi's per-promo correlated subqueries seq-scan 97MB, exceeding the pool's 30s statement_timeout, so a fresh re-bake times out on the 5 physical retailers. Then discovered HEAD already contains the fix (commits 40c6e21 "rebake serving views" + a7f4e58 "ship baked_views into image"): populated promo_roi (walmart=22 rows etc.), latest_week=2025-12-27. The working tree I read at start was STALE (old CHP-0001 keys, empty promos, 2027-01-02); it was restored to HEAD mid-session.

**State:** Repo clean, working tree == HEAD (4754238). HEAD baked views correct/populated. DB healthy but still unindexed. Proxy stopped; temp credential file deleted. My discarded re-bake backed up in scratchpad only. SECURITY: scripts/bake_views.py:24 still has the live DB password hardcoded + committed (untouched this session). Prod-vs-HEAD deploy status NOT verified.

**Next:**
1. VERIFY DEPLOY FIRST — curl velocity.lailarallc.com / check `fly releases`. If prod lags 40c6e21/a7f4e58, the empty-data symptom is a deploy gap → `fly deploy`, not a data bug.
2. Remove hardcoded DB password from scripts/bake_views.py:24 (read DATABASE_URL from env only), rotate the Fly credential, then purge git history (filter-repo/BFG — destructive, confirm before running).
3. Optional durable fix: CREATE INDEX CONCURRENTLY ON public_marts.fct_scan_data (sku, store_id, week_ending) so future re-bakes don't time out.
