"""Distribution Pruning decision mode -- Dash layout and callbacks.

Ported from velocity_tool.py render_distribution_pruning() (lines 2930-3247).
Business logic, SQL queries, chart construction, and metric calculations
are IDENTICAL to the original Streamlit version.

TWO tabs: By SKU and By Store (no third tab).
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
    metric_card,
    row_count_line,
    status_legend,
)
from constants import (
    GREY,
    GREY_BG,
    INK,
    CHICAGO,
    ORANGE,
    ORANGE_FAINT,
    RED,
    RED_FAINT,
    PRUNING_SEVERITY_COLORS,
    THRESHOLDS,
)
from data import get_latest_week, get_pruning_data


# ============================================================
# Layout
# ============================================================

def layout(
    retailer: str,
    threshold: float,
    product_line: str | None,
) -> html.Div:
    """Return the full Dash component tree for Distribution Pruning."""
    try:
        latest = get_latest_week()
        pairs = get_pruning_data(retailer, product_line)
    except Exception as exc:
        return error_card(
            "Distribution Pruning query failed",
            f"Could not load pruning data for {retailer}: {exc}",
        )

    # Caption
    caption_text = (
        f"Retailer: {retailer}  |  Delisting threshold: "
        f"{threshold:.2f} units/store/week  |  Window: last 13 weeks  "
        f"|  Most recent week: {latest}"
    )

    if pairs.empty:
        msg = f"No active SKU x store combinations at {retailer}"
        if product_line:
            msg += f" in {product_line}"
        return html.Div([
            html.P(caption_text, style={"color": GREY, "fontSize": "0.85rem"}),
            empty_state(msg + "."),
        ])

    # Bottom 20% threshold across this retailer's pairs
    p20 = pairs["velocity"].quantile(0.20)
    median_v = pairs["velocity"].median()

    pairs["below_threshold"] = pairs["velocity"] < threshold
    pairs["bottom_20"] = pairs["velocity"] <= p20
    pairs["shelf_cost"] = ((median_v - pairs["velocity"]) * pairs["wholesale_price"]).round(2)

    n_pairs = len(pairs)
    n_below = int(pairs["below_threshold"].sum())
    n_skus = pairs["sku"].nunique()
    n_stores = pairs["store_id"].nunique()
    n_skus_affected = pairs.loc[pairs["below_threshold"], "sku"].nunique()
    n_stores_affected = pairs.loc[pairs["below_threshold"], "store_id"].nunique()

    # Headline
    if n_below > 0:
        affected_stores = sorted(
            pairs.loc[pairs["below_threshold"], "store_id"].unique().tolist()
        )
        if len(affected_stores) <= 10:
            stores_phrase = (
                f"{n_stores_affected} store{'s' if n_stores_affected != 1 else ''} "
                f"affected: {', '.join(affected_stores)}"
            )
        else:
            stores_phrase = (
                f"across {n_stores_affected} stores — switch to the By Store "
                f"tab for store-level detail"
            )
        headline = (
            f"{n_below:,} of {n_pairs:,} SKU × store combinations at "
            f"{retailer} are below the delisting threshold of {threshold:.2f} "
            f"units/store/week — concentrated in {n_skus_affected} "
            f"SKU{'s' if n_skus_affected != 1 else ''}.  {stores_phrase}."
        )
    else:
        headline = (
            f"Every active SKU x store combination at {retailer} is at or above "
            f"the {threshold:.2f} threshold."
        )

    # Insight
    if n_below > 0:
        total_shelf_cost = int(pairs.loc[pairs["below_threshold"], "shelf_cost"].sum())
        insight = (
            f"Underperforming pairs represent ${total_shelf_cost:,}/week in "
            f"unrealized margin vs the median. Pruning the weakest "
            f"frees shelf space for higher-velocity SKUs."
        )
    else:
        insight = (
            f"All {n_pairs:,} active placements are above {threshold:.2f} "
            f"units/store/week — the portfolio is earning its shelf space."
        )

    # ---------- BY SKU tab ----------
    sku_tab_children = _build_sku_tab(pairs, threshold, retailer, product_line)

    # ---------- BY STORE tab ----------
    store_tab_children = _build_store_tab(pairs, threshold, retailer, product_line)

    return html.Div(
        className="dash-layout",
        children=[
            html.Div([
                html.H3(headline, className="dh-headline"),
                html.P(insight, className="dh-insight"),
                html.P(caption_text, className="dh-caption"),
                html.Div(
                    [
                        html.Div(metric_card("Active pairs", f"{n_pairs:,}"), className="dh-metric"),
                        html.Div(metric_card("Below threshold", f"{n_below:,}"), className="dh-metric"),
                        html.Div(metric_card("SKUs affected", f"{n_skus_affected} / {n_skus}"), className="dh-metric"),
                        html.Div(metric_card("Stores affected", f"{n_stores_affected} / {n_stores}"), className="dh-metric"),
                    ],
                    className="dh-metrics",
                ),
            ]),
            html.Div(
                style={"flex": "1", "minHeight": "400px"},
                children=[
                    dbc.Tabs([
                        dbc.Tab(label="By SKU", children=sku_tab_children),
                        dbc.Tab(label="By Store", children=store_tab_children),
                    ]),
                ],
            ),
            dcc.Download(id="pruning-sku-download"),
            dcc.Download(id="pruning-store-download"),
        ],
    )


# ============================================================
# Tab builders
# ============================================================

def _build_sku_tab(
    pairs: pd.DataFrame,
    threshold: float,
    retailer: str,
    product_line: str | None,
) -> list:
    """Build the children list for the By SKU tab."""
    by_sku = (
        pairs.groupby(["sku", "product_name", "product_line"])
        .agg(
            stores_below=("below_threshold", "sum"),
            total_stores=("store_id", "count"),
            avg_velocity=("velocity", "mean"),
        )
        .reset_index()
    )
    by_sku["pct_below"] = (by_sku["stores_below"] / by_sku["total_stores"] * 100).round(2)
    by_sku = by_sku[by_sku["stores_below"] > 0].sort_values(
        ["pct_below", "stores_below"], ascending=[False, False]
    ).reset_index(drop=True)

    if by_sku.empty:
        return [
            html.Div(
                "No SKUs have any stores below threshold — nothing to prune here.",
                style={"padding": "1.5rem", "color": GREY, "fontSize": "1rem"},
            ),
        ]

    crit_pct = THRESHOLDS["pruning_sku_critical"] * 100
    conc_pct = THRESHOLDS["pruning_sku_concerning"] * 100

    def severity(p: float) -> str:
        if p >= crit_pct:
            return "Critical"
        if p >= conc_pct:
            return "Concerning"
        return "Mild"

    by_sku["Severity"] = by_sku["pct_below"].apply(severity)

    display_sku = pd.DataFrame({
        "SKU":               by_sku["sku"],
        "Product Name":      by_sku["product_name"],
        "Product Line":      by_sku["product_line"],
        "# Stores Below Threshold": by_sku["stores_below"].astype(int),
        "# Total Stores":    by_sku["total_stores"].astype(int),
        "% Below Threshold": by_sku["pct_below"],
        "Avg Velocity":      by_sku["avg_velocity"].round(2),
        "Severity":          by_sku["Severity"],
    })

    n_crit = int((display_sku["Severity"] == "Critical").sum())
    n_conc = int((display_sku["Severity"] == "Concerning").sum())
    n_mild = int((display_sku["Severity"] == "Mild").sum())

    # AG Grid column defs
    column_defs = [
        {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 110},
        {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
        {"field": "Product Line", "headerName": "Product Line", "sortable": True, "filter": True, "width": 130},
        {"field": "# Stores Below Threshold", "headerName": "# Stores Below Threshold",
         "sortable": True, "filter": "agNumberColumnFilter", "width": 190},
        {"field": "# Total Stores", "headerName": "# Total Stores",
         "sortable": True, "filter": "agNumberColumnFilter", "width": 130},
        {"field": "% Below Threshold", "headerName": "% Below Threshold",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format(',.2f')(params.value) + '%'"}},
        {"field": "Avg Velocity", "headerName": "Avg Velocity",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format(',.2f')(params.value)"}},
        {"field": "Severity", "headerName": "Severity", "sortable": True, "filter": True, "width": 110},
    ]

    row_style_conditions = [
        {
            "condition": "params.data.Severity === 'Critical'",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
        {
            "condition": "params.data.Severity === 'Concerning'",
            "style": {"backgroundColor": ORANGE_FAINT, "color": ORANGE},
        },
        {
            "condition": "params.data.Severity === 'Mild'",
            "style": {"backgroundColor": GREY_BG, "color": CHICAGO},
        },
    ]

    grid = make_grid(
        display_sku,
        column_defs=column_defs,
        row_style_conditions=row_style_conditions,
        id="pruning-sku-grid",
    )

    # Chart: top SKUs by % below threshold
    n_show = min(15, len(by_sku))
    top = by_sku.head(n_show).copy()
    top["_label"] = top["sku"] + " · " + top["product_name"].str.slice(0, 26)

    fig = go.Figure()
    for sev in ("Critical", "Concerning", "Mild"):
        sub = top[top["Severity"] == sev]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["_label"],
            x=sub["pct_below"], orientation="h",
            marker_color=PRUNING_SEVERITY_COLORS[sev],
            text=sub["pct_below"].map(lambda v: f"{v:.0f}%"),
            textposition="outside", textfont=dict(size=12, color=INK),
            cliponaxis=False,
            customdata=sub[["stores_below", "total_stores", "avg_velocity"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "%{customdata[0]} of %{customdata[1]} stores below threshold "
                "(%{x:.2f}%)<br>"
                "Avg velocity: %{customdata[2]:.2f}<br>"
                f"Severity: {sev}<extra></extra>"
            ),
        ))
    chart_labels = top["_label"].tolist()
    apply_hbar_layout(
        fig,
        labels=chart_labels,
        height=max(420, 34 * n_show + 120),
        x_title="% of stores below delisting threshold",
    )
    fig.update_yaxes(categoryorder="array", categoryarray=chart_labels)

    chart_title = (
        f"These {n_show} SKUs have the highest share of "
        f"underperforming stores at {retailer}"
    )
    chart_caption = (
        f"Bars show what % of each SKU's stores fall below the "
        f"delisting threshold. Red ≥{crit_pct:.2f}%, orange "
        f"{conc_pct:.2f}–{crit_pct:.2f}%, navy <{conc_pct:.2f}%."
    )

    # Excel export data
    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")

    return [
        status_legend([
            html.B("Severity"),
            f" = % of this SKU's stores below the {threshold:.2f} threshold. ",
            html.B("Critical", style={"color": RED}),
            f" ≥ {crit_pct:.2f}%. ",
            html.B("Concerning", style={"color": ORANGE}),
            f" = {conc_pct:.2f}% to < {crit_pct:.2f}%. ",
            html.B("Mild", style={"color": CHICAGO}),
            f" < {conc_pct:.2f}%.",
        ]),
        row_count_line("SKUs", [
            (n_crit, "Critical"),
            (n_conc, "Concerning"),
            (n_mild, "Mild"),
        ]),
        html.Div(
            style={"display": "flex", "gap": "1.5rem", "height": "calc(100vh - 380px)", "minHeight": "300px"},
            children=[
                html.Div([grid], style={"flex": "1", "minWidth": "0", "overflow": "hidden"}),
                html.Div([
                    html.H4(chart_title, style={"marginTop": "0"}),
                    html.P(chart_caption, style={"color": GREY, "fontSize": "0.85rem"}),
                    chart_legend([
                        (RED,      f"Critical (≥{crit_pct:.2f}% of stores below threshold)"),
                        (ORANGE,   f"Concerning ({conc_pct:.2f}% to <{crit_pct:.2f}%)"),
                        (CHICAGO, f"Mild (<{conc_pct:.2f}%)"),
                    ]),
                    dcc.Graph(figure=fig, id="pruning-sku-chart", responsive=True, style={"width": "100%"}),
                ], style={"flex": "1", "minWidth": "0", "overflowY": "auto"}),
            ],
        ),
        html.Button(
            "Export By SKU to Excel", id="pruning-sku-export-btn", n_clicks=0,
            style={"padding": "0.4rem 1.2rem", "cursor": "pointer", "marginTop": "0.5rem"},
        ),
        dcc.Store(
            id="pruning-sku-table-data",
            data={
                "records": display_sku.to_dict("records"),
                "filename": f"pruning_by_sku_{safe_ret}_{safe_pl}",
            },
        ),
    ]


def _build_store_tab(
    pairs: pd.DataFrame,
    threshold: float,
    retailer: str,
    product_line: str | None,
) -> list:
    """Build the children list for the By Store tab."""
    by_store = (
        pairs.groupby(["store_id", "retailer", "region", "state", "volume_tier"])
        .agg(
            skus_below=("below_threshold", "sum"),
            bottom_20=("bottom_20", "sum"),
            total_skus=("sku", "count"),
            avg_velocity=("velocity", "mean"),
        )
        .reset_index()
    )
    by_store = by_store.sort_values(
        ["skus_below", "bottom_20"], ascending=[False, False]
    ).reset_index(drop=True)

    # Severity by skus_below count
    store_crit = THRESHOLDS["pruning_store_critical"]
    store_conc = THRESHOLDS["pruning_store_concerning"]

    def store_sev(n: int) -> str:
        if n >= store_crit:
            return "Critical"
        if n >= store_conc:
            return "Concerning"
        return "Mild"

    by_store["Severity"] = by_store["skus_below"].apply(store_sev)

    display_store = pd.DataFrame({
        "Store ID":              by_store["store_id"],
        "Retailer":              by_store["retailer"],
        "Region":                by_store["region"],
        "State":                 by_store["state"],
        "Volume Tier":           by_store["volume_tier"],
        "# SKUs Below Threshold": by_store["skus_below"].astype(int),
        "# SKUs in Bottom 20%":  by_store["bottom_20"].astype(int),
        "# Total SKUs":          by_store["total_skus"].astype(int),
        "Avg Velocity":          by_store["avg_velocity"].round(2),
        "Severity":              by_store["Severity"],
    })

    n_crit = int((display_store["Severity"] == "Critical").sum())
    n_conc = int((display_store["Severity"] == "Concerning").sum())
    n_mild = int((display_store["Severity"] == "Mild").sum())

    # AG Grid column defs
    column_defs = [
        {"field": "Store ID", "headerName": "Store ID", "sortable": True, "filter": True, "width": 120},
        {"field": "Retailer", "headerName": "Retailer", "sortable": True, "filter": True, "width": 120},
        {"field": "Region", "headerName": "Region", "sortable": True, "filter": True, "width": 110},
        {"field": "State", "headerName": "State", "sortable": True, "filter": True, "width": 80},
        {"field": "Volume Tier", "headerName": "Volume Tier", "sortable": True, "filter": True, "width": 110},
        {"field": "# SKUs Below Threshold", "headerName": "# SKUs Below Threshold",
         "sortable": True, "filter": "agNumberColumnFilter", "width": 190},
        {"field": "# SKUs in Bottom 20%", "headerName": "# SKUs in Bottom 20%",
         "sortable": True, "filter": "agNumberColumnFilter", "width": 170},
        {"field": "# Total SKUs", "headerName": "# Total SKUs",
         "sortable": True, "filter": "agNumberColumnFilter", "width": 120},
        {"field": "Avg Velocity", "headerName": "Avg Velocity",
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "d3.format(',.2f')(params.value)"}},
        {"field": "Severity", "headerName": "Severity", "sortable": True, "filter": True, "width": 110},
    ]

    row_style_conditions = [
        {
            "condition": "params.data.Severity === 'Critical'",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
        {
            "condition": "params.data.Severity === 'Concerning'",
            "style": {"backgroundColor": ORANGE_FAINT, "color": ORANGE},
        },
        {
            "condition": "params.data.Severity === 'Mild'",
            "style": {"backgroundColor": GREY_BG, "color": CHICAGO},
        },
    ]

    grid = make_grid(
        display_store,
        column_defs=column_defs,
        row_style_conditions=row_style_conditions,
        id="pruning-store-grid",
    )

    # Excel export data
    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")

    return [
        status_legend([
            html.B("Severity"),
            f" = number of SKUs at this store below the {threshold:.2f} threshold. ",
            html.B("Critical", style={"color": RED}),
            f" ≥ {store_crit} SKUs. ",
            html.B("Concerning", style={"color": ORANGE}),
            f" = {store_conc}–{store_crit - 1} SKUs. ",
            html.B("Mild", style={"color": CHICAGO}),
            " = 0 SKUs below threshold.",
        ]),
        row_count_line("stores", [
            (n_crit, "Critical"),
            (n_conc, "Concerning"),
            (n_mild, "Mild"),
        ]),
        html.Div([grid], style={"height": "calc(100vh - 380px)", "minHeight": "300px", "overflowY": "auto"}),
        html.Button(
            "Export By Store to Excel", id="pruning-store-export-btn", n_clicks=0,
            style={"padding": "0.4rem 1.2rem", "cursor": "pointer", "marginTop": "0.5rem"},
        ),
        dcc.Store(
            id="pruning-store-table-data",
            data={
                "records": display_store.to_dict("records"),
                "filename": f"pruning_by_store_{safe_ret}_{safe_pl}",
            },
        ),
    ]


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register Distribution Pruning decision callbacks."""

    @app.callback(
        Output("pruning-sku-download", "data"),
        Input("pruning-sku-export-btn", "n_clicks"),
        Input("pruning-sku-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_pruning_sku(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "pruning-sku-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "Pruning by SKU", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])

    @app.callback(
        Output("pruning-store-download", "data"),
        Input("pruning-store-export-btn", "n_clicks"),
        Input("pruning-store-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_pruning_store(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "pruning-store-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "Pruning by Store", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])
