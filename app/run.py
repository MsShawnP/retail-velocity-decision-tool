"""Cinderhaven Velocity Tool -- Dash application entry point.

Minimal scaffold for U1 foundation. Decision pages will be registered as
individual modules under app/decisions/ in subsequent units.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import Dash, html

from data import init_cache

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)
server = app.server
init_cache(app)

app.layout = html.Div("Cinderhaven Velocity Tool — foundation loaded")

if __name__ == "__main__":
    app.run(debug=True, port=8050)
