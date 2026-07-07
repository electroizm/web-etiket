"""Instagram uzun-ömürlü token'ını yeniler (60 gün → +60 gün).

Instagram Login API token'ı 60 günde dolar. `refresh_access_token` ile uzatılır
(token en az 24 saat eski ve hâlâ geçerli olmalı). Yeni token app_ayarlari.ig_token'a
yazılır; canlı bot (Render) onu `meta_client.aktif_ig_token()` ile okur — Render
env değişkeni elle güncellenmese bile token taze kalır.

Görev Zamanlayıcı ile HAFTADA BİR çalışır (run_ig_token_yenile.bat). Token 60 gün
geçerli olduğundan haftalık koşu bol marjla önde tutar; PC birkaç hafta kapalı
kalsa bile sorun olmaz.

İlk kurulum: DB'de ig_token yoksa komut env'deki IG_TOKEN'ı tohum alır. Yerel
.env'de IG_TOKEN yoksa bir kez  --tohum <TOKEN>  ile doğrudan DB'ye yaz.

Kullanım:
  python manage.py ig_token_yenile              # yenile + DB'ye yaz (canlı)
  python manage.py ig_token_yenile --kuru       # dene, yaz/uyarı yok (test)
  python manage.py ig_token_yenile --tohum XXX  # DB'yi ilk kez tohumla, sonra yenile
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import requests
from django.core.management.base import BaseCommand

REFRESH_URL = "https://graph.instagram.com/refresh_access_token"


class Command(BaseCommand):
    help = "IG uzun-ömürlü token'ını yeniler (60 gün) ve app_ayarlari'na yazar."

    def add_arguments(self, parser):
        parser.add_argument("--kuru", action="store_true",
                            help="Yenilemeyi dene ama DB'ye yazma / uyarı gönderme (test).")
        parser.add_argument("--tohum", metavar="TOKEN",
                            help="DB'ye ilk token'ı doğrudan yaz (env'de IG_TOKEN yoksa bir kez).")

    def handle(self, *args, **opts):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")

        from catalog.database import SessionLocal
        from catalog.services.ayarlar import get_ayar, set_ayar

        # --tohum: verilen token'ı DB'ye yaz (yenilemeden önce kaynak olsun).
        if opts.get("tohum"):
            session = SessionLocal()
            try:
                set_ayar(session, "ig_token", opts["tohum"].strip())
                session.commit()
            finally:
                session.close()
            self.stdout.write(self.style.SUCCESS("Tohum token DB'ye yazıldı."))

        # Mevcut token: DB (app_ayarlari.ig_token) → env (settings.IG_TOKEN).
        from bot import meta_client
        meta_client._ig_token_cache = None          # tohumdan sonra taze oku
        token = meta_client.aktif_ig_token()
        if not token:
            self.stderr.write("IG token yok (ne DB'de ne env'de) — yenilenecek bir şey yok. "
                              "İlk kez  --tohum <TOKEN>  ile ver.")
            return

        # Refresh çağrısı.
        try:
            r = requests.get(REFRESH_URL, params={
                "grant_type": "ig_refresh_token",
                "access_token": token,
            }, timeout=15)
        except requests.RequestException as e:
            self._basarisiz(opts, f"İstek hatası: {e}")
            return

        if r.status_code != 200:
            self._basarisiz(opts, f"HTTP {r.status_code}: {r.text[:300]}")
            return

        veri = r.json()
        yeni_token = veri.get("access_token")
        expires_in = veri.get("expires_in")  # saniye (~60 gün)
        if not yeni_token:
            self._basarisiz(opts, f"Yanıtta access_token yok: {r.text[:300]}")
            return

        simdi = datetime.now(timezone.utc)
        expires_iso = (
            (simdi + timedelta(seconds=int(expires_in))).isoformat()
            if expires_in else "bilinmiyor"
        )
        gun = (int(expires_in) // 86400) if expires_in else "?"

        if opts["kuru"]:
            self.stdout.write(self.style.SUCCESS(
                f"[--kuru] Yenileme başarılı — DB'ye YAZILMADI. "
                f"Yeni token ~{gun} gün geçerli (bitiş {expires_iso})."))
            return

        # Başarılı → DB'ye yaz (token + yenilenme + bitiş zamanı).
        session = SessionLocal()
        try:
            set_ayar(session, "ig_token", yeni_token)
            set_ayar(session, "ig_token_yenilenme", simdi.isoformat())
            set_ayar(session, "ig_token_expires", expires_iso)
            session.commit()
        finally:
            session.close()
        meta_client._ig_token_cache = None          # canlı süreç yeni token'ı hemen alsın

        self.stdout.write(self.style.SUCCESS(
            f"IG token yenilendi ✅  ~{gun} gün geçerli (bitiş {expires_iso})."))

    def _basarisiz(self, opts, ayrinti: str) -> None:
        """Yenileme başarısız — logla; --kuru değilse İsmail'e uyarı gönder."""
        mesaj = ("⚠️ IG TOKEN YENİLENEMEDİ\n"
                 f"{ayrinti}\n"
                 "Instagram botu token dolunca sessizce durur — token'ı elle "
                 "yenileyip  manage.py ig_token_yenile --tohum <TOKEN>  ile besle.")
        self.stderr.write(mesaj)
        if not opts["kuru"]:
            try:
                from bot import bildirim
                bildirim.sistem_uyari("instALL ajan — ⚠️ IG token yenilenemedi", mesaj)
            except Exception:
                self.stderr.write("(uyarı bildirimi de gönderilemedi)")
        sys.exit(1)
