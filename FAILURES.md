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
