"""Shelf Defense decision mode -- Dash layout and callbacks.

Ported from velocity_tool.py render_shelf_defense() (lines 1854-1994).
Business logic, SQL queries, chart construction, and metric calculations
are IDENTICAL to the original Streamlit version.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback_context, dcc, html, no_update

from charts import apply_hbar_layout, base_chart_layout, text_annotation
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
    GREY,
    NAVY,
    ORANGE,
    ORANGE_FAINT,
    GREEN_FAINT,
    RED,
    RED_FAINT,
    SHELF_STATUS_COLORS,
    TEAL,
    THRESHOLDS,
)
from data import get_latest_week, get_shelf_defense_data, get_weekly_velocity_trend


# ============================================================
# Classifier (from velocity_tool.py classify_shelf_status)
# ============================================================

def _classify_shelf_status(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    df = df.copy()
    df["trend_pct"] = (df["current_v"] - df["trailing_v"]) / df["trailing_v"] * 100
    warn_mult = THRESHOLDS["shelf_warning_mult"]
    warn_upper = threshold * warn_mult

    def classify(row: pd.Series) -> str:
        c = row["current_v"]
        t = row["trailing_v"]
        if c < threshold:
            return "At Risk"
        if c < warn_upper and pd.notna(t) and t > c:
            return "Warning"
        return "Safe"

    df["status"] = df.apply(classify, axis=1)
    return df


# ============================================================
# Layout
# ============================================================

def layout(
    retailer: str,
    threshold: float,
    product_line: str | None,
) -> html.Div:
    """Return the full Dash component tree for Shelf Defense."""
    latest = get_latest_week()

    try:
        df = get_shelf_defense_data(retailer, product_line)
    except Exception as exc:
        return error_card(
            "Shelf Defense query failed",
            f"Could not load shelf defense data for {retailer}: {exc}",
        )

    if df.empty:
        msg = f"No SKUs with recent activity at {retailer}"
        if product_line:
            msg += f" in {product_line}"
        return empty_state(msg + ".")

    df = _classify_shelf_status(df, threshold)
    n_atrisk = int((df["status"] == "At Risk").sum())
    n_warn = int((df["status"] == "Warning").sum())
    n_safe = int((df["status"] == "Safe").sum())

    # Headline
    if n_atrisk > 0:
        headline = (
            f"{n_atrisk} SKU{'s' if n_atrisk != 1 else ''} below the {retailer} "
            f"delisting threshold of {threshold:.2f} units/store/week."
        )
    elif n_warn > 0:
        headline = (
            f"No SKUs are below the {retailer} threshold yet, but "
            f"{n_warn} are in the warning zone."
        )
    else:
        headline = f"All SKUs are safely above the {retailer} threshold of {threshold:.2f}."

    # Insight
    total = n_atrisk + n_warn + n_safe
    if n_atrisk > 0:
        insight = (
            f"Losing shelf placement on {n_atrisk} SKU{'s' if n_atrisk != 1 else ''} "
            f"shifts that volume to competitors. Another {n_warn} in the warning "
            f"zone could tip with one slow week."
        )
    elif n_warn > 0:
        insight = (
            f"{n_warn} of {total} SKUs are close enough to the threshold "
            f"that a single slow week could trigger a delisting conversation."
        )
    else:
        insight = (
            f"All {total} SKUs are comfortably above threshold — "
            f"focus shelf conversations on expansion rather than defense."
        )

    # Caption
    caption_text = (
        f"Retailer: {retailer}  |  Delisting threshold: "
        f"{threshold:.2f} units/store/week  |  Most recent week: {latest}"
    )

    # Status legend
    warn_mult = THRESHOLDS["shelf_warning_mult"]
    warn_upper = threshold * warn_mult
    legend_html = (
        f"<b>Status definitions:</b> "
        f"<b style='color:{RED}'>At Risk</b> = current velocity below "
        f"{threshold:.2f} (strictly less than).  "
        f"<b style='color:{ORANGE}'>Warning</b> = velocity {threshold:.2f} or "
        f"above, but below {warn_upper:.2f}, <i>and</i> trailing higher than "
        f"current (declining toward threshold).  "
        f"<b style='color:{TEAL}'>Safe</b> = velocity {warn_upper:.2f} or "
        f"above, or in the warning band but not declining."
    )

    # Build display DataFrame
    display_df = pd.DataFrame({
        "SKU":                df["sku"],
        "Product Name":       df["product_name"],
        "Product Line":       df["product_line"],
        "Current Velocity":   df["current_v"].round(2),
        "Trailing Velocity":  df["trailing_v"].round(2),
        "Trend %":            df["trend_pct"].round(2),
        "Threshold":          round(threshold, 2),
        "Status":             df["status"],
    })
    status_order = {"At Risk": 0, "Warning": 1, "Safe": 2}
    display_df = (
        display_df.assign(_o=display_df["Status"].map(status_order))
        .sort_values(["_o", "Current Velocity"])
        .drop(columns="_o")
        .reset_index(drop=True)
    )

    # AG Grid column defs
    column_defs = [
        {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 110},
        {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
        {"field": "Product Line", "headerName": "Product Line", "sortable": True, "filter": True, "width": 130},
        {"field": "Current Velocity", "headerName": "Current Velocity", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
        {"field": "Trailing Velocity", "headerName": "Trailing Velocity", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format('.2f')(params.value)"}},
        {"field": "Trend %", "headerName": "Trend %", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format('+.2f')(params.value) + '%'"}},
        {"field": "Threshold", "headerName": "Threshold", "sortable": True,
         "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
        {"field": "Status", "headerName": "Status", "sortable": True, "filter": True, "width": 100},
    ]

    # Row style conditions
    row_style_conditions = [
        {
            "condition": "params.data.Status === 'At Risk'",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
        {
            "condition": "params.data.Status === 'Warning'",
            "style": {"backgroundColor": ORANGE_FAINT, "color": ORANGE},
        },
        {
            "condition": "params.data.Status === 'Safe'",
            "style": {"backgroundColor": GREEN_FAINT, "color": TEAL},
        },
    ]

    grid = make_grid(
        display_df,
        column_defs=column_defs,
        row_style_conditions=row_style_conditions,
        id="shelf-defense-grid",
    )

    # Chart: weakest SKUs
    n_show = min(15, len(display_df))
    weakest = display_df.nsmallest(n_show, "Current Velocity").copy()
    chart_title = (
        f"The {n_show} weakest SKUs at {retailer}"
        if n_atrisk > 0
        else f"The {n_show} lowest-velocity SKUs at {retailer} (all currently safe)"
    )
    chart_caption = (
        f"Sorted weakest to strongest. Bars to the left of the dashed line "
        f"({threshold:.2f}) are at risk of delisting."
    )

    fig = go.Figure()
    for status in ("At Risk", "Warning", "Safe"):
        sub = weakest[weakest["Status"] == status]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["SKU"], x=sub["Current Velocity"], orientation="h",
            marker_color=SHELF_STATUS_COLORS[status],
            text=sub["Current Velocity"].map(lambda v: f"{v:.2f}"),
            textposition="outside", textfont=dict(size=14, color=NAVY),
            cliponaxis=False,
            customdata=sub[["Product Name", "Trailing Velocity", "Trend %"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "Current: %{x:.2f} units/store/wk<br>"
                "Trailing: %{customdata[1]:.2f} units/store/wk<br>"
                "Trend: %{customdata[2]:+.2f}%<br>"
                f"Status: {status}<extra></extra>"
            ),
        ))
    fig.add_vline(
        x=threshold, line_dash="dash", line_color=GREY, line_width=2,
        annotation=text_annotation(f"Delisting threshold {threshold:.2f}"),
        annotation_position="top",
    )
    apply_hbar_layout(
        fig,
        labels=weakest["SKU"].tolist(),
        height=max(380, 32 * n_show + 120),
        x_title="Units per store per week (last 8 weeks)",
        label_pad_px=180,
        left_margin=200,
    )

    # Velocity trend chart for at-risk + warning SKUs
    trend_chart_elements = []
    watch_skus = df.loc[df["status"].isin(["At Risk", "Warning"]), "sku"].tolist()
    if watch_skus:
        trend_df = get_weekly_velocity_trend(retailer, watch_skus)
        if not trend_df.empty:
            trend_fig = go.Figure()
            status_map = dict(zip(df["sku"], df["status"]))
            for sku in watch_skus:
                s = trend_df[trend_df["sku"] == sku]
                if s.empty:
                    continue
                name = s["product_name"].iloc[0]
                color = SHELF_STATUS_COLORS.get(status_map.get(sku, "Warning"), ORANGE)
                trend_fig.add_trace(go.Scatter(
                    x=s["week_ending"], y=s["avg_velocity"],
                    mode="lines+markers", name=f"{sku} — {name}",
                    line=dict(color=color, width=2),
                    marker=dict(size=5),
                ))
            trend_fig.add_hline(
                y=threshold, line_dash="dash", line_color=GREY, line_width=2,
                annotation_text=f"Threshold {threshold:.2f}",
                annotation_position="top left",
            )
            layout_kw = base_chart_layout(
                height=340, x_title="Week", y_title="Avg units/store/week",
                show_legend=True,
            )
            layout_kw["yaxis"]["autorange"] = True
            layout_kw["legend"] = dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="left", x=0, font=dict(size=11),
            )
            trend_fig.update_layout(**layout_kw)
            trend_chart_elements = [
                html.H4(
                    "Velocity trend — at-risk & warning SKUs",
                    style={"marginTop": "1.5rem"},
                ),
                dcc.Graph(figure=trend_fig, id="shelf-trend-chart"),
            ]

    # Excel export filename parts
    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")

    # Assemble the full component tree
    return dashboard_layout(
        header=[
            html.H3(headline, className="dh-headline"),
            html.P(insight, className="dh-insight"),
            html.P(caption_text, className="dh-caption"),
            html.Div(
                [
                    html.Div(metric_card("At Risk", str(n_atrisk)), className="dh-metric"),
                    html.Div(metric_card("Warning", str(n_warn)), className="dh-metric"),
                    html.Div(metric_card("Safe", str(n_safe)), className="dh-metric"),
                ],
                className="dh-metrics",
            ),
            status_legend(legend_html),
            row_count_line("SKUs", [
                (n_atrisk, "At Risk"),
                (n_warn, "Warning"),
                (n_safe, "Safe"),
            ]),
        ],
        grid=grid,
        chart=[
            html.H4(chart_title, style={"marginTop": "0"}),
            html.P(chart_caption, style={"color": GREY, "fontSize": "0.85rem"}),
            chart_legend([
                (RED,    f"At Risk (<{threshold:.2f})"),
                (ORANGE, f"Warning ({threshold:.2f} ≤ v < {warn_upper:.2f}, declining)"),
                (TEAL,   f"Safe (v ≥ {warn_upper:.2f}, or in band but stable)"),
            ]),
            dcc.Graph(figure=fig, id="shelf-defense-chart"),
        ] + trend_chart_elements,
        footer=[
            html.Button(
                "Export to Excel", id="shelf-defense-export-btn", n_clicks=0,
                className="export-btn",
            ),
            dcc.Download(id="shelf-defense-download"),
            dcc.Store(
                id="shelf-defense-table-data",
                data={
                    "records": display_df.to_dict("records"),
                    "filename": f"shelf_defense_{safe_ret}_{safe_pl}",
                },
            ),
        ],
    )


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register Shelf Defense decision callbacks."""

    @app.callback(
        Output("shelf-defense-download", "data"),
        Input("shelf-defense-export-btn", "n_clicks"),
        Input("shelf-defense-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_shelf_defense(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "shelf-defense-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "Shelf Defense", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])
