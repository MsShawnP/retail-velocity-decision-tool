# Decisions

## 2026-05-13: Persistent Fly volume for cache instead of /tmp

**Decision:** Mount a 1GB Fly volume at `/cache` and point FileSystemCache there instead of `/tmp/dash-cache`.

**Why:** `/tmp` is wiped on every deploy and machine restart. With `auto_stop_machines` (now off) or any redeploy, the cache was lost and all ~60 queries had to re-run against Postgres. Weekly scan data doesn't change fast enough to justify re-querying on every boot.

**Tradeoff:** Volume costs ~$0.15/GB/month (negligible). Volume is pinned to one machine in one region — fine for a single-machine portfolio tool, would need rethinking for multi-region.

## 2026-05-13: Single gunicorn worker with 4 threads

**Decision:** Changed from 2 workers × 2 threads to 1 worker × 4 threads.

**Why:** Each worker independently ran `warm_cache()`, doubling the DB load (~120 concurrent queries). With FileSystemCache shared on disk, only one worker's warming is needed. Single worker eliminates the duplication while 4 threads maintain concurrency.

**Tradeoff:** No process-level isolation — a segfault kills the only worker. Acceptable for a portfolio tool.

## 2026-05-13: Machine always-on (auto_stop_machines = off)

**Decision:** Set `auto_stop_machines = 'off'` and `min_machines_running = 1` in fly.toml.

**Why:** With auto-stop, every idle timeout killed the machine, wiped `/tmp`, and forced a full cold-cache rebuild on the next visit. Even with the persistent volume, machine stop/start adds latency. Always-on keeps the process warm.

**Tradeoff:** ~$3-5/month for a shared-cpu-1x 1GB machine running continuously.

## 2026-05-13: Side-by-side layout (grid left, chart right)

**Decision:** Restructured all 8 decision modes from vertical stacking to a viewport-fitting flex layout with data grid on the left and chart/narrative on the right.

**Why:** User feedback — charts and insights were below the fold, requiring scrolling. The tool's value is the insight paired with the data; both need to be visible simultaneously.

**Tradeoff:** Less vertical space for each panel. AG Grid now uses internal scrollbars (`domLayout: "normal"`) instead of expanding to show all rows.
