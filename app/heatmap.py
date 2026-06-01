import json
import os
from app.db import get_db_connection
from app.zone_revenue import get_zone_revenue

# Load zones config to get categories
ZONES_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "pipeline", "config", "zones.json")
ZONES_DATA = {}
try:
    with open(ZONES_CONFIG_PATH, "r") as f:
        config = json.load(f)
        for k, v in config.items():
            if not k.startswith("_"):
                ZONES_DATA[k] = v
except Exception:
    pass

CANONICAL_ZONES = [
    "ZONE_EB_KOREAN", "ZONE_THE_FACE_SHOP", "ZONE_GOOD_VIBES", "ZONE_DERMDOC",
    "ZONE_MINIMALIST", "ZONE_AQUALOGICA", "ZONE_LAKME_SKIN", "ZONE_ACCESSORIES",
    "ZONE_FRAGRANCE", "ZONE_NAIL", "ZONE_FOH", "ZONE_MAKEUP_UNIT", "ZONE_CASH_COUNTER",
    "ZONE_PMU", "ZONE_MAYBELLINE", "ZONE_FACES_CANADA", "ZONE_LAKME_MAKEUP",
    "ZONE_COLORBAR_SUGAR", "ZONE_SWISS_BEAUTY", "ZONE_RENEE_NY_BAE",
    "ZONE_ALPS_GOODNESS", "ZONE_STREAX", "ZONE_BACKLIT"
]

def get_heatmap_for_store(store_id: str, start_time: str, end_time: str) -> dict:
    """
    Computes visit frequency, average dwell time, normalized scores, category, and revenue contribution per zone.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get visit counts (unique visitor sessions per zone)
    cursor.execute("""
        SELECT zone_id, COUNT(DISTINCT visitor_id) as visits
        FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL AND zone_id != 'ENTRY_EXIT' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
        GROUP BY zone_id
    """, (store_id, start_time, end_time))
    visit_rows = {row['zone_id']: row['visits'] for row in cursor.fetchall()}
    
    # Get average dwell times per zone
    cursor.execute("""
        SELECT zone_id, SUM(dwell_ms) as total_dwell, COUNT(*) as count
        FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL AND zone_id != 'ENTRY_EXIT' AND is_staff = 0
        AND event_type IN ('ZONE_EXIT', 'ZONE_DWELL')
        AND timestamp BETWEEN ? AND ?
        GROUP BY zone_id
    """, (store_id, start_time, end_time))
    dwell_rows = cursor.fetchall()
    
    avg_dwells = {}
    for row in dwell_rows:
        z_id = row['zone_id']
        total = row['total_dwell']
        cnt = row['count']
        avg_dwells[z_id] = int(total / cnt) if cnt > 0 else 0
        
    # Get zone revenue data
    try:
        revenue_data = get_zone_revenue(store_id, start_time, end_time)
        revenue_map = {z["zone_id"]: z["revenue_contribution_pct"] for z in revenue_data.get("zones", [])}
    except Exception:
        revenue_map = {}

    # Find max visit count for normalization
    max_visits = max(visit_rows.values()) if visit_rows else 0
    
    zones_list = []
    for zone_id in CANONICAL_ZONES:
        visit_count = visit_rows.get(zone_id, 0)
        avg_dwell = avg_dwells.get(zone_id, 0)
        
        # Normalization: normalised_score = round(visit_count / max_visit_count * 100)
        normalised_score = 0
        if max_visits > 0:
            normalised_score = round((visit_count / max_visits) * 100)
            
        # data_confidence is LOW if visit_count < 20 in that window
        data_confidence = "HIGH" if visit_count >= 20 else "LOW"
        
        category = ZONES_DATA.get(zone_id, {}).get("category", "Unknown")
        revenue_pct = revenue_map.get(zone_id, 0.0)

        zones_list.append({
            "zone_id": zone_id,
            "category": category,
            "visit_count": visit_count,
            "avg_dwell_ms": avg_dwell,
            "normalised_score": normalised_score,
            "revenue_contribution_pct": revenue_pct,
            "data_confidence": data_confidence
        })
        
    conn.close()
    
    return {
        "store_id": store_id,
        "zones": zones_list
    }

