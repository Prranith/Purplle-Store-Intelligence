from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime

class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None       # int; set for BILLING_QUEUE_JOIN only
    group_id: Optional[str] = None          # UUID; set for group-entry members
    session_seq: Optional[int] = None       # ordinal in visitor session
    reid_method: Optional[str] = None       # "osnet" | "histogram" | "bbox_iou"
    zone_confidence: Optional[str] = None   # "HIGH" | "LOW" (homography quality)
    low_confidence: Optional[bool] = None   # true if detection confidence < 0.5
    track_id: Optional[int] = None          # internal ByteTrack ID (debug)
    frame_number: Optional[int] = None      # source frame number (debug)

class Event(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: str # ISO-8601 string
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float
    metadata: Optional[EventMetadata] = Field(default_factory=EventMetadata)

    @field_validator("event_id")
    @classmethod
    def validate_uuid(cls, v):
        try:
            UUID(v)
            return v
        except ValueError:
            raise ValueError("event_id must be a valid UUID v4")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v):
        valid_types = {
            "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
            "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
        }
        if v not in valid_types:
            raise ValueError(f"invalid event_type: {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v):
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError:
            raise ValueError("timestamp must be in valid ISO-8601 format")

class IngestRequest(BaseModel):
    events: list[Event]
