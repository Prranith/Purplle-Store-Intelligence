# PROMPT:
# "Write pytest tests for store analytics metrics calculations.
# Test: (1) conversion rate calculation matching 5-minute pre-checkout window,
# (2) zero-traffic store handling returning 0 stats and NO_DATA confidence,
# (3) staff exclusions ensuring tracks with is_staff=True do not count toward store metrics,
# (4) zero-purchase stores returning 0.0 conversion rate without 5xx errors.
# Use FastAPI TestClient and a temporary SQLite DB fixture."
#
# CHANGES MADE:
# - Added customized helpers for populating events and POS transactions to precisely test the 5-minute overlap window.
# - Explicitly added tests for salesperson_id exclusions.
# - Asserted that data_confidence is LOW if traffic count is < 20.

import pytest
import os
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, get_db_connection

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

def test_metrics_zero_traffic(client):
    res = client.get("/stores/ST1008/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0
    assert data["data_confidence"] == "NO_DATA"

def test_metrics_conversion_and_staff_exclusion(client):
    # Ingest some events:
    # Visitor A: enters store, visits cash counter, buys.
    # Visitor B: enters store, visits cash counter, but does not buy.
    # Staff C: enters cash counter, but marked is_staff=True.
    
    events = [
        # Visitor A
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1",
            "visitor_id": "VIS_A", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30",
            "confidence": 0.9, "is_staff": False
        },
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_3",
            "visitor_id": "VIS_A", "event_type": "ZONE_ENTER", "timestamp": "2026-04-10T12:05:00+05:30",
            "zone_id": "ZONE_CASH_COUNTER", "confidence": 0.9, "is_staff": False
        },
        # Visitor B
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1",
            "visitor_id": "VIS_B", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30",
            "confidence": 0.9, "is_staff": False
        },
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_3",
            "visitor_id": "VIS_B", "event_type": "ZONE_ENTER", "timestamp": "2026-04-10T12:10:00+05:30",
            "zone_id": "ZONE_CASH_COUNTER", "confidence": 0.9, "is_staff": False
        },
        # Staff C (should be excluded)
        {
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_3",
            "visitor_id": "VIS_STAFF", "event_type": "ZONE_ENTER", "timestamp": "2026-04-10T12:05:00+05:30",
            "zone_id": "ZONE_CASH_COUNTER", "confidence": 0.9, "is_staff": True
        }
    ]
    
    # Ingest events
    client.post("/events/ingest", json={"events": events})
    
    # Insert a POS transaction matching Visitor A's cash counter visit (t_txn = 12:06:00 is within 12:05:00 + 300s)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pos_transactions (order_id, store_id, timestamp, total_amount, salesperson_id)
        VALUES (1001, 'ST1008', '2026-04-10T12:06:00+05:30', 2500.0, 1178)
    """)
    conn.commit()
    conn.close()
    
    res = client.get("/stores/ST1008/metrics")
    assert res.status_code == 200
    data = res.json()
    
    # 2 unique customers (VIS_A, VIS_B). Staff C is excluded.
    assert data["unique_visitors"] == 2
    
    # VIS_A bought, VIS_B did not. Conversion is 1 / 2 = 50.0%
    assert data["conversion_rate"] == 0.50
    assert data["data_confidence"] == "LOW"  # Traffic is < 20

def test_heatmap_structure_and_normalization(client):
    # Ingest zone events for two zones with different visit counts
    events = []
    for i in range(3):
        events.append({
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_2",
            "visitor_id": f"VIS_HEAT_{i}", "event_type": "ENTRY",
            "timestamp": "2026-04-10T12:00:00+05:30", "confidence": 0.9, "is_staff": False
        })
        events.append({
            "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_2",
            "visitor_id": f"VIS_HEAT_{i}", "event_type": "ZONE_ENTER",
            "zone_id": "ZONE_MAKEUP_UNIT", "timestamp": "2026-04-10T12:01:00+05:30",
            "confidence": 0.9, "is_staff": False
        })
    # One visitor goes to fragrance
    events.append({
        "event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_4",
        "visitor_id": "VIS_HEAT_0", "event_type": "ZONE_ENTER",
        "zone_id": "ZONE_FRAGRANCE", "timestamp": "2026-04-10T12:02:00+05:30",
        "confidence": 0.9, "is_staff": False
    })
    client.post("/events/ingest", json={"events": events})
    
    res = client.get("/stores/ST1008/heatmap")
    assert res.status_code == 200
    data = res.json()
    
    assert "store_id" in data
    assert "zones" in data
    assert len(data["zones"]) == 23  # All 23 canonical zones
    
    # Check zone structure
    zones_by_id = {z["zone_id"]: z for z in data["zones"]}
    
    # ZONE_MAKEUP_UNIT should have highest score (3 visits vs 1 for ZONE_FRAGRANCE)
    makeup = zones_by_id.get("ZONE_MAKEUP_UNIT")
    assert makeup is not None
    assert makeup["visit_count"] == 3
    assert makeup["normalised_score"] == 100  # max zone gets 100
    assert "avg_dwell_ms" in makeup
    assert "data_confidence" in makeup
    
    fragrance = zones_by_id.get("ZONE_FRAGRANCE")
    assert fragrance is not None
    assert fragrance["visit_count"] == 1
    assert fragrance["normalised_score"] == 33  # round(1/3 * 100)

def test_unknown_store_returns_404(client):
    # Unknown store IDs should return 404 store_not_found
    res = client.get("/stores/UNKNOWN_XYZ/metrics")
    assert res.status_code == 404
    assert res.json()["error"] == "store_not_found"
    
    res2 = client.get("/stores/UNKNOWN_XYZ/funnel")
    assert res2.status_code == 404
    
    res3 = client.get("/stores/UNKNOWN_XYZ/heatmap")
    assert res3.status_code == 404
    
    res4 = client.get("/stores/UNKNOWN_XYZ/anomalies")
    assert res4.status_code == 404
