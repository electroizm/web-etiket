"""Bot konuşma kaydı — gelen/giden mesajları bot_mesaj tablosuna yazar.

Kayıt asla webhook'u bozmamalı: DB hatası yutulur (loglanır), akış devam eder.
"""
from __future__ import annotations

import logging

from catalog.database import SessionLocal
from catalog.sa_models import BotMesaj

log = logging.getLogger("bot.kayit")

# Panelin "Deneme" sayfası bu kullanıcı adıyla yazar. Mesajlar bot_mesaj'a
# GERÇEKTEN kaydedilir — yoksa ajan geçmişi göremez ve pazarlık adımı /
# fotoğraf teklifi gibi ÇOK TURLU davranışlar denenemez (ikisi de giden
# mesajlardan okunuyor). Ama bu kayıtlar MÜŞTERİ DEĞİLDİR: konuşma listesi,
# gözden geçirme, fırsat defteri ve sabah özeti bunları DIŞARIDA bırakır,
# yoksa İsmail'in kendi denemeleri "cevapsız müşteri" diye raporlanır.
DENEME_KULLANICI = "panel-deneme"


def deneme_mi(kullanici: str) -> bool:
    return (kullanici or "") == DENEME_KULLANICI


def kaydet(platform: str, kullanici: str, yon: str, metin: str) -> None:
    """Tek bir mesajı kaydet (yon: 'gelen' | 'giden')."""
    try:
        session = SessionLocal()
        try:
            session.add(BotMesaj(
                platform=platform,
                kullanici=(kullanici or "?")[:64],
                yon=yon,
                metin=(metin or "")[:4000],
            ))
            session.commit()
        finally:
            session.close()
    except Exception:
        log.exception("bot mesajı kaydedilemedi (%s/%s)", platform, kullanici)


def ozet_gelen(olay) -> str:
    """Gelen olayın okunur özeti (buton payload'ı ya da serbest metin)."""
    if olay.secim:
        return f"[buton] {olay.secim}"
    metin = (olay.metin or "").strip()
    if getattr(olay, "ses", None):
        # Sesli mesaj: metin = transkript (views doldurur); çözülmediyse işaret kalsın.
        return f"[ses] {metin}" if metin else "[ses — çözülemedi]"
    if getattr(olay, "gorsel", None):
        # Görsel/story: metin = OCR + müşteri metni (views birleştirir).
        return f"[görsel] {metin}" if metin else "[görsel — çözülemedi]"
    return metin or "[sohbeti başlattı]"


def ozet_giden(mesaj: dict) -> str:
    """Botun gönderdiği payload'ın okunur özeti (menüler '[menü]' etiketlenir)."""
    # Ürün fotoğrafı — metin alanı YOK. Bu kontrol EN ÖNDE olmalı: IG fotoğrafı
    # {"attachment": {...}} taşıdığı için aşağıdaki carousel dalına düşüp
    # panelde "[kart menüsü]" diye görünüyordu (2026-07-29'da fark edildi).
    if mesaj.get("type") == "image" or (
            (mesaj.get("attachment") or {}).get("type") == "image"):
        return "[fotoğraf]"
    metin = mesaj.get("text")
    # WhatsApp düz metin: {"text": {"body": ...}}
    if isinstance(metin, dict):
        return metin.get("body", "")
    # Instagram düz metin / quick reply: {"text": "...", "quick_replies": [...]}
    if isinstance(metin, str):
        return metin + ("  [menü]" if mesaj.get("quick_replies") else "")
    # WhatsApp interactive (button/list)
    inter = mesaj.get("interactive")
    if inter:
        return (inter.get("body") or {}).get("text", "") + "  [menü]"
    # Instagram carousel
    if mesaj.get("attachment"):
        return "[kart menüsü]"
    return "[mesaj]"
