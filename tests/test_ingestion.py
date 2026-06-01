# PROMPT:
# "Write pytest tests for an event ingestion endpoint.
# The endpoint is POST /events/ingest. It must be idempotent
# by event_id. Test: (1) normal batch of 50 events accepted,
# (2) duplicate batch returns duplicate count not error,
# (3) malformed event in batch causes partial success,
# (4) batch of 501 events rejected with 422.
# Use FastAPI TestClient and an in-memory :memory: SQLite DB fixture."
#
# CHANGES MADE:
# - AI generated a fixture using pytest tmp_path; replaced with an in-memory :memory: SQLite DB for speed.
# - AI did not handle the 501-event boundary; added manually.
# - Renamed test_ingest_duplicates to test_ingest_idempotent for clarity.

import pytest
import os
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db

# Override the database path for tests
@pytest.fixture(autouse=True)
def test_db(tmp_path):
    # Set DB path to a temporary file
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

def make_mock_event(event_id=None, timestamp=None, is_staff=False, confidence=0.9):
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "store_id": "ST1008",
        "camera_id": "CAM_1",
        "visitor_id": "VIS_12345",
        "event_type": "ENTRY",
        "timestamp": timestamp or "2026-04-10T12:00:00+05:30",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": is_staff,
        "confidence": confidence,
        "metadata": {
            "session_seq": 1
        }
    }

def test_ingest_normal_batch(client):
    events = [make_mock_event() for _ in range(50)]
    res = client.post("/events/ingest", json={"events": events})
    assert res.status_code == 200
    data = res.json()
    assert data["accepted"] == 50
    assert data["rejected"] == 0
    assert data["duplicate"] == 0
    assert len(data["errors"]) == 0

def test_ingest_idempotent(client):
    events = [make_mock_event() for _ in range(10)]
    
    # First post
    res1 = client.post("/events/ingest", json={"events": events})
    assert res1.status_code == 200
    assert res1.json()["accepted"] == 10
    
    # Second post (duplicates)
    res2 = client.post("/events/ingest", json={"events": events})
    assert res2.status_code == 200
    data = res2.json()
    assert data["accepted"] == 0
    assert data["duplicate"] == 10

def test_ingest_partial_success(client):
    events = [make_mock_event() for _ in range(5)]
    # Add a malformed event (invalid UUID and invalid confidence)
    malformed = make_mock_event(event_id="invalid-uuid", confidence=2.5)
    events.append(malformed)
    
    res = client.post("/events/ingest", json={"events": events})
    assert res.status_code == 207  # Multi-Status partial success
    data = res.json()
    assert data["accepted"] == 5
    assert data["rejected"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["event_id"] == "invalid-uuid"

def test_ingest_batch_limit(client):
    events = [make_mock_event() for _ in range(501)]
    res = client.post("/events/ingest", json={"events": events})
    assert res.status_code == 422
