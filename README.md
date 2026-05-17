# Cinderhaven Velocity Decision Tool

**Try it live → [https://retail-velocity-decision-tool.fly.dev](https://retail-velocity-decision-tool.fly.dev)**

A prescriptive decision tool for specialty food CEOs who get velocity reports every Monday but don't know what decisions they should drive.

## What this is

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

## The dataset

Built on a synthetic dataset for Cinderhaven Provisions, a fictional ~$25M specialty food company with 50 SKUs across three product lines (artisan sauces, specialty condiments, pantry staples). The dataset includes:

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
cp .env.example .env   # set DATABASE_URL
cd app && python run.py
```

The app connects to a Postgres database. To run locally, start the shared
Docker Postgres from
[refactor-older-cinderhaven-projects](https://github.com/MsShawnP/refactor-older-cinderhaven-projects):

```bash
# In the refactor-older-cinderhaven-projects repo:
docker compose up

# Then in this repo:
cd app && python run.py
```

## Built with

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

This is the flagship portfolio piece for a decision-framework consulting practice targeting specialty food operators at $15M–$50M scaling into national retail. Adjacent pieces include the [Cinderhaven Product Data Audit Report](link), the [GTIN Validator](https://github.com/MsShawnP/gtin-validator), and a 53-query SQL library for retail data analysis.

---

*"The report isn't the point. The point is knowing what to do next."*

## License

MIT — see [LICENSE](LICENSE).
