import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.db import get_db_connection
from app.models import Event

def ingest_events_batch(events_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Ingests a batch of events with validation, duplicate detection, and batch insert.
    Returns counts and detailed errors for rejected events.
    """
    if len(events_data) > 500:
        raise ValueError("Batch size exceeds limit of 500 events")

    conn = get_db_connection()
    cursor = conn.cursor()

    accepted = 0
    rejected = 0
    duplicate = 0
    errors = []

    # Get existing event_ids in the batch or DB to detect duplicates
    # For high safety, we query the DB or rely on SQLite's UNIQUE constraint.
    # We will insert events one by one or in small batches, catching errors.
    
    ingested_at = datetime.now(timezone.utc).isoformat()

    for idx, raw_event in enumerate(events_data):
        # Validate Pydantic model
        try:
            # First try parsing
            event = Event(**raw_event)
        except Exception as e:
            rejected += 1
            errors.append({
                "index": idx,
                "event_id": raw_event.get("event_id", "unknown"),
                "reason": str(e)
            })
            continue

        # Check if already exists in DB
        cursor.execute("SELECT 1 FROM events WHERE event_id = ?", (event.event_id,))
        if cursor.fetchone():
            duplicate += 1
            continue

        # Insert event
        try:
            metadata_json = json.dumps(event.metadata.model_dump()) if event.metadata else None
            
            cursor.execute("""
                INSERT INTO events (
                    event_id, store_id, camera_id, visitor_id, event_type,
                    timestamp, zone_id, dwell_ms, is_staff, confidence,
                    metadata_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.store_id,
                event.camera_id,
                event.visitor_id,
                event.event_type,
                event.timestamp,
                event.zone_id,
                event.dwell_ms,
                1 if event.is_staff else 0,
                event.confidence,
                metadata_json,
                ingested_at
            ))
            accepted += 1
        except Exception as e:
            rejected += 1
            errors.append({
                "index": idx,
                "event_id": event.event_id,
                "reason": f"Database insertion failed: {str(e)}"
            })

    conn.commit()
    conn.close()

    return {
        "accepted": accepted,
        "rejected": rejected,
        "duplicate": duplicate,
        "errors": errors
    }
