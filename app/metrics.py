from datetime import datetime, timezone, timedelta
import json
from app.db import get_db_connection

def parse_iso(ts_str: str) -> datetime:
    """
    Parses ISO-8601 timestamps, handling UTC 'Z' or offset formats safely.
    """
    cleaned = ts_str.replace("Z", "+00:00")
    # SQLite datetime formats might have spaces instead of T, handle them
    if " " in cleaned and "T" not in cleaned:
        cleaned = cleaned.replace(" ", "T")
    return datetime.fromisoformat(cleaned)

def get_metrics_for_store(store_id: str, start_time: str, end_time: str) -> dict:
    """
    Computes all retail analytics metrics for the store within the given time window.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Check if we have any data
    cursor.execute("""
        SELECT COUNT(*) FROM events 
        WHERE store_id = ? AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    total_events = cursor.fetchone()[0]
    
    if total_events == 0:
        conn.close()
        return {
            "store_id": store_id,
            "window": {"from": start_time, "to": end_time},
            "unique_visitors": 0,
            "conversion_rate": 0.0,
            "avg_dwell_by_zone": {},
            "queue_depth_current": 0,
            "abandonment_rate": 0.0,
            "dark_conversions": 0,
            "data_confidence": "NO_DATA"
        }
        
    # 2. Get unique visitor sessions
    cursor.execute("""
        SELECT DISTINCT visitor_id FROM events
        WHERE store_id = ? AND event_type = 'ENTRY' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    unique_visitors_set = {row[0] for row in cursor.fetchall()}
    unique_visitors_count = len(unique_visitors_set)
    
    # Fallback: if no ENTRY events, grab any non-staff visitor seen in events
    if unique_visitors_count == 0:
        cursor.execute("""
            SELECT DISTINCT visitor_id FROM events
            WHERE store_id = ? AND is_staff = 0
            AND timestamp BETWEEN ? AND ?
        """, (store_id, start_time, end_time))
        unique_visitors_set = {row[0] for row in cursor.fetchall()}
        unique_visitors_count = len(unique_visitors_set)

    # 3. Calculate Conversions (Python-based timezone robust correlation)
    # Get all CASH COUNTER visits
    cursor.execute("""
        SELECT visitor_id, timestamp FROM events
        WHERE store_id = ? AND zone_id = 'ZONE_CASH_COUNTER' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    cash_counter_visits = cursor.fetchall()
    
    # Get all POS transactions in the window
    cursor.execute("""
        SELECT order_id, timestamp, total_amount FROM pos_transactions
        WHERE store_id = ? AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    transactions = cursor.fetchall()
    
    converted_visitors = set()
    matched_txn_ids = set()
    
    # Pre-parse timestamps
    parsed_visits = []
    for row in cash_counter_visits:
        parsed_visits.append((row['visitor_id'], parse_iso(row['timestamp'])))
        
    parsed_txns = []
    for row in transactions:
        parsed_txns.append((row['order_id'], parse_iso(row['timestamp'])))
        
    # Correlate: Visit starts t_enter. Transaction is within [t_enter - 30s, t_enter + 300s]
    for visitor_id, t_visit in parsed_visits:
        for txn_id, t_txn in parsed_txns:
            diff = (t_txn - t_visit).total_seconds()
            if -30.0 <= diff <= 300.0:
                converted_visitors.add(visitor_id)
                matched_txn_ids.add(txn_id)
                
    # Calculate Conversion Rate
    conversion_rate = 0.0
    if unique_visitors_count > 0:
        # Number of unique converted visitor sessions / Total unique visitor sessions
        conversion_rate = round(len(converted_visitors) / unique_visitors_count, 4)
        
    # Calculate Dark Conversions: POS transactions without matching visitor
    dark_conversions = max(0, len(parsed_txns) - len(matched_txn_ids))
    
    # 4. Average dwell time by zone (excluding staff)
    cursor.execute("""
        SELECT zone_id, dwell_ms FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL AND is_staff = 0
        AND event_type IN ('ZONE_EXIT', 'ZONE_DWELL')
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    dwell_rows = cursor.fetchall()
    
    zone_dwells = {}
    zone_counts = {}
    for row in dwell_rows:
        z_id = row['zone_id']
        d_ms = row['dwell_ms']
        zone_dwells[z_id] = zone_dwells.get(z_id, 0) + d_ms
        zone_counts[z_id] = zone_counts.get(z_id, 0) + 1
        
    avg_dwell_by_zone = {}
    for z_id in zone_dwells:
        avg_dwell_by_zone[z_id] = int(zone_dwells[z_id] / zone_counts[z_id])

    # 5. Current queue depth: count non-staff cash counter entries that haven't exited
    # Or, look at the last BILLING_QUEUE_JOIN event's queue_depth, or do active count in last 5 minutes.
    # To be fully real-time and simple, look at the latest event with event_type 'ZONE_ENTER' / 'ZONE_EXIT'
    # in the cash counter zone to maintain state, or count how many visitor_ids are currently active in cash counter.
    # Let's count visitors whose most recent event in the cash counter was an enter/dwell and happened in last 2 mins.
    # Alternatively, get the most recent event of type BILLING_QUEUE_JOIN or cash counter active visitor count.
    # Let's find unique visitor_ids whose last cash counter event is ZONE_ENTER/ZONE_DWELL in the last 2 minutes.
    two_mins_ago = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    cursor.execute("""
        SELECT COUNT(DISTINCT visitor_id) FROM events
        WHERE store_id = ? AND zone_id = 'ZONE_CASH_COUNTER' AND is_staff = 0
        AND timestamp >= ?
    """, (store_id, two_mins_ago))
    queue_depth_current = cursor.fetchone()[0]

    # 6. Queue abandonment rate
    # Abandonment Rate = Abandon events / (Join events or Cash Counter Visits)
    cursor.execute("""
        SELECT COUNT(*) FROM events
        WHERE store_id = ? AND event_type = 'BILLING_QUEUE_ABANDON' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    abandon_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM events
        WHERE store_id = ? AND event_type = 'BILLING_QUEUE_JOIN' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
    """, (store_id, start_time, end_time))
    join_count = cursor.fetchone()[0]
    
    abandonment_rate = 0.0
    if join_count > 0:
        abandonment_rate = round(abandon_count / join_count, 4)
    elif abandon_count > 0:
        # Fallback to cash counter entry if join count is missing
        cursor.execute("""
            SELECT COUNT(DISTINCT visitor_id) FROM events
            WHERE store_id = ? AND zone_id = 'ZONE_CASH_COUNTER' AND is_staff = 0
            AND timestamp BETWEEN ? AND ?
        """, (store_id, start_time, end_time))
        cc_count = cursor.fetchone()[0]
        if cc_count > 0:
            abandonment_rate = round(abandon_count / cc_count, 4)

    # 7. Hourly visitor breakdown
    cursor.execute("""
        SELECT substr(timestamp, 12, 2) as hour, COUNT(DISTINCT visitor_id) as visitors
        FROM events
        WHERE store_id = ? AND event_type = 'ENTRY' AND is_staff = 0
        AND timestamp BETWEEN ? AND ?
        GROUP BY hour
        ORDER BY hour
    """, (store_id, start_time, end_time))
    hourly_rows = cursor.fetchall()
    hourly_breakdown = [
        {"hour": f"{row['hour']}:00", "visitors": row['visitors']}
        for row in hourly_rows
    ]

    # Peak hour
    peak_hour = None
    if hourly_breakdown:
        peak = max(hourly_breakdown, key=lambda x: x["visitors"])
        peak_hour = peak["hour"]

    # 8. Data confidence
    data_confidence = "HIGH"
    if unique_visitors_count < 20:
        data_confidence = "LOW"

    conn.close()

    return {
        "store_id": store_id,
        "window": {"from": start_time, "to": end_time},
        "unique_visitors": unique_visitors_count,
        "conversion_rate": conversion_rate,
        "avg_dwell_by_zone": avg_dwell_by_zone,
        "queue_depth_current": queue_depth_current,
        "abandonment_rate": abandonment_rate,
        "dark_conversions": dark_conversions,
        "hourly_breakdown": hourly_breakdown,
        "peak_hour": peak_hour,
        "data_confidence": data_confidence
    }

