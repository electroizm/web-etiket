@echo off
REM ═══════════════════════════════════════════════════════════════════════
REM  IG token yenileme — Görev Zamanlayıcısı tarafından çalıştırılır
REM  Proje: web-etiket (instALL bot)
REM  Zamanlama: HAFTADA BİR (ör. her Pazartesi 09:30)
REM  İş: Instagram uzun-ömürlü token'ını 60 gün daha uzatır, app_ayarlari'na yazar
REM       (Render bu tabloyu okur — token dolup bot sessizce durmasın diye)
REM  Log: D:\GoogleDrive\~ DogtasCom.txt (scraper/özet ile aynı dosya)
REM ═══════════════════════════════════════════════════════════════════════

setlocal

set "PROJECT_DIR=C:\Users\GUNES\git\web-etiket"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "LOG_PATH=D:\GoogleDrive\~ DogtasCom.txt"

cd /d "%PROJECT_DIR%"

"%PYTHON_EXE%" manage.py ig_token_yenile >> "%LOG_PATH%" 2>&1
echo [%date% %time%] IG token yenile cikis kodu: %errorlevel% >> "%LOG_PATH%"

endlocal
