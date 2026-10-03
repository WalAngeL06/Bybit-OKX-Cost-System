from datetime import datetime
from typing import List, Optional, Dict, Any
from app.database.db import get_connection

def add_event(exchange: str, event_name: str, event_type: str, market: str,
              coin: str, pair: str, start_date: str, end_date: Optional[str] = None,
              target_volume: float = 0.0) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
        INSERT INTO events (exchange, event_name, event_type, market, coin, pair, start_date, end_date, target_volume, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (exchange, event_name, event_type, market, coin.upper(), pair.upper(), start_date, end_date, target_volume, now, now))
        event_id = cursor.lastrowid
        conn.commit()
        return event_id
    finally:
        conn.close()

def get_active_events(exchange: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if exchange:
            cursor.execute("SELECT * FROM events WHERE status = 'active' AND exchange = ? ORDER BY id DESC", (exchange,))
        else:
            cursor.execute("SELECT * FROM events WHERE status = 'active' ORDER BY id DESC")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

def get_all_events() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events ORDER BY id DESC")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

def delete_event(event_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
    finally:
        conn.close()

def save_trades_to_cache(trades: List[Dict[str, Any]]) -> int:
    """Save raw trades from exchange to SQLite cache, ignoring duplicates."""
    if not trades:
        return 0
    conn = get_connection()
    try:
        cursor = conn.cursor()
        inserted = 0
        now = datetime.now().isoformat()
        for t in trades:
            try:
                cursor.execute("""
                INSERT OR IGNORE INTO trade_cache (
                    exchange, exec_id, order_id, symbol, side, price, qty,
                    exec_value, fee, fee_rate, exec_time, market, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    t.get("exchange"),
                    t.get("exec_id"),
                    t.get("order_id"),
                    t.get("symbol"),
                    t.get("side"),
                    float(t.get("price", 0.0)),
                    float(t.get("qty", 0.0)),
                    float(t.get("exec_value", 0.0)),
                    float(t.get("fee", 0.0)),
                    float(t.get("fee_rate", 0.0)),
                    int(t.get("exec_time", 0)),
                    t.get("market"),
                    now
                ))
                if cursor.rowcount > 0:
                    inserted += 1
            except Exception:
                continue
        conn.commit()
        return inserted
    finally:
        conn.close()

def log_sync(exchange: str, status: str, message: str, trades_found: int = 0, excel_updated: bool = False):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
        INSERT INTO sync_logs (timestamp, exchange, status, message, trades_found, excel_updated)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (now, exchange, status, message, trades_found, 1 if excel_updated else 0))
        conn.commit()
    finally:
        conn.close()

def get_recent_logs(limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sync_logs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
