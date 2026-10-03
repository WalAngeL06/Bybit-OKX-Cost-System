import os
import sys
import shutil
import asyncio
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import settings
from app.database.models import add_event, get_all_events, delete_event, log_sync, get_recent_logs
from app.database.db import get_connection, init_db
from app.core.bybit_client import BybitClient
from app.core.okx_client import OKXClient
from app.core.detector import DetectorEngine
from app.core.excel_writer import ExcelWriter
from app.core.ai_agent import AIAgent

from contextlib import asynccontextmanager

sync_lock = asyncio.Lock()

async def auto_sync_worker():
    """Background task running periodic trade sync at AUTO_SYNC_INTERVAL_MINUTES."""
    while True:
        try:
            interval_mins = max(1, settings.AUTO_SYNC_INTERVAL_MINUTES or 15)
            await asyncio.sleep(interval_mins * 60)
            if (settings.BYBIT_API_KEY and settings.BYBIT_API_SECRET) or (settings.OKX_API_KEY and settings.OKX_API_SECRET):
                print(f"[*] Otomatik senkronizasyon çalıştırılıyor (Her {interval_mins} dakikada bir)...")
                await run_sync()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Auto-sync worker error]: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database schema is ready
    init_db()
    # Ensure working excel exists from template if needed
    target_excel = settings.get_excel_absolute_path()
    template_path = Path(__file__).resolve().parent.parent / "bybit-okx_maliyet_template.xlsx"
    if not target_excel.exists() and template_path.exists():
        shutil.copy(template_path, target_excel)
    # Start periodic background synchronization
    sync_task = asyncio.create_task(auto_sync_worker())
    yield
    sync_task.cancel()

app = FastAPI(title="Bybit & OKX Hacim & Maliyet Takip Sistemi", version="1.0.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": f"Sunucu hatası: {str(exc)}"}
    )

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

# --- Pydantic Schemas ---
class SettingsPayload(BaseModel):
    bybit_api_key: Optional[str] = None
    bybit_api_secret: Optional[str] = None
    bybit_testnet: Optional[bool] = None
    okx_api_key: Optional[str] = None
    okx_api_secret: Optional[str] = None
    okx_passphrase: Optional[str] = None
    gemini_api_key: Optional[str] = None

class EventPayload(BaseModel):
    exchange: str
    event_name: str
    event_type: str
    market: str
    coin: str
    pair: Optional[str] = None
    start_date: str
    end_date: Optional[str] = None
    target_volume: Optional[float] = 0.0

class AnnouncementPayload(BaseModel):
    text: str

# --- API Endpoints ---

@app.get("/api/status")
async def get_status():
    excel_path = settings.get_excel_absolute_path()
    return {
        "status": "online",
        "excel_file": str(excel_path),
        "excel_exists": excel_path.exists(),
        "has_bybit": bool(settings.BYBIT_API_KEY and settings.BYBIT_API_SECRET),
        "has_okx": bool(settings.OKX_API_KEY and settings.OKX_API_SECRET and settings.OKX_PASSPHRASE),
        "has_gemini": bool(settings.GEMINI_API_KEY),
        "bybit_testnet": settings.BYBIT_TESTNET,
        "bybit_key_masked": f"{settings.BYBIT_API_KEY[:4]}...{settings.BYBIT_API_KEY[-4:]}" if len(settings.BYBIT_API_KEY) > 8 else "",
        "okx_key_masked": f"{settings.OKX_API_KEY[:4]}...{settings.OKX_API_KEY[-4:]}" if len(settings.OKX_API_KEY) > 8 else ""
    }

@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    new_data = {}
    if payload.bybit_api_key and payload.bybit_api_key.strip():
        new_data["BYBIT_API_KEY"] = payload.bybit_api_key.strip()
    if payload.bybit_api_secret and payload.bybit_api_secret.strip():
        new_data["BYBIT_API_SECRET"] = payload.bybit_api_secret.strip()
    if payload.bybit_testnet is not None:
        new_data["BYBIT_TESTNET"] = "true" if payload.bybit_testnet else "false"

    if payload.okx_api_key and payload.okx_api_key.strip():
        new_data["OKX_API_KEY"] = payload.okx_api_key.strip()
    if payload.okx_api_secret and payload.okx_api_secret.strip():
        new_data["OKX_API_SECRET"] = payload.okx_api_secret.strip()
    if payload.okx_passphrase and payload.okx_passphrase.strip():
        new_data["OKX_PASSPHRASE"] = payload.okx_passphrase.strip()

    if payload.gemini_api_key and payload.gemini_api_key.strip():
        new_data["GEMINI_API_KEY"] = payload.gemini_api_key.strip()

    if new_data:
        settings.save_to_env(new_data)
    return {"success": True, "message": "Ayarlar başarıyla kaydedildi!"}

@app.post("/api/test-keys")
async def test_keys():
    bybit = BybitClient(settings.BYBIT_API_KEY, settings.BYBIT_API_SECRET, settings.BYBIT_TESTNET)
    okx = OKXClient(settings.OKX_API_KEY, settings.OKX_API_SECRET, settings.OKX_PASSPHRASE, settings.OKX_IS_SIMULATED)

    bybit_res = {"success": False, "message": "Bybit API anahtarı girilmedi."}
    if settings.BYBIT_API_KEY and settings.BYBIT_API_SECRET:
        bybit_res = await bybit.test_connection()

    okx_res = {"success": False, "message": "OKX API anahtarı girilmedi."}
    if settings.OKX_API_KEY and settings.OKX_API_SECRET and settings.OKX_PASSPHRASE:
        okx_res = await okx.test_connection()

    return {
        "bybit": bybit_res,
        "okx": okx_res
    }

@app.get("/api/events")
async def list_events():
    return {"events": get_all_events()}

@app.post("/api/events")
async def create_event(payload: EventPayload):
    try:
        coin = payload.coin.strip().upper()
        pair = payload.pair.strip().upper() if payload.pair else f"{coin}USDT"
        event_id = add_event(
            exchange=payload.exchange,
            event_name=payload.event_name,
            event_type=payload.event_type,
            market=payload.market,
            coin=coin,
            pair=pair,
            start_date=payload.start_date,
            end_date=payload.end_date,
            target_volume=payload.target_volume or 0.0
        )
        return {"success": True, "event_id": event_id, "message": "Etkinlik başarıyla eklendi!"}
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": f"Etkinlik eklenirken hata: {str(e)}"}
        )

@app.delete("/api/events/{event_id}")
async def remove_event(event_id: int):
    try:
        delete_event(event_id)
        return {"success": True, "message": "Etkinlik silindi."}
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": f"Etkinlik silinirken hata: {str(e)}"}
        )

@app.post("/api/parse-announcement")
async def parse_announcement(payload: AnnouncementPayload):
    agent = AIAgent()
    parsed = await agent.parse_announcement(payload.text)
    return {"success": True, "data": parsed}

@app.post("/api/sync")
async def run_sync():
    async with sync_lock:
        detector = DetectorEngine()
        excel = ExcelWriter()

        # 1. Fetch trades
        counts = await detector.fetch_and_cache_trades()
        has_errors = len(counts.get("errors", [])) > 0

        # 2. Get all trades from cache to match (no arbitrary 500 limit)
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trade_cache ORDER BY exec_time ASC")
            raw_trades = [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

        # 3. Match events
        detected = detector.match_events(raw_trades)

        # 4. Sync with Excel
        excel_res = excel.sync_detected_events(detected)

        # 5. Determine sync status & message
        if has_errors and not excel_res.get("success"):
            sync_status = "Error"
            log_msg = f"Hata: {'; '.join(counts['errors'])}"
        elif has_errors:
            sync_status = "Warning"
            log_msg = f"Kısmi Senkronizasyon (Hatalar: {'; '.join(counts['errors'])})"
        elif not excel_res.get("success"):
            sync_status = "Error"
            log_msg = f"Excel Yazma Hatası: {excel_res.get('error')}"
        else:
            sync_status = "Success"
            log_msg = f"Bybit ({counts['bybit_new']} yeni), OKX ({counts['okx_new']} yeni), {len(detected)} etkinlik eşleşti."

        # 6. Log
        log_sync(
            exchange="All",
            status=sync_status,
            message=log_msg,
            trades_found=counts["bybit_new"] + counts["okx_new"],
            excel_updated=excel_res.get("success", False)
        )

        is_overall_success = (sync_status in ["Success", "Warning"]) and excel_res.get("success", False)

        return {
            "success": is_overall_success,
            "status": sync_status,
            "errors": counts.get("errors", []),
            "counts": counts,
            "matched_events": detected,
            "excel_result": excel_res,
            "message": log_msg
        }

@app.get("/api/logs")
async def list_logs():
    return {"logs": get_recent_logs()}

@app.post("/api/open-excel")
async def open_excel():
    excel_path = settings.get_excel_absolute_path()
    if not excel_path.exists():
        raise HTTPException(status_code=404, detail="Excel dosyası bulunamadı!")
    
    try:
        if os.name == "nt":
            os.startfile(str(excel_path))
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(excel_path)])
        return {"success": True, "message": "Excel dosyası açıldı!"}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
