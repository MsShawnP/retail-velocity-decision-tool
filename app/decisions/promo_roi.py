"""Promo ROI decision mode -- Dash layout and callbacks.

Ported from velocity_tool.py render_promo_roi() (lines 2342-2628).
Business logic, SQL queries, chart construction, and metric calculations
are IDENTICAL to the original Streamlit version.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback_context, dcc, html, no_update

from charts import add_vline_at_date, apply_hbar_layout, text_annotation
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
    CANVAS,
    FONT_SANS,
    GREEN_FAINT,
    GREY,
    GREY_LIGHT,
    INK,
    NAVY_MED,
    ORANGE,
    ORANGE_FAINT,
    RED,
    RED_FAINT,
    TEAL,
    TEXT_SEC,
    THRESHOLDS,
    WHITE,
)
from data import get_promo_roi_data, get_promo_weekly_velocity


# ============================================================
# ROI tier classifier (from velocity_tool.py)
# ============================================================

def _roi_tier(roi: float) -> str:
    roi_strong_pct = THRESHOLDS["roi_strong"] * 100
    if pd.isna(roi):
        return "Marginal ROI"
    if roi >= roi_strong_pct:
        return "Strong ROI"
    if roi >= 0:
        return "Marginal ROI"
    return "Negative ROI"


def _bar_color_for_roi(r: float) -> str:
    roi_strong_pct = THRESHOLDS["roi_strong"] * 100
    if r >= roi_strong_pct:
        return TEAL
    if r >= 0:
        return ORANGE
    return RED


# ============================================================
# Layout
# ============================================================

def layout(
    retailer: str,
    sku_filter: str | None,
) -> html.Div:
    """Return the full Dash component tree for Promo ROI."""
    # Normalize "All SKUs" sentinel to None
    if sku_filter and sku_filter.lower().replace(" ", "") in ("allskus", "all"):
        sku_filter = None

    # Caption
    caption_parts = [f"Retailer: {retailer}"]
    if sku_filter:
        caption_parts.append(f"SKU: {sku_filter}")
    caption_parts.append(
        "Baseline = 4 weeks pre-promo. Post = 3 weeks after end."
        "  Stores with <4 weeks of pre-promo scan data are excluded."
    )
    caption_text = "  |  ".join(caption_parts)

    try:
        df = get_promo_roi_data(retailer, sku_filter)
    except Exception as exc:
        return error_card(
            "Promo ROI query failed",
            f"Could not load promo ROI data for {retailer}: {exc}",
        )

    if df.empty:
        msg = f"No promotions found for {retailer}"
        if sku_filter:
            msg += f" / {sku_filter}"
        return empty_state(msg + ".")

    df = df.dropna(subset=["baseline_v", "promo_v"])
    df = df[df["doors"] > 0]
    if df.empty:
        return empty_state(
            "All promos for this retailer were stranded (no in-window scan data)."
        )

    # Three-tier ROI bucketing
    roi_strong_pct = THRESHOLDS["roi_strong"] * 100

    df["roi_tier"] = df["roi_pct"].apply(_roi_tier)
    n_total = len(df)
    n_strong = int((df["roi_tier"] == "Strong ROI").sum())
    n_marginal = int((df["roi_tier"] == "Marginal ROI").sum())
    n_negative = int((df["roi_tier"] == "Negative ROI").sum())
    avg_lift = df["lift_pct"].mean()
    total_incr = df["incremental_revenue"].sum()
    total_cost = df["promo_cost"].sum()

    # Headline
    if n_strong >= n_marginal + n_negative:
        headline = (
            f"{n_strong} of {n_total} promos at {retailer} delivered "
            f"strong ROI (>{roi_strong_pct:.2f}%)."
        )
    elif n_negative > 0:
        headline = (
            f"Only {n_strong} of {n_total} promos at {retailer} delivered "
            f"strong ROI — {n_marginal} were marginal and {n_negative} lost money."
        )
    else:
        headline = (
            f"{n_strong} strong + {n_marginal} marginal of {n_total} promos "
            f"at {retailer}. None lost money."
        )

    # Insight
    net = total_incr - total_cost
    if n_negative > 0:
        insight = (
            f"These {n_total} promos generated ${total_incr:,.0f} in incremental "
            f"revenue against ${total_cost:,.0f} in spend. "
            f"{n_negative} promo{'s' if n_negative != 1 else ''} lost money — "
            f"consider reallocating that spend to the {n_strong} that delivered."
        )
    else:
        insight = (
            f"${total_incr:,.0f} in incremental revenue on ${total_cost:,.0f} "
            f"in promo spend — a net return of ${net:,.0f}. "
            f"Average lift was {avg_lift:.1f}% across {n_total} promos."
        )

    # Status legend
    legend_children = [
        html.B("ROI"),
        " = (incremental revenue − promo cost) ÷ promo cost × 100. ",
        html.B("Strong", style={"color": TEAL}),
        f" (>{roi_strong_pct:.2f}%) = earned back more than double the spend. ",
        html.B("Marginal", style={"color": ORANGE}),
        f" (0–{roi_strong_pct:.2f}%) = covered costs but modest return. ",
        html.B("Negative", style={"color": RED}),
        " (<0%) = lost money. Baseline = 4 weeks pre-promo at the same retailer.",
    ]

    # Build display DataFrame
    display_df = pd.DataFrame({
        "Promo ID":     df["promo_id"],
        "Start":        df["start_week"],
        "End":          df["end_week"],
        "SKU":          df["sku"],
        "Product Name": df["product_name"],
        "Type":         df["promo_type"],
        "Discount":     (df["discount_depth_pct"] * 100).round(0),
        "Scope":        df["store_scope"],
        "Baseline":     df["baseline_v"].round(2),
        "Promo":        df["promo_v"].round(2),
        "Lift %":       df["lift_pct"].round(2),
        "Dip %":        df["dip_pct"].round(2),
        "Incr. $":      df["incremental_revenue"].round(2),
        "Cost $":       df["promo_cost"].round(2),
        "ROI %":        df["roi_pct"].round(2),
        "Tier":         df["roi_tier"],
    }).reset_index(drop=True)

    # AG Grid column defs
    column_defs = [
        {"field": "Promo ID", "headerName": "Promo ID", "sortable": True, "filter": True, "width": 110},
        {"field": "Start", "headerName": "Start", "sortable": True, "filter": True, "width": 100},
        {"field": "End", "headerName": "End", "sortable": True, "filter": True, "width": 100},
        {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 100},
        {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
        {"field": "Type", "headerName": "Type", "sortable": True, "filter": True, "width": 100},
        {"field": "Discount", "headerName": "Discount", "sortable": True, "filter": "agNumberColumnFilter", "width": 90,
         "valueFormatter": {"function": "d3.format(',.2f')(params.value) + '%'"}},
        {"field": "Scope", "headerName": "Scope", "sortable": True, "filter": True, "width": 90},
        {"field": "Baseline", "headerName": "Baseline", "sortable": True, "filter": "agNumberColumnFilter", "width": 90,
         "valueFormatter": {"function": "d3.format(',.2f')(params.value)"}},
        {"field": "Promo", "headerName": "Promo", "sortable": True, "filter": "agNumberColumnFilter", "width": 80,
         "valueFormatter": {"function": "d3.format(',.2f')(params.value)"}},
        {"field": "Lift %", "headerName": "Lift %", "sortable": True, "filter": "agNumberColumnFilter", "width": 80,
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format('+.2f')(params.value) + '%'"}},
        {"field": "Dip %", "headerName": "Dip %", "sortable": True, "filter": "agNumberColumnFilter", "width": 80,
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format('+.2f')(params.value) + '%'"}},
        {"field": "Incr. $", "headerName": "Incr. $", "sortable": True, "filter": "agNumberColumnFilter", "width": 100,
         "valueFormatter": {"function": "params.value == null ? '—' : '$' + d3.format(',.2f')(params.value)"}},
        {"field": "Cost $", "headerName": "Cost $", "sortable": True, "filter": "agNumberColumnFilter", "width": 100,
         "valueFormatter": {"function": "params.value == null ? '—' : '$' + d3.format(',.2f')(params.value)"}},
        {"field": "ROI %", "headerName": "ROI %", "sortable": True, "filter": "agNumberColumnFilter", "width": 80,
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format('+.2f')(params.value) + '%'"}},
        {"field": "Tier", "headerName": "Tier", "sortable": True, "filter": True, "width": 120},
    ]

    # Row style conditions
    row_style_conditions = [
        {
            "condition": "params.data.Tier === 'Strong ROI'",
            "style": {"backgroundColor": GREEN_FAINT, "color": TEAL},
        },
        {
            "condition": "params.data.Tier === 'Marginal ROI'",
            "style": {"backgroundColor": ORANGE_FAINT, "color": ORANGE},
        },
        {
            "condition": "params.data.Tier === 'Negative ROI'",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
    ]

    grid = make_grid(
        display_df,
        column_defs=column_defs,
        row_style_conditions=row_style_conditions,
        id="promo-roi-grid",
    )

    # Chart: best and worst promos by ROI
    chart_df = display_df.dropna(subset=["ROI %"]).copy()
    chart_df["label"] = (
        chart_df["Promo ID"] + "  ·  " + chart_df["SKU"] + "  ·  " + chart_df["Type"]
    )
    winners = chart_df.nlargest(min(8, len(chart_df)), "ROI %")
    losers = chart_df.nsmallest(min(8, len(chart_df)), "ROI %")
    losers = losers[~losers["Promo ID"].isin(winners["Promo ID"])]
    bars = pd.concat([winners, losers]).sort_values(
        "ROI %", ascending=False
    ).reset_index(drop=True)

    chart_children = []
    if not bars.empty:
        colors = [_bar_color_for_roi(r) for r in bars["ROI %"]]
        bar_tiers = [_roi_tier(r) for r in bars["ROI %"]]
        fig = go.Figure(go.Bar(
            y=bars["label"], x=bars["ROI %"], orientation="h",
            marker_color=colors,
            text=bars["ROI %"].map(lambda v: f"{v:+.0f}%"),
            textposition="outside", textfont=dict(size=12, color=INK),
            cliponaxis=False,
            customdata=list(zip(
                bars["Product Name"],
                bars["Lift %"],
                bars["Incr. $"],
                bars["Cost $"],
                bar_tiers,
            )),
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "ROI: %{x:+.2f}%<br>"
                "Lift: %{customdata[1]:+.2f}%<br>"
                "Incremental revenue: $%{customdata[2]:,.2f}<br>"
                "Promo cost: $%{customdata[3]:,.2f}<br>"
                "Tier: %{customdata[4]}<extra></extra>"
            ),
        ))
        fig.add_vline(x=0, line_color=GREY, line_width=2)
        fig.add_vline(
            x=roi_strong_pct, line_dash="dot", line_color=GREY, line_width=1.5,
            annotation=text_annotation(
                f"Strong/marginal cutoff ({roi_strong_pct:.2f}%)"
            ),
            annotation_position="top",
        )
        apply_hbar_layout(
            fig,
            labels=bars["label"].tolist(),
            height=max(380, 32 * len(bars) + 120),
            x_title="Return on promo spend (%)",
            label_pad_px=150,
            left_margin=170,
        )
        chart_children.append(dcc.Graph(figure=fig, id="promo-roi-chart", responsive=True, style={"width": "100%"}))

    # Promo detail dropdown: list all promos
    df_d = df.copy()
    df_d["label"] = (
        df_d["promo_id"] + "  ·  " + df_d["sku"]
        + "  ·  " + df_d["promo_type"]
        + "  ·  " + df_d["start_week"].astype(str)
    )
    promo_options = [
        {"label": lbl, "value": lbl} for lbl in df_d["label"].tolist()
    ]
    default_promo = df_d["label"].iloc[0] if not df_d.empty else None

    # Excel export filename parts
    safe_ret = retailer.lower().replace(" ", "_")
    safe_sku = (sku_filter or "all").lower()

    # Assemble the full component tree
    return dashboard_layout(
        header=[
            html.H3(headline, className="dh-headline"),
            html.P(insight, className="dh-insight"),
            html.P(caption_text, className="dh-caption"),
            html.Div(
                [
                    html.Div(metric_card("Avg lift", f"{avg_lift:+.2f}%"), className="dh-metric"),
                    html.Div(metric_card("Incremental revenue", f"${total_incr:,.2f}"), className="dh-metric"),
                    html.Div(metric_card("Total promo cost", f"${total_cost:,.2f}"), className="dh-metric"),
                    html.Div(metric_card("Strong ROI promos", f"{n_strong} / {n_total}"), className="dh-metric"),
                ],
                className="dh-metrics",
            ),
            status_legend(legend_children),
            row_count_line("promos", [
                (n_strong, "Strong ROI"),
                (n_marginal, "Marginal ROI"),
                (n_negative, "Negative ROI"),
            ]),
        ],
        grid=grid,
        chart=[
            html.H4("Best and worst promos by return on spend", style={"marginTop": "0"}),
            html.P(
                f"Bars colored teal = strong ROI (>{roi_strong_pct:.2f}%), "
                f"orange = marginal (0–{roi_strong_pct:.2f}%), red = negative.",
                style={"color": GREY, "fontSize": "0.85rem"},
            ),
            chart_legend([
                (TEAL,   f"Strong ROI (>{roi_strong_pct:.2f}%)"),
                (ORANGE, f"Marginal ROI (0–{roi_strong_pct:.2f}%)"),
                (RED,    "Negative ROI (<0%)"),
            ]),
            *chart_children,
            html.H4("Drill into one promo", style={"marginTop": "1rem"}),
            html.P(
                "Pick a promo to see weekly velocity before, during, and after:",
                style={"color": GREY, "fontSize": "0.85rem"},
            ),
            dcc.Dropdown(
                id="promo-detail-select",
                options=promo_options,
                value=default_promo,
                clearable=False,
                style={"marginBottom": "0.5rem"},
            ),
            html.Div(id="promo-detail-content"),
        ],
        footer=[
            html.Button(
                "Export to Excel", id="promo-roi-export-btn", n_clicks=0,
                className="export-btn",
            ),
            dcc.Download(id="promo-roi-download"),
            dcc.Store(
                id="promo-roi-table-data",
                data={
                    "records": display_df.to_dict("records"),
                    "filename": f"promo_roi_{safe_ret}_{safe_sku}",
                },
            ),
        # Store the raw promo data for the detail callback
        dcc.Store(
            id="promo-roi-raw-data",
            data={
                "records": df_d[
                    ["label", "promo_id", "sku", "promo_type", "retailer",
                     "start_week", "end_week", "duration_weeks",
                     "discount_depth_pct", "baseline_v", "lift_pct",
                     "dip_pct", "roi_pct"]
                ].to_dict("records"),
            },
        ),
    ])


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register Promo ROI decision callbacks."""

    # Excel download
    @app.callback(
        Output("promo-roi-download", "data"),
        Input("promo-roi-export-btn", "n_clicks"),
        Input("promo-roi-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_promo_roi(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "promo-roi-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "Promo ROI", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])

    # Promo detail drilldown
    @app.callback(
        Output("promo-detail-content", "children"),
        Input("promo-detail-select", "value"),
        State("promo-roi-raw-data", "data"),
        prevent_initial_call=True,
    )
    def render_promo_detail(selected_label, raw_data):
        if not selected_label or not raw_data:
            return no_update

        records = raw_data["records"]
        # Find the selected promo
        selected = None
        for rec in records:
            if rec["label"] == selected_label:
                selected = rec
                break
        if selected is None:
            return html.P("Could not find the selected promo.", style={"color": GREY})

        retailer = selected["retailer"]
        promo_id = selected["promo_id"]
        sku = selected["sku"]

        try:
            weekly = get_promo_weekly_velocity(promo_id, sku, retailer)
        except Exception:
            return html.P(
                "Could not load weekly velocity for this promo.",
                style={"color": GREY},
            )

        if weekly.empty:
            return html.P(
                "No weekly scan data found for this promo's window.",
                style={"color": GREY},
            )

        lift = selected["lift_pct"]
        dip = selected["dip_pct"]
        roi = selected.get("roi_pct")

        # Color the trend line by ROI verdict
        if roi is None or pd.isna(roi):
            line_color = INK
        elif roi > 0:
            line_color = TEAL
        else:
            line_color = RED

        # Narrative
        lift_val = lift if lift is not None and not pd.isna(lift) else 0.0
        dip_val = dip if dip is not None and not pd.isna(dip) else 0.0
        narrative = (
            f"This {selected['promo_type']} promo on {sku} delivered a "
            f"{lift_val:+.2f}% lift during the promo and a {dip_val:+.2f}% "
            f"swing in the 3 weeks after."
        )

        # Build the weekly velocity line chart
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=weekly["week_ending"], y=weekly["velocity"],
            mode="lines+markers",
            line=dict(color=line_color, width=3),
            marker=dict(size=8, color=line_color),
            hovertemplate="<b>%{x}</b><br>Velocity: %{y:.2f} units/store<extra></extra>",
        ))

        baseline_v = selected.get("baseline_v")
        if baseline_v is not None and not pd.isna(baseline_v):
            fig.add_hline(
                y=baseline_v,
                line_dash="dot", line_color=GREY,
                annotation=text_annotation(f"Pre-promo baseline {baseline_v:.2f}"),
                annotation_position="bottom right",
            )

        add_vline_at_date(
            fig, selected["start_week"], "Promo started",
            color=ORANGE, dash="dash", width=2,
            annotation_position="top left",
        )

        duration = selected.get("duration_weeks", "?")
        discount = selected.get("discount_depth_pct", 0)
        add_vline_at_date(
            fig, selected["end_week"],
            f"Promo ended ({duration}wk · {discount * 100:.2f}% off)",
            color=ORANGE, dash="dash", width=2,
            annotation_position="top right",
        )

        fig.update_layout(
            template="simple_white",
            paper_bgcolor=CANVAS, plot_bgcolor=WHITE,
            height=420,
            margin=dict(l=10, r=10, t=40, b=40),
            yaxis=dict(
                title="Units per store per week",
                title_font=dict(size=14, color=TEXT_SEC),
                tickfont=dict(family=FONT_SANS, size=12, color=TEXT_SEC),
                gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT,
            ),
            xaxis=dict(
                tickfont=dict(family=FONT_SANS, size=12, color=TEXT_SEC),
                gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT,
            ),
            showlegend=False,
            font=dict(family=FONT_SANS, size=14, color=INK),
        )

        return html.Div([
            html.P(narrative, style={"fontWeight": "500"}),
            chart_legend([
                (TEAL, "Positive ROI (made money)"),
                (RED,  "Negative ROI (lost money)"),
            ]),
            dcc.Graph(figure=fig, id="promo-detail-chart", responsive=True, style={"width": "100%"}),
        ])
