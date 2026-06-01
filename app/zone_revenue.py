"""
app/zone_revenue.py
-------------------
Zone-to-revenue attribution: joins CCTV visitor zone data with POS transaction
data to show which product zones drive the most conversions and GMV.

This is the key differentiator endpoint — it answers the business question:
"Which shelf/brand areas are most valuable to the store?"
"""

from app.db import get_db_connection
from app.metrics import parse_iso

# Maps POS brand_name (lowercase) → canonical zone_id
BRAND_TO_ZONE = {
    "faces canada":     "ZONE_FACES_CANADA",
    "maybelline":       "ZONE_MAYBELLINE",
    "lakme":            "ZONE_LAKME_MAKEUP",
    "swiss beauty":     "ZONE_SWISS_BEAUTY",
    "ny bae":           "ZONE_RENEE_NY_BAE",
    "alps goodness":    "ZONE_ALPS_GOODNESS",
    "dermdoc":          "ZONE_DERMDOC",
    "good vibes":       "ZONE_GOOD_VIBES",
    "garnier":          "ZONE_LAKME_SKIN",
    "foxtale":          "ZONE_MINIMALIST",
    "minimalist":       "ZONE_MINIMALIST",
    "purplle":          "ZONE_ACCESSORIES",
    "carmesi":          "ZONE_ACCESSORIES",
    "gubb":             "ZONE_ACCESSORIES",
    "juicy chemistry":  "ZONE_GOOD_VIBES",
    "beauty of joseon": "ZONE_EB_KOREAN",
    "cosrx":            "ZONE_EB_KOREAN",
    "neutrogena":       "ZONE_DERMDOC",
    "bare anatomy":     "ZONE_MINIMALIST",
    "aqualogica":       "ZONE_AQUALOGICA",
    "cuffs n lashes":   "ZONE_PMU",
    "the face shop":    "ZONE_THE_FACE_SHOP",
    "good vibes":       "ZONE_GOOD_VIBES",
}

# Department → zone for department-level mapping
DEP_TO_ZONE = {
    "makeup":         "ZONE_MAKEUP_UNIT",
    "skin":           "ZONE_GOOD_VIBES",
    "fragrance":      "ZONE_FRAGRANCE",
    "hair":           "ZONE_STREAX",
    "bath-and-body":  "ZONE_GOOD_VIBES",
    "personal-care":  "ZONE_ACCESSORIES",
    "nail":           "ZONE_NAIL",
}


def get_zone_revenue(store_id: str, start_time: str, end_time: str) -> dict:
    """
    Computes per-zone revenue attribution by correlating:
    1. Which zones a visitor browsed (from CCTV events)
    2. Which brands/departments they purchased (from POS transactions)
    3. The GMV and conversion rate per zone

    This directly answers: "Which shelf area drives the most revenue?"
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # -----------------------------------------------------------------------
    # Step 1: Get all POS transactions with brand/dep info in the window
    # -----------------------------------------------------------------------
    cursor.execute("""
        SELECT order_id, timestamp, total_amount, brand_name, dep_name, matched_visitor
        FROM pos_transactions
        WHERE store_id = ? AND timestamp BETWEEN ? AND ?
        ORDER BY timestamp
    """, (store_id, start_time, end_time))
    transactions = cursor.fetchall()

    if not transactions:
        conn.close()
        return {
            "store_id": store_id,
            "window": {"from": start_time, "to": end_time},
            "zones": [],
            "total_gmv_inr": 0.0,
            "data_note": "No POS transactions loaded. Use POST /admin/load-pos to load the CSV."
        }

    # -----------------------------------------------------------------------
    # Step 2: Map each transaction to its likely zone via brand/dep
    # -----------------------------------------------------------------------
    zone_txns: dict = {}   # zone_id → list of (order_id, amount)

    for txn in transactions:
        brand = (txn["brand_name"] or "").lower().strip()
        dep = (txn["dep_name"] or "").lower().strip()
        amount = float(txn["total_amount"] or 0)

        zone_id = BRAND_TO_ZONE.get(brand) or DEP_TO_ZONE.get(dep) or "ZONE_MAKEUP_UNIT"

        if zone_id not in zone_txns:
            zone_txns[zone_id] = {"orders": set(), "total_gmv": 0.0}
        zone_txns[zone_id]["orders"].add(txn["order_id"])
        zone_txns[zone_id]["total_gmv"] += amount

    # -----------------------------------------------------------------------
    # Step 3: Get visitor counts per zone from CCTV events
    # -----------------------------------------------------------------------
    cursor.execute("""
        SELECT zone_id, COUNT(DISTINCT visitor_id) as visitors
        FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL
        AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
        AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
        GROUP BY zone_id
    """, (store_id, start_time, end_time))
    zone_visitors = {row["zone_id"]: row["visitors"] for row in cursor.fetchall()}

    # -----------------------------------------------------------------------
    # Step 4: Get average dwell per zone
    # -----------------------------------------------------------------------
    cursor.execute("""
        SELECT zone_id, AVG(dwell_ms) as avg_dwell
        FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL AND is_staff = 0
        AND event_type IN ('ZONE_EXIT', 'ZONE_DWELL') AND dwell_ms > 0
        AND timestamp BETWEEN ? AND ?
        GROUP BY zone_id
    """, (store_id, start_time, end_time))
    zone_dwells = {row["zone_id"]: int(row["avg_dwell"]) for row in cursor.fetchall()}

    # -----------------------------------------------------------------------
    # Step 5: Build enriched zone revenue response
    # -----------------------------------------------------------------------
    total_gmv = sum(z["total_gmv"] for z in zone_txns.values())
    all_zones = sorted(set(list(zone_txns.keys()) + list(zone_visitors.keys())))

    zone_results = []
    for zone_id in all_zones:
        txn_data = zone_txns.get(zone_id, {"orders": set(), "total_gmv": 0.0})
        visitors = zone_visitors.get(zone_id, 0)
        order_count = len(txn_data["orders"])
        gmv = txn_data["total_gmv"]
        avg_dwell = zone_dwells.get(zone_id, 0)

        # Conversion rate for this zone
        zone_cr = round(order_count / visitors, 4) if visitors > 0 else 0.0
        avg_basket = round(gmv / order_count, 2) if order_count > 0 else 0.0
        revenue_pct = round(gmv / total_gmv * 100, 1) if total_gmv > 0 else 0.0

        zone_results.append({
            "zone_id": zone_id,
            "visitors": visitors,
            "orders": order_count,
            "conversion_rate": zone_cr,
            "total_gmv_inr": round(gmv, 2),
            "avg_basket_inr": avg_basket,
            "avg_dwell_ms": avg_dwell,
            "revenue_contribution_pct": revenue_pct
        })

    # Sort by total GMV descending
    zone_results.sort(key=lambda z: z["total_gmv_inr"], reverse=True)

    conn.close()

    return {
        "store_id": store_id,
        "window": {"from": start_time, "to": end_time},
        "zones": zone_results,
        "total_gmv_inr": round(total_gmv, 2),
        "total_orders": len({txn["order_id"] for txn in transactions})
    }
