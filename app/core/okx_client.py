import time
import base64
import hmac
import hashlib
import json
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode

class OKXClient:
    BASE_URL = "https://www.okx.com"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, passphrase: Optional[str] = None, simulated: bool = False):
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self.passphrase = (passphrase or "").strip()
        self.simulated = simulated
        self._ct_val_cache: Dict[str, float] = {}

    def _get_timestamp(self) -> str:
        # OKX requires ISO 8601 UTC timestamp format: YYYY-MM-DDTHH:MM:SS.sssZ
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(self.api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode("utf-8")

    async def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        timestamp = self._get_timestamp()
        params = params or {}
        
        request_path = endpoint
        if method.upper() == "GET" and params:
            query_string = urlencode(sorted(params.items()))
            request_path = f"{endpoint}?{query_string}"

        signature = self._generate_signature(timestamp, method, request_path, "")

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }
        if self.simulated:
            headers["x-simulated-trading"] = "1"

        url = f"{self.BASE_URL}{request_path}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(method, url, headers=headers)
            data = resp.json()
            if data.get("code") != "0":
                raise Exception(f"OKX API Error ({data.get('code')}): {data.get('msg')}")
            return data.get("data", [])

    async def test_connection(self) -> Dict[str, Any]:
        """Verify OKX credentials by fetching user trade fee rate and tier."""
        try:
            res = await self._request("GET", "/api/v5/account/trade-fee", {"instType": "SPOT"})
            tier = "Regular user"
            maker_rate = "0.080%"
            taker_rate = "0.100%"
            if res:
                tier = res[0].get("level", "Regular user") or "Regular user"
                maker_rate = f"{abs(float(res[0].get('maker', 0.08))) * 100:.3f}%"
                taker_rate = f"{abs(float(res[0].get('taker', 0.10))) * 100:.3f}%"
            return {
                "success": True,
                "exchange": "OKX",
                "vip_tier": tier,
                "spot_maker_fee": maker_rate,
                "spot_taker_fee": taker_rate,
                "message": f"Bağlantı başarılı! Seviyeniz: {tier}"
            }
        except Exception as e:
            return {
                "success": False,
                "exchange": "OKX",
                "error": str(e),
                "message": f"OKX Bağlantı Hatası: {str(e)}"
            }

    async def get_contract_val(self, inst_id: str, inst_type: str = "SWAP") -> float:
        """Fetch and cache contract value (ctVal) for derivative instruments."""
        if not inst_id or inst_type == "SPOT":
            return 1.0
        if inst_id in self._ct_val_cache:
            return self._ct_val_cache[inst_id]
        try:
            res = await self._request("GET", "/api/v5/public/instruments", {"instType": inst_type, "instId": inst_id})
            if res and len(res) > 0:
                val = float(res[0].get("ctVal") or 1.0)
                self._ct_val_cache[inst_id] = val
                return val
        except Exception:
            pass
        return 1.0

    async def get_fills(self, inst_type: str = "SPOT", inst_id: Optional[str] = None,
                        limit: int = 100, max_trades: int = 1000) -> List[Dict[str, Any]]:
        """
        Fetch trade fills history from OKX V5 endpoint with pagination.
        Supports contract value multiplier for derivatives and converts base coin fees to USD.
        """
        normalized: List[Dict[str, Any]] = []
        after: Optional[str] = None

        while True:
            params: Dict[str, Any] = {
                "instType": inst_type,
                "limit": min(limit, 100)
            }
            if inst_id:
                params["instId"] = inst_id.upper()
            if after:
                params["after"] = after

            raw_list = await self._request("GET", "/api/v5/trade/fills", params)
            if not raw_list:
                break

            for item in raw_list:
                price = float(item.get("fillPx") or 0.0)
                sz = float(item.get("fillSz") or 0.0)
                symbol_raw = item.get("instId", "")

                # For derivative contracts (SWAP / FUTURES), fillSz represents contracts.
                # Multiply by ctVal to get true base currency quantity and USD notional value.
                if inst_type in ["SWAP", "FUTURES"]:
                    ct_val = await self.get_contract_val(symbol_raw, inst_type)
                    qty = sz * ct_val
                    exec_val = price * qty
                else:
                    qty = sz
                    exec_val = price * qty

                fee = abs(float(item.get("fee") or 0.0))
                fee_ccy = str(item.get("feeCcy") or "").strip().upper()
                
                # If fee is charged in base currency (e.g. BTC, ETH) instead of USDT/USDC, convert to USD
                if fee_ccy and fee_ccy not in ["USDT", "USDC", "USD"] and price > 0:
                    fee = fee * price

                fee_rate = float(item.get("feeRate") or 0.0)
                if fee_rate == 0.0 and exec_val > 0:
                    fee_rate = fee / exec_val

                symbol_clean = symbol_raw.replace("-", "")

                normalized.append({
                    "exchange": "OKX",
                    "exec_id": str(item.get("fillId") or item.get("tradeId") or item.get("billId")),
                    "order_id": str(item.get("ordId")),
                    "symbol": symbol_clean,
                    "side": item.get("side", "").capitalize(),
                    "price": price,
                    "qty": qty,
                    "exec_value": exec_val,
                    "fee": fee,
                    "fee_rate": fee_rate,
                    "exec_time": int(item.get("ts", 0)),
                    "market": "Futures" if inst_type in ["SWAP", "FUTURES"] else "Spot",
                    "is_maker": item.get("execType") == "M"
                })

            if len(normalized) >= max_trades or len(raw_list) < limit:
                break

            # OKX pagination cursor for older records
            last_record = raw_list[-1]
            after = str(last_record.get("billId") or last_record.get("tradeId") or last_record.get("fillId") or "")
            if not after:
                break

        return normalized
