"""Story mode -- 5-section scroll-driven narrative about CHP-0044.

Ported from velocity_tool.py render_story() (lines 1017-1789).  Every
sentence, chart configuration, metric, and visual structure is preserved
exactly.  The module exports ``layout()`` which returns a single scrollable
``html.Div`` and ``register_callbacks(app)`` for the jump-to-decision
and back-to-story wiring.
"""

from __future__ import annotations

import dash_ag_grid as dag
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, ctx, dcc, html, no_update

from charts import add_vline_at_date
from components import chart_legend, metric_card
from constants import (
    DECISIONS,
    GREY,
    GREY_BG,
    GREY_LIGHT,
    NAVY,
    NAVY_MED,
    ORANGE,
    PAGE_BG,
    PROTAGONIST_SKU,
    RED,
    RETAILER_THRESHOLDS,
    TEAL,
    WHITE,
    GREEN_FAINT,
)
from data import (
    get_bottom_stores_below_threshold,
    get_category_avg_velocity,
    get_monday_morning_summary,
    get_promo_hangover_data,
    get_sku_costs,
    get_sku_revenue_at_risk,
    get_sku_trade_spend,
    get_sku_weekly_velocity,
    get_top_demand_4wk,
    get_top_elasticity_skus,
    get_top_velocity_per_door,
    get_walmart_trajectory,
)


# ============================================================
# Narrative helpers (Dash equivalents of _h2 / _eyebrow / _narration)
# ============================================================

def _h2(text: str) -> html.H2:
    return html.H2(
        text,
        style={
            "color": NAVY,
            "marginTop": "1.2rem",
            "marginBottom": "0.3rem",
            "fontFamily": "Georgia, serif",
        },
    )


def _eyebrow(text: str) -> html.Div:
    return html.Div(
        text,
        style={
            "color": ORANGE,
            "fontSize": "0.8rem",
            "fontWeight": "700",
            "letterSpacing": "0.18rem",
            "textTransform": "uppercase",
            "marginTop": "1.5rem",
        },
    )


def _narration(text: str, *, color: str = NAVY) -> html.Div:
    """Pull-quote narration block.  The story-teller voice."""
    return html.Div(
        children=dcc.Markdown(text, dangerously_allow_html=True,
                              style={"color": color}),
        style={
            "fontSize": "1.08rem",
            "lineHeight": "1.6",
            "color": color,
            "margin": "0.6rem 0 0.8rem 0",
            "padding": "0.9rem 1.2rem",
            "backgroundColor": WHITE,
            "borderLeft": f"4px solid {ORANGE}",
            "borderRadius": "4px",
            "boxShadow": "0 1px 2px rgba(27, 42, 74, 0.05)",
        },
    )


def _section_divider() -> html.Hr:
    return html.Hr(style={"borderColor": GREY_LIGHT, "margin": "1.5rem 0"})


def _prose(text: str, *, max_width: str = "820px", font_size: str = "1rem",
           color: str = NAVY_MED) -> html.Div:
    """Ordinary paragraph in the Story layout (non-narration)."""
    return html.Div(
        children=dcc.Markdown(text, dangerously_allow_html=True,
                              style={"color": color}),
        style={
            "color": color,
            "fontSize": font_size,
            "maxWidth": max_width,
            "marginBottom": "0.7rem",
        },
    )


# ============================================================
# Section builders
# ============================================================

def _section_1() -> html.Div:
    """Section 1: The Monday Morning Report."""
    children: list = [
        _eyebrow("Section 1 of 5"),
        _h2("The Monday Morning Report"),
        _prose(
            "This is the report a $25 million specialty foods brand built on. "
            "Total units across the portfolio: up. Revenue: up. Charred Scallion "
            "Relish at +15% year-over-year. Green arrow. Most of the SKUs in "
            "the portfolio look exactly like this — and most of them are fine."
        ),
    ]

    summary = get_monday_morning_summary(PROTAGONIST_SKU)
    if not summary.empty:
        disp = pd.DataFrame({
            "SKU":                   summary["sku"],
            "Product Name":          summary["product_name"],
            "Product Line":          summary["product_line"],
            "Units (Current 52w)":   summary["units_cur"].round(0),
            "Units (Prior 52w)":     summary["units_prior"].round(0),
            "Units YoY %":           summary["units_yoy_pct"].round(1),
            "Revenue (Current 52w)": summary["dollars_cur"].round(0),
            "Revenue (Prior 52w)":   summary["dollars_prior"].round(0),
            "Revenue YoY %":         summary["dollars_yoy_pct"].round(1),
        })

        column_defs = [
            {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 110},
            {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
            {"field": "Product Line", "headerName": "Product Line", "sortable": True, "filter": True, "width": 130},
            {"field": "Units (Current 52w)", "headerName": "Units (Current 52w)", "sortable": True,
             "valueFormatter": {"function": "d3.format(',.0f')(params.value)"}},
            {"field": "Units (Prior 52w)", "headerName": "Units (Prior 52w)", "sortable": True,
             "valueFormatter": {"function": "d3.format(',.0f')(params.value)"}},
            {"field": "Units YoY %", "headerName": "Units YoY %", "sortable": True,
             "valueFormatter": {"function": "params.value == null ? '—' : d3.format('+.1f')(params.value) + '%'"},
             "cellStyle": {"function":
                 f"params.value >= 0 ? {{'color': '{TEAL}', 'fontWeight': '600'}} : "
                 f"{{'color': '{RED}', 'fontWeight': '600'}}"}},
            {"field": "Revenue (Current 52w)", "headerName": "Revenue (Current 52w)", "sortable": True,
             "valueFormatter": {"function": "'$' + d3.format(',.0f')(params.value)"}},
            {"field": "Revenue (Prior 52w)", "headerName": "Revenue (Prior 52w)", "sortable": True,
             "valueFormatter": {"function": "'$' + d3.format(',.0f')(params.value)"}},
            {"field": "Revenue YoY %", "headerName": "Revenue YoY %", "sortable": True,
             "valueFormatter": {"function": "params.value == null ? '—' : d3.format('+.1f')(params.value) + '%'"},
             "cellStyle": {"function":
                 f"params.value >= 0 ? {{'color': '{TEAL}', 'fontWeight': '600'}} : "
                 f"{{'color': '{RED}', 'fontWeight': '600'}}"}},
        ]

        row_style_conditions = [
            {
                "condition": f"params.data.SKU === '{PROTAGONIST_SKU}'",
                "style": {"backgroundColor": GREEN_FAINT, "color": NAVY, "fontWeight": "600"},
            },
        ]

        grid = dag.AgGrid(
            rowData=disp.to_dict("records"),
            columnDefs=column_defs,
            dashGridOptions={
                "domLayout": "autoHeight",
                "animateRows": True,
                "getRowStyle": {"styleConditions": row_style_conditions},
            },
            style={"width": "100%"},
            className="ag-theme-alpine",
            id="story-monday-grid",
        )
        children.append(grid)

    children.append(_narration(
        "Every number in this table is correct. This is the view that "
        "built a $25 million brand, and most of the time it tells you "
        "exactly what you need to know. But underneath these green arrows, "
        "there’s a layer this summary can’t reach — the "
        "place where margin leaks and shelf risk actually live. Watch what "
        "happens when you zoom in on one of the green ones."
    ))

    return html.Div(children, id="story-section-1")


def _section_2() -> tuple[html.Div, dict]:
    """Section 2: The Volume Trap.

    Returns (section_div, computed_values) where computed_values carries
    numbers needed by later sections (yoy_units_pct, baseline_pct,
    trade_spend, prior_baseline, recent_baseline).
    """
    weekly = get_sku_weekly_velocity(PROTAGONIST_SKU)
    trade_spend = get_sku_trade_spend(PROTAGONIST_SKU)

    def _wk_in(d: pd.DataFrame, lo: str, hi: str) -> pd.Series:
        return (d["week_ending"] >= pd.Timestamp(lo)) & (d["week_ending"] <= pd.Timestamp(hi))

    last52  = weekly[_wk_in(weekly, "2025-05-04", "2026-05-02")]
    prior52 = weekly[_wk_in(weekly, "2024-05-04", "2025-05-03")]
    yoy_units_pct = ((last52["units_total"].sum() - prior52["units_total"].sum())
                     / max(prior52["units_total"].sum(), 1) * 100)

    recent_baseline = weekly[
        _wk_in(weekly, "2025-11-03", "2026-05-02") & ~weekly["on_promo"]
    ]["velocity"].mean()
    prior_baseline = weekly[
        _wk_in(weekly, "2025-05-04", "2025-11-02") & ~weekly["on_promo"]
    ]["velocity"].mean()
    baseline_pct = (
        (recent_baseline - prior_baseline) / prior_baseline * 100
        if prior_baseline else 0
    )

    promo_pct_recent = weekly[_wk_in(weekly, "2025-11-03", "2026-05-02")]["on_promo"].mean() * 100
    promo_pct_prior  = weekly[_wk_in(weekly, "2025-05-04", "2025-11-02")]["on_promo"].mean() * 100

    # Metric cards row
    metrics_row = html.Div([
        html.Div(metric_card(
            "YoY total volume",
            f"{yoy_units_pct:+.1f}%",
            delta="Looks healthy",
            delta_color=TEAL,
        ), style={"flex": "1"}),
        html.Div(metric_card(
            "Baseline velocity",
            f"{baseline_pct:+.1f}%",
            delta="Real trend",
            delta_color=RED,
        ), style={"flex": "1"}),
        html.Div(metric_card(
            "Promo weeks (recent)",
            f"{promo_pct_recent:.0f}%",
            delta=f"was {promo_pct_prior:.0f}%",
            delta_color=GREY,
        ), style={"flex": "1"}),
        html.Div(metric_card(
            "Trade spend (life)",
            f"${trade_spend:,.0f}",
            delta="Burned to mask the decline",
            delta_color=GREY,
        ), style={"flex": "1"}),
    ], style={"display": "flex", "gap": "1rem", "marginBottom": "1rem"})

    # Chart: total vs baseline weekly velocity
    chart_title = html.H4(
        f"Charred Scallion Relish: +{yoy_units_pct:.0f}% growth — "
        f"or {baseline_pct:.0f}% decline?",
        style={"color": NAVY, "marginTop": "1rem"},
    )
    legend = chart_legend([
        (NAVY_MED, "Total weekly velocity (what the report sees)"),
        (RED,      "Baseline only (non-promo weeks — the real trend)"),
        (ORANGE,   "Promo weeks"),
    ])

    fig = go.Figure()
    # Promo-week vertical shading
    for _, row in weekly[weekly["on_promo"]].iterrows():
        fig.add_vrect(
            x0=row["week_ending"] - pd.Timedelta(days=3),
            x1=row["week_ending"] + pd.Timedelta(days=4),
            fillcolor=ORANGE, opacity=0.18, line_width=0, layer="below",
        )
    # Line 1: total velocity
    fig.add_trace(go.Scatter(
        x=weekly["week_ending"], y=weekly["velocity"],
        mode="lines+markers",
        line=dict(color=NAVY_MED, width=2),
        marker=dict(size=4, color=NAVY_MED),
        name="Total velocity",
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>Total: %{y:.2f} u/store/wk<extra></extra>",
    ))
    # Line 2: baseline (non-promo) velocity
    fig.add_trace(go.Scatter(
        x=weekly["week_ending"], y=weekly["baseline_v"],
        mode="lines+markers", connectgaps=False,
        line=dict(color=RED, width=2.5, dash="dot"),
        marker=dict(size=5, color=RED),
        name="Baseline velocity (non-promo only)",
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>Baseline: %{y:.2f} u/store/wk<extra></extra>",
    ))
    # Trend annotation
    if not weekly.empty:
        bl = weekly.dropna(subset=["baseline_v"])
        if len(bl) >= 8:
            x_last = bl.tail(8)["baseline_v"].mean()
            fig.add_annotation(
                x=bl["week_ending"].iloc[-1], y=x_last,
                text=f"<b>{x_last:.1f}</b><br>baseline<br>now",
                showarrow=False, xanchor="left", xshift=8,
                font=dict(size=12, color=RED),
            )

    fig.update_layout(
        template="simple_white",
        paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
        height=420, margin=dict(l=60, r=120, t=20, b=50),
        showlegend=False,
        xaxis=dict(title="Week ending", title_font=dict(size=13, color=NAVY_MED),
                   tickfont=dict(size=12, color=NAVY), gridcolor=GREY_LIGHT,
                   linecolor=GREY_LIGHT),
        yaxis=dict(title="Units per store per week",
                   title_font=dict(size=13, color=NAVY_MED),
                   tickfont=dict(size=12, color=NAVY), gridcolor=GREY_LIGHT,
                   linecolor=GREY_LIGHT, rangemode="tozero"),
        font=dict(family="sans-serif", size=13, color=NAVY),
    )

    narration = _narration(
        f"Charred Scallion Relish moved <b>{yoy_units_pct:.1f}% more units</b> "
        f"this year than last. But strip out the promotional weeks and the "
        f"real velocity — the rate at which consumers pick this product off "
        f"the shelf without a discount — dropped <b style='color:{RED}'>"
        f"{baseline_pct:.1f}%</b>. The brand spent "
        f"<b style='color:{RED}'>${trade_spend:,.0f}</b> in trade to make a "
        f"shrinking SKU look like a growing one."
    )

    section = html.Div([
        _eyebrow("Section 2 of 5"),
        _h2("The Volume Trap — Charred Scallion Relish"),
        metrics_row,
        chart_title,
        legend,
        dcc.Graph(figure=fig, id="story-velocity-chart"),
        narration,
    ], id="story-section-2")

    computed = {
        "yoy_units_pct": yoy_units_pct,
        "baseline_pct": baseline_pct,
        "trade_spend": trade_spend,
        "prior_baseline": prior_baseline,
        "recent_baseline": recent_baseline,
    }
    return section, computed


def _section_3(trade_spend: float) -> tuple[html.Div, dict]:
    """Section 3: What $X Bought -- Promo ROI.

    Returns (section_div, computed_values) with net_dollars, n_backfired, etc.
    """
    hangover = get_promo_hangover_data(PROTAGONIST_SKU)
    hangover = hangover.dropna(subset=["pre_v", "promo_v", "post_v"]).reset_index(drop=True)

    children: list = [
        _eyebrow("Section 3 of 5"),
        _h2(f"What ${trade_spend:,.0f} Bought — Promo ROI"),
    ]

    computed: dict = {"net_dollars": 0, "n_backfired": 0, "n_promos": 0}

    if hangover.empty:
        children.append(html.Div(
            "No comparable pre/during/post promo windows yet for this SKU.",
            style={"padding": "1rem", "color": GREY},
        ))
        return html.Div(children, id="story-section-3"), computed

    children.append(html.H4(
        "Every promotion left the baseline lower than before",
        style={"color": NAVY, "marginTop": "0.4rem"},
    ))
    children.append(chart_legend([
        (NAVY_MED, "Pre-promo baseline (4 weeks before)"),
        (TEAL,     "During promo"),
        (RED,      "Post-promo (4 weeks after)"),
    ]))

    # Grouped bar chart
    labels = [
        f"{r['retailer']}<br><span style='color:{GREY}; font-size:10px'>"
        f"{r['promo_type']} · {r['discount_depth_pct']*100:.0f}% off · "
        f"{r['start_week'][:7]}</span>"
        for _, r in hangover.iterrows()
    ]

    fig3 = go.Figure()
    fig3.add_trace(go.Bar(
        x=labels, y=hangover["pre_v"], name="Pre",
        marker_color=NAVY_MED,
        text=hangover["pre_v"].map(lambda v: f"{v:.1f}"),
        textposition="outside", textfont=dict(size=11, color=NAVY),
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>Pre-promo: %{y:.2f} u/sw<extra></extra>",
    ))
    fig3.add_trace(go.Bar(
        x=labels, y=hangover["promo_v"], name="During",
        marker_color=TEAL,
        text=hangover["promo_v"].map(lambda v: f"{v:.1f}"),
        textposition="outside", textfont=dict(size=11, color=NAVY),
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>During promo: %{y:.2f} u/sw<extra></extra>",
    ))
    fig3.add_trace(go.Bar(
        x=labels, y=hangover["post_v"], name="Post",
        marker_color=RED,
        text=hangover["post_v"].map(lambda v: f"{v:.1f}"),
        textposition="outside", textfont=dict(size=11, color=NAVY),
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>Post-promo: %{y:.2f} u/sw<extra></extra>",
    ))
    fig3.update_layout(
        template="simple_white", paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
        height=440, margin=dict(l=60, r=30, t=20, b=80),
        barmode="group", bargap=0.25, bargroupgap=0.05,
        showlegend=False,
        xaxis=dict(tickfont=dict(size=11, color=NAVY), linecolor=GREY_LIGHT),
        yaxis=dict(title="Units per store per week",
                   title_font=dict(size=13, color=NAVY_MED),
                   tickfont=dict(size=12, color=NAVY),
                   gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT, rangemode="tozero"),
        font=dict(family="sans-serif", size=13, color=NAVY),
    )
    children.append(dcc.Graph(figure=fig3, id="story-hangover-chart"))

    # Net effect computation
    cost_data = get_sku_costs(PROTAGONIST_SKU)
    ws = cost_data["wholesale_walmart"]
    cogs = cost_data["cogs_per_unit"]
    margin_per_unit = max(ws - cogs, 0.0)

    incr_units_total = ((hangover["promo_v"] - hangover["pre_v"])
                        * hangover["doors"] * hangover["duration_weeks"]).clip(lower=0).sum()
    hangover_units_total = ((hangover["pre_v"] - hangover["post_v"])
                            * hangover["doors"] * 4).clip(lower=0).sum()
    net_units = incr_units_total - hangover_units_total
    net_dollars = net_units * margin_per_unit
    n_backfired = int((hangover["post_v"] < hangover["pre_v"]).sum())
    n_promos = len(hangover)

    # Metric cards
    net_label = "Backfired" if net_dollars < 0 else "Net positive"
    net_color = RED if net_dollars < 0 else TEAL
    children.append(html.Div([
        html.Div(metric_card(
            "Incremental units (during promo)",
            f"{incr_units_total:,.0f}",
        ), style={"flex": "1"}),
        html.Div(metric_card(
            "Units lost in post-promo dip",
            f"{hangover_units_total:,.0f}",
        ), style={"flex": "1"}),
        html.Div(metric_card(
            "Net effect (margin terms)",
            f"${net_dollars:,.0f}",
            delta=net_label,
            delta_color=net_color,
        ), style={"flex": "1"}),
    ], style={"display": "flex", "gap": "1rem", "marginBottom": "1rem"}))

    children.append(_narration(
        f"The {n_promos} measurable promotions on Charred Scallion Relish "
        f"each followed the same pattern: a short spike in volume, "
        f"followed by a post-promo dip that settled "
        f"<b>{'below where it started' if n_backfired >= n_promos / 2 else 'near or below where it started'}</b>"
        f" in {n_backfired} of {n_promos} cases. The brand didn’t just "
        f"spend <b style='color:{RED}'>${trade_spend:,.0f}</b> to stand still — "
        f"after netting promo lift against post-promo erosion, the cumulative "
        f"effect on margin is "
        f"<b style='color:{RED if net_dollars < 0 else TEAL}'>"
        f"${net_dollars:,.0f}</b>."
    ))

    computed = {
        "net_dollars": net_dollars,
        "n_backfired": n_backfired,
        "n_promos": n_promos,
    }
    return html.Div(children, id="story-section-3"), computed


def _section_4() -> tuple[html.Div, dict]:
    """Section 4: The Shelf Is Watching -- Walmart trajectory.

    Returns (section_div, computed_values) with rev, cross_date, etc.
    """
    walmart_threshold = RETAILER_THRESHOLDS["Walmart"]
    traj = get_walmart_trajectory(PROTAGONIST_SKU)
    traj = traj.dropna(subset=["t13"]).reset_index(drop=True)

    children: list = [
        _eyebrow("Section 4 of 5"),
        _h2("The Shelf Is Watching — Velocity Trajectory vs Threshold"),
    ]

    computed: dict = {"rev": None, "cross_date": None}

    if traj.empty or len(traj) < 4:
        children.append(html.Div(
            "Not enough Walmart trajectory data to project a delisting date.",
            style={"padding": "1rem", "color": GREY},
        ))
        return html.Div(children, id="story-section-4"), computed

    # Linear projection from trailing 13wk avg curve (last 26 weeks)
    proj_window = traj.tail(26)
    x_num = (proj_window["week_ending"] - proj_window["week_ending"].iloc[0]).dt.days.values
    y_num = proj_window["t13"].values
    slope_per_day = (
        ((x_num * y_num).mean() - x_num.mean() * y_num.mean())
        / max(((x_num**2).mean() - x_num.mean()**2), 1e-9)
    )

    last_date = traj["week_ending"].iloc[-1]
    last_t13  = traj["t13"].iloc[-1]

    if slope_per_day < 0 and last_t13 > walmart_threshold:
        days_to_cross = (walmart_threshold - last_t13) / slope_per_day
        cross_date = last_date + pd.Timedelta(days=days_to_cross)
    else:
        cross_date = None
        days_to_cross = None

    horizon_days = min(int(days_to_cross) + 28, 78 * 7) if days_to_cross else 78 * 7
    proj_dates = pd.date_range(last_date, last_date + pd.Timedelta(days=horizon_days), freq="W-SAT")
    proj_days = (proj_dates - last_date).days
    proj_y = last_t13 + slope_per_day * proj_days

    cross_quarter_str = ""
    if cross_date is not None:
        q = (cross_date.month - 1) // 3 + 1
        cross_quarter_str = f"Q{q} {cross_date.year}"

    title_phrase = (
        f"hits the Walmart delisting threshold in "
        f"<b style='color:{RED}'>{cross_quarter_str}</b>"
        if cross_quarter_str else
        "stays above the Walmart delisting threshold for now"
    )
    children.append(html.Div(
        children=dcc.Markdown(
            f"<h4 style='color:{NAVY}; margin-top: 0.4rem;'>"
            f"At current trajectory, Charred Scallion Relish "
            f"{title_phrase}</h4>",
            dangerously_allow_html=True,
        ),
    ))
    children.append(chart_legend([
        (NAVY_MED, "Trailing 13-week avg velocity (Walmart)"),
        (ORANGE,   "Projected at current decline rate"),
        (RED,      f"Walmart delisting threshold ({walmart_threshold:.1f} u/sw)"),
    ]))

    fig4 = go.Figure()
    # Historical
    fig4.add_trace(go.Scatter(
        x=traj["week_ending"], y=traj["t13"],
        mode="lines", line=dict(color=NAVY_MED, width=2.5),
        hovertemplate="<b>%{x|%b %Y}</b><br>T13 vel: %{y:.2f} u/sw<extra></extra>",
    ))
    # Projection
    fig4.add_trace(go.Scatter(
        x=proj_dates, y=proj_y,
        mode="lines", line=dict(color=ORANGE, width=2.5, dash="dash"),
        hovertemplate="<b>%{x|%b %Y}</b><br>Projected: %{y:.2f} u/sw<extra></extra>",
    ))
    # Threshold line
    fig4.add_hline(y=walmart_threshold, line_dash="solid",
                   line_color=RED, line_width=2)
    fig4.add_annotation(
        x=traj["week_ending"].iloc[0], y=walmart_threshold,
        text=f"Walmart delisting threshold ({walmart_threshold:.1f})",
        showarrow=False, xanchor="left", yanchor="bottom",
        font=dict(size=11, color=RED),
        bgcolor="rgba(255,255,255,0.92)", borderpad=2,
    )
    if cross_date is not None:
        add_vline_at_date(fig4, cross_date,
                          f"Crosses threshold<br>{cross_quarter_str}",
                          color=RED, dash="dash",
                          annotation_position="top right")

    fig4.update_layout(
        template="simple_white", paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
        height=420, margin=dict(l=60, r=120, t=20, b=50),
        showlegend=False,
        xaxis=dict(title="Week ending",
                   title_font=dict(size=13, color=NAVY_MED),
                   tickfont=dict(size=12, color=NAVY),
                   gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT),
        yaxis=dict(title="Units per store per week (Walmart)",
                   title_font=dict(size=13, color=NAVY_MED),
                   tickfont=dict(size=12, color=NAVY),
                   gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT,
                   rangemode="tozero"),
        font=dict(family="sans-serif", size=13, color=NAVY),
    )
    children.append(dcc.Graph(figure=fig4, id="story-trajectory-chart"))

    # Revenue at risk
    rev = get_sku_revenue_at_risk(PROTAGONIST_SKU)
    decline_per_quarter = abs(slope_per_day) * 91
    timeframe = f"by {cross_quarter_str}" if cross_date is not None else "in the near term"

    children.append(_narration(
        f"Walmart reviews velocity quarterly. The category threshold is "
        f"<b>{walmart_threshold:.1f} units/store/week</b>. Charred Scallion "
        f"Relish is currently at <b>{last_t13:.2f}</b>, declining at "
        f"<b>{decline_per_quarter:.2f}</b> units/store/week per quarter. "
        f"If nothing changes, it crosses the threshold "
        f"<b>{timeframe}</b>. That’s "
        f"<b>{rev['walmart_doors']:,}</b> doors and "
        f"<b>${rev['annual_rev_walmart']:,.0f}</b> in annual revenue at risk."
    ))

    computed = {"rev": rev, "cross_date": cross_date}
    return html.Div(children, id="story-section-4"), computed


def _section_5(
    *,
    yoy_units_pct: float,
    trade_spend: float,
    prior_baseline: float,
    recent_baseline: float,
    rev: dict | None,
) -> html.Div:
    """Section 5: The Total Cost of Not Knowing."""
    # If rev wasn't computed in section 4, fetch it fresh
    if rev is None:
        rev = get_sku_revenue_at_risk(PROTAGONIST_SKU)
    cat_avg = get_category_avg_velocity("Specialty Condiments")
    walmart_doors = rev["walmart_doors"]
    margin_per_unit = max(rev["wholesale_walmart"] - rev["cogs"], 0.0)

    annual_erosion_units = max(prior_baseline - recent_baseline, 0) * walmart_doors * 52
    margin_destroyed = annual_erosion_units * margin_per_unit
    revenue_at_risk = rev["annual_rev_walmart"]
    total_cost = trade_spend + margin_destroyed + revenue_at_risk

    # Big callout card
    callout = html.Div(
        children=[
            html.Div(
                "Total Cost of Not Knowing",
                style={
                    "color": NAVY_MED, "fontSize": "0.85rem",
                    "fontWeight": "600", "letterSpacing": "0.18rem",
                    "textTransform": "uppercase",
                },
            ),
            html.Div(
                f"${total_cost:,.0f}",
                style={
                    "color": RED, "fontFamily": "Georgia, serif",
                    "fontSize": "3.4rem", "fontWeight": "700",
                    "margin": "0.3rem 0 0.6rem 0", "lineHeight": "1",
                },
            ),
            html.Div(
                "One SKU. One year. Three buckets that never appear in the "
                "Monday morning report.",
                style={"color": NAVY_MED, "fontSize": "0.95rem", "maxWidth": "720px"},
            ),
        ],
        style={
            "backgroundColor": WHITE,
            "border": f"1px solid {GREY_LIGHT}",
            "borderLeft": f"8px solid {RED}",
            "borderRadius": "6px",
            "padding": "1.4rem 1.8rem",
            "margin": "1rem 0",
            "boxShadow": "0 2px 6px rgba(192, 34, 31, 0.08)",
        },
    )

    # Three cost-bucket metric cards
    bucket_row = html.Div([
        html.Div(metric_card(
            "Trade spend burned",
            f"${trade_spend:,.0f}",
            delta="On a SKU with declining baseline",
            delta_color=GREY,
        ), style={"flex": "1"}),
        html.Div(metric_card(
            "Annualized margin destroyed",
            f"${margin_destroyed:,.0f}",
            delta=f"vs. holding baseline at {prior_baseline:.1f} u/sw",
            delta_color=GREY,
        ), style={"flex": "1"}),
        html.Div(metric_card(
            "Walmart revenue at risk",
            f"${revenue_at_risk:,.0f}",
            delta=f"{walmart_doors:,} doors below threshold trajectory",
            delta_color=GREY,
        ), style={"flex": "1"}),
    ], style={"display": "flex", "gap": "1rem", "marginBottom": "1rem"})

    narration_1 = _narration(
        f"Every number in the Monday morning report was accurate. The "
        f"portfolio was up. Revenue was up. Charred Scallion Relish was "
        f"up {yoy_units_pct:.0f}%. And underneath those green arrows, "
        f"<b style='color:{RED}'>${total_cost:,.0f}</b> in value was being "
        f"destroyed — invisible to every pivot table in the building."
    )

    jump_intro = html.Div(
        "This is one SKU. The Velocity Decision Tool runs this analysis "
        "across all 90. Pick a decision from the sidebar — or jump "
        "straight into the relevant view below.",
        style={
            "fontSize": "1.08rem", "color": NAVY,
            "margin": "1.2rem 0 0.7rem 0",
        },
    )

    # Jump-to-decision buttons
    button_style = {
        "display": "block",
        "width": "100%",
        "padding": "0.55rem 0.75rem",
        "fontSize": "0.85rem",
        "fontWeight": "600",
        "color": WHITE,
        "backgroundColor": NAVY,
        "border": "none",
        "borderRadius": "6px",
        "cursor": "pointer",
        "textAlign": "center",
    }

    jump_buttons = html.Div([
        html.Div(html.Button(
            "→ Shelf Defense", id="story-jump-shelf", n_clicks=0,
            style=button_style,
        ), style={"flex": "1"}),
        html.Div(html.Button(
            "→ Promo ROI", id="story-jump-promo", n_clicks=0,
            style=button_style,
        ), style={"flex": "1"}),
        html.Div(html.Button(
            "→ Pricing Power", id="story-jump-pricing", n_clicks=0,
            style=button_style,
        ), style={"flex": "1"}),
        html.Div(html.Button(
            "→ SKU Rationalization", id="story-jump-rat", n_clicks=0,
            style=button_style,
        ), style={"flex": "1"}),
    ], style={"display": "flex", "gap": "1rem", "marginBottom": "1rem"})

    # ---- Coda: What the rest of the portfolio looks like ----
    coda_children: list = [
        _section_divider(),
        _eyebrow("Coda"),
        _h2("What the rest of the portfolio looks like"),
        _prose(
            "Not every SKU is Charred Scallion Relish. Most of the portfolio is "
            "healthy, with normal demand signals and clear opportunities. The "
            "four panels below are tactical pulls from the rest of the tool — "
            "the day-to-day decisions you’ll come back for once the protagonist "
            "is dealt with."
        ),
    ]

    # 1. Production Planning
    coda_children.append(html.H4(
        "1. Production Planning",
        style={"color": NAVY, "marginTop": "1.2rem"},
    ))
    demand = get_top_demand_4wk()
    if not demand.empty:
        top1 = demand.iloc[0]
        coda_children.append(_prose(
            f"Demand signals align with current production cadence. Over the "
            f"trailing 4 weeks, "
            f"<b>{top1['product_name']}</b> ({top1['sku']}) led "
            f"the portfolio at <b>{top1['cases_4wk']:,.0f} cases</b>. The top "
            f"10 SKUs by projected case demand are listed below — set "
            f"production to match the next 4 weeks. "
            f"<i>Explore this in the Production Planning tab →</i>",
            font_size="0.98rem",
        ))
        figp = go.Figure(go.Bar(
            x=demand["cases_4wk"], y=demand["sku"],
            orientation="h", marker_color=NAVY_MED,
            text=demand["cases_4wk"].map(lambda v: f"{v:,.0f}"),
            textposition="outside", textfont=dict(size=12, color=NAVY),
            cliponaxis=False,
            customdata=demand[["product_name"]].values,
            hovertemplate="<b>%{y}</b> %{customdata[0]}<br>%{x:,.0f} cases<extra></extra>",
        ))
        figp.update_layout(
            template="simple_white", paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
            height=380, margin=dict(l=110, r=80, t=10, b=40), showlegend=False,
            xaxis=dict(title="Projected 4-week case demand",
                       title_font=dict(size=12, color=NAVY_MED),
                       gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT),
            yaxis=dict(autorange="reversed", tickfont=dict(size=12, color=NAVY)),
            font=dict(family="sans-serif", size=12, color=NAVY),
        )
        coda_children.append(dcc.Graph(figure=figp, id="story-demand-chart"))

    # 2. Distribution Expansion
    coda_children.append(html.H4(
        "2. Distribution Expansion",
        style={"color": NAVY, "marginTop": "1.2rem"},
    ))
    chains = get_top_velocity_per_door()
    if not chains.empty:
        top1 = chains.iloc[0]
        coda_children.append(_prose(
            f"<b>{top1['chain']}</b> leads on per-door productivity at "
            f"<b>{top1['vel_per_door']:.2f} units/store/week</b>, well above "
            f"the chain average. The chains below earn their shelf — start "
            f"there before opening new ones. "
            f"<i>Explore this in the Distribution Expansion tab →</i>",
            font_size="0.98rem",
        ))
        fige = go.Figure(go.Bar(
            x=chains["vel_per_door"], y=chains["chain"],
            orientation="h", marker_color=TEAL,
            text=chains["vel_per_door"].map(lambda v: f"{v:.2f}"),
            textposition="outside", textfont=dict(size=12, color=NAVY),
            cliponaxis=False,
            customdata=chains[["active_doors"]].values,
            hovertemplate="<b>%{y}</b><br>%{x:.2f} u/sw · %{customdata[0]:,} doors<extra></extra>",
        ))
        fige.update_layout(
            template="simple_white", paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
            height=380, margin=dict(l=160, r=80, t=10, b=40), showlegend=False,
            xaxis=dict(title="Avg units per door per week (last 13 weeks)",
                       title_font=dict(size=12, color=NAVY_MED),
                       gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT),
            yaxis=dict(autorange="reversed", tickfont=dict(size=12, color=NAVY)),
            font=dict(family="sans-serif", size=12, color=NAVY),
        )
        coda_children.append(dcc.Graph(figure=fige, id="story-expansion-chart"))

    # 3. Distribution Pruning
    coda_children.append(html.H4(
        "3. Distribution Pruning",
        style={"color": NAVY, "marginTop": "1.2rem"},
    ))
    weak = get_bottom_stores_below_threshold(threshold=2.0)
    if weak.empty:
        coda_children.append(_prose(
            "No Walmart velocity data in the last 13 weeks. "
            "<i>Explore this in the Distribution Pruning tab →</i>",
            font_size="0.98rem",
        ))
    else:
        n_below = int((weak["gap"] > 0).sum())
        if n_below > 0:
            lede = (f"<b>{n_below}</b> of the 10 weakest Walmart stores fall "
                    f"below the 2.0 u/sw threshold over the last 13 weeks.")
        else:
            lede = ("All Walmart stores currently sit above the 2.0 u/sw "
                    "threshold, but the bottom of the distribution is "
                    "tracking close.")
        coda_children.append(_prose(
            f"{lede} Pruning underperformers frees up working capital and "
            f"reduces chargeback exposure. "
            f"<i>Explore this in the Distribution Pruning tab →</i>",
            font_size="0.98rem",
        ))
        # Sort highest velocity -> lowest
        weak = weak.iloc[::-1].reset_index(drop=True)
        bar_colors = [RED if g > 0 else ORANGE for g in weak["gap"]]
        figpr = go.Figure(go.Bar(
            x=weak["vel"], y=weak["store_id"],
            orientation="h", marker_color=bar_colors,
            text=weak["vel"].map(lambda v: f"{v:.2f}"),
            textposition="outside", textfont=dict(size=12, color=NAVY),
            cliponaxis=False,
            customdata=weak[["gap"]].values,
            hovertemplate="<b>%{y}</b><br>Velocity %{x:.2f} u/sw "
                          "(gap to 2.0: %{customdata[0]:+.2f})<extra></extra>",
        ))
        figpr.add_vline(x=2.0, line_dash="dash", line_color=GREY, line_width=2)
        figpr.update_layout(
            template="simple_white", paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
            height=380, margin=dict(l=110, r=80, t=10, b=40), showlegend=False,
            xaxis=dict(title="Velocity (u/sw, last 13 weeks) — dashed line = 2.0 threshold",
                       title_font=dict(size=12, color=NAVY_MED),
                       gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT),
            yaxis=dict(autorange="reversed", tickfont=dict(size=12, color=NAVY)),
            font=dict(family="sans-serif", size=12, color=NAVY),
        )
        coda_children.append(dcc.Graph(figure=figpr, id="story-pruning-chart"))

    # 4. Pricing Power
    coda_children.append(html.H4(
        "4. Pricing Power",
        style={"color": NAVY, "marginTop": "1.2rem"},
    ))
    elasticity = get_top_elasticity_skus()
    if not elasticity.empty:
        top1 = elasticity.iloc[0]
        coda_children.append(_prose(
            f"<b>{top1['product_name']}</b> ({top1['sku']}) is the most "
            f"elastic SKU in the portfolio — every 1% of discount yielded "
            f"<b>{top1['elasticity']:.2f}%</b> of unit lift. Highly elastic "
            f"SKUs respond well to promotion; inelastic ones are giving up "
            f"margin without earning incremental volume. "
            f"<i>Explore this in the Pricing Power tab →</i>",
            font_size="0.98rem",
        ))
        figel = go.Figure(go.Bar(
            x=elasticity["elasticity"], y=elasticity["sku"],
            orientation="h", marker_color=ORANGE,
            text=elasticity["elasticity"].map(lambda v: f"{v:.2f}"),
            textposition="outside", textfont=dict(size=12, color=NAVY),
            cliponaxis=False,
            customdata=elasticity[["product_name", "n_promos"]].values,
            hovertemplate="<b>%{y}</b> %{customdata[0]}<br>"
                          "Elasticity %{x:.2f} · %{customdata[1]} promos<extra></extra>",
        ))
        figel.update_layout(
            template="simple_white", paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
            height=380, margin=dict(l=110, r=80, t=10, b=40), showlegend=False,
            xaxis=dict(title="Avg lift % per 1% discount",
                       title_font=dict(size=12, color=NAVY_MED),
                       gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT),
            yaxis=dict(autorange="reversed", tickfont=dict(size=12, color=NAVY)),
            font=dict(family="sans-serif", size=12, color=NAVY),
        )
        coda_children.append(dcc.Graph(figure=figel, id="story-elasticity-chart"))

    return html.Div([
        _eyebrow("Section 5 of 5"),
        _h2("The Total Cost of Not Knowing"),
        callout,
        bucket_row,
        narration_1,
        jump_intro,
        jump_buttons,
        html.Div(coda_children),
    ], id="story-section-5")


# ============================================================
# Public entry point
# ============================================================

def layout() -> html.Div:
    """Return the full Story narrative as a single scrollable Div."""

    # Title block
    title_block = html.Div([
        html.Div(
            "Why this tool exists",
            style={
                "color": ORANGE, "fontSize": "0.75rem",
                "fontWeight": "700", "letterSpacing": "0.22rem",
                "textTransform": "uppercase",
            },
        ),
        html.H1(
            "The Charred Scallion Relish Problem",
            style={
                "color": NAVY, "margin": "0.05rem 0 0 0",
                "fontFamily": "Georgia, serif",
            },
        ),
        html.Div(
            "One SKU. Eight months. $18,701 in trade spend. A +15% YoY headline "
            "that hides a 25% baseline collapse. Read the story, then use the tool.",
            style={
                "color": NAVY_MED, "fontSize": "1.05rem",
                "marginTop": "0.4rem", "maxWidth": "820px",
            },
        ),
    ], style={"marginBottom": "0.6rem"})

    import logging
    log = logging.getLogger("story")

    def _fallback(section_name: str, exc: Exception) -> html.Div:
        return html.Div(
            [
                html.Div(
                    f"This section of the deep dive could not be loaded.",
                    style={"color": NAVY, "fontWeight": "600", "marginBottom": "0.3rem"},
                ),
                html.Div(
                    f"{section_name}: {exc.__class__.__name__} — {exc}",
                    style={"color": GREY, "fontSize": "0.85rem", "fontFamily": "monospace"},
                ),
            ],
            style={
                "backgroundColor": GREY_BG, "border": f"1px solid {GREY_LIGHT}",
                "borderLeft": f"6px solid {ORANGE}", "borderRadius": "6px",
                "padding": "1rem 1.2rem", "margin": "1rem 0",
            },
        )

    _SEC2_DEFAULTS = {
        "yoy_units_pct": 0.0, "trade_spend": 0.0,
        "prior_baseline": 0.0, "recent_baseline": 0.0, "baseline_pct": 0.0,
    }
    _SEC4_DEFAULTS = {"rev": None, "cross_date": None}

    try:
        sec1 = _section_1()
    except Exception as exc:
        log.exception("story section 1 failed")
        sec1 = _fallback("Section 1 — Monday morning report", exc)

    try:
        sec2, sec2_vals = _section_2()
    except Exception as exc:
        log.exception("story section 2 failed")
        sec2 = _fallback("Section 2 — velocity & baseline", exc)
        sec2_vals = dict(_SEC2_DEFAULTS)

    try:
        sec3, _ = _section_3(sec2_vals["trade_spend"])
    except Exception as exc:
        log.exception("story section 3 failed")
        sec3 = _fallback("Section 3 — promo ROI", exc)

    try:
        sec4, sec4_vals = _section_4()
    except Exception as exc:
        log.exception("story section 4 failed")
        sec4 = _fallback("Section 4 — Walmart trajectory", exc)
        sec4_vals = dict(_SEC4_DEFAULTS)

    try:
        sec5 = _section_5(
            yoy_units_pct=sec2_vals["yoy_units_pct"],
            trade_spend=sec2_vals["trade_spend"],
            prior_baseline=sec2_vals["prior_baseline"],
            recent_baseline=sec2_vals["recent_baseline"],
            rev=sec4_vals["rev"],
        )
    except Exception as exc:
        log.exception("story section 5 failed")
        sec5 = _fallback("Section 5 — total cost", exc)

    return html.Div([
        title_block,
        _section_divider(),
        sec1,
        _section_divider(),
        sec2,
        _section_divider(),
        sec3,
        _section_divider(),
        sec4,
        _section_divider(),
        sec5,
    ], style={"maxWidth": "1100px", "margin": "0 auto"})


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register Story-mode jump-to-decision and back-to-story callbacks."""

    # Jump buttons: each sets the decision picker and switches view
    @app.callback(
        Output("decision-picker", "value", allow_duplicate=True),
        Output("view-store", "data", allow_duplicate=True),
        Output("came-from-story", "data", allow_duplicate=True),
        Input("story-jump-shelf", "n_clicks"),
        Input("story-jump-promo", "n_clicks"),
        Input("story-jump-pricing", "n_clicks"),
        Input("story-jump-rat", "n_clicks"),
        prevent_initial_call=True,
    )
    def jump_to_decision(n_shelf, n_promo, n_pricing, n_rat):
        triggered = ctx.triggered_id
        if not triggered:
            return no_update, no_update, no_update

        mapping = {
            "story-jump-shelf":   DECISIONS[0],
            "story-jump-promo":   DECISIONS[2],
            "story-jump-pricing": DECISIONS[7],
            "story-jump-rat":     DECISIONS[5],
        }
        decision = mapping.get(triggered)
        if decision is None:
            return no_update, no_update, no_update

        return decision, "decision", True

    # Back to Deep Dive: switch view to "story" and set a scroll flag.
    # The scroll-to-section-5 dcc.Store lives in the layout; the
    # clientside callback below watches it and scrolls after the
    # story DOM re-renders.
    @app.callback(
        Output("view-store", "data", allow_duplicate=True),
        Output("came-from-story", "data", allow_duplicate=True),
        Output("scroll-to-section-5", "data", allow_duplicate=True),
        Input("back-to-story-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def back_to_story(_n_clicks):
        return "story", False, True

    # Clientside: after the story re-renders and scroll flag is set,
    # scroll to section 5. Uses a retry loop since the DOM may not be
    # fully painted when the flag fires.
    app.clientside_callback(
        """
        function(shouldScroll) {
            if (!shouldScroll) { return false; }
            var attempts = 0;
            var tryScroll = function() {
                var target = document.getElementById('story-section-5');
                if (target) {
                    target.scrollIntoView({behavior: 'smooth', block: 'start'});
                } else if (attempts++ < 20) {
                    setTimeout(tryScroll, 100);
                }
            };
            setTimeout(tryScroll, 150);
            return false;
        }
        """,
        Output("scroll-to-section-5", "data"),
        Input("scroll-to-section-5", "data"),
        prevent_initial_call=True,
    )
