# -*- mode: python ; coding: utf-8 -*-
"""Doğtaş Scraper — konsolsuz tek dosya exe (kullanıcı 2026-07-23).

Girdi: scraper_exe.py (manage.py scrape_dogtas'ın exe sarmalayıcısı).
Çıktı: dist/DogtasScraper.exe — başka PC'de çalışır, tek şart `.env` yanında.

Django uygulamaları/modelleri ÇALIŞMA ANINDA (django.setup) import edildiği
için PyInstaller'ın statik çözümleyicisi göremez → hiddenimports ile açıkça
verilir. Aynı şekilde SQLAlchemy'nin postgresql sürücüsü de dinamik yüklenir.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# Django'nun kendi şablon/locale/statik dosyaları + alt modülleri
for paket in ("django",):
    d, b, h = collect_all(paket)
    datas += d; binaries += b; hiddenimports += h

# Proje uygulamaları: django.setup() bunları isimle import eder
for uygulama in ("accounts", "dashboard", "catalog", "bot", "etiket_project"):
    hiddenimports += collect_submodules(uygulama)

# Dinamik yüklenen sürücüler/eklentiler
hiddenimports += [
    "psycopg2", "sqlalchemy.dialects.postgresql",
    "whitenoise", "whitenoise.middleware",
]

a = Analysis(
    ['scraper_exe.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Kullanılmayan ağır bağımlılıklar dışlanır (exe küçülsün):
    # bot/ajan.py'nin litellm'i ve PDF etiketin reportlab'ı scraper yolunda YOK.
    excludes=['litellm', 'reportlab', 'PIL', 'qrcode', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DogtasScraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # KONSOL YOK (kullanıcı isteği); sys.stdout None olur
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
