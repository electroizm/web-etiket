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

import requests

from django.conf import settings

log = logging.getLogger("bot.ses")

MAKS_SES_BAYT = 8 * 1024 * 1024   # Gemini inline sınırına güvenli mesafe (~8 MB)

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
    d = requests.get(url, headers=basliklar, timeout=20)
    if d.status_code != 200 or len(d.content) > MAKS_SES_BAYT:
        log.error("WA medya indirilemedi (%s, %s bayt)", d.status_code, len(d.content))
        return None
    return d.content, mime


def _ig_indir(url: str) -> tuple[bytes, str] | None:
    """Instagram sesi CDN URL'inden doğrudan iner (kimlik gerekmez)."""
    if not url:
        return None
    d = requests.get(url, timeout=20)
    if d.status_code != 200 or len(d.content) > MAKS_SES_BAYT:
        log.error("IG ses indirilemedi (%s)", d.status_code)
        return None
    mime = (d.headers.get("Content-Type") or "audio/mp4").split(";")[0].strip()
    return d.content, mime


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
