# Failures

## 2026-05-13: Cache warming strategy — runtime warming doesn't work at scale

**What happened:** Added a background `warm_cache()` thread that runs ~60 sequential Postgres queries on worker boot. With 2 workers, this doubled to ~120 queries. The thread consumed DB connections from the same pool user requests need, causing "connection pool exhausted" errors on tab switches.

**Why it failed:** The connection pool (maxconn=4) was too small for 4 request threads + 1 warming thread. More fundamentally, runtime cache warming races against user requests — the cache isn't useful until warming finishes, but warming competes with the requests it's supposed to speed up.

**Lesson:** For a read-heavy analytics tool with infrequently-changing data, cache warming should happen BEFORE the app serves traffic (build-time or deploy-time pre-computation), not alongside it. The persistent volume was the right call; the warming strategy needs rethinking.

## 2026-05-13: Dockerfile COPY . . put modules at wrong path

**What happened:** First Fly deploy returned 502 — `ModuleNotFoundError: No module named 'callbacks'`. The Dockerfile used `COPY . .` which placed the repo root at `/app/`, so `app/run.py` was at `/app/app/run.py`. Gunicorn's `app.run:server` found the module, but bare imports like `from callbacks import ...` resolved against `/app/` (repo root) not `/app/app/` (where the Python modules live).

**Fix:** Changed to `COPY app/ .` and gunicorn module path from `app.run:server` to `run:server`.

**Lesson:** When the Dockerfile WORKDIR is `/app` and the Python code lives in `app/`, use `COPY app/ .` to flatten the contents. Don't assume `COPY . .` preserves the import paths you expect.
