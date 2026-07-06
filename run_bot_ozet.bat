@echo off
REM ═══════════════════════════════════════════════════════════════════════
REM  Bot sabah özeti — Görev Zamanlayıcısı tarafından çalıştırılır
REM  Proje: web-etiket (instALL bot)
REM  Zamanlama: Her gün saat 09:00
REM  İş: Son 24 saatin bot konuşmalarını Gemini ile özetleyip e-posta atar
REM  Log: D:\GoogleDrive\~ DogtasCom.txt (scraper ile aynı dosya)
REM ═══════════════════════════════════════════════════════════════════════

setlocal

set "PROJECT_DIR=C:\Users\GUNES\git\web-etiket"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "LOG_PATH=D:\GoogleDrive\~ DogtasCom.txt"

cd /d "%PROJECT_DIR%"

"%PYTHON_EXE%" manage.py bot_ozet >> "%LOG_PATH%" 2>&1
echo [%date% %time%] Bot ozet cikis kodu: %errorlevel% >> "%LOG_PATH%"

endlocal
