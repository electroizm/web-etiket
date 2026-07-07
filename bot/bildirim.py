"""Yetkiliye (İsmail) bildirim — geri arama talepleri + memnuniyetsizlik alarmı.

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


def _kimlik(platform: str, kullanici: str) -> str:
    if platform == "whatsapp":
        return f"wa.me/{kullanici}"            # tıklayınca sohbet açılır
    return f"Instagram ({kullanici})"


def _yetkiliye_ilet(eposta_konu: str, govde: str) -> None:
    """Bildirimi ilet: önce WhatsApp (0532), olmazsa e-posta yedeği."""
    from bot.router import YETKILI_WA   # tek kaynak (0532)

    # 1) WhatsApp — İsmail botla son 24 saatte konuştuysa ulaşır.
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
        log.exception("WA bildirimi gönderilemedi")

    # 2) E-posta yedeği (24 saat penceresi kapalıysa WA düşer).
    if not ok:
        try:
            if settings.EMAIL_HOST_USER and settings.BILDIRIM_EPOSTA_ALICILAR:
                from django.core.mail import send_mail
                send_mail(eposta_konu, govde,
                          settings.DEFAULT_FROM_EMAIL,
                          settings.BILDIRIM_EPOSTA_ALICILAR,
                          fail_silently=True)
        except Exception:
            log.exception("e-posta bildirimi gönderilemedi")


def geri_arama_bildir(platform: str, kullanici: str, mesaj: str) -> None:
    """Geri arama talebini yetkiliye ilet."""
    ad = _musteri_adi(platform, kullanici)
    govde = ("📞 GERİ ARAMA TALEBİ\n"
             f"Müşteri: {ad or 'İsimsiz'} — {_kimlik(platform, kullanici)}\n"
             f"Yazdığı: {mesaj}")
    _yetkiliye_ilet("instALL ajan — 📞 geri arama talebi", govde)


def sistem_uyari(konu: str, govde: str) -> None:
    """Operasyonel sistem uyarısı (ör. IG token yenileme hatası) → yetkiliye ilet.

    Müşteri akışıyla ilgisi yok; altyapı sessizce ölmesin diye İsmail haberdar olur."""
    _yetkiliye_ilet(konu, govde)


def memnuniyetsizlik_bildir(platform: str, kullanici: str,
                            mesaj: str, sinyal: str) -> None:
    """Şikâyet sinyali alarmı: müşteri daha hattayken İsmail haberdar olsun."""
    ad = _musteri_adi(platform, kullanici)
    govde = ("⚠️ MEMNUNİYETSİZLİK SİNYALİ\n"
             f"Müşteri: {ad or 'İsimsiz'} — {_kimlik(platform, kullanici)}\n"
             f"Yazdığı: {mesaj}\n"
             f"(yakalanan ifade: \"{sinyal}\")")
    _yetkiliye_ilet("instALL ajan — ⚠️ memnuniyetsizlik sinyali", govde)
