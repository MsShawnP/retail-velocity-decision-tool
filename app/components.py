"""Reusable Dash components -- metric cards, legends, grids, downloads.

Each function returns a Dash component tree (html.Div, dbc.Card, etc.)
instead of calling Streamlit's st.* API. The visual style matches the
Cinderhaven brand palette from constants.py.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import pandas as pd
from dash import html

from constants import (
    NAVY_MED,
    RED,
)


# ============================================================
# Number formatting
# ============================================================

def fmt_num(val: float, decimals: int = 2) -> str:
    """Magnitude-aware number formatter for user-facing text.

    Prevents false zeros (0.001 → "<0.01") and adds comma
    grouping for large values (1234 → "1,234.00").
    """
    if pd.isna(val):
        return "—"
    if val == 0:
        return f"0.{'0' * decimals}"
    if 0 < abs(val) < 10 ** -decimals:
        return f"<0.{'0' * (decimals - 1)}1"
    return f"{val:,.{decimals}f}"


# ============================================================
# Metric card (replaces st.metric)
# ============================================================

def metric_card(
    label: str,
    value: str,
    delta: str | None = None,
    delta_color: str | None = None,
) -> html.Div:
    """White card with a label on top, large value, and optional delta line.

    Styled to match the Streamlit st.metric look: white background, subtle
    border + shadow, label in muted grey, value in navy, delta underneath.
    """
    children = [
        html.Div(label, className="mc-label"),
        html.Div(value, className="mc-value"),
    ]
    if delta is not None:
        children.append(
            html.Div(delta, className="mc-delta",
                     style={"color": delta_color or NAVY_MED})
        )
    return html.Div(children, className="metric-card")


# ============================================================
# Chart legend (replaces render_chart_legend)
# ============================================================

def chart_legend(items: list[tuple[str, str]]) -> html.Div:
    """One-line color legend for a chart. Sits just below the chart subtitle.

    items is a list of (color_hex, label) tuples. Renders tiny colored squares
    inline rather than emojis.
    """
    chips = []
    for color, label in items:
        chips.append(
            html.Span(
                [
                    html.Span(className="legend-swatch",
                              style={"background": color}),
                    label,
                ],
                className="legend-chip",
            )
        )
    return html.Div(chips, className="chart-legend")


# ============================================================
# Status legend (replaces render_status_legend)
# ============================================================

def status_legend(children) -> html.Div:
    """Compact muted-grey legend that spells out the bucket cutoffs.

    Accepts either a list of Dash components (html.Span, html.B, str) or
    a plain string. Renders inline without dangerously_allow_html.
    """
    return html.Div(className="status-legend", children=children)


# ============================================================
# Row count line (replaces render_row_count_line)
# ============================================================

def row_count_line(item_label: str, parts: list[tuple[int, str]]) -> html.Div:
    """Small muted-grey line proving the buckets sum to the table total.

    Format: "Showing N items | X bucket1 + Y bucket2 = N total".
    """
    total = sum(n for n, _ in parts)
    parts_text = " + ".join(f"{n} {label}" for n, label in parts)
    return html.Div(
        f"Showing {total} {item_label} | {parts_text} = {total} total",
        className="row-count",
    )


# ============================================================
# Excel download helper (replaces excel_button)
# ============================================================

def excel_download_data(
    df: pd.DataFrame,
    sheet_name: str,
    file_stem: str,
) -> dict[str, Any]:
    """Return a dict with 'content' (base64-encoded bytes) and 'filename'.

    Use with dcc.Download:
        dcc.Download(id="dl"), ...
        @callback(Output("dl", "data"), ...)
        def download(...):
            info = excel_download_data(df, "Sheet1", "export")
            return dcc.send_bytes(info["content"], info["filename"])
    """
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return {
        "content": buf.getvalue(),
        "filename": f"{file_stem}.xlsx",
    }


# ============================================================
# Error card
# ============================================================

def error_card(title: str, message: str) -> dbc.Card:
    """Styled card with a warning for query failures."""
    return dbc.Card(
        dbc.CardBody([
            html.H5(title, style={"color": RED, "fontWeight": "600"}),
            html.P(message, style={"color": NAVY_MED}),
        ]),
        className="error-card",
    )


# ============================================================
# Empty state
# ============================================================

def empty_state(message: str) -> html.Div:
    """Centered message for zero-row results."""
    return html.Div(message, className="empty-state")


# ============================================================
# AG Grid wrapper (replaces st.dataframe)
# ============================================================

def make_grid(
    df: pd.DataFrame,
    column_defs: list[dict] | None = None,
    row_style_conditions: list[dict] | None = None,
    **kwargs: Any,
) -> dag.AgGrid:
    """Wrapper for dash-ag-grid with Cinderhaven defaults.

    Parameters
    ----------
    df : DataFrame
        The data to display.
    column_defs : list[dict], optional
        AG Grid columnDefs. If None, auto-generated from df columns.
    row_style_conditions : list[dict], optional
        AG Grid rowClassRules or getRowStyle conditions.
    **kwargs
        Passed through to dag.AgGrid.
    """
    if column_defs is None:
        column_defs = [
            {"field": col, "headerName": col, "sortable": True, "filter": True}
            for col in df.columns
        ]

    grid_options: dict[str, Any] = {
        "domLayout": "autoHeight",
        "animateRows": True,
        "autoSizeStrategy": {"type": "fitCellContents"},
    }
    if row_style_conditions:
        grid_options["getRowStyle"] = {"styleConditions": row_style_conditions}

    defaults: dict[str, Any] = {
        "rowData": df.to_dict("records"),
        "columnDefs": column_defs,
        "dashGridOptions": grid_options,
        "style": {"width": "100%"},
        "className": "ag-theme-alpine",
    }
    defaults.update(kwargs)
    return dag.AgGrid(**defaults)


def dashboard_layout(
    header: list,
    grid,
    chart: list,
    footer: list | None = None,
) -> html.Div:
    """Two-column dashboard: grid left, chart right, everything in-viewport.

    ``header`` spans full width (headline + metrics).
    ``grid`` fills the left column with its own scrollbar.
    ``chart`` fills the right column — visible without page scrolling.
    ``footer`` spans full width below (export button, stores, downloads).
    """
    return html.Div(
        className="dash-layout",
        children=[
            html.Div(header),
            html.Div(
                className="dash-body",
                children=[
                    html.Div([grid], className="dash-col"),
                    html.Div(chart, className="dash-col--scroll"),
                ],
            ),
            html.Div(footer or [], className="dash-footer"),
        ],
    )
