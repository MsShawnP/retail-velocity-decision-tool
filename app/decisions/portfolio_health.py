"""Portfolio Health -- landing-page overview of the Cinderhaven portfolio.

Renders KPI cards, risk indicators by decision area, and production
trend distribution.  All data comes from ``get_portfolio_summary()``
which composes the same queries the decision modes use.
"""

from __future__ import annotations

from dash import html

import pandas as pd

from components import error_card, metric_card
from constants import (
    CHICAGO,
    ORANGE,
    RED,
    TEAL,
)
from data import get_category_benchmark, get_portfolio_summary


def _risk_card(
    title: str,
    count: int,
    total: int,
    color: str,
    detail: str,
    decision_value: str,
) -> html.Div:
    """Single risk-indicator card. Shows count / total with a color accent."""
    pct = round(count / total * 100) if total else 0
    return html.Div(
        className="ph-risk-card",
        id={"type": "ph-risk-card", "decision": decision_value},
        children=[
            html.Div(title, className="ph-risk-title"),
            html.Div(
                f"{count}",
                className="ph-risk-count",
                style={"color": color},
            ),
            html.Div(
                f"of {total} SKUs ({pct}%)",
                className="ph-risk-subtitle",
            ),
            html.Div(detail, className="ph-risk-detail"),
        ],
    )


def _status_bar(
    items: list[tuple[int, str, str]],
    total: int,
) -> html.Div:
    """Horizontal stacked bar showing status distribution."""
    segments = []
    for count, label, color in items:
        if count == 0:
            continue
        pct = count / total * 100 if total else 0
        segments.append(html.Div(
            f"{count}",
            className="ph-bar-segment",
            style={
                "width": f"{pct}%",
                "backgroundColor": color,
            },
            title=f"{count} {label} ({pct:.0f}%)",
        ))
    legend = html.Div(
        [html.Span([
            html.Span(
                className="legend-swatch",
                style={"background": color},
            ),
            f"{label} ({count})",
        ], className="legend-chip")
         for count, label, color in items if count > 0],
        className="chart-legend",
        style={"marginTop": "0.4rem"},
    )
    return html.Div([
        html.Div(segments, className="ph-bar"),
        legend,
    ])


def layout() -> html.Div:
    """Return the full Dash component tree for the Portfolio Health overview."""
    try:
        s = get_portfolio_summary()
    except Exception as exc:
        return error_card(
            "Portfolio summary failed",
            f"Could not aggregate portfolio data: {exc}",
        )

    headline = (
        f"Cinderhaven Provisions runs {s['total_skus']} active SKUs "
        f"across {s['total_retailers']} retailers "
        f"and {s['total_doors']:,} doors."
    )

    attention_items = (
        s["shelf_at_risk"]
        + s["prod_decelerating"]
        + s["launches_failing"]
    )
    if attention_items > 0:
        subhead = (
            f"{attention_items} items need attention this week — "
            f"drill into a decision area below."
        )
    else:
        subhead = "All clear this week — portfolio is running healthy."

    # Category benchmark (portfolio-wide)
    bench_df = get_category_benchmark("Walmart")  # largest retailer as proxy
    bench_vs_pct = None
    if not bench_df.empty and "vs_category_pct" in bench_df.columns:
        valid = bench_df.dropna(subset=["vs_category_pct"])
        if not valid.empty:
            bench_vs_pct = valid["vs_category_pct"].mean()

    kpi_cards = [
        html.Div(
            metric_card("Active SKUs", str(s["total_skus"])),
            className="dh-metric",
        ),
        html.Div(
            metric_card("Physical Doors", f"{s['total_doors']:,}"),
            className="dh-metric",
        ),
        html.Div(
            metric_card("Weekly Units", f"{s['weekly_units']:,}"),
            className="dh-metric",
        ),
        html.Div(
            metric_card(
                "Weekly Margin",
                f"${s['total_weekly_margin']:,}",
            ),
            className="dh-metric",
        ),
        html.Div(
            metric_card("4-Wk Forecast", f"{s['forecast_4w_cases']:,} cs"),
            className="dh-metric",
        ),
    ]
    if pd.notna(bench_vs_pct):
        kpi_cards.append(html.Div(
            metric_card("vs. Category Avg", f"{bench_vs_pct:+.1f}%"),
            className="dh-metric",
        ))
    kpi_row = html.Div(kpi_cards, className="dh-metrics")

    shelf_total = s["shelf_at_risk"] + s["shelf_warning"] + (
        s["total_skus"] - s["shelf_at_risk"] - s["shelf_warning"]
    )

    risk_cards = html.Div([
        _risk_card(
            "Shelf Risk",
            s["shelf_at_risk"],
            shelf_total,
            RED,
            (f"{s['shelf_at_risk']} at risk of delisting, "
             f"{s['shelf_warning']} in warning zone"),
            "shelf",
        ),
        _risk_card(
            "Decelerating",
            s["prod_decelerating"],
            s["total_skus"],
            RED,
            (f"{s['prod_decelerating']} slowing — may need "
             "production adjustment"),
            "production-decel",
        ),
        _risk_card(
            "Accelerating",
            s["prod_accelerating"],
            s["total_skus"],
            TEAL,
            (f"{s['prod_accelerating']} gaining velocity — "
             "check supply can keep up"),
            "production-accel",
        ),
        _risk_card(
            "Launch Health",
            s["launches_failing"],
            s["launches_total"],
            ORANGE if s["launches_failing"] > 0 else TEAL,
            (f"{s['launches_on_track']} on track, "
             f"{s['launches_attention']} need attention, "
             f"{s['launches_failing']} failing"),
            "launch",
        ),
    ], className="ph-risk-row")

    prod_bar = _status_bar(
        [
            (s["prod_accelerating"], "Accelerating", TEAL),
            (s["prod_stable"], "Stable", CHICAGO),
            (s["prod_decelerating"], "Decelerating", RED),
        ],
        s["total_skus"],
    )

    caption = (
        f"Product lines: {s['total_product_lines']}  |  "
        f"Retailers: {s['total_retailers']}  |  "
        f"Most recent week: {s['latest_week']}"
    )

    return html.Div(
        className="ph-layout",
        children=[
            html.H3(headline, className="dh-headline"),
            html.P(subhead, className="ph-subhead"),
            html.P(caption, className="dh-caption"),
            kpi_row,
            html.H4(
                "Attention areas",
                style={"marginTop": "1.25rem", "marginBottom": "0.5rem"},
            ),
            risk_cards,
            html.H4(
                "Production velocity distribution",
                style={"marginTop": "1.25rem", "marginBottom": "0.5rem"},
            ),
            prod_bar,
        ],
    )
