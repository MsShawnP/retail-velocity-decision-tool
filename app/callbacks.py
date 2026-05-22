"""Cinderhaven Velocity Tool -- top-level Dash callbacks.

Central nervous system for the app: filter visibility, the main-content
dispatcher, dependent dropdown chains, and threshold defaults.

All callbacks are registered via ``register_callbacks(app)`` so the module
never touches a module-level app instance.
"""

from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, dcc, no_update, html

from constants import (
    DECISIONS,
    DECISION_TITLES,
    GREY,
    PHYSICAL_RETAILERS,
    PORTFOLIO_HEALTH,
    RETAILER_THRESHOLDS,
)
from data import get_promo_skus, get_product_lines, get_skus_for_line
from pitch_export import build_pitch_excel, build_pitch_pdf
from decisions.portfolio_health import layout as portfolio_layout
from decisions.shelf_defense import layout as shelf_layout
from decisions.production import layout as production_layout
from decisions.promo_roi import layout as promo_layout
from decisions.expansion import layout as expansion_layout
from decisions.pruning import layout as pruning_layout
from decisions.rationalization import layout as rationalization_layout
from decisions.launch_health import layout as launch_layout
from decisions.pricing_power import layout as pricing_layout
from decisions.data_quality import layout as data_quality_layout


# ============================================================
# Mapping: decision index -> filter-group div id
# ============================================================

_FILTER_IDS = [
    "filters-portfolio",          # Portfolio Health (no inputs)
    "filters-shelf-defense",      # 0 — Shelf Defense
    "filters-production",         # 1 — Production
    "filters-promo",              # 2 — Promo ROI
    "filters-expansion",          # 3 — Expansion
    "filters-pruning",            # 4 — Pruning
    "filters-rationalization",    # 5 — Rationalization
    "filters-launch",             # 6 — Launch Health
    "filters-pricing",            # 7 — Pricing Power
    "filters-data-quality",       # 8 — Data Quality
]

# Component IDs that belong to each decision mode (for short-circuit logic).
_MODE_INPUTS = {
    0: {"shelf-retailer", "shelf-threshold", "shelf-product-line"},
    1: {"prod-retailer", "prod-product-line"},
    2: {"promo-retailer", "promo-sku"},
    3: {"expansion-product-line", "expansion-focus-sku", "expansion-retailer"},
    4: {"pruning-retailer", "pruning-threshold", "pruning-product-line"},
    5: {"rat-retailer", "rat-product-line"},
    6: set(),  # Launch Health has no filter inputs
    7: {"pricing-retailer", "pricing-scope", "pricing-product-line", "pricing-sku"},
    8: set(),  # Data Quality has no filter inputs
}


def register_callbacks(app) -> None:
    """Register every top-level callback on *app*."""

    # ----------------------------------------------------------
    # a) Filter visibility: show active mode, hide others
    # ----------------------------------------------------------
    @app.callback(
        [Output(fid, "style") for fid in _FILTER_IDS],
        Input("decision-picker", "value"),
    )
    def toggle_filters(decision: str):
        if decision == PORTFOLIO_HEALTH:
            idx = 0
        elif decision in DECISIONS:
            idx = DECISIONS.index(decision) + 1
        else:
            idx = 0
        return [
            {"display": "block"} if i == idx else {"display": "none"}
            for i in range(len(_FILTER_IDS))
        ]

    # ----------------------------------------------------------
    # a2) Portfolio drill-down: risk card click → decision picker
    # ----------------------------------------------------------
    _RISK_TO_DECISION = {
        "shelf": DECISIONS[0],
        "production-decel": DECISIONS[1],
        "production-accel": DECISIONS[1],
        "launch": DECISIONS[6],
    }

    @app.callback(
        Output("decision-picker", "value"),
        Input({"type": "ph-risk-card", "decision": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def drill_down(n_clicks_list):
        if not ctx.triggered_id or not any(n_clicks_list):
            return no_update
        decision_key = ctx.triggered_id["decision"]
        return _RISK_TO_DECISION.get(decision_key, no_update)

    # ----------------------------------------------------------
    # b) Dispatcher: single callback that owns main-content
    # ----------------------------------------------------------
    @app.callback(
        Output("main-content", "children"),
        Input("decision-picker", "value"),
        # Mode 0 — Shelf Defense
        Input("shelf-retailer", "value"),
        Input("shelf-threshold", "value"),
        Input("shelf-product-line", "value"),
        # Mode 1 — Production
        Input("prod-retailer", "value"),
        Input("prod-product-line", "value"),
        # Mode 2 — Promo ROI
        Input("promo-retailer", "value"),
        Input("promo-sku", "value"),
        # Mode 3 — Expansion
        Input("expansion-product-line", "value"),
        Input("expansion-focus-sku", "value"),
        Input("expansion-retailer", "value"),
        # Mode 4 — Pruning
        Input("pruning-retailer", "value"),
        Input("pruning-threshold", "value"),
        Input("pruning-product-line", "value"),
        # Mode 5 — Rationalization
        Input("rat-retailer", "value"),
        Input("rat-product-line", "value"),
        # Mode 6 — Launch Health (no filter inputs)
        # Mode 7 — Pricing Power
        Input("pricing-retailer", "value"),
        Input("pricing-scope", "value"),
        Input("pricing-product-line", "value"),
        Input("pricing-sku", "value"),
        prevent_initial_call=False,
    )
    def dispatch(
        decision,
        shelf_ret, shelf_thr, shelf_pl,
        prod_ret, prod_pl,
        promo_ret, promo_sku,
        exp_pl, exp_sku, exp_ret,
        prune_ret, prune_thr, prune_pl,
        rat_ret, rat_pl,
        price_ret, price_scope, price_pl, price_sku,
    ):
        if decision == PORTFOLIO_HEALTH:
            return portfolio_layout()

        idx = DECISIONS.index(decision) if decision in DECISIONS else 0

        triggered = ctx.triggered_id
        if triggered and triggered != "decision-picker":
            active_ids = _MODE_INPUTS.get(idx, set())
            if triggered not in active_ids:
                return no_update

        def _none_if(val: str | None, sentinel: str) -> str | None:
            return None if val == sentinel else val

        shelf_pl = _none_if(shelf_pl, "All")
        prod_pl = _none_if(prod_pl, "All")
        prune_pl = _none_if(prune_pl, "All")
        rat_pl = _none_if(rat_pl, "All")
        price_pl = _none_if(price_pl, "All")
        promo_sku = _none_if(promo_sku, "All SKUs")
        exp_ret = _none_if(exp_ret, "All Retailers")

        if shelf_thr is not None and shelf_thr <= 0:
            shelf_thr = RETAILER_THRESHOLDS.get(shelf_ret, 2.0)
        if prune_thr is not None and prune_thr <= 0:
            prune_thr = RETAILER_THRESHOLDS.get(prune_ret, 2.0) if prune_ret else 2.0

        try:
            if idx == 0:
                return shelf_layout(shelf_ret, shelf_thr, shelf_pl)
            elif idx == 1:
                return production_layout(prod_ret, prod_pl)
            elif idx == 2:
                return promo_layout(promo_ret, promo_sku)
            elif idx == 3:
                return expansion_layout(exp_pl, exp_sku, exp_ret)
            elif idx == 4:
                return pruning_layout(prune_ret, prune_thr, prune_pl)
            elif idx == 5:
                return rationalization_layout(rat_ret, rat_pl)
            elif idx == 6:
                return launch_layout()
            elif idx == 7:
                return pricing_layout(price_ret, price_scope, price_pl, price_sku)
            elif idx == 8:
                return data_quality_layout()
        except Exception as exc:
            return error_card(
                "Decision mode failed",
                f"An unexpected error occurred: {exc}",
            )

        title = DECISION_TITLES.get(decision, decision)
        return html.Div(
            f"Decision mode: {title} — unknown mode index {idx}",
            style={"padding": "2rem", "color": GREY, "fontSize": "1.1rem"},
        )

    # ----------------------------------------------------------
    # c) Dependent dropdown: Promo ROI SKU list
    # ----------------------------------------------------------
    @app.callback(
        Output("promo-sku", "options"),
        Output("promo-sku", "value"),
        Input("promo-retailer", "value"),
        prevent_initial_call=True,
    )
    def update_promo_skus(retailer: str):
        if not retailer:
            return ["All SKUs"], "All SKUs"
        skus = get_promo_skus(retailer)
        options = ["All SKUs"] + skus
        return options, "All SKUs"

    # ----------------------------------------------------------
    # c) Dependent dropdown: Expansion focus SKU list
    # ----------------------------------------------------------
    @app.callback(
        Output("expansion-focus-sku", "options"),
        Output("expansion-focus-sku", "value"),
        Input("expansion-product-line", "value"),
        prevent_initial_call=True,
    )
    def update_expansion_skus(product_line: str):
        if not product_line:
            return [], None
        pairs = get_skus_for_line(product_line)
        options = [{"label": f"{sku} — {name}", "value": sku} for sku, name in pairs]
        value = options[0]["value"] if options else None
        return options, value

    # ----------------------------------------------------------
    # c) Dependent dropdown: Pricing Power scope toggles
    # ----------------------------------------------------------
    @app.callback(
        Output("pricing-line-filter", "style"),
        Output("pricing-sku-filter", "style"),
        Input("pricing-scope", "value"),
        prevent_initial_call=True,
    )
    def toggle_pricing_filters(scope: str):
        show_line = {"display": "block"} if scope == "Product line" else {"display": "none"}
        show_sku = {"display": "block"} if scope == "Specific SKU" else {"display": "none"}
        return show_line, show_sku

    # ----------------------------------------------------------
    # c) Dependent dropdown: Pricing Power product line options
    # ----------------------------------------------------------
    @app.callback(
        Output("pricing-product-line", "options"),
        Output("pricing-product-line", "value"),
        Input("pricing-scope", "value"),
        prevent_initial_call=True,
    )
    def update_pricing_product_lines(scope: str):
        if scope != "Product line":
            return [], None
        lines = get_product_lines()
        value = lines[0] if lines else None
        return lines, value

    # ----------------------------------------------------------
    # c) Dependent dropdown: Pricing Power SKU options
    # ----------------------------------------------------------
    @app.callback(
        Output("pricing-sku", "options"),
        Output("pricing-sku", "value"),
        Input("pricing-retailer", "value"),
        Input("pricing-scope", "value"),
        prevent_initial_call=True,
    )
    def update_pricing_skus(retailer: str, scope: str):
        if scope != "Specific SKU" or not retailer:
            return [], None
        skus = get_promo_skus(retailer)
        value = skus[0] if skus else None
        return skus, value

    # ----------------------------------------------------------
    # f) Threshold defaults: Shelf Defense
    # ----------------------------------------------------------
    @app.callback(
        Output("shelf-threshold", "value"),
        Input("shelf-retailer", "value"),
        prevent_initial_call=True,
    )
    def update_shelf_threshold(retailer: str):
        return RETAILER_THRESHOLDS.get(retailer, 2.0)

    # ----------------------------------------------------------
    # f) Threshold defaults: Pruning
    # ----------------------------------------------------------
    @app.callback(
        Output("pruning-threshold", "value"),
        Input("pruning-retailer", "value"),
        prevent_initial_call=True,
    )
    def update_pruning_threshold(retailer: str):
        return RETAILER_THRESHOLDS.get(retailer, 2.0)

    # ----------------------------------------------------------
    # f2) Sync pitch-retailer with active mode's retailer
    # ----------------------------------------------------------
    @app.callback(
        Output("pitch-retailer", "value"),
        Input("shelf-retailer", "value"),
        Input("prod-retailer", "value"),
        Input("promo-retailer", "value"),
        Input("pruning-retailer", "value"),
        Input("rat-retailer", "value"),
        Input("pricing-retailer", "value"),
        prevent_initial_call=True,
    )
    def sync_pitch_retailer(shelf, prod, promo, pruning, rat, pricing):
        triggered = ctx.triggered_id
        if not isinstance(triggered, str):
            return no_update
        val_map = {
            "shelf-retailer": shelf,
            "prod-retailer": prod,
            "promo-retailer": promo,
            "pruning-retailer": pruning,
            "rat-retailer": rat,
            "pricing-retailer": pricing,
        }
        val = val_map.get(triggered)
        if val and val in PHYSICAL_RETAILERS:
            return val
        return no_update

    # ----------------------------------------------------------
    # g) Pitch export: Excel
    # ----------------------------------------------------------
    @app.callback(
        Output("pitch-excel-download", "data"),
        Input("pitch-excel-btn", "n_clicks"),
        State("pitch-retailer", "value"),
        State("pitch-product-line", "value"),
        prevent_initial_call=True,
    )
    def download_pitch_excel(n_clicks, retailer, product_line):
        if not n_clicks or not retailer:
            return no_update
        product_line = None if product_line == "All" else product_line
        threshold = RETAILER_THRESHOLDS.get(retailer, 2.0)
        try:
            info = build_pitch_excel(retailer, product_line, threshold)
            return dcc.send_bytes(info["content"], info["filename"])
        except Exception:
            import logging
            logging.getLogger("pitch_export").exception("Excel export failed")
            return no_update

    # ----------------------------------------------------------
    # g) Pitch export: PDF
    # ----------------------------------------------------------
    @app.callback(
        Output("pitch-pdf-download", "data"),
        Input("pitch-pdf-btn", "n_clicks"),
        State("pitch-retailer", "value"),
        State("pitch-product-line", "value"),
        prevent_initial_call=True,
    )
    def download_pitch_pdf(n_clicks, retailer, product_line):
        if not n_clicks or not retailer:
            return no_update
        product_line = None if product_line == "All" else product_line
        threshold = RETAILER_THRESHOLDS.get(retailer, 2.0)
        try:
            info = build_pitch_pdf(retailer, product_line, threshold)
            return dcc.send_bytes(info["content"], info["filename"])
        except Exception:
            import logging
            logging.getLogger("pitch_export").exception("PDF export failed")
            return no_update
