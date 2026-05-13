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
from dash import dcc, html

from constants import (
    GREY,
    GREY_LIGHT,
    NAVY,
    NAVY_MED,
    RED,
    WHITE,
)


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
        html.Div(
            label,
            style={
                "fontSize": "0.85rem",
                "color": GREY,
                "marginBottom": "0.25rem",
            },
        ),
        html.Div(
            value,
            style={
                "fontSize": "1.5rem",
                "fontWeight": "700",
                "color": NAVY,
            },
        ),
    ]
    if delta is not None:
        children.append(
            html.Div(
                delta,
                style={
                    "fontSize": "0.8rem",
                    "color": delta_color or NAVY_MED,
                    "marginTop": "0.15rem",
                },
            )
        )
    return html.Div(
        children,
        style={
            "backgroundColor": WHITE,
            "border": f"1px solid {GREY_LIGHT}",
            "borderRadius": "6px",
            "padding": "0.85rem 1rem 0.75rem 1rem",
            "boxShadow": "0 1px 2px rgba(27, 42, 74, 0.05)",
        },
    )


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
                    html.Span(
                        style={
                            "display": "inline-block",
                            "width": "10px",
                            "height": "10px",
                            "background": color,
                            "borderRadius": "2px",
                            "marginRight": "5px",
                            "verticalAlign": "middle",
                        },
                    ),
                    label,
                ],
                style={"marginRight": "1rem"},
            )
        )
    return html.Div(
        chips,
        style={
            "color": GREY,
            "fontSize": "12px",
            "margin": "-0.4em 0 0.6em 0",
        },
    )


# ============================================================
# Status legend (replaces render_status_legend)
# ============================================================

def status_legend(text: str) -> html.Div:
    """Compact muted-grey legend that spells out the bucket cutoffs.

    Accepts raw HTML in *text* via dcc.Markdown with
    dangerously_allow_html so the same legend strings from the Streamlit
    app work without conversion.
    """
    return html.Div(
        style={
            "color": GREY,
            "fontSize": "12px",
            "lineHeight": "1.5",
            "margin": "0.25em 0 0.6em 0",
        },
        children=dcc.Markdown(text, dangerously_allow_html=True),
    )


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
        style={
            "color": GREY,
            "fontSize": "0.85em",
            "margin": "0.25em 0 0.75em 0",
        },
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
        style={
            "borderLeft": f"4px solid {RED}",
            "marginBottom": "1rem",
        },
    )


# ============================================================
# Empty state
# ============================================================

def empty_state(message: str) -> html.Div:
    """Centered message for zero-row results."""
    return html.Div(
        message,
        style={
            "textAlign": "center",
            "padding": "3rem 1rem",
            "color": GREY,
            "fontSize": "1.1rem",
        },
    )


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
