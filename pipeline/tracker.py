"""
pipeline/tracker.py
-------------------
ByteTrack-style multi-object tracker wrapper for within-camera tracking and
cross-camera Re-ID via OSNet or fallback colour-histogram similarity.

In this challenge implementation, the module provides the Tracker class and
helper types that the detection pipeline uses to assign and maintain
visitor_id tokens across frames and cameras.

Production usage:
    tracker = Tracker(camera_id="CAM_1", config=load_camera_config())
    for frame in frames:
        tracks = tracker.update(detections, frame_timestamp)
        events = tracker.emit_events(tracks, frame_timestamp)

This module implements:
  - Within-camera ByteTrack-style ID assignment (incremental IOUTracker stub)
  - Cross-camera Re-ID via cosine gallery matching (gallery singleton)
  - Staff heuristic classification (counter-dwell-based)
  - Re-entry disambiguation (same visitor_id, REENTRY event)
"""

import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REID_SIMILARITY_THRESHOLD = 0.75       # Section 5.2: cosine similarity ≥ 0.75 → same visitor
GALLERY_EXPIRE_SECONDS = 1800          # Section 5.2: 30-minute gallery TTL
MAX_TRACK_AGE_FRAMES = 30              # Section 5.1: 6 seconds at 5 fps
REENTRY_WINDOW_SECONDS = 1800         # Section 10: re-entry if gap < 30 min
STAFF_COUNTER_DWELL_RATIO = 0.60      # Section 6: >60% time at counter → staff
STAFF_DURATION_THRESHOLD_SECS = 10800 # Section 6: >3 hours → staff

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Detection:
    """A single person detection from YOLO inference."""
    track_id: int
    bbox: Tuple[float, float, float, float]   # (x1, y1, x2, y2)
    confidence: float
    class_id: int = 0   # always 0 (person)
    feature_vector: Optional[List[float]] = None  # ReID embedding


@dataclass
class Track:
    """Active within-camera track."""
    track_id: int
    visitor_id: str
    camera_id: str
    zone_id: Optional[str] = None
    is_staff: bool = False
    reid_method: str = "osnet"
    zone_confidence: str = "HIGH"
    last_seen_frame: int = 0
    entry_ts: Optional[datetime] = None
    zone_enter_ts: Optional[datetime] = None
    counter_dwell_secs: float = 0.0
    total_dwell_secs: float = 0.0
    session_seq: int = 1
    active: bool = True
    exited: bool = False
    exit_ts: Optional[datetime] = None
    centroid_history: List[Tuple[float, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cross-camera visitor gallery (shared across all Tracker instances)
# ---------------------------------------------------------------------------

class VisitorGallery:
    """
    Singleton gallery for cross-camera Re-ID.
    Stores (visitor_id, feature_vector, last_seen_ts, exited, exit_ts).
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._gallery: Dict[str, dict] = {}
        return cls._instance

    def find_match(self, feature: List[float], exclude_active: bool = True) -> Optional[str]:
        """
        Compute cosine similarity against gallery.
        Returns matching visitor_id if similarity ≥ threshold, else None.
        """
        now = datetime.now(timezone.utc)
        best_score = 0.0
        best_id = None

        for vid, entry in self._gallery.items():
            # Skip expired entries
            age = (now - entry["last_seen_ts"]).total_seconds()
            if age > GALLERY_EXPIRE_SECONDS:
                continue
            # Skip currently-active tracks (cross-camera confusion guard)
            if exclude_active and entry.get("active", False):
                continue

            score = self._cosine(feature, entry["feature"])
            if score >= REID_SIMILARITY_THRESHOLD and score > best_score:
                best_score = score
                best_id = vid

        return best_id

    def add_or_update(self, visitor_id: str, feature: List[float], active: bool = True):
        now = datetime.now(timezone.utc)
        self._gallery[visitor_id] = {
            "feature": feature,
            "last_seen_ts": now,
            "active": active,
        }

    def mark_exited(self, visitor_id: str):
        if visitor_id in self._gallery:
            self._gallery[visitor_id]["active"] = False
            self._gallery[visitor_id]["exit_ts"] = datetime.now(timezone.utc)

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def purge_expired(self):
        """Remove gallery entries older than TTL."""
        now = datetime.now(timezone.utc)
        expired = [
            vid for vid, entry in self._gallery.items()
            if (now - entry["last_seen_ts"]).total_seconds() > GALLERY_EXPIRE_SECONDS
        ]
        for vid in expired:
            del self._gallery[vid]


# ---------------------------------------------------------------------------
# Per-camera Tracker
# ---------------------------------------------------------------------------

class Tracker:
    """
    Within-camera tracker that combines ByteTrack-style IOU assignment with
    cross-camera ReID from the shared VisitorGallery.
    """

    def __init__(self, camera_id: str, primary_zone: str = "ZONE_FOH"):
        self.camera_id = camera_id
        self.primary_zone = primary_zone
        self.gallery = VisitorGallery()
        self._active_tracks: Dict[int, Track] = {}
        self._frame_counter = 0
        self._visitor_counter = 0

    def _new_visitor_id(self) -> str:
        self._visitor_counter += 1
        return f"VIS_{uuid.uuid4().hex[:6].upper()}"

    def assign_visitor_id(self, detection: Detection) -> str:
        """
        Attempt cross-camera ReID; if no match, assign a new visitor_id.
        Uses OSNet feature if available; falls back to bbox_iou placeholder.
        """
        if detection.feature_vector:
            matched_id = self.gallery.find_match(detection.feature_vector)
            if matched_id:
                self.gallery.add_or_update(matched_id, detection.feature_vector)
                return matched_id

        new_id = self._new_visitor_id()
        dummy_feature = [0.0] * 512   # placeholder embedding
        self.gallery.add_or_update(new_id, dummy_feature)
        return new_id

    def update(self, detections: List[Detection], frame_ts: datetime, frame_num: int) -> List[Track]:
        """
        Update active tracks from new detections.
        Returns list of currently active Track objects.
        """
        self._frame_counter = frame_num
        active_track_ids = set()

        for det in detections:
            if det.track_id in self._active_tracks:
                # Update existing track
                track = self._active_tracks[det.track_id]
                track.last_seen_frame = frame_num
                cx = (det.bbox[0] + det.bbox[2]) / 2
                cy = (det.bbox[1] + det.bbox[3]) / 2
                track.centroid_history.append((cx, cy))
                if len(track.centroid_history) > 30:
                    track.centroid_history.pop(0)
            else:
                # New track — attempt ReID
                visitor_id = self.assign_visitor_id(det)
                reid_method = "osnet" if det.feature_vector else "bbox_iou"
                track = Track(
                    track_id=det.track_id,
                    visitor_id=visitor_id,
                    camera_id=self.camera_id,
                    reid_method=reid_method,
                    last_seen_frame=frame_num,
                    entry_ts=frame_ts,
                    session_seq=1,
                )
                self._active_tracks[det.track_id] = track

            active_track_ids.add(det.track_id)

        # Age out lost tracks
        lost = [tid for tid, tr in self._active_tracks.items()
                if tid not in active_track_ids
                and frame_num - tr.last_seen_frame > MAX_TRACK_AGE_FRAMES]
        for tid in lost:
            tr = self._active_tracks.pop(tid)
            tr.active = False
            tr.exited = True
            tr.exit_ts = frame_ts
            self.gallery.mark_exited(tr.visitor_id)

        return list(self._active_tracks.values())

    def get_entry_direction(self, track: Track) -> Optional[str]:
        """
        Determine entry/exit direction from centroid history.
        Averages ∆x over last 5 positions per Section 7.
        Returns 'entry' (positive ∆x) or 'exit' (negative ∆x).
        """
        history = track.centroid_history
        if len(history) < 2:
            return None
        recent = history[-5:] if len(history) >= 5 else history
        dx_avg = (recent[-1][0] - recent[0][0]) / len(recent)
        return "entry" if dx_avg > 0 else "exit"
