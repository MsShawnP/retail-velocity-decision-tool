# Handoff — Retail Velocity Decision Tool

## Session ended: 2026-05-16

### Status: Moves 5–9 complete, mobile UX polished, all merged to main

### What shipped this session
- **Mobile sidebar fix** — starts collapsed on mobile so users see the dashboard
  first. Toggle button reads "☰ Show Filters & Navigation" / "☰ Hide Filters".
  Desktop unaffected via CSS media query override.
- **Bar chart label overflow** — reduced text font 14→12, fewer decimal places,
  increased x_pad_pct to 0.30 across all 7 decision modes with bar charts.
- **Trend chart y-axis fix** — replaced `autorange=True` with explicit range
  that includes threshold + category avg reference lines (they were off-screen).
- **Plotly modebar hidden on mobile** — toolbar icons overlapped annotations
  and are useless on touch screens.
- **Merged PR #12** into main (squash merge).

### PRs merged
- [#10 — Moves 5–9](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/10) (merged prior session)
- [#12 — Mobile UX polish + chart y-axis fix](https://github.com/MsShawnP/retail-velocity-decision-tool/pull/12)

### What's left (verification only)
- Move 6 verify: first-visitor load time <3s with warm cache
- Move 7 verify: eyeball on iPhone SE / Pixel viewport sizes

### Possible next moves
1. **Move 10: "How do I compare?" mode** — standalone benchmarking decision mode
   (deferred from Move 8). Would give category benchmarks their own view instead
   of being reference lines on other charts.
2. **Inline styles cleanup** — AUDIT finding #6, low-medium priority.
3. **Time-series layout helper** — extract `time_series_layout()` from the
   repeated pattern in shelf_defense, launch_health, production trend charts.

### Known risks
- `fct_distribution` created via direct SQL, not dbt. Won't auto-refresh.
- Cache TTL is 24h. Persistent volume survives deploys but not TTL expiry.
- Fly machine occasionally stops unexpectedly despite `auto_stop_machines = 'off'`.

### Architecture notes
- Cache: `flask-caching` FileSystemCache at `/cache/dash` (Fly volume, 1GB)
- DB: Postgres via psycopg2, PID-aware ThreadedConnectionPool (maxconn=10)
- Deploy: `fly deploy` from local, Dockerfile builds from `app/` directory
- Tests: 80 tests across 7 modules, CI via GitHub Actions (ruff + pytest)
- Live: https://retail-velocity-decision-tool.fly.dev/

---

## Session ended: 2026-05-15 (prior session)

### Status: PLAN.md complete — PR #8 open, ready for merge

### What shipped
- A1–A4: Portfolio health dashboard (data layer, landing page, drill-down nav)
- B1–B2: Narrative insights + trend charts on all decision modes
- C: End-to-end polish
