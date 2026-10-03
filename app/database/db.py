import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent.parent.parent / "tracker.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    try:
        cursor = conn.cursor()

        # Events table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange TEXT NOT NULL,         -- 'Bybit' or 'OKX'
            event_name TEXT NOT NULL,       -- e.g. 'MNT Token Splash'
            event_type TEXT NOT NULL,       -- 'Splash', 'Alpha', 'Stock Buzz', 'Puzzle Hunt', 'Flash Earn', 'Others'
            market TEXT NOT NULL,           -- 'Spot', 'Futures', 'Alpha'
            coin TEXT NOT NULL,             -- e.g. 'MNT'
            pair TEXT NOT NULL,             -- e.g. 'MNTUSDT'
            start_date TEXT NOT NULL,       -- 'YYYY-MM-DD'
            end_date TEXT,                  -- 'YYYY-MM-DD'
            target_volume REAL DEFAULT 0,
            status TEXT DEFAULT 'active',   -- 'active', 'completed', 'paused'
            created_at TEXT,
            updated_at TEXT
        )
        """)

        # Trade cache table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange TEXT NOT NULL,
            exec_id TEXT UNIQUE NOT NULL,
            order_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT,                      -- 'Buy', 'Sell'
            price REAL,
            qty REAL,
            exec_value REAL,                -- price * qty in USD
            fee REAL,                       -- fee paid in USD
            fee_rate REAL,
            exec_time INTEGER,              -- epoch ms
            market TEXT,                    -- 'Spot', 'Futures', 'Alpha'
            matched_event_id INTEGER,
            created_at TEXT
        )
        """)

        # Sync log table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            exchange TEXT,
            status TEXT,
            message TEXT,
            trades_found INTEGER DEFAULT 0,
            excel_updated INTEGER DEFAULT 0
        )
        """)

        conn.commit()
    finally:
        conn.close()

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
    if not cursor.fetchone():
        init_db()
    return conn

# Auto-initialize database on import
init_db()
