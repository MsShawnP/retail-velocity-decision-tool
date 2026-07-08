"""Cinderhaven Velocity Tool -- page layout with sidebar and main content.

Sidebar contains the brand header, decision picker, and filter groups
(one per decision mode). Main content area holds a dcc.Loading wrapper
around a single div that the dispatcher callback owns.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

from constants import (
    ALL_PHYSICAL_OR_AGG,
    DECISIONS,
    PHYSICAL_RETAILERS,
    PORTFOLIO_HEALTH,
    RETAILER_THRESHOLDS,
)
from data import get_product_lines, get_skus_for_line


# ============================================================
# Sidebar helpers
# ============================================================

def _brand_header() -> html.Div:
    """Cinderhaven Provisions / Velocity Tool — Lailara brand header."""
    return html.Div([
        html.Div("Cinderhaven", className="brand-name"),
        html.Div("PROVISIONS", className="brand-sub"),
        html.Div("Velocity Tool", className="brand-tool"),
    ], style={"marginBottom": "1.25rem"})


def _filter_dropdown(component_id: str, options: list, value=None,
                     label: str | None = None, **kwargs) -> html.Div:
    """Labelled dropdown used throughout the sidebar filter groups."""
    children = []
    if label:
        children.append(html.Label(label, className="sidebar-label"))
    dd_kwargs = dict(id=component_id, options=options, clearable=False)
    if value is not None:
        dd_kwargs["value"] = value
    elif options:
        first = options[0]
        dd_kwargs["value"] = first["value"] if isinstance(first, dict) else first
    dd_kwargs.update(kwargs)
    children.append(dcc.Dropdown(**dd_kwargs))
    return html.Div(children, style={"marginBottom": "0.6rem"})


def _caption(text: str) -> html.Div:
    return html.Div(text, className="sidebar-caption")


def _threshold_input(component_id: str, value: float, label: str | None = None) -> html.Div:
    children = []
    if label:
        children.append(html.Label(label, className="sidebar-label"))
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
            "Retailers don't publish this number — use your buyer "
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
    initial_skus = []
    if product_lines:
        pairs = get_skus_for_line(product_lines[0])
        initial_skus = [{"label": f"{sku} — {name}", "value": sku} for sku, name in pairs]
    return html.Div(id="filters-expansion", style={"display": "none"}, children=[
        _filter_dropdown("expansion-product-line", product_lines, label="Product Line"),
        _filter_dropdown("expansion-focus-sku", initial_skus, label="Focus SKU",
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
        _filter_dropdown("rat-retailer", PHYSICAL_RETAILERS,
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


def _filters_data_quality() -> html.Div:
    return html.Div(
        id="filters-data-quality",
        style={"display": "none"},
        children=[
            _caption(
                "Automated data contract checks — verifies the schema "
                "and coverage assumptions every decision mode depends on."
            ),
        ],
    )


# ============================================================
# Pitch export section
# ============================================================

def _pitch_export_section(product_lines: list[str]) -> html.Div:
    return html.Div([
        html.Hr(className="sidebar-divider"),
        html.Div("PITCH EXPORT", className="sidebar-section-tag"),
        _filter_dropdown("pitch-retailer", PHYSICAL_RETAILERS, label="Retailer"),
        _filter_dropdown("pitch-product-line", ["All"] + product_lines, label="Product Line"),
        html.Div([
            html.Button("Excel", id="pitch-excel-btn", n_clicks=0, className="pitch-btn"),
            html.Button("PDF", id="pitch-pdf-btn", n_clicks=0,
                        className="pitch-btn pitch-btn--right"),
        ], style={"marginTop": "0.4rem"}),
        _caption(
            "Bundles Shelf Defense, Production Planning, SKU Rationalization, "
            "and Launch Health into a buyer-ready document."
        ),
        dcc.Download(id="pitch-excel-download"),
        dcc.Download(id="pitch-pdf-download"),
    ])


# ============================================================
# Sidebar assembly
# ============================================================

def _filters_portfolio() -> html.Div:
    return html.Div(
        id="filters-portfolio",
        children=[
            _caption(
                "Portfolio-wide overview. Select a decision mode "
                "above to drill into a specific area."
            ),
        ],
    )


def _sidebar() -> html.Div:
    product_lines = get_product_lines()
    options = (
        [{"label": PORTFOLIO_HEALTH, "value": PORTFOLIO_HEALTH}]
        + [{"label": d, "value": d} for d in DECISIONS]
    )
    return html.Div([
        _brand_header(),
        html.Button([
            html.Span(
                html.Img(
                    src="/assets/menu.svg",
                    style={"width": "18px", "height": "18px", "verticalAlign": "middle"},
                ),
                style={"marginRight": "0.4rem"},
            ),
            "Show Filters & Navigation",
        ],
            id="sidebar-toggle",
            n_clicks=0,
            className="sidebar-toggle",
        ),
        dbc.Collapse(
            id="sidebar-collapse",
            is_open=False,
            children=[
                _caption("Start with the portfolio overview, or pick a decision to drill in."),
                dcc.Dropdown(
                    id="decision-picker",
                    options=options,
                    value=PORTFOLIO_HEALTH,
                    clearable=False,
                    style={"marginBottom": "1rem"},
                ),
                html.Div("Filters", className="sidebar-section-title"),
                _filters_portfolio(),
                _filters_shelf_defense(product_lines),
                _filters_production(product_lines),
                _filters_promo(),
                _filters_expansion(product_lines),
                _filters_pruning(product_lines),
                _filters_rationalization(product_lines),
                _filters_launch(),
                _filters_pricing(),
                _filters_data_quality(),
                _pitch_export_section(product_lines),
            ],
        ),
    ], className="sidebar")


# ============================================================
# Main content area
# ============================================================

def _main_content() -> html.Div:
    return html.Div([
        html.Div([
            html.H1("Retail Velocity Decision Tool", className="hero-title"),
            html.P(
                "Velocity is units sold per store per week — the number a retailer "
                "watches to decide whether a SKU keeps its shelf space or gets "
                "delisted. Each mode below turns Cinderhaven's scan data into that call.",
                className="hero-sub",
            ),
        ], className="hero"),
        dcc.Loading(
            id="main-loading",
            type="default",
            delay_show=300,
            delay_hide=200,
            children=html.Div(id="main-content"),
        ),
    ], className="main-content", style={"padding": "1.25rem"})


# ============================================================
# Public entry point
# ============================================================

def create_layout() -> dbc.Container:
    """Return the full-page layout: sidebar (col-3) + main content (col-9)."""
    return dbc.Container(
        fluid=True,
        style={"padding": "0"},
        children=dbc.Row([
            dbc.Col(_sidebar(), xs=12, md=3, style={"padding": "0"}),
            dbc.Col(_main_content(), xs=12, md=9, style={"padding": "0"}),
        ], className="g-0"),
    )
