# Cinderhaven Velocity Decision Tool

**Try it live → [https://retail-velocity-decision-tool.fly.dev](https://retail-velocity-decision-tool.fly.dev)**

A prescriptive decision tool for specialty food CEOs who get velocity reports every Monday but don't know what decisions they should drive.

## What this is

Most velocity reports tell you what happened. This tool tells you what to do next. The CEO picks a decision they're trying to make, and the tool surfaces the right velocity view to answer it.

**Eight decisions velocity should drive:**

1. **Shelf Defense** — Is this SKU about to get delisted?
2. **Production Planning** — How much should I produce over the next 4 weeks?
3. **Promo ROI** — Should I run that promotion again?
4. **Distribution Expansion** — Which stores should I pitch next?
5. **Distribution Pruning** — Which stores aren't earning their shelf space?
6. **SKU Rationalization** — Which SKUs should I cut or keep?
7. **Launch Trajectory** — Is my new product on track?
8. **Pricing Power** — Should I promote this SKU again?

## The Deep Dive: The Charred Scallion Relish Problem

The app includes a narrative case study that traces one SKU — Charred Scallion Relish (CHP-0044) — through four decision modes. What looks like a healthy +15% YoY growth story in the Monday morning report turns out to be a SKU buying revenue at a loss: baseline velocity declining 25%, promotional intensity tripled to mask it, $24,686 in trade spend burned, and $723,842 in total value being destroyed — invisible to every pivot table in the building. Click "The Charred Scallion Relish problem" in the sidebar to read it.

## The dataset

Built on a synthetic dataset for Cinderhaven Provisions, a fictional ~$25M specialty food company with 90 SKUs across three product lines (artisan sauces, specialty condiments, pantry staples). The dataset includes:

- **1.2M rows** of weekly scan data across 902 stores
- **6 retail channels:** Walmart (~500 doors), Costco (~80), Whole Foods (~120), Regional (~200), UNFI distribution, DTC
- Realistic promotional history with retailer-specific patterns
- Data-quality-driven chargebacks traceable to product master defects
- Seasonal patterns, stockout events, new product cannibalization, price changes, and organic velocity trends

> **Data source:** the Cinderhaven Data Platform — a Postgres database
> with dbt-managed staging, intermediate, and mart tables, hosted on
> Fly.io with local Docker for development.

## Running locally

```bash
git clone https://github.com/MsShawnP/retail-velocity-decision-tool.git
cd retail-velocity-decision-tool
pip install -r app/requirements.txt
cp .env.example .env   # edit DATABASE_URL if not using local Docker
cd app && python run.py
```

To run locally, start the shared Docker Postgres from
[refactor-older-cinderhaven-projects](https://github.com/MsShawnP/refactor-older-cinderhaven-projects):

```bash
# In the refactor-older-cinderhaven-projects repo:
docker compose up

# Then in this repo (development mode, http://localhost:8050):
cd app && python run.py

# Or, to run the gunicorn server the way it runs in production:
cd app && gunicorn run:server -b 0.0.0.0:8080 --worker-class gthread --threads 4
```

## Built with

- **Dash + Plotly** — interactive decision tool and CEO-readable visualizations
- **dash-ag-grid** — sortable, filterable data grids
- **flask-caching** — FileSystemCache backed by a persistent Fly volume
- **Python + Pandas** — data analysis
- **Postgres** — Cinderhaven Data Platform (psycopg2 + PID-aware pool)
- **Fly.io** — deployment (1 gunicorn worker × 4 threads, always-on)

## Context

This is the flagship portfolio piece for a decision-framework consulting practice targeting specialty food operators at $15M–$50M scaling into national retail. Adjacent pieces include the [Cinderhaven Product Data Audit Report](link), a GTIN Validator tool, and a 53-query SQL library for retail data analysis.

---

*"The report isn't the point. The point is knowing what to do next."*
