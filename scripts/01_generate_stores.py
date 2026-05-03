"""Generate the `stores` table for the Cinderhaven velocity-tool database.

Creates ~1,000 retailer store records plus two aggregated channel rows
(UNFI and DTC). Volumes, regions and state distributions are intended to
roughly mirror real US retail footprints.
"""

import random
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"
SEED = 42

REGION_STATES = {
    "Northeast": ["ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA"],
    "Southeast": ["VA", "NC", "SC", "GA", "FL", "KY", "TN", "WV"],
    "Midwest":   ["OH", "IN", "IL", "MI", "WI", "MN", "IA", "MO", "ND", "SD", "NE", "KS"],
    "South":     ["AL", "MS", "AR", "LA", "OK", "TX"],
    "West":      ["MT", "WY", "CO", "NM", "ID", "UT", "AZ", "NV", "WA", "OR", "CA", "AK", "HI"],
}

# Realistic intra-region state weights (rough store-count proxies)
STATE_WEIGHTS = {
    # Northeast
    "ME": 1, "NH": 1, "VT": 1, "MA": 5, "RI": 1, "CT": 3, "NY": 10, "NJ": 6, "PA": 8,
    # Southeast
    "VA": 5, "NC": 7, "SC": 4, "GA": 7, "FL": 12, "KY": 4, "TN": 5, "WV": 2,
    # Midwest
    "OH": 7, "IN": 5, "IL": 7, "MI": 6, "WI": 4, "MN": 4, "IA": 3, "MO": 5,
    "ND": 1, "SD": 1, "NE": 2, "KS": 3,
    # South
    "AL": 4, "MS": 3, "AR": 6, "LA": 4, "OK": 4, "TX": 15,
    # West
    "MT": 1, "WY": 1, "CO": 4, "NM": 2, "ID": 2, "UT": 3, "AZ": 5, "NV": 2,
    "WA": 5, "OR": 3, "CA": 14, "AK": 1, "HI": 1,
}


def weighted_state(region: str) -> str:
    states = REGION_STATES[region]
    weights = [STATE_WEIGHTS[s] for s in states]
    return random.choices(states, weights=weights, k=1)[0]


def weighted_region(distribution: dict) -> str:
    regions = list(distribution.keys())
    weights = list(distribution.values())
    return random.choices(regions, weights=weights, k=1)[0]


def weighted_tier(distribution: dict) -> str:
    tiers = list(distribution.keys())
    weights = list(distribution.values())
    return random.choices(tiers, weights=weights, k=1)[0]


def gen_walmart(n=500):
    # Walmart is heaviest in South, Southeast, Midwest
    region_dist = {"Northeast": 12, "Southeast": 26, "Midwest": 22, "South": 26, "West": 14}
    tier_dist = {"A": 20, "B": 50, "C": 30}
    rows = []
    for i in range(1, n + 1):
        region = weighted_region(region_dist)
        rows.append((
            f"WMT-{i:04d}",
            "Walmart",
            "Walmart",
            region,
            weighted_state(region),
            weighted_tier(tier_dist),
            0,
        ))
    return rows


def gen_costco(n=80):
    # Costco concentrated in West and Northeast (also some Midwest/South/SE)
    region_dist = {"West": 55, "Northeast": 25, "Midwest": 8, "Southeast": 7, "South": 5}
    rows = []
    for i in range(1, n + 1):
        region = weighted_region(region_dist)
        rows.append((
            f"COST-{i:04d}",
            "Costco",
            "Costco",
            region,
            weighted_state(region),
            "A",
            0,
        ))
    return rows


def gen_whole_foods(n=120):
    # Heavy Northeast + Pacific Northwest (West). Pacific Northwest sits in West region;
    # we bias West states to WA/OR/CA via dedicated weights below.
    region_dist = {"Northeast": 38, "West": 32, "Southeast": 12, "Midwest": 10, "South": 8}
    tier_dist = {"A": 30, "B": 50, "C": 20}
    pnw_states = ["WA", "OR", "CA", "CO", "AZ", "NV", "UT", "ID", "NM", "MT", "WY", "AK", "HI"]
    pnw_weights = [9, 6, 14, 3, 3, 2, 2, 1, 1, 1, 1, 1, 1]  # heavy WA/OR/CA
    rows = []
    for i in range(1, n + 1):
        region = weighted_region(region_dist)
        if region == "West":
            state = random.choices(pnw_states, weights=pnw_weights, k=1)[0]
        else:
            state = weighted_state(region)
        rows.append((
            f"WFM-{i:04d}",
            "Whole Foods",
            "Whole Foods Market",
            region,
            state,
            weighted_tier(tier_dist),
            0,
        ))
    return rows


def gen_regional(n=200):
    # Five regional chains, each concentrated in 1-2 regions.
    chains = [
        {
            "name": "Green Basket Market",
            "prefix": "GBM",
            "regions": {"Northeast": 70, "Midwest": 30},
            "share": 0.22,
        },
        {
            "name": "Harbor Fresh",
            "prefix": "HBF",
            "regions": {"Northeast": 60, "Southeast": 40},
            "share": 0.18,
        },
        {
            "name": "Prairie Provisions",
            "prefix": "PRP",
            "regions": {"Midwest": 75, "South": 25},
            "share": 0.20,
        },
        {
            "name": "Mountain Pantry Co",
            "prefix": "MPC",
            "regions": {"West": 80, "Midwest": 20},
            "share": 0.18,
        },
        {
            "name": "Southside Grocers",
            "prefix": "SSG",
            "regions": {"South": 65, "Southeast": 35},
            "share": 0.22,
        },
    ]
    tier_dist = {"B": 55, "C": 40, "A": 5}  # mostly B/C
    rows = []
    counts = [round(c["share"] * n) for c in chains]
    # adjust for rounding to hit n exactly
    diff = n - sum(counts)
    counts[0] += diff

    for chain, count in zip(chains, counts):
        for i in range(1, count + 1):
            region = weighted_region(chain["regions"])
            rows.append((
                f"{chain['prefix']}-{i:04d}",
                chain["name"],
                chain["name"],
                region,
                weighted_state(region),
                weighted_tier(tier_dist),
                0,
            ))
    return rows


def gen_aggregated():
    return [
        ("UNFI-AGG", "UNFI", "UNFI", None, None, None, 1),
        ("DTC-AGG",  "DTC",  "DTC",  None, None, None, 1),
    ]


def main():
    random.seed(SEED)
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("DROP TABLE IF EXISTS stores")
    cur.execute("""
        CREATE TABLE stores (
            store_id              TEXT PRIMARY KEY,
            retailer              TEXT NOT NULL,
            chain_name            TEXT NOT NULL,
            region                TEXT,
            state                 TEXT,
            volume_tier           TEXT,
            is_aggregated_channel INTEGER NOT NULL DEFAULT 0
        )
    """)

    rows = []
    rows.extend(gen_walmart(500))
    rows.extend(gen_costco(80))
    rows.extend(gen_whole_foods(120))
    rows.extend(gen_regional(200))
    rows.extend(gen_aggregated())

    cur.executemany(
        "INSERT INTO stores (store_id, retailer, chain_name, region, state, volume_tier, is_aggregated_channel) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()

    print(f"Inserted {len(rows)} rows into stores table.\n")

    print("Counts by retailer:")
    for r, c in cur.execute("SELECT retailer, COUNT(*) FROM stores GROUP BY retailer ORDER BY COUNT(*) DESC"):
        print(f"  {r:<15} {c}")

    print("\nWalmart tier breakdown:")
    for t, c in cur.execute(
        "SELECT volume_tier, COUNT(*) FROM stores WHERE retailer='Walmart' GROUP BY volume_tier ORDER BY volume_tier"
    ):
        print(f"  Tier {t}: {c}")

    print("\nWalmart region breakdown:")
    for region, c in cur.execute(
        "SELECT region, COUNT(*) FROM stores WHERE retailer='Walmart' GROUP BY region ORDER BY COUNT(*) DESC"
    ):
        print(f"  {region:<10} {c}")

    print("\nCostco region breakdown:")
    for region, c in cur.execute(
        "SELECT region, COUNT(*) FROM stores WHERE retailer='Costco' GROUP BY region ORDER BY COUNT(*) DESC"
    ):
        print(f"  {region:<10} {c}")

    print("\nWhole Foods region breakdown:")
    for region, c in cur.execute(
        "SELECT region, COUNT(*) FROM stores WHERE retailer='Whole Foods' GROUP BY region ORDER BY COUNT(*) DESC"
    ):
        print(f"  {region:<10} {c}")

    print("\nRegional chain counts:")
    for chain, c in cur.execute(
        "SELECT chain_name, COUNT(*) FROM stores "
        "WHERE retailer NOT IN ('Walmart','Costco','Whole Foods','UNFI','DTC') "
        "GROUP BY chain_name ORDER BY COUNT(*) DESC"
    ):
        print(f"  {chain:<25} {c}")

    print("\nAggregated channel rows:")
    for row in cur.execute(
        "SELECT store_id, retailer, is_aggregated_channel FROM stores WHERE is_aggregated_channel=1"
    ):
        print(f"  {row}")

    con.close()


if __name__ == "__main__":
    main()
