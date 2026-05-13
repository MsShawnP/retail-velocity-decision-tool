"""Production Planning decision mode -- Dash layout and callbacks.

Ported from velocity_tool.py render_production_planning() (lines 2082-2221).
Business logic, SQL queries, chart construction, and metric calculations
are IDENTICAL to the original Streamlit version.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback_context, dcc, html, no_update

from charts import apply_hbar_layout
from components import (
    chart_legend,
    dashboard_layout,
    empty_state,
    error_card,
    excel_download_data,
    make_grid,
    metric_card,
    row_count_line,
    status_legend,
)
from constants import (
    GREEN_FAINT,
    GREY,
    GREY_BG,
    NAVY,
    NAVY_MED,
    PRODUCTION_ROW,
    PRODUCTION_STATUS_COLORS,
    RED,
    RED_FAINT,
    TEAL,
    THRESHOLDS,
)
from data import get_latest_week, get_production_data


# ============================================================
# Layout
# ============================================================

def layout(
    retailer: str,
    product_line: str | None,
) -> html.Div:
    """Return the full Dash component tree for Production Planning."""
    latest = get_latest_week()

    try:
        df = get_production_data(retailer, product_line)
    except Exception as exc:
        return error_card(
            "Production Planning query failed",
            f"Could not load production data for {retailer}: {exc}",
        )

    if df.empty:
        msg = f"No SKUs with recent activity at {retailer}"
        if product_line:
            msg += f" in {product_line}"
        return empty_state(msg + ".")

    n_total = len(df)
    n_accel = int((df["status"] == "Accelerating").sum())
    n_decel = int((df["status"] == "Decelerating").sum())
    n_stable = n_total - n_accel - n_decel

    # Headline
    if n_accel > 0:
        headline = (
            f"{n_accel} of {n_total} SKUs are accelerating "
            f"(velocity up >10%) and may stock out without a production increase."
        )
    elif n_decel > 0:
        headline = (
            f"No SKUs are accelerating sharply. "
            f"{n_decel} are decelerating and may risk overstock."
        )
    else:
        headline = f"All {n_total} SKUs are running at stable velocity."

    # Caption
    caption_text = (
        f"Retailer scope: {retailer}  |  Window: last 4 weeks  "
        f"|  Most recent week: {latest}  "
        "|  Forecast adjusted by year-over-year seasonality."
    )

    # Metric totals
    total_units = int(df["weekly_units"].sum())
    total_cases = int(df["weekly_cases"].sum())
    forecast_cases = int(df["forecast_4w_cases"].sum())

    # Forecast explanation
    forecast_explanation = (
        "This forecast uses trailing 4-week velocity adjusted for seasonal "
        "patterns. If the same period last year ran above the annual average, "
        "the forecast adjusts upward — and vice versa. These are production "
        "targets, not historical summaries."
    )

    # Status legend
    accel_pct = THRESHOLDS["production_trend_accel"] * 100
    decel_pct = THRESHOLDS["production_trend_decel"] * 100
    legend_html = (
        f"<b>Status definitions</b> (4-week trend vs prior 4 weeks): "
        f"<b style='color:{TEAL}'>Accelerating</b> = trend &gt; "
        f"{accel_pct:+.2f}% (good — raise production).  "
        f"<b style='color:{RED}'>Decelerating</b> = trend &lt; "
        f"{decel_pct:+.2f}% (bad — consider trimming).  "
        f"<b style='color:{NAVY_MED}'>Stable</b> = trend within "
        f"±{accel_pct:.2f}%."
    )

    # Build display DataFrame
    display_df = pd.DataFrame({
        "SKU":                              df["sku"],
        "Product Name":                     df["product_name"],
        "Product Line":                     df["product_line"],
        "Doors":                            df["doors"].astype(int),
        "Forecasted weekly demand (units)": df["weekly_units"].astype(int),
        "Forecasted weekly demand (cases)": df["weekly_cases"],
        "Next 4-Wk Production Target (cases)": df["forecast_4w_cases"],
        "Trend %":                          df["trend_pct"].round(2),
        "Status":                           df["status"],
    })
    status_order = {"Accelerating": 0, "Decelerating": 1, "Stable": 2}
    display_df = (
        display_df.assign(_o=display_df["Status"].map(status_order))
        .sort_values(["_o", "Forecasted weekly demand (units)"], ascending=[True, False])
        .drop(columns="_o")
        .reset_index(drop=True)
    )

    # AG Grid column defs
    column_defs = [
        {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 110},
        {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
        {"field": "Product Line", "headerName": "Product Line", "sortable": True, "filter": True, "width": 130},
        {"field": "Doors", "headerName": "Doors", "sortable": True, "filter": "agNumberColumnFilter", "width": 80},
        {"field": "Forecasted weekly demand (units)", "headerName": "Weekly Demand (units)", "sortable": True, "filter": "agNumberColumnFilter"},
        {"field": "Forecasted weekly demand (cases)", "headerName": "Weekly Demand (cases)", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
        {"field": "Next 4-Wk Production Target (cases)", "headerName": "4-Wk Target (cases)", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
        {"field": "Trend %", "headerName": "Trend %", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format('+.2f')(params.value) + '%'"}},
        {"field": "Status", "headerName": "Status", "sortable": True, "filter": True, "width": 120},
    ]

    # Row style conditions
    row_style_conditions = [
        {
            "condition": "params.data.Status === 'Accelerating'",
            "style": {"backgroundColor": GREEN_FAINT, "color": TEAL},
        },
        {
            "condition": "params.data.Status === 'Decelerating'",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
        {
            "condition": "params.data.Status === 'Stable'",
            "style": {"backgroundColor": GREY_BG, "color": NAVY_MED},
        },
    ]

    grid = make_grid(
        display_df,
        column_defs=column_defs,
        row_style_conditions=row_style_conditions,
        id="production-grid",
    )

    # Chart: top SKUs by forecasted case demand
    n_show = min(20, len(display_df))
    top = display_df.nlargest(n_show, "Next 4-Wk Production Target (cases)").copy()
    chart_title = f"Top {n_show} SKUs by forecasted case demand for the next 4 weeks"
    chart_caption = (
        "Bars colored teal = accelerating (raise production), red = decelerating "
        "(consider trimming), navy = stable."
    )

    fig = go.Figure()
    for status in ("Accelerating", "Decelerating", "Stable"):
        sub = top[top["Status"] == status]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["SKU"], x=sub["Next 4-Wk Production Target (cases)"], orientation="h",
            marker_color=PRODUCTION_STATUS_COLORS[status],
            text=sub["Next 4-Wk Production Target (cases)"].map(lambda v: f"{v:.2f}"),
            textposition="outside", textfont=dict(size=14, color=NAVY),
            cliponaxis=False,
            customdata=sub[["Product Name", "Trend %", "Doors"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "Next 4-wk cases: %{x:.2f}<br>"
                "Trend: %{customdata[1]:+.2f}%<br>"
                "Doors: %{customdata[2]}<br>"
                f"Status: {status}<extra></extra>"
            ),
        ))
    apply_hbar_layout(
        fig,
        labels=top["SKU"].tolist(),
        height=max(420, 32 * n_show + 120),
        x_title="Forecasted cases for next 4 weeks",
        label_pad_px=180,
        left_margin=200,
    )

    # Excel export filename parts
    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")

    # Assemble the full component tree
    return dashboard_layout(
        header=[
            html.H3(headline, style={"marginBottom": "0.3rem"}),
            html.P(caption_text, style={"color": GREY, "fontSize": "0.85rem", "margin": "0 0 0.5rem"}),
            html.Div(
                [
                    html.Div(metric_card("Weekly demand (units)", f"{total_units:,}"), style={"flex": "1"}),
                    html.Div(metric_card("Weekly demand (cases)", f"{total_cases:,}"), style={"flex": "1"}),
                    html.Div(metric_card("4-wk target (cases)", f"{forecast_cases:,}"), style={"flex": "1"}),
                    html.Div(metric_card("Accelerating SKUs", str(n_accel)), style={"flex": "1"}),
                ],
                style={"display": "flex", "gap": "1rem", "marginBottom": "0.5rem"},
            ),
            status_legend(legend_html),
            row_count_line("SKUs", [
                (n_accel, "Accelerating"),
                (n_decel, "Decelerating"),
                (n_stable, "Stable"),
            ]),
        ],
        grid=grid,
        chart=[
            html.H4(chart_title, style={"marginTop": "0"}),
            html.P(chart_caption, style={"color": GREY, "fontSize": "0.85rem"}),
            chart_legend([
                (TEAL,     f"Accelerating (trend > {accel_pct:+.2f}%)"),
                (RED,      f"Decelerating (trend < {decel_pct:+.2f}%)"),
                (NAVY_MED, f"Stable (±{accel_pct:.2f}%)"),
            ]),
            dcc.Graph(figure=fig, id="production-chart"),
        ],
        footer=[
            html.Button(
                "Export to Excel", id="production-export-btn", n_clicks=0,
                style={"padding": "0.4rem 1.2rem", "cursor": "pointer"},
            ),
            dcc.Download(id="production-download"),
            dcc.Store(
                id="production-table-data",
                data={
                    "records": display_df.to_dict("records"),
                    "filename": f"production_plan_{safe_ret}_{safe_pl}",
                },
            ),
        ],
    )


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register Production Planning decision callbacks."""

    @app.callback(
        Output("production-download", "data"),
        Input("production-export-btn", "n_clicks"),
        Input("production-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_production(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "production-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "Production Plan", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])
