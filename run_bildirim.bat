@echo off
REM ═══════════════════════════════════════════════════════════════════════
REM  Telegram bildirimi — Görev Zamanlayıcısı tarafından çalıştırılır
REM  Proje: web-etiket
REM  Zamanlama: Her gün saat 10:07
REM  İş: Sabah taramasının özetini Telegram'a gönderir
REM  Log: D:\GoogleDrive\~ DogtasCom.txt (scraper ile aynı dosya)
REM ═══════════════════════════════════════════════════════════════════════

setlocal

set "PROJECT_DIR=C:\Users\GUNES\git\web-etiket"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "LOG_PATH=D:\GoogleDrive\~ DogtasCom.txt"

cd /d "%PROJECT_DIR%"

"%PYTHON_EXE%" manage.py bildirim_gonder >> "%LOG_PATH%" 2>&1
echo [%date% %time%] Bildirim cikis kodu: %errorlevel% >> "%LOG_PATH%"

endlocal
