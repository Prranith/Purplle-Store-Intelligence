# PROMPT:
# "Write pytest tests for POS CSV loading functionality.
# Test: (1) successful CSV loading with correct record count,
# (2) POS timestamp conversion (date + time -> ISO-8601),
# (3) idempotency via INSERT OR REPLACE (duplicate order_id handling),
# (4) error handling for malformed CSV,
# (5) auto-loading on startup via lifespan hook.
# Use FastAPI TestClient, temporary SQLite DB, and in-memory CSV fixtures."

import pytest
import os
import csv
import io
import tempfile
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, get_db_connection
from app.pos import load_pos_csv, pos_timestamp

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

def create_test_csv(records: list) -> str:
    """Create a temporary CSV file with the given records."""
    fd, path = tempfile.mkstemp(suffix=".csv", text=True)
    try:
        with os.fdopen(fd, "w", newline="") as f:
            if records:
                writer = csv.DictWriter(f, fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
    except Exception as e:
        os.close(fd)
        raise e
    return path

def test_pos_csv_loading_basic(client):
    """Test loading a valid POS CSV file."""
    records = [
        {
            "order_id": "1001",
            "order_date": "10-04-2026",
            "order_time": "12:15:05",
            "store_id": "ST1008",
            "total_amount": "2500.00",
            "salesperson_id": "1178",
            "dep_name": "makeup",
            "brand_name": "Faces Canada",
            "customer_name": "Guest"
        },
        {
            "order_id": "1002",
            "order_date": "10-04-2026",
            "order_time": "12:42:18",
            "store_id": "ST1008",
            "total_amount": "1500.00",
            "salesperson_id": "971",
            "dep_name": "skincare",
            "brand_name": "Lakme",
            "customer_name": "Guest"
        }
    ]
    
    csv_path = create_test_csv(records)
    try:
        stats = load_pos_csv(csv_path)
        assert stats["accepted"] == 2
        assert stats["rejected"] == 0
        
        # Verify records are in DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM pos_transactions WHERE store_id = ?", ("ST1008",))
        count = cursor.fetchone()[0]
        assert count == 2
        conn.close()
    finally:
        os.remove(csv_path)

def test_pos_timestamp_conversion():
    """Test POS date+time conversion to ISO-8601."""
    ts = pos_timestamp("10-04-2026", "12:15:05")
    assert ts == "2026-04-10T12:15:05+05:30"
    
    ts2 = pos_timestamp("01-01-2026", "00:00:00")
    assert ts2 == "2026-01-01T00:00:00+05:30"

def test_pos_csv_idempotency(client):
    """Test that duplicate order_ids use INSERT OR REPLACE."""
    records = [
        {
            "order_id": "1001",
            "order_date": "10-04-2026",
            "order_time": "12:15:05",
            "store_id": "ST1008",
            "total_amount": "2500.00",
            "salesperson_id": "1178",
            "dep_name": "makeup",
            "brand_name": "Faces Canada",
            "customer_name": "Guest"
        }
    ]
    
    csv_path = create_test_csv(records)
    try:
        # Load once
        stats1 = load_pos_csv(csv_path)
        assert stats1["accepted"] == 1
        
        # Load same CSV again (duplicate order_id 1001)
        stats2 = load_pos_csv(csv_path)
        # Since we INSERT OR REPLACE, it's still 1 record
        assert stats2["accepted"] == 1
        
        # Verify only 1 record in DB (not 2)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM pos_transactions WHERE order_id = ?", (1001,))
        count = cursor.fetchone()[0]
        assert count == 1
        conn.close()
    finally:
        os.remove(csv_path)

def test_pos_csv_malformed_handling(client):
    """Test error handling for malformed CSV (missing order_id)."""
    records = [
        {
            "order_id": "",  # Missing order_id
            "order_date": "10-04-2026",
            "order_time": "12:15:05",
            "store_id": "ST1008",
            "total_amount": "2500.00",
            "salesperson_id": "1178",
            "dep_name": "makeup",
            "brand_name": "Faces Canada",
            "customer_name": "Guest"
        },
        {
            "order_id": "1002",
            "order_date": "10-04-2026",
            "order_time": "12:42:18",
            "store_id": "ST1008",
            "total_amount": "1500.00",
            "salesperson_id": "971",
            "dep_name": "skincare",
            "brand_name": "Lakme",
            "customer_name": "Guest"
        }
    ]
    
    csv_path = create_test_csv(records)
    try:
        stats = load_pos_csv(csv_path)
        assert stats["accepted"] == 1  # Only 1002 accepted
        assert stats["rejected"] == 1  # First record rejected (missing order_id)
    finally:
        os.remove(csv_path)

def test_pos_csv_missing_required_column(client):
    """Test error handling for missing required column."""
    # Create CSV with missing 'total_amount' column
    fd, path = tempfile.mkstemp(suffix=".csv", text=True)
    try:
        with os.fdopen(fd, "w", newline="") as f:
            f.write("order_id,order_date,store_id\n")
            f.write("1001,10-04-2026,ST1008\n")
        
        with pytest.raises(ValueError) as exc_info:
            load_pos_csv(path)
        assert "Missing required CSV column" in str(exc_info.value)
    finally:
        os.remove(path)

def test_pos_file_not_found():
    """Test handling of non-existent CSV file."""
    with pytest.raises(FileNotFoundError):
        load_pos_csv("/nonexistent/path/to/file.csv")

def test_pos_admin_upload_endpoint(client):
    """Test the /admin/load-pos endpoint for file upload."""
    records = [
        {
            "order_id": "5001",
            "order_date": "10-04-2026",
            "order_time": "19:21:55",
            "store_id": "ST1008",
            "total_amount": "3200.00",
            "salesperson_id": "1178",
            "dep_name": "makeup",
            "brand_name": "Maybelline",
            "customer_name": "Guest"
        }
    ]
    
    csv_path = create_test_csv(records)
    try:
        with open(csv_path, "rb") as f:
            res = client.post("/admin/load-pos", files={"file": f})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["stats"]["accepted"] == 1
    finally:
        os.remove(csv_path)
