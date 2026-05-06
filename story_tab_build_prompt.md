# Build Prompt: "The Story" Tab in the Velocity Decision Tool

Paste this into Claude Code.

---

## What to build

Add a new tab to `app/velocity_tool.py` called **"The Story"** — a scroll-driven narrative that lives alongside the eight decision modes. This is the narrative companion to the tool. It tells the story of one SKU (CHP-0044, Charred Scallion Relish) that looks healthy in every standard report but is actually destroying value.

This tab should be the **first tab** in the sidebar navigation — before the eight decision modes. It's the entry point for someone who lands on the app and needs to understand why this tool exists before they use it.

---

## Structure (5 sections, scrolling vertically)

### Section 1: "The Monday Morning Report"

**Purpose:** Make the reader see their own report and feel good about it — then pull the rug.

Build a mock "Monday Morning Velocity Summary" that looks like what a CEO would build in Excel. Use `st.dataframe` or a styled HTML table with:

- Columns: SKU, Product Name, Product Line, Units (Current 52wk), Units (Prior 52wk), YoY Change %, Revenue (Current 52wk), Revenue (Prior 52wk), YoY Change %
- Pull REAL data from the database for ~15-20 SKUs including CHP-0044
- Sort by YoY Unit Change % descending (best performers on top)
- Apply green/red conditional formatting: green for positive YoY, red for negative
- CHP-0044 (Charred Scallion Relish) should appear in the top half of this table with its +14.9% YoY unit growth, looking healthy

**Text above the table:**
> "This is probably what your Monday morning report looks like. Total units across the portfolio: up. Revenue: up. Charred Scallion Relish at +15% year-over-year. Green arrow. Moving on to the next meeting."

**Text below the table:**
> "Everything in this table is accurate. None of it is useful. Here's what it can't show you."

Use a visual divider/separator before Section 2.

---

### Section 2: "The Volume Trap" — Charred Scallion Relish

**Purpose:** Introduce the protagonist SKU and reveal that its growth is fake.

**Chart 1: "Two versions of the same SKU"**
A dual-line chart (Plotly) showing CHP-0044's weekly velocity over the full time range:
- Line 1: Total velocity (all weeks) — this is what the CEO sees. Looks bumpy but generally OK.
- Line 2: Baseline velocity (non-promo weeks only, with promo weeks shown as gaps or greyed out) — this shows the real trend: declining.
- Shade or highlight the promo weeks in a distinct color so the reader can see how much of the "good" volume is promo-driven.
- Title: "Charred Scallion Relish: +15% growth — or -25% decline?"

**Key stats to display as callout cards (st.metric or styled HTML):**
- YoY Total Volume: +14.9% ↑ (green)
- Baseline Velocity Trend: -24.8% ↓ (red)
- Promo Weeks: 4% → 27% of all weeks (orange)
- Trade Spend: $18,701 (red)

**Text:**
> "Charred Scallion Relish moved 14.9% more units this year than last. But strip out the promotional weeks and the real velocity — the rate at which consumers pick this product off the shelf without a discount — dropped 24.8%. The brand spent $18,701 in trade to make a shrinking SKU look like a growing one."

---

### Section 3: "What $18,701 Bought" — Promo ROI

**Purpose:** Show that the trade spend didn't just mask the decline — it may have accelerated it.

**Chart 2: "The Promo Hangover"**
For CHP-0044, show a bar or area chart with three velocity phases around each promo event:
- Pre-promo baseline velocity (4 weeks before)
- Promo velocity (during the promo)
- Post-promo velocity (4 weeks after)

Show this for each promotional event CHP-0044 had. The key insight: post-promo velocity is LOWER than pre-promo velocity. Each promotion leaves the baseline worse than before.

If the data supports it, show the cumulative effect: each successive promo lifts less and drops the baseline further.

Title: "Every promotion left the baseline lower than before"

**Text:**
> "The three promotions on Charred Scallion Relish each followed the same pattern: a short spike in volume, followed by a post-promo dip that settled below where it started. The brand didn't just spend $18,701 to stand still — it spent $18,701 to accelerate the decline."

Calculate and display: net units gained from promos vs. what baseline decline cost. Show whether the promo spend was net positive or net negative in dollar terms.

---

### Section 4: "The Shelf Is Watching" — Shelf Defense

**Purpose:** Show where this trajectory leads — delisting.

**Chart 3: "Velocity Trajectory vs. Delisting Threshold"**
A line chart showing CHP-0044's trailing 13-week average velocity, projected forward at the current decline rate. Include a horizontal line for the retailer's delisting threshold (use the threshold from the Shelf Defense decision mode). Show when the lines cross — that's the estimated delisting date.

Title: "At current trajectory, Charred Scallion Relish hits the delisting threshold in Q[X] [Year]"

**Text:**
> "Walmart reviews velocity quarterly. The category threshold is [X] units/store/week. Charred Scallion Relish is currently at [Y], declining at [Z]% per quarter. If nothing changes, it crosses the threshold in [timeframe]. That's [N] doors and $[amount] in annual revenue at risk."

---

### Section 5: "The Total Cost of Not Knowing"

**Purpose:** Roll it all up into one number and close.

**Calculate and display the total cost:**
- Trade spend burned on declining SKU: $18,701
- Revenue at risk from potential delisting (annual revenue from this SKU at current stores)
- Margin destroyed: the gap between what this SKU earned and what a replacement SKU in that shelf space could have earned (use category average velocity × margin as the benchmark)
- Sum it all into one "Total Cost of Not Knowing" figure

Display this as a single large number, prominently styled.

**Text:**
> "Every number in the Monday morning report was accurate. The portfolio was up. Revenue was up. Charred Scallion Relish was up 15%. And underneath those green arrows, $[total] in value was being destroyed — invisible to every pivot table in the building."

**Transition to the tool:**
> "This is one SKU. The Velocity Decision Tool runs this analysis across all 90. Pick a decision from the sidebar."

Include buttons or links to jump directly to each of the four relevant decision modes with CHP-0044 context.

---

## The Four "Healthy" Decisions

After the main narrative (or as a clearly labeled subsection at the bottom), include a section called **"What the rest of the portfolio looks like"** with one paragraph and one chart for each of these four decisions:

1. **Production Planning** — One paragraph summarizing that demand signals align with current production. One chart: a simple bar chart showing top 10 SKUs by projected 4-week case demand.

2. **Distribution Expansion** — One paragraph summarizing where opportunity exists. One chart: horizontal bar chart showing top 10 stores/regions by velocity-per-door vs. current distribution.

3. **Distribution Pruning** — One paragraph summarizing the bottom performers. One chart: horizontal bar chart of bottom 10 stores by velocity gap below threshold.

4. **Pricing Power** — One paragraph summarizing elasticity findings. One chart: horizontal bar chart of top 10 SKUs by price elasticity.

Each paragraph should be 2-3 sentences, state a specific finding with a number, and end with: "Explore this in the [Decision Name] tab →" linking to that tab.

---

## Design rules

Follow ALL existing visualization rules from the app:

- **Color scheme:** Dark navy #1B2A4A, Medium navy #3D5A80, Teal #1E8C7E, Deep red #C0221F, Orange #D35830, Grey #636E72, Light grey #DADDE3, White #FFFFFF
- **Chart rules:** Horizontal bars > scatter plots. Direct labels > legends. Plain English titles that state the insight. Red/orange/green color coding. One chart = one question.
- **Typography:** Use the same heading/subheading hierarchy as the rest of the app
- **Spacing:** Use `st.divider()` or generous whitespace between sections to create the scroll-driven pacing

## Writing standard

- Every claim traced to a specific dollar amount from the data
- Let the data say something sharp. Don't water it down.
- Don't punch down at Excel — frame it as "accurate but incomplete"
- No hedging. No "approximately" or "roughly." Specific numbers.
- The tone is authoritative, not academic. A smart person explaining what they found, not a consultant trying to sound impressive.

## Technical notes

- Query the database for all numbers. Do not hardcode values — pull them from scan_data, promotions, sku_costs, distribution_log, and product_master tables.
- CHP-0044 is the protagonist SKU. All narrative charts focus on this SKU.
- The "Before" pivot table in Section 1 should use real aggregated data for ~15-20 SKUs so the table looks like a real report, not a setup.
- For the delisting threshold projection in Section 4, use the same threshold logic from the existing Shelf Defense decision mode.
- Make sure the tab renders performantly — the scan_data table is 1.19M rows. Pre-aggregate where possible.
