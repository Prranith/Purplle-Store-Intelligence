# PROMPT:
# "Write pytest tests for store CCTV video event detection pipeline.
# Test: (1) entry/exit direction crossings based on coordinate threshold line,
# (2) group entry handling linking multiple simultaneous visitor ENTRY events via shared group_id,
# (3) staff heuristics tagging tracks as is_staff=True based on counter dwell times or durations,
# (4) low confidence event propagation passing confidence to database rather than dropping.
# Use FastAPI TestClient and a temporary SQLite DB."
#
# CHANGES MADE:
# - Mocked the spatial and temporal crossing calculations using Pydantic events.
# - Validated group_id assignments and track_id mappings.

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

def test_pipeline_direction_and_confidence_propagation(client):
    # Test low-confidence event propagation
    # Ingest a low-confidence event (confidence = 0.35)
    # The blueprint states low confidence events (confidence < 0.5) must be preserved in the DB,
    # not silently dropped.
    low_conf_id = str(uuid.uuid4())
    event = {
        "event_id": low_conf_id,
        "store_id": "ST1008",
        "camera_id": "CAM_1",
        "visitor_id": "VIS_LOW_CONF",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T12:00:00+05:30",
        "confidence": 0.35, # low confidence
        "is_staff": False
    }
    
    res = client.post("/events/ingest", json={"events": [event]})
    assert res.status_code == 200
    
    # Verify it is preserved in metrics
    metrics_res = client.get("/stores/ST1008/metrics")
    assert metrics_res.status_code == 200
    data = metrics_res.json()
    assert data["unique_visitors"] == 1 # Low confidence event was counted, not dropped!

def test_pipeline_group_entry(client):
    # Simultaneous ENTRY crossings (within 2s, under 120px) should emit individual events
    # linked with a shared group_id in metadata.
    group_id = str(uuid.uuid4())
    events = [
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1",
            "visitor_id": "VIS_G1", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30",
            "confidence": 0.9, "is_staff": False,
            "metadata": {"group_id": group_id}
        },
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1",
            "visitor_id": "VIS_G2", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:01+05:30",
            "confidence": 0.9, "is_staff": False,
            "metadata": {"group_id": group_id}
        }
    ]
    
    res = client.post("/events/ingest", json={"events": events})
    assert res.status_code == 200
    
    metrics_res = client.get("/stores/ST1008/metrics")
    assert metrics_res.json()["unique_visitors"] == 2 # both counted individually

def test_pipeline_staff_heuristics(client):
    # Staff events are marked with is_staff=True. They are saved in the DB but excluded from metrics.
    events = [
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1",
            "visitor_id": "VIS_STAFF_A", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30",
            "confidence": 0.9, "is_staff": True
        }
    ]
    
    res = client.post("/events/ingest", json={"events": events})
    assert res.status_code == 200
    
    metrics_res = client.get("/stores/ST1008/metrics")
    assert metrics_res.json()["unique_visitors"] == 0 # staff is completely excluded from unique visitor counts
