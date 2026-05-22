"""Distribution Expansion decision mode -- Dash layout and callbacks.

Ported from velocity_tool.py render_expansion_targeting() (lines 2693-2882).
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
    fmt_num,
    make_grid,
    metric_card,
    row_count_line,
    status_legend,
)
from constants import (
    CHICAGO,
    CHICAGO_LT,
    GREY,
    INK,
    TEAL,
)
from data import get_expansion_data, get_sku_meta


# ============================================================
# Tier colors (from velocity_tool.py)
# ============================================================

EXPANSION_TIER_COLORS = {
    "Strongest":         TEAL,
    "Solid":             CHICAGO,
    "Worth considering": CHICAGO_LT,
}


# ============================================================
# Layout
# ============================================================

def layout(
    product_line: str | None,
    focus_sku: str | None,
    retailer: str | None,
) -> html.Div:
    """Return the full Dash component tree for Distribution Expansion."""
    if not focus_sku:
        return empty_state("Select a product line and focus SKU to find expansion opportunities.")

    try:
        sku_meta = get_sku_meta(focus_sku)
    except Exception as exc:
        return error_card(
            "Expansion metadata lookup failed",
            f"Could not load SKU metadata for {focus_sku}: {exc}",
        )

    if not sku_meta:
        return empty_state(f"Selected SKU {focus_sku} not found.")

    product_name, sku_product_line = sku_meta
    ret_label = retailer if retailer and retailer != "All Retailers" else "all retailers"

    try:
        df = get_expansion_data(focus_sku, retailer)
    except Exception as exc:
        return error_card(
            "Expansion query failed",
            f"Could not load expansion data for {focus_sku} at {ret_label}: {exc}",
        )

    # Caption
    caption_text = (
        f"Focus SKU: {focus_sku} — {product_name}  |  "
        f"Product line: {sku_product_line}  |  Retailer scope: {ret_label}"
    )

    if df.empty:
        return html.Div([
            html.P(caption_text, style={"color": GREY, "fontSize": "0.85rem"}),
            empty_state(
                "No expansion opportunities found — either this SKU is already in every "
                "candidate store, or no peer SKUs in the same product line have recent activity."
            ),
        ])

    n_opps = len(df)

    # Metric cards
    top_score = df["score"].iloc[0]
    avg_score = df["score"].mean()

    is_all_retailers = (retailer is None) or (retailer == "All Retailers")
    if is_all_retailers:
        retailer_avg = (
            df.groupby("retailer")["score"].mean().sort_values(ascending=False)
        )
        third_label = "Strongest retailer"
        third_value = retailer_avg.index[0]
    else:
        tied = df[df["score"] == top_score]
        n_tied = len(tied)
        if n_tied == 1:
            third_label = "Top store"
            third_value = tied["store_id"].iloc[0]
        else:
            third_label = "Top stores (tied)"
            third_value = f"{n_tied} stores at {fmt_num(top_score)}"

    # Tier boundaries derived from the SCORE RANGE
    score_min = float(df["score"].min())
    score_max = float(df["score"].max())
    score_span = max(score_max - score_min, 1e-9)
    solid_floor = score_min + score_span / 3.0
    strongest_floor = score_min + 2.0 * score_span / 3.0

    def _tier_for_score(s: float) -> str:
        if s >= strongest_floor:
            return "Strongest"
        if s >= solid_floor:
            return "Solid"
        return "Worth considering"

    # Build display DataFrame (top 30)
    show = df.head(30).copy().reset_index(drop=True)
    show["Strength"] = show["score"].apply(_tier_for_score)

    display_df = pd.DataFrame({
        "Store ID":               show["store_id"],
        "Retailer":               show["retailer"],
        "Region":                 show["region"],
        "State":                  show["state"],
        "Volume Tier":            show["volume_tier"],
        "Strength":               show["Strength"],
        "Similar SKUs Already There": show["n_similar"].astype(int),
        "Their Avg Velocity":     show["avg_velocity"],
        "Expansion Score":        show["score"],
    })

    # Bucket by retailer category for row count line
    def _ret_cat(r: str) -> str:
        if r in ("Walmart", "Costco", "Whole Foods", "Kroger", "Sprouts"):
            return r
        return "Regional"
    cat_counts = show["retailer"].map(_ret_cat).value_counts()
    bucket_parts = [
        (int(cat_counts.get(c, 0)), c)
        for c in ("Walmart", "Costco", "Whole Foods", "Kroger", "Sprouts", "Regional")
        if cat_counts.get(c, 0) > 0
    ]

    # AG Grid column defs
    column_defs = [
        {"field": "Store ID", "headerName": "Store ID", "sortable": True, "filter": True, "width": 120},
        {"field": "Retailer", "headerName": "Retailer", "sortable": True, "filter": True, "width": 120},
        {"field": "Region", "headerName": "Region", "sortable": True, "filter": True, "width": 110},
        {"field": "State", "headerName": "State", "sortable": True, "filter": True, "width": 80},
        {"field": "Volume Tier", "headerName": "Volume Tier", "sortable": True, "filter": True, "width": 110},
        {"field": "Strength", "headerName": "Strength", "sortable": True, "filter": True, "width": 140,
         "cellStyle": {"styleConditions": [
             {"condition": "params.value === 'Strongest'", "style": {"color": TEAL, "fontWeight": "700"}},
             {"condition": "params.value === 'Solid'", "style": {"color": CHICAGO, "fontWeight": "700"}},
             {"condition": "params.value === 'Worth considering'", "style": {"color": CHICAGO_LT, "fontWeight": "700"}},
         ]}},
        {"field": "Similar SKUs Already There", "headerName": "Similar SKUs Already There",
         "sortable": True, "filter": "agNumberColumnFilter", "width": 200},
        {"field": "Their Avg Velocity", "headerName": "Their Avg Velocity",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format(',.2f')(params.value)"}},
        {"field": "Expansion Score", "headerName": "Expansion Score",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format(',.2f')(params.value)"}},
    ]

    grid = make_grid(
        display_df,
        column_defs=column_defs,
        id="expansion-grid",
    )

    # Chart: top 15 by expansion score
    n_show = min(15, len(df))
    top = df.head(n_show).copy().reset_index(drop=True)
    top["label"] = top["store_id"] + "  ·  " + top["retailer"]
    top["tier"] = top["score"].apply(_tier_for_score)

    chart_title = f"Top {n_show} stores ranked by expansion score"
    chart_caption = (
        "Score = peer-SKU avg velocity at that store × volume-tier multiplier "
        "(A=1.3, B=1.0, C=0.7)."
    )

    fig = go.Figure()
    for tier_name in ("Strongest", "Solid", "Worth considering"):
        sub = top[top["tier"] == tier_name]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["label"], x=sub["score"], orientation="h",
            marker_color=EXPANSION_TIER_COLORS[tier_name],
            text=sub["score"].map(lambda v: f"{v:.1f}"),
            textposition="outside", textfont=dict(size=12, color=INK),
            cliponaxis=False,
            customdata=sub[["retailer", "n_similar", "avg_velocity", "volume_tier"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>Retailer: %{customdata[0]}<br>"
                "Score: %{x:.2f}<br>"
                "Peer SKUs: %{customdata[1]}<br>"
                "Peer velocity: %{customdata[2]:.2f}<br>"
                "Volume tier: %{customdata[3]}<br>"
                f"Strength: {tier_name}<extra></extra>"
            ),
        ))

    apply_hbar_layout(
        fig,
        labels=top["label"].tolist(),
        height=max(420, 32 * n_show + 120),
        x_title="Expansion score (peer velocity × tier multiplier)",
        x_pad_pct=0.30,
    )
    fig.update_yaxes(categoryorder="array", categoryarray=top["label"].tolist())

    # Excel export filename parts
    safe_sku = focus_sku.lower()
    safe_ret = (retailer or "all").lower().replace(" ", "_")

    # Headline
    headline = (
        f"{n_opps} stores carry other {sku_product_line} but not "
        f"{product_name} yet — here are the strongest fits."
    )

    n_strongest = int((df["score"] >= strongest_floor).sum())
    insight = (
        f"{n_strongest} of {n_opps} opportunities score in the top tier. "
        f"Prioritize stores where peer SKUs already perform — "
        f"those buyers have proven category demand."
    )

    return dashboard_layout(
        header=[
            html.H3(headline, className="dh-headline"),
            html.P(insight, className="dh-insight"),
            html.P(caption_text, className="dh-caption"),
            html.Div(
                [
                    html.Div(metric_card("Top opportunity score", fmt_num(top_score)), className="dh-metric"),
                    html.Div(metric_card("Average score", fmt_num(avg_score)), className="dh-metric"),
                    html.Div(metric_card(third_label, str(third_value)), className="dh-metric"),
                ],
                className="dh-metrics",
            ),
            status_legend([
                html.B("Score"),
                " = average velocity of peer SKUs (same product line, "
                "already on shelf at that store) × volume-tier multiplier "
                "(A = 1.3, B = 1.0, C = 0.7). Higher score = stronger expansion fit. "
                "Showing top 30 of all qualifying stores.",
            ]),
            row_count_line("stores", bucket_parts),
        ],
        grid=grid,
        chart=[
            html.H4(chart_title, style={"marginTop": "0"}),
            html.P(chart_caption, style={"color": GREY, "fontSize": "0.85rem"}),
            chart_legend([
                (TEAL,     f"Strongest (score ≥ {fmt_num(strongest_floor)})"),
                (CHICAGO,    f"Solid ({fmt_num(solid_floor)}–{fmt_num(strongest_floor)})"),
                (CHICAGO_LT, f"Worth considering (< {fmt_num(solid_floor)})"),
            ]),
            dcc.Graph(figure=fig, id="expansion-chart", responsive=True, style={"width": "100%"}),
        ],
        footer=[
            html.Button(
                "Export to Excel", id="expansion-export-btn", n_clicks=0,
                className="export-btn",
            ),
            dcc.Download(id="expansion-download"),
            dcc.Store(
                id="expansion-table-data",
                data={
                    "records": display_df.to_dict("records"),
                    "filename": f"expansion_{safe_sku}_{safe_ret}",
                },
            ),
        ],
    )


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register Distribution Expansion decision callbacks."""

    @app.callback(
        Output("expansion-download", "data"),
        Input("expansion-export-btn", "n_clicks"),
        Input("expansion-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_expansion(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "expansion-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "Expansion Targets", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])
