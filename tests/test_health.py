# PROMPT:
# "Write pytest tests for store system health diagnostics.
# Test: (1) GET /health returns DB connected liveness and uptime,
# (2) DB disconnection triggers HTTP 503 Service Unavailable,
# (3) stale feeds flagged if camera lag exceeds 10 minutes.
# Use FastAPI TestClient and temporary SQLite DB."
#
# CHANGES MADE:
# - Simulating database connection failure by mocking get_db_connection or corrupting DB path.
# - Confirmed correct status code propagation in global exception middleware.

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

def test_health_check_liveness(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["db_connected"] is True
    assert "uptime_seconds" in data

def test_health_stale_feed_detection(client):
    # Ingest event for CAM_1 (at 12:00:00) and CAM_2 (at 12:15:00)
    # Since CAM_1 is 15 minutes older than CAM_2 (the latest global event), CAM_1 should be flagged as stale
    events = [
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1",
            "visitor_id": "VIS_1", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30",
            "confidence": 0.9, "is_staff": False
        },
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_2",
            "visitor_id": "VIS_2", "event_type": "ENTRY", "timestamp": "2026-04-10T12:15:00+05:30",
            "confidence": 0.9, "is_staff": False
        }
    ]
    client.post("/events/ingest", json={"events": events})
    
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    
    cameras = data["stores"]["ST1008"]["cameras"]
    assert cameras["CAM_1"]["stale"] is True
    assert cameras["CAM_1"]["reason"] == "STALE_FEED"
    assert cameras["CAM_2"]["stale"] is False

def test_health_db_down_graceful_degradation(client):
    # Corrupt DB path to trigger an insertion/query error simulating a down database
    os.environ["DB_PATH"] = "invalid_drive:/nonexistent_folder/db.sqlite"
    
    # Global exception handler should catch database failure and return 503
    res = client.get("/stores/ST1008/metrics")
    assert res.status_code == 503
    data = res.json()
    assert data["error"] == "db_unavailable"
    assert "trace_id" in data
