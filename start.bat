@echo off
chcp 65001 >nul
title Bybit ve OKX Hacim ve Maliyet Takipcisi
color 0b

echo ================================================================
echo   Bybit ve OKX Otomatik Hacim ve Maliyet Takip Sistemi
echo   Lokal Web Arayuzu Baslatiliyor: http://localhost:8000
echo ================================================================
echo.

cd /d "%~dp0"

REM Python kontrolu
where py >nul 2>nul
if %errorlevel% equ 0 (
    set PY_CMD=py
    goto :PYTHON_FOUND
)
where python >nul 2>nul
if %errorlevel% equ 0 (
    set PY_CMD=python
    goto :PYTHON_FOUND
)

echo [HATA] Python bulunamadi! Lutfen python.org adresinden Python yukleyiniz.
echo "Add Python to PATH" secenegini isaretlemeyi unutmayiniz.
pause
exit /b 1

:PYTHON_FOUND
REM Sanal ortam kontrolu
if not exist ".venv\Scripts\python.exe" (
    echo [*] Sanal Python ortami hazirlaniyor... Lutfen bekleyiniz...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [HATA] Sanal ortam olusturulamadi!
        pause
        exit /b 1
    )
    echo [*] Gerekli kutuphaneler yukleniyor...
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

REM .env kontrolu
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [*] .env yapilandirma sablonu olusturuldu.
    )
)

REM Excel calisma dosyasi kontrolu
if not exist "bybit-okx_maliyet.xlsx" (
    if exist "bybit-okx_maliyet_template.xlsx" (
        copy bybit-okx_maliyet_template.xlsx bybit-okx_maliyet.xlsx >nul
        echo [*] Excel calisma dosyasi sablondan olusturuldu.
    )
)

REM Port 8000 kontrolu ve eski oturumlari temizleme
for /f "tokens=5" %%p in ('netstat -a -n -o ^| findstr /R /C:":8000 " ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1

REM Tarayiciyi sunucu hazir oldugunda ac (2 sn gecikmeyle)
echo [*] Tarayici aciliyor: http://localhost:8000
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"

REM Sunucuyu baslat
echo [*] FastAPI / Uvicorn sunucusu baslatiliyor...
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

pause
