"""Cinderhaven Velocity Tool -- Dash application entry point."""

from __future__ import annotations

import pathlib
import threading

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")

import dash_bootstrap_components as dbc
from dash import Dash
from flask import jsonify

from callbacks import register_callbacks
from data import init_cache, warm_cache, warm_default_view
from decisions.shelf_defense import register_callbacks as shelf_cbs
from decisions.production import register_callbacks as prod_cbs
from decisions.promo_roi import register_callbacks as promo_cbs
from decisions.expansion import register_callbacks as expansion_cbs
from decisions.pruning import register_callbacks as pruning_cbs
from decisions.rationalization import register_callbacks as rationalization_cbs
from decisions.launch_health import register_callbacks as launch_cbs
from decisions.pricing_power import register_callbacks as pricing_cbs
from layout import create_layout

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)
server = app.server
init_cache(server)


@server.route("/health")
def health():
    return jsonify({"status": "ok"})


app.layout = create_layout()
register_callbacks(app)
shelf_cbs(app)
prod_cbs(app)
promo_cbs(app)
expansion_cbs(app)
pruning_cbs(app)
rationalization_cbs(app)
launch_cbs(app)
pricing_cbs(app)

warm_default_view()
threading.Thread(target=warm_cache, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True, port=8050)
