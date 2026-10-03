import time
import hmac
import hashlib
import json
import httpx
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode

class BybitClient:
    MAINNET_URL = "https://api.bybit.com"
    TESTNET_URL = "https://api-testnet.bybit.com"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, testnet: bool = False):
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL
        self.recv_window = "5000"

    def _generate_signature(self, timestamp: str, query_or_body: str) -> str:
        param_str = timestamp + self.api_key + self.recv_window + query_or_body
        return hmac.new(
            self.api_secret.encode("utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    async def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        timestamp = str(int(time.time() * 1000))
        params = params or {}
        
        # Sort query params
        query_string = urlencode(sorted(params.items())) if method.upper() == "GET" and params else ""
        signature = self._generate_signature(timestamp, query_string)

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "X-BAPI-SIGN": signature,
            "Content-Type": "application/json"
        }

        url = f"{self.base_url}{endpoint}"
        if query_string:
            url += f"?{query_string}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(method, url, headers=headers)
            data = resp.json()
            if data.get("retCode") != 0:
                raise Exception(f"Bybit API Error ({data.get('retCode')}): {data.get('retMsg')}")
            return data.get("result", {})

    async def test_connection(self) -> Dict[str, Any]:
        """Verify API keys by fetching account fee rates and VIP status."""
        try:
            res = await self._request("GET", "/v5/account/fee-rate", {"category": "spot"})
            tier = "Regular User"
            maker_rate = "0.075%"
            taker_rate = "0.075%"
            list_res = res.get("list", [])
            if list_res:
                tier = list_res[0].get("vipLevel", "VIP") or "Regular User"
                maker_rate = list_res[0].get("makerFeeRate", "0.075%")
                taker_rate = list_res[0].get("takerFeeRate", "0.075%")
            return {
                "success": True,
                "exchange": "Bybit",
                "vip_tier": tier,
                "spot_maker_fee": maker_rate,
                "spot_taker_fee": taker_rate,
                "message": f"Bağlantı başarılı! Seviyeniz: {tier}"
            }
        except Exception as e:
            return {
                "success": False,
                "exchange": "Bybit",
                "error": str(e),
                "message": f"Bybit Bağlantı Hatası: {str(e)}"
            }

    async def get_executions(self, category: str = "spot", symbol: Optional[str] = None,
                             start_time: Optional[int] = None, end_time: Optional[int] = None,
                             limit: int = 100, max_trades: int = 1000) -> List[Dict[str, Any]]:
        """
        Fetch trade executions from Bybit V5 execution/list endpoint.
        Supports cursor pagination to fetch all recent trades up to max_trades.
        Converts non-USD/USDT fees (e.g. base coin fees) to USD equivalent using execPrice.
        """
        normalized: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        while True:
            params: Dict[str, Any] = {
                "category": category,
                "limit": min(limit, 100)
            }
            if symbol:
                params["symbol"] = symbol.upper()
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            if cursor:
                params["cursor"] = cursor

            res = await self._request("GET", "/v5/execution/list", params)
            raw_list = res.get("list", [])
            if not raw_list:
                break

            for item in raw_list:
                exec_val = float(item.get("execValue") or 0.0)
                exec_qty = float(item.get("execQty") or 0.0)
                exec_price = float(item.get("execPrice") or 0.0)
                if exec_val == 0.0 and exec_qty > 0 and exec_price > 0:
                    exec_val = exec_qty * exec_price

                fee = abs(float(item.get("execFee") or 0.0))
                fee_currency = str(item.get("feeCurrency") or "").strip().upper()
                
                # If fee is charged in base currency (e.g. BTC, ETH, MNT) instead of USDT/USDC, convert to USD
                if fee_currency and fee_currency not in ["USDT", "USDC", "USD"] and exec_price > 0:
                    fee = fee * exec_price

                fee_rate = float(item.get("feeRate") or 0.0)
                if fee_rate == 0.0 and exec_val > 0:
                    fee_rate = fee / exec_val

                normalized.append({
                    "exchange": "Bybit",
                    "exec_id": str(item.get("execId")),
                    "order_id": str(item.get("orderId")),
                    "symbol": item.get("symbol"),
                    "side": item.get("side"),
                    "price": exec_price,
                    "qty": exec_qty,
                    "exec_value": exec_val,
                    "fee": fee,
                    "fee_rate": fee_rate,
                    "exec_time": int(item.get("execTime")),
                    "market": "Futures" if category == "linear" else "Spot",
                    "is_maker": item.get("isMaker", False)
                })

            if len(normalized) >= max_trades:
                break

            cursor = res.get("nextPageCursor")
            if not cursor:
                break

        return normalized
