' ═══════════════════════════════════════════════════════════════════════
'  Doğtaş Scraper — Görev Zamanlayıcısı tarafından çalıştırılır
'  Proje: web-etiket
'  Zamanlama: Her gün saat 07:00
'  Log: D:\GoogleDrive\~ DogtasCom.txt
' ═══════════════════════════════════════════════════════════════════════

Dim WshShell, fso, logFile, projectDir, pythonExe, logPath

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectDir = "C:\Users\GUNES\git\web-etiket"
pythonExe  = projectDir & "\.venv\Scripts\python.exe"
logPath    = "D:\GoogleDrive\~ DogtasCom.txt"

' Proje dizinine geç
WshShell.CurrentDirectory = projectDir

' Komutu sessiz çalıştır ve çıktıyı log dosyasına yönlendir
Dim cmd
cmd = "cmd /c """ & pythonExe & """ manage.py scrape_dogtas >> """ & logPath & """ 2>&1 && echo [%date% %time%] Cikis kodu: %errorlevel% >> """ & logPath & """"

' 0 = gizli pencere, True = tamamlanana kadar bekle
WshShell.Run cmd, 0, True

Set WshShell = Nothing
Set fso = Nothing
