"""Cinderhaven Velocity Tool — decision-oriented retail analytics.

Streamlit app. Reads from data/cinderhaven_product_master.db.
Implemented decisions:
  1. Shelf Defense (delisting risk)
  2. Production Planning (replenishment demand + acceleration)
  3. Promo ROI (per-promo lift, dip, incremental, ROI)
  4. Distribution Expansion (where to add SKUs based on similar-SKU performance)
  5. Distribution Pruning (which SKU x store combinations are underperforming)

Visual rules: see memory `visualization_rules.md` and `color_palette.md`.
End user is a CEO who lives in Excel — every chart has a plain-English
headline, ≤20 items, direct labels, intuitive red/yellow/green, no scatter
for rankings. All colors come from the Cinderhaven brand palette.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ============================================================
# Constants
# ============================================================

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"


# ============================================================
# First-boot bootstrap
# ============================================================
# The 164 MB synthetic dataset is too large to commit to GitHub, so we
# regenerate it from scratch on the first boot of a fresh deploy. Subsequent
# boots find the DB on disk and skip straight to serving requests. Wrap the
# build in @st.cache_resource so concurrent first-time visitors don't all
# kick off duplicate rebuilds on a cold start.

_BUILD_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_db.py"


@st.cache_resource(show_spinner="First-time setup: building the Cinderhaven dataset (one-time, ~1 min)...")
def _ensure_database() -> str:
    """Build the SQLite DB if it doesn't exist. Returns its path on success."""
    if DB_PATH.exists():
        return str(DB_PATH)
    if not _BUILD_SCRIPT.exists():
        raise FileNotFoundError(
            f"Database missing and build script not found at {_BUILD_SCRIPT}. "
            "Cannot bootstrap."
        )
    # Use the same interpreter that's running Streamlit so we match the
    # deployed virtualenv exactly. Streams stdout/stderr to the deploy logs.
    result = subprocess.run(
        [sys.executable, str(_BUILD_SCRIPT)],
        cwd=_BUILD_SCRIPT.parent.parent,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"build_db.py exited with status {result.returncode}. "
            "Check the deploy logs for the failing script."
        )
    return str(DB_PATH)


_ensure_database()

# Cinderhaven brand palette
NAVY         = "#1B2A4A"   # primary headings, emphasis
NAVY_MED     = "#3D5A80"   # subheadings, secondary text
TEAL         = "#1E8C7E"   # positive / safe / accent
RED          = "#C0221F"   # critical / at-risk
DARK_RED     = "#8B0000"   # "worse than red" — used for promo-backfired bars
ORANGE       = "#D35830"   # warning
GREY         = "#636E72"   # muted text, labels
GREY_LIGHT   = "#DFE6E9"   # borders, dividers, gridlines
GREY_BG      = "#F8F9FA"   # alternating rows
WHITE        = "#FFFFFF"
RED_FAINT    = "#FFF5F5"   # critical alert backgrounds
GREEN_FAINT  = "#F0FFF4"   # positive alert backgrounds
ORANGE_FAINT = "#FFF8F0"   # warning alert backgrounds (derived)
DARK_RED_FAINT = "#FBE9E7" # backfired-promo row backgrounds
PAGE_BG      = "#DADDE3"   # main content area (matches .streamlit theme)

# Centralized policy thresholds. Every classifier function and every legend
# string reads from this dict — change a number here and the entire app
# (logic + on-screen explanation) stays in sync.
THRESHOLDS = {
    # Production Planning: 4-week trend vs prior 4 weeks
    "production_trend_accel":   0.10,   # > +10% → Accelerating
    "production_trend_decel":  -0.10,   # < −10% → Decelerating
    # Launch Health: current velocity vs initial-4-weeks and benchmark
    "launch_on_track":          0.85,   # ≥85% retention required for On Track
    "launch_failing":           0.70,   # <70% of benchmark → Failing
    # Pricing Power: post-promo recovery vs pre-promo baseline
    "pricing_full_recovery":    0.95,   # ≥95% → Full
    "pricing_slow_recovery":    0.80,   # <80% → Slow
    # Distribution Pruning, By SKU: % of stores below threshold
    "pruning_sku_critical":     0.50,   # ≥50% → Critical
    "pruning_sku_concerning":   0.25,   # 25–49% → Concerning
    # Distribution Pruning, By Store: count of SKUs below threshold
    "pruning_store_critical":   3,      # ≥3 SKUs → Critical
    "pruning_store_concerning": 1,      # 1–2 SKUs → Concerning
    # Shelf Defense: warning band as multiple of delisting threshold
    "shelf_warning_mult":       1.5,    # warning zone = [thr, 1.5×thr] AND declining
    # Promo ROI: cutoff between "marginal positive" and "strong" returns
    "roi_strong":               1.0,    # ROI > 100% (>1.0) → Strong; 0–100% → Marginal; <0% → Negative
}

# The Story is a scroll-driven narrative entry point that lives ABOVE the
# decision dropdown as a standalone sidebar callout — not as one of the
# selectable decisions. The dropdown stays focused on the eight day-to-day
# decision modes; the Story is the "read this once" callout for first-time
# visitors. State lives in `st.session_state["show_story"]` (default True
# so a fresh load always lands on the story).
PROTAGONIST_SKU = "CHP-0044"

DECISIONS = [
    "Is this SKU at risk of being delisted?",
    "How much should I produce over the next 4 weeks?",
    "Did my last promotion pay off?",
    "Which stores should I expand into next?",
    "Which stores aren't earning their shelf space?",
    "Which SKUs should I cut or keep?",
    "Is my new launch on track?",
    "Do I have pricing power on this SKU?",
]
DECISION_TITLES = {
    DECISIONS[0]: "Shelf Defense",
    DECISIONS[1]: "Production Planning — Next 4 Weeks",
    DECISIONS[2]: "Promo ROI",
    DECISIONS[3]: "Distribution Expansion",
    DECISIONS[4]: "Distribution Pruning",
    DECISIONS[5]: "SKU Rationalization",
    DECISIONS[6]: "Launch Health",
    DECISIONS[7]: "Pricing Power",
}

PHYSICAL_RETAILERS = ["Walmart", "Costco", "Whole Foods", "Regional"]
ALL_PHYSICAL_OR_AGG = ["Walmart", "Costco", "Whole Foods", "Regional", "UNFI", "DTC"]

RETAILER_THRESHOLDS = {
    "Walmart":     2.0,
    "Costco":      5.0,
    "Whole Foods": 1.5,
    "Regional":    1.0,
}

REGIONAL_CHAINS = (
    "Green Basket Market",
    "Harbor Fresh",
    "Prairie Provisions",
    "Mountain Pantry Co",
    "Southside Grocers",
)

VOLUME_TIER_MULT = {"A": 1.3, "B": 1.0, "C": 0.7}

# Status -> bar/line/text color
# Universal color rule across the app:
#   TEAL  = positive / good / healthy
#   RED   = negative / bad / problem
#   ORANGE = caution / watch / mixed
#   NAVY_MED = neutral / stable / informational
SHELF_STATUS_COLORS = {"At Risk": RED, "Warning": ORANGE, "Safe": TEAL}
# Production: accelerating velocity is GOOD news (your product is selling),
# decelerating is BAD (slowing down), stable is neutral.
PRODUCTION_STATUS_COLORS = {"Accelerating": TEAL, "Decelerating": RED, "Stable": NAVY_MED}
# Pruning: Mild still means "some stores below threshold" — that's a small
# concern, not a positive, so it reads as neutral (navy) rather than teal.
PRUNING_SEVERITY_COLORS = {"Critical": RED, "Concerning": ORANGE, "Mild": NAVY_MED}

# Status -> (row bg, row text) for colored tables
SHELF_ROW = {
    "At Risk": (RED_FAINT, RED),
    "Warning": (ORANGE_FAINT, ORANGE),
    "Safe":    (GREEN_FAINT, TEAL),
}
PRODUCTION_ROW = {
    "Accelerating": (GREEN_FAINT, TEAL),
    "Decelerating": (RED_FAINT, RED),
    "Stable":       (GREY_BG, NAVY_MED),
}
PRUNING_ROW = {
    "Critical":   (RED_FAINT, RED),
    "Concerning": (ORANGE_FAINT, ORANGE),
    "Mild":       (GREY_BG, NAVY_MED),
}

# Retailer -> brand color (for grouped charts)
RETAILER_COLORS = {
    "Walmart":     NAVY,
    "Costco":      TEAL,
    "Whole Foods": ORANGE,
    "Regional":    NAVY_MED,
    "UNFI":        GREY,
    "DTC":         "#8B6F47",   # warm muted, distinguishes from the rest
}


# ============================================================
# Page setup
# ============================================================

st.set_page_config(
    page_title="Cinderhaven Velocity Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Soft-grey main background needs tables, charts and metric cards to render
# as discrete white panels — Streamlit doesn't card them by default. The CSS
# below adds a hairline border + subtle shadow so each block reads as its
# own surface against the grey page.
st.markdown(
    f"""
    <style>
      /* Metric tiles and basic tables render as white card panels on the
         grey main area. Plotly charts and dataframes both blend into the
         page — their internal styling carries the visual structure. */
      div[data-testid="stTable"],
      div[data-testid="stVegaLiteChart"] {{
          background-color: {WHITE};
          border: 1px solid {GREY_LIGHT};
          border-radius: 6px;
          padding: 0.5rem;
          box-shadow: 0 1px 2px rgba(27, 42, 74, 0.05);
      }}
      div[data-testid="stMetric"] {{
          background-color: {WHITE};
          border: 1px solid {GREY_LIGHT};
          border-radius: 6px;
          padding: 0.85rem 1rem 0.75rem 1rem;
          box-shadow: 0 1px 2px rgba(27, 42, 74, 0.05);
      }}
      /* Dataframes blend into the page — the per-row cell colors carry the
         visual structure, no outer white card needed. */
      div[data-testid="stDataFrame"] {{
          background-color: transparent !important;
          border: none !important;
          box-shadow: none !important;
          padding: 0 !important;
      }}
      div[data-testid="stDataFrame"] > div,
      div[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {{
          background-color: transparent !important;
      }}
      /* Plotly charts blend into the page too — the chart's paper_bgcolor is
         set to the page color in code, so the outer canvas matches; only the
         inner plot_bgcolor stays white as the floating data panel. */
      div[data-testid="stPlotlyChart"] {{
          background-color: transparent !important;
          border: none !important;
          box-shadow: none !important;
          padding: 0 !important;
      }}
      div[data-testid="stPlotlyChart"] > div {{
          background-color: transparent !important;
      }}
      /* Tabs strip stays transparent so the panels below carry the card styling */
      div[data-testid="stTabs"] [data-baseweb="tab-list"] {{
          background-color: transparent;
          border-bottom: 1px solid {GREY_LIGHT};
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# Connection & cached lookups
# ============================================================

@st.cache_resource
def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


@st.cache_data(show_spinner=False)
def get_product_lines() -> list[str]:
    con = get_connection()
    return [r[0] for r in con.execute(
        "SELECT DISTINCT product_line FROM product_master ORDER BY product_line"
    ).fetchall()]


@st.cache_data(show_spinner=False)
def get_skus_for_line(product_line: str) -> list[tuple[str, str]]:
    """Return [(sku, product_name), ...] for one product line."""
    con = get_connection()
    return con.execute(
        "SELECT sku, product_name FROM product_master "
        "WHERE product_line = ? ORDER BY sku",
        (product_line,),
    ).fetchall()


@st.cache_data(show_spinner=False)
def get_latest_week() -> str:
    con = get_connection()
    return con.execute("SELECT MAX(week_ending) FROM scan_data").fetchone()[0]


@st.cache_data(show_spinner=False)
def get_promo_skus(retailer: str) -> list[str]:
    con = get_connection()
    return [r[0] for r in con.execute(
        "SELECT DISTINCT sku FROM promotions WHERE retailer = ? ORDER BY sku",
        (retailer,),
    ).fetchall()]


def retailer_clause(retailer: str) -> tuple[str, list]:
    """Return (sql_clause, params) for a stores-table filter on retailer."""
    if retailer == "All Retailers":
        return ("1=1", [])
    if retailer == "Regional":
        ph = ",".join("?" for _ in REGIONAL_CHAINS)
        return (f"s.retailer IN ({ph})", list(REGIONAL_CHAINS))
    return ("s.retailer = ?", [retailer])


# ============================================================
# Plotly + table helpers (brand-styled)
# ============================================================

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


def make_row_styler(color_map: dict[str, tuple[str, str]], status_col: str = "Status"):
    """Returns a row-level styler. color_map = {status: (bg, fg)}."""
    def styler(row: pd.Series) -> list[str]:
        bg, fg = color_map.get(row[status_col], (WHITE, NAVY))
        return [f"background-color: {bg}; color: {fg}"] * len(row)
    return styler


def render_chart_legend(items: list[tuple[str, str]]) -> None:
    """One-line color legend for a chart, sits just below the chart subtitle.

    items is a list of (color_hex, label) tuples. Renders tiny colored squares
    inline (HTML spans) rather than emojis — emoji rendering varies by OS.
    """
    chips = []
    for color, label in items:
        chips.append(
            f"<span style='display:inline-block; width:10px; height:10px; "
            f"background:{color}; border-radius:2px; "
            f"margin-right:5px; vertical-align:middle;'></span>{label}"
        )
    st.markdown(
        f"<div style='color: {GREY}; font-size: 12px; "
        f"margin: -0.4em 0 0.6em 0;'>"
        + "&nbsp;&nbsp;&nbsp;".join(chips)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_status_legend(text: str) -> None:
    """Compact muted-grey legend that spells out the bucket cutoffs.

    A CEO who sees orange and not green should never have to wonder why —
    this prints the exact rule under the summary cards.
    """
    st.markdown(
        f"<div style='color: {GREY}; font-size: 12px; "
        f"line-height: 1.5; margin: 0.25em 0 0.6em 0;'>{text}</div>",
        unsafe_allow_html=True,
    )


def render_row_count_line(item_label: str, parts: list[tuple[int, str]]) -> None:
    """Small muted-grey line proving the buckets sum to the table total.

    Format: "Showing N items | X bucket1 + Y bucket2 = N total". Built for an
    Excel-trained CEO who always sums the parts to verify the whole.
    """
    total = sum(n for n, _ in parts)
    parts_text = " + ".join(f"{n} {label}" for n, label in parts)
    st.markdown(
        f"<div style='color: {GREY}; font-size: 0.85em; "
        f"margin: 0.25em 0 0.75em 0;'>"
        f"Showing {total} {item_label} | {parts_text} = {total} total"
        f"</div>",
        unsafe_allow_html=True,
    )


def excel_button(df: pd.DataFrame, sheet_name: str, file_stem: str) -> None:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    st.download_button(
        "Export to Excel",
        data=buf.getvalue(),
        file_name=f"{file_stem}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
# THE STORY — narrative entry tab
# ============================================================
# Five scrolling sections that take the reader through the protagonist SKU
# (CHP-0044, Charred Scallion Relish): a SKU that posts +15% YoY units in
# the Monday morning report while its baseline velocity quietly drops 25%
# under the cover of escalating promotional spend. The arc is:
#   1. The Monday Morning Report — show the report that hides the problem
#   2. The Volume Trap — split total vs baseline, reveal the masking
#   3. What $18,701 Bought — promo-by-promo hangover analysis
#   4. The Shelf Is Watching — project the trajectory to the delisting line
#   5. The Total Cost of Not Knowing — sum the dollars
# Then a "What the rest of the portfolio looks like" coda so the reader
# leaves understanding which decision tab to open next.

# Saturday-aligned helper: scan_data uses week-ending-Saturday, promotions
# table uses Monday week-start. Shifting promo dates by +5 days lines them up
# with the corresponding scan week.
def _promo_to_scan_weeks(start_week: str, end_week: str) -> list[str]:
    s = pd.to_datetime(start_week) + pd.Timedelta(days=5)
    e = pd.to_datetime(end_week) + pd.Timedelta(days=5)
    out = []
    cur = s
    while cur <= e:
        out.append(cur.date().isoformat())
        cur += pd.Timedelta(days=7)
    return out


@st.cache_data(show_spinner="Loading Monday-morning summary...")
def get_monday_morning_summary(protagonist: str, n_show: int = 18) -> pd.DataFrame:
    """52wk vs prior-52wk units & dollars per SKU.

    Builds a CEO-style pivot summary: a mix of the highest-volume SKUs (the
    ones that show up in any executive report) and a few weak performers
    so the YoY range looks like a real list — not just a green-arrows
    cherry-pick. Sorted by YoY unit change descending (best on top), with
    the protagonist guaranteed to land in the top half so its +15% reads as
    "yet another healthy SKU" rather than a standout.
    """
    con = get_connection()
    latest = get_latest_week()
    sql = """
        SELECT pm.sku, pm.product_name, pm.product_line,
               SUM(CASE WHEN julianday(?) - julianday(d.week_ending) < 364
                        THEN d.units_sold ELSE 0 END) AS units_cur,
               SUM(CASE WHEN julianday(?) - julianday(d.week_ending) >= 364
                         AND julianday(?) - julianday(d.week_ending) < 728
                        THEN d.units_sold ELSE 0 END) AS units_prior,
               SUM(CASE WHEN julianday(?) - julianday(d.week_ending) < 364
                        THEN d.dollars_sold ELSE 0 END) AS dollars_cur,
               SUM(CASE WHEN julianday(?) - julianday(d.week_ending) >= 364
                         AND julianday(?) - julianday(d.week_ending) < 728
                        THEN d.dollars_sold ELSE 0 END) AS dollars_prior
        FROM scan_data d JOIN product_master pm ON d.sku = pm.sku
        GROUP BY pm.sku, pm.product_name, pm.product_line
        HAVING units_prior > 0
    """
    df = pd.read_sql(sql, con, params=[latest] * 6)
    df["units_yoy_pct"] = (df["units_cur"] - df["units_prior"]) / df["units_prior"] * 100
    df["dollars_yoy_pct"] = (df["dollars_cur"] - df["dollars_prior"]) / df["dollars_prior"] * 100

    # Stratified sample so the YoY column shows a realistic spread: take the
    # top half of n_show from biggest-volume winners (YoY > 0) and the bottom
    # half from the laggards (YoY <= 0). The protagonist is forced into the
    # winner pool so its +15% sits naturally among the "growing" SKUs.
    n_winners = (n_show + 1) // 2
    n_losers = n_show - n_winners
    winners_pool = df[df["units_yoy_pct"] > 0].nlargest(n_winners * 2, "units_cur")
    winners = winners_pool.nlargest(n_winners, "units_cur").copy()
    if protagonist not in set(winners["sku"]):
        prot = df[df["sku"] == protagonist]
        if not prot.empty:
            winners = pd.concat([winners.iloc[:n_winners - 1], prot], ignore_index=True)
    losers = df[df["units_yoy_pct"] <= 0].nlargest(n_losers, "units_cur")
    out = pd.concat([winners, losers], ignore_index=True)
    return out.sort_values("units_yoy_pct", ascending=False).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def get_sku_weekly_velocity(sku: str) -> pd.DataFrame:
    """Per-week total + baseline velocity (units / store-week). Promo flag set
    from the union of all promo windows on this SKU regardless of retailer."""
    con = get_connection()
    promos = pd.read_sql(
        "SELECT start_week, end_week FROM promotions WHERE sku=?",
        con, params=[sku],
    )
    promo_set: set[str] = set()
    for _, r in promos.iterrows():
        promo_set.update(_promo_to_scan_weeks(r["start_week"], r["end_week"]))

    df = pd.read_sql(
        """
        SELECT week_ending,
               AVG(units_sold) AS velocity,
               COUNT(*) AS doors,
               SUM(units_sold) AS units_total,
               SUM(dollars_sold) AS dollars_total
        FROM scan_data WHERE sku=?
        GROUP BY week_ending ORDER BY week_ending
        """,
        con, params=[sku],
    )
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    df["on_promo"] = df["week_ending"].dt.date.astype(str).isin(promo_set)
    # baseline_v: velocity in non-promo weeks only (NaN on promo weeks so the
    # plotted line breaks rather than connecting through the spike)
    df["baseline_v"] = df["velocity"].where(~df["on_promo"])
    return df


@st.cache_data(show_spinner=False)
def get_promo_hangover_data(sku: str) -> pd.DataFrame:
    """For each promo on the SKU, compute pre / during / post velocity at the
    promo's retailer. Pre = 4 weeks before start. Post = 4 weeks after end."""
    con = get_connection()
    promos = pd.read_sql(
        """
        SELECT promo_id, retailer, start_week, end_week, duration_weeks,
               discount_depth_pct, promo_type
        FROM promotions WHERE sku=? ORDER BY start_week
        """,
        con, params=[sku],
    )
    rows = []
    for _, p in promos.iterrows():
        ret = p["retailer"]
        ret_clause, ret_params = retailer_clause(ret)
        is_agg = 1 if ret in ("UNFI", "DTC") else 0
        # Saturday-align the promo dates
        start_we = (pd.to_datetime(p["start_week"]) + pd.Timedelta(days=5)).date().isoformat()
        end_we   = (pd.to_datetime(p["end_week"])   + pd.Timedelta(days=5)).date().isoformat()
        pre_start  = (pd.to_datetime(p["start_week"]) + pd.Timedelta(days=5) - pd.Timedelta(weeks=4)).date().isoformat()
        pre_end    = (pd.to_datetime(p["start_week"]) + pd.Timedelta(days=5) - pd.Timedelta(days=1)).date().isoformat()
        post_start = (pd.to_datetime(p["end_week"])   + pd.Timedelta(days=5) + pd.Timedelta(days=7)).date().isoformat()
        post_end   = (pd.to_datetime(p["end_week"])   + pd.Timedelta(days=5) + pd.Timedelta(weeks=4)).date().isoformat()

        def _avg_vel(start: str, end: str) -> float | None:
            sql = f"""
                SELECT AVG(d.units_sold)
                FROM scan_data d
                JOIN stores s ON d.store_id = s.store_id
                WHERE d.sku = ? AND {ret_clause} AND s.is_aggregated_channel = ?
                  AND d.week_ending BETWEEN ? AND ?
            """
            cur = con.execute(sql, [sku] + ret_params + [is_agg, start, end])
            r = cur.fetchone()[0]
            return float(r) if r is not None else None

        pre_v   = _avg_vel(pre_start, pre_end)
        promo_v = _avg_vel(start_we, end_we)
        post_v  = _avg_vel(post_start, post_end)

        # Doors and incremental dollars
        doors_sql = f"""
            SELECT COUNT(DISTINCT d.store_id)
            FROM scan_data d JOIN stores s ON d.store_id = s.store_id
            WHERE d.sku = ? AND {ret_clause} AND s.is_aggregated_channel = ?
              AND d.week_ending BETWEEN ? AND ?
        """
        doors = con.execute(doors_sql, [sku] + ret_params + [is_agg, start_we, end_we]).fetchone()[0] or 0

        rows.append({
            "promo_id": p["promo_id"], "retailer": ret,
            "start_week": p["start_week"], "end_week": p["end_week"],
            "duration_weeks": p["duration_weeks"],
            "discount_depth_pct": p["discount_depth_pct"],
            "promo_type": p["promo_type"],
            "pre_v": pre_v, "promo_v": promo_v, "post_v": post_v,
            "doors": doors,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Lift, dip, and per-promo hangover (post minus pre, the residual damage)
    df["lift_pct"] = (df["promo_v"] - df["pre_v"]) / df["pre_v"] * 100
    df["dip_pct"]  = (df["post_v"] - df["pre_v"]) / df["pre_v"] * 100
    return df


@st.cache_data(show_spinner=False)
def get_sku_trade_spend(sku: str) -> float:
    """Total trade spend on a SKU summed over all promo (sku, week, retailer)
    triples. Trade $ = scan dollars in that promo week × retailer trade %."""
    con = get_connection()
    costs = con.execute(
        """SELECT trade_spend_pct_walmart, trade_spend_pct_costco,
                  trade_spend_pct_whole_foods, trade_spend_pct_regional,
                  trade_spend_pct_unfi, trade_spend_pct_dtc
           FROM sku_costs WHERE sku=?""",
        [sku],
    ).fetchone()
    if costs is None:
        return 0.0
    pct = {
        "Walmart":     costs[0] or 0.0,
        "Costco":      costs[1] or 0.0,
        "Whole Foods": costs[2] or 0.0,
        "UNFI":        costs[4] or 0.0,
        "DTC":         costs[5] or 0.0,
    }
    regional_pct = costs[3] or 0.0

    # Promo (week, retailer) set
    promo_rows = con.execute(
        "SELECT retailer, start_week, end_week FROM promotions WHERE sku=?",
        [sku],
    ).fetchall()
    promo_index: dict[str, set[str]] = {}  # retailer -> set of week_ending
    for ret, sw, ew in promo_rows:
        for wk in _promo_to_scan_weeks(sw, ew):
            promo_index.setdefault(ret, set()).add(wk)

    # Total scan dollars by (week, retailer) for this SKU
    scan_rows = con.execute(
        """
        SELECT d.week_ending, s.retailer, SUM(d.dollars_sold)
        FROM scan_data d JOIN stores s ON d.store_id = s.store_id
        WHERE d.sku = ?
        GROUP BY d.week_ending, s.retailer
        """,
        [sku],
    ).fetchall()
    total = 0.0
    for wk, ret, dollars in scan_rows:
        if ret not in promo_index or wk not in promo_index[ret]:
            continue
        if ret in REGIONAL_CHAINS:
            tp = regional_pct
        else:
            tp = pct.get(ret, 0.0)
        total += (dollars or 0.0) * tp
    return total


@st.cache_data(show_spinner=False)
def get_walmart_trajectory(sku: str) -> pd.DataFrame:
    """Trailing 13-week rolling avg of Walmart-only weekly velocity."""
    con = get_connection()
    df = pd.read_sql(
        """
        SELECT d.week_ending, AVG(d.units_sold) AS velocity
        FROM scan_data d JOIN stores s ON d.store_id = s.store_id
        WHERE d.sku = ? AND s.retailer = 'Walmart'
        GROUP BY d.week_ending ORDER BY d.week_ending
        """,
        con, params=[sku],
    )
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    df["t13"] = df["velocity"].rolling(window=13, min_periods=4).mean()
    return df


@st.cache_data(show_spinner=False)
def get_sku_revenue_at_risk(sku: str) -> dict:
    """Annual revenue at the protagonist's current Walmart distribution
    (doors × current velocity × wholesale × 52). What's "at risk" if the SKU
    crosses the delisting threshold and Walmart drops it in the next review."""
    con = get_connection()
    row = con.execute(
        """
        SELECT COUNT(DISTINCT d.store_id),
               AVG(d.units_sold),
               SUM(d.dollars_sold)
        FROM scan_data d JOIN stores s ON d.store_id = s.store_id
        WHERE d.sku = ? AND s.retailer = 'Walmart'
          AND julianday((SELECT MAX(week_ending) FROM scan_data))
              - julianday(d.week_ending) < 91
        """,
        [sku],
    ).fetchone()
    walmart_doors = row[0] or 0
    walmart_v     = row[1] or 0.0
    walmart_q     = row[2] or 0.0  # last 13wk dollars at walmart

    # Annualize: take the trailing 13wk avg velocity and project a year forward
    annual_units_walmart = walmart_v * walmart_doors * 52
    # SKU wholesale at walmart for revenue conversion
    cost_row = con.execute(
        """SELECT wholesale_walmart, cogs_per_unit FROM sku_costs WHERE sku=?""",
        [sku],
    ).fetchone()
    wholesale_walmart = cost_row[0] or 0
    cogs              = cost_row[1] or 0
    annual_rev_walmart = annual_units_walmart * wholesale_walmart
    annual_margin_walmart = annual_units_walmart * (wholesale_walmart - cogs)

    return {
        "walmart_doors": walmart_doors,
        "walmart_v_t13": walmart_v,
        "walmart_dollars_t13": walmart_q,
        "annual_rev_walmart": annual_rev_walmart,
        "annual_margin_walmart": annual_margin_walmart,
        "wholesale_walmart": wholesale_walmart,
        "cogs": cogs,
    }


@st.cache_data(show_spinner=False)
def get_category_avg_velocity(product_line: str) -> float:
    """Recent 13wk units/store-week for the product line — used as the
    'replacement SKU could earn this much' benchmark."""
    con = get_connection()
    row = con.execute(
        """
        SELECT AVG(d.units_sold)
        FROM scan_data d JOIN product_master pm ON d.sku = pm.sku
        WHERE pm.product_line = ?
          AND julianday((SELECT MAX(week_ending) FROM scan_data))
              - julianday(d.week_ending) < 91
        """,
        [product_line],
    ).fetchone()
    return row[0] or 0.0


# ----------------------------------------------------------------
# Bottom subsection: "What the rest of the portfolio looks like"
# ----------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_top_demand_4wk() -> pd.DataFrame:
    """Top 10 SKUs by projected next-4-week case demand."""
    con = get_connection()
    df = pd.read_sql(
        """
        SELECT pm.sku, pm.product_name,
               SUM(d.units_sold) * 1.0 / NULLIF(pm.case_pack_qty, 0) AS cases_4wk
        FROM scan_data d JOIN product_master pm ON d.sku = pm.sku
        WHERE julianday((SELECT MAX(week_ending) FROM scan_data))
              - julianday(d.week_ending) < 28
        GROUP BY pm.sku, pm.product_name, pm.case_pack_qty
        ORDER BY cases_4wk DESC LIMIT 10
        """,
        con,
    )
    return df.dropna(subset=["cases_4wk"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def get_top_velocity_per_door() -> pd.DataFrame:
    """Top 10 retailer chains by avg units/door/week over the trailing 13 weeks."""
    con = get_connection()
    df = pd.read_sql(
        """
        SELECT s.retailer AS chain,
               AVG(d.units_sold) AS vel_per_door,
               COUNT(DISTINCT d.store_id) AS active_doors
        FROM scan_data d JOIN stores s ON d.store_id = s.store_id
        WHERE julianday((SELECT MAX(week_ending) FROM scan_data))
              - julianday(d.week_ending) < 91
          AND s.is_aggregated_channel = 0
        GROUP BY s.retailer
        ORDER BY vel_per_door DESC LIMIT 10
        """,
        con,
    )
    return df


@st.cache_data(show_spinner=False)
def get_bottom_stores_below_threshold(threshold: float = 2.0) -> pd.DataFrame:
    """Bottom 10 Walmart stores by per-SKU avg velocity, with their gap below
    the threshold. Returns the worst stores even if all are above threshold —
    the chart still shows the tail of the distribution. The 'gap' column is
    threshold − velocity (positive = below the line, negative = above)."""
    con = get_connection()
    df = pd.read_sql(
        """
        SELECT d.store_id, AVG(d.units_sold) AS vel
        FROM scan_data d JOIN stores s ON d.store_id = s.store_id
        WHERE s.retailer = 'Walmart'
          AND julianday((SELECT MAX(week_ending) FROM scan_data))
              - julianday(d.week_ending) < 91
        GROUP BY d.store_id
        ORDER BY vel ASC LIMIT 10
        """,
        con,
    )
    df["gap"] = threshold - df["vel"]
    df["threshold"] = threshold
    return df


@st.cache_data(show_spinner=False)
def get_top_elasticity_skus() -> pd.DataFrame:
    """Top 10 SKUs by avg promo lift / discount-depth ratio (elasticity)."""
    con = get_connection()
    df = pd.read_sql(
        """
        WITH promo_pairs AS (
            SELECT p.sku, p.start_week, p.end_week, p.discount_depth_pct,
                   AVG(CASE WHEN sd.week_ending BETWEEN p.start_week AND p.end_week
                            THEN sd.units_sold END) AS promo_v,
                   AVG(CASE WHEN sd.week_ending BETWEEN DATE(p.start_week, '-28 days')
                                              AND DATE(p.start_week, '-1 days')
                            THEN sd.units_sold END) AS pre_v
            FROM promotions p JOIN scan_data sd ON sd.sku = p.sku
            WHERE sd.week_ending BETWEEN DATE(p.start_week, '-28 days')
                                     AND DATE(p.end_week, '+1 days')
            GROUP BY p.promo_id, p.sku, p.start_week, p.end_week, p.discount_depth_pct
        )
        SELECT pm.sku, pm.product_name,
               AVG((pp.promo_v - pp.pre_v) / NULLIF(pp.pre_v, 0)
                   / NULLIF(pp.discount_depth_pct, 0)) AS elasticity,
               COUNT(*) AS n_promos
        FROM promo_pairs pp JOIN product_master pm ON pp.sku = pm.sku
        WHERE pp.pre_v > 0 AND pp.discount_depth_pct > 0
        GROUP BY pm.sku, pm.product_name
        HAVING n_promos >= 1 AND elasticity IS NOT NULL
        ORDER BY elasticity DESC LIMIT 10
        """,
        con,
    )
    return df


# ----------------------------------------------------------------
# Render: The Story
# ----------------------------------------------------------------

def _h2(text: str) -> None:
    st.markdown(
        f"<h2 style='color:{NAVY}; margin-top: 1.2rem; margin-bottom: 0.3rem;'>"
        f"{text}</h2>",
        unsafe_allow_html=True,
    )


def _eyebrow(text: str) -> None:
    st.markdown(
        f"<div style='color:{ORANGE}; font-size: 0.8rem; "
        f"font-weight: 700; letter-spacing: 0.18rem; "
        f"text-transform: uppercase; margin-top: 1.5rem;'>{text}</div>",
        unsafe_allow_html=True,
    )


def _narration(text: str, *, color: str = NAVY) -> None:
    """Pull-quote narration block. The story-teller voice."""
    st.markdown(
        f"<div style='font-size: 1.08rem; line-height: 1.6; color: {color}; "
        f"margin: 0.6rem 0 0.8rem 0; padding: 0.9rem 1.2rem; "
        f"background-color: {WHITE}; border-left: 4px solid {ORANGE}; "
        f"border-radius: 4px; box-shadow: 0 1px 2px rgba(27, 42, 74, 0.05);'>"
        f"{text}</div>",
        unsafe_allow_html=True,
    )


def _switch_decision(target: str) -> None:
    """Set the sidebar selectbox to a target decision and exit Story view.

    Used as an `on_click` callback on the Section-5 jump buttons. Streamlit
    runs `on_click` callbacks BEFORE widgets re-instantiate on the next run,
    which is the only point at which we're allowed to write to a widget's
    own session-state key (`decision_picker`). Doing the same write inline
    after `if st.button(...)` raises StreamlitAPIException because the
    selectbox has already locked its key for that render.
    """
    st.session_state["decision_picker"] = target
    st.session_state["show_story"] = False


def render_story() -> None:
    # Title
    st.markdown(
        f"""
        <div style='margin-bottom: 0.6rem;'>
          <div style='color:{ORANGE}; font-size: 0.75rem;
                      font-weight: 700; letter-spacing: 0.22rem;
                      text-transform: uppercase;'>
            Why this tool exists
          </div>
          <h1 style='color:{NAVY}; margin: 0.05rem 0 0 0;
                     font-family: Georgia, serif;'>
            The Charred Scallion Relish Problem
          </h1>
          <div style='color:{NAVY_MED}; font-size: 1.05rem;
                      margin-top: 0.4rem; max-width: 820px;'>
            One SKU. Eight months. $18,701 in trade spend. A +15% YoY headline
            that hides a 25% baseline collapse. Read the story, then use the tool.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()

    # ---- Section 1: The Monday Morning Report ----
    _eyebrow("Section 1 of 5")
    _h2("The Monday Morning Report")

    st.markdown(
        f"<div style='color:{NAVY_MED}; font-size: 1rem; max-width: 820px; "
        f"margin-bottom: 0.7rem;'>"
        f"This is the report a $25 million specialty foods brand built on. "
        f"Total units across the portfolio: up. Revenue: up. Charred Scallion "
        f"Relish at +15% year-over-year. Green arrow. Most of the SKUs in "
        f"the portfolio look exactly like this — and most of them are fine."
        f"</div>",
        unsafe_allow_html=True,
    )

    summary = get_monday_morning_summary(PROTAGONIST_SKU)
    if not summary.empty:
        disp = pd.DataFrame({
            "SKU":                summary["sku"],
            "Product Name":       summary["product_name"],
            "Product Line":       summary["product_line"],
            "Units (Current 52w)":  summary["units_cur"].round(0),
            "Units (Prior 52w)":    summary["units_prior"].round(0),
            "Units YoY %":         summary["units_yoy_pct"].round(1),
            "Revenue (Current 52w)": summary["dollars_cur"].round(0),
            "Revenue (Prior 52w)":   summary["dollars_prior"].round(0),
            "Revenue YoY %":       summary["dollars_yoy_pct"].round(1),
        })

        def _highlight_row(row: pd.Series) -> list[str]:
            n = len(row)
            # Hero row always teal-tinted so it pops out of the list
            if row["SKU"] == PROTAGONIST_SKU:
                return [f"background-color: {GREEN_FAINT}; color: {NAVY}; "
                        f"font-weight: 600;"] * n
            return [""] * n

        def _color_yoy(v: float) -> str:
            if pd.isna(v):
                return ""
            if v >= 0:
                return f"color: {TEAL}; font-weight: 600;"
            return f"color: {RED}; font-weight: 600;"

        styled = (
            disp.style
            .apply(_highlight_row, axis=1)
            .map(_color_yoy, subset=["Units YoY %", "Revenue YoY %"])
            .format({
                "Units (Current 52w)":   "{:,.0f}",
                "Units (Prior 52w)":     "{:,.0f}",
                "Units YoY %":           "{:+.1f}%",
                "Revenue (Current 52w)": "${:,.0f}",
                "Revenue (Prior 52w)":   "${:,.0f}",
                "Revenue YoY %":         "{:+.1f}%",
            })
        )
        st.dataframe(styled, use_container_width=True, hide_index=True,
                     height=min(640, 38 * len(disp) + 50))

    _narration(
        "Every number in this table is correct. This is the view that "
        "built a $25 million brand, and most of the time it tells you "
        "exactly what you need to know. But underneath these green arrows, "
        "there&rsquo;s a layer this summary can&rsquo;t reach &mdash; the "
        "place where margin leaks and shelf risk actually live. Watch what "
        "happens when you zoom in on one of the green ones."
    )

    st.divider()

    # ---- Section 2: The Volume Trap ----
    _eyebrow("Section 2 of 5")
    _h2("The Volume Trap — Charred Scallion Relish")

    weekly = get_sku_weekly_velocity(PROTAGONIST_SKU)
    trade_spend = get_sku_trade_spend(PROTAGONIST_SKU)

    # Compute the headline numbers from the raw weekly series
    def _wk_in(d: pd.Series, lo: str, hi: str) -> pd.Series:
        return (d["week_ending"] >= pd.Timestamp(lo)) & (d["week_ending"] <= pd.Timestamp(hi))

    last52  = weekly[_wk_in(weekly, "2025-05-04", "2026-05-02")]
    prior52 = weekly[_wk_in(weekly, "2024-05-04", "2025-05-03")]
    yoy_units_pct = ((last52["units_total"].sum() - prior52["units_total"].sum())
                     / max(prior52["units_total"].sum(), 1) * 100)

    recent_baseline = weekly[_wk_in(weekly, "2025-11-03", "2026-05-02") & ~weekly["on_promo"]]["velocity"].mean()
    prior_baseline  = weekly[_wk_in(weekly, "2025-05-04", "2025-11-02") & ~weekly["on_promo"]]["velocity"].mean()
    baseline_pct = (recent_baseline - prior_baseline) / prior_baseline * 100 if prior_baseline else 0

    promo_pct_recent = weekly[_wk_in(weekly, "2025-11-03", "2026-05-02")]["on_promo"].mean() * 100
    promo_pct_prior  = weekly[_wk_in(weekly, "2025-05-04", "2025-11-02")]["on_promo"].mean() * 100

    # Callout cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("YoY total volume", f"{yoy_units_pct:+.1f}%", delta="Looks healthy",
              delta_color="normal")
    c2.metric("Baseline velocity", f"{baseline_pct:+.1f}%", delta="Real trend",
              delta_color="inverse")
    c3.metric("Promo weeks (recent)",
              f"{promo_pct_recent:.0f}%", delta=f"was {promo_pct_prior:.0f}%",
              delta_color="off")
    c4.metric("Trade spend (life)", f"${trade_spend:,.0f}",
              delta="Burned to mask the decline", delta_color="off")

    # Chart 1: Total vs baseline weekly velocity, with promo-week shading
    st.markdown(
        f"<h4 style='color:{NAVY}; margin-top: 1rem;'>"
        f"Charred Scallion Relish: +{yoy_units_pct:.0f}% growth — "
        f"or {baseline_pct:.0f}% decline?</h4>",
        unsafe_allow_html=True,
    )
    render_chart_legend([
        (NAVY_MED, "Total weekly velocity (what the report sees)"),
        (RED,      "Baseline only (non-promo weeks — the real trend)"),
        (ORANGE,   "Promo weeks"),
    ])

    fig = go.Figure()
    # Promo-week vertical shading so the reader sees how much of the upside is paid for
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
    # Line 2: baseline (non-promo) velocity. NaNs on promo weeks so the line breaks
    fig.add_trace(go.Scatter(
        x=weekly["week_ending"], y=weekly["baseline_v"],
        mode="lines+markers", connectgaps=False,
        line=dict(color=RED, width=2.5, dash="dot"),
        marker=dict(size=5, color=RED),
        name="Baseline velocity (non-promo only)",
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>Baseline: %{y:.2f} u/store/wk<extra></extra>",
    ))
    # Trend annotation: where the baseline is heading
    if not weekly.empty:
        bl = weekly.dropna(subset=["baseline_v"])
        if len(bl) >= 8:
            x_first = bl.iloc[len(bl)//2:].head(8)["baseline_v"].mean()
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
    st.plotly_chart(fig, use_container_width=True)

    _narration(
        f"Charred Scallion Relish moved <b>{yoy_units_pct:.1f}% more units</b> "
        f"this year than last. But strip out the promotional weeks and the "
        f"real velocity — the rate at which consumers pick this product off "
        f"the shelf without a discount — dropped <b style='color:{RED}'>"
        f"{baseline_pct:.1f}%</b>. The brand spent "
        f"<b style='color:{RED}'>${trade_spend:,.0f}</b> in trade to make a "
        f"shrinking SKU look like a growing one."
    )

    st.divider()

    # ---- Section 3: What $18,701 Bought ----
    _eyebrow("Section 3 of 5")
    _h2(f"What ${trade_spend:,.0f} Bought — Promo ROI")

    hangover = get_promo_hangover_data(PROTAGONIST_SKU)
    hangover = hangover.dropna(subset=["pre_v", "promo_v", "post_v"]).reset_index(drop=True)

    if hangover.empty:
        st.info("No comparable pre/during/post promo windows yet for this SKU.")
    else:
        st.markdown(
            f"<h4 style='color:{NAVY}; margin-top: 0.4rem;'>"
            f"Every promotion left the baseline lower than before</h4>",
            unsafe_allow_html=True,
        )
        render_chart_legend([
            (NAVY_MED, "Pre-promo baseline (4 weeks before)"),
            (TEAL,     "During promo"),
            (RED,      "Post-promo (4 weeks after)"),
        ])

        # Grouped bar: one cluster per promo, three bars (pre/promo/post)
        labels = [f"{r['retailer']}<br><span style='color:{GREY}; font-size:10px'>"
                  f"{r['promo_type']} · {r['discount_depth_pct']*100:.0f}% off · "
                  f"{r['start_week'][:7]}</span>"
                  for _, r in hangover.iterrows()]

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
        st.plotly_chart(fig3, use_container_width=True)

        # Compute net effect: incremental units gained vs. baseline erosion cost
        # Use wholesale margin per unit so the dollar number is honest.
        cost_row = get_connection().execute(
            "SELECT wholesale_walmart, cogs_per_unit FROM sku_costs WHERE sku=?",
            [PROTAGONIST_SKU],
        ).fetchone()
        ws = (cost_row[0] or 0)
        cogs = (cost_row[1] or 0)
        margin_per_unit = max(ws - cogs, 0.0)

        incr_units_total = ((hangover["promo_v"] - hangover["pre_v"])
                            * hangover["doors"] * hangover["duration_weeks"]).clip(lower=0).sum()
        # Hangover units lost = (pre - post) * doors * 4 weeks (post window)
        hangover_units_total = ((hangover["pre_v"] - hangover["post_v"])
                                * hangover["doors"] * 4).clip(lower=0).sum()
        net_units = incr_units_total - hangover_units_total
        net_dollars = net_units * margin_per_unit

        n_backfired = int((hangover["post_v"] < hangover["pre_v"]).sum())

        c1, c2, c3 = st.columns(3)
        c1.metric("Incremental units (during promo)", f"{incr_units_total:,.0f}")
        c2.metric("Units lost in post-promo dip", f"{hangover_units_total:,.0f}",
                  delta_color="off")
        c3.metric("Net effect (margin terms)",
                  f"${net_dollars:,.0f}",
                  delta=("Backfired" if net_dollars < 0 else "Net positive"),
                  delta_color=("inverse" if net_dollars < 0 else "normal"))

        n_promos = len(hangover)
        _narration(
            f"The {n_promos} measurable promotions on Charred Scallion Relish "
            f"each followed the same pattern: a short spike in volume, "
            f"followed by a post-promo dip that settled "
            f"<b>{'below where it started' if n_backfired >= n_promos / 2 else 'near or below where it started'}</b>"
            f" in {n_backfired} of {n_promos} cases. The brand didn't just "
            f"spend <b style='color:{RED}'>${trade_spend:,.0f}</b> to stand still — "
            f"after netting promo lift against post-promo erosion, the cumulative "
            f"effect on margin is "
            f"<b style='color:{RED if net_dollars < 0 else TEAL}'>"
            f"${net_dollars:,.0f}</b>."
        )

    st.divider()

    # ---- Section 4: The Shelf Is Watching ----
    _eyebrow("Section 4 of 5")
    _h2("The Shelf Is Watching — Velocity Trajectory vs Threshold")

    walmart_threshold = RETAILER_THRESHOLDS["Walmart"]
    traj = get_walmart_trajectory(PROTAGONIST_SKU)
    traj = traj.dropna(subset=["t13"]).reset_index(drop=True)

    if traj.empty or len(traj) < 4:
        st.info("Not enough Walmart trajectory data to project a delisting date.")
    else:
        # Linear projection from the trailing 13wk avg curve over the last 26
        # weeks (recent rate-of-change is what predicts the next quarter, not
        # the full multi-year history).
        proj_window = traj.tail(26)
        x_num = (proj_window["week_ending"] - proj_window["week_ending"].iloc[0]).dt.days.values
        y_num = proj_window["t13"].values
        slope_per_day = ((x_num * y_num).mean() - x_num.mean() * y_num.mean()) / max(((x_num**2).mean() - x_num.mean()**2), 1e-9)
        intercept = y_num.mean() - slope_per_day * x_num.mean()

        last_date = traj["week_ending"].iloc[-1]
        last_t13  = traj["t13"].iloc[-1]

        # When does the projection cross the threshold?
        # y(t) = last_t13 + slope_per_day * (t - last_date_in_days)
        if slope_per_day < 0 and last_t13 > walmart_threshold:
            days_to_cross = (walmart_threshold - last_t13) / slope_per_day
            cross_date = last_date + pd.Timedelta(days=days_to_cross)
        else:
            cross_date = None
            days_to_cross = None

        # Build a forward projection 78 weeks out (or until threshold)
        horizon_days = min(int(days_to_cross) + 28, 78 * 7) if days_to_cross else 78 * 7
        proj_dates = pd.date_range(last_date, last_date + pd.Timedelta(days=horizon_days), freq="W-SAT")
        proj_days = (proj_dates - last_date).days
        proj_y = last_t13 + slope_per_day * proj_days

        cross_quarter_str = ""
        if cross_date is not None:
            q = (cross_date.month - 1) // 3 + 1
            cross_quarter_str = f"Q{q} {cross_date.year}"

        title_phrase = (f"hits the Walmart delisting threshold in "
                        f"<b style='color:{RED}'>{cross_quarter_str}</b>"
                        if cross_quarter_str else
                        "stays above the Walmart delisting threshold for now")
        st.markdown(
            f"<h4 style='color:{NAVY}; margin-top: 0.4rem;'>"
            f"At current trajectory, Charred Scallion Relish "
            f"{title_phrase}</h4>",
            unsafe_allow_html=True,
        )
        render_chart_legend([
            (NAVY_MED, "Trailing 13-week avg velocity (Walmart)"),
            (ORANGE,   "Projected at current decline rate"),
            (RED,      f"Walmart delisting threshold ({walmart_threshold:.1f} u/sw)"),
        ])

        fig4 = go.Figure()
        # historical
        fig4.add_trace(go.Scatter(
            x=traj["week_ending"], y=traj["t13"],
            mode="lines", line=dict(color=NAVY_MED, width=2.5),
            hovertemplate="<b>%{x|%b %Y}</b><br>T13 vel: %{y:.2f} u/sw<extra></extra>",
        ))
        # projection
        fig4.add_trace(go.Scatter(
            x=proj_dates, y=proj_y,
            mode="lines", line=dict(color=ORANGE, width=2.5, dash="dash"),
            hovertemplate="<b>%{x|%b %Y}</b><br>Projected: %{y:.2f} u/sw<extra></extra>",
        ))
        # threshold line
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
        st.plotly_chart(fig4, use_container_width=True)

        rev = get_sku_revenue_at_risk(PROTAGONIST_SKU)
        decline_per_quarter = abs(slope_per_day) * 91
        if cross_date is not None:
            timeframe = f"by {cross_quarter_str}"
        else:
            timeframe = "in the near term"

        _narration(
            f"Walmart reviews velocity quarterly. The category threshold is "
            f"<b>{walmart_threshold:.1f} units/store/week</b>. Charred Scallion "
            f"Relish is currently at <b>{last_t13:.2f}</b>, declining at "
            f"<b>{decline_per_quarter:.2f}</b> units/store/week per quarter. "
            f"If nothing changes, it crosses the threshold "
            f"<b>{timeframe}</b>. That's "
            f"<b>{rev['walmart_doors']:,}</b> doors and "
            f"<b>${rev['annual_rev_walmart']:,.0f}</b> in annual revenue at risk."
        )

        st.session_state["_story_walmart_rev"] = rev
        st.session_state["_story_cross_date"]  = cross_date

    st.divider()

    # ---- Section 5: The Total Cost of Not Knowing ----
    _eyebrow("Section 5 of 5")
    _h2("The Total Cost of Not Knowing")

    rev = st.session_state.get("_story_walmart_rev") or get_sku_revenue_at_risk(PROTAGONIST_SKU)
    cat_avg = get_category_avg_velocity("Specialty Condiments")
    walmart_v = rev["walmart_v_t13"]
    walmart_doors = rev["walmart_doors"]
    margin_per_unit = max(rev["wholesale_walmart"] - rev["cogs"], 0.0)

    # Margin destroyed = annualized baseline erosion. Compare what the SKU
    # earned in the prior 26-week baseline window vs what it would have
    # earned at recent baseline, and pull that gap forward over a year.
    annual_erosion_units = max(prior_baseline - recent_baseline, 0) * walmart_doors * 52
    margin_destroyed = annual_erosion_units * margin_per_unit

    revenue_at_risk = rev["annual_rev_walmart"]

    total_cost = trade_spend + margin_destroyed + revenue_at_risk

    st.markdown(
        f"""
        <div style='background-color: {WHITE}; border: 1px solid {GREY_LIGHT};
                    border-left: 8px solid {RED}; border-radius: 6px;
                    padding: 1.4rem 1.8rem; margin: 1rem 0;
                    box-shadow: 0 2px 6px rgba(192, 34, 31, 0.08);'>
          <div style='color: {NAVY_MED}; font-size: 0.85rem;
                      font-weight: 600; letter-spacing: 0.18rem;
                      text-transform: uppercase;'>
            Total Cost of Not Knowing
          </div>
          <div style='color: {RED}; font-family: Georgia, serif;
                      font-size: 3.4rem; font-weight: 700;
                      margin: 0.3rem 0 0.6rem 0; line-height: 1;'>
            ${total_cost:,.0f}
          </div>
          <div style='color: {NAVY_MED}; font-size: 0.95rem;
                      max-width: 720px;'>
            One SKU. One year. Three buckets that never appear in the
            Monday morning report.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Trade spend burned",
               f"${trade_spend:,.0f}",
               delta="On a SKU with declining baseline", delta_color="off")
    cc2.metric("Annualized margin destroyed",
               f"${margin_destroyed:,.0f}",
               delta=f"vs. holding baseline at {prior_baseline:.1f} u/sw",
               delta_color="off")
    cc3.metric("Walmart revenue at risk",
               f"${revenue_at_risk:,.0f}",
               delta=f"{walmart_doors:,} doors below threshold trajectory",
               delta_color="off")

    _narration(
        f"Every number in the Monday morning report was accurate. The "
        f"portfolio was up. Revenue was up. Charred Scallion Relish was "
        f"up {yoy_units_pct:.0f}%. And underneath those green arrows, "
        f"<b style='color:{RED}'>${total_cost:,.0f}</b> in value was being "
        f"destroyed — invisible to every pivot table in the building."
    )

    st.markdown(
        f"<div style='font-size: 1.08rem; color: {NAVY}; "
        f"margin: 1.2rem 0 0.7rem 0;'>"
        f"This is one SKU. The Velocity Decision Tool runs this analysis "
        f"across all 90. Pick a decision from the sidebar — or jump "
        f"straight into the relevant view below."
        f"</div>",
        unsafe_allow_html=True,
    )

    # Jump-to-decision buttons. Indices match the (Story-free) DECISIONS list.
    # Use `on_click` instead of inline state writes — Streamlit blocks writes
    # to a widget's own key after the widget has instantiated.
    b1, b2, b3, b4 = st.columns(4)
    b1.button("→ Shelf Defense", use_container_width=True,
              key="story_jump_shelf",
              on_click=_switch_decision, args=(DECISIONS[0],))
    b2.button("→ Promo ROI", use_container_width=True,
              key="story_jump_promo",
              on_click=_switch_decision, args=(DECISIONS[2],))
    b3.button("→ Pricing Power", use_container_width=True,
              key="story_jump_pricing",
              on_click=_switch_decision, args=(DECISIONS[7],))
    b4.button("→ SKU Rationalization", use_container_width=True,
              key="story_jump_rat",
              on_click=_switch_decision, args=(DECISIONS[5],))

    st.divider()

    # ---- "What the rest of the portfolio looks like" coda ----
    _eyebrow("Coda")
    _h2("What the rest of the portfolio looks like")
    st.markdown(
        f"<div style='color: {NAVY_MED}; font-size: 1rem; max-width: 820px;'>"
        f"Not every SKU is Charred Scallion Relish. Most of the portfolio is "
        f"healthy, with normal demand signals and clear opportunities. The "
        f"four panels below are tactical pulls from the rest of the tool — "
        f"the day-to-day decisions you'll come back for once the protagonist "
        f"is dealt with."
        f"</div>",
        unsafe_allow_html=True,
    )

    # 1. Production Planning
    st.markdown(f"<h4 style='color:{NAVY}; margin-top:1.2rem;'>1. Production Planning</h4>",
                unsafe_allow_html=True)
    demand = get_top_demand_4wk()
    if not demand.empty:
        top1 = demand.iloc[0]
        st.markdown(
            f"<div style='color:{NAVY_MED}; font-size:0.98rem;'>"
            f"Demand signals align with current production cadence. Over the "
            f"trailing 4 weeks, "
            f"<b>{top1['product_name']}</b> ({top1['sku']}) led "
            f"the portfolio at <b>{top1['cases_4wk']:,.0f} cases</b>. The top "
            f"10 SKUs by projected case demand are listed below — set "
            f"production to match the next 4 weeks. "
            f"<i>Explore this in the Production Planning tab →</i>"
            f"</div>",
            unsafe_allow_html=True,
        )
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
        st.plotly_chart(figp, use_container_width=True)

    # 2. Distribution Expansion
    st.markdown(f"<h4 style='color:{NAVY}; margin-top:1.2rem;'>2. Distribution Expansion</h4>",
                unsafe_allow_html=True)
    chains = get_top_velocity_per_door()
    if not chains.empty:
        top1 = chains.iloc[0]
        st.markdown(
            f"<div style='color:{NAVY_MED}; font-size:0.98rem;'>"
            f"<b>{top1['chain']}</b> leads on per-door productivity at "
            f"<b>{top1['vel_per_door']:.2f} units/store/week</b>, well above "
            f"the chain average. The chains below earn their shelf — start "
            f"there before opening new ones. "
            f"<i>Explore this in the Distribution Expansion tab →</i>"
            f"</div>",
            unsafe_allow_html=True,
        )
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
        st.plotly_chart(fige, use_container_width=True)

    # 3. Distribution Pruning
    st.markdown(f"<h4 style='color:{NAVY}; margin-top:1.2rem;'>3. Distribution Pruning</h4>",
                unsafe_allow_html=True)
    weak = get_bottom_stores_below_threshold(threshold=2.0)
    if weak.empty:
        st.markdown(
            f"<div style='color:{NAVY_MED}; font-size:0.98rem;'>"
            f"No Walmart velocity data in the last 13 weeks. "
            f"<i>Explore this in the Distribution Pruning tab →</i>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        n_below = int((weak["gap"] > 0).sum())
        if n_below > 0:
            lede = (f"<b>{n_below}</b> of the 10 weakest Walmart stores fall "
                    f"below the 2.0 u/sw threshold over the last 13 weeks.")
        else:
            lede = ("All Walmart stores currently sit above the 2.0 u/sw "
                    "threshold, but the bottom of the distribution is "
                    "tracking close.")
        st.markdown(
            f"<div style='color:{NAVY_MED}; font-size:0.98rem;'>"
            f"{lede} Pruning underperformers frees up working capital and "
            f"reduces chargeback exposure. "
            f"<i>Explore this in the Distribution Pruning tab →</i>"
            f"</div>",
            unsafe_allow_html=True,
        )
        # Bar color is RED when below the threshold, ORANGE when above but in
        # the bottom-10 — gives the chart a green/red read without lying about
        # the underlying state.
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
        st.plotly_chart(figpr, use_container_width=True)

    # 4. Pricing Power
    st.markdown(f"<h4 style='color:{NAVY}; margin-top:1.2rem;'>4. Pricing Power</h4>",
                unsafe_allow_html=True)
    elasticity = get_top_elasticity_skus()
    if not elasticity.empty:
        top1 = elasticity.iloc[0]
        st.markdown(
            f"<div style='color:{NAVY_MED}; font-size:0.98rem;'>"
            f"<b>{top1['product_name']}</b> ({top1['sku']}) is the most "
            f"elastic SKU in the portfolio — every 1% of discount yielded "
            f"<b>{top1['elasticity']:.2f}%</b> of unit lift. Highly elastic "
            f"SKUs respond well to promotion; inelastic ones are giving up "
            f"margin without earning incremental volume. "
            f"<i>Explore this in the Pricing Power tab →</i>"
            f"</div>",
            unsafe_allow_html=True,
        )
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
        st.plotly_chart(figel, use_container_width=True)


# ============================================================
# DECISION 1 — SHELF DEFENSE
# ============================================================

@st.cache_data(show_spinner="Loading shelf-defense data...")
def get_shelf_defense_data(retailer: str, product_line: str | None) -> pd.DataFrame:
    con = get_connection()
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = 0
        ),
        agg AS (
            SELECT
              d.sku,
              AVG(CASE WHEN julianday(?) - julianday(d.week_ending) < 56
                       THEN d.units_sold END) AS current_v,
              AVG(CASE WHEN julianday(?) - julianday(d.week_ending) >= 56
                        AND julianday(?) - julianday(d.week_ending) < 112
                       THEN d.units_sold END) AS trailing_v
            FROM scan_data d
            JOIN ret_stores rs ON d.store_id = rs.store_id
            WHERE julianday(?) - julianday(d.week_ending) < 112
            GROUP BY d.sku
        )
        SELECT pm.sku, pm.product_name, pm.product_line,
               agg.current_v, agg.trailing_v
        FROM agg JOIN product_master pm ON agg.sku = pm.sku
        ORDER BY pm.sku
    """
    df = pd.read_sql(sql, con, params=ret_params + [latest, latest, latest, latest])
    if product_line:
        df = df[df["product_line"] == product_line]
    return df.dropna(subset=["current_v"]).reset_index(drop=True)


def classify_shelf_status(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    df = df.copy()
    df["trend_pct"] = (df["current_v"] - df["trailing_v"]) / df["trailing_v"] * 100
    warn_mult = THRESHOLDS["shelf_warning_mult"]
    warn_upper = threshold * warn_mult

    def classify(row: pd.Series) -> str:
        # Use raw computed velocity, not rounded. Display will show 2 decimals
        # so the CEO sees the actual value (1.96, 2.04) and the classification
        # matches it exactly: 1.96 < 2.0 → At Risk, no boundary illusion.
        c = row["current_v"]
        t = row["trailing_v"]
        if c < threshold:
            return "At Risk"
        # Warning = at-or-above threshold, strictly below warn_upper, AND
        # trailing higher than current (declining toward the line).
        if c < warn_upper and pd.notna(t) and t > c:
            return "Warning"
        return "Safe"

    df["status"] = df.apply(classify, axis=1)
    return df


def render_shelf_defense(retailer: str, product_line: str | None, threshold: float) -> None:
    latest = get_latest_week()

    st.caption(
        f"Retailer: **{retailer}**  |  Delisting threshold: "
        f"**{threshold:.2f} units/store/week**  |  Most recent week: **{latest}**"
    )

    df = get_shelf_defense_data(retailer, product_line)
    if df.empty:
        st.warning(
            f"No SKUs with recent activity at {retailer}"
            + (f" in {product_line}" if product_line else "") + "."
        )
        return

    df = classify_shelf_status(df, threshold)
    n_atrisk = int((df["status"] == "At Risk").sum())
    n_warn = int((df["status"] == "Warning").sum())
    n_safe = int((df["status"] == "Safe").sum())

    if n_atrisk > 0:
        st.markdown(
            f"### {n_atrisk} SKU{'s' if n_atrisk != 1 else ''} below the {retailer} "
            f"delisting threshold of {threshold:.2f} units/store/week."
        )
    elif n_warn > 0:
        st.markdown(
            f"### No SKUs are below the {retailer} threshold yet, but "
            f"{n_warn} are in the warning zone."
        )
    else:
        st.markdown(f"### All SKUs are safely above the {retailer} threshold of {threshold:.2f}.")

    c1, c2, c3 = st.columns(3)
    c1.metric("At Risk", n_atrisk)
    c2.metric("Warning", n_warn)
    c3.metric("Safe", n_safe)

    warn_mult = THRESHOLDS["shelf_warning_mult"]
    warn_upper = threshold * warn_mult
    # Wording mirrors the operators in classify_shelf_status: "below X" = <,
    # "X or above" = ≥, "below Y" = <, "Y or above" = ≥. Velocity values
    # are shown to 2 decimals so a 1.96 reads as 1.96, not "2.0", and the
    # "below 2.00" classification is visibly correct.
    render_status_legend(
        f"<b>Status definitions:</b> "
        f"<b style='color:{RED}'>At Risk</b> = current velocity below "
        f"{threshold:.2f} (strictly less than).  "
        f"<b style='color:{ORANGE}'>Warning</b> = velocity {threshold:.2f} or "
        f"above, but below {warn_upper:.2f}, <i>and</i> trailing higher than "
        f"current (declining toward threshold).  "
        f"<b style='color:{TEAL}'>Safe</b> = velocity {warn_upper:.2f} or "
        f"above, or in the warning band but not declining."
    )
    render_row_count_line("SKUs", [
        (n_atrisk, "At Risk"),
        (n_warn, "Warning"),
        (n_safe, "Safe"),
    ])

    display_df = pd.DataFrame({
        "SKU":                df["sku"],
        "Product Name":       df["product_name"],
        "Product Line":       df["product_line"],
        "Current Velocity":   df["current_v"].round(2),
        "Trailing Velocity":  df["trailing_v"].round(2),
        "Trend %":            df["trend_pct"].round(2),
        "Threshold":          round(threshold, 2),
        "Status":             df["status"],
    })
    status_order = {"At Risk": 0, "Warning": 1, "Safe": 2}
    display_df = (
        display_df.assign(_o=display_df["Status"].map(status_order))
        .sort_values(["_o", "Current Velocity"]).drop(columns="_o").reset_index(drop=True)
    )

    styled = display_df.style.apply(make_row_styler(SHELF_ROW), axis=1).format({
        "Current Velocity":  "{:.2f}",
        "Trailing Velocity": "{:.2f}",
        "Trend %":           "{:+.2f}%",
        "Threshold":         "{:.2f}",
    }, na_rep="—")
    st.dataframe(styled, use_container_width=True, hide_index=True, height=460)

    n_show = min(15, len(display_df))
    weakest = display_df.nsmallest(n_show, "Current Velocity").copy()
    chart_title = (
        f"The {n_show} weakest SKUs at {retailer}"
        if n_atrisk > 0
        else f"The {n_show} lowest-velocity SKUs at {retailer} (all currently safe)"
    )
    st.markdown(f"#### {chart_title}")
    st.caption(
        f"Sorted weakest to strongest. Bars to the left of the dashed line "
        f"({threshold:.2f}) are at risk of delisting."
    )
    render_chart_legend([
        (RED,    f"At Risk (<{threshold:.2f})"),
        (ORANGE, f"Warning ({threshold:.2f} ≤ v < {warn_upper:.2f}, declining)"),
        (TEAL,   f"Safe (v ≥ {warn_upper:.2f}, or in band but stable)"),
    ])

    fig = go.Figure()
    for status in ("At Risk", "Warning", "Safe"):
        sub = weakest[weakest["Status"] == status]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["SKU"], x=sub["Current Velocity"], orientation="h",
            marker_color=SHELF_STATUS_COLORS[status],
            text=sub["Current Velocity"].map(lambda v: f"{v:.2f}"),
            textposition="outside", textfont=dict(size=14, color=NAVY),
            cliponaxis=False,
            customdata=sub[["Product Name", "Trailing Velocity", "Trend %"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "Current: %{x:.2f} units/store/wk<br>"
                "Trailing: %{customdata[1]:.2f} units/store/wk<br>"
                "Trend: %{customdata[2]:+.2f}%<br>"
                f"Status: {status}<extra></extra>"
            ),
        ))
    fig.add_vline(
        x=threshold, line_dash="dash", line_color=GREY, line_width=2,
        annotation=text_annotation(f"Delisting threshold {threshold:.2f}"),
        annotation_position="top",
    )
    apply_hbar_layout(
        fig,
        labels=weakest["SKU"].tolist(),
        height=max(380, 32 * n_show + 120),
        x_title="Units per store per week (last 8 weeks)",
        label_pad_px=180,
        left_margin=200,
    )
    st.plotly_chart(fig, use_container_width=True)

    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")
    excel_button(display_df, "Shelf Defense", f"shelf_defense_{safe_ret}_{safe_pl}")


# ============================================================
# DECISION 2 — PRODUCTION PLANNING
# ============================================================

@st.cache_data(show_spinner="Loading production data...")
def get_production_data(retailer: str, product_line: str | None) -> pd.DataFrame:
    con = get_connection()
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id, s.is_aggregated_channel FROM stores s
            WHERE {ret_sql}
        ),
        physical AS (
            SELECT d.sku,
              AVG(CASE WHEN julianday(?) - julianday(d.week_ending) < 28
                       THEN d.units_sold END) AS phys_v_recent,
              AVG(CASE WHEN julianday(?) - julianday(d.week_ending) >= 28
                        AND julianday(?) - julianday(d.week_ending) < 56
                       THEN d.units_sold END) AS phys_v_prior,
              COUNT(DISTINCT CASE WHEN julianday(?) - julianday(d.week_ending) < 28
                                   THEN d.store_id END) AS doors
            FROM scan_data d
            JOIN ret_stores rs ON d.store_id = rs.store_id AND rs.is_aggregated_channel = 0
            WHERE julianday(?) - julianday(d.week_ending) < 56
            GROUP BY d.sku
        ),
        all_chan AS (
            SELECT d.sku,
              SUM(CASE WHEN julianday(?) - julianday(d.week_ending) < 28
                       THEN d.units_sold END) AS sum_recent,
              SUM(CASE WHEN julianday(?) - julianday(d.week_ending) BETWEEN 364 AND 392
                       THEN d.units_sold END) AS sum_ly_current,
              SUM(CASE WHEN julianday(?) - julianday(d.week_ending) BETWEEN 336 AND 364
                       THEN d.units_sold END) AS sum_ly_forward
            FROM scan_data d
            JOIN ret_stores rs ON d.store_id = rs.store_id
            WHERE julianday(?) - julianday(d.week_ending) < 393
            GROUP BY d.sku
        )
        SELECT pm.sku, pm.product_name, pm.product_line, pm.case_pack_qty,
               COALESCE(p.doors, 0) AS doors,
               p.phys_v_recent, p.phys_v_prior,
               a.sum_recent, a.sum_ly_current, a.sum_ly_forward
        FROM all_chan a
        JOIN product_master pm ON a.sku = pm.sku
        LEFT JOIN physical p ON a.sku = p.sku
        WHERE a.sum_recent > 0
        ORDER BY a.sum_recent DESC
    """
    params = ret_params + [latest] * 9
    df = pd.read_sql(sql, con, params=params)
    if product_line:
        df = df[df["product_line"] == product_line].reset_index(drop=True)

    df["weekly_units"] = (df["sum_recent"] / 4).round(0)
    df["weekly_cases"] = (df["weekly_units"] / df["case_pack_qty"]).round(2)

    sf = df["sum_ly_forward"] / df["sum_ly_current"].replace(0, pd.NA)
    sf = sf.where(sf.notna(), 1.0).clip(lower=0.5, upper=2.0)
    df["seasonal_factor"] = sf
    df["forecast_4w_units"] = (df["weekly_units"] * sf * 4).round(0)
    df["forecast_4w_cases"] = (df["forecast_4w_units"] / df["case_pack_qty"]).round(2)

    trend = (df["phys_v_recent"] - df["phys_v_prior"]) / df["phys_v_prior"].replace(0, pd.NA) * 100
    df["trend_pct"] = trend

    accel_pct = THRESHOLDS["production_trend_accel"] * 100
    decel_pct = THRESHOLDS["production_trend_decel"] * 100

    def status(t: float) -> str:
        if pd.isna(t):
            return "Stable"
        if t > accel_pct:
            return "Accelerating"
        if t < decel_pct:
            return "Decelerating"
        return "Stable"

    df["status"] = df["trend_pct"].apply(status)
    return df


def render_production_planning(retailer: str, product_line: str | None) -> None:
    latest = get_latest_week()
    st.caption(
        f"Retailer scope: **{retailer}**  |  Window: last 4 weeks  "
        f"|  Most recent week: **{latest}**  "
        "|  Forecast adjusted by year-over-year seasonality."
    )

    df = get_production_data(retailer, product_line)
    if df.empty:
        st.warning(
            f"No SKUs with recent activity at {retailer}"
            + (f" in {product_line}" if product_line else "") + "."
        )
        return

    n_total = len(df)
    n_accel = int((df["status"] == "Accelerating").sum())
    n_decel = int((df["status"] == "Decelerating").sum())

    if n_accel > 0:
        st.markdown(
            f"### {n_accel} of {n_total} SKUs are accelerating "
            f"(velocity up >10%) and may stock out without a production increase."
        )
    elif n_decel > 0:
        st.markdown(
            f"### No SKUs are accelerating sharply. "
            f"{n_decel} are decelerating and may risk overstock."
        )
    else:
        st.markdown(f"### All {n_total} SKUs are running at stable velocity.")

    total_units = int(df["weekly_units"].sum())
    total_cases = int(df["weekly_cases"].sum())
    forecast_cases = int(df["forecast_4w_cases"].sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Forecasted weekly demand (units)", f"{total_units:,}")
    c2.metric("Forecasted weekly demand (cases)", f"{total_cases:,}")
    c3.metric("Next 4-wk production target (cases)", f"{forecast_cases:,}")
    c4.metric("Accelerating SKUs", n_accel)

    st.markdown(
        "This forecast uses trailing 4-week velocity adjusted for seasonal "
        "patterns. If the same period last year ran above the annual average, "
        "the forecast adjusts upward — and vice versa. These are production "
        "targets, not historical summaries."
    )

    n_stable = n_total - n_accel - n_decel
    accel_pct = THRESHOLDS["production_trend_accel"] * 100
    decel_pct = THRESHOLDS["production_trend_decel"] * 100
    render_status_legend(
        f"<b>Status definitions</b> (4-week trend vs prior 4 weeks): "
        f"<b style='color:{TEAL}'>Accelerating</b> = trend &gt; "
        f"{accel_pct:+.2f}% (good — raise production).  "
        f"<b style='color:{RED}'>Decelerating</b> = trend &lt; "
        f"{decel_pct:+.2f}% (bad — consider trimming).  "
        f"<b style='color:{NAVY_MED}'>Stable</b> = trend within "
        f"±{accel_pct:.2f}%."
    )
    render_row_count_line("SKUs", [
        (n_accel, "Accelerating"),
        (n_decel, "Decelerating"),
        (n_stable, "Stable"),
    ])

    display_df = pd.DataFrame({
        "SKU":                              df["sku"],
        "Product Name":                     df["product_name"],
        "Product Line":                     df["product_line"],
        "Doors":                            df["doors"].astype(int),
        "Forecasted weekly demand (units)": df["weekly_units"].astype(int),
        "Forecasted weekly demand (cases)": df["weekly_cases"],
        "Next 4-Wk Production Target (cases)": df["forecast_4w_cases"],
        "Trend %":                          df["trend_pct"].round(2),
        "Status":                           df["status"],
    })
    status_order = {"Accelerating": 0, "Decelerating": 1, "Stable": 2}
    display_df = (
        display_df.assign(_o=display_df["Status"].map(status_order))
        .sort_values(["_o", "Forecasted weekly demand (units)"], ascending=[True, False])
        .drop(columns="_o").reset_index(drop=True)
    )

    styled = display_df.style.apply(make_row_styler(PRODUCTION_ROW), axis=1).format({
        "Forecasted weekly demand (cases)":     "{:.2f}",
        "Next 4-Wk Production Target (cases)":  "{:.2f}",
        "Trend %":                              "{:+.2f}%",
    }, na_rep="—")
    st.dataframe(styled, use_container_width=True, hide_index=True, height=460)

    n_show = min(20, len(display_df))
    top = display_df.nlargest(n_show, "Next 4-Wk Production Target (cases)").copy()
    st.markdown(
        f"#### Top {n_show} SKUs by forecasted case demand for the next 4 weeks"
    )
    st.caption(
        "Bars colored teal = accelerating (raise production), red = decelerating "
        "(consider trimming), navy = stable."
    )
    render_chart_legend([
        (TEAL,     f"Accelerating (trend > {accel_pct:+.2f}%)"),
        (RED,      f"Decelerating (trend < {decel_pct:+.2f}%)"),
        (NAVY_MED, f"Stable (±{accel_pct:.2f}%)"),
    ])

    fig = go.Figure()
    for status in ("Accelerating", "Decelerating", "Stable"):
        sub = top[top["Status"] == status]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["SKU"], x=sub["Next 4-Wk Production Target (cases)"], orientation="h",
            marker_color=PRODUCTION_STATUS_COLORS[status],
            text=sub["Next 4-Wk Production Target (cases)"].map(lambda v: f"{v:.2f}"),
            textposition="outside", textfont=dict(size=14, color=NAVY),
            cliponaxis=False,
            customdata=sub[["Product Name", "Trend %", "Doors"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "Next 4-wk cases: %{x:.2f}<br>"
                "Trend: %{customdata[1]:+.2f}%<br>"
                "Doors: %{customdata[2]}<br>"
                f"Status: {status}<extra></extra>"
            ),
        ))
    apply_hbar_layout(
        fig,
        labels=top["SKU"].tolist(),
        height=max(420, 32 * n_show + 120),
        x_title="Forecasted cases for next 4 weeks",
        label_pad_px=180,
        left_margin=200,
    )
    st.plotly_chart(fig, use_container_width=True)

    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")
    excel_button(display_df, "Production Plan", f"production_plan_{safe_ret}_{safe_pl}")


# ============================================================
# DECISION 3 — PROMO ROI
# ============================================================

@st.cache_data(show_spinner="Loading promo ROI data...")
def get_promo_roi_data(retailer: str, sku_filter: str | None) -> pd.DataFrame:
    con = get_connection()
    ret_sql, ret_params = retailer_clause(retailer)
    is_agg = 1 if retailer in ("UNFI", "DTC") else 0

    sku_clause = ""
    sku_params: list = []
    if sku_filter:
        sku_clause = "AND p.sku = ?"
        sku_params = [sku_filter]

    # Only include (SKU, store) pairs where the SKU was already scanning at the
    # store at least 28 days before the promo start. Without this guard, SKUs
    # with delayed time-to-shelf produce near-zero baselines and absurd lift %.
    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = ?
        ),
        promo_list AS (
            SELECT promo_id, sku, retailer, start_week, end_week,
                   duration_weeks, discount_depth_pct, promo_type, store_scope
            FROM promotions p
            WHERE p.retailer = ? {sku_clause}
        ),
        sku_store_first_scan AS (
            SELECT sku, store_id, MIN(week_ending) AS first_scan
            FROM scan_data
            GROUP BY sku, store_id
        ),
        qualified_pairs AS (
            SELECT p.promo_id, p.sku, sf.store_id
            FROM promo_list p
            JOIN sku_store_first_scan sf ON sf.sku = p.sku
            JOIN ret_stores rs ON sf.store_id = rs.store_id
            WHERE sf.first_scan <= DATE(p.start_week, '-28 days')
        )
        SELECT
            p.promo_id, p.sku, p.retailer, p.start_week, p.end_week,
            p.duration_weeks, p.discount_depth_pct, p.promo_type, p.store_scope,
            pm.product_name, pm.product_line, sc.wholesale_price,
            (SELECT AVG(d.units_sold) FROM scan_data d
             JOIN qualified_pairs qp ON qp.sku = d.sku AND qp.store_id = d.store_id
             WHERE qp.promo_id = p.promo_id
               AND d.week_ending BETWEEN DATE(p.start_week, '-28 days')
                                     AND DATE(p.start_week, '-1 days')
            ) AS baseline_v,
            (SELECT AVG(d.units_sold) FROM scan_data d
             JOIN qualified_pairs qp ON qp.sku = d.sku AND qp.store_id = d.store_id
             WHERE qp.promo_id = p.promo_id
               AND d.week_ending BETWEEN p.start_week AND p.end_week
            ) AS promo_v,
            (SELECT AVG(d.units_sold) FROM scan_data d
             JOIN qualified_pairs qp ON qp.sku = d.sku AND qp.store_id = d.store_id
             WHERE qp.promo_id = p.promo_id
               AND d.week_ending BETWEEN DATE(p.end_week, '+7 days')
                                     AND DATE(p.end_week, '+21 days')
            ) AS post_v,
            (SELECT COUNT(DISTINCT qp.store_id) FROM qualified_pairs qp
             WHERE qp.promo_id = p.promo_id
            ) AS doors
        FROM promo_list p
        JOIN product_master pm ON p.sku = pm.sku
        JOIN sku_costs sc ON p.sku = sc.sku
        ORDER BY p.start_week DESC
    """
    df = pd.read_sql(sql, con, params=ret_params + [is_agg, retailer] + sku_params)
    if df.empty:
        return df

    bv, pv, pov = df["baseline_v"], df["promo_v"], df["post_v"]
    df["lift_pct"] = (pv - bv) / bv * 100
    df["dip_pct"] = (pov - bv) / bv * 100
    df["incremental_units"] = ((pv - bv) * df["doors"] * df["duration_weeks"]).round(0)
    df["incremental_revenue"] = (
        df["incremental_units"] * df["wholesale_price"] * (1 - df["discount_depth_pct"])
    ).round(0)
    df["promo_cost"] = (
        bv * df["doors"] * df["duration_weeks"] * df["wholesale_price"] * df["discount_depth_pct"]
    ).round(0)
    df["roi_pct"] = (
        (df["incremental_revenue"] - df["promo_cost"]) / df["promo_cost"].replace(0, pd.NA) * 100
    )
    return df


@st.cache_data(show_spinner=False)
def get_promo_weekly_velocity(promo_id: str, sku: str, retailer: str) -> pd.DataFrame:
    con = get_connection()
    ret_sql, ret_params = retailer_clause(retailer)
    is_agg = 1 if retailer in ("UNFI", "DTC") else 0

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = ?
        ),
        prom AS (
            SELECT start_week, end_week FROM promotions
            WHERE promo_id = ? AND sku = ?
            LIMIT 1
        )
        SELECT d.week_ending, AVG(d.units_sold) AS velocity
        FROM scan_data d, prom
        WHERE d.sku = ?
          AND d.store_id IN (SELECT store_id FROM ret_stores)
          AND d.week_ending BETWEEN DATE(prom.start_week, '-28 days')
                                AND DATE(prom.end_week, '+28 days')
        GROUP BY d.week_ending ORDER BY d.week_ending
    """
    return pd.read_sql(sql, con, params=ret_params + [is_agg, promo_id, sku, sku])


def render_promo_roi(retailer: str, sku_filter: str | None) -> None:
    st.caption(
        f"Retailer: **{retailer}**"
        + (f"  |  SKU: **{sku_filter}**" if sku_filter else "")
        + "  |  Baseline = 4 weeks pre-promo. Post = 3 weeks after end."
        + "  Stores with <4 weeks of pre-promo scan data are excluded."
    )

    df = get_promo_roi_data(retailer, sku_filter)
    if df.empty:
        st.warning(
            f"No promotions found for {retailer}"
            + (f" / {sku_filter}" if sku_filter else "") + "."
        )
        return

    df = df.dropna(subset=["baseline_v", "promo_v"])
    df = df[df["doors"] > 0]
    if df.empty:
        st.info("All promos for this retailer were stranded (no in-window scan data).")
        return

    # Three-tier ROI bucketing — a +397% promo and a +2% promo both used to
    # render teal, hiding the fact that some "positive" promos barely paid
    # for themselves. Strong (>100%), Marginal (0–100%), Negative (<0%).
    roi_strong_pct = THRESHOLDS["roi_strong"] * 100  # cutoff in % (e.g. 100)

    def _roi_tier(roi: float) -> str:
        if pd.isna(roi):
            return "Marginal ROI"
        if roi >= roi_strong_pct:
            return "Strong ROI"
        if roi >= 0:
            return "Marginal ROI"
        return "Negative ROI"

    df["roi_tier"] = df["roi_pct"].apply(_roi_tier)
    n_total = len(df)
    n_strong = int((df["roi_tier"] == "Strong ROI").sum())
    n_marginal = int((df["roi_tier"] == "Marginal ROI").sum())
    n_negative = int((df["roi_tier"] == "Negative ROI").sum())
    avg_lift = df["lift_pct"].mean()
    total_incr = df["incremental_revenue"].sum()
    total_cost = df["promo_cost"].sum()

    if n_strong >= n_marginal + n_negative:
        st.markdown(
            f"### {n_strong} of {n_total} promos at {retailer} delivered "
            f"strong ROI (>{roi_strong_pct:.2f}%)."
        )
    elif n_negative > 0:
        st.markdown(
            f"### Only {n_strong} of {n_total} promos at {retailer} delivered "
            f"strong ROI — {n_marginal} were marginal and {n_negative} lost money."
        )
    else:
        st.markdown(
            f"### {n_strong} strong + {n_marginal} marginal of {n_total} promos "
            f"at {retailer}. None lost money."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg lift", f"{avg_lift:+.2f}%")
    c2.metric("Incremental revenue", f"${total_incr:,.2f}")
    c3.metric("Total promo cost", f"${total_cost:,.2f}")
    c4.metric("Strong ROI promos", f"{n_strong} / {n_total}")

    render_status_legend(
        f"<b>ROI</b> = (incremental revenue − promo cost) ÷ promo cost × 100.  "
        f"<b style='color:{TEAL}'>Strong</b> (&gt;{roi_strong_pct:.2f}%) = "
        f"earned back more than double the spend.  "
        f"<b style='color:{ORANGE}'>Marginal</b> (0–{roi_strong_pct:.2f}%) = "
        f"covered costs but modest return.  "
        f"<b style='color:{RED}'>Negative</b> (&lt;0%) = lost money.  "
        f"Baseline = 4 weeks pre-promo at the same retailer."
    )
    render_row_count_line("promos", [
        (n_strong, "Strong ROI"),
        (n_marginal, "Marginal ROI"),
        (n_negative, "Negative ROI"),
    ])

    display_df = pd.DataFrame({
        "Promo ID":     df["promo_id"],
        "Start":        df["start_week"],
        "End":          df["end_week"],
        "SKU":          df["sku"],
        "Product Name": df["product_name"],
        "Type":         df["promo_type"],
        "Discount":     (df["discount_depth_pct"] * 100).round(0),
        "Scope":        df["store_scope"],
        "Baseline":     df["baseline_v"].round(2),
        "Promo":        df["promo_v"].round(2),
        "Lift %":       df["lift_pct"].round(2),
        "Dip %":        df["dip_pct"].round(2),
        "Incr. $":      df["incremental_revenue"].round(2),
        "Cost $":       df["promo_cost"].round(2),
        "ROI %":        df["roi_pct"].round(2),
        "Tier":         df["roi_tier"],
    }).reset_index(drop=True)

    def style_promo(row: pd.Series) -> list[str]:
        # Three-tier tint mirrors the chart and summary cards: Strong=teal,
        # Marginal=orange, Negative=red. NaN ROI falls back to neutral.
        tier = row["Tier"]
        if tier == "Strong ROI":
            bg, fg = GREEN_FAINT, TEAL
        elif tier == "Marginal ROI":
            bg, fg = ORANGE_FAINT, ORANGE
        elif tier == "Negative ROI":
            bg, fg = RED_FAINT, RED
        else:
            bg, fg = WHITE, GREY
        return [f"background-color: {bg}; color: {fg}"] * len(row)

    styled = display_df.style.apply(style_promo, axis=1).format({
        "Discount": "{:.2f}%", "Baseline": "{:.2f}", "Promo": "{:.2f}",
        "Lift %": "{:+.2f}%", "Dip %": "{:+.2f}%",
        "Incr. $": "${:,.2f}", "Cost $": "${:,.2f}", "ROI %": "{:+.2f}%",
    }, na_rep="—")
    st.dataframe(styled, use_container_width=True, hide_index=True, height=420)

    st.markdown("#### Best and worst promos by return on spend")
    st.caption(
        f"Bars colored teal = strong ROI (>{roi_strong_pct:.2f}%), "
        f"orange = marginal (0–{roi_strong_pct:.2f}%), red = negative."
    )
    render_chart_legend([
        (TEAL,   f"Strong ROI (>{roi_strong_pct:.2f}%)"),
        (ORANGE, f"Marginal ROI (0–{roi_strong_pct:.2f}%)"),
        (RED,    "Negative ROI (<0%)"),
    ])

    chart_df = display_df.dropna(subset=["ROI %"]).copy()
    chart_df["label"] = (
        chart_df["Promo ID"] + "  ·  " + chart_df["SKU"] + "  ·  " + chart_df["Type"]
    )
    winners = chart_df.nlargest(min(8, len(chart_df)), "ROI %")
    losers = chart_df.nsmallest(min(8, len(chart_df)), "ROI %")
    losers = losers[~losers["Promo ID"].isin(winners["Promo ID"])]
    # Sort DESCENDING by ROI so the biggest win is at the TOP of the chart.
    # autorange="reversed" (set globally in base_chart_layout) puts the first
    # row on top, so descending ROI → highest ROI on top, deepest losses at
    # the bottom. Matches the "most actionable at top" rule used by the other
    # charts (Pricing Power highest elasticity, SKU Rat largest margin, etc.).
    bars = pd.concat([winners, losers]).sort_values(
        "ROI %", ascending=False
    ).reset_index(drop=True)
    if not bars.empty:
        def _bar_color_for_roi(r: float) -> str:
            if r >= roi_strong_pct:
                return TEAL
            if r >= 0:
                return ORANGE
            return RED
        colors = [_bar_color_for_roi(r) for r in bars["ROI %"]]
        bar_tiers = [_roi_tier(r) for r in bars["ROI %"]]
        # Tooltip carries Product Name plus the financial drivers behind the
        # ROI tier (lift %, incremental $, cost $) so the CEO can read the
        # full story without leaving the chart.
        fig = go.Figure(go.Bar(
            y=bars["label"], x=bars["ROI %"], orientation="h",
            marker_color=colors,
            text=bars["ROI %"].map(lambda v: f"{v:+.2f}%"),
            textposition="outside", textfont=dict(size=14, color=NAVY),
            cliponaxis=False,
            customdata=list(zip(
                bars["Product Name"],
                bars["Lift %"],
                bars["Incr. $"],
                bars["Cost $"],
                bar_tiers,
            )),
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "ROI: %{x:+.2f}%<br>"
                "Lift: %{customdata[1]:+.2f}%<br>"
                "Incremental revenue: $%{customdata[2]:,.2f}<br>"
                "Promo cost: $%{customdata[3]:,.2f}<br>"
                "Tier: %{customdata[4]}<extra></extra>"
            ),
        ))
        fig.add_vline(x=0, line_color=GREY, line_width=2)
        fig.add_vline(
            x=roi_strong_pct, line_dash="dot", line_color=GREY, line_width=1.5,
            annotation=text_annotation(
                f"Strong/marginal cutoff ({roi_strong_pct:.2f}%)"
            ),
            annotation_position="top",
        )
        apply_hbar_layout(
            fig,
            labels=bars["label"].tolist(),
            height=max(380, 32 * len(bars) + 120),
            x_title="Return on promo spend (%)",
            label_pad_px=300,
            left_margin=320,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Drill into one promo")
    df_d = df.copy()
    df_d["label"] = (
        df_d["promo_id"] + "  ·  " + df_d["sku"]
        + "  ·  " + df_d["promo_type"]
        + "  ·  " + df_d["start_week"]
    )
    selected_label = st.selectbox(
        "Pick a promo to see weekly velocity before, during, and after:",
        options=df_d["label"].tolist(), index=0,
    )
    selected = df_d[df_d["label"] == selected_label].iloc[0]
    weekly = get_promo_weekly_velocity(selected["promo_id"], selected["sku"], retailer)
    if weekly.empty:
        st.info("No weekly scan data found for this promo's window.")
        return

    lift = selected["lift_pct"]
    dip = selected["dip_pct"]
    # Color the trend line by ROI verdict so the chart's coloring matches the
    # row tint in the table above and the bar color in the winners/losers chart.
    roi = selected.get("roi_pct")
    if pd.isna(roi):
        line_color = NAVY
    elif roi > 0:
        line_color = TEAL
    else:
        line_color = RED
    st.markdown(
        f"This {selected['promo_type']} promo on **{selected['sku']}** delivered a "
        f"**{lift:+.2f}% lift** during the promo and a **{dip:+.2f}%** swing in the 3 weeks after."
    )
    render_chart_legend([
        (TEAL, "Positive ROI (made money)"),
        (RED,  "Negative ROI (lost money)"),
    ])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=weekly["week_ending"], y=weekly["velocity"],
        mode="lines+markers",
        line=dict(color=line_color, width=3),
        marker=dict(size=8, color=line_color),
        hovertemplate="<b>%{x}</b><br>Velocity: %{y:.2f} units/store<extra></extra>",
    ))
    if pd.notna(selected["baseline_v"]):
        fig.add_hline(
            y=selected["baseline_v"],
            line_dash="dot", line_color=GREY,
            annotation=text_annotation(f"Pre-promo baseline {selected['baseline_v']:.2f}"),
            annotation_position="bottom right",
        )
    add_vline_at_date(
        fig, selected["start_week"], "Promo started",
        color=ORANGE, dash="dash", width=2,
        annotation_position="top left",
    )
    add_vline_at_date(
        fig, selected["end_week"],
        (f"Promo ended ({selected['duration_weeks']}wk · "
         f"{selected['discount_depth_pct']*100:.2f}% off)"),
        color=ORANGE, dash="dash", width=2,
        annotation_position="top right",
    )
    fig.update_layout(
        template="simple_white",
        paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
        height=420,
        margin=dict(l=10, r=10, t=40, b=40),
        yaxis=dict(
            title="Units per store per week",
            title_font=dict(size=14, color=NAVY_MED),
            tickfont=dict(size=13, color=NAVY),
            gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT,
        ),
        xaxis=dict(
            tickfont=dict(size=13, color=NAVY),
            gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT,
        ),
        showlegend=False,
        font=dict(family="sans-serif", size=14, color=NAVY),
    )
    st.plotly_chart(fig, use_container_width=True)

    safe_ret = retailer.lower().replace(" ", "_")
    safe_sku = (sku_filter or "all").lower()
    excel_button(display_df, "Promo ROI", f"promo_roi_{safe_ret}_{safe_sku}")


# ============================================================
# DECISION 4 — DISTRIBUTION EXPANSION
# ============================================================

@st.cache_data(show_spinner="Finding expansion opportunities...")
def get_expansion_data(focus_sku: str, retailer: str | None) -> pd.DataFrame:
    """Stores where focus_sku is NOT authorized but same-line SKUs perform well."""
    con = get_connection()
    latest = get_latest_week()

    # Determine retailer filter for stores
    if retailer is None or retailer == "All Retailers":
        ret_sql, ret_params = "1=1", []
    elif retailer == "Regional":
        ph = ",".join("?" for _ in REGIONAL_CHAINS)
        ret_sql, ret_params = f"s.retailer IN ({ph})", list(REGIONAL_CHAINS)
    else:
        ret_sql, ret_params = "s.retailer = ?", [retailer]

    sql = f"""
        WITH focus AS (SELECT product_line FROM product_master WHERE sku = ?),
        target_stores AS (
            SELECT s.store_id, s.retailer, s.region, s.state, s.volume_tier
            FROM stores s
            WHERE s.is_aggregated_channel = 0
              AND ({ret_sql})
              AND s.store_id NOT IN (
                  SELECT store_id FROM distribution_log
                  WHERE sku = ?
                    AND (deauthorized_date IS NULL OR deauthorized_date > ?)
              )
        ),
        peer_perf AS (
            SELECT d.store_id,
                   COUNT(DISTINCT d.sku) AS n_similar,
                   AVG(sd.units_sold) AS avg_velocity
            FROM distribution_log d
            JOIN product_master pm ON d.sku = pm.sku
            JOIN scan_data sd ON sd.sku = d.sku AND sd.store_id = d.store_id
            WHERE pm.product_line = (SELECT product_line FROM focus)
              AND d.sku != ?
              AND (d.deauthorized_date IS NULL OR d.deauthorized_date > ?)
              AND julianday(?) - julianday(sd.week_ending) < 56
            GROUP BY d.store_id
        )
        SELECT ts.store_id, ts.retailer, ts.region, ts.state, ts.volume_tier,
               p.n_similar, p.avg_velocity
        FROM target_stores ts
        JOIN peer_perf p ON ts.store_id = p.store_id
        ORDER BY p.avg_velocity DESC
    """
    params = [focus_sku] + ret_params + [focus_sku, latest, focus_sku, latest, latest]
    df = pd.read_sql(sql, con, params=params)
    if df.empty:
        return df

    df["tier_mult"] = df["volume_tier"].map(VOLUME_TIER_MULT).fillna(1.0)
    df["score"] = (df["avg_velocity"] * df["tier_mult"]).round(2)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    return df


def render_expansion_targeting(focus_sku: str, retailer: str | None) -> None:
    con = get_connection()
    sku_meta = con.execute(
        "SELECT product_name, product_line FROM product_master WHERE sku = ?",
        (focus_sku,),
    ).fetchone()
    if not sku_meta:
        st.warning("Selected SKU not found.")
        return
    product_name, product_line = sku_meta

    ret_label = retailer if retailer and retailer != "All Retailers" else "all retailers"
    st.caption(
        f"Focus SKU: **{focus_sku} — {product_name}**  |  "
        f"Product line: **{product_line}**  |  Retailer scope: **{ret_label}**"
    )

    df = get_expansion_data(focus_sku, retailer)
    if df.empty:
        st.warning(
            "No expansion opportunities found — either this SKU is already in every "
            "candidate store, or no peer SKUs in the same product line have recent activity."
        )
        return

    n_opps = len(df)
    st.markdown(
        f"### {n_opps} stores carry other {product_line} but not "
        f"**{product_name}** yet — here are the strongest fits."
    )

    top_score = df["score"].iloc[0]
    avg_score = df["score"].mean()
    c1, c2, c3 = st.columns(3)
    c1.metric("Top opportunity score", f"{top_score:.2f}")
    c2.metric("Average score", f"{avg_score:.2f}")

    # Third card adapts to whether the user has filtered to a single retailer.
    # All Retailers: surface which retailer leads on average score (otherwise
    # the card just echoes the selected filter back at the user).
    # One retailer:  surface the top store, or — when several stores tie for
    # the lead — the count plus the shared score.
    is_all_retailers = (retailer is None) or (retailer == "All Retailers")
    if is_all_retailers:
        retailer_avg = (
            df.groupby("retailer")["score"].mean().sort_values(ascending=False)
        )
        c3.metric("Strongest retailer", retailer_avg.index[0])
    else:
        # Tie detection — how many stores share the top score?
        # `top_score` is already rounded to 2 decimals on the underlying df,
        # so equality is reliable here without an extra epsilon check.
        tied = df[df["score"] == top_score]
        n_tied = len(tied)
        if n_tied == 1:
            c3.metric("Top store", tied["store_id"].iloc[0])
        else:
            c3.metric(
                "Top stores (tied)",
                f"{n_tied} stores at {top_score:.2f}",
            )

    # Tier boundaries derived from the SCORE RANGE across all qualifying
    # stores — not from row position. Two stores with the same score must
    # always land in the same tier and render the same color, regardless of
    # whether they sit at row 5 or row 14 in the displayed slice.
    score_min = float(df["score"].min())
    score_max = float(df["score"].max())
    score_span = max(score_max - score_min, 1e-9)  # guard divide-by-zero
    solid_floor = score_min + score_span / 3.0          # below this → Worth considering
    strongest_floor = score_min + 2.0 * score_span / 3.0  # ≥ this → Strongest

    def _tier_for_score(s: float) -> str:
        # Inclusive floors: anyone at or above strongest_floor is Strongest.
        # Identical scores → identical tier, by construction.
        if s >= strongest_floor:
            return "Strongest"
        if s >= solid_floor:
            return "Solid"
        return "Worth considering"

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

    # Bucket by retailer category so the count line proves to the CEO that the
    # 30 rows on screen are spread across retailers as expected (or aren't).
    def _ret_cat(r: str) -> str:
        if r in ("Walmart", "Costco", "Whole Foods"):
            return r
        return "Regional"
    cat_counts = show["retailer"].map(_ret_cat).value_counts()
    bucket_parts = [(int(cat_counts.get(c, 0)), c) for c in
                    ("Walmart", "Costco", "Whole Foods", "Regional")
                    if cat_counts.get(c, 0) > 0]

    render_status_legend(
        "<b>Score</b> = average velocity of peer SKUs (same product line, "
        "already on shelf at that store) × volume-tier multiplier "
        "(A = 1.3, B = 1.0, C = 0.7).  Higher score = stronger expansion fit. "
        "Showing top 30 of all qualifying stores."
    )
    render_row_count_line("stores", bucket_parts)

    EXPANSION_TIER_COLORS = {
        "Strongest":          TEAL,
        "Solid":              NAVY_MED,
        "Worth considering":  GREY,
    }
    def _style_strength_col(col: pd.Series) -> list[str]:
        return [
            f"color: {EXPANSION_TIER_COLORS.get(v, NAVY)}; font-weight: 700"
            for v in col
        ]
    styled_expansion = display_df.style.apply(
        _style_strength_col, subset=["Strength"]
    ).format({
        "Their Avg Velocity": "{:.2f}",
        "Expansion Score":    "{:.2f}",
    }, na_rep="—")
    st.dataframe(styled_expansion, use_container_width=True, hide_index=True, height=460)

    # Top 15 bar chart — same value-based tier function as the table, so a
    # store at score 29.0 paints the same color in the table and in the chart,
    # never depending on row position.
    n_show = min(15, len(df))
    top = df.head(n_show).copy().reset_index(drop=True)
    top["label"] = top["store_id"] + "  ·  " + top["retailer"]
    top["tier"] = top["score"].apply(_tier_for_score)

    st.markdown(f"#### Top {n_show} stores ranked by expansion score")
    st.caption("Score = peer-SKU avg velocity at that store × volume-tier multiplier (A=1.3, B=1.0, C=0.7).")
    render_chart_legend([
        (TEAL,     f"Strongest (score ≥ {strongest_floor:.2f})"),
        (NAVY_MED, f"Solid ({solid_floor:.2f}–{strongest_floor:.2f})"),
        (GREY,     f"Worth considering (< {solid_floor:.2f})"),
    ])

    fig = go.Figure()
    for tier_name in ("Strongest", "Solid", "Worth considering"):
        sub = top[top["tier"] == tier_name]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["label"], x=sub["score"], orientation="h",
            marker_color=EXPANSION_TIER_COLORS[tier_name],
            text=sub["score"].map(lambda v: f"{v:.2f}"),
            textposition="outside", textfont=dict(size=14, color=NAVY),
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
        label_pad_px=240,
        left_margin=260,
    )
    # Restore original (score-descending) order on y-axis
    # `top` is sorted score-descending, so passing the labels as-is to
    # categoryarray (no [::-1]) lines up with autorange="reversed" to put
    # the highest-score store at the TOP of the chart.
    fig.update_yaxes(categoryorder="array", categoryarray=top["label"].tolist())
    st.plotly_chart(fig, use_container_width=True)

    safe_sku = focus_sku.lower()
    safe_ret = (retailer or "all").lower().replace(" ", "_")
    excel_button(display_df, "Expansion Targets", f"expansion_{safe_sku}_{safe_ret}")


# ============================================================
# DECISION 5 — DISTRIBUTION PRUNING
# ============================================================

@st.cache_data(show_spinner="Loading pruning data...")
def get_pruning_pairs(retailer: str, product_line: str | None) -> pd.DataFrame:
    """Per (sku, store) currently authorized at retailer: 13-week avg velocity."""
    con = get_connection()
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()

    pl_clause = "AND pm.product_line = ?" if product_line else ""
    pl_params = [product_line] if product_line else []

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id, s.retailer, s.region, s.state, s.volume_tier
            FROM stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = 0
        ),
        active AS (
            SELECT d.sku, d.store_id
            FROM distribution_log d
            WHERE d.store_id IN (SELECT store_id FROM ret_stores)
              AND (d.deauthorized_date IS NULL OR d.deauthorized_date > ?)
        )
        SELECT
            a.sku, a.store_id,
            rs.retailer, rs.region, rs.state, rs.volume_tier,
            pm.product_name, pm.product_line,
            sc.wholesale_price,
            AVG(sd.units_sold) AS velocity
        FROM active a
        JOIN ret_stores rs ON a.store_id = rs.store_id
        JOIN product_master pm ON a.sku = pm.sku
        JOIN sku_costs sc ON a.sku = sc.sku
        LEFT JOIN scan_data sd ON sd.sku = a.sku AND sd.store_id = a.store_id
                              AND julianday(?) - julianday(sd.week_ending) < 91
        WHERE 1=1 {pl_clause}
        GROUP BY a.sku, a.store_id
    """
    params = ret_params + [latest, latest] + pl_params
    df = pd.read_sql(sql, con, params=params)
    return df.dropna(subset=["velocity"]).reset_index(drop=True)


def render_distribution_pruning(retailer: str, product_line: str | None, threshold: float) -> None:
    latest = get_latest_week()

    st.caption(
        f"Retailer: **{retailer}**  |  Delisting threshold: "
        f"**{threshold:.2f} units/store/week**  |  Window: last 13 weeks  "
        f"|  Most recent week: **{latest}**"
    )

    pairs = get_pruning_pairs(retailer, product_line)
    if pairs.empty:
        st.warning(
            f"No active SKU x store combinations at {retailer}"
            + (f" in {product_line}" if product_line else "") + "."
        )
        return

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

    if n_below > 0:
        # Headline cross-reference: list affected stores inline when there are
        # ≤10 (the CEO can verify at a glance), otherwise show the count and
        # point at the tab where each one is enumerated.
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
        st.markdown(
            f"### {n_below:,} of {n_pairs:,} SKU × store combinations at "
            f"{retailer} are below the delisting threshold of {threshold:.2f} "
            f"units/store/week — concentrated in {n_skus_affected} "
            f"SKU{'s' if n_skus_affected != 1 else ''}.  {stores_phrase}."
        )
    else:
        st.markdown(
            f"### Every active SKU x store combination at {retailer} is at or above "
            f"the {threshold:.2f} threshold."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active pairs", f"{n_pairs:,}")
    c2.metric("Below threshold", f"{n_below:,}")
    c3.metric("SKUs affected", f"{n_skus_affected} / {n_skus}")
    c4.metric("Stores affected", f"{n_stores_affected} / {n_stores}")

    tab_sku, tab_store = st.tabs(["By SKU", "By Store"])

    # ---------- BY SKU ----------
    with tab_sku:
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
            st.info("No SKUs have any stores below threshold — nothing to prune here.")
        else:
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
            render_status_legend(
                f"<b>Severity</b> = % of this SKU's stores below the "
                f"{threshold:.2f} threshold.  "
                f"<b style='color:{RED}'>Critical</b> ≥ {crit_pct:.2f}%.  "
                f"<b style='color:{ORANGE}'>Concerning</b> = "
                f"{conc_pct:.2f}% to &lt; {crit_pct:.2f}%.  "
                f"<b style='color:{NAVY_MED}'>Mild</b> &lt; {conc_pct:.2f}%."
            )
            render_row_count_line("SKUs", [
                (n_crit, "Critical"),
                (n_conc, "Concerning"),
                (n_mild, "Mild"),
            ])

            styled = display_sku.style.apply(
                make_row_styler(PRUNING_ROW, status_col="Severity"), axis=1
            ).format({
                "% Below Threshold": "{:.2f}%",
                "Avg Velocity":      "{:.2f}",
            }, na_rep="—")
            st.dataframe(styled, use_container_width=True, hide_index=True, height=420)

            n_show = min(15, len(by_sku))
            top = by_sku.head(n_show).copy()
            st.markdown(
                f"#### These {n_show} SKUs have the highest share of "
                f"underperforming stores at {retailer}"
            )
            st.caption(
                f"Bars show what % of each SKU's stores fall below the "
                f"delisting threshold. Red ≥{crit_pct:.2f}%, orange "
                f"{conc_pct:.2f}–{crit_pct:.2f}%, navy <{conc_pct:.2f}%."
            )
            render_chart_legend([
                (RED,      f"Critical (≥{crit_pct:.2f}% of stores below threshold)"),
                (ORANGE,   f"Concerning ({conc_pct:.2f}% to <{crit_pct:.2f}%)"),
                (NAVY_MED, f"Mild (<{conc_pct:.2f}%)"),
            ])

            fig = go.Figure()
            for sev in ("Critical", "Concerning", "Mild"):
                sub = top[top["Severity"] == sev]
                if sub.empty:
                    continue
                fig.add_trace(go.Bar(
                    y=sub["sku"] + "  ·  " + sub["product_name"].str.slice(0, 28),
                    x=sub["pct_below"], orientation="h",
                    marker_color=PRUNING_SEVERITY_COLORS[sev],
                    text=sub["pct_below"].map(lambda v: f"{v:.2f}%"),
                    textposition="outside", textfont=dict(size=14, color=NAVY),
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
            apply_hbar_layout(
                fig,
                labels=(top["sku"] + "  ·  " + top["product_name"].str.slice(0, 28)).tolist(),
                height=max(420, 34 * n_show + 120),
                x_title="% of stores below delisting threshold",
                label_pad_px=320,
                left_margin=340,
            )
            st.plotly_chart(fig, use_container_width=True)

            # ---- Drill-in: which specific stores are dragging this SKU? ----
            # The summary headline names a count of stores; the By SKU table
            # also shows just a count. To verify either, the CEO would have
            # to switch to the By Store tab and filter mentally. This drill-in
            # answers "for this one SKU, which stores fail?" right here.
            st.markdown("##### Drill into a SKU to see which stores are underperforming")
            sku_options = display_sku["SKU"].tolist()
            drill_label_map = {
                row["SKU"]: f"{row['SKU']} — {row['Product Name']}  "
                            f"({int(row['# Stores Below Threshold'])} of "
                            f"{int(row['# Total Stores'])} stores below)"
                for _, row in display_sku.iterrows()
            }
            selected_sku = st.selectbox(
                "Pick a SKU:",
                options=sku_options,
                index=0,
                format_func=lambda s: drill_label_map.get(s, s),
                key=f"pruning_drill_{retailer}_{product_line or 'all'}",
            )
            detail = pairs[
                (pairs["sku"] == selected_sku) & pairs["below_threshold"]
            ].copy()
            if detail.empty:
                st.info(
                    f"{selected_sku} has no stores below the {threshold:.2f} "
                    f"threshold at {retailer}."
                )
            else:
                # Gap = how far below threshold (positive number = bigger problem).
                detail["gap"] = (threshold - detail["velocity"]).round(2)
                detail = detail.sort_values("gap", ascending=False).reset_index(drop=True)
                detail_display = pd.DataFrame({
                    "Store ID":          detail["store_id"],
                    "Retailer":          detail["retailer"],
                    "Region":            detail["region"],
                    "State":             detail["state"],
                    "Volume Tier":       detail["volume_tier"],
                    "Velocity at Store": detail["velocity"].round(2),
                    "Threshold":         threshold,
                    "Gap (below)":       detail["gap"],
                })
                detail_styled = detail_display.style.format({
                    "Velocity at Store": "{:.2f}",
                    "Threshold":         "{:.2f}",
                    "Gap (below)":       "{:.2f}",
                }, na_rep="—").apply(
                    lambda _: [
                        f"background-color: {RED_FAINT}; color: {RED}"
                    ] * len(detail_display.columns),
                    axis=1,
                )
                st.caption(
                    f"{len(detail_display)} stores carry **{selected_sku}** "
                    f"at velocity below {threshold:.2f}. Sorted by gap, "
                    f"worst first."
                )
                st.dataframe(
                    detail_styled,
                    use_container_width=True, hide_index=True,
                    height=min(420, 44 + 35 * len(detail_display)),
                )

            safe_ret = retailer.lower().replace(" ", "_")
            safe_pl = (product_line or "all").lower().replace(" ", "_")
            excel_button(display_sku, "Pruning by SKU", f"pruning_by_sku_{safe_ret}_{safe_pl}")

    # ---------- BY STORE ----------
    with tab_store:
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

        # Severity by skus_below count, cutoffs from THRESHOLDS
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
        render_status_legend(
            f"<b>Severity</b> = number of SKUs at this store below the "
            f"{threshold:.2f} threshold.  "
            f"<b style='color:{RED}'>Critical</b> ≥ {store_crit} SKUs.  "
            f"<b style='color:{ORANGE}'>Concerning</b> = "
            f"{store_conc}–{store_crit - 1} SKUs.  "
            f"<b style='color:{NAVY_MED}'>Mild</b> = 0 SKUs below threshold."
        )
        render_row_count_line("stores", [
            (n_crit, "Critical"),
            (n_conc, "Concerning"),
            (n_mild, "Mild"),
        ])

        styled = display_store.style.apply(
            make_row_styler(PRUNING_ROW, status_col="Severity"), axis=1
        ).format({"Avg Velocity": "{:.2f}"}, na_rep="—")
        st.dataframe(styled, use_container_width=True, hide_index=True, height=460)

        safe_ret = retailer.lower().replace(" ", "_")
        safe_pl = (product_line or "all").lower().replace(" ", "_")
        excel_button(display_store, "Pruning by Store", f"pruning_by_store_{safe_ret}_{safe_pl}")


# ============================================================
# DECISION 6 — SKU RATIONALIZATION
# ============================================================

@st.cache_data(show_spinner="Loading SKU rationalization data...")
def get_rationalization_data(retailer: str, product_line: str | None) -> pd.DataFrame:
    """Per-SKU 13-week velocity, margin, and door count at the chosen retailer."""
    con = get_connection()
    ret_sql, ret_params = retailer_clause(retailer)
    latest = get_latest_week()

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = 0
        )
        SELECT pm.sku, pm.product_name, pm.product_line,
               sc.wholesale_price, sc.cogs_per_unit,
               AVG(sd.units_sold) AS velocity,
               COUNT(DISTINCT sd.store_id) AS doors
        FROM scan_data sd
        JOIN ret_stores rs ON sd.store_id = rs.store_id
        JOIN product_master pm ON sd.sku = pm.sku
        JOIN sku_costs sc ON sd.sku = sc.sku
        WHERE julianday(?) - julianday(sd.week_ending) < 91
        GROUP BY pm.sku, pm.product_name, pm.product_line,
                 sc.wholesale_price, sc.cogs_per_unit
    """
    df = pd.read_sql(sql, con, params=ret_params + [latest])
    if product_line:
        df = df[df["product_line"] == product_line]
    df = df.dropna(subset=["velocity"]).reset_index(drop=True)
    if df.empty:
        return df

    df["margin_per_unit"] = (df["wholesale_price"] - df["cogs_per_unit"]).round(2)
    df["margin_per_sw"] = (df["velocity"] * df["margin_per_unit"]).round(2)
    df["revenue_per_sw"] = (df["velocity"] * df["wholesale_price"]).round(2)
    df["weekly_total_margin"] = (df["margin_per_sw"] * df["doors"]).round(0)
    return df


def render_sku_rationalization(retailer: str, product_line: str | None) -> None:
    threshold = RETAILER_THRESHOLDS.get(retailer, 1.0)  # Walmart=2.0 used for "All Retailers" baseline
    if retailer == "All Retailers":
        threshold = 2.0
    latest = get_latest_week()

    st.caption(
        f"Retailer scope: **{retailer}**  |  Window: last 13 weeks  "
        f"|  Velocity threshold for at-risk: **{threshold:.2f} units/store/week**  "
        f"|  Most recent week: **{latest}**"
    )

    df = get_rationalization_data(retailer, product_line)
    if df.empty:
        st.warning(
            f"No SKUs with recent activity at {retailer}"
            + (f" in {product_line}" if product_line else "") + "."
        )
        return

    median_velocity = df["velocity"].median()
    median_margin = df["margin_per_sw"].median()

    df["high_velocity"] = df["velocity"] > median_velocity
    df["high_margin"] = df["margin_per_sw"] > median_margin

    n_winners = int(((df["high_velocity"]) & (df["high_margin"])).sum())
    n_volume = int(((df["high_velocity"]) & (~df["high_margin"])).sum())
    n_niche = int(((~df["high_velocity"]) & (df["high_margin"])).sum())
    n_cut = int(((~df["high_velocity"]) & (~df["high_margin"])).sum())

    n_below_thresh = int((df["velocity"] < threshold).sum())
    bottom_q = df["weekly_total_margin"].quantile(0.20)
    n_low_margin = int((df["weekly_total_margin"] <= bottom_q).sum())
    cut_candidates = df[(df["velocity"] < threshold) & (df["weekly_total_margin"] <= bottom_q)]
    n_cut_candidates = len(cut_candidates)

    if n_cut_candidates > 0:
        st.markdown(
            f"### {n_low_margin} SKUs generate the bottom 20% of weekly gross margin "
            f"(≤ ${bottom_q:,.0f}/wk). {n_cut_candidates} of those are also below the "
            f"{threshold:.2f} velocity threshold — these are clear discontinuation candidates."
        )
    else:
        st.markdown(
            f"### {n_low_margin} SKUs sit in the bottom 20% by weekly gross margin, "
            f"but none are also below the velocity threshold — pruning here would lose volume."
        )

    # 2x2 quadrant cards
    st.markdown("#### Velocity vs. margin: where does each SKU sit?")
    st.caption(
        f"Median velocity = {median_velocity:.2f}. Median margin per store-week = "
        f"${median_margin:.2f}. Each SKU lands in one quadrant."
    )
    q1, q2, q3, q4 = st.columns(4)
    quadrant_card(q1, "Winners",
                  "High velocity, high margin",
                  n_winners, TEAL, GREEN_FAINT)
    # Volume plays = high velocity, low margin: a neutral business call
    # (do you keep volume or push margin?). Navy reads as "informational".
    quadrant_card(q2, "Volume plays",
                  "High velocity, low margin",
                  n_volume, NAVY_MED, GREY_BG)
    # Niche / slow = low velocity, high margin: caution signal — they earn
    # money per unit but aren't moving. Orange = watch.
    quadrant_card(q3, "Niche / slow movers",
                  "Low velocity, high margin",
                  n_niche, ORANGE, ORANGE_FAINT)
    quadrant_card(q4, "Cut candidates",
                  "Low velocity, low margin",
                  n_cut, RED, RED_FAINT)

    # Table
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
    # Sort: Cut candidates first (kill zone — what the CEO needs to act on),
    # then Niche / slow, Volume plays, Winners. Within each quadrant, worst
    # weekly margin first so the most-suspicious SKUs surface at the top.
    quadrant_order = {"Cut candidate": 0, "Niche / slow": 1, "Volume play": 2, "Winner": 3}
    display_df = (
        display_df.assign(_q=display_df["Quadrant"].map(quadrant_order))
        .sort_values(["_q", "Total Weekly Margin"], ascending=[True, True])
        .drop(columns="_q").reset_index(drop=True)
    )

    QUADRANT_COLORS = {
        "Winner":        TEAL,
        "Volume play":   NAVY_MED,
        "Niche / slow":  ORANGE,
        "Cut candidate": RED,
    }
    # One color scheme for the whole view: row tint matches the Quadrant
    # column matches the summary cards matches the bottom-15 chart. A SKU
    # tinted red in a row reads as a Cut candidate everywhere on screen.
    QUADRANT_ROW_BG = {
        "Winner":        GREEN_FAINT,
        "Volume play":   GREY_BG,
        "Niche / slow":  ORANGE_FAINT,
        "Cut candidate": RED_FAINT,
    }

    def style_row(row: pd.Series) -> list[str]:
        bg = QUADRANT_ROW_BG.get(row["Quadrant"], WHITE)
        fg = QUADRANT_COLORS.get(row["Quadrant"], NAVY)
        return [f"background-color: {bg}; color: {fg}"] * len(row)

    def style_quadrant_col(col: pd.Series) -> list[str]:
        return [
            f"color: {QUADRANT_COLORS.get(v, NAVY)}; font-weight: 700"
            for v in col
        ]

    # ============================================================
    # Tabs: "Cut candidates" (clean action list) + "Portfolio overview"
    # (full velocity × margin matrix). Quadrant cards above stay visible
    # so the CEO has the topline before picking a tab.
    # ============================================================
    tab_cut, tab_portfolio = st.tabs(["Cut candidates", "Portfolio overview"])

    # ---------------- TAB 1: CUT CANDIDATES ----------------
    with tab_cut:
        cut_df = display_df[display_df["Quadrant"] == "Cut candidate"].copy()
        # Sort DESCENDING by total weekly margin so the SKU you'd lose the
        # MOST dollars by cutting is at the top of both the chart and the
        # table. That's the row the CEO should think hardest about before
        # delisting; the smallest contributors are obvious cuts and sink to
        # the bottom of the screen.
        cut_df = cut_df.sort_values(
            "Total Weekly Margin", ascending=False
        ).reset_index(drop=True)

        if cut_df.empty:
            st.info(
                "No SKUs landed in the Cut-candidate quadrant — every SKU is "
                "above at least one of the two medians. Switch to **Portfolio "
                "overview** to see the full matrix."
            )
        else:
            total_cut_margin = int(cut_df["Total Weekly Margin"].sum())
            st.markdown(
                f"### These SKUs have low velocity AND low margin — cut first"
            )
            st.markdown(
                f"<div style='color: {GREY}; font-size: 0.92em; "
                f"margin: -0.4em 0 0.6em 0;'>"
                f"<b>{len(cut_df)} SKUs are cut candidates</b>, generating a "
                f"combined <b>${total_cut_margin:,.2f}/wk</b> in gross margin "
                f"— the same dollars you'd recapture if you delisted them and "
                f"redirected the shelf to a Winner. Below both the median "
                f"velocity ({median_velocity:.2f}) and the median margin per "
                f"store-week (${median_margin:.2f})."
                f"</div>",
                unsafe_allow_html=True,
            )

            # --- Cut-candidate chart: all bars red, largest margin at TOP
            # so the SKU with the biggest dollars at risk reads first ---
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
            # cut_chart is sorted margin-descending, so passing labels as-is
            # plus autorange="reversed" (set in base layout) puts the LARGEST
            # margin at the TOP — the SKU you'd lose the most by cutting.
            fig_cut.update_yaxes(categoryorder="array", categoryarray=cut_labels)
            st.plotly_chart(fig_cut, use_container_width=True)

            # --- Cut-candidate table: all rows red-tinted ---
            cut_display = cut_df.drop(columns=["Quadrant"])
            cut_styled = cut_display.style.apply(
                lambda _: [
                    f"background-color: {RED_FAINT}; color: {RED}"
                ] * len(cut_display.columns),
                axis=1,
            ).format({
                "Velocity":            "{:.2f}",
                "Margin/Unit":         "${:.2f}",
                "Margin/Store/Week":   "${:.2f}",
                "Total Weekly Margin": "${:,.2f}",
            }, na_rep="—")
            st.dataframe(
                cut_styled, use_container_width=True, hide_index=True, height=460
            )

    # ---------------- TAB 2: PORTFOLIO OVERVIEW ----------------
    with tab_portfolio:
        render_status_legend(
            f"<b>Quadrant cutoffs:</b> Median velocity = "
            f"<b>{median_velocity:.2f}</b> units/store/week.  "
            f"Median margin per store-week = <b>${median_margin:.2f}</b>.  "
            f"<b style='color:{TEAL}'>Winner</b> = above both medians.  "
            f"<b style='color:{NAVY_MED}'>Volume play</b> = high velocity, low "
            f"margin.  "
            f"<b style='color:{ORANGE}'>Niche / slow</b> = low velocity, high "
            f"margin.  "
            f"<b style='color:{RED}'>Cut candidate</b> = below both medians."
        )
        render_row_count_line("SKUs", [
            (n_winners, "Winners"),
            (n_volume, "Volume plays"),
            (n_niche, "Niche / slow"),
            (n_cut, "Cut candidates"),
        ])

        styled = (
            display_df.style
            .apply(style_row, axis=1)
            .apply(style_quadrant_col, subset=["Quadrant"])
            .format({
                "Velocity":            "{:.2f}",
                "Margin/Unit":         "${:.2f}",
                "Margin/Store/Week":   "${:.2f}",
                "Total Weekly Margin": "${:,.2f}",
            }, na_rep="—")
        )
        st.dataframe(styled, use_container_width=True, hide_index=True, height=460)

        # Bottom 15 by total weekly margin, colored by quadrant — but Winners
        # and Volume plays get re-bucketed as "Low distribution" (navy)
        # because they only landed here because of door count, not poor
        # per-store performance.
        # Within the bottom-15 slice, sort DESCENDING so the largest margin
        # contributor sits at the TOP — same "biggest dollars at risk first"
        # rule used on the Cut-candidates tab.
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

        st.markdown(f"#### Bottom {n_show} SKUs by weekly margin — should they stay or go?")
        st.markdown(
            f"<div style='color: {GREY}; font-size: 0.92em; "
            f"margin: -0.4em 0 0.4em 0;'>"
            f"Low total margin doesn't always mean cut.  "
            f"<span style='color:{NAVY_MED}; font-weight:600'>Low distribution</span> "
            f"(navy) = strong per-store performance but too few doors to generate "
            f"meaningful total margin — consider expanding distribution rather "
            f"than cutting.  "
            f"<span style='color:{ORANGE}; font-weight:600'>Niche / slow</span> "
            f"(orange) = low velocity but high margin per unit — selective "
            f"expansion may help.  "
            f"<span style='color:{RED}; font-weight:600'>Cut candidates</span> "
            f"(red) have low velocity AND low margin — kill first.  "
            f"Median velocity = {median_velocity:.2f} units/store/week, median "
            f"margin per store-week = ${median_margin:.2f}."
            f"</div>",
            unsafe_allow_html=True,
        )
        render_chart_legend([
            (NAVY_MED, "Low distribution (Winner / Volume play, too few doors)"),
            (ORANGE,   "Niche / slow (low velocity, high margin)"),
            (RED,      "Cut candidate (below both medians)"),
        ])

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
        st.plotly_chart(fig, use_container_width=True)

    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")
    excel_button(display_df, "SKU Rationalization", f"sku_rationalization_{safe_ret}_{safe_pl}")


def quadrant_card(col, title: str, subtitle: str, count: int, fg: str, bg: str) -> None:
    col.markdown(
        f"""
        <div style='background-color: {bg}; border: 1px solid {GREY_LIGHT};
                    border-radius: 6px; padding: 0.85rem 1rem;
                    box-shadow: 0 1px 2px rgba(27, 42, 74, 0.05);'>
            <div style='color: {fg}; font-size: 0.85rem; font-weight: 600;
                        text-transform: uppercase; letter-spacing: 0.04rem;'>
                {title}
            </div>
            <div style='color: {NAVY}; font-size: 2.3rem; font-weight: 700;
                        line-height: 1.05; margin-top: 0.2rem;'>{count}</div>
            <div style='color: {GREY}; font-size: 0.78rem; margin-top: 0.15rem;'>
                {subtitle}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# DECISION 7 — LAUNCH HEALTH
# ============================================================

@st.cache_data(show_spinner="Loading launch trajectories...")
def get_launch_data() -> pd.DataFrame:
    """One row per SKU launched in the last 52 weeks, with window averages."""
    con = get_connection()
    latest = get_latest_week()

    sql = """
        WITH launches AS (
            SELECT sku, MIN(authorized_date) AS launch_date
            FROM distribution_log
            GROUP BY sku
            HAVING MIN(authorized_date) >= DATE(?, '-364 days')
        ),
        phys_stores AS (
            SELECT store_id FROM stores WHERE is_aggregated_channel = 0
        )
        SELECT pm.sku, pm.product_name, pm.product_line, l.launch_date,
            AVG(CASE WHEN julianday(sd.week_ending) - julianday(l.launch_date) BETWEEN 0 AND 27
                     THEN sd.units_sold END) AS v_w14,
            AVG(CASE WHEN julianday(sd.week_ending) - julianday(l.launch_date) BETWEEN 28 AND 55
                     THEN sd.units_sold END) AS v_w58,
            AVG(CASE WHEN julianday(sd.week_ending) - julianday(l.launch_date) BETWEEN 56 AND 90
                     THEN sd.units_sold END) AS v_w913,
            AVG(CASE WHEN julianday(sd.week_ending) - julianday(l.launch_date) >= 91
                     THEN sd.units_sold END) AS v_w14plus,
            AVG(CASE WHEN julianday(?) - julianday(sd.week_ending) < 28
                     THEN sd.units_sold END) AS v_current
        FROM scan_data sd
        JOIN launches l ON sd.sku = l.sku
        JOIN phys_stores ps ON sd.store_id = ps.store_id
        JOIN product_master pm ON sd.sku = pm.sku
        GROUP BY pm.sku, pm.product_name, pm.product_line, l.launch_date
        ORDER BY l.launch_date DESC
    """
    df = pd.read_sql(sql, con, params=[latest, latest])
    if df.empty:
        return df

    latest_d = pd.to_datetime(latest)
    launch_d = pd.to_datetime(df["launch_date"])
    df["weeks_since_launch"] = ((latest_d - launch_d).dt.days // 7).astype(int)
    return df


@st.cache_data(show_spinner=False)
def get_launch_weekly(sku: str) -> pd.DataFrame:
    con = get_connection()
    sql = """
        WITH phys_stores AS (
            SELECT store_id FROM stores WHERE is_aggregated_channel = 0
        ),
        launch AS (
            SELECT MIN(authorized_date) AS launch_date
            FROM distribution_log WHERE sku = ?
        )
        SELECT sd.week_ending, AVG(sd.units_sold) AS velocity,
               (SELECT launch_date FROM launch) AS launch_date
        FROM scan_data sd
        JOIN phys_stores ps ON sd.store_id = ps.store_id
        WHERE sd.sku = ?
          AND sd.week_ending >= (SELECT launch_date FROM launch)
        GROUP BY sd.week_ending
        ORDER BY sd.week_ending
    """
    return pd.read_sql(sql, con, params=[sku, sku])


def classify_launch(row: pd.Series, threshold: float) -> str:
    on_track_retention = THRESHOLDS["launch_on_track"]   # ≥ this fraction of initial → still On Track
    failing_floor      = THRESHOLDS["launch_failing"]    # < this fraction of benchmark → Failing
    initial = row["v_w14"]
    current = row["v_current"]
    if pd.isna(current):
        return "Needs Attention"
    if pd.isna(initial):
        # Too early to compare — judge on current
        return "On Track" if current >= threshold else "Needs Attention"
    if current >= threshold:
        return "Needs Attention" if current < initial * on_track_retention else "On Track"
    # Below threshold:
    if current < initial * on_track_retention:
        return "Failing"
    if current < threshold * failing_floor:
        return "Failing"
    return "Needs Attention"


def render_launch_health() -> None:
    threshold = 2.0   # Walmart benchmark used as a generic "did the launch land" signal
    latest = get_latest_week()

    st.caption(
        f"All SKUs whose first authorization was within the last 52 weeks  |  "
        f"Velocity benchmark: **{threshold:.2f} units/store/week** (Walmart standard)  |  "
        f"Most recent week: **{latest}**"
    )

    df = get_launch_data()
    if df.empty:
        st.info("No SKUs have launched in the last 52 weeks.")
        return

    df["status"] = df.apply(lambda r: classify_launch(r, threshold), axis=1)
    n_total = len(df)
    n_track = int((df["status"] == "On Track").sum())
    n_attn = int((df["status"] == "Needs Attention").sum())
    n_fail = int((df["status"] == "Failing").sum())

    if n_fail > 0:
        st.markdown(
            f"### {n_total} SKUs launched in the last 52 weeks. "
            f"{n_track} on track, {n_attn} need attention, {n_fail} failing."
        )
    else:
        st.markdown(
            f"### {n_total} SKUs launched in the last 52 weeks. "
            f"{n_track} on track, {n_attn} need attention, none currently failing."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Launched in last 52 wk", n_total)
    c2.metric("On Track", n_track)
    c3.metric("Needs Attention", n_attn)
    c4.metric("Failing", n_fail)

    on_track_pct = THRESHOLDS["launch_on_track"] * 100
    failing_pct = THRESHOLDS["launch_failing"] * 100
    render_status_legend(
        f"<b>Status definitions</b> (current vs first-4-weeks velocity, "
        f"benchmark = {threshold:.2f} units/store/week):  "
        f"<b style='color:{TEAL}'>On Track</b> = current ≥ benchmark and "
        f"holding ≥ {on_track_pct:.2f}% of initial.  "
        f"<b style='color:{ORANGE}'>Needs Attention</b> = above benchmark but "
        f"trending down, or modestly below benchmark.  "
        f"<b style='color:{RED}'>Failing</b> = current &lt; {failing_pct:.2f}% of "
        f"benchmark, or current &lt; {on_track_pct:.2f}% of initial AND below "
        f"benchmark."
    )
    render_row_count_line("launches", [
        (n_track, "On Track"),
        (n_attn, "Needs Attention"),
        (n_fail, "Failing"),
    ])

    display_df = pd.DataFrame({
        "SKU":             df["sku"],
        "Product Name":    df["product_name"],
        "Product Line":    df["product_line"],
        "Launch Date":     df["launch_date"],
        "Weeks Since":     df["weeks_since_launch"].astype(int),
        "Wks 1-4 Vel":     df["v_w14"].round(2),
        "Wks 5-8 Vel":     df["v_w58"].round(2),
        "Wks 9-13 Vel":    df["v_w913"].round(2),
        "Wks 14+ Vel":     df["v_w14plus"].round(2),
        "Current Vel":     df["v_current"].round(2),
        "Status":          df["status"],
    })
    status_order = {"Failing": 0, "Needs Attention": 1, "On Track": 2}
    display_df = (
        display_df.assign(_o=display_df["Status"].map(status_order))
        .sort_values(["_o", "Launch Date"], ascending=[True, False])
        .drop(columns="_o").reset_index(drop=True)
    )

    LAUNCH_ROW = {
        "Failing":         (RED_FAINT, RED),
        "Needs Attention": (ORANGE_FAINT, ORANGE),
        "On Track":        (GREEN_FAINT, TEAL),
    }
    styled = display_df.style.apply(make_row_styler(LAUNCH_ROW), axis=1).format({
        "Wks 1-4 Vel":  "{:.2f}",
        "Wks 5-8 Vel":  "{:.2f}",
        "Wks 9-13 Vel": "{:.2f}",
        "Wks 14+ Vel":  "{:.2f}",
        "Current Vel":  "{:.2f}",
    }, na_rep="—")
    st.dataframe(styled, use_container_width=True, hide_index=True, height=420)

    # Drill-in line chart per SKU
    st.markdown("#### Drill into one launch")
    df_d = display_df.copy()
    df_d["label"] = df_d["SKU"] + "  ·  " + df_d["Product Name"] + "  (" + df_d["Status"] + ")"
    selected_label = st.selectbox(
        "Pick a launched SKU to see weekly velocity since launch:",
        options=df_d["label"].tolist(), index=0,
    )
    selected = df_d[df_d["label"] == selected_label].iloc[0]
    weekly = get_launch_weekly(selected["SKU"])
    if weekly.empty:
        st.info("No weekly scan data found yet for this SKU.")
        return

    launch_d = pd.to_datetime(weekly["launch_date"].iloc[0])
    weekly["week_ending"] = pd.to_datetime(weekly["week_ending"])
    weekly["weeks_since"] = ((weekly["week_ending"] - launch_d).dt.days // 7) + 1

    sku = selected["SKU"]
    pname = selected["Product Name"]
    status = selected["Status"]
    color = {"Failing": RED, "Needs Attention": ORANGE, "On Track": TEAL}[status]
    st.markdown(
        f"**{sku} — {pname}** launched on **{launch_d.date()}**, "
        f"<span style='color:{color}; font-weight:600'>{status}</span>.",
        unsafe_allow_html=True,
    )
    on_track_pct = THRESHOLDS["launch_on_track"] * 100
    failing_floor = THRESHOLDS["launch_failing"]
    failing_drop_pct = (1 - THRESHOLDS["launch_on_track"]) * 100
    render_chart_legend([
        (TEAL,   f"On Track (≥{threshold:.2f}, holding ≥{on_track_pct:.2f}% of initial)"),
        (ORANGE, f"Needs Attention ({threshold * failing_floor:.2f}–{threshold:.2f}, or slipping)"),
        (RED,    f"Failing (<{threshold * failing_floor:.2f} or down ≥{failing_drop_pct:.2f}% from start)"),
    ])

    # Trend line painted in the SKU's status color so the CEO can read the
    # chart's verdict before reading any numbers. Benchmark stays grey so it
    # reads as a static "floor" and doesn't compete with the trend.
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

    # Window boundary lines: end of weeks 1-4, 5-8, 9-13
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
        paper_bgcolor=PAGE_BG, plot_bgcolor=WHITE,
        height=420,
        margin=dict(l=10, r=10, t=40, b=40),
        yaxis=dict(
            title="Units per store per week",
            title_font=dict(size=14, color=NAVY_MED),
            tickfont=dict(size=13, color=NAVY),
            gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT,
        ),
        xaxis=dict(
            tickfont=dict(size=13, color=NAVY),
            gridcolor=GREY_LIGHT, linecolor=GREY_LIGHT,
        ),
        showlegend=False,
        font=dict(family="sans-serif", size=14, color=NAVY),
    )
    st.plotly_chart(fig, use_container_width=True)

    excel_button(display_df, "Launch Health", "launch_health_all")


# ============================================================
# DECISION 8 — PRICING POWER
# ============================================================

@st.cache_data(show_spinner="Loading pricing-power data...")
def get_pricing_power_data(retailer: str, sku_filter: str | None,
                           product_line_filter: str | None) -> pd.DataFrame:
    """Per-SKU baseline / promo / post-promo velocity at one retailer."""
    con = get_connection()
    ret_sql, ret_params = retailer_clause(retailer)
    is_agg = 1 if retailer in ("UNFI", "DTC") else 0

    sku_clause = ""
    sku_params: list = []
    if sku_filter:
        sku_clause = "AND sd.sku = ?"
        sku_params = [sku_filter]

    sql = f"""
        WITH ret_stores AS (
            SELECT s.store_id FROM stores s
            WHERE {ret_sql} AND s.is_aggregated_channel = ?
        ),
        sku_promos AS (
            SELECT sku, start_week, end_week, discount_depth_pct
            FROM promotions WHERE retailer = ?
        ),
        promo_window AS (
            SELECT DISTINCT sp.sku, sd.week_ending
            FROM sku_promos sp
            JOIN scan_data sd ON sd.sku = sp.sku
            JOIN ret_stores rs ON sd.store_id = rs.store_id
            WHERE sd.week_ending BETWEEN sp.start_week AND sp.end_week
        ),
        post_window AS (
            SELECT DISTINCT sp.sku, sd.week_ending
            FROM sku_promos sp
            JOIN scan_data sd ON sd.sku = sp.sku
            JOIN ret_stores rs ON sd.store_id = rs.store_id
            WHERE sd.week_ending BETWEEN DATE(sp.end_week, '+7 days')
                                     AND DATE(sp.end_week, '+28 days')
        ),
        metrics AS (
            SELECT sd.sku,
                AVG(CASE WHEN EXISTS (SELECT 1 FROM promo_window pw
                                       WHERE pw.sku = sd.sku AND pw.week_ending = sd.week_ending)
                         THEN sd.units_sold END) AS promo_v,
                AVG(CASE WHEN EXISTS (SELECT 1 FROM post_window pow
                                       WHERE pow.sku = sd.sku AND pow.week_ending = sd.week_ending)
                         THEN sd.units_sold END) AS post_v,
                AVG(CASE WHEN NOT EXISTS (SELECT 1 FROM promo_window pw
                                           WHERE pw.sku = sd.sku AND pw.week_ending = sd.week_ending)
                          AND NOT EXISTS (SELECT 1 FROM post_window pow
                                           WHERE pow.sku = sd.sku AND pow.week_ending = sd.week_ending)
                         THEN sd.units_sold END) AS baseline_v
            FROM scan_data sd
            JOIN ret_stores rs ON sd.store_id = rs.store_id
            WHERE sd.sku IN (SELECT DISTINCT sku FROM sku_promos)
              {sku_clause}
            GROUP BY sd.sku
        ),
        discount_avg AS (
            SELECT sku, AVG(discount_depth_pct) AS avg_discount, COUNT(*) AS n_promos
            FROM sku_promos GROUP BY sku
        )
        SELECT pm.sku, pm.product_name, pm.product_line,
               m.baseline_v, m.promo_v, m.post_v,
               d.avg_discount, d.n_promos
        FROM metrics m
        JOIN product_master pm ON m.sku = pm.sku
        JOIN discount_avg d ON m.sku = d.sku
        ORDER BY pm.sku
    """
    df = pd.read_sql(sql, con, params=ret_params + [is_agg, retailer] + sku_params)
    if df.empty:
        return df
    if product_line_filter:
        df = df[df["product_line"] == product_line_filter].reset_index(drop=True)
    df = df.dropna(subset=["baseline_v", "promo_v"])
    df = df[df["baseline_v"] > 0].reset_index(drop=True)
    if df.empty:
        return df

    df["lift_pct"] = (df["promo_v"] - df["baseline_v"]) / df["baseline_v"]
    df["elasticity"] = df["lift_pct"] / df["avg_discount"].replace(0, pd.NA)
    df["recovery_ratio"] = df["post_v"] / df["baseline_v"]

    full_floor = THRESHOLDS["pricing_full_recovery"]
    slow_floor = THRESHOLDS["pricing_slow_recovery"]

    def recovery_label(r: float) -> str:
        if pd.isna(r):
            return "Slow Recovery"
        if r >= full_floor:
            return "Full Recovery"
        if r >= slow_floor:
            return "Partial Recovery"
        return "Slow Recovery"

    df["recovery_status"] = df["recovery_ratio"].apply(recovery_label)
    df = df.sort_values("elasticity", ascending=False).reset_index(drop=True)
    return df


def render_pricing_power(retailer: str, sku_filter: str | None,
                         product_line_filter: str | None) -> None:
    st.caption(
        f"Retailer: **{retailer}**"
        + (f"  |  SKU: **{sku_filter}**" if sku_filter else "")
        + (f"  |  Product line: **{product_line_filter}**" if product_line_filter else "")
        + "  |  Elasticity = (% velocity lift) ÷ (% discount depth). Higher = more price-sensitive."
    )

    df = get_pricing_power_data(retailer, sku_filter, product_line_filter)
    if df.empty:
        st.warning(
            f"No SKUs with valid baseline + promo data at {retailer}"
            + (f" / {sku_filter}" if sku_filter else "")
            + (f" / {product_line_filter}" if product_line_filter else "") + "."
        )
        return

    high_sensitivity = df[df["elasticity"] > 5.0]
    low_sensitivity = df[(df["elasticity"] >= 0) & (df["elasticity"] <= 1.5)]

    n_total = len(df)
    if len(high_sensitivity) > 0:
        st.markdown(
            f"### {len(high_sensitivity)} of {n_total} SKUs show high price sensitivity "
            f"(elasticity > 5) — these benefit most from promotions. "
            f"{len(low_sensitivity)} show low sensitivity and may have pricing power "
            f"to raise margins."
        )
    else:
        st.markdown(
            f"### Across {n_total} SKUs at {retailer}, "
            f"{len(low_sensitivity)} show low price sensitivity — discounts barely move "
            f"velocity, suggesting room to raise margins."
        )

    # One verdict per SKU, combining elasticity sign with recovery tier.
    # This is the SINGLE classification that drives the chart color, the
    # table tint, and the row count — no more separate "recovery status"
    # vs "elasticity status" parsing on the CEO's part.
    VERDICTS = {
        "Promote again":      TEAL,      # positive lift + Full recovery
        "Promote cautiously": ORANGE,    # positive lift + Partial recovery
        "Stop promoting":     RED,       # positive lift + Slow recovery
        "Promo backfired":    DARK_RED,  # negative elasticity, regardless of recovery
    }
    VERDICT_ROW_BG = {
        "Promote again":      GREEN_FAINT,
        "Promote cautiously": ORANGE_FAINT,
        "Stop promoting":     RED_FAINT,
        "Promo backfired":    DARK_RED_FAINT,
    }

    def _verdict(row: pd.Series) -> str:
        # Negative elasticity overrides recovery: a promo that REDUCED velocity
        # is broken regardless of how velocity rebounded post-promo.
        if pd.notna(row["elasticity"]) and row["elasticity"] < 0:
            return "Promo backfired"
        return {
            "Full Recovery":    "Promote again",
            "Partial Recovery": "Promote cautiously",
            "Slow Recovery":    "Stop promoting",
        }.get(row["recovery_status"], "Stop promoting")

    df["verdict"] = df.apply(_verdict, axis=1)

    avg_elast = df["elasticity"].mean()
    avg_disc = df["avg_discount"].mean() * 100
    n_promote_again = int((df["verdict"] == "Promote again").sum())
    n_cautious      = int((df["verdict"] == "Promote cautiously").sum())
    n_stop          = int((df["verdict"] == "Stop promoting").sum())
    n_backfired     = int((df["verdict"] == "Promo backfired").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg elasticity", f"{avg_elast:.2f}")
    c2.metric("Avg discount across promos", f"{avg_disc:.2f}%")
    c3.metric("Promote-again SKUs", n_promote_again)
    c4.metric("Backfired promos", n_backfired)

    full_pct = THRESHOLDS["pricing_full_recovery"] * 100
    slow_pct = THRESHOLDS["pricing_slow_recovery"] * 100
    render_status_legend(
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
    render_row_count_line("SKUs", [
        (n_promote_again, "Promote again"),
        (n_cautious,      "Promote cautiously"),
        (n_stop,          "Stop promoting"),
        (n_backfired,     "Promo backfired"),
    ])

    display_df = pd.DataFrame({
        "SKU":              df["sku"],
        "Product Name":     df["product_name"],
        "Product Line":     df["product_line"],
        "Baseline Vel":     df["baseline_v"].round(2),
        "Avg Promo Vel":    df["promo_v"].round(2),
        "Avg Discount %":   (df["avg_discount"] * 100).round(0),
        "# Promos":         df["n_promos"].astype(int),
        "Elasticity":       df["elasticity"].round(2),
        "Outcome":          df["verdict"],
    })

    # Row tint matches verdict color so a SKU labeled "Stop promoting" in the
    # Outcome column also has a red row background — same color story across
    # the table, the chart, and the summary cards.
    PRICING_ROW = {
        verdict: (VERDICT_ROW_BG[verdict], VERDICTS[verdict])
        for verdict in VERDICTS
    }
    styled = display_df.style.apply(
        make_row_styler(PRICING_ROW, status_col="Outcome"), axis=1
    ).format({
        "Baseline Vel":   "{:.2f}",
        "Avg Promo Vel":  "{:.2f}",
        "Avg Discount %": "{:.2f}%",
        "Elasticity":     "{:+.2f}",
    }, na_rep="—")
    st.dataframe(styled, use_container_width=True, hide_index=True, height=460)

    # ---------- Verdict chart ----------
    # One bar per SKU. Bar length = elasticity (how big a lift). Bar color =
    # the verdict (whether to repeat the promo). Bar text = just the verdict
    # name — no two-number composite to parse. Mix top responders and worst
    # responders so the screen always surfaces both ends of the distribution.
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
    chart_top["label"] = chart_top["sku"] + "  ·  " + chart_top["product_name"].str.slice(0, 26)
    chart_top["recovery_pct"] = chart_top["recovery_ratio"] * 100
    chart_top["avg_disc_pct"] = chart_top["avg_discount"] * 100
    chart_top["bar_color"] = chart_top["verdict"].map(VERDICTS)
    # Hatching on the backfired bars: a second visual cue beyond DARK_RED so
    # the "stop promoting" red and "backfired" dark-red can't blur together
    # under low-contrast displays or a color-blind viewer.
    chart_top["bar_pattern"] = [
        "/" if v == "Promo backfired" else "" for v in chart_top["verdict"]
    ]
    top_labels = chart_top["label"].tolist()

    st.markdown("#### Should you run this promotion again?")
    st.caption(
        "Bar length = how much velocity responds to discounts.  "
        "Color = whether the promotion is worth repeating."
    )
    render_chart_legend([
        (TEAL,     "Promote again (lift + full recovery)"),
        (ORANGE,   "Promote cautiously (lift + partial recovery)"),
        (RED,      "Stop promoting (lift + slow recovery)"),
        (DARK_RED, "Promo backfired (velocity dropped)"),
    ])

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
        # "auto" lets plotly put the verdict inside long bars (white text on
        # color) and outside short bars (navy text on white). The x-axis
        # padding added by apply_hbar_layout keeps outside labels on-canvas.
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
    # Reference line at 0 separates "promo helped" from "promo hurt".
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
    # `chart_top` is sorted elasticity-descending, so passing labels as-is
    # plus autorange="reversed" puts the highest-elasticity SKU at the TOP.
    fig.update_yaxes(categoryorder="array", categoryarray=top_labels)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(
        f"<div style='color: {GREY}; font-size: 12px; "
        f"margin: -0.5em 0 0.8em 0;'>"
        f"Negative elasticity can indicate failed promo execution (item not "
        f"properly set up at POS), poor price perception, or brand damage "
        f"from discounting.</div>",
        unsafe_allow_html=True,
    )

    safe_ret = retailer.lower().replace(" ", "_")
    safe_sku = (sku_filter or product_line_filter or "all").lower().replace(" ", "_")
    excel_button(display_df, "Pricing Power", f"pricing_power_{safe_ret}_{safe_sku}")


# ============================================================
# Placeholder + sidebar + main
# ============================================================

def render_placeholder(decision: str) -> None:
    title = DECISION_TITLES[decision]
    st.markdown(
        f"""
        <div style='padding: 3rem 1rem; text-align: center;
                    border: 1px dashed {GREY_LIGHT}; border-radius: 8px;
                    margin-top: 1.5rem; background-color: {GREY_BG};'>
            <div style='font-size: 1.1rem; color: {NAVY_MED};'>
                <strong>{title}</strong> isn't built yet.
            </div>
            <div style='font-size: 0.9rem; color: {GREY}; margin-top: 0.6rem;'>
                Pick a different decision in the sidebar to see a working analysis.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _on_decision_change() -> None:
    """Selectbox on_change handler — picking a decision exits Story view.

    Without this, switching from the Story to a decision via the dropdown
    would leave `show_story=True` and the user would still see the narrative.
    """
    st.session_state["show_story"] = False


def render_sidebar() -> dict:
    with st.sidebar:
        # Navy pill for the Story entry button. Targets the in-sidebar
        # primary button only, so the Section-5 jump buttons (rendered in the
        # main pane as default-style buttons) keep their neutral look.
        st.markdown(
            f"""
            <style>
              [data-testid="stSidebar"] [data-testid="stBaseButton-primary"],
              [data-testid="stSidebar"] button[kind="primary"] {{
                  background-color: {NAVY_MED} !important;
                  border-color: {NAVY_MED} !important;
                  color: {WHITE} !important;
                  font-weight: 600 !important;
                  text-align: left !important;
                  padding: 0.7rem 0.9rem !important;
                  line-height: 1.3 !important;
                  box-shadow: 0 2px 6px rgba(61, 90, 128, 0.22);
              }}
              [data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:hover,
              [data-testid="stSidebar"] button[kind="primary"]:hover {{
                  background-color: {NAVY} !important;
                  border-color: {NAVY} !important;
                  box-shadow: 0 3px 8px rgba(27, 42, 74, 0.32);
              }}
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div style='padding: 0.5rem 0 1rem 0;
                        border-bottom: 1px solid {GREY_LIGHT};
                        margin-bottom: 1rem;'>
                <div style='font-family: Georgia, "Times New Roman", serif;
                            font-size: 1.55rem; font-weight: 700;
                            letter-spacing: 0.04rem; color: {NAVY};'>
                    CINDERHAVEN
                </div>
                <div style='font-family: Georgia, "Times New Roman", serif;
                            font-size: 0.78rem; color: {NAVY_MED};
                            letter-spacing: 0.32rem; margin-top: -0.1rem;'>
                    P R O V I S I O N S
                </div>
                <div style='font-size: 0.72rem; color: {GREY}; margin-top: 0.6rem;'>
                    Velocity Tool
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Stable, explicit key on the decision picker itself so Streamlit
        # never tries to re-bind it to one of the per-mode widgets below.
        # The on_change handler exits Story view as soon as the user picks
        # a different decision.
        decision = st.selectbox(
            "What decision are you making?", DECISIONS, index=0,
            key="decision_picker",
            on_change=_on_decision_change,
        )
        st.markdown("**Filters**")
        state: dict = {"decision": decision}

        # Every per-mode widget gets a key prefixed with its decision-mode
        # short name. Without explicit keys, Streamlit auto-generates them
        # from (widget type + label + render order) — and modes that share a
        # label like "Retailer" or "Product Line" collide on switch, leaving
        # stale values cached. Explicit keys give each widget its own slot
        # in session_state.
        if decision == DECISIONS[0]:  # Shelf Defense
            state["retailer"] = st.selectbox(
                "Retailer", PHYSICAL_RETAILERS, index=0,
                key="shelf_retailer",
            )
            # Threshold key includes the retailer so the default value
            # refreshes when the retailer changes (each retailer has a
            # different RETAILER_THRESHOLDS default).
            state["threshold"] = st.number_input(
                "Delisting threshold (units/store/week)",
                min_value=0.0, step=0.1, format="%.1f",
                value=RETAILER_THRESHOLDS[state["retailer"]],
                key=f"shelf_threshold_{state['retailer']}",
            )
            st.caption(
                "Retailers don't publish this number. Set it based on your "
                "broker intelligence and category review history."
            )
            pl = st.selectbox(
                "Product Line", ["All"] + get_product_lines(), index=0,
                key="shelf_product_line",
            )
            state["product_line"] = None if pl == "All" else pl

        elif decision == DECISIONS[1]:  # Production Planning
            state["retailer"] = st.selectbox(
                "Retailer", ["All Retailers"] + PHYSICAL_RETAILERS, index=0,
                key="prod_retailer",
            )
            pl = st.selectbox(
                "Product Line", ["All"] + get_product_lines(), index=0,
                key="prod_product_line",
            )
            state["product_line"] = None if pl == "All" else pl

        elif decision == DECISIONS[2]:  # Promo ROI
            state["retailer"] = st.selectbox(
                "Retailer", ALL_PHYSICAL_OR_AGG, index=0,
                key="promo_retailer",
            )
            sku_options = ["All SKUs"] + get_promo_skus(state["retailer"])
            # SKU options depend on retailer; keying by retailer forces the
            # picker to reset to "All SKUs" when the retailer changes so
            # we never carry over a SKU that doesn't promote at the new one.
            sku_pick = st.selectbox(
                "SKU", sku_options, index=0,
                key=f"promo_sku_{state['retailer']}",
            )
            state["sku_filter"] = None if sku_pick == "All SKUs" else sku_pick

        elif decision == DECISIONS[3]:  # Distribution Expansion
            pl = st.selectbox(
                "Product Line", get_product_lines(), index=0,
                key="expansion_product_line",
            )
            sku_options = get_skus_for_line(pl)
            sku_labels = [f"{s} — {n}" for s, n in sku_options]
            # Focus SKU options depend on the chosen product line — same
            # reset-on-parent-change pattern as Promo ROI's SKU picker.
            label = st.selectbox(
                "Focus SKU", sku_labels, index=0,
                key=f"expansion_focus_sku_{pl}",
            )
            state["focus_sku"] = label.split(" — ", 1)[0] if label else None
            ret_pick = st.selectbox(
                "Retailer (optional)",
                ["All Retailers"] + PHYSICAL_RETAILERS, index=0,
                key="expansion_retailer",
            )
            state["retailer"] = None if ret_pick == "All Retailers" else ret_pick

        elif decision == DECISIONS[4]:  # Distribution Pruning
            state["retailer"] = st.selectbox(
                "Retailer", PHYSICAL_RETAILERS, index=0,
                key="pruning_retailer",
            )
            state["threshold"] = st.number_input(
                "Delisting threshold (units/store/week)",
                min_value=0.0, step=0.1, format="%.1f",
                value=RETAILER_THRESHOLDS[state["retailer"]],
                key=f"pruning_threshold_{state['retailer']}",
            )
            st.caption(
                "Retailers don't publish this number. Set it based on your "
                "broker intelligence and category review history."
            )
            pl = st.selectbox(
                "Product Line", ["All"] + get_product_lines(), index=0,
                key="pruning_product_line",
            )
            state["product_line"] = None if pl == "All" else pl

        elif decision == DECISIONS[5]:  # SKU Rationalization
            state["retailer"] = st.selectbox(
                "Retailer", ["All Retailers"] + PHYSICAL_RETAILERS, index=0,
                key="rat_retailer",
            )
            pl = st.selectbox(
                "Product Line", ["All"] + get_product_lines(), index=0,
                key="rat_product_line",
            )
            state["product_line"] = None if pl == "All" else pl

        elif decision == DECISIONS[6]:  # Launch Health
            st.caption("Auto-detects SKUs launched in the last 52 weeks. No filters needed.")

        elif decision == DECISIONS[7]:  # Pricing Power
            state["retailer"] = st.selectbox(
                "Retailer", ALL_PHYSICAL_OR_AGG, index=0,
                key="pricing_retailer",
            )
            scope = st.radio(
                "Narrow by", ["All SKUs", "Product line", "Specific SKU"], index=0,
                key="pricing_scope",
            )
            state["sku_filter"] = None
            state["product_line"] = None
            if scope == "Product line":
                pl = st.selectbox(
                    "Product Line", get_product_lines(), index=0,
                    key="pricing_product_line",
                )
                state["product_line"] = pl
            elif scope == "Specific SKU":
                sku_options = get_promo_skus(state["retailer"])
                if sku_options:
                    state["sku_filter"] = st.selectbox(
                        "SKU", sku_options, index=0,
                        key=f"pricing_sku_{state['retailer']}",
                    )
                else:
                    st.caption("This retailer has no promotions yet.")

        else:
            st.caption("Filters will populate once this decision is built out.")

        # Story entry — placed at the bottom of the sidebar so users see
        # the decision modes and filters first and discover the narrative
        # callout after exploring. The label hints at the reveal; the
        # caption underneath delivers the second-half punch without giving
        # away the full story.
        st.markdown(
            f"<div style='border-top: 1px solid {GREY_LIGHT}; "
            f"margin: 1.2rem 0 0.9rem 0;'></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-size: 0.68rem; color: {NAVY_MED}; "
            f"font-weight: 700; letter-spacing: 0.18rem; "
            f"text-transform: uppercase; margin: 0 0 0.35rem 0;'>"
            f"Read this first &middot; 2 min</div>",
            unsafe_allow_html=True,
        )
        if st.button(
            "The Charred Scallion Relish problem",
            key="story_entry_button",
            type="primary",
            use_container_width=True,
        ):
            st.session_state["show_story"] = True
            st.rerun()
        st.markdown(
            f"<div style='font-size: 0.78rem; color: {NAVY_MED}; "
            f"line-height: 1.4; margin: 0.4rem 0 0 0;'>"
            f"How a +15% growth SKU was actually losing money &mdash; "
            f"and what the Monday morning report couldn&rsquo;t see."
            f"</div>",
            unsafe_allow_html=True,
        )

    return state


def main() -> None:
    # First-time visitors land on the Story; once they pick a decision the
    # flag flips to False and stays False until they click the Story button
    # again.
    if "show_story" not in st.session_state:
        st.session_state["show_story"] = True

    state = render_sidebar()
    decision = state["decision"]

    # The Story renders its own headline and subhead inside render_story();
    # the standard "decision name" H1 is suppressed because the narrative
    # opens with its own framing copy.
    if st.session_state.get("show_story"):
        render_story()
        return

    st.markdown(
        f"<h1 style='color:{NAVY}; margin-bottom: 0.2rem;'>"
        f"{DECISION_TITLES[decision]}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='color:{NAVY_MED}; font-size: 1rem; margin-bottom: 1rem;'>"
        f"{decision}</div>",
        unsafe_allow_html=True,
    )

    if decision == DECISIONS[0]:
        render_shelf_defense(state["retailer"], state["product_line"], state["threshold"])
    elif decision == DECISIONS[1]:
        render_production_planning(state["retailer"], state["product_line"])
    elif decision == DECISIONS[2]:
        render_promo_roi(state["retailer"], state["sku_filter"])
    elif decision == DECISIONS[3]:
        render_expansion_targeting(state["focus_sku"], state["retailer"])
    elif decision == DECISIONS[4]:
        render_distribution_pruning(state["retailer"], state["product_line"], state["threshold"])
    elif decision == DECISIONS[5]:
        render_sku_rationalization(state["retailer"], state["product_line"])
    elif decision == DECISIONS[6]:
        render_launch_health()
    elif decision == DECISIONS[7]:
        render_pricing_power(
            state["retailer"], state["sku_filter"], state["product_line"]
        )
    else:
        render_placeholder(decision)


if __name__ == "__main__":
    main()
