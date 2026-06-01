from datetime import datetime, timezone, timedelta
from app.db import get_db_connection
from app.metrics import parse_iso

START_TIME = datetime.now(timezone.utc)

def get_health_status() -> dict:
    """
    Computes system liveness diagnostics and stale camera feed checks.
    """
    uptime = int((datetime.now(timezone.utc) - START_TIME).total_seconds())
    
    db_connected = False
    stores_diagnostics = {}
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Test connection
        cursor.execute("SELECT 1")
        cursor.fetchone()
        db_connected = True
        
        # Query distinct stores
        cursor.execute("SELECT DISTINCT store_id FROM events")
        store_ids = [row[0] for row in cursor.fetchall()]
        
        # If no stores are in the DB, mock ST1008 placeholder so the schema is visible
        if not store_ids:
            store_ids = ["ST1008"]
            
        for store_id in store_ids:
            # Query last global event timestamp for the store
            cursor.execute("SELECT MAX(timestamp) FROM events WHERE store_id = ?", (store_id,))
            last_global_ts = cursor.fetchone()[0]
            
            if not last_global_ts:
                stores_diagnostics[store_id] = {
                    "last_event_ts": None,
                    "cameras": {}
                }
                continue
                
            ref_time = parse_iso(last_global_ts)
            
            # Query cameras for this store
            cursor.execute("""
                SELECT camera_id, MAX(timestamp) as last_ts FROM events
                WHERE store_id = ?
                GROUP BY camera_id
            """, (store_id,))
            cam_rows = cursor.fetchall()
            
            cameras_diag = {}
            for row in cam_rows:
                cam_id = row['camera_id']
                cam_ts_str = row['last_ts']
                cam_ts = parse_iso(cam_ts_str)
                
                # Camera is stale if its latest event is > 10 minutes older than the global latest event
                age_seconds = (ref_time - cam_ts).total_seconds()
                stale = age_seconds > 600.0
                
                cameras_diag[cam_id] = {
                    "last_event_ts": cam_ts_str,
                    "stale": stale
                }
                if stale:
                    cameras_diag[cam_id]["reason"] = "STALE_FEED"
                    
            stores_diagnostics[store_id] = {
                "last_event_ts": last_global_ts,
                "cameras": cameras_diag
            }
            
        conn.close()
    except Exception as e:
        db_connected = False
        stores_diagnostics = {
            "ST1008": {
                "last_event_ts": None,
                "cameras": {},
                "error": str(e)
            }
        }
        
    status = "ok" if db_connected else "error"
    
    return {
        "status": status,
        "uptime_seconds": uptime,
        "db_connected": db_connected,
        "stores": stores_diagnostics
    }
