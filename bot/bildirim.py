"""Yetkiliye (İsmail) bildirim — geri arama talepleri.

Müşteri "📞 Beni arayın" akışında numara+saat yazınca burası devreye girer.
Önce İsmail'in kişisel WhatsApp'ına (0532) Cloud API ile serbest metin denenir;
24 saat penceresi kapalıysa Meta serbest metni reddeder → e-posta yedeği
(scraper bildirimleriyle aynı SMTP ayarları) devreye girer.

Hiçbir hata müşteri akışını bozmaz: yut, logla, devam et.
"""
from __future__ import annotations

import logging

from django.conf import settings

log = logging.getLogger("bot.bildirim")


def _musteri_adi(platform: str, kullanici: str) -> str | None:
    """bot_kisi tablosundan müşterinin bilinen adını çek (yoksa None)."""
    try:
        from sqlalchemy import select

        from catalog.database import SessionLocal
        from catalog.sa_models import BotKisi
        session = SessionLocal()
        try:
            kisi = session.scalar(
                select(BotKisi).where(BotKisi.platform == platform,
                                      BotKisi.kullanici == kullanici)
            )
            return kisi.ad if kisi is not None else None
        finally:
            session.close()
    except Exception:
        return None


def geri_arama_bildir(platform: str, kullanici: str, mesaj: str) -> None:
    """Geri arama talebini yetkiliye ilet: önce WhatsApp, olmazsa e-posta."""
    from bot.router import YETKILI_WA   # tek kaynak (0532)

    ad = _musteri_adi(platform, kullanici)
    if platform == "whatsapp":
        kimlik = f"wa.me/{kullanici}"          # tıklayınca sohbet açılır
    else:
        kimlik = f"Instagram ({kullanici})"
    govde = ("📞 GERİ ARAMA TALEBİ\n"
             f"Müşteri: {ad or 'İsimsiz'} — {kimlik}\n"
             f"Yazdığı: {mesaj}")

    # 1) WhatsApp (0532) — İsmail botla son 24 saatte konuştuysa ulaşır.
    ok = False
    try:
        from bot import meta_client
        ok = meta_client.gonder_whatsapp(YETKILI_WA, {
            "type": "text", "text": {"body": govde},
        })
        if ok:
            from bot.kayit import kaydet   # dashboard'da iz kalsın
            kaydet("whatsapp", YETKILI_WA, "giden", govde)
    except Exception:
        log.exception("geri arama WA bildirimi gönderilemedi")

    # 2) E-posta yedeği (24 saat penceresi kapalıysa WA düşer).
    if not ok:
        try:
            if settings.EMAIL_HOST_USER and settings.BILDIRIM_EPOSTA_ALICILAR:
                from django.core.mail import send_mail
                send_mail("instALL bot — 📞 geri arama talebi", govde,
                          settings.DEFAULT_FROM_EMAIL,
                          settings.BILDIRIM_EPOSTA_ALICILAR,
                          fail_silently=True)
        except Exception:
            log.exception("geri arama e-posta bildirimi gönderilemedi")
