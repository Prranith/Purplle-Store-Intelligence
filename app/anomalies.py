import uuid
import json
from datetime import datetime, timezone, timedelta
from app.db import get_db_connection
from app.metrics import get_metrics_for_store, parse_iso
from app.heatmap import CANONICAL_ZONES

def get_anomalies_for_store(store_id: str) -> dict:
    """
    Evaluates rule-based anomalies for the store based on the active event stream.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    anomalies = []
    
    # Get current time as the latest event timestamp in the DB (for back-testing clip compatibility)
    cursor.execute("SELECT MAX(timestamp) FROM events WHERE store_id = ?", (store_id,))
    max_ts_str = cursor.fetchone()[0]
    
    if not max_ts_str:
        conn.close()
        return {
            "store_id": store_id,
            "anomalies": []
        }
        
    current_time = parse_iso(max_ts_str)
    
    # Define time thresholds relative to current_time
    thirty_mins_ago = (current_time - timedelta(minutes=30)).isoformat()
    ten_mins_ago = (current_time - timedelta(minutes=10)).isoformat()
    five_mins_ago = (current_time - timedelta(minutes=5)).isoformat()
    two_mins_ago = (current_time - timedelta(minutes=2)).isoformat()
    
    # 1. BILLING_QUEUE_SPIKE
    # WARN: queue_depth > 3 for > 2 minutes
    # CRIT: queue_depth > 5 for > 5 minutes
    # Fetch queue joins in the last 5 minutes
    cursor.execute("""
        SELECT timestamp, metadata_json FROM events
        WHERE store_id = ? AND event_type = 'BILLING_QUEUE_JOIN' AND is_staff = 0
        AND timestamp >= ?
        ORDER BY timestamp ASC
    """, (store_id, five_mins_ago))
    queue_joins = cursor.fetchall()
    
    high_q_5min = []
    high_q_2min = []
    
    for row in queue_joins:
        ts = parse_iso(row['timestamp'])
        meta = json.loads(row['metadata_json']) if row['metadata_json'] else {}
        q_depth = meta.get('queue_depth', 0) or 0
        
        if q_depth > 5:
            high_q_5min.append(ts)
        if q_depth > 3:
            high_q_2min.append(ts)
            
    # Check CRIT: if high queue > 5 happened across a duration of > 5 mins (or multiple occurrences in 5 mins)
    if len(high_q_5min) >= 2 and (high_q_5min[-1] - high_q_5min[0]).total_seconds() >= 240.0:
        anomalies.append({
            "anomaly_id": str(uuid.uuid4()),
            "type": "BILLING_QUEUE_SPIKE",
            "severity": "CRITICAL",
            "detected_at": current_time.isoformat(),
            "description": f"Critical queue depth spike: Cash Counter has had > 5 customers for over 5 minutes.",
            "suggested_action": "Urgent! Deploy backup cashier and open secondary POS register immediately."
        })
    elif len(high_q_2min) >= 2 and (high_q_2min[-1] - high_q_2min[0]).total_seconds() >= 100.0:
        anomalies.append({
            "anomaly_id": str(uuid.uuid4()),
            "type": "BILLING_QUEUE_SPIKE",
            "severity": "WARN",
            "detected_at": current_time.isoformat(),
            "description": "Queue depth reached 4 (threshold: 3) for over 2 minutes.",
            "suggested_action": "Deploy additional staff to billing counter to expedite checkout."
        })

    # 2. CONVERSION_DROP
    # conversion rate < 70% of 7-day average (baseline 0.55 -> threshold 0.385)
    # Let's compute today's metrics
    today_start = current_time.replace(hour=0, minute=0, second=0).isoformat()
    today_end = current_time.replace(hour=23, minute=59, second=59).isoformat()
    metrics = get_metrics_for_store(store_id, today_start, today_end)
    conv_rate = metrics.get("conversion_rate", 0.0)
    unique_visitors = metrics.get("unique_visitors", 0)
    
    # Only report conversion drop if we have a reasonable sample size
    if unique_visitors >= 5 and conv_rate < 0.385:
        anomalies.append({
            "anomaly_id": str(uuid.uuid4()),
            "type": "CONVERSION_DROP",
            "severity": "WARN",
            "detected_at": current_time.isoformat(),
            "description": f"Conversion rate dropped to {conv_rate:.1%} (7-day baseline: 55.0%).",
            "suggested_action": "Audit store layout and makeup demo engagement. Prompt floor managers to assist shoppers."
        })

    # 3. DEAD_ZONE
    # No ZONE_ENTER for a named zone in 30 minutes
    # Select zones visited in last 30 minutes
    cursor.execute("""
        SELECT DISTINCT zone_id FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL AND zone_id != 'ENTRY_EXIT'
        AND event_type = 'ZONE_ENTER' AND is_staff = 0
        AND timestamp >= ?
    """, (store_id, thirty_mins_ago))
    visited_zones = {row[0] for row in cursor.fetchall()}
    
    for zone in CANONICAL_ZONES:
        # FOH is the main open space, ignore it for dead zone triggers
        if zone == "ZONE_FOH":
            continue
        if zone not in visited_zones:
            anomalies.append({
                "anomaly_id": str(uuid.uuid4()),
                "type": "DEAD_ZONE",
                "severity": "INFO",
                "zone_id": zone,
                "detected_at": current_time.isoformat(),
                "description": f"No zone visits in last 30 minutes for {zone}.",
                "suggested_action": "Check zone display organization; consider adding active promotional signage or lighting."
            })

    # 4. EMPTY_STORE
    # No active visitor tracks for > 10 minutes
    cursor.execute("""
        SELECT COUNT(*) FROM events
        WHERE store_id = ? AND is_staff = 0
        AND timestamp >= ?
    """, (store_id, ten_mins_ago))
    recent_customer_events = cursor.fetchone()[0]
    
    if recent_customer_events == 0:
        anomalies.append({
            "anomaly_id": str(uuid.uuid4()),
            "type": "EMPTY_STORE",
            "severity": "INFO",
            "detected_at": current_time.isoformat(),
            "description": "No active customer tracks detected in the store for over 10 minutes.",
            "suggested_action": "Store appears empty. Keep storefront displays clean and optimized to attract foot traffic."
        })

    # 5. STALE_FEED
    # Last event for a camera > 10 minutes ago
    cursor.execute("""
        SELECT camera_id, MAX(timestamp) as last_ts FROM events
        WHERE store_id = ?
        GROUP BY camera_id
    """, (store_id,))
    camera_feeds = cursor.fetchall()
    
    for row in camera_feeds:
        cam_id = row['camera_id']
        cam_ts = parse_iso(row['last_ts'])
        age_seconds = (current_time - cam_ts).total_seconds()
        
        if age_seconds > 600.0:
            anomalies.append({
                "anomaly_id": str(uuid.uuid4()),
                "type": "STALE_FEED",
                "severity": "WARN",
                "detected_at": current_time.isoformat(),
                "description": f"Camera feed {cam_id} has not emitted events in over 10 minutes (last seen: {cam_ts.isoformat()}).",
                "suggested_action": f"Verify hardware connectivity and process status for {cam_id} streaming pipeline."
            })
            
    conn.close()
    return {
        "store_id": store_id,
        "anomalies": anomalies
    }
