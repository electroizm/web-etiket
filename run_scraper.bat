@echo off
REM ═══════════════════════════════════════════════════════════════════════
REM  Doğtaş Scraper — Görev Zamanlayıcısı tarafından çalıştırılır
REM  Proje: web-etiket
REM  Zamanlama: Her gün saat 07:00
REM  Log: D:\GoogleDrive\~ DogtasCom.txt
REM ═══════════════════════════════════════════════════════════════════════

setlocal

set "PROJECT_DIR=C:\Users\GUNES\git\web-etiket"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "LOG_PATH=D:\GoogleDrive\~ DogtasCom.txt"

cd /d "%PROJECT_DIR%"

"%PYTHON_EXE%" manage.py scrape_dogtas >> "%LOG_PATH%" 2>&1
echo [%date% %time%] Cikis kodu: %errorlevel% >> "%LOG_PATH%"

endlocal
