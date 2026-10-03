import asyncio
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, date

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.database.db import init_db, get_connection
from app.database.models import add_event, get_active_events, get_all_events, save_trades_to_cache
from app.core.detector import DetectorEngine
from app.core.excel_writer import ExcelWriter
from app.core.ai_agent import AIAgent

class TestSystemIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        init_db()
        conn = get_connection()
        try:
            conn.execute("DELETE FROM events WHERE coin LIKE 'CATI%'")
            conn.execute("DELETE FROM trade_cache WHERE symbol LIKE 'CATI%'")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        conn = get_connection()
        try:
            conn.execute("DELETE FROM events WHERE coin LIKE 'CATI%'")
            conn.execute("DELETE FROM trade_cache WHERE symbol LIKE 'CATI%'")
            conn.commit()
        finally:
            conn.close()

    async def test_end_to_end_system_pipeline(self):
        """End-to-end 5-stage async integration test for database, CRUD, AI parser, detector, and Excel writer."""
        
        # --- STAGE 1: Database Initialization ---
        init_db()
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

        self.assertIn("events", tables, "events table must be created")
        self.assertIn("trade_cache", tables, "trade_cache table must be created")
        self.assertIn("sync_logs", tables, "sync_logs table must be created")

        # --- STAGE 2: Event CRUD ---
        test_coin = "CATI"
        ev_id = add_event(
            exchange="Bybit",
            event_name="CATI Alpha Test",
            event_type="Alpha",
            market="Alpha",
            coin=test_coin,
            pair=f"{test_coin}USDT",
            start_date=date.today().strftime("%Y-%m-%d"),
            target_volume=20000.0
        )
        self.assertIsInstance(ev_id, int)
        events = get_active_events(exchange="Bybit")
        self.assertTrue(any(e["id"] == ev_id for e in events), "Created event must be in active events")

        # --- STAGE 3: AI Announcement Parsing ---
        agent = AIAgent()
        announcement = """
        Bybit Token Splash: Trade MNT/USDT to share 50,000 USDT reward pool!
        Event period: 2024-07-12 to 2024-07-26.
        Eligible Market: Spot.
        Target Volume: 40000 USDT.
        """
        parsed = await agent.parse_announcement(announcement)
        self.assertIn(parsed.get("coin"), ["MNT", "BTC", "TOKEN"])
        self.assertEqual(parsed.get("exchange"), "Bybit")

        # --- STAGE 4: Detector & Trade Matching ---
        now_ms = int(datetime.now().timestamp() * 1000)
        mock_trades = [
            {
                "exchange": "Bybit",
                "exec_id": f"sys_exec_001_{now_ms}",
                "order_id": "test_ord_001",
                "symbol": f"{test_coin}USDT",
                "side": "Buy",
                "price": 1.0,
                "qty": 5000.0,
                "exec_value": 5000.0,
                "fee": 25.0,  # Alpha binde 5
                "fee_rate": 0.005,
                "exec_time": now_ms,
                "market": "Alpha"
            },
            {
                "exchange": "Bybit",
                "exec_id": f"sys_exec_002_{now_ms}",
                "order_id": "test_ord_002",
                "symbol": f"{test_coin}USDT",
                "side": "Sell",
                "price": 0.999,
                "qty": 5000.0,
                "exec_value": 4995.0,
                "fee": 25.0,  # Alpha binde 5
                "fee_rate": 0.005,
                "exec_time": now_ms + 1000,
                "market": "Alpha"
            }
        ]
        inserted = save_trades_to_cache(mock_trades)
        self.assertEqual(inserted, 2, "Both mock trades should be inserted")

        detector = DetectorEngine()
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trade_cache")
            raw = [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

        matched = detector.match_events(raw)
        matched_cati = [m for m in matched if m["event_id"] == ev_id]
        self.assertEqual(len(matched_cati), 1, "Must match CATI event")
        cati_result = matched_cati[0]
        self.assertAlmostEqual(cati_result["total_volume"], 9995.0, places=1)
        self.assertAlmostEqual(cati_result["total_fee"], 50.0, places=1)
        # Rebate for Alpha: round($9995 * 0.0030, 2) = $29.98 (round-to-even)
        self.assertAlmostEqual(cati_result["rebate"], 29.98, places=2)

        # --- STAGE 5: Excel Sync Engine ---
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_excel_path = Path(tmp_dir) / "test_maliyet.xlsx"
            source_excel = PROJECT_ROOT / "bybit-okx_maliyet.xlsx"
            if not source_excel.exists():
                source_excel = PROJECT_ROOT / "bybit-okx_maliyet_template.xlsx"
            shutil.copyfile(source_excel, test_excel_path)

            excel_writer = ExcelWriter(excel_path=str(test_excel_path))
            res = excel_writer.sync_detected_events(matched_cati)
            self.assertTrue(res.get("success"), f"Excel sync must succeed: {res}")
            self.assertGreaterEqual(res.get("added", 0) + res.get("updated", 0), 1)

if __name__ == "__main__":
    unittest.main()
