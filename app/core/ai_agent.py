import re
import json
from datetime import datetime
from typing import Dict, Any, Optional
from app.config import settings

class AIAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def parse_announcement(self, text: str) -> Dict[str, Any]:
        """
        Extract structured event details from raw announcement text.
        Uses Gemini if API key is present, otherwise falls back to smart regex heuristics.
        """
        if self.is_available():
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                prompt = f"""
                Aşağıdaki kripto para borsa etkinlik duyurusunu analiz et ve JSON formatında yapılandırılmış bilgi çıkar:

                Metin:
                \"\"\"{text}\"\"\"

                Lütfen SADECE aşağıdaki JSON şemasına uygun geçerli bir JSON objesi döndür:
                {{
                    "exchange": "Bybit" veya "OKX",
                    "event_name": "Etkinlik başlığı",
                    "event_type": "Splash", "Alpha", "Stock Buzz", "Puzzle Hunt", "Flash Earn" veya "Others",
                    "market": "Spot", "Futures" veya "Alpha",
                    "coin": "Coin sembolü (Örn: SUI, MNT, BTC, NOT)",
                    "pair": "İşlem çifti (Örn: SUIUSDT)",
                    "start_date": "YYYY-MM-DD formatında başlama tarihi",
                    "end_date": "YYYY-MM-DD formatında bitiş tarihi (yoksa null)",
                    "target_volume": Gerekli hacim dolar cinsinden (sayı, yoksa 0)
                }}
                """
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                if response.text:
                    return json.loads(response.text)
            except Exception as e:
                print(f"[AI Parsing Error]: {e}, fallback heuristic used.")

        # Fallback heuristic parser
        return self._heuristic_parse(text)

    def _heuristic_parse(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower()
        exchange = "Bybit" if "bybit" in text_lower else ("OKX" if "okx" in text_lower else "Bybit")
        
        # Event type
        if "alpha" in text_lower:
            event_type = "Alpha"
            market = "Alpha"
        elif "splash" in text_lower:
            event_type = "Splash"
            market = "Spot"
        elif "stock buzz" in text_lower or "buzz" in text_lower:
            event_type = "Stock Buzz"
            market = "Futures"
        elif "puzzle" in text_lower:
            event_type = "Puzzle Hunt"
            market = "Spot"
        elif "flash earn" in text_lower or "earn" in text_lower:
            event_type = "Flash Earn"
            market = "Spot"
        else:
            event_type = "Others"
            market = "Futures" if "futures" in text_lower or "vadeli" in text_lower else "Spot"

        # Coin search with smart priority and stop-words
        stop_words = {
            "BEYLER", "ARKADASLAR", "ARKADAŞLAR", "DUYURU", "YENI", "YENİ", "ACIL", "ACİL",
            "HAYDI", "HAYDİ", "HABER", "KACIRMAYIN", "KAÇIRMAYIN", "HERKES", "GUYS", "ALERT",
            "NEW", "UPDATE", "FLASH", "EARN", "BYBIT", "OKX", "TOKEN", "COIN", "SPOT",
            "FUTURES", "EVENT", "USDT", "USDC", "USD", "HAVUZ", "ODUL", "ÖDÜL"
        }
        
        coin = "BTC"
        # 1. First priority: Words directly attached to coin/token/USDT (e.g. "SUI coin", "MNT Token", "BTC/USDT")
        prioritized_match = re.search(r'\b([A-Z0-9]{2,10})\s*(?:/USDT|USDT|\s+coin|\s+token|\s+paritesinde)\b', text, re.IGNORECASE)
        if prioritized_match and prioritized_match.group(1).upper() not in stop_words:
            coin = prioritized_match.group(1).upper()
        else:
            # 2. General search: all uppercase words not in stop_words
            candidates = re.findall(r'\b([A-Z]{2,10})\b', text)
            for c in candidates:
                if c.upper() not in stop_words:
                    coin = c.upper()
                    break

        pair = f"{coin}USDT"

        # Date search
        today_str = datetime.now().strftime("%Y-%m-%d")
        start_date = today_str
        date_matches = re.findall(r'(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/.]\d{2}[-/.]\d{4})', text)
        if date_matches:
            try:
                d = date_matches[0].replace("/", "-").replace(".", "-")
                parts = d.split("-")
                if len(parts[0]) == 4:
                    start_date = d
                else:
                    start_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
            except Exception:
                start_date = today_str

        return {
            "exchange": exchange,
            "event_name": f"{coin} {event_type}",
            "event_type": event_type,
            "market": market,
            "coin": coin,
            "pair": pair,
            "start_date": start_date,
            "end_date": None,
            "target_volume": 0.0
        }
