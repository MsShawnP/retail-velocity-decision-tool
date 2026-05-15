# Plan — Cinderhaven Velocity Decision Tool

## Goal (2026-05-15)

Replace the Story mode with a portfolio health dashboard as the default landing
page, and enhance the decision modes to tell a more compelling story when
prospects drill in.

**Audience:** Cold-landing CEO of a $20-25M food company. Lean org, velocity-
minded, zero onboarding tolerance. Already uses velocity for production planning
but is data-hungry for shelf defense, promo ROI, and other areas their current
system can't serve.

**Scope:**
- Remove story.py and all story UI (deep dive sidebar section, callbacks, etc.)
- Build a portfolio health overview as the new landing view: business-wide
  metrics, time-series trends, risk indicators across the portfolio
- Enhance decision modes with time-series charts, contextual insights, and
  "so what" narrative framing — the decision modes ARE the story chapters
- Clear drill-down paths from portfolio health into the relevant decision modes
- Existing Cinderhaven dataset only (no new synthetic data)

**Out of scope:**
- Competitive benchmarking (requires new synthetic data — separate workstream)
- New decision modes

**Done looks like:**
The tool tells a portfolio story from the moment you land. The health overview
hooks you by surfacing what's interesting (at-risk clusters, production spikes,
promo patterns). Each decision mode delivers a clear "here's what's happening
and what to do about it" narrative. No separate story mode needed because the
whole tool IS the story. A prospect walks away thinking "I need this for my
data."

**Key assumptions:**
- The Cinderhaven dataset was purpose-built for this tool and has realistic
  patterns worth discovering at the portfolio level (confirmed)
- Decision modes are narrative building blocks, not frozen — they can and
  should be enhanced to be more compelling (confirmed)

---

## Decomposition: Portfolio Health Dashboard

Goal: Replace Story mode with a portfolio health landing page and enhance
decision modes as narrative building blocks — so the whole tool tells the
portfolio story.

### Track A — Landing page (sequential)

- [x] A1: Remove Story mode
    - Depends on: none
    - Delete story.py. Remove all story references from callbacks.py
      (story_layout import, view=="story" branch, came-from-story back-button
      logic, enter_story callback), layout.py (_deep_dive_section, view-store
      "story" handling, came-from-story/scroll-to-section-5 stores), run.py
      (story_cbs import + registration), constants.py (PROTAGONIST_SKU), and
      CSS (.story-entry-btn, .back-to-story-btn). Remove story-only data
      functions from data.py (get_monday_morning_summary,
      get_sku_weekly_velocity, get_promo_hangover_data, get_sku_trade_spend,
      get_walmart_trajectory, get_sku_revenue_at_risk, get_sku_costs,
      get_category_avg_velocity, get_top_demand_4wk, get_top_velocity_per_door,
      get_bottom_stores_below_threshold, get_top_elasticity_skus).
    - Done when: story.py is gone, app starts cleanly, all 8 decision modes
      still work, no import errors.

- [x] A2: Portfolio health data layer
    - Depends on: none
    - New functions in data.py that aggregate across decision areas to produce
      portfolio-level metrics. Compose from existing queries where possible:
      get_shelf_defense_data("All Retailers"), get_production_data("All
      Retailers"), get_rationalization_data("All Retailers"),
      get_launch_data(). Return: total active SKUs, retailer count, at-risk
      counts by area (shelf-risk, decelerating, low-rationalization-score),
      accelerating counts, launch health summary. No new SQL if avoidable.
    - Done when: A `get_portfolio_summary()` function returns a dict of
      portfolio-wide metrics. Unit tests verify the shape and types.

- [x] A3: Portfolio health landing page
    - Depends on: A1, A2
    - New `decisions/portfolio_health.py` module with a `layout()` function
      that renders: KPI row (total SKUs, total retailers, total doors,
      latest week), risk indicator cards by decision area (at-risk shelf SKUs,
      decelerating production SKUs, underperforming rationalization scores,
      recent launches needing attention), and status distribution summary.
      Wire as the default view: dispatcher renders portfolio health when
      decision-picker value is a new "Portfolio Health" entry at index 0
      (existing modes shift to indices 1-8).
    - Done when: App launches to the portfolio health page. KPIs and risk
      cards render with real Cinderhaven data. Decision picker still switches
      to all 8 existing modes.

- [x] A4: Drill-down navigation
    - Depends on: A3
    - Risk indicator cards on the portfolio health page are clickable. Clicking
      one sets the decision-picker to the corresponding mode (e.g., clicking
      "3 at-risk SKUs" navigates to Shelf Defense). Use clientside callback
      or regular callback to update the decision-picker value.
    - Done when: Each risk card navigates to the correct decision mode.
      Browser test confirms the round-trip: land on portfolio → click a
      risk card → arrive at the right decision mode with data loaded.

### Track B — Decision mode enhancements (parallel, independent of A)

- [x] B1: Decision mode narrative framing
    - Depends on: none
    - Add a "so what" insight section to each of the 8 decision modes: a
      1-2 sentence contextual interpretation below the headline that frames
      the business implication. Example: Shelf Defense currently says "12 of
      45 SKUs are at risk" — add "These 12 SKUs represent $X in weekly
      revenue. Losing shelf space here shifts volume to competitors." Derive
      from existing data already available in each layout function.
    - Done when: Each mode shows a contextual insight that references
      specific numbers from the current filter selection. Visual QA confirms
      readability.

- [x] B2: Decision mode time-series additions
    - Depends on: none
    - Add trend visualizations to decision modes that currently show only
      point-in-time data. Candidates: Shelf Defense (velocity trend over
      last 12 weeks for at-risk SKUs), Production (trend line alongside
      the bar chart), Rationalization (score trend). Use existing weekly
      scan data — no new synthetic data.
    - Done when: At least 3 decision modes gain a time-series chart that
      uses real Cinderhaven data. Charts render without errors.

### Integration

- [x] C: End-to-end polish
    - Depends on: A4, B1, B2
    - Full flow verification in browser: land on portfolio health → read
      the KPIs → click a risk card → arrive at decision mode with narrative
      context → return to portfolio. Visual QA for layout consistency,
      loading states, and mobile-width degradation. Fix any regressions.
    - Done when: A prospect can walk through the tool cold and understand
      what Cinderhaven's portfolio looks like within 30 seconds of landing.
