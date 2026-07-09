"""Bake all decision-mode views to JSON for offline serving.

Connects to Postgres via DATABASE_URL, calls each data query function for
every retailer × mode combination, and writes the results to
data/baked_views/ as JSON files. These files are committed artifacts that
the app can serve from when Postgres is unavailable.

Usage:
    flyctl proxy 5432 -a cinderhaven-db    # in another terminal
    DATABASE_URL=postgresql://... python scripts/bake_views.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))

OUT = REPO / "data" / "baked_views"

import pathlib
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

if not os.environ.get("DATABASE_URL"):
    sys.exit(
        "DATABASE_URL is not set. Start the Fly proxy and provide it, e.g.:\n"
        "  flyctl proxy 5432 -a cinderhaven-db\n"
        "  DATABASE_URL=postgresql://... python scripts/bake_views.py\n"
        "(or put DATABASE_URL in a local .env — never commit it)"
    )

import dash_bootstrap_components as dbc
from dash import Dash
import pandas as pd

_app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
_server = _app.server

from data import init_cache
init_cache(_server)

from constants import ALL_PHYSICAL_OR_AGG, PHYSICAL_RETAILERS
from data import (
    get_category_benchmark,
    get_expansion_data,
    get_launch_data,
    get_latest_week,
    get_portfolio_summary,
    get_pricing_data,
    get_product_lines,
    get_production_data,
    get_promo_roi_data,
    get_pruning_data,
    get_rationalization_data,
    get_shelf_defense_data,
    get_skus_for_line,
)


def _save(name: str, obj) -> None:
    path = OUT / f"{name}.json"
    if isinstance(obj, pd.DataFrame):
        path.write_text(obj.to_json(orient="split", date_format="iso"), encoding="utf-8")
    elif isinstance(obj, dict):
        path.write_text(json.dumps(obj, default=str), encoding="utf-8")
    elif isinstance(obj, list):
        path.write_text(json.dumps(obj, default=str), encoding="utf-8")
    else:
        path.write_text(json.dumps(obj, default=str), encoding="utf-8")
    print(f"  {path.name} ({path.stat().st_size / 1024:.1f} KB)")


def _try(label: str, fn):
    try:
        result = fn()
        _save(label, result)
        return result
    except Exception as e:
        print(f"  SKIP {label}: {type(e).__name__}: {e}")
        return None


def bake():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Baking views to {OUT}/\n")

    _try("product_lines", get_product_lines)
    _try("latest_week", get_latest_week)
    _try("portfolio_summary", get_portfolio_summary)

    lines = get_product_lines()
    for line in lines:
        safe = line.lower().replace(" ", "_")
        _try(f"skus__{safe}", lambda l=line: get_skus_for_line(l))

    _try("launch_data", get_launch_data)

    for ret in PHYSICAL_RETAILERS:
        safe = ret.lower().replace(" ", "_")
        _try(f"shelf_defense__{safe}", lambda r=ret: get_shelf_defense_data(r, None))
        _try(f"pruning__{safe}", lambda r=ret: get_pruning_data(r, None))

    for ret in ["All Retailers"] + PHYSICAL_RETAILERS:
        safe = ret.lower().replace(" ", "_")
        _try(f"production__{safe}", lambda r=ret: get_production_data(r, None))
        _try(f"rationalization__{safe}", lambda r=ret: get_rationalization_data(r, None))

    for ret in ALL_PHYSICAL_OR_AGG:
        safe = ret.lower().replace(" ", "_")
        _try(f"promo_roi__{safe}", lambda r=ret: get_promo_roi_data(r, None)[0])
        _try(f"pricing__{safe}", lambda r=ret: get_pricing_data(r, None, None))

    for ret in ALL_PHYSICAL_OR_AGG:
        safe = ret.lower().replace(" ", "_")
        _try(f"category_benchmark__{safe}", lambda r=ret: get_category_benchmark(r, None))

    if lines:
        skus = get_skus_for_line(lines[0])
        if skus:
            first_sku = skus[0][0]
            for ret in [None] + PHYSICAL_RETAILERS:
                safe = (ret or "all").lower().replace(" ", "_")
                _try(f"expansion__{safe}__{first_sku}", lambda r=ret, s=first_sku: get_expansion_data(s, r))

    total_kb = sum(f.stat().st_size for f in OUT.glob("*.json")) / 1024
    n_files = len(list(OUT.glob("*.json")))
    print(f"\nDone. {n_files} files, {total_kb:.0f} KB total.")


if __name__ == "__main__":
    with _server.app_context():
        bake()
