# Cinderhaven Velocity Decision Tool

**[Try it live → https://velocity-tool.streamlit.app/](https://velocity-tool.streamlit.app/)**

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

## The dataset

Built on a synthetic dataset for Cinderhaven Provisions, a fictional ~$25M specialty food company with 90 SKUs across three product lines (artisan sauces, specialty condiments, pantry staples). The dataset includes:

- **1.2M rows** of weekly scan data across 902 stores
- **6 retail channels:** Walmart (~500 doors), Costco (~80), Whole Foods (~120), Regional (~200), UNFI distribution, DTC
- Realistic promotional history with retailer-specific patterns
- Data-quality-driven chargebacks traceable to product master defects
- Seasonal patterns, stockout events, new product cannibalization, price changes, and organic velocity trends

## Running locally

```bash
git clone https://github.com/MsShawnP/retail-velocity-decision-tool.git
cd retail-velocity-decision-tool
pip install -r app/requirements.txt
streamlit run app/velocity_tool.py
```

The database generates automatically on first run (~5-10 minutes). Subsequent starts are instant.

## Built with

- **Streamlit** — interactive decision tool
- **Python + Pandas** — data generation and analysis
- **Plotly** — CEO-readable visualizations
- **SQLite** — lightweight data storage

## Context

This is the flagship portfolio piece for a decision-framework consulting practice targeting specialty food operators at $15M–$50M scaling into national retail. Adjacent pieces include the [Cinderhaven Product Data Audit Report](link), a GTIN Validator tool, and a 53-query SQL library for retail data analysis.

---

*"The report isn't the point. The point is knowing what to do next."*
