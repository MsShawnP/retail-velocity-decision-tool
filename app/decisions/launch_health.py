"""Launch Health decision mode -- Dash layout and callbacks.

Ported from velocity_tool.py render_launch_health() (lines 3824-4001).
Business logic, SQL queries, chart construction, and metric calculations
are IDENTICAL to the original Streamlit version.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback_context, dcc, html, no_update

from charts import add_vline_at_date, apply_hbar_layout, base_chart_layout, text_annotation
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
    GREY,
    GREY_LIGHT,
    GREEN_FAINT,
    INK,
    LAUNCH_BENCHMARK,
    ORANGE,
    ORANGE_FAINT,
    RED,
    RED_FAINT,
    TEAL,
    TEXT_SEC,
    THRESHOLDS,
    TREND_PALETTE,
)
from data import get_latest_week, get_launch_data, get_launch_velocity_curve, get_launch_weekly


# ============================================================
# Classifier (from velocity_tool.py classify_launch)
# ============================================================

def _classify_launch(row: pd.Series, threshold: float) -> str:
    on_track_retention = THRESHOLDS["launch_on_track"]
    failing_floor = THRESHOLDS["launch_failing"]
    initial = row["v_w14"]
    current = row["v_current"]
    if pd.isna(current):
        return "Needs Attention"
    if pd.isna(initial):
        return "On Track" if current >= threshold else "Needs Attention"
    if current >= threshold:
        return "Needs Attention" if current < initial * on_track_retention else "On Track"
    if current < initial * on_track_retention:
        return "Failing"
    if current < threshold * failing_floor:
        return "Failing"
    return "Needs Attention"


# ============================================================
# Status colors and row tints
# ============================================================

LAUNCH_STATUS_COLORS = {
    "On Track": TEAL,
    "Needs Attention": ORANGE,
    "Failing": RED,
}


# ============================================================
# Layout
# ============================================================

def layout() -> html.Div:
    """Return the full Dash component tree for Launch Health."""
    threshold = LAUNCH_BENCHMARK
    latest = get_latest_week()

    try:
        df = get_launch_data()
    except Exception as exc:
        return error_card(
            "Launch Health query failed",
            f"Could not load launch data: {exc}",
        )

    if df.empty:
        return empty_state("No SKUs have launched in the last 52 weeks.")

    df["status"] = df.apply(lambda r: _classify_launch(r, threshold), axis=1)
    n_total = len(df)
    n_track = int((df["status"] == "On Track").sum())
    n_attn = int((df["status"] == "Needs Attention").sum())
    n_fail = int((df["status"] == "Failing").sum())

    # Headline
    if n_fail > 0:
        headline = (
            f"{n_total} SKUs launched in the last 52 weeks. "
            f"{n_track} on track, {n_attn} need attention, {n_fail} failing."
        )
    else:
        headline = (
            f"{n_total} SKUs launched in the last 52 weeks. "
            f"{n_track} on track, {n_attn} need attention, none currently failing."
        )

    # Insight
    if n_fail > 0:
        insight = (
            f"{n_fail} launch{'es' if n_fail != 1 else ''} falling below "
            f"the velocity benchmark — act now before retailers "
            f"question the placement. {n_track} are building momentum."
        )
    elif n_attn > 0:
        insight = (
            f"No launches are failing, but {n_attn} need a velocity boost "
            f"to stay on track. Early intervention prevents delisting conversations."
        )
    else:
        insight = (
            f"All {n_total} recent launches are on track — "
            f"velocity is meeting or exceeding the benchmark across the board."
        )

    # Caption
    caption_text = (
        f"All SKUs whose first authorization was within the last 52 weeks  |  "
        f"Velocity benchmark: {threshold:.2f} units/store/week (Walmart standard)  |  "
        f"Most recent week: {latest}"
    )

    # Status legend
    on_track_pct = THRESHOLDS["launch_on_track"] * 100
    failing_pct = THRESHOLDS["launch_failing"] * 100
    legend_children = [
        html.B("Status definitions"),
        f" (current vs first-4-weeks velocity, benchmark = {threshold:.2f} units/store/week): ",
        html.B("On Track", style={"color": TEAL}),
        f" = current ≥ benchmark and holding ≥ {on_track_pct:.2f}% of initial. ",
        html.B("Needs Attention", style={"color": ORANGE}),
        " = above benchmark but trending down, or modestly below benchmark. ",
        html.B("Failing", style={"color": RED}),
        f" = current < {failing_pct:.2f}% of benchmark, or current < {on_track_pct:.2f}% of initial AND below benchmark.",
    ]

    # Build display DataFrame
    display_df = pd.DataFrame({
        "SKU":           df["sku"],
        "Product Name":  df["product_name"],
        "Product Line":  df["product_line"],
        "Launch Date":   df["launch_date"],
        "Weeks Since":   df["weeks_since_launch"].astype(int),
        "Wks 1-4 Vel":   df["v_w14"].round(2),
        "Wks 5-8 Vel":   df["v_w58"].round(2),
        "Wks 9-13 Vel":  df["v_w913"].round(2),
        "Wks 14+ Vel":   df["v_w14plus"].round(2),
        "Current Vel":   df["v_current"].round(2),
        "Status":        df["status"],
    })
    status_order = {"Failing": 0, "Needs Attention": 1, "On Track": 2}
    display_df = (
        display_df.assign(_o=display_df["Status"].map(status_order))
        .sort_values(["_o", "Launch Date"], ascending=[True, False])
        .drop(columns="_o")
        .reset_index(drop=True)
    )

    # AG Grid column defs
    column_defs = [
        {"field": "SKU", "headerName": "SKU", "sortable": True, "filter": True, "width": 110},
        {"field": "Product Name", "headerName": "Product Name", "sortable": True, "filter": True, "flex": 1},
        {"field": "Product Line", "headerName": "Product Line", "sortable": True, "filter": True, "width": 130},
        {"field": "Launch Date", "headerName": "Launch Date", "sortable": True, "filter": True, "width": 120},
        {"field": "Weeks Since", "headerName": "Weeks Since", "sortable": True, "filter": "agNumberColumnFilter", "width": 110},
        {"field": "Wks 1-4 Vel", "headerName": "Wks 1-4 Vel", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.2f')(params.value)"}},
        {"field": "Wks 5-8 Vel", "headerName": "Wks 5-8 Vel", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.2f')(params.value)"}},
        {"field": "Wks 9-13 Vel", "headerName": "Wks 9-13 Vel", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.2f')(params.value)"}},
        {"field": "Wks 14+ Vel", "headerName": "Wks 14+ Vel", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.2f')(params.value)"}},
        {"field": "Current Vel", "headerName": "Current Vel", "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.2f')(params.value)"}},
        {"field": "Status", "headerName": "Status", "sortable": True, "filter": True, "width": 130},
    ]

    # Row style conditions
    row_style_conditions = [
        {
            "condition": "params.data.Status === 'Failing'",
            "style": {"backgroundColor": RED_FAINT, "color": RED},
        },
        {
            "condition": "params.data.Status === 'Needs Attention'",
            "style": {"backgroundColor": ORANGE_FAINT, "color": ORANGE},
        },
        {
            "condition": "params.data.Status === 'On Track'",
            "style": {"backgroundColor": GREEN_FAINT, "color": TEAL},
        },
    ]

    grid = make_grid(
        display_df,
        column_defs=column_defs,
        row_style_conditions=row_style_conditions,
        id="launch-health-grid",
    )

    # Chart: horizontal bar showing current velocity per launch
    n_show = min(15, len(display_df))
    chart_df = display_df.nsmallest(n_show, "Current Vel").copy()
    chart_title = (
        f"The {n_show} weakest launches by current velocity"
        if n_fail > 0
        else f"The {n_show} lowest-velocity launches (none currently failing)"
    )
    chart_caption = (
        f"Sorted weakest to strongest. Bars to the left of the dashed line "
        f"({threshold:.2f}) are below the Walmart benchmark."
    )

    fig = go.Figure()
    for status_val in ("Failing", "Needs Attention", "On Track"):
        sub = chart_df[chart_df["Status"] == status_val]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["SKU"], x=sub["Current Vel"], orientation="h",
            marker_color=LAUNCH_STATUS_COLORS[status_val],
            text=sub["Current Vel"].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—"),
            textposition="outside", textfont=dict(size=12, color=INK),
            cliponaxis=False,
            customdata=sub[["Product Name", "Wks 1-4 Vel", "Weeks Since"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "Current: %{x:.2f} units/store/wk<br>"
                "Wks 1-4 Vel: %{customdata[1]:.2f}<br>"
                "Weeks since launch: %{customdata[2]}<br>"
                f"Status: {status_val}<extra></extra>"
            ),
        ))
    fig.add_vline(
        x=threshold, line_dash="dash", line_color=GREY, line_width=2,
        annotation=text_annotation(f"Velocity benchmark {threshold:.2f}"),
        annotation_position="top",
    )
    apply_hbar_layout(
        fig,
        labels=chart_df["SKU"].tolist(),
        height=max(380, 32 * n_show + 120),
        x_title="Units per store per week (current 4-week average)",
        label_pad_px=110,
        left_margin=130,
    )

    # Velocity curve overview for failing / needs-attention launches
    trend_chart_elements = []
    watch_skus = df.loc[df["status"].isin(["Failing", "Needs Attention"]), "sku"].tolist()
    if watch_skus:
        trend_fig = go.Figure()
        name_map = dict(zip(df["sku"], df["product_name"]))
        # Distinct palette so each SKU is visually separable
        for i, sku in enumerate(watch_skus):
            curve = get_launch_velocity_curve(sku)
            if curve.empty:
                continue
            color = TREND_PALETTE[i % len(TREND_PALETTE)]
            trend_fig.add_trace(go.Scatter(
                x=curve["weeks_since_launch"],
                y=curve["avg_velocity"],
                mode="lines+markers",
                name=f"{sku} — {name_map.get(sku, '')}",
                line=dict(color=color, width=2.5),
                marker=dict(size=4, color=color),
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Week %{x}: %{y:.2f} units/store<extra></extra>"
                ),
            ))
        trend_fig.add_hline(
            y=threshold, line_dash="dash", line_color=GREY, line_width=2,
            annotation_text=f"Benchmark {threshold:.2f}",
            annotation_position="top left",
        )
        layout_kw = base_chart_layout(
            height=480, x_title="Weeks since launch", y_title="Avg units/store/week",
            show_legend=True,
        )
        # Compute y range that includes data AND the benchmark line
        _yvals = []
        for _t in trend_fig.data:
            if hasattr(_t, "y") and _t.y is not None:
                _yvals.extend([v for v in _t.y if v is not None])
        _yvals.append(threshold)
        _ymin, _ymax = min(_yvals), max(_yvals)
        _ypad = max((_ymax - _ymin) * 0.10, 0.2)
        layout_kw["yaxis"]["range"] = [max(0, _ymin - _ypad), _ymax + _ypad]
        layout_kw["yaxis"]["autorange"] = False
        layout_kw["margin"] = dict(l=50, r=10, t=40, b=100)
        layout_kw["legend"] = dict(
            orientation="h", yanchor="top", y=-0.18,
            xanchor="center", x=0.5, font=dict(size=11),
        )
        trend_fig.update_layout(**layout_kw)
        trend_chart_elements = [
            html.H4(
                "Velocity since launch — failing & needs-attention SKUs",
                style={"marginTop": "1.5rem"},
            ),
            dcc.Graph(figure=trend_fig, id="launch-trend-chart", responsive=True, style={"width": "100%"}),
        ]

    # Build dropdown options for drilldown
    drill_df = display_df.copy()
    drill_df["label"] = (
        drill_df["SKU"] + "  ·  " + drill_df["Product Name"]
        + "  (" + drill_df["Status"] + ")"
    )
    drill_options = [
        {"label": row["label"], "value": row["SKU"]}
        for _, row in drill_df.iterrows()
    ]

    failing_drop_pct = (1 - THRESHOLDS["launch_on_track"]) * 100
    failing_floor_val = THRESHOLDS["launch_failing"]
    detail_legend = chart_legend([
        (TEAL,   f"On Track (≥{threshold:.2f}, holding ≥{on_track_pct:.2f}% of initial)"),
        (ORANGE, f"Needs Attention ({threshold * failing_floor_val:.2f}–{threshold:.2f}, or slipping)"),
        (RED,    f"Failing (<{threshold * failing_floor_val:.2f} or down ≥{failing_drop_pct:.2f}% from start)"),
    ])

    # Assemble the full component tree
    return dashboard_layout(
        header=[
            html.H3(headline, className="dh-headline"),
            html.P(insight, className="dh-insight"),
            html.P(caption_text, className="dh-caption"),
            html.Div(
                [
                    html.Div(metric_card("Launched in last 52 wk", str(n_total)), className="dh-metric"),
                    html.Div(metric_card("On Track", str(n_track)), className="dh-metric"),
                    html.Div(metric_card("Needs Attention", str(n_attn)), className="dh-metric"),
                    html.Div(metric_card("Failing", str(n_fail)), className="dh-metric"),
                ],
                className="dh-metrics",
            ),
            status_legend(legend_children),
            row_count_line("launches", [
                (n_track, "On Track"),
                (n_attn, "Needs Attention"),
                (n_fail, "Failing"),
            ]),
        ],
        grid=grid,
        chart=[
            html.H4(chart_title, style={"marginTop": "0"}),
            html.P(chart_caption, style={"color": GREY, "fontSize": "0.85rem"}),
            chart_legend([
                (RED,    "Failing"),
                (ORANGE, "Needs Attention"),
                (TEAL,   "On Track"),
            ]),
            dcc.Graph(figure=fig, id="launch-health-chart", responsive=True, style={"width": "100%"}),
        ] + trend_chart_elements + [
            html.H4("Drill into one launch", style={"marginTop": "1rem"}),
            html.P(
                "Pick a launched SKU to see weekly velocity since launch:",
                style={"color": GREY, "fontSize": "0.85rem"},
            ),
            dcc.Dropdown(
                id="launch-detail-select",
                options=drill_options,
                value=drill_options[0]["value"] if drill_options else None,
                clearable=False,
                style={"marginBottom": "0.5rem"},
            ),
            detail_legend,
            html.Div(id="launch-detail-content"),
        ],
        footer=[
            html.Button(
                "Export to Excel", id="launch-health-export-btn", n_clicks=0,
                className="export-btn",
            ),
            dcc.Download(id="launch-health-download"),
            dcc.Store(
                id="launch-health-table-data",
                data={
                    "records": display_df.to_dict("records"),
                    "filename": "launch_health_all",
                },
            ),
            dcc.Store(
                id="launch-health-sku-status",
                data=drill_df[["SKU", "Product Name", "Status", "Launch Date"]].to_dict("records"),
            ),
        ],
    )


# ============================================================
# Callbacks
# ============================================================

def register_callbacks(app) -> None:
    """Register Launch Health decision callbacks."""

    @app.callback(
        Output("launch-health-download", "data"),
        Input("launch-health-export-btn", "n_clicks"),
        Input("launch-health-table-data", "data"),
        prevent_initial_call=True,
    )
    def download_launch_health(n_clicks, table_data):
        triggered = callback_context.triggered_id
        if triggered != "launch-health-export-btn" or not n_clicks:
            return no_update
        if not table_data:
            return no_update
        df = pd.DataFrame(table_data["records"])
        info = excel_download_data(df, "Launch Health", table_data["filename"])
        return dcc.send_bytes(info["content"], info["filename"])

    @app.callback(
        Output("launch-detail-content", "children"),
        Input("launch-detail-select", "value"),
        State("launch-health-sku-status", "data"),
        prevent_initial_call=True,
    )
    def render_launch_detail(selected_sku, sku_status_data):
        if not selected_sku or not sku_status_data:
            return no_update

        # Find the selected SKU's metadata
        sku_info = None
        for row in sku_status_data:
            if row["SKU"] == selected_sku:
                sku_info = row
                break
        if sku_info is None:
            return html.P("SKU not found.", style={"color": GREY})

        sku = sku_info["SKU"]
        pname = sku_info["Product Name"]
        status_val = sku_info["Status"]
        color = LAUNCH_STATUS_COLORS[status_val]

        try:
            weekly = get_launch_weekly(sku)
        except Exception as exc:
            return error_card(
                "Weekly data query failed",
                f"Could not load weekly data for {sku}: {exc}",
            )

        if weekly.empty:
            return html.P(
                "No weekly scan data found yet for this SKU.",
                style={"color": GREY, "padding": "1rem 0"},
            )

        launch_d = pd.to_datetime(weekly["launch_date"].iloc[0])
        weekly["week_ending"] = pd.to_datetime(weekly["week_ending"])
        weekly["weeks_since"] = ((weekly["week_ending"] - launch_d).dt.days // 7) + 1

        threshold = LAUNCH_BENCHMARK

        header_children = [
            html.B(f"{sku} — {pname}"),
            " launched on ",
            html.B(str(launch_d.date())),
            ", ",
            html.Span(status_val, style={"color": color, "fontWeight": "600"}),
            ".",
        ]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=weekly["week_ending"], y=weekly["velocity"],
            mode="lines+markers",
            line=dict(color=color, width=3),
            marker=dict(size=7, color=color),
            hovertemplate="<b>%{x}</b><br>Velocity: %{y:.2f} units/store<extra></extra>",
        ))
        fig.add_hline(
            y=threshold, line_dash="dot", line_color=GREY,
            annotation=text_annotation(f"Velocity benchmark {threshold:.2f}"),
            annotation_position="bottom right",
        )

        # Window boundary lines
        for wk_end, label in [(4, "End of weeks 1-4"),
                              (8, "End of weeks 5-8"),
                              (13, "End of weeks 9-13")]:
            boundary = launch_d + pd.Timedelta(days=wk_end * 7)
            if boundary <= weekly["week_ending"].max():
                add_vline_at_date(
                    fig, boundary, label,
                    color=GREY_LIGHT, dash="dash", width=1.5,
                    annotation_position="top",
                )

        fig.update_layout(
            template="simple_white",
            paper_bgcolor=CANVAS, plot_bgcolor=CANVAS,
            height=420,
            margin=dict(l=10, r=10, t=40, b=40),
            yaxis=dict(
                title="Units per store per week",
                title_font=dict(family=FONT_SANS, size=14, color=TEXT_SEC),
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
            html.Div(
                header_children,
                style={"marginBottom": "0.5rem"},
            ),
            dcc.Graph(figure=fig, id="launch-detail-chart", responsive=True, style={"width": "100%"}),
        ])
