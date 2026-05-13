"""Cinderhaven Velocity Tool -- page layout with sidebar and main content.

Sidebar ported from velocity_tool.py lines 4384-4655. Contains the brand
header, decision picker, and eight filter groups (one per decision mode).
Main content area holds a dcc.Loading wrapper around a single div that
the dispatcher callback owns.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

from constants import (
    ALL_PHYSICAL_OR_AGG,
    DECISIONS,
    GREY,
    GREY_LIGHT,
    NAVY,
    NAVY_MED,
    PHYSICAL_RETAILERS,
    RETAILER_THRESHOLDS,
    WHITE,
)
from data import get_product_lines


# ============================================================
# Sidebar helpers
# ============================================================

def _brand_header() -> html.Div:
    """CINDERHAVEN / P R O V I S I O N S / Velocity Tool."""
    return html.Div([
        html.Div(
            "CINDERHAVEN",
            style={
                "fontFamily": "Georgia, serif",
                "fontSize": "1.55rem",
                "fontWeight": "bold",
                "color": NAVY,
                "lineHeight": "1.2",
            },
        ),
        html.Div(
            "P R O V I S I O N S",
            style={
                "fontSize": "0.78rem",
                "letterSpacing": "0.32rem",
                "color": NAVY_MED,
                "marginTop": "0.15rem",
            },
        ),
        html.Div(
            "Velocity Tool",
            style={
                "fontSize": "0.72rem",
                "color": GREY,
                "marginTop": "0.25rem",
            },
        ),
    ], style={"marginBottom": "1.25rem"})


def _filter_dropdown(component_id: str, options: list, value=None,
                     label: str | None = None, **kwargs) -> html.Div:
    """Labelled dropdown used throughout the sidebar filter groups."""
    children = []
    if label:
        children.append(html.Label(
            label,
            style={"fontSize": "0.82rem", "color": NAVY_MED, "marginBottom": "0.2rem"},
        ))
    dd_kwargs = dict(id=component_id, options=options, clearable=False)
    if value is not None:
        dd_kwargs["value"] = value
    elif options:
        # default to first option
        first = options[0]
        dd_kwargs["value"] = first["value"] if isinstance(first, dict) else first
    dd_kwargs.update(kwargs)
    children.append(dcc.Dropdown(**dd_kwargs))
    return html.Div(children, style={"marginBottom": "0.6rem"})


def _caption(text: str) -> html.Div:
    return html.Div(
        text,
        style={"fontSize": "0.75rem", "color": GREY, "marginBottom": "0.5rem",
               "lineHeight": "1.4"},
    )


def _threshold_input(component_id: str, value: float, label: str | None = None) -> html.Div:
    children = []
    if label:
        children.append(html.Label(
            label,
            style={"fontSize": "0.82rem", "color": NAVY_MED, "marginBottom": "0.2rem"},
        ))
    children.append(dbc.Input(
        id=component_id,
        type="number",
        value=value,
        step=0.1,
        min=0,
        style={"marginBottom": "0.6rem"},
    ))
    return html.Div(children)


# ============================================================
# Per-mode filter groups
# ============================================================

def _filters_shelf_defense(product_lines: list[str]) -> html.Div:
    first_retailer = PHYSICAL_RETAILERS[0]
    return html.Div(id="filters-shelf-defense", style={"display": "none"}, children=[
        _filter_dropdown("shelf-retailer", PHYSICAL_RETAILERS, label="Retailer"),
        _threshold_input(
            "shelf-threshold",
            RETAILER_THRESHOLDS[first_retailer],
            label="Delisting threshold (units/store/wk)",
        ),
        _caption(
            "Retailers don't publish this number -- use your buyer "
            "conversations and category reviews to set it."
        ),
        _filter_dropdown("shelf-product-line", ["All"] + product_lines, label="Product Line"),
    ])


def _filters_production(product_lines: list[str]) -> html.Div:
    return html.Div(id="filters-production", style={"display": "none"}, children=[
        _filter_dropdown("prod-retailer", ["All Retailers"] + PHYSICAL_RETAILERS,
                         label="Retailer"),
        _filter_dropdown("prod-product-line", ["All"] + product_lines, label="Product Line"),
    ])


def _filters_promo() -> html.Div:
    return html.Div(id="filters-promo", style={"display": "none"}, children=[
        _filter_dropdown("promo-retailer", ALL_PHYSICAL_OR_AGG, label="Retailer"),
        _filter_dropdown("promo-sku", ["All SKUs"], value="All SKUs", label="SKU"),
    ])


def _filters_expansion(product_lines: list[str]) -> html.Div:
    return html.Div(id="filters-expansion", style={"display": "none"}, children=[
        _filter_dropdown("expansion-product-line", product_lines, label="Product Line"),
        _filter_dropdown("expansion-focus-sku", [], label="Focus SKU",
                         placeholder="Select a product line first"),
        _filter_dropdown("expansion-retailer", ["All Retailers"] + PHYSICAL_RETAILERS,
                         label="Retailer"),
    ])


def _filters_pruning(product_lines: list[str]) -> html.Div:
    first_retailer = PHYSICAL_RETAILERS[0]
    return html.Div(id="filters-pruning", style={"display": "none"}, children=[
        _filter_dropdown("pruning-retailer", PHYSICAL_RETAILERS, label="Retailer"),
        _threshold_input(
            "pruning-threshold",
            RETAILER_THRESHOLDS[first_retailer],
            label="Delisting threshold (units/store/wk)",
        ),
        _caption(
            "Stores with avg velocity below this are candidates for pruning."
        ),
        _filter_dropdown("pruning-product-line", ["All"] + product_lines,
                         label="Product Line"),
    ])


def _filters_rationalization(product_lines: list[str]) -> html.Div:
    return html.Div(id="filters-rationalization", style={"display": "none"}, children=[
        _filter_dropdown("rat-retailer", ["All Retailers"] + PHYSICAL_RETAILERS,
                         label="Retailer"),
        _filter_dropdown("rat-product-line", ["All"] + product_lines, label="Product Line"),
    ])


def _filters_launch() -> html.Div:
    return html.Div(id="filters-launch", style={"display": "none"}, children=[
        _caption("Auto-detects SKUs launched in the last 52 weeks. No filters needed."),
    ])


def _filters_pricing() -> html.Div:
    return html.Div(id="filters-pricing", style={"display": "none"}, children=[
        _filter_dropdown("pricing-retailer", ALL_PHYSICAL_OR_AGG, label="Retailer"),
        dbc.RadioItems(
            id="pricing-scope",
            options=["All SKUs", "Product line", "Specific SKU"],
            value="All SKUs",
            inline=True,
            style={"fontSize": "0.82rem", "marginBottom": "0.6rem"},
        ),
        html.Div(id="pricing-line-filter", style={"display": "none"}, children=[
            _filter_dropdown("pricing-product-line", [], label="Product Line"),
        ]),
        html.Div(id="pricing-sku-filter", style={"display": "none"}, children=[
            _filter_dropdown("pricing-sku", [], label="SKU"),
        ]),
    ])


# ============================================================
# Story entry button + deep dive section
# ============================================================

def _deep_dive_section() -> html.Div:
    return html.Div([
        html.Hr(style={"borderColor": GREY_LIGHT, "margin": "1.25rem 0"}),
        html.Div(
            "DEEP DIVE · 2 MIN",
            style={
                "fontSize": "0.7rem",
                "fontWeight": "600",
                "color": GREY,
                "letterSpacing": "0.05rem",
                "marginBottom": "0.5rem",
            },
        ),
        html.Button(
            "The Charred Scallion Relish problem",
            id="story-entry-btn",
            n_clicks=0,
            style={
                "display": "block",
                "width": "100%",
                "padding": "0.45rem 0.75rem",
                "fontSize": "0.82rem",
                "fontWeight": "600",
                "color": WHITE,
                "backgroundColor": NAVY,
                "border": "none",
                "borderRadius": "999px",
                "cursor": "pointer",
                "marginBottom": "0.5rem",
                "textAlign": "center",
            },
        ),
        _caption(
            "A single-SKU case study that walks through all eight "
            "decisions -- from a Monday-morning sales report to a "
            "board-ready recommendation."
        ),
    ])


# ============================================================
# Sidebar assembly
# ============================================================

def _sidebar() -> html.Div:
    product_lines = get_product_lines()
    return html.Div([
        _brand_header(),
        _caption("Pick a decision you're trying to make, then set the filters below."),
        dcc.Dropdown(
            id="decision-picker",
            options=[{"label": d, "value": d} for d in DECISIONS],
            value=DECISIONS[0],
            clearable=False,
            style={"marginBottom": "1rem"},
        ),
        html.Div(
            "Filters",
            style={
                "fontSize": "0.85rem",
                "fontWeight": "600",
                "color": NAVY_MED,
                "marginBottom": "0.5rem",
            },
        ),
        _filters_shelf_defense(product_lines),
        _filters_production(product_lines),
        _filters_promo(),
        _filters_expansion(product_lines),
        _filters_pruning(product_lines),
        _filters_rationalization(product_lines),
        _filters_launch(),
        _filters_pricing(),
        _deep_dive_section(),
    ], style={
        "padding": "1.25rem 1rem",
        "backgroundColor": WHITE,
        "borderRight": f"1px solid {GREY_LIGHT}",
        "height": "100vh",
        "overflowY": "auto",
    })


# ============================================================
# Main content area
# ============================================================

def _main_content() -> html.Div:
    return html.Div([
        dcc.Store(id="view-store", data="decision"),
        dcc.Store(id="came-from-story", data=False),
        dcc.Store(id="scroll-to-section-5", data=False),
        dcc.Loading(
            id="main-loading",
            type="default",
            delay_show=300,
            delay_hide=200,
            children=html.Div(id="main-content"),
        ),
    ], style={"padding": "1.25rem"})


# ============================================================
# Public entry point
# ============================================================

def create_layout() -> dbc.Container:
    """Return the full-page layout: sidebar (col-3) + main content (col-9)."""
    return dbc.Container(
        fluid=True,
        style={"padding": "0"},
        children=dbc.Row([
            dbc.Col(_sidebar(), width=3, style={"padding": "0"}),
            dbc.Col(_main_content(), width=9, style={"padding": "0"}),
        ], className="g-0"),
    )
