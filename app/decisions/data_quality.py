"""Data Quality decision mode -- surfaces data contract validation results.

Answers "Is my data trustworthy?" by showing validation check results,
table statistics, coverage metrics, and data completeness indicators.
No competitor surfaces data quality to the end user -- this is a
differentiator that turns an internal risk into a visible feature.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from charts import base_chart_layout
from components import (
    dashboard_layout,
    error_card,
    make_grid,
    metric_card,
    status_legend,
)
from constants import (
    GREY,
    NAVY,
    ORANGE,
    RED,
    TEAL,
)
from data import get_data_quality_summary


def layout() -> html.Div:
    """Return the full Dash component tree for Data Quality."""
    try:
        summary = get_data_quality_summary()
    except Exception as exc:
        return error_card(
            "Data quality check failed",
            f"Could not run validation checks: {exc}",
        )

    passed = summary["checks_passed"]
    total = summary["checks_total"]
    pct = passed / total * 100 if total > 0 else 0

    # Headline
    if passed == total:
        headline = (
            f"All {total} data contract checks pass — your dataset is healthy "
            f"and ready for analysis."
        )
        headline_color = TEAL
    elif passed >= total - 2:
        headline = (
            f"{passed} of {total} checks pass — minor issues detected. "
            f"Review the failing checks below."
        )
        headline_color = ORANGE
    else:
        headline = (
            f"Only {passed} of {total} checks pass — significant data issues "
            f"may affect analysis accuracy."
        )
        headline_color = RED

    # Insight
    null_pct = summary["null_scans"] / max(summary["total_scans"], 1) * 100
    zero_pct = summary["zero_scans"] / max(summary["total_scans"], 1) * 100
    insight = (
        f"Dataset spans {summary['n_weeks']} weeks "
        f"({summary['min_date']} to {summary['max_date']}), "
        f"covering {summary['n_skus']} SKUs across "
        f"{summary['n_stores']:,} stores and {summary['n_retailers']} retailers. "
        f"{summary['total_scans']:,} scan records total — "
        f"{zero_pct:.1f}% zero-velocity, {null_pct:.1f}% null."
    )

    caption_text = (
        f"Data contract: {passed}/{total} checks passed ({pct:.0f}%)  |  "
        f"Latest data: {summary['max_date']}"
    )

    # Table stats grid
    table_df = pd.DataFrame(summary["table_stats"])
    table_col_defs = [
        {"field": "table", "headerName": "Table", "sortable": True,
         "filter": True, "width": 140},
        {"field": "description", "headerName": "Purpose", "sortable": True,
         "filter": True, "flex": 1},
        {"field": "rows", "headerName": "Rows", "sortable": True,
         "filter": "agNumberColumnFilter", "width": 120,
         "valueFormatter": {"function": "d3.format(',')(params.value)"}},
        {"field": "status", "headerName": "Status", "sortable": True,
         "filter": True, "width": 100,
         "cellStyle": {"styleConditions": [
             {"condition": "params.value === 'Pass'",
              "style": {"color": TEAL, "fontWeight": "700"}},
             {"condition": "params.value === 'Fail'",
              "style": {"color": RED, "fontWeight": "700"}},
         ]}},
    ]

    # Validation checks grid
    check_df = pd.DataFrame(summary["check_details"])
    check_col_defs = [
        {"field": "check", "headerName": "Validation Check", "sortable": True,
         "filter": True, "flex": 1},
        {"field": "status", "headerName": "Status", "sortable": True,
         "filter": True, "width": 100,
         "cellStyle": {"styleConditions": [
             {"condition": "params.value === 'Pass'",
              "style": {"color": TEAL, "fontWeight": "700"}},
             {"condition": "params.value === 'Fail'",
              "style": {"color": RED, "fontWeight": "700"}},
         ]}},
        {"field": "detail", "headerName": "Detail", "sortable": True,
         "filter": True, "flex": 2},
    ]

    grid = html.Div([
        html.H4("Table Statistics", style={"marginBottom": "0.5rem"}),
        make_grid(table_df, column_defs=table_col_defs, id="dq-table-grid"),
        html.H4("Validation Checks",
                 style={"marginTop": "1.5rem", "marginBottom": "0.5rem"}),
        make_grid(check_df, column_defs=check_col_defs, id="dq-check-grid"),
    ])

    # Chart: data volume by table (horizontal bar)
    fig = go.Figure()
    tables = table_df.sort_values("rows", ascending=True)
    colors = [TEAL if s == "Pass" else RED for s in tables["status"]]
    fig.add_trace(go.Bar(
        y=tables["table"],
        x=tables["rows"],
        orientation="h",
        marker_color=colors,
        text=[f"{r:,}" for r in tables["rows"]],
        textposition="outside",
        textfont=dict(size=11, color=NAVY),
    ))

    fig_layout = base_chart_layout("Records by Table")
    fig_layout["yaxis"]["autorange"] = True
    fig_layout["xaxis"] = dict(
        title="Row Count",
        gridcolor="#DFE6E9",
        zeroline=True,
        zerolinecolor="#DFE6E9",
    )
    fig_layout["margin"] = dict(l=120, r=80, t=40, b=40)
    fig.update_layout(**fig_layout)

    # Health score card color
    if pct == 100:
        score_color = TEAL
    elif pct >= 80:
        score_color = ORANGE
    else:
        score_color = RED

    return dashboard_layout(
        header=[
            html.H3(headline, className="dh-headline",
                     style={"color": headline_color}),
            html.P(insight, className="dh-insight"),
            html.P(caption_text, className="dh-caption"),
            html.Div(
                [
                    html.Div(
                        metric_card("Data Health",
                                    f"{passed}/{total}",
                                    delta=f"{pct:.0f}% passing",
                                    delta_color=score_color),
                        className="dh-metric",
                    ),
                    html.Div(
                        metric_card("Date Span",
                                    f"{summary['n_weeks']} weeks"),
                        className="dh-metric",
                    ),
                    html.Div(
                        metric_card("Total Records",
                                    f"{summary['total_scans']:,}"),
                        className="dh-metric",
                    ),
                    html.Div(
                        metric_card("Zero-Velocity Scans",
                                    f"{summary['zero_scans']:,}",
                                    delta=f"{zero_pct:.1f}% of total"),
                        className="dh-metric",
                    ),
                ],
                className="dh-metrics",
            ),
            status_legend([
                html.B("Data contract checks"),
                " validate the schema and data assumptions that every "
                "decision mode depends on. ",
                html.B("Pass", style={"color": TEAL}),
                " = check satisfied. ",
                html.B("Fail", style={"color": RED}),
                " = data issue that may affect analysis accuracy. "
                "Checks run automatically on app startup.",
            ]),
        ],
        grid=grid,
        chart=[
            html.H4("Data Volume by Table",
                     style={"marginTop": "0"}),
            html.P(
                "Bar length shows record count per table. "
                "Color indicates validation status.",
                style={"color": GREY, "fontSize": "0.85rem"},
            ),
            dcc.Graph(figure=fig, id="dq-volume-chart",
                      responsive=True, style={"width": "100%"}),
        ],
    )
