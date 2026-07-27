"""Sesli mesaj → metin (transkript) — Gemini üzerinden.

WhatsApp sesli mesajı media_id ile gelir: önce Graph API'den geçici indirme
URL'i alınır (Bearer META_TOKEN), sonra dosya indirilir. Instagram sesi
webhook'ta doğrudan CDN URL'i taşır (kimlik gerekmez). İndirilen ses base64
ile Gemini'ye verilir; model zinciri ajanla aynı (settings.AJAN_MODELLER).

Hiçbir hata müşteri akışını bozmaz: her adım None dönebilir, çağıran
(bot/views) müşteriye "çözemedim" mesajı atar ve devam eder.
"""
from __future__ import annotations

import base64
import logging
from urllib.parse import urlparse

import requests

from django.conf import settings

log = logging.getLogger("bot.ses")

MAKS_SES_BAYT = 8 * 1024 * 1024   # Gemini inline sınırına güvenli mesafe (~8 MB)

# Instagram/Facebook CDN host son ekleri — _ig_indir yalnız bunlara gider.
# SSRF savunma derinliği: webhook imzası artık doğrulanıyor (URL gerçekten
# Meta'dan gelir) ama yine de iç ağa / rastgele host'a istek atmayı engelle.
_IG_IZINLI_HOST_SONEK = (".cdninstagram.com", ".fbcdn.net", ".fbsbx.com")


def _ig_url_guvenli(url: str) -> bool:
    """URL https + host bilinen Meta/Instagram CDN mi? (SSRF savunma derinliği)."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = (p.hostname or "").lower()
    if p.scheme != "https" or not host:
        return False
    return any(host == s.lstrip(".") or host.endswith(s) for s in _IG_IZINLI_HOST_SONEK)


def _indir_sinirli(url: str, headers: dict | None = None, timeout: int = 20):
    """URL'i AKIŞLA indir, MAKS_SES_BAYT aşılırsa iptal et (OOM koruması).

    (icerik_bayt, content_type) döner; HTTP != 200 / sınır aşımı / hata → None.
    Boyut kontrolü indirme SIRASINDA yapılır (tüm dosyayı belleğe almadan)."""
    with requests.get(url, headers=headers, timeout=timeout, stream=True) as d:
        if d.status_code != 200:
            log.error("indirme HTTP %s", d.status_code)
            return None
        cl = d.headers.get("Content-Length")
        if cl and cl.isdigit() and int(cl) > MAKS_SES_BAYT:
            log.error("indirme çok büyük (Content-Length %s bayt)", cl)
            return None
        parcalar, toplam = [], 0
        for parca in d.iter_content(chunk_size=65536):
            toplam += len(parca)
            if toplam > MAKS_SES_BAYT:
                log.error("indirme sınırı aşıldı (%s bayt), iptal", toplam)
                return None
            parcalar.append(parca)
        ct = (d.headers.get("Content-Type") or "").split(";")[0].strip()
        return b"".join(parcalar), ct

# Son transkript hatası — /saglik teşhisi için (Render loguna erişim yok).
SON_HATA: str | None = None

TRANSKRIPT_TALIMAT = (
    "Bu ses kaydını Türkçe metne dök. YALNIZCA söylenenleri yaz; "
    "açıklama, başlık, tırnak ekleme. Anlaşılmayan yer varsa atlayıp devam et."
)


def coz(ses: dict) -> str | None:
    """Webhook'un çıkardığı ses bilgisini indir + metne çevir. Hata → None."""
    global SON_HATA
    try:
        if ses.get("tip") == "wa":
            indirilen = _wa_indir(ses.get("media_id", ""))
        else:
            indirilen = _ig_indir(ses.get("url", ""))
        if not indirilen:
            return None
        veri, mime = indirilen
        return transkript(veri, mime)
    except Exception as e:
        from datetime import datetime
        SON_HATA = f"{datetime.now():%H:%M:%S} coz {type(e).__name__}: {str(e)[:200]}"
        log.exception("ses çözülemedi: %s", ses)
        return None


def _wa_indir(media_id: str) -> tuple[bytes, str] | None:
    """WhatsApp medyası iki adımda iner: media_id → geçici URL → dosya.

    Geçici URL ~5 dk geçerlidir ve indirme de Bearer token ister (CDN'e
    token'sız istek 404 döner — Meta kuralı).
    """
    if not media_id or settings.BOT_DRY_RUN:
        return None
    basliklar = {"Authorization": f"Bearer {settings.META_TOKEN}"}
    r = requests.get(
        f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}/{media_id}",
        headers=basliklar, timeout=10)
    if r.status_code != 200:
        log.error("WA medya bilgisi alınamadı %s: %s", r.status_code, r.text[:200])
        return None
    bilgi = r.json()
    url = bilgi.get("url")
    # "audio/ogg; codecs=opus" → "audio/ogg"
    mime = (bilgi.get("mime_type") or "audio/ogg").split(";")[0].strip()
    if not url:
        return None
    sonuc = _indir_sinirli(url, headers=basliklar, timeout=20)
    if not sonuc:
        return None
    return sonuc[0], mime   # mime Graph API bilgisinden (header'dan daha güvenilir)


def _ig_indir(url: str) -> tuple[bytes, str] | None:
    """Instagram medyası CDN URL'inden doğrudan iner (kimlik gerekmez).

    SSRF savunma derinliği: yalnız Meta/Instagram CDN host'larına gider;
    akışla indirip boyut sınırını aşarsa iptal eder."""
    if not url:
        return None
    if not _ig_url_guvenli(url):
        log.error("IG indirme reddedildi (güvensiz host): %s", (urlparse(url).hostname or "?"))
        return None
    sonuc = _indir_sinirli(url, timeout=20)
    if not sonuc:
        return None
    icerik, ct = sonuc
    return icerik, (ct or "audio/mp4")


def transkript(veri: bytes, mime: str) -> str | None:
    """Ses baytlarını Gemini ile metne çevir (ajanla aynı model zinciri)."""
    global SON_HATA
    if not settings.AJAN_AKTIF:
        return None
    import litellm
    litellm.suppress_debug_info = True

    b64 = base64.b64encode(veri).decode("ascii")
    mesajlar = [{
        "role": "user",
        "content": [
            {"type": "text", "text": TRANSKRIPT_TALIMAT},
            {"type": "file", "file": {"file_data": f"data:{mime};base64,{b64}"}},
        ],
    }]
    from datetime import datetime
    for model in settings.AJAN_MODELLER:
        try:
            yanit = litellm.completion(model=model, messages=mesajlar,
                                       max_tokens=500, timeout=25)
            metin = (yanit.choices[0].message.content or "").strip()
            if metin:
                return metin[:1000]
        except Exception as e:
            SON_HATA = f"{datetime.now():%H:%M:%S} [{model}] {type(e).__name__}: {str(e)[:200]}"
            log.warning("transkript: %s başarısız (%s), sıradaki model",
                        model, type(e).__name__)
    log.error("transkript: tüm modeller başarısız")
    return None
