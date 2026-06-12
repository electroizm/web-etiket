"""Günlük Telegram bildirimi — Görev Zamanlayıcı her gün 10:07'de çalıştırır.

Sabah 07:00 taraması, FİYAT GÜNCELLEMESİ VARSA (guncellenen > 0) özeti DB'ye
yazar ('son_tarama_ozeti' ayarı); bu komut o özeti okuyup Telegram'a iletir.
Bugüne ait özet yoksa (güncelleme yok / tarama çalışmamış) SESSİZ kalır —
kullanıcı kararı (2026-06-12): güncelleme yoksa hiç mesaj gitmesin.

Kullanım: python manage.py bildirim_gonder
"""
import json
import sys
from datetime import date

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Bekleyen tarama özetini Telegram'a gönderir (günlük 10:07 görevi)."

    def handle(self, *args, **opts):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")

        from catalog.database import SessionLocal
        from catalog.services.ayarlar import get_ayar, set_ayar
        from catalog.services.bildirim import (
            telegram_aktif,
            telegram_gonder,
            whatsapp_aktif,
            whatsapp_gonder,
        )

        if not telegram_aktif() and not whatsapp_aktif():
            self.stdout.write("Bildirim yapılandırılmamış (Telegram/WhatsApp env boş).")
            return

        bugun = date.today().isoformat()
        session = SessionLocal()
        try:
            raw = get_ayar(session, "son_tarama_ozeti")
            data = None
            if raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = None

            if data and data.get("tarih") == bugun:
                mesaj = data.get("mesaj") or ""
                tg_ok = telegram_gonder(mesaj)
                wa_say = whatsapp_gonder(mesaj) if whatsapp_aktif() else 0
                if tg_ok or wa_say:
                    # En az bir kanala ulaştı → tekrar gönderilmesin diye temizle
                    set_ayar(session, "son_tarama_ozeti", None)
                    session.commit()
                    self.stdout.write(self.style.SUCCESS(
                        f"Özet gönderildi (Telegram: {'✓' if tg_ok else '✗'}, "
                        f"WhatsApp: {wa_say} alıcı)."
                    ))
                else:
                    self.stderr.write("Gönderim başarısız — özet korunuyor, sonra tekrar denenebilir.")
            else:
                # Bugüne ait özet yok = güncelleme yok (veya tarama çalışmadı).
                # Kullanıcı kararı: bu durumda HİÇ mesaj atma.
                self.stdout.write("Bugüne ait gönderilecek özet yok — sessiz.")
        finally:
            session.close()
