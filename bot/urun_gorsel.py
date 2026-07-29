"""Ürün fotoğrafı — dogtas.com ürün sayfasındaki og:image (istek anında çekilir).

Neden veritabanında saklamıyoruz (2026-07-28 kararı): kolon açmak Supabase'de
ELLE SQL gerektiriyor ve fotoğraf isteği seyrek (her mesajda değil). Sayfa
saniyede geliyor, bellek önbelleği tekrarı ucuzlatıyor.

Güvenlik: yalnız BİZİM veritabanımızdaki ürün sayfası çekilir ve dönen görselin
sunucusu beyaz listeye takılır — bot/ses.py'deki SSRF kalkanıyla aynı ilke.
Müşteriye giden link asla serbest metinden gelmez.
"""
from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("bot.urun_gorsel")

# Doğtaş ürün görsellerinin sunulduğu alan adları. Ürün sayfası başka bir yere
# işaret ederse (reklam, izleyici pikseli) müşteriye GÖNDERİLMEZ.
_IZINLI_HOST_SONEK = (".percdn.com", "percdn.com", ".dogtas.com", "dogtas.com")

_ONBELLEK: dict[str, tuple[float, str | None]] = {}
_TTL = 12 * 3600          # ürün fotoğrafı neredeyse hiç değişmez

_OG_KALIBI = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I)


def _guvenli_mi(url: str) -> bool:
    if not url.startswith("https://"):
        return False
    host = url.split("/", 3)[2].split(":")[0].lower()
    return any(host == s.lstrip(".") or host.endswith(s)
               for s in _IZINLI_HOST_SONEK)


def url_bul(sku: str) -> str | None:
    """SKU'dan ürün fotoğrafı URL'i. Bulunamazsa None — akış bozulmaz."""
    sku = (sku or "").strip()
    if not sku:
        return None
    simdi = time.monotonic()
    onbellekli = _ONBELLEK.get(sku)
    if onbellekli and simdi - onbellekli[0] < _TTL:
        return onbellekli[1]

    sonuc = None
    try:
        import requests
        from sqlalchemy import select

        from catalog.database import SessionLocal
        from catalog.sa_models import Urun

        session = SessionLocal()
        try:
            sayfa_url = session.scalar(
                select(Urun.url).where(Urun.sku == sku).limit(1))
        finally:
            session.close()

        if sayfa_url and _guvenli_mi(sayfa_url):
            r = requests.get(sayfa_url, timeout=12, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if r.ok:
                bulunan = _OG_KALIBI.search(r.text)
                if bulunan and _guvenli_mi(bulunan.group(1)):
                    sonuc = bulunan.group(1)
    except Exception:
        log.warning("urun gorseli alinamadi (sku=%s)", sku, exc_info=True)
        return None      # başarısızlığı ÖNBELLEKLEME — geçici olabilir

    _ONBELLEK[sku] = (simdi, sonuc)
    return sonuc
