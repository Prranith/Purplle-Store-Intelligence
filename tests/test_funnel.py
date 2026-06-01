# PROMPT:
# "Write pytest tests for store conversion funnel metrics.
# Test: (1) correct counts at each stage: ENTRY -> ZONE_VISIT -> BILLING_QUEUE -> PURCHASE,
# (2) session deduplication verifying that multiple entries or zone visits by the same visitor
# do not inflate counts,
# (3) drop-off calculations matching sequential percentages.
# Use FastAPI TestClient and temporary SQLite DB."
#
# CHANGES MADE:
# - Ensured drop-off percentages are relative to the previous stage.
# - Handled division-by-zero safely for empty funnel stages.

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

def test_funnel_counts_and_dropoffs(client):
    # Ingest sequence:
    # VIS_1: ENTRY -> ZONE_EB_KOREAN -> ZONE_CASH_COUNTER -> buys (reaches stage 4)
    # VIS_2: ENTRY -> ZONE_GOOD_VIBES -> ZONE_CASH_COUNTER -> does not buy (reaches stage 3)
    # VIS_3: ENTRY -> ZONE_DERMDOC -> does not go to counter (reaches stage 2)
    # VIS_4: ENTRY -> stays at door, no zone visit (reaches stage 1)
    
    events = [
        # VIS_1
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1", "visitor_id": "VIS_1", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30", "confidence": 0.9, "is_staff": False},
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_2", "visitor_id": "VIS_1", "event_type": "ZONE_ENTER", "zone_id": "ZONE_EB_KOREAN", "timestamp": "2026-04-10T12:01:00+05:30", "confidence": 0.9, "is_staff": False},
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_3", "visitor_id": "VIS_1", "event_type": "ZONE_ENTER", "zone_id": "ZONE_CASH_COUNTER", "timestamp": "2026-04-10T12:02:00+05:30", "confidence": 0.9, "is_staff": False},
        
        # VIS_2
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1", "visitor_id": "VIS_2", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30", "confidence": 0.9, "is_staff": False},
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_2", "visitor_id": "VIS_2", "event_type": "ZONE_ENTER", "zone_id": "ZONE_GOOD_VIBES", "timestamp": "2026-04-10T12:01:00+05:30", "confidence": 0.9, "is_staff": False},
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_3", "visitor_id": "VIS_2", "event_type": "ZONE_ENTER", "zone_id": "ZONE_CASH_COUNTER", "timestamp": "2026-04-10T12:15:00+05:30", "confidence": 0.9, "is_staff": False},
        
        # VIS_3
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1", "visitor_id": "VIS_3", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30", "confidence": 0.9, "is_staff": False},
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_2", "visitor_id": "VIS_3", "event_type": "ZONE_ENTER", "zone_id": "ZONE_DERMDOC", "timestamp": "2026-04-10T12:01:00+05:30", "confidence": 0.9, "is_staff": False},
        
        # VIS_4
        {"event_id": str(uuid.uuid4()), "store_id": "ST1008", "camera_id": "CAM_1", "visitor_id": "VIS_4", "event_type": "ENTRY", "timestamp": "2026-04-10T12:00:00+05:30", "confidence": 0.9, "is_staff": False},
    ]
    
    client.post("/events/ingest", json={"events": events})
    
    # Store transaction for VIS_1 (at 12:03:00)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pos_transactions (order_id, store_id, timestamp, total_amount)
        VALUES (2001, 'ST1008', '2026-04-10T12:03:00+05:30', 980.00)
    """)
    conn.commit()
    conn.close()
    
    res = client.get("/stores/ST1008/funnel")
    assert res.status_code == 200
    data = res.json()
    
    funnel = data["funnel"]
    
    # Assert counts
    assert funnel[0]["stage"] == "ENTRY"
    assert funnel[0]["count"] == 4
    
    assert funnel[1]["stage"] == "ZONE_VISIT"
    assert funnel[1]["count"] == 3  # VIS_1, VIS_2, VIS_3
    
    assert funnel[2]["stage"] == "BILLING_QUEUE"
    assert funnel[2]["count"] == 2  # VIS_1, VIS_2
    
    assert funnel[3]["stage"] == "PURCHASE"
    assert funnel[3]["count"] == 1  # VIS_1
    
    # Assert drop-offs
    # Entry -> Zone: 4 to 3 -> 25.0% drop-off
    assert funnel[1]["drop_pct"] == 25.00
    # Zone -> Queue: 3 to 2 -> 33.33% drop-off
    assert funnel[2]["drop_pct"] == 33.33
    # Queue -> Purchase: 2 to 1 -> 50.0% drop-off
    assert funnel[3]["drop_pct"] == 50.00
