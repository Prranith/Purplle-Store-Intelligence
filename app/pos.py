import csv
import os
from datetime import datetime, timezone, timedelta
from app.db import get_db_connection

IST = timezone(timedelta(hours=5, minutes=30))

def pos_timestamp(order_date: str, order_time: str) -> str:
    """
    Synthesizes date and time into a timezone-aware ISO-8601 string.
    Example: '10-04-2026' and '12:15:05' -> '2026-04-10T12:15:05+05:30'
    """
    dt = datetime.strptime(f"{order_date.strip()} {order_time.strip()}", "%d-%m-%Y %H:%M:%S")
    return dt.replace(tzinfo=IST).isoformat()

def load_pos_csv(csv_path: str) -> dict:
    """
    Parses POS CSV and populates pos_transactions table.
    Ensures idempotency using INSERT OR IGNORE / REPLACE.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"POS CSV file not found at: {csv_path}")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    loaded_orders = set()
    accepted = 0
    rejected = 0
    
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return {"accepted": 0, "rejected": 0, "error": "Empty file"}
            
        col_map = {col.strip(): idx for idx, col in enumerate(header)}
        
        required_cols = ['order_id', 'store_id', 'order_date', 'order_time', 'total_amount']
        for col in required_cols:
            if col not in col_map:
                conn.close()
                raise ValueError(f"Missing required CSV column: {col}")
                
        for row_idx, row in enumerate(reader):
            if not row or len(row) < len(header):
                rejected += 1
                continue
                
            try:
                order_id_str = row[col_map['order_id']].strip()
                if not order_id_str:
                    rejected += 1
                    continue
                order_id = int(order_id_str)
                
                # Check for line items within same order - aggregate or take first?
                # The schema represents orders. If we have duplicate orders in CSV, we insert-or-ignore.
                if order_id in loaded_orders:
                    # We already loaded this order ID, skip line items for same order to keep unique orders
                    continue
                    
                store_id = row[col_map['store_id']].strip()
                order_date = row[col_map['order_date']].strip()
                order_time = row[col_map['order_time']].strip()
                
                # Synthesize timestamp
                timestamp = pos_timestamp(order_date, order_time)
                
                total_amount_str = row[col_map['total_amount']].strip()
                total_amount = float(total_amount_str) if total_amount_str else 0.0
                
                salesperson_id_str = row[col_map['salesperson_id']].strip() if 'salesperson_id' in col_map else '0'
                salesperson_id = int(salesperson_id_str) if salesperson_id_str and salesperson_id_str != '' else 0
                
                dep_name = row[col_map['dep_name']].strip() if 'dep_name' in col_map else ''
                brand_name = row[col_map['brand_name']].strip() if 'brand_name' in col_map else ''
                
                cursor.execute("""
                    INSERT OR REPLACE INTO pos_transactions (
                        order_id, store_id, timestamp, total_amount, salesperson_id, dep_name, brand_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (order_id, store_id, timestamp, total_amount, salesperson_id, dep_name, brand_name))
                
                loaded_orders.add(order_id)
                accepted += 1
            except Exception as e:
                # Log or trace row-level failures
                rejected += 1
                
    conn.commit()
    conn.close()
    
    return {"accepted": accepted, "rejected": rejected}
