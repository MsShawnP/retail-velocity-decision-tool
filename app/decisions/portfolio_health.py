"""Portfolio Health -- landing-page overview of the Cinderhaven portfolio.

Renders KPI cards, risk indicators by decision area, and production
trend distribution.  All data comes from ``get_portfolio_summary()``
which composes the same queries the decision modes use.
"""

from __future__ import annotations

from dash import html

import pandas as pd

from calcs import classify_shelf_status
from components import error_card, metric_card
from constants import (
    BAR_RED,
    CHICAGO,
    GREY,
    ORANGE,
    PHYSICAL_RETAILERS,
    RED,
    RETAILER_THRESHOLDS,
    TEAL,
)
from data import (
    get_category_benchmark,
    get_portfolio_summary,
    get_rationalization_data,
    get_shelf_defense_data,
)


def _shelf_at_risk_dollars() -> tuple[int, float]:
    """Unique at-risk SKUs and their weekly wholesale revenue on shelf.

    Same per-retailer classification the portfolio summary uses. Dollars are
    scoped to the retailer where each SKU is at risk: a SKU below threshold at
    Sprouts (10 doors) but healthy at Walmart (500 doors) contributes only its
    Sprouts revenue, not its full cross-retailer revenue. Revenue at a retailer
    is revenue_per_sw x doors (13-week velocity x wholesale x that retailer's
    doors). Returns (0, 0.0) on any failure so the headline can degrade to the
    inventory line.
    """
    try:
        at_risk: set[str] = set()
        weekly_revenue = 0.0
        for ret in PHYSICAL_RETAILERS:
            shelf = get_shelf_defense_data(ret, None)
            if shelf.empty:
                continue
            shelf = classify_shelf_status(shelf, RETAILER_THRESHOLDS.get(ret, 2.0))
            ret_at_risk = set(shelf.loc[shelf["status"] == "At Risk", "sku"])
            if not ret_at_risk:
                continue
            at_risk |= ret_at_risk
            rat = get_rationalization_data(ret, None)
            if rat.empty:
                continue
            rows = rat[rat["sku"].isin(ret_at_risk)]
            weekly_revenue += float((rows["revenue_per_sw"] * rows["doors"]).sum())
        return len(at_risk), weekly_revenue
    except Exception:
        return 0, 0.0


def _risk_card(
    title: str,
    count: int,
    total: int,
    color: str,
    detail: str,
    decision_value: str,
) -> html.Div:
    """Single risk-indicator card. Shows count / total with a color accent.

    When ``total`` is 0 (e.g. no active launches to track) the card shows a
    neutral em-dash and an empty-state subtitle instead of a red ``0 of 0
    SKUs (0%)``, which reads as a broken/unfinished panel.
    """
    if total == 0:
        count_display, count_color, subtitle = "—", GREY, "None to track"
    else:
        pct = round(count / total * 100)
        count_display, count_color = f"{count}", color
        subtitle = f"of {total} SKUs ({pct}%)"
    return html.Div(
        className="ph-risk-card",
        id={"type": "ph-risk-card", "decision": decision_value},
        children=[
            html.Div(title, className="ph-risk-title"),
            html.Div(
                count_display,
                className="ph-risk-count",
                style={"color": count_color},
            ),
            html.Div(
                subtitle,
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
        # No inline count text: white-on-teal fails WCAG AA (4.02:1) and the
        # exact counts are already in the accessible legend below. The segment
        # conveys proportion by width + color; the tooltip carries the detail.
        segments.append(html.Div(
            "",
            className="ph-bar-segment",
            style={
                "width": f"{pct}%",
                "backgroundColor": color,
            },
            title=f"{count} {label} ({pct:.0f}%)",
            **{"aria-label": f"{count} {label} ({pct:.0f}%)"},
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

    inventory_line = (
        f"Cinderhaven Provisions runs {s['total_skus']} active SKUs "
        f"across {s['total_retailers']} retailers "
        f"and {s['total_doors']:,} doors."
    )

    attention_items = (
        s["shelf_at_risk"]
        + s["prod_decelerating"]
        + s["launches_failing"]
    )

    # Spell out what the attention count is made of, so it visibly reconciles
    # with the dollarized headline's at-risk SKU count instead of reading as
    # an off-by-one typo (e.g. "29 items ... (28 at delisting risk, 1 ...)").
    attention_parts = []
    if s["shelf_at_risk"]:
        attention_parts.append(f"{s['shelf_at_risk']} at delisting risk")
    if s["prod_decelerating"]:
        attention_parts.append(f"{s['prod_decelerating']} decelerating")
    if s["launches_failing"]:
        attention_parts.append(f"{s['launches_failing']} failing launches")
    attention_breakdown = ", ".join(attention_parts)

    # Lead with the finding, dollarized; the inventory line demotes to subhead.
    n_risk, risk_revenue = _shelf_at_risk_dollars()
    if n_risk and risk_revenue > 0:
        headline = (
            f"{n_risk} SKUs below the delisting threshold — "
            f"${risk_revenue:,.0f}/week of shelf revenue at risk."
        )
        subhead = (
            f"{inventory_line} {attention_items} items need attention this "
            f"week ({attention_breakdown}) — drill into a decision area below."
        )
    elif attention_items > 0:
        headline = inventory_line
        subhead = (
            f"{attention_items} items need attention this week "
            f"({attention_breakdown}) — drill into a decision area below."
        )
    else:
        headline = inventory_line
        subhead = "All clear this week — portfolio is running healthy."

    # Category benchmark (portfolio-wide)
    try:
        bench_df = get_category_benchmark("Walmart")
    except Exception:
        bench_df = pd.DataFrame()
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
                "Avg Weekly Margin (13wk)",
                f"${s['total_weekly_margin']:,}",
            ),
            className="dh-metric",
        ),
        html.Div(
            metric_card("4-Wk Forecast", f"{s['forecast_4w_cases']:,} cases"),
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
             f"{s['launches_failing']} failing")
            if s["launches_total"]
            else "No SKUs launched in the last 52 weeks.",
            "launch",
        ),
    ], className="ph-risk-row")

    prod_bar = _status_bar(
        [
            (s["prod_accelerating"], "Accelerating", TEAL),
            (s["prod_stable"], "Stable", CHICAGO),
            (s["prod_decelerating"], "Decelerating", BAR_RED),
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
