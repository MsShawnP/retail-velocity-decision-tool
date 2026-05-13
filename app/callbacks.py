"""Cinderhaven Velocity Tool -- top-level Dash callbacks.

Central nervous system for the app: filter visibility, the main-content
dispatcher, dependent dropdown chains, story/decision toggling, and
threshold defaults.

All callbacks are registered via ``register_callbacks(app)`` so the module
never touches a module-level app instance.
"""

from __future__ import annotations

from dash import Input, Output, State, ctx, no_update, html

from constants import (
    DECISIONS,
    DECISION_TITLES,
    PHYSICAL_RETAILERS,
    RETAILER_THRESHOLDS,
)
from data import get_promo_skus, get_product_lines, get_skus_for_line
from decisions.shelf_defense import layout as shelf_layout
from decisions.production import layout as production_layout
from decisions.promo_roi import layout as promo_layout
from decisions.expansion import layout as expansion_layout
from decisions.pruning import layout as pruning_layout
from decisions.rationalization import layout as rationalization_layout


# ============================================================
# Mapping: decision index -> filter-group div id
# ============================================================

_FILTER_IDS = [
    "filters-shelf-defense",      # 0 — Shelf Defense
    "filters-production",         # 1 — Production
    "filters-promo",              # 2 — Promo ROI
    "filters-expansion",          # 3 — Expansion
    "filters-pruning",            # 4 — Pruning
    "filters-rationalization",    # 5 — Rationalization
    "filters-launch",             # 6 — Launch Health
    "filters-pricing",            # 7 — Pricing Power
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
        idx = DECISIONS.index(decision) if decision in DECISIONS else 0
        styles = []
        for i in range(len(_FILTER_IDS)):
            if i == idx:
                styles.append({"display": "block"})
            else:
                styles.append({"display": "none"})
        return styles

    # ----------------------------------------------------------
    # b) Dispatcher: single callback that owns main-content
    # ----------------------------------------------------------
    @app.callback(
        Output("main-content", "children"),
        # Global inputs
        Input("decision-picker", "value"),
        Input("view-store", "data"),
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
        decision, view,
        shelf_ret, shelf_thr, shelf_pl,
        prod_ret, prod_pl,
        promo_ret, promo_sku,
        exp_pl, exp_sku, exp_ret,
        prune_ret, prune_thr, prune_pl,
        rat_ret, rat_pl,
        price_ret, price_scope, price_pl, price_sku,
    ):
        # Story mode
        if view == "story":
            return html.Div("Story mode — coming in U6")

        # Determine active mode index
        idx = DECISIONS.index(decision) if decision in DECISIONS else 0

        # Short-circuit: if a filter from a non-active mode triggered
        # this callback, skip the re-render.
        triggered = ctx.triggered_id
        if triggered and triggered not in ("decision-picker", "view-store"):
            active_ids = _MODE_INPUTS.get(idx, set())
            if triggered not in active_ids:
                return no_update

        # Modes 0-2: real layouts (U3)
        if idx == 0:
            return shelf_layout(shelf_ret, shelf_thr, shelf_pl)
        if idx == 1:
            return production_layout(prod_ret, prod_pl)
        if idx == 2:
            return promo_layout(promo_ret, promo_sku)

        # Modes 3-5: real layouts (U4)
        if idx == 3:
            return expansion_layout(exp_pl, exp_sku, exp_ret)
        if idx == 4:
            return pruning_layout(prune_ret, prune_thr, prune_pl)
        if idx == 5:
            return rationalization_layout(rat_ret, rat_pl)

        # Placeholder for U5: remaining decision modules
        title = DECISION_TITLES.get(decision, decision)
        return html.Div(
            f"Decision mode: {title} — coming in U5",
            style={"padding": "2rem", "color": "#636E72", "fontSize": "1.1rem"},
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
    # d) Story toggle: button click -> "story" view
    # ----------------------------------------------------------
    @app.callback(
        Output("view-store", "data", allow_duplicate=True),
        Input("story-entry-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def enter_story(_n_clicks):
        return "story"

    # ----------------------------------------------------------
    # e) Decision picker resets view to "decision"
    # ----------------------------------------------------------
    @app.callback(
        Output("view-store", "data", allow_duplicate=True),
        Input("decision-picker", "value"),
        prevent_initial_call=True,
    )
    def reset_to_decision(_decision):
        return "decision"

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
