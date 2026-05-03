"""Build the Cinderhaven SQLite dataset from scratch.

The 164 MB synthetic dataset is too large to commit to GitHub, so this
script regenerates it on demand. Runs once on first deploy (or whenever
the DB file is missing) and is a no-op on subsequent boots.

Order of operations:
  0. Seed `product_master` from scripts/seed_product_master.sql (90 rows
     of read-only product reference data).
  1. 01_generate_stores.py          — store directory
  2. 02_generate_distribution.py    — SKU x store authorizations + deauths
  3. 02b_generate_chargebacks.py    — defect-driven chargebacks
  4. 03_generate_costs.py           — sku_costs (wholesale, COGS, etc.)
  5. 04_generate_promos.py          — promotions table
  6. 04b_generate_price_history.py  — price history per SKU x retailer
  7. 05_generate_scan_data.py       — weekly scan data (the big one)
  8. 06_validate_dataset.py         — sanity-check the built DB

Usage:
  python scripts/build_db.py           # build if missing
  python scripts/build_db.py --force   # rebuild even if DB exists
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "cinderhaven_product_master.db"
SEED_SQL = Path(__file__).resolve().parent / "seed_product_master.sql"

# Order matters: each script reads from tables built by earlier ones.
PIPELINE = [
    "01_generate_stores.py",
    "02_generate_distribution.py",
    "02b_generate_chargebacks.py",
    "03_generate_costs.py",
    "04_generate_promos.py",
    "04b_generate_price_history.py",
    "05_generate_scan_data.py",
    "06_validate_dataset.py",
]


def seed_product_master() -> None:
    """Load the 90-row product_master seed from SQL."""
    if not SEED_SQL.exists():
        raise FileNotFoundError(
            f"Seed file missing: {SEED_SQL}. "
            "Cannot bootstrap product_master without it."
        )
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        with SEED_SQL.open(encoding="utf-8") as f:
            con.executescript(f.read())
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM product_master").fetchone()[0]
        print(f"  [OK] Seeded product_master ({n} rows)")
    finally:
        con.close()


def run_script(name: str) -> None:
    script = Path(__file__).resolve().parent / name
    if not script.exists():
        raise FileNotFoundError(f"Pipeline script missing: {script}")
    print(f"  -> Running {name}...")
    # Same Python interpreter that's running build_db.py — ensures the same
    # virtualenv / dependencies are used. Inherits stdout/stderr so progress
    # output streams through to the caller (Streamlit Cloud logs, terminal).
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{name} exited with status {result.returncode}. "
            f"Build aborted; the DB may be in a partial state."
        )


def build(force: bool = False) -> None:
    if DB_PATH.exists() and not force:
        size_mb = DB_PATH.stat().st_size / (1024 * 1024)
        print(f"Database already exists ({size_mb:.1f} MB) — skipping build.")
        print(f"  Path: {DB_PATH}")
        print(f"  Pass --force to rebuild from scratch.")
        return

    if force and DB_PATH.exists():
        print(f"Removing existing {DB_PATH.name} (--force)...")
        DB_PATH.unlink()
        # Also clear stale WAL/SHM that would otherwise survive the rebuild.
        for sidecar in (DB_PATH.with_suffix(".db-wal"), DB_PATH.with_suffix(".db-shm")):
            if sidecar.exists():
                sidecar.unlink()

    print("Building Cinderhaven dataset...")
    print("Step 0: seed product_master")
    seed_product_master()

    for i, name in enumerate(PIPELINE, start=1):
        print(f"Step {i}: {name}")
        run_script(name)

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\nBuild complete. Database is {size_mb:.1f} MB at {DB_PATH}.")


def main() -> int:
    p = argparse.ArgumentParser(description="Build the Cinderhaven SQLite dataset.")
    p.add_argument(
        "--force", action="store_true",
        help="Rebuild from scratch even if the DB already exists.",
    )
    args = p.parse_args()
    try:
        build(force=args.force)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
