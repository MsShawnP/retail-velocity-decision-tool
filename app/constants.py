"""Cinderhaven Velocity Tool — shared constants.

Extracted from velocity_tool.py lines 29-163. Every color, threshold,
retailer list, and status-color map lives here so both the legacy Streamlit
app and the new Dash app import from the same source of truth.

Color palette: Lailara Design System v2 — city-named color families.
"""

from __future__ import annotations

# ============================================================
# Lailara Design System v2 — color palette
# ============================================================

# Canvas
CANVAS       = "#f5f3ee"

# London greyscale
INK          = "#0d0d0d"   # London-5: chart titles, primary headings
NAVY         = "#0d0d0d"   # alias — legacy import compat (maps to London-5 ink)
TEXT         = "#333333"   # London-20: body text, secondary headings
NAVY_MED     = "#595959"   # alias — legacy import compat (maps to London-35)
TEXT_SEC     = "#595959"   # London-35: axis text, tick labels, chart subtitles
REFERENCE    = "#666666"   # London-40: reference lines (median, benchmark)
GREY         = "#666666"   # alias — legacy import compat (maps to London-40)
GREY_LIGHT   = "#d9d9d9"   # London-85: gridlines, hairline dividers
GREY_BG      = "#f2f2f2"   # London-95: alternating rows, soft surfaces
WHITE        = "#ffffff"
PAGE_BG      = "#f5f3ee"   # canvas — warm off-white replaces cold grey

# Brand red (Economist Red)
RED          = "#cc100a"   # Red-42: brand accent, critical status
DARK_RED     = "#7a0906"   # Red-18: emphasis, promo-backfired bars

# Accent — Chicago (blue)
CHICAGO      = "#1f2e7a"   # Chicago-20: primary button, chart anchor
CHICAGO_LT   = "#8e9ad0"   # Chicago-70: chart light pair

# Secondary — Hong Kong (teal)
TEAL         = "#158f75"   # HK-35: positive / safe / accent
HK_DARK      = "#0c6552"   # HK-20: chart dark pair
HK_LIGHT     = "#6dcdb5"   # HK-70: chart light pair

# Secondary — Tokyo (berry/rose)
TOKYO        = "#b82d4a"   # Tokyo-40: contrast data, alert-adjacent
TOKYO_DARK   = "#7e1f34"   # Tokyo-20: chart dark pair
TOKYO_LIGHT  = "#e68a9a"   # Tokyo-70: chart light pair

# Tertiary — Singapore (orange)
ORANGE       = "#ee8a2a"   # SG-55: warning, warm emphasis
SG_DARK      = "#7a3d10"   # SG-20: chart dark pair
SG_LIGHT     = "#f6b97c"   # SG-70: chart light pair

# Surface tints (step 95 — surface fills only, never data bars)
RED_FAINT    = "#fce8e7"   # Red-95
GREEN_FAINT  = "#e4f5f0"   # HK-95
ORANGE_FAINT = "#fdeee0"   # SG-95
DARK_RED_FAINT = "#fbe9ed" # Tokyo-95

# Benchmark reference
BENCHMARK_REF = "#666666"  # London-40, dashed 2px — replaces old blue

# Fonts
FONT_SERIF   = "'Playfair Display', Georgia, 'Times New Roman', serif"
FONT_SANS    = "'Source Sans 3', 'Source Sans Pro', 'Helvetica Neue', Helvetica, Arial, sans-serif"

# Categorical chart palette (paired: 5 families × 2 stops)
CHART_PALETTE = [
    "#1f2e7a",  # Chicago-20
    "#8e9ad0",  # Chicago-70
    "#0c6552",  # HK-20
    "#6dcdb5",  # HK-70
    "#7e1f34",  # Tokyo-20
    "#e68a9a",  # Tokyo-70
    "#7a3d10",  # SG-20
    "#f6b97c",  # SG-70
    "#8e0b07",  # Red-20
    "#ee8880",  # Red-70
]

# Trend line palette (distinct hues for multi-SKU line charts)
TREND_PALETTE = [
    "#1f2e7a",  # Chicago-20
    "#0c6552",  # HK-20
    "#7e1f34",  # Tokyo-20
    "#7a3d10",  # SG-20
    "#8e0b07",  # Red-20
    "#8e9ad0",  # Chicago-70
    "#6dcdb5",  # HK-70
    "#e68a9a",  # Tokyo-70
]

# ============================================================
# Policy thresholds
# ============================================================
# Centralized policy thresholds. Every classifier function and every legend
# string reads from this dict -- change a number here and the entire app
# (logic + on-screen explanation) stays in sync.

THRESHOLDS = {
    # Production Planning: 4-week trend vs prior 4 weeks
    "production_trend_accel":   0.15,   # > +15% -> Accelerating
    "production_trend_decel":  -0.15,   # < -15% -> Decelerating
    # Launch Health: current velocity vs initial-4-weeks and benchmark
    "launch_on_track":          0.85,   # >=85% retention required for On Track
    "launch_failing":           0.70,   # <70% of benchmark -> Failing
    # Pricing Power: post-promo recovery vs pre-promo baseline
    "pricing_full_recovery":    0.95,   # >=95% -> Full
    "pricing_slow_recovery":    0.80,   # <80% -> Slow
    # Distribution Pruning, By SKU: % of stores below threshold
    "pruning_sku_critical":     0.50,   # >=50% -> Critical
    "pruning_sku_concerning":   0.25,   # 25-49% -> Concerning
    # Distribution Pruning, By Store: count of SKUs below threshold
    "pruning_store_critical":   3,      # >=3 SKUs -> Critical
    "pruning_store_concerning": 1,      # 1-2 SKUs -> Concerning
    # Shelf Defense: warning band as multiple of delisting threshold
    "shelf_warning_mult":       1.5,    # warning zone = [thr, 1.5*thr] AND declining
    # Promo ROI: cutoff between "marginal positive" and "strong" returns
    "roi_strong":               1.0,    # ROI > 100% (>1.0) -> Strong; 0-100% -> Marginal; <0% -> Negative
}

# ============================================================
# Decisions
# ============================================================

PORTFOLIO_HEALTH = "How healthy is my portfolio?"

DECISIONS = [
    "Is this SKU at risk of being delisted?",
    "How much should I produce over the next 4 weeks?",
    "Did my last promotion pay off?",
    "Which stores should I expand into next?",
    "Which stores aren't earning their shelf space?",
    "Which SKUs should I cut or keep?",
    "Is my new launch on track?",
    "Do I have pricing power on this SKU?",
    "Is my data trustworthy?",
]
DECISION_TITLES = {
    DECISIONS[0]: "Shelf Defense",
    DECISIONS[1]: "Production Planning -- Next 4 Weeks",
    DECISIONS[2]: "Promo ROI",
    DECISIONS[3]: "Distribution Expansion",
    DECISIONS[4]: "Distribution Pruning",
    DECISIONS[5]: "SKU Rationalization",
    DECISIONS[6]: "Launch Health",
    DECISIONS[7]: "Pricing Power",
    DECISIONS[8]: "Data Quality",
}

# ============================================================
# Retailer lists and thresholds
# ============================================================

PHYSICAL_RETAILERS = ["Walmart", "Costco", "Whole Foods", "Kroger", "Sprouts", "Regional"]
ALL_PHYSICAL_OR_AGG = [
    "Walmart", "Costco", "Whole Foods", "Kroger", "Sprouts",
    "Regional", "UNFI", "KeHE", "DTC",
]

RETAILER_THRESHOLDS = {
    "Walmart":     2.5,   # conventional grocery floor, condiment/sauce category
    "Costco":      10.0,  # club channel — 25x grocery velocity, higher floor
    "Whole Foods": 1.5,   # specialty/premium, lower volume tolerated
    "Kroger":      2.5,   # conventional grocery, similar to Walmart
    "Sprouts":     1.5,   # natural/specialty, similar to Whole Foods
    "Regional":    1.5,   # small chains, lower expectations
}

REGIONAL_CHAINS = (
    "Regional Group",
)

RETAILER_ID_MAP = {
    "Walmart":      "RET-WALMART",
    "Costco":       "RET-COSTCO",
    "Whole Foods":  "RET-WHOLEFOODS",
    "Kroger":       "RET-KROGER",
    "Sprouts":      "RET-SPROUTS",
    "Regional":     "RET-REGIONAL",
    "Regional Group": "RET-REGIONAL",
}

VOLUME_TIER_MULT = {"A": 1.3, "B": 1.0, "C": 0.7}

LAUNCH_BENCHMARK = 4.0

# ============================================================
# Category mapping (product_line → market category)
# ============================================================

CATEGORY_MAP = {
    "Artisan Sauces":        "Sauces & Marinades",
    "Specialty Condiments":  "Condiments & Dressings",
    "Pantry Staples":        "Dry Grocery & Baking",
}

BENCHMARK_BLUE = BENCHMARK_REF   # alias — legacy import compat

# ============================================================
# Status -> bar/line/text color
# ============================================================
# Universal color rule across the app:
#   TEAL  = positive / good / healthy
#   RED   = negative / bad / problem
#   ORANGE = caution / watch / mixed
#   NAVY_MED = neutral / stable / informational

SHELF_STATUS_COLORS = {"At Risk": RED, "Warning": ORANGE, "Safe": TEAL}
# Production: accelerating velocity is GOOD news (your product is selling),
# decelerating is BAD (slowing down), stable is neutral.
PRODUCTION_STATUS_COLORS = {"Accelerating": TEAL, "Decelerating": RED, "Stable": NAVY_MED}
# Pruning: Mild still means "some stores below threshold" -- that's a small
# concern, not a positive, so it reads as neutral (navy) rather than teal.
PRUNING_SEVERITY_COLORS = {"Critical": RED, "Concerning": ORANGE, "Mild": NAVY_MED}

# ============================================================
# Status -> (row bg, row text) for colored tables
# ============================================================

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

# ============================================================
# Retailer -> brand color (for grouped charts)
# ============================================================

RETAILER_COLORS = {
    "Walmart":     CHICAGO,       # Chicago-20
    "Costco":      HK_DARK,       # HK-20
    "Whole Foods": SG_DARK,       # SG-20
    "Kroger":      TOKYO_DARK,    # Tokyo-20
    "Sprouts":     TEAL,          # HK-35
    "Regional":    CHICAGO_LT,    # Chicago-70
    "UNFI":        GREY,          # London-40
    "KeHE":        SG_LIGHT,      # SG-70
    "DTC":         TOKYO_LIGHT,   # Tokyo-70
}
