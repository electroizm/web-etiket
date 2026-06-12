"""Günlük e-posta bildirimi — Görev Zamanlayıcı her gün 10:07'de çalıştırır.

Sabah 07:00 taraması 'son_tarama_ozeti' ayarına şunları yazabilir:
  tur="ozet" → fiyat güncellemesi var (guncellenen > 0); özet
               BILDIRIM_EPOSTA_ALICILAR'a gider
  tur="hata" → tarama hata ile durdu; hata mesajı HATA_EPOSTA_ALICILAR'a gider
Bugüne ait kayıt yoksa (güncelleme yok / tarama hiç çalışmamış) SESSİZ kalır —
kullanıcı kararı (2026-06-12): güncelleme yoksa hiç bildirim gitmesin.

Kullanım: python manage.py bildirim_gonder
"""
import json
import sys
from datetime import date

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Bekleyen tarama özetini e-posta ile gönderir (günlük 10:07 görevi)."

    def handle(self, *args, **opts):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")

        from catalog.database import SessionLocal
        from catalog.services.ayarlar import get_ayar, set_ayar
        from catalog.services.bildirim import eposta_aktif, eposta_gonder

        if not eposta_aktif():
            self.stdout.write(
                "E-posta yapılandırılmamış (EMAIL_HOST_USER/PASSWORD/ALICILAR boş)."
            )
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
                from django.conf import settings as dj_settings

                bugun_tr = date.today().strftime("%d.%m.%Y")
                if data.get("tur") == "hata":
                    konu = f"Doğtaş taraması HATA ile durdu — {bugun_tr}"
                    alicilar = dj_settings.HATA_EPOSTA_ALICILAR
                else:
                    konu = f"Doğtaş fiyat güncellemesi — {bugun_tr}"
                    alicilar = dj_settings.BILDIRIM_EPOSTA_ALICILAR
                ok = eposta_gonder(konu, data.get("mesaj") or "", alicilar=alicilar)
                if ok:
                    # Tekrar gönderilmesin diye temizle
                    set_ayar(session, "son_tarama_ozeti", None)
                    session.commit()
                    self.stdout.write(self.style.SUCCESS(
                        f"E-posta gönderildi → {', '.join(alicilar)}"
                    ))
                else:
                    self.stderr.write(
                        "Gönderim başarısız — kayıt korunuyor, sonra tekrar denenebilir."
                    )
            else:
                # Bugüne ait özet yok = güncelleme yok (veya tarama çalışmadı).
                # Kullanıcı kararı: bu durumda HİÇ bildirim gitmesin.
                self.stdout.write("Bugüne ait gönderilecek özet yok — sessiz.")
        finally:
            session.close()
