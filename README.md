# Cinderhaven Velocity Decision Tool

A prescriptive decision tool for specialty food CEOs who get velocity reports every Monday but don't know what decisions they should drive.

**Try it live → [https://velocity.lailarallc.com](https://velocity.lailarallc.com)**

## What it does

Most velocity reports tell you what happened. This tool tells you what to do next. The default view is a portfolio health dashboard that surfaces risk indicators across every decision area. The CEO sees what needs attention immediately, then drills into the decision mode that answers it.

**Nine decision views:**

1. **Portfolio Health** — What needs my attention right now? (default landing page)
2. **Shelf Defense** — Is this SKU about to get delisted?
3. **Production Planning** — How much should I produce over the next 4 weeks?
4. **Promo ROI** — Should I run that promotion again?
5. **Distribution Expansion** — Which stores should I pitch next?
6. **Distribution Pruning** — Which stores aren't earning their shelf space?
7. **SKU Rationalization** — Which SKUs should I cut or keep?
8. **Launch Trajectory** — Is my new product on track?
9. **Pricing Power** — Should I promote this SKU again?

Each decision mode includes a data grid, a chart, and a narrative "so what" insight. Shelf Defense, Production Planning, and Launch Trajectory also include time-series trend views.

## Why it matters

A $15M–$50M brand pays for syndicated data and gets back description, not prescription: velocity by SKU by store, week after week, with no verdict attached. The decisions that data should drive — defend the shelf slot, cut the SKU, reprice, expand, prune — get made on instinct or not at all. Framing the same data as nine answerable questions turns the Monday report from a reading assignment into a decision queue, and puts the "so what" next to every number. The report isn't the point. The point is knowing what to do next.

## The dataset

Built on a synthetic dataset for Cinderhaven Provisions, a fictional ~$25M specialty food company with 50 SKUs across five product lines (Artisan Sauces, Pantry Staples, Specialty Condiments, Dried Goods, Snack Bites):

- **1.2M rows** of weekly scan data across 902 stores
- **6 contracted retailers:** Walmart (~500 doors), Costco (~80), Whole Foods (~120), Sprouts, Kroger, Regional Group
- **3 distributors + DTC:** UNFI, KeHE, DPI Northwest, Shopify (DTC)
- Realistic promotional history, data-quality-driven chargebacks traceable to product master defects, seasonal patterns, stockout events, new product cannibalization, price changes, and organic velocity trends

Data source: the Cinderhaven Data Platform — a Postgres database with dbt-managed staging, intermediate, and mart tables, hosted on Fly.io with local Docker for development. All decision modes operate on the full 50-SKU set and all channels.

## Quick start

```bash
git clone https://github.com/MsShawnP/retail-velocity-decision-tool.git
cd retail-velocity-decision-tool
pip install -r app/requirements.txt
cp .env.example .env   # set DATABASE_URL
cd app && python run.py
```

The app connects to a Postgres database. To run locally, start the shared Docker Postgres from [refactor-older-cinderhaven-projects](https://github.com/MsShawnP/refactor-older-cinderhaven-projects):

```bash
# In the refactor-older-cinderhaven-projects repo:
docker compose up

# Then in this repo:
cd app && python run.py
```

## Tech stack

- **Dash** — interactive decision tool
- **Dash Bootstrap Components** — layout grid, cards, tabs
- **AG Grid** — sortable, filterable data tables
- **Plotly** — CEO-readable visualizations
- **Python + Pandas** — data analysis
- **Postgres** — Cinderhaven Data Platform (psycopg2, ThreadedConnectionPool)
- **flask-caching** — FileSystemCache on a persistent Fly volume
- **Gunicorn** — 1 worker, 4 gthread threads, 120s timeout
- **Fly.io** — hosting (shared-cpu-1x, 1GB RAM, always-on)

## Context

This is the flagship portfolio piece for a decision-framework consulting practice targeting specialty food operators at $15M–$50M scaling into national retail. Adjacent pieces include the [Cinderhaven Product Data Audit Report](https://audit.lailarallc.com), the [GTIN Validator](https://github.com/MsShawnP/gtin-validator), and a 53-query SQL library for retail data analysis.

## License

MIT — see [LICENSE](LICENSE).
