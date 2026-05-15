"""Cinderhaven Velocity Tool — shared constants.

Extracted from velocity_tool.py lines 29-163. Every color, threshold,
retailer list, and status-color map lives here so both the legacy Streamlit
app and the new Dash app import from the same source of truth.
"""

from __future__ import annotations

# ============================================================
# Cinderhaven brand palette
# ============================================================

NAVY         = "#1B2A4A"   # primary headings, emphasis
NAVY_MED     = "#3D5A80"   # subheadings, secondary text
TEAL         = "#1E8C7E"   # positive / safe / accent
RED          = "#C0221F"   # critical / at-risk
DARK_RED     = "#8B0000"   # "worse than red" -- used for promo-backfired bars
ORANGE       = "#D35830"   # warning
GREY         = "#636E72"   # muted text, labels
GREY_LIGHT   = "#DFE6E9"   # borders, dividers, gridlines
GREY_BG      = "#F8F9FA"   # alternating rows
WHITE        = "#FFFFFF"
RED_FAINT    = "#FFF5F5"   # critical alert backgrounds
GREEN_FAINT  = "#F0FFF4"   # positive alert backgrounds
ORANGE_FAINT = "#FFF8F0"   # warning alert backgrounds (derived)
DARK_RED_FAINT = "#FBE9E7" # backfired-promo row backgrounds
PAGE_BG      = "#DADDE3"   # main content area

# ============================================================
# Policy thresholds
# ============================================================
# Centralized policy thresholds. Every classifier function and every legend
# string reads from this dict -- change a number here and the entire app
# (logic + on-screen explanation) stays in sync.

THRESHOLDS = {
    # Production Planning: 4-week trend vs prior 4 weeks
    "production_trend_accel":   0.10,   # > +10% -> Accelerating
    "production_trend_decel":  -0.10,   # < -10% -> Decelerating
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
}

# ============================================================
# Retailer lists and thresholds
# ============================================================

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
    "Walmart":     NAVY,
    "Costco":      TEAL,
    "Whole Foods": ORANGE,
    "Regional":    NAVY_MED,
    "UNFI":        GREY,
    "DTC":         "#8B6F47",   # warm muted, distinguishes from the rest
}
