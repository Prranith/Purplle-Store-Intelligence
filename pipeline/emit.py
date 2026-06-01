import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

def create_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: datetime,
    zone_id: Optional[str] = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.9,
    metadata: Optional[Dict[str, Any]] = None,
    reid_method: str = "osnet",
    zone_confidence: str = "HIGH",
    session_seq: int = 1,
    track_id: int = 1,
    frame_number: int = 1
) -> Dict[str, Any]:
    """
    Constructs a schema-compliant event payload dictionary.
    Follows the canonical event schema from the Master Implementation Blueprint.
    All required fields are populated; metadata follows the exact spec.
    """
    event_id = str(uuid.uuid4())
    
    # Format timezone-aware ISO string
    ts_str = timestamp.isoformat()
    # Convert +00:00 UTC to Z notation for readability
    ts_str = ts_str.replace("+00:00", "Z")
    
    # Build canonical metadata block - every field must be present
    event_metadata = {
        "queue_depth": None,          # int; set for BILLING_QUEUE_JOIN only
        "group_id": None,             # UUID; set for group-entry members
        "session_seq": session_seq,   # ordinal in visitor session
        "reid_method": reid_method,   # "osnet" | "histogram" | "bbox_iou"
        "zone_confidence": zone_confidence,  # "HIGH" | "LOW"
        "low_confidence": confidence < 0.5,  # true if detection conf < 0.5
        "track_id": track_id,         # internal ByteTrack ID (debug)
        "frame_number": frame_number  # source frame (debug)
    }
    
    # Override/extend with caller-supplied metadata
    if metadata:
        event_metadata.update(metadata)
    
    payload = {
        "event_id": event_id,
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": ts_str,
        "zone_id": zone_id,          # null for ENTRY/EXIT
        "dwell_ms": dwell_ms,        # 0 for instantaneous events
        "is_staff": is_staff,        # classifier output
        "confidence": round(float(confidence), 2),   # YOLOv8 detection confidence
        "metadata": event_metadata
    }
    
    return payload
