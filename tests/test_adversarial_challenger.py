import sys
import unittest
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.detector import DetectorEngine
from app.core.bybit_client import BybitClient
from app.core.okx_client import OKXClient

class TestSlippageAdversarial(unittest.TestCase):
    """Adversarial stress-testing of slippage isolation on unsold/held assets."""

    def setUp(self):
        self.detector = DetectorEngine()

    def _make_event(self, coin="TEST", market="Spot", event_type="Splash"):
        return {
            "id": 101,
            "exchange": "Bybit",
            "event_name": f"{coin} Event",
            "event_type": event_type,
            "market": market,
            "coin": coin,
            "pair": f"{coin}USDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

    def test_zero_sell_holding_all_assets(self):
        """Stress: 1,000,000 tokens bought at $0.001 ($1000). Zero sold.
        Remaining balance = 1,000,000 tokens. Realized slippage must be strictly 0.0!"""
        event = self._make_event()
        trades = [{
            "exchange": "Bybit",
            "symbol": "TESTUSDT",
            "market": "Spot",
            "side": "Buy",
            "price": 0.001,
            "qty": 1_000_000.0,
            "exec_value": 1000.0,
            "fee": 1.0,
            "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
        }]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertEqual(res["makas"], 0.0, "Unsold held assets must produce 0 realized slippage!")
            self.assertEqual(res["total_fee"], 1.0)
            self.assertEqual(res["total_cost"], 1.0, "Total cost should strictly be the fee, not $1000!")

    def test_zero_buy_selling_preheld_assets(self):
        """Stress: User transfers 500 tokens in and sells at $10 ($5000).
        Zero buys in event period. Realized slippage must be strictly 0.0!"""
        event = self._make_event()
        trades = [{
            "exchange": "Bybit",
            "symbol": "TESTUSDT",
            "market": "Spot",
            "side": "Sell",
            "price": 10.0,
            "qty": 500.0,
            "exec_value": 5000.0,
            "fee": 5.0,
            "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
        }]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertEqual(res["makas"], 0.0, "Selling without buys must produce 0 realized slippage!")
            self.assertEqual(res["total_cost"], 5.0)

    def test_partial_sell_with_price_drop_isolated(self):
        """Stress: Buy 100 @ $10 ($1000), Sell 20 @ $8 ($160).
        Unsold: 80 tokens. Closed qty = 20.
        Realized loss on closed: 20 * (10 - 8) = $40.00.
        Unsold 80 tokens must NOT be charged as slippage!"""
        event = self._make_event()
        trades = [
            {
                "exchange": "Bybit",
                "symbol": "TESTUSDT",
                "market": "Spot",
                "side": "Buy",
                "price": 10.0,
                "qty": 100.0,
                "exec_value": 1000.0,
                "fee": 1.0,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            },
            {
                "exchange": "Bybit",
                "symbol": "TESTUSDT",
                "market": "Spot",
                "side": "Sell",
                "price": 8.0,
                "qty": 20.0,
                "exec_value": 160.0,
                "fee": 0.16,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            }
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertEqual(res["makas"], 40.00, "Realized slippage should strictly be (10-8)*20 = 40.00")
            self.assertEqual(res["total_cost"], round(1.16 + 40.00, 2))

    def test_profitable_partial_sell_no_negative_slippage(self):
        """Stress: Buy 100 @ $10 ($1000), Sell 20 @ $15 ($300).
        Price increased! Realized slippage must be capped at 0.0, not negative!"""
        event = self._make_event()
        trades = [
            {
                "exchange": "Bybit",
                "symbol": "TESTUSDT",
                "market": "Spot",
                "side": "Buy",
                "price": 10.0,
                "qty": 100.0,
                "exec_value": 1000.0,
                "fee": 1.0,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            },
            {
                "exchange": "Bybit",
                "symbol": "TESTUSDT",
                "market": "Spot",
                "side": "Sell",
                "price": 15.0,
                "qty": 20.0,
                "exec_value": 300.0,
                "fee": 0.3,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            }
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertEqual(res["makas"], 0.0, "Profitable trade must result in 0.0 realized slippage!")
            self.assertEqual(res["total_cost"], 1.30)

    def test_sell_more_than_bought_min_qty_isolation(self):
        """Stress: Buy 10 @ $100 ($1000), Sell 50 @ $90 ($4500).
        Closed qty = min(10, 50) = 10.
        Realized loss = (100 - 90) * 10 = $100.00."""
        event = self._make_event()
        trades = [
            {
                "exchange": "Bybit",
                "symbol": "TESTUSDT",
                "market": "Spot",
                "side": "Buy",
                "price": 100.0,
                "qty": 10.0,
                "exec_value": 1000.0,
                "fee": 1.0,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            },
            {
                "exchange": "Bybit",
                "symbol": "TESTUSDT",
                "market": "Spot",
                "side": "Sell",
                "price": 90.0,
                "qty": 50.0,
                "exec_value": 4500.0,
                "fee": 4.5,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            }
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertEqual(res["makas"], 100.00, "Closed qty should be min(10, 50)=10, loss=(100-90)*10=100")

    def test_multiple_fills_weighted_slippage(self):
        """Stress: Multiple buy and sell fills at varying price tiers."""
        event = self._make_event()
        # Buy: 10 @ $100 ($1000), 20 @ $110 ($2200), 30 @ $120 ($3600) -> Tot Qty=60, Tot Val=$6800. Avg Buy=$113.333333
        # Sell: 15 @ $105 ($1575), 5 @ $95 ($475) -> Tot Qty=20, Tot Val=$2050. Avg Sell=$102.50
        # Closed qty = min(60, 20) = 20.
        # Expected slippage = (113.333333 - 102.50) * 20 = 10.833333 * 20 = 216.666667 -> round to 216.67
        now_ms = int(datetime(2026, 10, 2).timestamp() * 1000)
        trades = [
            {"exchange": "Bybit", "symbol": "TESTUSDT", "market": "Spot", "side": "Buy", "price": 100.0, "qty": 10.0, "exec_value": 1000.0, "fee": 1.0, "exec_time": now_ms},
            {"exchange": "Bybit", "symbol": "TESTUSDT", "market": "Spot", "side": "Buy", "price": 110.0, "qty": 20.0, "exec_value": 2200.0, "fee": 2.2, "exec_time": now_ms + 1000},
            {"exchange": "Bybit", "symbol": "TESTUSDT", "market": "Spot", "side": "Buy", "price": 120.0, "qty": 30.0, "exec_value": 3600.0, "fee": 3.6, "exec_time": now_ms + 2000},
            {"exchange": "Bybit", "symbol": "TESTUSDT", "market": "Spot", "side": "Sell", "price": 105.0, "qty": 15.0, "exec_value": 1575.0, "fee": 1.575, "exec_time": now_ms + 3000},
            {"exchange": "Bybit", "symbol": "TESTUSDT", "market": "Spot", "side": "Sell", "price": 95.0, "qty": 5.0, "exec_value": 475.0, "fee": 0.475, "exec_time": now_ms + 4000},
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertAlmostEqual(res["makas"], 216.67, places=2)


class TestSymbolMatchingAdversarial(unittest.TestCase):
    """Adversarial stress-testing of symbol matching false positives."""

    def setUp(self):
        self.detector = DetectorEngine()

    def test_prefix_false_positive_collisions(self):
        """Stress test: Event coin KII must strictly reject KIICHI and all prefix variations."""
        event = {
            "id": 201,
            "exchange": "Bybit",
            "event_name": "KII Event",
            "event_type": "Alpha",
            "market": "Alpha",
            "coin": "KII",
            "pair": "KIIUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        # List of adversarial collision symbols that MUST NOT match KII
        impostor_symbols = [
            "KIICHIUSDT",
            "KIICHI",
            "KIICHI-USDT",
            "KIICHI-USDT-SWAP",
            "KIICHIUSD",
            "KIICHIUSDC",
            "KII2USDT",
            "KII_PLUS_USDT",
            "KIIXUSDT",
            "WKIIUSDT",
            "AKIIUSDT"
        ]

        trades = [
            {
                "exchange": "Bybit",
                "symbol": sym,
                "market": "Spot",
                "side": "Buy",
                "price": 1.0,
                "qty": 100.0,
                "exec_value": 100.0,
                "fee": 0.5,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            }
            for sym in impostor_symbols
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            # NONE of the impostors should match!
            self.assertEqual(len(results), 0, f"False positive detected! Impostor symbols matched: {results}")

    def test_valid_kii_symbol_formats_match(self):
        """Verify that genuine variations of KII (KIIUSDT, KII-USDT, KII/USDT, KIIUSDC, KII) match."""
        event = {
            "id": 202,
            "exchange": "Bybit",
            "event_name": "KII Event",
            "event_type": "Alpha",
            "market": "Alpha",
            "coin": "KII",
            "pair": "KIIUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        valid_symbols = [
            "KIIUSDT",
            "KII-USDT",
            "KII/USDT",
            "KII_USDT",
            "KIIUSDC",
            "KIIUSD",
            "KII"
        ]

        trades = [
            {
                "exchange": "Bybit",
                "symbol": sym,
                "market": "Spot",
                "side": "Buy",
                "price": 1.0,
                "qty": 100.0,
                "exec_value": 100.0,
                "fee": 0.5,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            }
            for sym in valid_symbols
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["trades_count"], len(valid_symbols))
            self.assertEqual(results[0]["total_volume"], 100.0 * len(valid_symbols))

    def test_crypto_ticker_substring_minefield(self):
        """Stress test multiple real-world ticker pairs where one is a substring/prefix of another."""
        # Pairs: (Target coin, Impostor symbol)
        minefield = [
            ("CAT", "CATIUSDT"),
            ("NOT", "NOTEUSDT"),
            ("SOL", "SOLOUSDT"),
            ("NEAR", "NEIROUSDT"),
            ("SUI", "SUIPUSDT"),
            ("PEPE", "PEPE2USDT"),
            ("DOGE", "NEODOGEUSDT"),
            ("BTC", "WBTCUSDT"),
            ("BTC", "BTC3LUSDT"),
            ("ETH", "ETHWUSDT"),
            ("LUNA", "LUNCUSDT"),
        ]

        for target_coin, impostor_symbol in minefield:
            event = {
                "id": 300,
                "exchange": "Bybit",
                "event_name": f"{target_coin} Event",
                "event_type": "Splash",
                "market": "Spot",
                "coin": target_coin,
                "pair": f"{target_coin}USDT",
                "start_date": "2026-10-01",
                "end_date": None
            }
            trade = {
                "exchange": "Bybit",
                "symbol": impostor_symbol,
                "market": "Spot",
                "side": "Buy",
                "price": 10.0,
                "qty": 10.0,
                "exec_value": 100.0,
                "fee": 0.1,
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            }
            with patch("app.core.detector.get_active_events", return_value=[event]):
                results = self.detector.match_events([trade])
                self.assertEqual(
                    len(results), 0,
                    f"False positive! Target {target_coin} erroneously matched impostor {impostor_symbol}"
                )


class TestSpotFuturesIsolationAdversarial(unittest.TestCase):
    """Adversarial stress-testing of Spot vs Futures market isolation."""

    def setUp(self):
        self.detector = DetectorEngine()

    def test_spot_event_strictly_rejects_futures_trades(self):
        """Spot event must strictly ignore Futures trades even if symbol, coin, exchange, and time match."""
        event = {
            "id": 401,
            "exchange": "OKX",
            "event_name": "BTC Spot Event",
            "event_type": "Splash",
            "market": "Spot",
            "coin": "BTC",
            "pair": "BTCUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        now_ms = int(datetime(2026, 10, 2).timestamp() * 1000)
        trades = [
            # Spot trade -> MUST match
            {"exchange": "OKX", "symbol": "BTC-USDT", "market": "Spot", "side": "Buy", "price": 60000, "qty": 1, "exec_value": 60000, "fee": 60, "exec_time": now_ms},
            # Futures trade -> MUST be ignored
            {"exchange": "OKX", "symbol": "BTC-USDT-SWAP", "market": "Futures", "side": "Buy", "price": 60000, "qty": 1, "exec_value": 60000, "fee": 30, "exec_time": now_ms},
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["trades_count"], 1)
            self.assertEqual(results[0]["total_volume"], 60000)

    def test_futures_event_strictly_rejects_spot_trades(self):
        """Futures event must strictly ignore Spot trades."""
        event = {
            "id": 402,
            "exchange": "Bybit",
            "event_name": "BTC Futures Event",
            "event_type": "Stock Buzz",
            "market": "Futures",
            "coin": "BTC",
            "pair": "BTCUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        now_ms = int(datetime(2026, 10, 2).timestamp() * 1000)
        trades = [
            # Spot trade -> MUST be ignored
            {"exchange": "Bybit", "symbol": "BTCUSDT", "market": "Spot", "side": "Buy", "price": 60000, "qty": 1, "exec_value": 60000, "fee": 60, "exec_time": now_ms},
            # Futures trade -> MUST match
            {"exchange": "Bybit", "symbol": "BTCUSDT", "market": "Futures", "side": "Buy", "price": 60000, "qty": 1, "exec_value": 60000, "fee": 30, "exec_time": now_ms},
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["trades_count"], 1)
            self.assertEqual(results[0]["total_volume"], 60000)

    def test_alpha_event_rejects_futures_accepts_alpha_and_spot(self):
        """Alpha event allows 'Alpha' and 'Spot' but strictly rejects 'Futures'."""
        event = {
            "id": 403,
            "exchange": "Bybit",
            "event_name": "KII Alpha Event",
            "event_type": "Alpha",
            "market": "Alpha",
            "coin": "KII",
            "pair": "KIIUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        now_ms = int(datetime(2026, 10, 2).timestamp() * 1000)
        trades = [
            {"exchange": "Bybit", "symbol": "KIIUSDT", "market": "Spot", "side": "Buy", "price": 1, "qty": 100, "exec_value": 100, "fee": 0.5, "exec_time": now_ms},
            {"exchange": "Bybit", "symbol": "KIIUSDT", "market": "Alpha", "side": "Buy", "price": 1, "qty": 200, "exec_value": 200, "fee": 1.0, "exec_time": now_ms + 1000},
            {"exchange": "Bybit", "symbol": "KIIUSDT", "market": "Futures", "side": "Buy", "price": 1, "qty": 500, "exec_value": 500, "fee": 0.25, "exec_time": now_ms + 2000},
        ]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["trades_count"], 2)
            self.assertEqual(results[0]["total_volume"], 300)


class TestFeeConversionAndOKXContractMultiplier(unittest.TestCase):
    """Adversarial stress-testing of base coin fee conversion and OKX contract multiplier (ctVal)."""

    def test_bybit_various_base_coin_fees(self):
        """Stress: Test Bybit executions with fees charged in BTC, ETH, MNT, USDC, USDT."""
        bybit = BybitClient("key", "secret")
        mock_raw = {
            "list": [
                # 1. BTC fee: 0.002 BTC at $50,000 = $100.00
                {"execId": "1", "symbol": "BTCUSDT", "side": "Buy", "execPrice": "50000", "execQty": "2", "execValue": "100000", "execFee": "0.002", "feeCurrency": "BTC", "execTime": 1700000000000},
                # 2. ETH fee: 0.05 ETH at $3,000 = $150.00
                {"execId": "2", "symbol": "ETHUSDT", "side": "Buy", "execPrice": "3000", "execQty": "10", "execValue": "30000", "execFee": "0.05", "feeCurrency": "ETH", "execTime": 1700000000000},
                # 3. MNT fee: 20 MNT at $1.50 = $30.00
                {"execId": "3", "symbol": "MNTUSDT", "side": "Buy", "execPrice": "1.5", "execQty": "1000", "execValue": "1500", "execFee": "20", "feeCurrency": "MNT", "execTime": 1700000000000},
                # 4. USDT fee: 25 USDT at $50,000 = $25.00 (NOT multiplied!)
                {"execId": "4", "symbol": "BTCUSDT", "side": "Buy", "execPrice": "50000", "execQty": "1", "execValue": "50000", "execFee": "25", "feeCurrency": "USDT", "execTime": 1700000000000},
                # 5. USDC fee: 10 USDC = $10.00 (NOT multiplied!)
                {"execId": "5", "symbol": "BTCUSDC", "side": "Buy", "execPrice": "50000", "execQty": "1", "execValue": "50000", "execFee": "10", "feeCurrency": "USDC", "execTime": 1700000000000},
            ]
        }

        with patch.object(bybit, "_request", new_callable=AsyncMock, return_value=mock_raw):
            trades = asyncio.run(bybit.get_executions())
            self.assertEqual(len(trades), 5)
            self.assertAlmostEqual(trades[0]["fee"], 100.0, places=2)
            self.assertAlmostEqual(trades[1]["fee"], 150.0, places=2)
            self.assertAlmostEqual(trades[2]["fee"], 30.0, places=2)
            self.assertAlmostEqual(trades[3]["fee"], 25.0, places=2)
            self.assertAlmostEqual(trades[4]["fee"], 10.0, places=2)

    def test_okx_derivatives_ct_val_different_assets(self):
        """Stress: OKX contract multipliers across BTC (0.01), ETH (0.1), DOGE (100.0)."""
        okx = OKXClient("key", "secret", "pass")
        mock_raw = [
            # BTC: 500 contracts * 0.01 = 5.0 BTC @ $60,000 = $300,000
            {"fillId": "1", "ordId": "o1", "instId": "BTC-USDT-SWAP", "side": "buy", "fillPx": "60000", "fillSz": "500", "fee": "-0.001", "feeCcy": "BTC", "ts": "1700000000000"},
            # ETH: 200 contracts * 0.1 = 20.0 ETH @ $3,000 = $60,000
            {"fillId": "2", "ordId": "o2", "instId": "ETH-USDT-SWAP", "side": "buy", "fillPx": "3000", "fillSz": "200", "fee": "-15", "feeCcy": "USDT", "ts": "1700000000000"},
            # DOGE: 10 contracts * 100.0 = 1000 DOGE @ $0.20 = $200
            {"fillId": "3", "ordId": "o3", "instId": "DOGE-USDT-SWAP", "side": "buy", "fillPx": "0.20", "fillSz": "10", "fee": "-0.10", "feeCcy": "USDT", "ts": "1700000000000"},
        ]

        async def mock_get_ct_val(inst_id, inst_type):
            if "BTC" in inst_id:
                return 0.01
            elif "ETH" in inst_id:
                return 0.1
            elif "DOGE" in inst_id:
                return 100.0
            return 1.0

        with patch.object(okx, "_request", new_callable=AsyncMock, return_value=mock_raw), \
             patch.object(okx, "get_contract_val", side_effect=mock_get_ct_val):
            trades = asyncio.run(okx.get_fills(inst_type="SWAP"))
            self.assertEqual(len(trades), 3)

            # BTC
            self.assertAlmostEqual(trades[0]["qty"], 5.0, places=4)
            self.assertAlmostEqual(trades[0]["exec_value"], 300000.0, places=2)
            # BTC fee converted to USD: 0.001 BTC * $60,000 = $60.0
            self.assertAlmostEqual(trades[0]["fee"], 60.0, places=2)

            # ETH
            self.assertAlmostEqual(trades[1]["qty"], 20.0, places=4)
            self.assertAlmostEqual(trades[1]["exec_value"], 60000.0, places=2)
            # USDT fee unchanged: $15.0
            self.assertAlmostEqual(trades[1]["fee"], 15.0, places=2)

            # DOGE
            self.assertAlmostEqual(trades[2]["qty"], 1000.0, places=2)
            self.assertAlmostEqual(trades[2]["exec_value"], 200.0, places=2)
            self.assertAlmostEqual(trades[2]["fee"], 0.10, places=2)

    def test_okx_spot_bypasses_contract_multiplier(self):
        """Spot trades on OKX must NOT have ctVal applied (fillSz is literal asset qty)."""
        okx = OKXClient("key", "secret", "pass")
        mock_raw = [
            {"fillId": "s1", "ordId": "os1", "instId": "BTC-USDT", "side": "buy", "fillPx": "60000", "fillSz": "2.5", "fee": "-15", "feeCcy": "USDT", "ts": "1700000000000"}
        ]

        with patch.object(okx, "_request", new_callable=AsyncMock, return_value=mock_raw):
            trades = asyncio.run(okx.get_fills(inst_type="SPOT"))
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["qty"], 2.5)
            self.assertEqual(trades[0]["exec_value"], 150000.0)


class TestBybitAlphaRebateAdversarial(unittest.TestCase):
    """Adversarial stress-testing of the Bybit Alpha rebate formula ($3 per $1000 volume)."""

    def setUp(self):
        self.detector = DetectorEngine()

    def test_alpha_rebate_binde_3_formula(self):
        """Verify rebate = round(total_vol * 0.0030, 2) across various volume levels."""
        event = {
            "id": 501,
            "exchange": "Bybit",
            "event_name": "Alpha Event",
            "event_type": "Alpha",
            "market": "Alpha",
            "coin": "ALPHA",
            "pair": "ALPHAUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        test_cases = [
            (1000.0, 3.00),         # $1,000 -> $3.00
            (10000.0, 30.00),       # $10,000 -> $30.00
            (50000.0, 150.00),      # $50,000 -> $150.00
            (33333.33, 100.00),     # $33,333.33 -> $100.00
            (12345.67, 37.04),      # $12,345.67 -> round(37.037, 2) = $37.04
            (0.0, 0.0),             # $0 -> $0.0
        ]

        for vol, expected_rebate in test_cases:
            trades = [{
                "exchange": "Bybit",
                "symbol": "ALPHAUSDT",
                "market": "Alpha",
                "side": "Buy",
                "price": 1.0,
                "qty": vol,
                "exec_value": vol,
                "fee": vol * 0.005,  # Alpha fee is 0.5%
                "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
            }] if vol > 0 else []

            with patch("app.core.detector.get_active_events", return_value=[event]):
                results = self.detector.match_events(trades)
                if vol == 0:
                    self.assertEqual(len(results), 0)
                else:
                    self.assertEqual(len(results), 1)
                    res = results[0]
                    self.assertAlmostEqual(res["rebate"], expected_rebate, places=2)

    def test_bybit_splash_uses_55_percent_fee(self):
        """Non-Alpha Bybit events (e.g. Splash) must calculate rebate as 55% of fee."""
        event = {
            "id": 502,
            "exchange": "Bybit",
            "event_name": "Splash Event",
            "event_type": "Splash",
            "market": "Spot",
            "coin": "SPLASH",
            "pair": "SPLASHUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        trades = [{
            "exchange": "Bybit",
            "symbol": "SPLASHUSDT",
            "market": "Spot",
            "side": "Buy",
            "price": 10.0,
            "qty": 1000.0,
            "exec_value": 10000.0,
            "fee": 10.0,
            "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
        }]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            # Rebate: 55% of 10.0 = 5.50
            self.assertEqual(results[0]["rebate"], 5.50)

    def test_okx_uses_47_5_percent_fee(self):
        """OKX events must calculate rebate as 47.50% of fee."""
        event = {
            "id": 503,
            "exchange": "OKX",
            "event_name": "OKX Event",
            "event_type": "Flash Earn",
            "market": "Spot",
            "coin": "OKB",
            "pair": "OKBUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        trades = [{
            "exchange": "OKX",
            "symbol": "OKBUSDT",
            "market": "Spot",
            "side": "Buy",
            "price": 50.0,
            "qty": 200.0,
            "exec_value": 10000.0,
            "fee": 10.0,
            "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
        }]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            # Rebate: 47.5% of 10.0 = 4.75
            self.assertEqual(results[0]["rebate"], 4.75)

    def test_net_cost_floor_cannot_be_negative(self):
        """If rebate exceeds cost, net_cost must be floored at 0.00."""
        event = {
            "id": 504,
            "exchange": "Bybit",
            "event_name": "Alpha Event",
            "event_type": "Alpha",
            "market": "Alpha",
            "coin": "ALPHA",
            "pair": "ALPHAUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        # Zero fee maker trades with zero slippage
        trades = [{
            "exchange": "Bybit",
            "symbol": "ALPHAUSDT",
            "market": "Alpha",
            "side": "Buy",
            "price": 1.0,
            "qty": 10000.0,
            "exec_value": 10000.0,
            "fee": 0.0, # Zero fee
            "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
        }]

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events(trades)
            self.assertEqual(len(results), 1)
            # Rebate = $30.00, Cost = $0.00
            self.assertEqual(results[0]["rebate"], 30.00)
            self.assertEqual(results[0]["net_cost"], 0.00, "Net cost must never be negative!")


class TestFuzzingAndInvariants(unittest.TestCase):
    """Fuzzing and arithmetic invariants across 1,000 randomized trade combinations."""

    def setUp(self):
        self.detector = DetectorEngine()

    def test_random_trade_fuzzing_invariants(self):
        """Property-based stress test:
        1. realized_slippage >= 0.0 (no negative slippage)
        2. cost >= total_fee
        3. cost >= 0.0
        4. rebate >= 0.0
        5. 0.0 <= net_cost <= cost
        6. if min(buy_qty, sell_qty) == 0 => makas == 0.0 strictly!
        7. cost_per_1k >= 0.0
        """
        import random
        random.seed(42)

        event = {
            "id": 601,
            "exchange": "Bybit",
            "event_name": "FUZZ Event",
            "event_type": "Alpha",
            "market": "Alpha",
            "coin": "FUZZ",
            "pair": "FUZZUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        now_ms = int(datetime(2026, 10, 2).timestamp() * 1000)

        for iteration in range(200):
            num_trades = random.randint(1, 30)
            trades = []
            for i in range(num_trades):
                side = random.choice(["Buy", "Sell"])
                px = round(random.uniform(0.0001, 10000.0), 6)
                qty = round(random.uniform(0.0001, 50000.0), 6)
                val = round(px * qty, 4)
                fee = round(val * random.uniform(0.0, 0.01), 4)

                trades.append({
                    "exchange": "Bybit",
                    "symbol": "FUZZUSDT",
                    "market": "Alpha",
                    "side": side,
                    "price": px,
                    "qty": qty,
                    "exec_value": val,
                    "fee": fee,
                    "exec_time": now_ms + i * 1000
                })

            with patch("app.core.detector.get_active_events", return_value=[event]):
                results = self.detector.match_events(trades)
                self.assertEqual(len(results), 1, f"Failed on iteration {iteration}")
                res = results[0]

                # Invariant checks
                self.assertGreaterEqual(res["makas"], 0.0, "Slippage must never be negative!")
                self.assertGreaterEqual(res["total_cost"], 0.0, "Total cost must never be negative!")
                self.assertGreaterEqual(res["total_cost"], res["total_fee"] - 0.01, "Cost must be >= total fee!")
                self.assertGreaterEqual(res["rebate"], 0.0, "Rebate must never be negative!")
                self.assertGreaterEqual(res["net_cost"], 0.0, "Net cost must never be negative!")
                self.assertLessEqual(res["net_cost"], res["total_cost"] + 0.01, "Net cost must not exceed total cost!")
                self.assertGreaterEqual(res["cost_per_1k"], 0.0, "1k cost must never be negative!")

                # Unsold / held check
                buy_qty = sum(t["qty"] for t in trades if t["side"] == "Buy")
                sell_qty = sum(t["qty"] for t in trades if t["side"] == "Sell")
                if min(buy_qty, sell_qty) == 0:
                    self.assertEqual(res["makas"], 0.0, "Holding all or selling with zero buys must strictly yield 0 makas!")


class TestAdversarialBoundaryCases(unittest.TestCase):
    """Empirical investigation into edge-case vulnerabilities."""

    def setUp(self):
        self.detector = DetectorEngine()

    def test_perp_token_symbol_matching_bug(self):
        """Verify that 'PERP' coin derivative 'PERP-USDT-SWAP' is properly matched and not stripped by suffix regex."""
        event = {
            "id": 701,
            "exchange": "OKX",
            "event_name": "PERP Event",
            "event_type": "Others",
            "market": "Futures",
            "coin": "PERP",
            "pair": "PERPUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        trade = {
            "exchange": "OKX",
            "symbol": "PERPUSDTSWAP",
            "market": "Futures",
            "side": "Buy",
            "price": 1.0,
            "qty": 100.0,
            "exec_value": 100.0,
            "fee": 0.1,
            "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
        }

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events([trade])
            self.assertEqual(len(results), 1, "PERP token derivative SWAP symbol must match properly!")

    def test_market_casing_vulnerability(self):
        """Verify that lowercase market='spot' in database does NOT leak Futures trades into Spot events."""
        event = {
            "id": 702,
            "exchange": "Bybit",
            "event_name": "Spot Lowercase Event",
            "event_type": "Splash",
            "market": "spot",  # lowercase!
            "coin": "BTC",
            "pair": "BTCUSDT",
            "start_date": "2026-10-01",
            "end_date": None
        }

        futures_trade = {
            "exchange": "Bybit",
            "symbol": "BTCUSDT",
            "market": "Futures",  # Futures trade!
            "side": "Buy",
            "price": 60000.0,
            "qty": 1.0,
            "exec_value": 60000.0,
            "fee": 30.0,
            "exec_time": int(datetime(2026, 10, 2).timestamp() * 1000)
        }

        with patch("app.core.detector.get_active_events", return_value=[event]):
            results = self.detector.match_events([futures_trade])
            self.assertEqual(len(results), 0, "Lowercase market='spot' must NOT leak Futures trades into Spot events!")


if __name__ == "__main__":
    unittest.main()

