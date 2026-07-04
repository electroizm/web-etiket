"""Meta Graph API'ye giden mesaj gönderimi.

Token yoksa (DRY_RUN) gerçek istek atılmaz, payload loglanır. Token gelince
otomatik gerçek gönderim. Ayarlar Django settings'ten okunur (env → settings).
`requests` kullanır (projede zaten bağımlılık).
"""
from __future__ import annotations

import json
import logging

import requests

from django.conf import settings

log = logging.getLogger("bot.meta")


def gonder_instagram(alici_id: str, mesaj: dict) -> bool:
    """Instagram DM gönder (Instagram Login API — host graph.instagram.com,
    kimlik IG_TOKEN; WhatsApp'ın META_TOKEN'ından bağımsız)."""
    govde = {"recipient": {"id": alici_id}, "message": mesaj}

    if settings.BOT_DRY_RUN_IG:
        log.info("[DRY_RUN] IG → %s: %s", alici_id, json.dumps(mesaj, ensure_ascii=False))
        return True

    url = (f"https://graph.instagram.com/{settings.GRAPH_API_VERSION}"
           f"/{settings.IG_ID}/messages")
    try:
        r = requests.post(url,
                          headers={"Authorization": f"Bearer {settings.IG_TOKEN}"},
                          json=govde, timeout=10)
        if r.status_code == 200:
            return True
        log.error("IG gönderim hatası %s: %s", r.status_code, r.text)
    except requests.RequestException as e:
        log.error("IG gönderim istisnası: %s", e)
    return False


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
                         headers={"Authorization": f"Bearer {settings.IG_TOKEN}"},
                         timeout=10)
        if r.status_code == 200:
            return r.json()
        log.warning("IG profil hatası %s: %s", r.status_code, r.text[:200])
    except requests.RequestException as e:
        log.warning("IG profil istisnası: %s", e)
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
