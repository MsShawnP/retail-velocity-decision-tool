"""SKU Rationalization decision mode -- Dash layout and callbacks.

Ported from velocity_tool.py render_sku_rationalization() (lines 3291-3709).
Business logic, SQL queries, chart construction, and metric calculations
are IDENTICAL to the original Streamlit version.

Includes quadrant analysis: Winners, Volume plays, Niche / slow, Cut candidates.
Two tabs: "Cut candidates" and "Portfolio overview".
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import Input, Output, callback_context, dcc, html, no_update

from charts import apply_hbar_layout
from components import (
    chart_legend,
    empty_state,
    error_card,
    excel_download_data,
    make_grid,
    row_count_line,
    status_legend,
)
from constants import (
    GREEN_FAINT,
    GREY,
    GREY_BG,
    GREY_LIGHT,
    NAVY,
    NAVY_MED,
    ORANGE,
    ORANGE_FAINT,
    RED,
    RED_FAINT,
    RETAILER_THRESHOLDS,
    TEAL,
)
from data import get_latest_week, get_rationalization_data


# ============================================================
# Quadrant colors (from velocity_tool.py)
# ============================================================

QUADRANT_COLORS = {
    "Winner":        TEAL,
    "Volume play":   NAVY_MED,
    "Niche / slow":  ORANGE,
    "Cut candidate": RED,
}

QUADRANT_ROW_BG = {
    "Winner":        GREEN_FAINT,
    "Volume play":   GREY_BG,
    "Niche / slow":  ORANGE_FAINT,
    "Cut candidate": RED_FAINT,
}


# ============================================================
# Quadrant card component (replicates velocity_tool.py quadrant_card)
# ============================================================

def _quadrant_card(title: str, subtitle: str, count: int, fg: str, bg: str) -> html.Div:
    return html.Div(
        [
            html.Div(title, style={
                "fontSize": "1rem", "fontWeight": "700", "color": fg,
            }),
            html.Div(subtitle, style={
                "fontSize": "0.78rem", "color": GREY, "marginBottom": "0.3rem",
            }),
            html.Div(str(count), style={
                "fontSize": "1.5rem", "fontWeight": "700", "color": fg,
            }),
        ],
        style={
            "backgroundColor": bg,
            "border": f"1px solid {GREY_LIGHT}",
            "borderRadius": "6px",
            "padding": "0.85rem 1rem 0.75rem 1rem",
            "boxShadow": "0 1px 2px rgba(27, 42, 74, 0.05)",
            "flex": "1",
        },
    )


# ============================================================
# Layout
# ============================================================

def layout(
    retailer: str,
    product_line: str | None,
) -> html.Div:
    """Return the full Dash component tree for SKU Rationalization."""
    threshold = RETAILER_THRESHOLDS.get(retailer, 1.0)
    if retailer == "All Retailers":
        threshold = 2.0
    latest = get_latest_week()

    caption_text = (
        f"Retailer scope: {retailer}  |  Window: last 13 weeks  "
        f"|  Velocity threshold for at-risk: {threshold:.2f} units/store/week  "
        f"|  Most recent week: {latest}"
    )

    try:
        df = get_rationalization_data(retailer, product_line)
    except Exception as exc:
        return error_card(
            "SKU Rationalization query failed",
            f"Could not load rationalization data for {retailer}: {exc}",
        )

    if df.empty:
        msg = f"No SKUs with recent activity at {retailer}"
        if product_line:
            msg += f" in {product_line}"
        return html.Div([
            html.P(caption_text, style={"color": GREY, "fontSize": "0.85rem"}),
            empty_state(msg + "."),
        ])

    median_velocity = df["velocity"].median()
    median_margin = df["margin_per_sw"].median()

    df["high_velocity"] = df["velocity"] > median_velocity
    df["high_margin"] = df["margin_per_sw"] > median_margin

    n_winners = int(((df["high_velocity"]) & (df["high_margin"])).sum())
    n_volume = int(((df["high_velocity"]) & (~df["high_margin"])).sum())
    n_niche = int(((~df["high_velocity"]) & (df["high_margin"])).sum())
    n_cut = int(((~df["high_velocity"]) & (~df["high_margin"])).sum())

    bottom_q = df["weekly_total_margin"].quantile(0.20)
    n_low_margin = int((df["weekly_total_margin"] <= bottom_q).sum())
    cut_candidates = df[(df["velocity"] < threshold) & (df["weekly_total_margin"] <= bottom_q)]
    n_cut_candidates = len(cut_candidates)

    # Headline
    if n_cut_candidates > 0:
        headline = (
            f"{n_low_margin} SKUs generate the bottom 20% of weekly gross margin "
            f"(≤ ${bottom_q:,.0f}/wk). {n_cut_candidates} of those are also below the "
            f"{threshold:.2f} velocity threshold — these are clear discontinuation candidates."
        )
    else:
        headline = (
            f"{n_low_margin} SKUs sit in the bottom 20% by weekly gross margin, "
            f"but none are also below the velocity threshold — pruning here would lose volume."
        )

    # Insight
    total_margin = int(df["weekly_total_margin"].sum())
    cut_margin = int(cut_candidates["weekly_total_margin"].sum()) if n_cut_candidates > 0 else 0
    if n_cut_candidates > 0:
        insight = (
            f"The portfolio generates ${total_margin:,}/week in gross margin. "
            f"The {n_cut_candidates} cut candidate{'s' if n_cut_candidates != 1 else ''} "
            f"contribute{'s' if n_cut_candidates == 1 else ''} only "
            f"${cut_margin:,}/week — discontinuing them frees resources "
            f"for the {n_winners} winners."
        )
    else:
        insight = (
            f"${total_margin:,}/week total gross margin across {len(df)} SKUs. "
            f"No clear cut candidates — every low-margin SKU still pulls enough "
            f"velocity to justify its shelf space."
        )

    # Quadrant label assignment
    def quadrant_label(row: pd.Series) -> str:
        if row["high_velocity"] and row["high_margin"]:
            return "Winner"
        if row["high_velocity"] and not row["high_margin"]:
            return "Volume play"
        if not row["high_velocity"] and row["high_margin"]:
            return "Niche / slow"
        return "Cut candidate"

    df["quadrant"] = df.apply(quadrant_label, axis=1)

    display_df = pd.DataFrame({
        "SKU":                df["sku"],
        "Product Name":       df["product_name"],
        "Product Line":       df["product_line"],
        "Quadrant":           df["quadrant"],
        "Velocity":           df["velocity"].round(2),
        "Margin/Unit":        df["margin_per_unit"],
        "Margin/Store/Week":  df["margin_per_sw"],
        "Doors":              df["doors"].astype(int),
        "Total Weekly Margin": df["weekly_total_margin"].astype(int),
    })
    quadrant_order = {"Cut candidate": 0, "Niche / slow": 1, "Volume play": 2, "Winner": 3}
    display_df = (
        display_df.assign(_q=display_df["Quadrant"].map(quadrant_order))
        .sort_values(["_q", "Total Weekly Margin"], ascending=[True, True])
        .drop(columns="_q").reset_index(drop=True)
    )

    # Build tabs
    cut_tab_children = _build_cut_tab(display_df, df, median_velocity, median_margin)
    portfolio_tab_children = _build_portfolio_tab(
        display_df, df, median_velocity, median_margin,
        n_winners, n_volume, n_niche, n_cut, retailer,
    )

    # Excel export filename parts
    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")

    return html.Div(
        className="dash-layout",
        children=[
        html.Div([
            html.H3(headline, className="dh-headline"),
            html.P(insight, className="dh-insight"),
            html.P(caption_text, className="dh-caption"),
            html.P(
                f"Median velocity = {median_velocity:.2f}. Median margin/store-week = "
                f"${median_margin:.2f}. Each SKU lands in one quadrant.",
                className="dh-caption",
            ),
            html.Div(
                [
                    _quadrant_card("Winners", "High velocity, high margin",
                                   n_winners, TEAL, GREEN_FAINT),
                    _quadrant_card("Volume plays", "High velocity, low margin",
                                   n_volume, NAVY_MED, GREY_BG),
                    _quadrant_card("Niche / slow movers", "Low velocity, high margin",
                                   n_niche, ORANGE, ORANGE_FAINT),
                    _quadrant_card("Cut candidates", "Low velocity, low margin",
                                   n_cut, RED, RED_FAINT),
                ],
                className="dh-metrics",
            ),
        ]),
        html.Div(
            style={"flex": "1", "minHeight": "0", "overflow": "hidden"},
            children=[
                dbc.Tabs([
                    dbc.Tab(label="Cut candidates", children=cut_tab_children),
                    dbc.Tab(label="Portfolio overview", children=portfolio_tab_children),
                ]),
            ],
        ),
        html.Div([
        html.Button(
            "Export to Excel",
            id="rationalization-export-btn",
            n_clicks=0,
            className="export-btn",
            style={"marginTop": "1rem"},
        ),
        dcc.Download(id="rationalization-download"),
        dcc.Store(
            id="rationalization-table-data",
            data={
                "records": display_df.to_dict("records"),
                "filename": f"sku_rationalization_{safe_ret}_{safe_pl}",
            },
        ),
        ]),
    ])


# ============================================================
# Tab builders
# ============================================================

def _build_cut_tab(
    display_df: pd.DataFrame,
    raw_df: pd.DataFrame,
    median_velocity: float,
    median_margin: float,
) -> list:
    """Build the children list for the Cut candidates tab."""
    cut_df = display_df[display_df["Quadrant"] == "Cut candidate"].copy()
    cut_df = cut_df.sort_values(
        "Total Weekly Margin", ascending=False
    ).reset_index(drop=True)

    if cut_df.empty:
        return [
            html.Div(
                "No SKUs landed in the Cut-candidate quadrant — every SKU is "
                "above at least one of the two medians. Switch to Portfolio "
                "overview to see the full matrix.",
                style={"padding": "1.5rem", "color": GREY, "fontSize": "1rem"},
            ),
        ]

    total_cut_margin = float(cut_df["Total Weekly Margin"].sum())
    cut_slots = int(cut_df["Doors"].sum())

    # Replacement opportunity from Winners
    winners_df = raw_df[raw_df["quadrant"] == "Winner"]
    have_winners = not winners_df.empty

    children: list = []

    children.append(
        html.H4("These SKUs have low velocity AND low margin — cut first",
                 style={"marginTop": "0.5rem"})
    )

    if have_winners:
        winner_med_msw = float(winners_df["margin_per_sw"].median())
        winner_med_vel = float(winners_df["velocity"].median())
        winner_med_mpu = float(winners_df["margin_per_unit"].median())
        projected_weekly = cut_slots * winner_med_msw
        net_weekly = projected_weekly - total_cut_margin
        net_annual = net_weekly * 52
        gain_or_loss = "gain" if net_weekly >= 0 else "loss"
        net_color = TEAL if net_weekly >= 0 else RED

        # Lede
        children.append(html.Div(
            style={"color": NAVY, "fontSize": "1rem", "lineHeight": "1.55",
                   "margin": "-0.2em 0 0.4em 0"},
            children=[
                "These ", html.B(f"{len(cut_df)} SKUs"), " currently earn ",
                html.B(f"${total_cut_margin:,.0f}/week"), " across ",
                html.B(f"{cut_slots:,}"), " shelf slots. At median Winner "
                "performance, the same shelf space would earn ",
                html.B(f"${projected_weekly:,.0f}/week"), " — a net ",
                html.B(
                    f"{gain_or_loss} of ${abs(net_weekly):,.0f}/week "
                    f"(${abs(net_annual):,.0f}/year)",
                    style={"color": net_color},
                ),
                " from replacement.",
            ],
        ))
        # Supporting math line
        children.append(html.Div(
            style={"color": GREY, "fontSize": "0.86em", "margin": "0 0 0.6em 0"},
            children=[
                "Median Winner: ", html.B(f"{winner_med_vel:.2f}"),
                " u/store/week × ", html.B(f"${winner_med_mpu:.2f}"),
                "/unit = ", html.B(f"${winner_med_msw:.2f}"),
                "/store/week. Cut candidates fall below both the median velocity "
                f"({median_velocity:.2f}) and the median margin per "
                f"store-week (${median_margin:.2f}).",
            ],
        ))
    else:
        children.append(html.Div(
            style={"color": GREY, "fontSize": "0.92em", "margin": "-0.4em 0 0.6em 0"},
            children=[
                html.B(f"{len(cut_df)} SKUs are cut candidates"),
                ", currently earning ",
                html.B(f"${total_cut_margin:,.0f}/wk"),
                f" across {cut_slots:,} shelf slots. Below both the median "
                f"velocity ({median_velocity:.2f}) and the median margin "
                f"per store-week (${median_margin:.2f}). No Winner SKUs "
                "in scope to project a replacement comparison against.",
            ],
        ))

    # Cut-candidate chart
    n_chart = min(20, len(cut_df))
    cut_chart = cut_df.head(n_chart).copy()
    cut_labels = (
        cut_chart["SKU"] + "  ·  " + cut_chart["Product Name"].str.slice(0, 26)
    ).tolist()

    fig_cut = go.Figure()
    fig_cut.add_trace(go.Bar(
        y=cut_chart["SKU"] + "  ·  " + cut_chart["Product Name"].str.slice(0, 26),
        x=cut_chart["Total Weekly Margin"],
        orientation="h",
        marker_color=RED,
        text=[
            f"${m:,.2f} · {int(d)} doors"
            for m, d in zip(cut_chart["Total Weekly Margin"], cut_chart["Doors"])
        ],
        textposition="outside",
        textfont=dict(size=14, color=NAVY),
        cliponaxis=False,
        customdata=cut_chart[
            ["Velocity", "Margin/Store/Week", "Doors"]
        ].values,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Total weekly margin: %{x:$,.2f}<br>"
            "Velocity: %{customdata[0]:.2f}<br>"
            "Margin/store/week: $%{customdata[1]:.2f}<br>"
            "Doors: %{customdata[2]}<br>"
            "Quadrant: Cut candidate<extra></extra>"
        ),
    ))
    apply_hbar_layout(
        fig_cut,
        labels=cut_labels,
        height=max(420, 34 * n_chart + 120),
        x_title="Total weekly gross margin ($)",
        label_pad_px=320,
        left_margin=340,
    )
    fig_cut.update_yaxes(categoryorder="array", categoryarray=cut_labels)

    # Cut-candidate table — all rows red-tinted
    cut_display = cut_df.drop(columns=["Quadrant"])
    cut_column_defs = [
        {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 110},
        {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
        {"field": "Product Line", "headerName": "Product Line", "sortable": True, "filter": True, "width": 130},
        {"field": "Velocity", "headerName": "Velocity", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
        {"field": "Margin/Unit", "headerName": "Margin/Unit", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "'$' + d3.format('.2f')(params.value)"}},
        {"field": "Margin/Store/Week", "headerName": "Margin/Store/Week",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "'$' + d3.format('.2f')(params.value)"}},
        {"field": "Doors", "headerName": "Doors", "sortable": True, "filter": "agNumberColumnFilter", "width": 90},
        {"field": "Total Weekly Margin", "headerName": "Total Weekly Margin",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "'$' + d3.format(',.2f')(params.value)"}},
    ]

    cut_row_style = [
        {
            "condition": "true",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
    ]

    cut_grid = make_grid(
        cut_display,
        column_defs=cut_column_defs,
        row_style_conditions=cut_row_style,
        id="rationalization-cut-grid",
    )
    children.append(html.Div(
        style={"display": "flex", "gap": "1.5rem", "height": "calc(100vh - 420px)", "minHeight": "250px"},
        children=[
            html.Div([cut_grid], style={"flex": "1", "minWidth": "0", "overflow": "hidden"}),
            html.Div(
                [dcc.Graph(figure=fig_cut, id="rationalization-cut-chart", responsive=True, style={"width": "100%"})],
                style={"flex": "1", "minWidth": "0", "overflowY": "auto"},
            ),
        ],
    ))

    return children


def _build_portfolio_tab(
    display_df: pd.DataFrame,
    raw_df: pd.DataFrame,
    median_velocity: float,
    median_margin: float,
    n_winners: int,
    n_volume: int,
    n_niche: int,
    n_cut: int,
    retailer: str,
) -> list:
    """Build the children list for the Portfolio overview tab."""
    children: list = []

    children.append(status_legend([
        html.B("Quadrant cutoffs:"),
        " Median velocity = ",
        html.B(f"{median_velocity:.2f}"),
        " units/store/week. Median margin per store-week = ",
        html.B(f"${median_margin:.2f}"),
        ". ",
        html.B("Winner", style={"color": TEAL}),
        " = above both medians. ",
        html.B("Volume play", style={"color": NAVY_MED}),
        " = high velocity, low margin. ",
        html.B("Niche / slow", style={"color": ORANGE}),
        " = low velocity, high margin. ",
        html.B("Cut candidate", style={"color": RED}),
        " = below both medians.",
    ]))
    children.append(row_count_line("SKUs", [
        (n_winners, "Winners"),
        (n_volume, "Volume plays"),
        (n_niche, "Niche / slow"),
        (n_cut, "Cut candidates"),
    ]))

    # AG Grid with per-cell coloring on the Quadrant column
    column_defs = [
        {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 110},
        {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
        {"field": "Product Line", "headerName": "Product Line", "sortable": True, "filter": True, "width": 130},
        {"field": "Quadrant", "headerName": "Quadrant", "sortable": True, "filter": True, "width": 140,
         "cellStyle": {"styleConditions": [
             {"condition": "params.value === 'Winner'",
              "style": {"color": TEAL, "fontWeight": "700"}},
             {"condition": "params.value === 'Volume play'",
              "style": {"color": NAVY_MED, "fontWeight": "700"}},
             {"condition": "params.value === 'Niche / slow'",
              "style": {"color": ORANGE, "fontWeight": "700"}},
             {"condition": "params.value === 'Cut candidate'",
              "style": {"color": RED, "fontWeight": "700"}},
         ]}},
        {"field": "Velocity", "headerName": "Velocity", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
        {"field": "Margin/Unit", "headerName": "Margin/Unit", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "'$' + d3.format('.2f')(params.value)"}},
        {"field": "Margin/Store/Week", "headerName": "Margin/Store/Week",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "'$' + d3.format('.2f')(params.value)"}},
        {"field": "Doors", "headerName": "Doors", "sortable": True, "filter": "agNumberColumnFilter", "width": 90},
        {"field": "Total Weekly Margin", "headerName": "Total Weekly Margin",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "'$' + d3.format(',.2f')(params.value)"}},
    ]

    row_style_conditions = [
        {
            "condition": "params.data.Quadrant === 'Winner'",
            "style": {"backgroundColor": GREEN_FAINT, "color": TEAL},
        },
        {
            "condition": "params.data.Quadrant === 'Volume play'",
            "style": {"backgroundColor": GREY_BG, "color": NAVY_MED},
        },
        {
            "condition": "params.data.Quadrant === 'Niche / slow'",
            "style": {"backgroundColor": ORANGE_FAINT, "color": ORANGE},
        },
        {
            "condition": "params.data.Quadrant === 'Cut candidate'",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
    ]

    grid = make_grid(
        display_df,
        column_defs=column_defs,
        row_style_conditions=row_style_conditions,
        id="rationalization-portfolio-grid",
    )

    # Bottom 15 by total weekly margin chart
    n_show = min(15, len(display_df))
    bottom = (
        display_df.nsmallest(n_show, "Total Weekly Margin")
        .sort_values("Total Weekly Margin", ascending=False)
        .reset_index(drop=True)
        .copy()
    )
    LOW_DIST = "Low distribution"

    def _chart_bucket(q: str) -> str:
        if q in ("Winner", "Volume play"):
            return LOW_DIST
        return q

    bottom["ChartBucket"] = bottom["Quadrant"].apply(_chart_bucket)
    CHART_BUCKET_COLORS = {
        LOW_DIST:        NAVY_MED,
        "Niche / slow":  ORANGE,
        "Cut candidate": RED,
    }

    fig = go.Figure()
    for bucket in (LOW_DIST, "Niche / slow", "Cut candidate"):
        sub = bottom[bottom["ChartBucket"] == bucket]
        if sub.empty:
            continue
        bar_text = [
            f"${margin:,.2f} · {bucket} ({int(doors)} doors)"
            for margin, doors in zip(sub["Total Weekly Margin"], sub["Doors"])
        ]
        fig.add_trace(go.Bar(
            y=sub["SKU"] + "  ·  " + sub["Product Name"].str.slice(0, 26),
            x=sub["Total Weekly Margin"], orientation="h",
            marker_color=CHART_BUCKET_COLORS[bucket],
            text=bar_text,
            textposition="outside", textfont=dict(size=14, color=NAVY),
            cliponaxis=False,
            customdata=sub[["Velocity", "Margin/Store/Week", "Doors", "Quadrant"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Total weekly margin: %{x:$,.2f}<br>"
                "Velocity: %{customdata[0]:.2f}<br>"
                "Margin/store/week: $%{customdata[1]:.2f}<br>"
                "Doors: %{customdata[2]}<br>"
                "Underlying quadrant: %{customdata[3]}<br>"
                f"Chart bucket: {bucket}<extra></extra>"
            ),
        ))
    bottom_labels = (bottom["SKU"] + "  ·  " + bottom["Product Name"].str.slice(0, 26)).tolist()
    apply_hbar_layout(
        fig,
        labels=bottom_labels,
        height=max(420, 34 * n_show + 120),
        x_title="Total weekly gross margin ($)",
        label_pad_px=320,
        left_margin=340,
    )
    fig.update_yaxes(categoryorder="array", categoryarray=bottom_labels)

    children.append(html.Div(
        style={"display": "flex", "gap": "1.5rem", "height": "calc(100vh - 380px)", "minHeight": "250px"},
        children=[
            html.Div([grid], style={"flex": "1", "minWidth": "0", "overflow": "hidden"}),
            html.Div(
                [
                    html.H4(
                        f"Bottom {n_show} SKUs by weekly margin — should they stay or go?",
                        style={"marginTop": "0"},
                    ),
                    html.Div(
                        style={"color": GREY, "fontSize": "0.92em", "margin": "0 0 0.4em 0"},
                        children=[
                            "Low total margin doesn't always mean cut. ",
                            html.Span("Low distribution", style={"color": NAVY_MED, "fontWeight": "600"}),
                            " (navy) = strong per-store performance but too few doors to generate "
                            "meaningful total margin — consider expanding distribution rather "
                            "than cutting. ",
                            html.Span("Niche / slow", style={"color": ORANGE, "fontWeight": "600"}),
                            " (orange) = low velocity but high margin per unit — selective "
                            "expansion may help. ",
                            html.Span("Cut candidates", style={"color": RED, "fontWeight": "600"}),
                            " (red) have low velocity AND low margin — kill first. "
                            f"Median velocity = {median_velocity:.2f} units/store/week, median "
                            f"margin per store-week = ${median_margin:.2f}.",
                        ],
                    ),
                    chart_legend([
                        (NAVY_MED, "Low distribution (Winner / Volume play, too few doors)"),
                        (ORANGE,   "Niche / slow (low velocity, high margin)"),
                        (RED,      "Cut candidate (below both medians)"),
                    ]),
                    dcc.Graph(figure=fig, id="rationalization-portfolio-chart", responsive=True, style={"width": "100%"}),
                ],
                style={"flex": "1", "minWidth": "0", "overflowY": "auto"},
            ),
        ],
    ))

    return children


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register SKU Rationalization decision callbacks."""

    @app.callback(
        Output("rationalization-download", "data"),
        Input("rationalization-export-btn", "n_clicks"),
        Input("rationalization-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_rationalization(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "rationalization-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "SKU Rationalization", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])
