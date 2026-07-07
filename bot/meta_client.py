"""Meta Graph API'ye giden mesaj gönderimi.

Token yoksa (DRY_RUN) gerçek istek atılmaz, payload loglanır. Token gelince
otomatik gerçek gönderim. Ayarlar Django settings'ten okunur (env → settings).
`requests` kullanır (projede zaten bağımlılık).
"""
from __future__ import annotations

import json
import logging
import time

import requests

from django.conf import settings

log = logging.getLogger("bot.meta")

# Son IG gönderim hatası — Render loguna erişim olmadan /saglik'tan teşhis için.
# (2026-07-07 arızası: bot cevap üretiyor + kaydediyordu ama müşteriye ulaşmıyordu;
#  hata yalnız log.error'daydı, göremiyorduk.)
IG_SON_GONDERIM_HATA: str | None = None

# Canlı IG token önbelleği (yenileme app_ayarlari'na yazar; her gönderimde DB'ye
# gitmemek için kısa TTL). Eski token'ı ~5 dk tutmak zararsız — 60 gün geçerli.
_ig_token_cache: tuple[float, str] | None = None
_IG_TOKEN_TTL = 300  # saniye


def aktif_ig_token() -> str:
    """Kullanılacak IG token'ı: önce DB (app_ayarlari.ig_token — oto-yenileme
    buraya yazar), yoksa env (settings.IG_TOKEN, ilk tohum). DB erişilemezse env.

    Token 60 günde dolar; `manage.py ig_token_yenile` DB'yi tazeler, Render bu
    fonksiyonla yeni token'ı okur (env değişkeni elle güncellenmese de)."""
    global _ig_token_cache
    now = time.monotonic()
    if _ig_token_cache and now - _ig_token_cache[0] < _IG_TOKEN_TTL:
        return _ig_token_cache[1]

    token = settings.IG_TOKEN
    try:
        from catalog.database import SessionLocal
        from catalog.services.ayarlar import get_ayar
        session = SessionLocal()
        try:
            deger = get_ayar(session, "ig_token")
            if deger:
                token = deger
        finally:
            session.close()
    except Exception:
        log.warning("aktif_ig_token: DB okunamadı, env token'a düşülüyor", exc_info=True)

    _ig_token_cache = (now, token)
    return token


def gonder_instagram(alici_id: str, mesaj: dict) -> bool:
    """Instagram DM gönder (Instagram Login API — host graph.instagram.com,
    kimlik IG_TOKEN; WhatsApp'ın META_TOKEN'ından bağımsız)."""
    govde = {"recipient": {"id": alici_id}, "message": mesaj}

    if settings.BOT_DRY_RUN_IG:
        log.info("[DRY_RUN] IG → %s: %s", alici_id, json.dumps(mesaj, ensure_ascii=False))
        return True

    global IG_SON_GONDERIM_HATA
    from datetime import datetime
    url = (f"https://graph.instagram.com/{settings.GRAPH_API_VERSION}"
           f"/{settings.IG_ID}/messages")
    try:
        r = requests.post(url,
                          headers={"Authorization": f"Bearer {aktif_ig_token()}"},
                          json=govde, timeout=10)
        if r.status_code == 200:
            return True
        IG_SON_GONDERIM_HATA = f"{datetime.now():%H:%M:%S} HTTP {r.status_code}: {r.text[:300]}"
        log.error("IG gönderim hatası %s: %s", r.status_code, r.text)
    except requests.RequestException as e:
        IG_SON_GONDERIM_HATA = f"{datetime.now():%H:%M:%S} {type(e).__name__}: {str(e)[:200]}"
        log.error("IG gönderim istisnası: %s", e)
    return False


def gonder_instagram_private_reply(comment_id: str, mesaj: dict) -> dict | None:
    """Bir yoruma ÖZEL (private) DM cevabı gönder (yorumdan-DM tetikleyicisi).

    Meta kısıtı: yorum başına yalnızca BİR kez kullanılabilir, yorumdan sonraki
    7 gün içinde. Başarılı yanıt {"recipient_id": <igsid>, ...} döner — o andan
    sonra kişiyle normal gonder_instagram(igsid, ...) ile konuşulur.
    """
    govde = {"recipient": {"comment_id": comment_id}, "message": mesaj}

    if settings.BOT_DRY_RUN_IG:
        log.info("[DRY_RUN] IG private-reply → yorum %s: %s", comment_id,
                 json.dumps(mesaj, ensure_ascii=False))
        return {"recipient_id": "DRY_RUN"}

    url = (f"https://graph.instagram.com/{settings.GRAPH_API_VERSION}"
           f"/{settings.IG_ID}/messages")
    try:
        r = requests.post(url,
                          headers={"Authorization": f"Bearer {aktif_ig_token()}"},
                          json=govde, timeout=10)
        if r.status_code == 200:
            return r.json()
        log.error("IG private-reply hatası %s: %s", r.status_code, r.text)
    except requests.RequestException as e:
        log.error("IG private-reply istisnası: %s", e)
    return None


def profil_instagram(igsid: str) -> dict | None:
    """Bize mesaj atan IG kullanıcısının profilini çek (ad, kullanıcı adı, foto).

    Yalnızca işletmeye mesaj göndermiş kullanıcılar için çalışır (Meta kuralı) —
    bizim senaryo tam olarak bu. Hata durumunda None (çağıran id göstermeye devam eder).
    """
    if settings.BOT_DRY_RUN_IG:
        return None
    url = f"https://graph.instagram.com/{settings.GRAPH_API_VERSION}/{igsid}"
    try:
        r = requests.get(url,
                         params={"fields": "name,username,profile_pic"},
                         headers={"Authorization": f"Bearer {aktif_ig_token()}"},
                         timeout=10)
        if r.status_code == 200:
            return r.json()
        log.warning("IG profil hatası %s: %s", r.status_code, r.text[:200])
    except requests.RequestException as e:
        log.warning("IG profil istisnası: %s", e)
    return None


def gonderi_bilgi(media_id: str) -> dict | None:
    """Bir gönderinin/reels'in başlığı (caption) + OCR'lanacak görseli.

    Yorumdan-DM'de kullanılır: yorum "fiyat" der ama hangi ürün olduğunu
    söylemez — gönderinin kendisi (görsel üstündeki ürün adı + başlık) bağlamı
    verir. IMAGE'da media_url görseldir; VIDEO/REELS'te thumbnail_url görsel,
    media_url videodur (OCR için thumbnail tercih edilir)."""
    if not media_id or settings.BOT_DRY_RUN_IG:
        return None
    url = f"https://graph.instagram.com/{settings.GRAPH_API_VERSION}/{media_id}"
    try:
        r = requests.get(
            url,
            params={"fields": "caption,media_type,media_url,thumbnail_url"},
            headers={"Authorization": f"Bearer {aktif_ig_token()}"}, timeout=10)
        if r.status_code != 200:
            log.warning("gönderi bilgisi alınamadı %s: %s", r.status_code, r.text[:200])
            return None
        d = r.json()
        gorsel_url = (d.get("media_url") if d.get("media_type") == "IMAGE"
                      else d.get("thumbnail_url") or d.get("media_url"))
        return {"caption": d.get("caption"), "gorsel_url": gorsel_url,
                "media_type": d.get("media_type")}
    except requests.RequestException as e:
        log.warning("gönderi bilgisi istisnası: %s", e)
        return None


def gonder_whatsapp(alici_id: str, mesaj: dict) -> bool:
    """WhatsApp mesajı gönder (Cloud API /{PHONE_NUMBER_ID}/messages).

    mesaj: wa_presenter'dan gelen tip+içerik (type/text/interactive). Buraya
    "messaging_product" ve "to" zarfı eklenir.
    """
    govde = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": alici_id,
        **mesaj,
    }

    if settings.BOT_DRY_RUN:
        log.info("[DRY_RUN] WA → %s: %s", alici_id, json.dumps(mesaj, ensure_ascii=False))
        return True

    url = (f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}"
           f"/{settings.PHONE_NUMBER_ID}/messages")
    try:
        r = requests.post(url,
                          headers={"Authorization": f"Bearer {settings.META_TOKEN}"},
                          json=govde, timeout=10)
        if r.status_code == 200:
            return True
        log.error("WA gönderim hatası %s: %s", r.status_code, r.text)
    except requests.RequestException as e:
        log.error("WA gönderim istisnası: %s", e)
    return False
