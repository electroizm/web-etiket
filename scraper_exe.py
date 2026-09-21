r"""Doğtaş Scraper — tek dosyalık, konsolsuz exe başlatıcısı.

`run_scraper.bat`ın (manage.py scrape_dogtas) yerine geçer; başka PC'de de
çalışsın diye Python/venv/proje klasörü GEREKTİRMEZ.

Kullanıcı istekleri (2026-07-23):
  - **Konsol penceresi açılmasın** → PyInstaller `--noconsole` ile derlenir;
    bu modda `sys.stdout` None'dır, bu yüzden burada hiç `print` kullanılmaz.
  - **Tarayıcı açılmasın** → scraper zaten saf HTTP (aiohttp + BeautifulSoup),
    Playwright/Selenium kullanmıyor; ek bir iş gerekmiyor.
  - **Başka PC'de çalışsın** → tek şart: `.env` exe'nin YANINDA olmalı.

`.env` NEDEN BURADA YÜKLENİYOR (kritik):
`etiket_project/settings.py` `.env`'i `BASE_DIR / '.env'` ile okur. Donmuş
exe'de `BASE_DIR` PyInstaller'ın geçici `_MEIPASS` klasörünü gösterir → orada
`.env` yoktur ve ayarlar boş kalır. Burada exe'nin gerçek klasöründen ÖNCE
yükleyerek bunu çözüyoruz: `load_dotenv` varsayılan olarak mevcut ortam
değişkenlerini EZMEZ, dolayısıyla settings.py'deki çağrı zararsız bir no-op olur.
Böylece web-etiket projesinin dosyalarına hiç dokunmuyoruz.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _kok() -> Path:
    """Exe'nin (donmuşsa) ya da bu betiğin bulunduğu klasör."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _log_yolu() -> Path:
    """Koşu kaydı: VeriSil varsa oraya (mevcut düzen, `~ DogtasCom.txt`),
    yoksa exe'nin yanına. Konsol olmadığı için tek geri bildirim budur."""
    verisil = Path(r"D:\GoogleDrive\VeriSil")
    try:
        if verisil.is_dir():
            return verisil / "~ DogtasCom.txt"
    except OSError:
        pass
    return _kok() / "~ DogtasCom.txt"


_akis = None          # konsolsuz modda stdout/stderr yerine geçen log dosyası


def _stdio_hazirla() -> None:
    r"""Konsolsuz (windowed) exe'de `sys.stdout`/`sys.stderr` **None**'dır.

    Django'nun `BaseCommand` çıktısı `OutputWrapper(sys.stdout)` üzerinden gider;
    None sarılınca ilk `self.stdout.write(...)` çağrısında
    `AttributeError: 'NoneType' object has no attribute 'write'` ile çöker
    (saha hatası 2026-07-23 — komut `handle()`in ilk satırında patlıyordu).
    Aynı şey scraper'ın `logging` StreamHandler'ı için de geçerli.

    Çözüm: ikisini de log DOSYASINA yönlendir. Böylece hem çökme biter hem de
    `run_scraper.bat`ın `>> LOG 2>&1` ile yaptığı ŞEYİN AYNISI olur — koşunun
    tüm çıktısı `~ DogtasCom.txt` içinde toplanır.
    """
    global _akis
    if sys.stdout is not None and sys.stderr is not None:
        return                                   # konsoldan çalışıyoruz, dokunma
    try:
        _akis = open(_log_yolu(), "a", encoding="utf-8",
                     errors="replace", buffering=1)   # satır tamponlu
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = _akis
    if sys.stderr is None:
        sys.stderr = _akis


def _yaz(satir: str) -> None:
    if _akis is not None:                        # tek dosya tutamacı kullan
        try:
            _akis.write(satir + "\n")
            return
        except OSError:
            pass
    try:
        with open(_log_yolu(), "a", encoding="utf-8", errors="replace") as f:
            f.write(satir + "\n")
    except OSError:
        pass          # log yazılamıyorsa koşu yine de sürsün


def main() -> int:
    kok = _kok()
    _stdio_hazirla()          # DJANGO'DAN ÖNCE: stdout/stderr None kalmasın
    basladi = datetime.now()
    _yaz(f"\n[{basladi:%Y-%m-%d %H:%M:%S}] Scraper başlıyor (exe)")

    # 1) .env — exe'nin yanından (settings.py'den ÖNCE, bkz. modül açıklaması)
    from dotenv import load_dotenv

    env_yolu = kok / ".env"
    if not env_yolu.is_file():
        _yaz(f"[HATA] .env bulunamadı: {env_yolu} — exe ile aynı klasörde olmalı.")
        return 2
    load_dotenv(env_yolu)

    # 2) Django ayar katmanı (veri yolu SQLAlchemy → Supabase Postgres)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "etiket_project.settings")
    try:
        import django

        django.setup()
    except Exception as e:
        _yaz(f"[HATA] Django başlatılamadı: {e}")
        _yaz(traceback.format_exc())
        return 3

    # 3) Komutu ÖRNEK olarak çağır — donmuş exe'de Django'nun dosya sistemi
    #    tabanlı komut keşfi çalışmaz; sınıfı doğrudan vermek bunu atlar.
    try:
        from django.core.management import call_command

        from catalog.management.commands.scrape_dogtas import Command

        call_command(Command(), *sys.argv[1:])
    except SystemExit as e:                      # komut kendi çıkış kodunu verdi
        kod = int(e.code or 0)
        _yaz(f"[{datetime.now():%H:%M:%S}] Komut çıkış kodu: {kod}")
        return kod
    except Exception as e:
        _yaz(f"[HATA] Scraper hatası: {e}")
        _yaz(traceback.format_exc())
        return 1

    sure = (datetime.now() - basladi).total_seconds() / 60
    _yaz(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Scraper bitti ({sure:.0f} dk)")
    return 0


if __name__ == "__main__":
    try:
        _kod = main()
    finally:
        if _akis is not None:                # log tamponu diske insin
            try:
                _akis.flush()
                _akis.close()
            except OSError:
                pass
    raise SystemExit(_kod)
