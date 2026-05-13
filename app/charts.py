"""Plotly chart helpers -- brand-styled layout functions.

Ported from velocity_tool.py lines 294-460. Every chart in the Dash app
uses these to get consistent Cinderhaven styling.
"""

from __future__ import annotations

import plotly.graph_objects as go

from constants import (
    GREY_LIGHT,
    NAVY,
    NAVY_MED,
    PAGE_BG,
    WHITE,
)


def base_chart_layout(
    *,
    height: int,
    x_title: str | None = None,
    y_title: str | None = None,
    show_legend: bool = False,
    left_margin: int = 10,
) -> dict:
    return dict(
        template="simple_white",
        paper_bgcolor=PAGE_BG,
        plot_bgcolor=WHITE,
        height=height,
        margin=dict(l=left_margin, r=90, t=40, b=50),
        yaxis=dict(
            autorange="reversed",
            title=y_title,
            tickfont=dict(size=14, color=NAVY),
            showgrid=False,
            linecolor=GREY_LIGHT,
        ),
        xaxis=dict(
            title=x_title,
            title_font=dict(size=14, color=NAVY_MED),
            tickfont=dict(size=13, color=NAVY),
            gridcolor=GREY_LIGHT,
            linecolor=GREY_LIGHT,
            zerolinecolor=GREY_LIGHT,
        ),
        showlegend=show_legend,
        font=dict(family="sans-serif", size=14, color=NAVY),
        bargap=0.25,
    )


def apply_hbar_layout(
    fig: go.Figure,
    labels: list[str],
    *,
    height: int,
    x_title: str | None = None,
    show_legend: bool = False,
    label_pad_px: int = 305,
    left_margin: int = 325,
    label_font_size: int = 14,
    x_pad_pct: float = 0.20,
) -> None:
    """Apply consistent horizontal-bar styling with left-aligned y-axis labels.

    Plotly's default y-tick labels right-align at the axis line, which makes
    bars with labels of varying length look ragged. This helper hides the
    default labels and re-renders them as annotations anchored to the LEFT
    edge of the chart's left margin, so every label starts at the same
    horizontal position regardless of text length.

    Also computes an x-axis range with `x_pad_pct` padding on each end (20%
    by default) so `textposition="outside"` labels never bleed past the plot
    area. The range is inferred from the figure's existing Bar traces, so
    each chart's padding scales with its own data and any negative bars get
    left-side breathing room automatically.
    """
    fig.update_layout(**base_chart_layout(
        height=height,
        x_title=x_title,
        show_legend=show_legend,
        left_margin=left_margin,
    ))
    fig.update_yaxes(showticklabels=False)

    # Auto-pad the x-axis based on the actual bar data.
    xs: list[float] = []
    for trace in fig.data:
        trace_x = getattr(trace, "x", None)
        if trace_x is None:
            continue
        for v in trace_x:
            if v is None:
                continue
            try:
                xs.append(float(v))
            except (TypeError, ValueError):
                pass
    if xs:
        x_max = max(xs)
        x_min = min(xs)
        span = max(x_max - min(x_min, 0), 1e-9)
        right_pad = span * x_pad_pct
        left_pad = span * x_pad_pct
        # Right edge: always extend by pad. Left edge: extend below 0 only
        # when the data actually goes negative; otherwise pin at 0 so
        # positive-only charts don't waste left margin.
        upper = x_max + right_pad
        if x_min < 0:
            lower = x_min - left_pad
        else:
            lower = 0
        fig.update_xaxes(range=[lower, upper])
    seen: set[str] = set()
    for lbl in labels:
        if lbl in seen or lbl is None:
            continue
        seen.add(lbl)
        fig.add_annotation(
            x=0, y=lbl,
            xref="paper", yref="y",
            xshift=-label_pad_px,
            xanchor="left", yanchor="middle",
            text=str(lbl),
            showarrow=False,
            font=dict(size=label_font_size, color=NAVY),
        )


def text_annotation(text: str, **kw) -> dict:
    return dict(
        text=text,
        font=dict(size=13, color=NAVY),
        bgcolor="rgba(255,255,255,0.95)",
        bordercolor=GREY_LIGHT,
        borderwidth=1,
        borderpad=4,
        **kw,
    )


def add_vline_at_date(fig, x, label: str, *,
                      color: str, dash: str = "dash", width: float = 1.5,
                      annotation_position: str = "top") -> None:
    """Vertical line at a date-typed x value, drawn via add_shape + add_annotation.

    plotly.add_vline() internally does integer arithmetic on the x value, which
    raises `TypeError: Addition/subtraction of integers and integer-arrays with
    Timestamp is no longer supported` on pandas 3.x + plotly 6.x for date axes.
    Drawing the line as a shape with xref='x' / yref='paper' avoids that path.
    """
    fig.add_shape(
        type="line", xref="x", yref="paper",
        x0=x, x1=x, y0=0, y1=1,
        line=dict(color=color, dash=dash, width=width),
    )
    # Map plotly's annotation_position language onto explicit anchors. "top",
    # "top left", "top right", "bottom left", "bottom right" cover the cases
    # used in the app.
    pos = annotation_position
    y_anchor = "top"  # keeps the box just below y1
    y = 1.0
    yshift = -8
    if pos.startswith("bottom"):
        y_anchor = "bottom"
        y = 0.0
        yshift = 8
    if "left" in pos:
        xanchor = "right"
    elif "right" in pos:
        xanchor = "left"
    else:
        xanchor = "center"
    fig.add_annotation(
        x=x, y=y, xref="x", yref="paper",
        text=label,
        showarrow=False,
        font=dict(size=13, color=NAVY),
        bgcolor="rgba(255,255,255,0.95)",
        bordercolor=GREY_LIGHT, borderwidth=1, borderpad=4,
        xanchor=xanchor, yanchor=y_anchor, yshift=yshift,
    )
