"""Instagram webhook'una 'comments' alanını abone eder (yorumdan-DM için şart).

Mevcut abonelik yalnızca messages + messaging_postbacks'ti (faz-4 kurulumu).
Bu komut ÜÇÜNÜ birden yeniden gönderir (subscribed_fields listesi TAM olarak
verilenle değişir — eksik yazarsan mevcut alan da düşer, bu yüzden hepsi burada).

⚠️ Token her yenilendiğinde bu abonelik SIFIRLANIR (faz-4 tuzak #2) — token
yenileme koştuğunda (ig_token_yenile) ayrıca bu komutu da çalıştırmak gerekebilir.

Kullanım:
  python manage.py ig_yorum_abone            # abone et
  python manage.py ig_yorum_abone --kontrol  # mevcut aboneliği göster, değiştirme
"""
from __future__ import annotations

import sys

import requests
from django.core.management.base import BaseCommand

ABONE_ALANLAR = "messages,messaging_postbacks,comments"


class Command(BaseCommand):
    help = "IG webhook aboneliğine 'comments' alanını ekler (yorumdan-DM için)."

    def add_arguments(self, parser):
        parser.add_argument("--kontrol", action="store_true",
                            help="Sadece mevcut aboneliği göster, değiştirme.")

    def handle(self, *args, **opts):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")

        from django.conf import settings
        from bot import meta_client
        token = meta_client.aktif_ig_token()
        if not token:
            self.stderr.write("IG token yok — önce manage.py ig_token_yenile --tohum ile besle.")
            sys.exit(1)

        base = f"https://graph.instagram.com/{settings.GRAPH_API_VERSION}/me"
        headers = {"Authorization": f"Bearer {token}"}

        if opts["kontrol"]:
            r = requests.get(f"{base}/subscribed_apps", headers=headers, timeout=15)
            self.stdout.write(f"HTTP {r.status_code}: {r.text}")
            return

        r = requests.post(f"{base}/subscribed_apps",
                          params={"subscribed_fields": ABONE_ALANLAR},
                          headers=headers, timeout=15)
        if r.status_code == 200 and r.json().get("success"):
            self.stdout.write(self.style.SUCCESS(
                f"Abone olundu: {ABONE_ALANLAR}"))
        else:
            self.stderr.write(f"Abonelik başarısız — HTTP {r.status_code}: {r.text}")
            sys.exit(1)
