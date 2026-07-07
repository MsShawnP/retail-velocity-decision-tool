# Failures

## 2026-05-13: Cache warming strategy — runtime warming doesn't work at scale

**What happened:** Added a background `warm_cache()` thread that runs ~60 sequential Postgres queries on worker boot. With 2 workers, this doubled to ~120 queries. The thread consumed DB connections from the same pool user requests need, causing "connection pool exhausted" errors on tab switches.

**Why it failed:** The connection pool (maxconn=4) was too small for 4 request threads + 1 warming thread. More fundamentally, runtime cache warming races against user requests — the cache isn't useful until warming finishes, but warming competes with the requests it's supposed to speed up.

**Lesson:** For a read-heavy analytics tool with infrequently-changing data, cache warming should happen BEFORE the app serves traffic (build-time or deploy-time pre-computation), not alongside it. The persistent volume was the right call; the warming strategy needs rethinking.

## 2026-05-14: Pruning query GROUP BY missing columns

**What happened:** `get_pruning_data` SELECT included `rs.retailer, rs.region, rs.state, rs.volume_tier, pm.product_name, pm.product_line, sc.wholesale_price` but the GROUP BY only had `a.sku, a.store_id`. Postgres rejected every pruning query with `GroupingError`, causing all pruning tab loads and warm_cache pruning entries to fail silently. The machine crashed repeatedly during warm_cache as a result.

**Why it failed:** When writing the SQL, the GROUP BY clause was copied from a simpler version of the query before the join columns were added to the SELECT. Postgres requires all non-aggregated SELECT columns in GROUP BY (unlike MySQL's permissive mode).

**Fix:** Added all non-aggregated columns to GROUP BY: `rs.retailer, rs.region, rs.state, rs.volume_tier, pm.product_name, pm.product_line, sc.wholesale_price`.

**Lesson:** After adding columns to a SELECT that has a GROUP BY, always verify the GROUP BY includes them. The error only surfaces at runtime against Postgres — no local lint catches it.

## 2026-05-13: Dockerfile COPY . . put modules at wrong path

**What happened:** First Fly deploy returned 502 — `ModuleNotFoundError: No module named 'callbacks'`. The Dockerfile used `COPY . .` which placed the repo root at `/app/`, so `app/run.py` was at `/app/app/run.py`. Gunicorn's `app.run:server` found the module, but bare imports like `from callbacks import ...` resolved against `/app/` (repo root) not `/app/app/` (where the Python modules live).

**Fix:** Changed to `COPY app/ .` and gunicorn module path from `app.run:server` to `run:server`.

**Lesson:** When the Dockerfile WORKDIR is `/app` and the Python code lives in `app/`, use `COPY app/ .` to flatten the contents. Don't assume `COPY . .` preserves the import paths you expect.

## 2026-05-15: SQLite-to-Postgres type mismatches (boolean and date columns)

**What happened:** After loading Cinderhaven data into Postgres via COPY, multiple queries failed. `is_aggregated_channel` loaded as BIGINT (0/1) but SQL used `= false`. Date columns (week_ending, authorized_date, etc.) loaded as TEXT, so comparisons like `text <= date` failed with type errors.

**Why it failed:** The CSV loader inferred types from the data rather than the schema. SQLite doesn't enforce column types, so the original data had no type metadata. Postgres is strict about type comparisons.

**Fix:** ALTER COLUMN TYPE for booleans (`USING col::int::boolean`) and dates (`USING col::date`) on all 6 affected columns.

**Lesson:** When migrating from SQLite to Postgres, audit every column type before running queries. SQLite's dynamic typing masks type mismatches that Postgres enforces.

## 2026-05-17: Fly Postgres OOM on analytical queries at 256MB

**What happened:** Running a calibration script with correlated subqueries (`SELECT ... WHERE (SELECT MAX(week_ending) FROM stg_scan_data)::date - week_ending::date < 28`) against ~4200 rows OOM'd the 256MB shared-cpu Postgres instance. The server closed the connection mid-query, the connection pool was corrupted, and subsequent queries also failed.

**Why it failed:** Correlated subqueries materialize intermediate results that don't fit in 256MB. The Fly shared-cpu tier has tight memory limits with no swap.

**Fix:** Scaled DB to 1GB (`fly machines update --vm-memory 1024`). Required stop/start cycle and role recovery (error → primary).

**Lesson:** Don't run ad-hoc analytical queries against the production DB at minimum memory. For one-time analysis, scale up first, run the query, then optionally scale back down.

## 2026-05-17: Mock cursor shared-index bug in validation tests

**What happened:** `test_validation.py` used separate `MagicMock(side_effect=...)` for `fetchone` and `fetchall`, each with its own internal counter through the response list. Three tests failed because the methods consumed responses out of order — `fetchone` grabbed a response meant for `fetchall` and vice versa.

**Why it failed:** The validation function interleaves `fetchone` and `fetchall` calls on the same cursor. Two independent side_effect iterators meant each method had its own position, but they needed to share one position through a single ordered response list.

**Fix:** Used a single `it = iter(responses)` shared by both methods: `cur.fetchone = MagicMock(side_effect=lambda: next(it))`.

**Lesson:** When mocking a cursor that interleaves fetchone/fetchall, use a shared iterator, not separate counters.

## 2026-05-15: Expansion mode empty state on initial load

**What happened:** Navigating to the Expansion decision mode shows an empty state ("Select a product line and focus SKU") even though "Artisan Sauces" is pre-selected as the product line. The focus SKU dropdown stays empty.

**Why it failed:** The `update_expansion_skus` callback has `prevent_initial_call=True`, so it only fires when the product line value changes. On initial load, the default value is already set but the callback never fires to populate the dependent SKU dropdown.

**Fixed:** Pre-populated SKU options server-side in `_filters_expansion()` by calling `get_skus_for_line(product_lines[0])` at layout build time (PR #9).

## 2026-05-16: Plotly autorange ignores hline/vline reference lines

**What happened:** Trend charts in Shelf Defense and Launch Health had reference lines (threshold, category avg) added via `add_hline()`, but they were invisible — the chart appeared "zoomed in too much."

**Why it failed:** `yaxis.autorange = True` only considers scatter trace data points when computing the axis range. `add_hline` draws shapes/annotations that don't participate in Plotly's autorange calculation. With data at ~2.5–3.0, the y-axis was set to ~2.3–3.2, putting the threshold (2.00) below the viewport and category avg (7.19) way above it.

**Fix:** Computed explicit y-axis range that collects all data values plus reference line values, adds 10% padding, and sets `yaxis.range` + `autorange=False`.

**Lesson:** Never rely on Plotly autorange when you have reference lines via `add_hline`/`add_vline`. Always compute the range explicitly to include them.

## 2026-06-03: Baked-view diff produced empty DataFrames — had to supplement with SQL verification

**What happened:** During the mart migration verification, both baseline and refactored bake_views.py runs produced 67 files but all DataFrame-based views were empty (0 rows). The diff script reported "18 fields compared" across 67 files — only the flat dicts (portfolio_summary) and lists (product_lines, SKU lists) had data.

**Why it failed:** The scan data in the live database has `latest_week = 2027-01-02` (synthetic future date), and the query windows (`latest_week - N days`) don't overlap with the actual scan data date range. Every velocity/margin query returns an empty result set.

**Fix:** Supplemented with direct SQL verification — compared mart columns against staging equivalents for all 50 SKUs, 640 stores, 138 promos, and 1.4M scan rows. This proved column-level parity without depending on the query windows.

**Lesson:** When verifying a refactor with a baseline diff, check that the baseline actually contains data before trusting the diff result. Empty-vs-empty always passes. Direct SQL comparisons (mart column = staging column) are more robust than end-to-end bake comparisons when the data state is sparse.
