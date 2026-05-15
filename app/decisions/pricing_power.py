"""Pricing Power decision mode -- Dash layout and callbacks.

Ported from velocity_tool.py render_pricing_power() (lines 4107-4344).
Business logic, SQL queries, chart construction, and metric calculations
are IDENTICAL to the original Streamlit version.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback_context, dcc, html, no_update

from charts import apply_hbar_layout, text_annotation
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
    DARK_RED,
    DARK_RED_FAINT,
    GREY,
    GREEN_FAINT,
    NAVY,
    ORANGE,
    ORANGE_FAINT,
    RED,
    RED_FAINT,
    TEAL,
    THRESHOLDS,
    WHITE,
)
from data import get_pricing_data


# ============================================================
# Verdict classification (from velocity_tool.py render_pricing_power)
# ============================================================

VERDICT_COLORS = {
    "Promote again":      TEAL,
    "Promote cautiously": ORANGE,
    "Stop promoting":     RED,
    "Promo backfired":    DARK_RED,
}

VERDICT_ROW_BG = {
    "Promote again":      GREEN_FAINT,
    "Promote cautiously": ORANGE_FAINT,
    "Stop promoting":     RED_FAINT,
    "Promo backfired":    DARK_RED_FAINT,
}


def _verdict(row: pd.Series) -> str:
    """Single classification combining elasticity sign with recovery tier."""
    if pd.notna(row["elasticity"]) and row["elasticity"] < 0:
        return "Promo backfired"
    return {
        "Full Recovery":    "Promote again",
        "Partial Recovery": "Promote cautiously",
        "Slow Recovery":    "Stop promoting",
    }.get(row["recovery_status"], "Stop promoting")


# ============================================================
# Layout
# ============================================================

def layout(
    retailer: str,
    scope: str | None,
    product_line: str | None,
    sku_filter: str | None,
) -> html.Div:
    """Return the full Dash component tree for Pricing Power."""
    # Determine effective filters based on scope
    effective_pl = product_line if scope == "Product line" else None
    effective_sku = sku_filter if scope == "Specific SKU" else None

    try:
        df = get_pricing_data(retailer, effective_sku, effective_pl)
    except Exception as exc:
        return error_card(
            "Pricing Power query failed",
            f"Could not load pricing data for {retailer}: {exc}",
        )

    if df.empty:
        msg = f"No SKUs with valid baseline + promo data at {retailer}"
        if effective_sku:
            msg += f" / {effective_sku}"
        if effective_pl:
            msg += f" / {effective_pl}"
        return empty_state(msg + ".")

    # Apply verdict classification
    df["verdict"] = df.apply(_verdict, axis=1)

    n_total = len(df)
    high_sensitivity = df[df["elasticity"] > 5.0]
    low_sensitivity = df[(df["elasticity"] >= 0) & (df["elasticity"] <= 1.5)]

    # Headline
    if len(high_sensitivity) > 0:
        headline = (
            f"{len(high_sensitivity)} of {n_total} SKUs show high price sensitivity "
            f"(elasticity > 5) — these benefit most from promotions. "
            f"{len(low_sensitivity)} show low sensitivity and may have pricing power "
            f"to raise margins."
        )
    else:
        headline = (
            f"Across {n_total} SKUs at {retailer}, "
            f"{len(low_sensitivity)} show low price sensitivity — discounts barely move "
            f"velocity, suggesting room to raise margins."
        )

    # Caption
    caption_parts = [f"Retailer: {retailer}"]
    if effective_sku:
        caption_parts.append(f"SKU: {effective_sku}")
    if effective_pl:
        caption_parts.append(f"Product line: {effective_pl}")
    caption_parts.append(
        "Elasticity = (% velocity lift) / (% discount depth). Higher = more price-sensitive."
    )
    caption_text = "  |  ".join(caption_parts)

    # Metrics
    avg_elast = df["elasticity"].mean()
    avg_disc = df["avg_discount"].mean() * 100
    n_promote_again = int((df["verdict"] == "Promote again").sum())
    n_cautious = int((df["verdict"] == "Promote cautiously").sum())
    n_stop = int((df["verdict"] == "Stop promoting").sum())
    n_backfired = int((df["verdict"] == "Promo backfired").sum())

    # Status legend
    full_pct = THRESHOLDS["pricing_full_recovery"] * 100
    slow_pct = THRESHOLDS["pricing_slow_recovery"] * 100
    legend_html = (
        f"<b>Verdict</b> combines elasticity (did the promo lift velocity?) "
        f"with post-promo recovery (did the lift stick?):  "
        f"<b style='color:{TEAL}'>Promote again</b> = positive lift + recovery "
        f"≥ {full_pct:.2f}%.  "
        f"<b style='color:{ORANGE}'>Promote cautiously</b> = positive lift + "
        f"recovery {slow_pct:.2f}–{full_pct:.2f}% (some sales borrowed).  "
        f"<b style='color:{RED}'>Stop promoting</b> = positive lift + recovery "
        f"&lt; {slow_pct:.2f}% (shoppers learned to wait — net negative).  "
        f"<b style='color:{DARK_RED}'>Promo backfired</b> = elasticity &lt; 0, "
        f"velocity dropped during the promo (overrides recovery)."
    )

    # Build display DataFrame
    display_df = pd.DataFrame({
        "SKU":            df["sku"],
        "Product Name":   df["product_name"],
        "Product Line":   df["product_line"],
        "Baseline Vel":   df["baseline_v"].round(2),
        "Avg Promo Vel":  df["promo_v"].round(2),
        "Avg Discount %": (df["avg_discount"] * 100).round(0),
        "# Promos":       df["n_promos"].astype(int),
        "Elasticity":     df["elasticity"].round(2),
        "Outcome":        df["verdict"],
    })

    # AG Grid column defs
    column_defs = [
        {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 110},
        {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
        {"field": "Product Line", "headerName": "Product Line", "sortable": True, "filter": True, "width": 130},
        {"field": "Baseline Vel", "headerName": "Baseline Vel", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
        {"field": "Avg Promo Vel", "headerName": "Avg Promo Vel", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
        {"field": "Avg Discount %", "headerName": "Avg Discount %", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format('.2f')(params.value) + '%'"}},
        {"field": "# Promos", "headerName": "# Promos", "sortable": True, "filter": "agNumberColumnFilter", "width": 100},
        {"field": "Elasticity", "headerName": "Elasticity", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format('+.2f')(params.value)"}},
        {"field": "Outcome", "headerName": "Outcome", "sortable": True, "filter": True, "width": 150},
    ]

    # Row style conditions
    row_style_conditions = [
        {
            "condition": "params.data.Outcome === 'Promote again'",
            "style": {"backgroundColor": GREEN_FAINT, "color": TEAL},
        },
        {
            "condition": "params.data.Outcome === 'Promote cautiously'",
            "style": {"backgroundColor": ORANGE_FAINT, "color": ORANGE},
        },
        {
            "condition": "params.data.Outcome === 'Stop promoting'",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
        {
            "condition": "params.data.Outcome === 'Promo backfired'",
            "style": {"backgroundColor": DARK_RED_FAINT, "color": DARK_RED},
        },
    ]

    grid = make_grid(
        display_df,
        column_defs=column_defs,
        row_style_conditions=row_style_conditions,
        id="pricing-power-grid",
    )

    # Chart: verdict bar chart
    n_show = min(12, len(df))
    n_neg_avail = int((df["elasticity"] < 0).sum())
    n_pos_avail = int((df["elasticity"] >= 0).sum())
    target_neg = min(n_show // 3, n_neg_avail)
    target_pos = min(n_show - target_neg, n_pos_avail)
    target_neg = min(n_show - target_pos, n_neg_avail)

    pos_part = df[df["elasticity"] >= 0].nlargest(target_pos, "elasticity")
    neg_part = df[df["elasticity"] < 0].nsmallest(target_neg, "elasticity")
    chart_top = (
        pd.concat([pos_part, neg_part])
        .sort_values("elasticity", ascending=False)
        .reset_index(drop=True)
    )
    chart_top["label"] = (
        chart_top["sku"] + "  ·  " + chart_top["product_name"].str.slice(0, 26)
    )
    chart_top["recovery_pct"] = chart_top["recovery_ratio"] * 100
    chart_top["avg_disc_pct"] = chart_top["avg_discount"] * 100
    chart_top["bar_color"] = chart_top["verdict"].map(VERDICT_COLORS)
    chart_top["bar_pattern"] = [
        "/" if v == "Promo backfired" else "" for v in chart_top["verdict"]
    ]
    top_labels = chart_top["label"].tolist()

    chart_title = "Should you run this promotion again?"
    chart_caption = (
        "Bar length = how much velocity responds to discounts.  "
        "Color = whether the promotion is worth repeating."
    )

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=chart_top["label"],
        x=chart_top["elasticity"],
        orientation="h",
        marker=dict(
            color=chart_top["bar_color"].tolist(),
            pattern=dict(shape=chart_top["bar_pattern"].tolist()),
        ),
        text=chart_top["verdict"].tolist(),
        textposition="auto",
        insidetextfont=dict(size=14, color=WHITE),
        outsidetextfont=dict(size=14, color=NAVY),
        cliponaxis=False,
        customdata=list(zip(
            chart_top["avg_disc_pct"],
            chart_top["baseline_v"],
            chart_top["promo_v"],
            chart_top["post_v"],
            chart_top["recovery_pct"],
            chart_top["verdict"],
        )),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Elasticity: %{x:+.2f}<br>"
            "Avg discount: %{customdata[0]:.2f}%<br>"
            "Baseline: %{customdata[1]:.2f}<br>"
            "On promo: %{customdata[2]:.2f}<br>"
            "Post-promo: %{customdata[3]:.2f}<br>"
            "Recovery: %{customdata[4]:.2f}%<br>"
            "Verdict: %{customdata[5]}<extra></extra>"
        ),
    ))
    fig.add_vline(
        x=0, line_color=GREY, line_width=1.5,
        annotation=text_annotation("No effect"),
        annotation_position="top",
    )
    apply_hbar_layout(
        fig,
        labels=top_labels,
        height=max(420, 38 * n_show + 120),
        x_title="Elasticity (% lift per 1% of discount — negative means velocity dropped)",
        label_pad_px=320,
        left_margin=340,
    )
    fig.update_yaxes(categoryorder="array", categoryarray=top_labels)

    # Excel export filename parts
    safe_ret = retailer.lower().replace(" ", "_")
    safe_scope = (effective_sku or effective_pl or "all").lower().replace(" ", "_")

    # Assemble the full component tree
    return dashboard_layout(
        header=[
            html.H3(headline, className="dh-headline"),
            html.P(caption_text, className="dh-caption"),
            html.Div(
                [
                    html.Div(metric_card("Avg Elasticity", f"{avg_elast:.2f}"), className="dh-metric"),
                    html.Div(metric_card("Avg Discount", f"{avg_disc:.2f}%"), className="dh-metric"),
                    html.Div(metric_card("Promote-again SKUs", str(n_promote_again)), className="dh-metric"),
                    html.Div(metric_card("Backfired Promos", str(n_backfired)), className="dh-metric"),
                ],
                className="dh-metrics",
            ),
            status_legend(legend_html),
            row_count_line("SKUs", [
                (n_promote_again, "Promote again"),
                (n_cautious, "Promote cautiously"),
                (n_stop, "Stop promoting"),
                (n_backfired, "Promo backfired"),
            ]),
        ],
        grid=grid,
        chart=[
            html.H4(chart_title, style={"marginTop": "0"}),
            html.P(chart_caption, style={"color": GREY, "fontSize": "0.85rem"}),
            chart_legend([
                (TEAL,     "Promote again (lift + full recovery)"),
                (ORANGE,   "Promote cautiously (lift + partial recovery)"),
                (RED,      "Stop promoting (lift + slow recovery)"),
                (DARK_RED, "Promo backfired (velocity dropped)"),
            ]),
            dcc.Graph(figure=fig, id="pricing-power-chart"),
            html.Div(
                "Negative elasticity can indicate failed promo execution (item not "
                "properly set up at POS), poor price perception, or brand damage "
                "from discounting.",
                style={"color": GREY, "fontSize": "12px", "margin": "-0.5em 0 0.8em 0"},
            ),
        ],
        footer=[
            html.Button(
                "Export to Excel", id="pricing-power-export-btn", n_clicks=0,
                className="export-btn",
            ),
            dcc.Download(id="pricing-power-download"),
            dcc.Store(
                id="pricing-power-table-data",
                data={
                    "records": display_df.to_dict("records"),
                    "filename": f"pricing_power_{safe_ret}_{safe_scope}",
                },
            ),
        ],
    )


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register Pricing Power decision callbacks."""

    @app.callback(
        Output("pricing-power-download", "data"),
        Input("pricing-power-export-btn", "n_clicks"),
        Input("pricing-power-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_pricing_power(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "pricing-power-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "Pricing Power", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])
