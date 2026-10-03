import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.config import settings
from app.core.bybit_client import BybitClient
from app.core.okx_client import OKXClient
from app.database.models import get_active_events, save_trades_to_cache

class DetectorEngine:
    def __init__(self):
        self.bybit = BybitClient(settings.BYBIT_API_KEY, settings.BYBIT_API_SECRET, settings.BYBIT_TESTNET)
        self.okx = OKXClient(settings.OKX_API_KEY, settings.OKX_API_SECRET, settings.OKX_PASSPHRASE, settings.OKX_IS_SIMULATED)

    async def fetch_and_cache_trades(self) -> Dict[str, Any]:
        """Fetch trades from both exchanges and save to SQLite trade_cache."""
        bybit_count = 0
        okx_count = 0
        errors: List[str] = []

        # Bybit Spot & Linear
        if settings.BYBIT_API_KEY and settings.BYBIT_API_SECRET:
            try:
                spot_trades = await self.bybit.get_executions(category="spot", limit=100)
                linear_trades = await self.bybit.get_executions(category="linear", limit=100)
                all_bybit = spot_trades + linear_trades
                bybit_count = save_trades_to_cache(all_bybit)
            except Exception as e:
                err_msg = f"Bybit: {str(e)}"
                print(f"[Detector Bybit Error]: {err_msg}")
                errors.append(err_msg)

        # OKX Spot & Futures
        if settings.OKX_API_KEY and settings.OKX_API_SECRET:
            try:
                spot_trades = await self.okx.get_fills(inst_type="SPOT", limit=100)
                swap_trades = await self.okx.get_fills(inst_type="SWAP", limit=100)
                all_okx = spot_trades + swap_trades
                okx_count = save_trades_to_cache(all_okx)
            except Exception as e:
                err_msg = f"OKX: {str(e)}"
                print(f"[Detector OKX Error]: {err_msg}")
                errors.append(err_msg)

        return {
            "bybit_new": bybit_count,
            "okx_new": okx_count,
            "errors": errors,
            "success": len(errors) == 0
        }

    def match_events(self, raw_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Match trades against active events and aggregate volume, fees, slippage and net cost.
        """
        active_events = get_active_events()
        results: List[Dict[str, Any]] = []

        for event in active_events:
            ev_exchange = event["exchange"]
            ev_coin = event["coin"].upper()
            ev_pair = event["pair"].upper()
            ev_market = str(event.get("market", "")).strip().capitalize()
            ev_type = event["event_type"]

            # Parse start date to timestamp ms
            try:
                dt_start = datetime.strptime(event["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                start_ts = int(dt_start.timestamp() * 1000)
            except Exception:
                start_ts = 0

            end_ts = float("inf")
            if event.get("end_date"):
                try:
                    dt_end = datetime.strptime(event["end_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    end_ts = int(dt_end.timestamp() * 1000) + 86400000 # end of day
                except Exception:
                    pass

            # Filter matching trades
            matched_trades = []
            for t in raw_trades:
                if str(t.get("exchange", "")).lower() != str(ev_exchange).lower():
                    continue

                # 1. Market matching (Spot vs Futures vs Alpha)
                t_market = str(t.get("market", "Spot")).strip().capitalize()
                if ev_market == "Spot" and t_market != "Spot":
                    continue
                elif ev_market == "Futures" and t_market != "Futures":
                    continue
                elif ev_market == "Alpha" and t_market not in ["Alpha", "Spot"]:
                    continue

                # 2. Strict Symbol matching (prevent coin prefix false-positives e.g. KIICHI vs KII)
                sym_raw = t["symbol"].upper()
                sym_clean = sym_raw.replace("-", "").replace("/", "").replace("_", "")
                sym_no_deriv = re.sub(r'(SWAP|PERP)$', '', sym_clean)
                
                valid_symbols = {
                    ev_coin,
                    f"{ev_coin}USDT",
                    f"{ev_coin}USDC",
                    f"{ev_coin}USD",
                    ev_pair.replace("-", "").replace("/", "").replace("_", "")
                }

                if sym_clean not in valid_symbols and sym_no_deriv not in valid_symbols:
                    continue

                # 3. Timestamp matching
                if not (start_ts <= t["exec_time"] <= end_ts):
                    continue

                matched_trades.append(t)

            if not matched_trades:
                continue

            # Calculate aggregated volume & fees
            total_vol = sum(t["exec_value"] for t in matched_trades)
            total_fee = sum(t["fee"] for t in matched_trades)
            avg_fee_rate = (total_fee / total_vol) if total_vol > 0 else 0.0

            buy_trades = [t for t in matched_trades if t["side"].lower() == "buy"]
            sell_trades = [t for t in matched_trades if t["side"].lower() == "sell"]

            buy_val = sum(t["exec_value"] for t in buy_trades)
            buy_qty = sum(t["qty"] for t in buy_trades)
            sell_val = sum(t["exec_value"] for t in sell_trades)
            sell_qty = sum(t["qty"] for t in sell_trades)

            # Realized slippage is only calculated on closed (round-trip) volume.
            # Holding remaining unsold assets does NOT generate fake spread/slippage cost!
            closed_qty = min(buy_qty, sell_qty)
            realized_slippage = 0.0

            if closed_qty > 0:
                avg_buy_px = buy_val / buy_qty if buy_qty > 0 else 0.0
                avg_sell_px = sell_val / sell_qty if sell_qty > 0 else 0.0
                realized_slippage = max(0.0, (avg_buy_px - avg_sell_px) * closed_qty)

            cost = round(total_fee + realized_slippage, 2)
            total_fee = round(total_fee, 2)
            makas = round(realized_slippage, 2)
            cost_per_1k = round((cost / total_vol * 1000), 3) if total_vol > 0 else 0.0

            # Rebate calculation
            if str(ev_exchange).lower() == "bybit":
                if ev_market == "Alpha" or ev_type == "Alpha":
                    # Fix Binde 3 ($3 / 1000$ volume = 60% of binde 5 fee)
                    rebate = round(total_vol * 0.0030, 2)
                else:
                    # Bybit normal %55
                    rebate = round(total_fee * 0.55, 2)
            else:
                # OKX %47.50
                rebate = round(total_fee * 0.4750, 2)

            net_cost = round(max(0.0, cost - rebate), 2)

            results.append({
                "event_id": event["id"],
                "exchange": ev_exchange,
                "event_name": event["event_name"],
                "event_type": ev_type,
                "market": ev_market,
                "coin": ev_coin,
                "date": event["start_date"],
                "trades_count": len(matched_trades),
                "total_volume": round(total_vol, 2),
                "total_cost": cost,
                "cost_per_1k": cost_per_1k,
                "total_fee": total_fee,
                "fee_rate": round(avg_fee_rate, 6),
                "makas": makas,
                "rebate": rebate,
                "net_cost": net_cost,
                "target_volume": event.get("target_volume", 0)
            })

        return results
