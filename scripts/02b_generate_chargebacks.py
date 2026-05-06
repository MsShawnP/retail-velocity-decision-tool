"""Regenerate the `chargebacks` table so reasons map to actual product
master defects.

Rules (from the user's defect → chargeback brief):
  - SKUs with invalid GTIN-14 check digit  -> "Invalid GTIN/UPC"  (Walmart, Costco, UNFI, Whole Foods)
  - SKUs with missing/placeholder UPC      -> "Missing product data" (Walmart, UNFI, Whole Foods)
  - SKUs with missing case dimensions      -> "Dimension mismatch" (Walmart, Costco, UNFI)
  - SKUs missing brand_owner               -> "Missing product data" (Walmart, UNFI)
  - SKUs missing country_of_origin         -> "Missing product data" (Walmart)
  - Clean SKUs (no defects)                -> rare "Short shipment" / "Late delivery" (operational)

Total annual chargeback amount targeted at $55K-$75K. Runtime is short — the
script reads product master defects, then probabilistically emits one charge
per (sku, defect, retailer, month) cell.
"""

from __future__ import annotations

import random
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cinderhaven_product_master.db"
SEED = 42

# Chargeback window: 18 months ending 2026-05 (matches the prior table).
START_YEAR_MONTH = (2024, 12)
END_YEAR_MONTH = (2026, 5)


def months_in_window() -> list[str]:
    out = []
    y, m = START_YEAR_MONTH
    while (y, m) <= END_YEAR_MONTH:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y += 1
            m = 1
    return out


# ----- defect detection (mirror script 02) -----

def gtin_invalid(gtin: str | None) -> bool:
    if not gtin or len(gtin) != 14 or not gtin.isdigit():
        return True
    d = [int(c) for c in gtin]
    s = sum(d[i] * (1 if (12 - i) % 2 == 0 else 3) for i in range(13))
    return (10 - s % 10) % 10 != d[13]


def upc_missing(upc: str | None) -> bool:
    if upc is None:
        return True
    s = str(upc).strip()
    return s == "" or s in ("TBD", "N/A", "0", "00000000000", "000000000000")


# ----- chargeback config -----

# Each defect type lists: (reason text, retailers that bill it, monthly probability,
# (amount min, amount max)). Probabilities tuned so totals land at ~$55-75K/yr.
#
# Calibration note: monthly_p values were scaled up 2.5× from the original
# tuning after the authorization filter was added. The original values
# assumed every SKU rolled against every retailer in the rule (regardless
# of authorization), which inflated dollar volume by ~2.7× via rolls on
# pairs that should never have been sampled. With the filter in place,
# the per-SKU surface area is smaller, so per-pair monthly_p has to rise
# to keep the targeted dollar range.
DEFECT_RULES = {
    "invalid_gtin": {
        "reason": "Invalid GTIN/UPC",
        "retailers": [
            ("Walmart",     0.875, (250, 500)),
            ("Costco",      0.700, (200, 400)),
            ("UNFI",        0.625, (100, 220)),
            ("Whole Foods", 0.625, (150, 300)),
        ],
    },
    "missing_upc": {
        "reason": "Missing product data",
        "retailers": [
            ("Walmart",     0.700, (200, 400)),
            ("UNFI",        0.550, (100, 200)),
            ("Whole Foods", 0.450, (120, 240)),
        ],
    },
    "missing_case_dims": {
        "reason": "Dimension mismatch",
        "retailers": [
            ("Walmart", 0.150, (180, 350)),
            ("Costco",  0.150, (200, 400)),
            ("UNFI",    0.100, (100, 200)),
        ],
    },
    "missing_brand": {
        "reason": "Missing product data",
        "retailers": [
            ("Walmart", 0.100, (150, 280)),
            ("UNFI",    0.075, (80, 180)),
        ],
    },
    "missing_country": {
        "reason": "Missing product data",
        "retailers": [
            ("Walmart", 0.1125, (180, 320)),
        ],
    },
}

# Operational chargebacks for clean SKUs. Per (sku, retailer, month).
OPERATIONAL_REASONS = [
    ("Short shipment", (180, 380)),
    ("Late delivery",  (150, 320)),
]
OPERATIONAL_RETAILERS = ["Walmart", "Costco", "UNFI", "Whole Foods"]
OPERATIONAL_MONTHLY_PROB = 0.020


def main() -> None:
    rng = random.Random(SEED)
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Authorized (sku, retailer) pairs from distribution_log joined to stores.
    # Includes any historical authorization (whether currently active or
    # since deauthorized) — a retailer that ever carried a SKU can still bill
    # against past shipments, but a retailer that never carried it cannot.
    auth_rows = cur.execute("""
        SELECT DISTINCT d.sku, s.retailer
        FROM distribution_log d
        JOIN stores s ON s.store_id = d.store_id
    """).fetchall()
    authorized: dict[str, set[str]] = {}
    for sku, retailer in auth_rows:
        authorized.setdefault(sku, set()).add(retailer)

    # Earliest authorization month per (sku, retailer) — used to suppress
    # chargebacks dated before the SKU was first carried at that retailer.
    first_auth_rows = cur.execute("""
        SELECT d.sku, s.retailer, MIN(d.authorized_date)
        FROM distribution_log d JOIN stores s ON s.store_id = d.store_id
        GROUP BY d.sku, s.retailer
    """).fetchall()
    first_auth_month: dict[tuple[str, str], str] = {
        (sku, retailer): ad[:7]  # YYYY-MM
        for sku, retailer, ad in first_auth_rows if ad
    }

    products = cur.execute("""
        SELECT sku, gtin14, upc, case_length_in, case_width_in, case_height_in,
               brand_owner, country_of_origin
        FROM product_master
    """).fetchall()

    # Build per-SKU defect flags
    sku_defects: dict[str, set[str]] = {}
    for sku, gtin, upc, l, w, h, brand, country in products:
        flags = set()
        if gtin_invalid(gtin):
            flags.add("invalid_gtin")
        if upc_missing(upc):
            flags.add("missing_upc")
        if l is None or w is None or h is None:
            flags.add("missing_case_dims")
        if brand is None or str(brand).strip() == "":
            flags.add("missing_brand")
        if country is None or str(country).strip() == "":
            flags.add("missing_country")
        sku_defects[sku] = flags

    months = months_in_window()
    rows: list[tuple[str, str, str, float, str]] = []  # (month, retailer, reason, amount, sku)

    # Defect-driven chargebacks. A retailer can only chargeback a SKU it
    # actually carries (or carried), so cfg["retailers"] is filtered against
    # the SKU's authorization set before sampling. Months before the SKU's
    # first authorization at that retailer are also skipped.
    for sku, flags in sku_defects.items():
        sku_auth = authorized.get(sku, set())
        if not sku_auth:
            continue
        for defect in flags:
            cfg = DEFECT_RULES[defect]
            reason = cfg["reason"]
            for retailer, monthly_p, (lo, hi) in cfg["retailers"]:
                if retailer not in sku_auth:
                    continue
                pair_first = first_auth_month.get((sku, retailer))
                for m in months:
                    if pair_first is not None and m < pair_first:
                        continue
                    if rng.random() < monthly_p:
                        amount = round(rng.uniform(lo, hi), 2)
                        rows.append((m, retailer, reason, amount, sku))

    # Operational chargebacks for clean SKUs (no defects). Same authorization
    # and temporal filter — only retailers that actually carry the SKU can
    # issue a short-shipment / late-delivery deduction, and only after the
    # SKU is first authorized there.
    clean_skus = [s for s, f in sku_defects.items() if not f]
    for sku in clean_skus:
        sku_auth = authorized.get(sku, set())
        for retailer in OPERATIONAL_RETAILERS:
            if retailer not in sku_auth:
                continue
            pair_first = first_auth_month.get((sku, retailer))
            for m in months:
                if pair_first is not None and m < pair_first:
                    continue
                if rng.random() < OPERATIONAL_MONTHLY_PROB:
                    reason, (lo, hi) = rng.choice(OPERATIONAL_REASONS)
                    amount = round(rng.uniform(lo, hi), 2)
                    rows.append((m, retailer, reason, amount, sku))

    # Replace the chargebacks table
    cur.execute("DROP TABLE IF EXISTS chargebacks")
    cur.execute("""
        CREATE TABLE chargebacks (
            month    TEXT NOT NULL,
            retailer TEXT NOT NULL,
            reason   TEXT NOT NULL,
            amount   REAL NOT NULL,
            sku      TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX idx_cb_sku ON chargebacks(sku)")
    cur.execute("CREATE INDEX idx_cb_month ON chargebacks(month)")
    cur.executemany(
        "INSERT INTO chargebacks (month, retailer, reason, amount, sku) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()

    # Summary
    total = sum(r[3] for r in rows)
    n_months = len(months)
    annual = total * (12 / n_months)
    print(f"Inserted {len(rows):,} chargebacks across {n_months} months "
          f"({months[0]} to {months[-1]}).")
    print(f"Total amount: ${total:,.0f}")
    print(f"Annualized:   ${annual:,.0f}  (target $55,000-$75,000)\n")

    print("Chargebacks by reason:")
    by_reason = Counter()
    amt_by_reason: dict[str, float] = {}
    for m, ret, reason, amt, sku in rows:
        by_reason[reason] += 1
        amt_by_reason[reason] = amt_by_reason.get(reason, 0) + amt
    for reason, n in by_reason.most_common():
        print(f"  {reason:<25} {n:>4}  ${amt_by_reason[reason]:>9,.0f}")

    print("\nChargebacks by retailer:")
    by_retailer = Counter()
    amt_by_ret: dict[str, float] = {}
    for m, ret, reason, amt, sku in rows:
        by_retailer[ret] += 1
        amt_by_ret[ret] = amt_by_ret.get(ret, 0) + amt
    for ret, n in by_retailer.most_common():
        print(f"  {ret:<15} {n:>4}  ${amt_by_ret[ret]:>9,.0f}")

    print("\nDefect-driven SKU summary:")
    n_skus_charged = len({r[4] for r in rows})
    n_clean_charged = len({r[4] for r in rows if not sku_defects[r[4]]})
    print(f"  SKUs with at least one chargeback: {n_skus_charged}")
    print(f"  Clean SKUs hit by operational charges: {n_clean_charged}")
    print(f"  Defect SKUs total: {sum(1 for f in sku_defects.values() if f)}")
    print(f"  Clean SKUs total:  {sum(1 for f in sku_defects.values() if not f)}")

    # Top 5 SKUs by chargeback amount — these should be the worst defect carriers
    print("\nTop 5 SKUs by chargeback total:")
    sku_totals: dict[str, float] = {}
    for m, ret, reason, amt, sku in rows:
        sku_totals[sku] = sku_totals.get(sku, 0) + amt
    for sku, amt in sorted(sku_totals.items(), key=lambda kv: -kv[1])[:5]:
        flags = ", ".join(sorted(sku_defects[sku])) or "no defects (operational only)"
        print(f"  {sku}  ${amt:>7,.0f}   defects: {flags}")

    con.close()


if __name__ == "__main__":
    main()
