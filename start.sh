#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "================================================================"
echo "  🚀 Bybit & OKX Otomatik Hacim ve Maliyet Takip Sistemi"
echo "  Lokal Web Arayüzü Başlatılıyor (http://localhost:8000)"
echo "================================================================"

# Python detection
if command -v python3 &>/dev/null; then
    PY_CMD="python3"
elif command -v python &>/dev/null; then
    PY_CMD="python"
else
    echo "[HATA] Python bulunamadı! Lütfen Python 3.10+ yükleyiniz."
    exit 1
fi

# Sanal ortam kontrolü
if [ ! -d ".venv" ]; then
    echo "[*] Sanal Python ortamı (.venv) oluşturuluyor..."
    $PY_CMD -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# .env kontrolü
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo "[*] .env yapılandırma şablonu oluşturuldu."
fi

# Excel çalışma dosyası kontrolü
if [ ! -f "bybit-okx_maliyet.xlsx" ] && [ -f "bybit-okx_maliyet_template.xlsx" ]; then
    cp bybit-okx_maliyet_template.xlsx bybit-okx_maliyet.xlsx
    echo "[*] Excel çalışma dosyası şablondan oluşturuldu."
fi

# Tarayıcıyı aç
if command -v open &>/dev/null; then
    open "http://localhost:8000" &
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:8000" &
fi

# Sunucuyu başlat
echo "[*] FastAPI / Uvicorn sunucusu başlatılıyor..."
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
