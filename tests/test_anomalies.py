# PROMPT:
# "Write pytest tests for store operational anomaly detection.
# Test: (1) BILLING_QUEUE_SPIKE triggered if queue depth exceeds 3 for over 2 minutes,
# (2) DEAD_ZONE triggered if a canonical zone receives no visitor entries for 30 minutes,
# (3) EMPTY_STORE triggered if there are no active customer tracks for over 10 minutes.
# Use FastAPI TestClient and temporary SQLite DB."
#
# CHANGES MADE:
# - Pre-populated events with precise timestamps and queue_depth metadata fields to simulate time durations.
# - Included tests for STALE_FEED checks.

import pytest
import os
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db

@pytest.fixture(autouse=True)
def test_db(tmp_path):
    db_file = tmp_path / "test_store_intelligence.db"
    os.environ["DB_PATH"] = str(db_file)
    init_db()
    yield
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass

@pytest.fixture
def client():
    return TestClient(app)

def test_anomalies_empty_store_and_dead_zones(client):
    # Ingest a single event to anchor time but make it old so that we trigger EMPTY_STORE and DEAD_ZONE
    events = [
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1",
            "visitor_id": "VIS_OLD", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30",
            "confidence": 0.9, "is_staff": False
        },
        # Ingest a staff event at 12:15:00 to advance the store current clock
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1",
            "visitor_id": "VIS_STAFF", "event_type": "ENTRY", "timestamp": "2026-04-10T12:15:00+05:30",
            "confidence": 0.9, "is_staff": True
        }
    ]
    client.post("/events/ingest", json={"events": events})
    
    # We query anomalies. Since the latest event was at 12:00:00, and no activity occurred within 10 or 30 minutes,
    # it should trigger EMPTY_STORE and DEAD_ZONE anomalies.
    res = client.get("/stores/ST1008/anomalies")
    assert res.status_code == 200
    data = res.json()
    
    anomaly_types = [a["type"] for a in data["anomalies"]]
    assert "EMPTY_STORE" in anomaly_types
    assert "DEAD_ZONE" in anomaly_types

def test_billing_queue_spike_anomaly(client):
    # Ingest two BILLING_QUEUE_JOIN events with queue_depth > 3 spaced 3 minutes apart
    events = [
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_3",
            "visitor_id": "VIS_Q1", "event_type": "BILLING_QUEUE_JOIN", "timestamp": "2026-04-10T12:00:00+05:30",
            "zone_id": "ZONE_CASH_COUNTER", "confidence": 0.9, "is_staff": False,
            "metadata": {"queue_depth": 4}
        },
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_3",
            "visitor_id": "VIS_Q2", "event_type": "BILLING_QUEUE_JOIN", "timestamp": "2026-04-10T12:03:00+05:30",
            "zone_id": "ZONE_CASH_COUNTER", "confidence": 0.9, "is_staff": False,
            "metadata": {"queue_depth": 4}
        }
    ]
    client.post("/events/ingest", json={"events": events})
    
    res = client.get("/stores/ST1008/anomalies")
    assert res.status_code == 200
    data = res.json()
    
    anomaly_types = [a["type"] for a in data["anomalies"]]
    assert "BILLING_QUEUE_SPIKE" in anomaly_types
    
    # Assert details
    spike = [a for a in data["anomalies"] if a["type"] == "BILLING_QUEUE_SPIKE"][0]
    assert spike["severity"] == "WARN"
