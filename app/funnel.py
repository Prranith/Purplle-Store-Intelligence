from datetime import datetime
from app.db import get_db_connection
from app.metrics import parse_iso

def get_funnel_for_store(store_id: str, start_time: str, end_time: str) -> dict:
    """
    Computes conversion funnel counts and drop-off percentages:
    ENTRY -> ZONE_VISIT -> BILLING_QUEUE -> PURCHASE
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Total entry sessions
    cursor.execute("""
        SELECT DISTINCT visitor_id FROM events
        WHERE store_id = ? AND event_type = 'ENTRY' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    entry_visitors = {row[0] for row in cursor.fetchall()}
    entry_count = len(entry_visitors)
    
    # Fallback to any visitor observed in the time window
    if entry_count == 0:
        cursor.execute("""
            SELECT DISTINCT visitor_id FROM events
            WHERE store_id = ? AND is_staff = 0
            AND timestamp BETWEEN ? AND ?
        """, (store_id, start_time, end_time))
        entry_visitors = {row[0] for row in cursor.fetchall()}
        entry_count = len(entry_visitors)

    # 2. Zone visits: visitors who entered at least one named zone (excluding ENTRY/EXIT)
    cursor.execute("""
        SELECT DISTINCT visitor_id FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL AND zone_id != 'ENTRY_EXIT' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    zone_visitors = {row[0] for row in cursor.fetchall()}
    # Keep only those who also had entry sessions (or if entry was fallback, intersect)
    zone_visitors = zone_visitors.intersection(entry_visitors)
    zone_count = len(zone_visitors)

    # 3. Billing Queue: visitors who entered/joined Cash Counter
    cursor.execute("""
        SELECT DISTINCT visitor_id FROM events
        WHERE store_id = ? AND zone_id = 'ZONE_CASH_COUNTER' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    queue_visitors = {row[0] for row in cursor.fetchall()}
    queue_visitors = queue_visitors.intersection(zone_visitors)
    queue_count = len(queue_visitors)

    # 4. Purchases: visitors who had POS match
    # Get all CASH COUNTER visits for queue visitors
    cursor.execute("""
        SELECT visitor_id, timestamp FROM events
        WHERE store_id = ? AND zone_id = 'ZONE_CASH_COUNTER' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    cc_visits = cursor.fetchall()
    
    cursor.execute("""
        SELECT order_id, timestamp FROM pos_transactions
        WHERE store_id = ? AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    txns = cursor.fetchall()
    
    purchase_visitors = set()
    
    # Pre-parse timestamps
    parsed_visits = [(row['visitor_id'], parse_iso(row['timestamp'])) for row in cc_visits]
    parsed_txns = [(row['order_id'], parse_iso(row['timestamp'])) for row in txns]
    
    for visitor_id, t_visit in parsed_visits:
        if visitor_id not in queue_visitors:
            continue
        for txn_id, t_txn in parsed_txns:
            diff = (t_txn - t_visit).total_seconds()
            if -30.0 <= diff <= 300.0:
                purchase_visitors.add(visitor_id)
                break
                
    purchase_count = len(purchase_visitors)

    # Calculate drop-off percentages
    # stage 1: ENTRY
    drop_entry = 0.0
    
    # stage 2: ZONE_VISIT
    drop_zone = 0.0
    if entry_count > 0:
        drop_zone = round((entry_count - zone_count) / entry_count * 100, 2)
        
    # stage 3: BILLING_QUEUE
    drop_queue = 0.0
    if zone_count > 0:
        drop_queue = round((zone_count - queue_count) / zone_count * 100, 2)
        
    # stage 4: PURCHASE
    drop_purchase = 0.0
    if queue_count > 0:
        drop_purchase = round((queue_count - purchase_count) / queue_count * 100, 2)

    conn.close()

    return {
        "store_id": store_id,
        "funnel": [
            {"stage": "ENTRY", "count": entry_count, "drop_pct": drop_entry},
            {"stage": "ZONE_VISIT", "count": zone_count, "drop_pct": drop_zone},
            {"stage": "BILLING_QUEUE", "count": queue_count, "drop_pct": drop_queue},
            {"stage": "PURCHASE", "count": purchase_count, "drop_pct": drop_purchase}
        ],
        "session_unit": True,
        "reentry_excluded": True
    }
