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

## 2026-05-15: Expansion mode empty state on initial load

**What happened:** Navigating to the Expansion decision mode shows an empty state ("Select a product line and focus SKU") even though "Artisan Sauces" is pre-selected as the product line. The focus SKU dropdown stays empty.

**Why it failed:** The `update_expansion_skus` callback has `prevent_initial_call=True`, so it only fires when the product line value changes. On initial load, the default value is already set but the callback never fires to populate the dependent SKU dropdown.

**Fixed:** Pre-populated SKU options server-side in `_filters_expansion()` by calling `get_skus_for_line(product_lines[0])` at layout build time (PR #9).
