import sqlite3
import os
import json
from datetime import datetime, timezone

def get_db_path() -> str:
    return os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "store_intelligence.db"))

def get_db_connection() -> sqlite3.Connection:
    """
    Returns a connection to the SQLite database.
    Enables WAL mode and dictionary/row factory for ease of use.
    """
    db_path = get_db_path()
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    
    # Enable WAL mode for high concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    
    return conn

def init_db():
    """
    Creates tables and indexes if they do not exist.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create events table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            visitor_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            zone_id TEXT,
            dwell_ms INTEGER NOT NULL DEFAULT 0,
            is_staff INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL,
            metadata_json TEXT,
            ingested_at TEXT NOT NULL
        );
    """)
    
    # Create pos_transactions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pos_transactions (
            order_id INTEGER PRIMARY KEY,
            store_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            total_amount REAL,
            salesperson_id INTEGER,
            dep_name TEXT,
            brand_name TEXT,
            matched_visitor TEXT
        );
    """)
    
    # Create indexes for high-performance analytics queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_store_ts ON events(store_id, timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_visitor ON events(visitor_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_zone ON events(zone_id, timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pos_store_ts ON pos_transactions(store_id, timestamp);")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", get_db_path())
