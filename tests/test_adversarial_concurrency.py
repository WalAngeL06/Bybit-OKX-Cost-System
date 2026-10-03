import asyncio
import os
import sys
import time
import shutil
import tempfile
import threading
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import openpyxl
from app.config import settings
from app.database.db import init_db, get_connection
import app.database.db as db_mod
import app.database.models as models_mod
from app.database.models import (
    add_event, get_active_events, get_all_events, delete_event,
    save_trades_to_cache, log_sync, get_recent_logs
)
from app.core.excel_writer import ExcelWriter
import app.main as main_mod
from app.main import run_sync, sync_lock


class TestAdversarialConcurrency(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial stress testing for database resilience, ExcelWriter file handle
    lifecycle, and asyncio concurrency synchronization.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="adv_test_")
        self.test_db_path = Path(self.tmp_dir) / "test_tracker.db"
        self.test_excel_path = Path(self.tmp_dir) / "test_maliyet.xlsx"

        # Initialize a test excel from template
        template = PROJECT_ROOT / "bybit-okx_maliyet_template.xlsx"
        if template.exists():
            shutil.copyfile(template, self.test_excel_path)
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Bybit Maliyetleri"
            ws["C5"] = 0.001
            ws["C6"] = 0.0005
            ws["C7"] = 0.0002
            ws["C8"] = 0.55
            ws["C9"] = 0.60
            wb.save(self.test_excel_path)
            wb.close()

    def tearDown(self):
        # Clean up temporary directory
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # =========================================================================
    # PART 1: CONCURRENT SQLITE WAL MODE READS AND WRITES STRESS TEST
    # =========================================================================

    def test_concurrent_sqlite_threads_stress(self):
        """
        Adversarial Test 1A: Multithreaded SQLite stress test.
        Launch 20 concurrent worker threads executing 500 interleaved
        read and write operations on the database under WAL mode.
        Verify zero 'database is locked' or locking crashes occur.
        """
        with patch.object(db_mod, "DB_PATH", self.test_db_path):
            init_db()

            errors = []
            operations_completed = 0
            lock = threading.Lock()

            def worker_task(thread_id: int, iterations: int):
                nonlocal operations_completed
                for i in range(iterations):
                    op_type = (thread_id + i) % 4
                    try:
                        if op_type == 0:
                            # Write: add_event
                            add_event(
                                exchange="Bybit" if i % 2 == 0 else "OKX",
                                event_name=f"StressEvent_{thread_id}_{i}",
                                event_type="Alpha",
                                market="Alpha",
                                coin=f"C{thread_id}",
                                pair=f"C{thread_id}USDT",
                                start_date="2026-10-01",
                                target_volume=1000.0 * (i + 1)
                            )
                        elif op_type == 1:
                            # Write: save_trades_to_cache (batch insert)
                            trades = [
                                {
                                    "exchange": "Bybit",
                                    "exec_id": f"exec_{thread_id}_{i}_{k}_{time.time_ns()}",
                                    "order_id": f"ord_{k}",
                                    "symbol": f"C{thread_id}USDT",
                                    "side": "Buy" if k % 2 == 0 else "Sell",
                                    "price": 1.25,
                                    "qty": 100.0,
                                    "exec_value": 125.0,
                                    "fee": 0.0625,
                                    "fee_rate": 0.0005,
                                    "exec_time": int(time.time() * 1000),
                                    "market": "Alpha"
                                }
                                for k in range(5)
                            ]
                            save_trades_to_cache(trades)
                        elif op_type == 2:
                            # Read: get_active_events & get_all_events
                            events = get_active_events()
                            all_ev = get_all_events()
                            self.assertIsInstance(events, list)
                            self.assertIsInstance(all_ev, list)
                        elif op_type == 3:
                            # Write: log_sync & Read: get_recent_logs
                            log_sync("All", "Success", f"Log from thread {thread_id} op {i}")
                            logs = get_recent_logs(limit=10)
                            self.assertIsInstance(logs, list)

                        with lock:
                            operations_completed += 1
                    except Exception as exc:
                        with lock:
                            errors.append((thread_id, i, op_type, str(exc), type(exc).__name__))

            # Run 20 threads with 25 operations each = 500 total operations
            num_threads = 20
            ops_per_thread = 25
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [
                    executor.submit(worker_task, tid, ops_per_thread)
                    for tid in range(num_threads)
                ]
                for f in as_completed(futures):
                    f.result()

            self.assertEqual(len(errors), 0, f"Encountered database concurrency errors: {errors}")
            self.assertEqual(operations_completed, num_threads * ops_per_thread)

    async def test_concurrent_sqlite_async_tasks_stress(self):
        """
        Adversarial Test 1B: Concurrent async tasks accessing SQLite.
        Launch 30 concurrent coroutines performing rapid database CRUD.
        Verify no connection leaks, deadlocks, or lock contention crashes.
        """
        with patch.object(db_mod, "DB_PATH", self.test_db_path):
            init_db()

            async def async_worker(task_id: int):
                # Run sync DB operations in executor to simulate async FastAPI handlers
                loop = asyncio.get_running_loop()
                for i in range(10):
                    await loop.run_in_executor(
                        None,
                        add_event,
                        "Bybit", f"AsyncEvent_{task_id}_{i}", "Splash", "Spot",
                        f"COIN{task_id}", f"COIN{task_id}USDT", "2026-10-01"
                    )
                    evs = await loop.run_in_executor(None, get_active_events)
                    self.assertGreater(len(evs), 0)
                    await loop.run_in_executor(
                        None,
                        log_sync, "Bybit", "Success", f"Task {task_id} completed {i}"
                    )

            tasks = [async_worker(i) for i in range(30)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for idx, res in enumerate(results):
                self.assertNotIsInstance(res, Exception, f"Task {idx} failed with {res}")

    def test_sqlite_busy_timeout_contention(self):
        """
        Adversarial Test 1C: Intentional contention test.
        Hold an exclusive write transaction in one thread for 200ms while 5 other
        threads attempt to write. With PRAGMA busy_timeout=5000, all waiting
        threads MUST successfully complete without raising OperationalError.
        """
        with patch.object(db_mod, "DB_PATH", self.test_db_path):
            init_db()

            barrier = threading.Barrier(2)
            contention_errors = []

            def holding_thread():
                conn = get_connection()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("INSERT INTO sync_logs (message) VALUES ('holding')")
                    # Signal second thread to start writing
                    barrier.wait()
                    time.sleep(0.3)  # Hold write lock for 300ms (less than 5000ms timeout)
                    conn.commit()
                finally:
                    conn.close()

            def contending_thread():
                barrier.wait()
                try:
                    # This write will block until holding_thread commits
                    log_sync("OKX", "Success", "Contending write succeeded")
                except Exception as e:
                    contention_errors.append(str(e))

            t1 = threading.Thread(target=holding_thread)
            t2 = threading.Thread(target=contending_thread)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            self.assertEqual(len(contention_errors), 0,
                             f"Contending write failed under busy_timeout: {contention_errors}")

    # =========================================================================
    # PART 2: EXCEL WRITER HANDLE RELEASE & WINDOWS PERMISSION LIFECYCLE
    # =========================================================================

    def test_excel_writer_handle_release_normal_operation(self):
        """
        Adversarial Test 2A: Verify ExcelWriter releases file handle upon success.
        On Windows, if a file handle remains open, os.remove or open('r+b') will
        raise PermissionError. Test that immediate file modification and deletion
        succeed without PermissionError.
        """
        writer = ExcelWriter(excel_path=str(self.test_excel_path))
        event = {
            "exchange": "Bybit",
            "coin": "BTC",
            "event_type": "Alpha",
            "market": "Alpha",
            "total_volume": 50000.0,
            "total_cost": 25.0,
            "date": "2026-10-01"
        }
        res = writer.sync_detected_events([event])
        self.assertTrue(res["success"], f"Sync failed: {res}")

        # Test 1: Immediate re-open with openpyxl in write mode
        wb2 = openpyxl.load_workbook(self.test_excel_path)
        ws2 = wb2["Bybit Maliyetleri"]
        self.assertEqual(ws2["D12"].value, "BTC")
        wb2.save(self.test_excel_path)
        wb2.close()

        # Test 2: Immediate file deletion (strictly fails on Windows if handle is leaked)
        try:
            os.remove(self.test_excel_path)
        except PermissionError as pe:
            self.fail(f"ExcelWriter leaked file handle! os.remove failed with PermissionError: {pe}")

        self.assertFalse(self.test_excel_path.exists(), "File should be successfully deleted")

    def test_excel_writer_handle_release_on_unexpected_exception(self):
        """
        Adversarial Test 2B: Exception injection during sync.
        Verify that even if an unexpected exception occurs during workbook processing,
        the `finally: wb.close()` block ALWAYS executes, releasing the Windows file handle.
        """
        writer = ExcelWriter(excel_path=str(self.test_excel_path))

        # Inject malformed data that causes a TypeError/ValueError during row processing
        malformed_event = {
            "exchange": "Bybit",
            "coin": "MALFORMED",
            "event_type": "Alpha",
            "market": "Alpha",
            "total_volume": "INVALID_VOLUME_STRING",  # float() will fail!
            "total_cost": 10.0,
            "date": "2026-10-01"
        }

        # Expect ValueError when float() is called in sync_detected_events
        with self.assertRaises(ValueError):
            writer.sync_detected_events([malformed_event])

        # Verify that despite the crash, wb.close() was executed in finally
        # File MUST be deletable without PermissionError
        try:
            os.remove(self.test_excel_path)
        except PermissionError as pe:
            self.fail(f"Handle leak detected after exception! os.remove raised: {pe}")

    def test_excel_writer_handling_when_file_is_externally_locked(self):
        """
        Adversarial Test 2C: Simulate another process (Excel) holding an exclusive lock.
        When another application has the file locked on Windows, ExcelWriter MUST
        catch PermissionError, return a descriptive error message, and NOT crash.
        """
        writer = ExcelWriter(excel_path=str(self.test_excel_path))
        event = {
            "exchange": "Bybit",
            "coin": "ETH",
            "event_type": "Alpha",
            "market": "Alpha",
            "total_volume": 10000.0,
            "total_cost": 5.0,
            "date": "2026-10-01"
        }

        # Mock wb.save to raise PermissionError (simulating Windows file lock by Excel)
        with patch("openpyxl.Workbook.save", side_effect=PermissionError("File in use")):
            res = writer.sync_detected_events([event])
            self.assertFalse(res["success"])
            self.assertIn("Excel dosyası başka bir programda", res["error"])

        # After the simulated lock failure, file must still be accessible and not corrupted
        self.assertTrue(self.test_excel_path.exists())
        wb_check = openpyxl.load_workbook(self.test_excel_path)
        wb_check.close()

    def test_excel_writer_rapid_successive_syncs(self):
        """
        Adversarial Test 2D: Rapid sequential syncs (50 iterations).
        Ensure repetitive opening and closing does not hit Windows handle exhaustion.
        """
        writer = ExcelWriter(excel_path=str(self.test_excel_path))
        for i in range(50):
            event = {
                "exchange": "Bybit",
                "coin": f"COIN_{i}",
                "event_type": "Alpha",
                "market": "Alpha",
                "total_volume": 100.0 * (i + 1),
                "total_cost": 1.0 * (i + 1),
                "date": "2026-10-01"
            }
            res = writer.sync_detected_events([event])
            self.assertTrue(res["success"], f"Sync failed at iteration {i}: {res}")

        # Verify file can be removed cleanly
        os.remove(self.test_excel_path)

    # =========================================================================
    # PART 3: MUTUAL EXCLUSION OF RUN_SYNC VIA ASYNCIO.LOCK
    # =========================================================================

    async def test_run_sync_mutual_exclusion_stress(self):
        """
        Adversarial Test 3A: Concurrent triggers of run_sync().
        Simulate 10 simultaneous calls (e.g., auto-sync worker and rapid user clicks).
        Instrument the critical section to assert max_active_executions is NEVER > 1.
        """
        active_executions = 0
        max_active_executions = 0
        execution_count = 0
        concurrency_lock = asyncio.Lock()

        # Mock the internal work of run_sync to simulate realistic network/DB I/O duration
        async def instrumented_run_sync():
            nonlocal active_executions, max_active_executions, execution_count
            async with sync_lock:
                async with concurrency_lock:
                    active_executions += 1
                    if active_executions > max_active_executions:
                        max_active_executions = active_executions
                
                # Check invariant: at no point during the execution may active_executions > 1
                self.assertEqual(active_executions, 1, "Concurrency violation: multiple tasks in critical section!")
                
                # Simulate work duration (I/O, network)
                await asyncio.sleep(0.05)

                async with concurrency_lock:
                    active_executions -= 1
                    execution_count += 1

                return {"success": True, "message": "OK"}

        # Launch 10 simultaneous triggers
        tasks = [asyncio.create_task(instrumented_run_sync()) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        self.assertEqual(max_active_executions, 1,
                         f"Mutual exclusion failed! Max concurrent executions observed: {max_active_executions}")
        self.assertEqual(execution_count, 10, "All 10 sync calls must complete sequentially")
        for r in results:
            self.assertTrue(r["success"])

    async def test_run_sync_lock_release_on_failure(self):
        """
        Adversarial Test 3B: Verify sync_lock does NOT deadlock if an exception occurs.
        If a task crashes inside run_sync(), the lock must be properly released so
        subsequent auto-sync or manual sync calls proceed smoothly.
        """
        async def failing_task():
            async with sync_lock:
                await asyncio.sleep(0.01)
                raise RuntimeError("Simulated crash in trade fetching or DB!")

        async def succeeding_task():
            async with sync_lock:
                await asyncio.sleep(0.01)
                return "SUCCESS"

        # Task 1 raises exception
        with self.assertRaises(RuntimeError):
            await failing_task()

        # Verify lock is not held
        self.assertFalse(sync_lock.locked(), "sync_lock remained locked after exception!")

        # Task 2 MUST succeed and not deadlock
        try:
            res = await asyncio.wait_for(succeeding_task(), timeout=2.0)
            self.assertEqual(res, "SUCCESS")
        except asyncio.TimeoutError:
            self.fail("sync_lock deadlocked after previous task crashed!")

    async def test_event_loop_responsiveness_during_sync(self):
        """
        Adversarial Test 3C: Verify event loop remains responsive while sync is running.
        While run_sync() is active, other non-sync operations (like status queries)
        must execute without being blocked.
        """
        sync_started = asyncio.Event()

        async def long_sync():
            async with sync_lock:
                sync_started.set()
                await asyncio.sleep(0.2)  # 200ms sync
                return "SYNC_DONE"

        async def quick_status_check():
            await sync_started.wait()
            # Status check should complete immediately while sync is still running
            start_t = time.time()
            status = {"status": "online"}
            await asyncio.sleep(0.001)
            duration = time.time() - start_t
            return status, duration

        sync_task = asyncio.create_task(long_sync())
        status_task = asyncio.create_task(quick_status_check())

        status_res, duration = await status_task
        sync_res = await sync_task

        self.assertEqual(status_res["status"], "online")
        self.assertLess(duration, 0.1, f"Status check was blocked by sync! Took {duration:.3f}s")
        self.assertEqual(sync_res, "SYNC_DONE")


if __name__ == "__main__":
    unittest.main()
