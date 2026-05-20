# Handoff — Retail Velocity Decision Tool

## Session ended: 2026-05-20

### Status: Post-Lailara DS v2 QA — 13 review findings fixed + deployed, but user reports more bugs remain

### What shipped this session
- **Lailara Design System v2 QA fixes** — ran 5-agent `/ce:review` (correctness,
  maintainability, kieran-python, testing, adversarial). Found 13 issues across
  P0–P3 severity. All fixed and deployed.
- Key fixes:
  - `pitch_export.py` — `_hex_to_rgb` was splitting import blocks (fragile)
  - `components.py` — AG Grid `autoHeight` now only for ≤100 rows (was freezing
    browser on large pruning/rationalization grids)
  - `data.py` — `get_promo_roi_data` and `get_pricing_data` now handle "All
    Retailers" correctly (was filtering `WHERE retailer = 'All Retailers'` which
    matches zero DB rows)
  - `promo_roi.py` — NaN guards on format strings (was crashing on all-NaN columns)
  - `charts.py` — auto-margin capped at 40 chars (was producing 1300px+ margins
    on long labels), None-safe label handling
  - `pruning.py` — store tab `overflow: hidden` → `overflow-y: auto`
  - `constants.py` — deleted dead `RETAILER_ID_MAP` and misleading `BENCHMARK_BLUE`
  - `layout.py` — removed double-scrollbar inline style
  - `rationalization.py` — added missing `dash-footer` class
  - `callbacks.py` — type guard in `sync_pitch_retailer`

### What's broken (user says stuff is still broken)
- User reports there are STILL bugs visible on the live site
- User explicitly requested a "DEEP AUDIT AND CODE REVIEW" next session
- The prior round found 13 issues but was scoped to the DS v2 migration diff only
- **Next session must audit the ENTIRE codebase**, not just recent changes

### Next concrete action
1. Open the live site in a browser and systematically test EVERY decision mode
2. Run `/ce:review` against a broader scope (full codebase, not just a diff)
3. Fix everything found before declaring QA complete

### Commits this session
- `acd5228` — Fix 13 bugs from multi-agent code review (deployed)

### Tests
- 160 tests passing (up from 80 in prior session — test files were added between sessions)

### Known risks (carried forward)
- `fct_distribution` created via direct SQL, not dbt. Won't auto-refresh.
- Cache TTL is 24h. Persistent volume survives deploys but not TTL expiry.
- Fly machine occasionally stops unexpectedly despite `auto_stop_machines = 'off'`.

### Architecture notes
- Cache: `flask-caching` FileSystemCache at `/cache/dash` (Fly volume, 1GB)
- DB: Postgres via psycopg2, PID-aware ThreadedConnectionPool (maxconn=10)
- Deploy: `fly deploy` from local, Dockerfile builds from `app/` directory
- Tests: 160 tests across 7+ modules, CI via GitHub Actions (ruff + pytest)
- Live: https://retail-velocity-decision-tool.fly.dev/

---

## Session ended: 2026-05-16 (prior session)

### Status: Moves 5–9 complete, mobile UX polished, all merged to main

### What shipped
- Mobile sidebar fix, bar chart label overflow, trend chart y-axis fix
- Plotly modebar hidden on mobile
- Merged PR #12

### PRs merged
- [#10 — Moves 5–9](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/10)
- [#12 — Mobile UX polish + chart y-axis fix](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/12)
