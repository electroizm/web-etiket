"""Görsel eşleştirme kataloğunu kur: her ürün fotoğrafını tarif edip vektörle.

    python manage.py gorsel_katalog --limit 25     # deneme
    python manage.py gorsel_katalog                # tamamı
    python manage.py gorsel_katalog --durum        # ilerleme raporu

Tekrarlanabilir: zaten işlenmiş SKU atlanır, yarıda kalırsa kaldığı yerden
devam eder. Hiçbir ürün hatası işi durdurmaz — atlanır, sonraki tura kalır.

Maliyet (ölçüldü): ürün başına ~1,5K görsel token. 1.783 ürün ≈ 2,7M token,
qwen3.7-flash ile ~10 sent. Süre ~2 saat (fotoğraf sayfası + tarif + vektör).
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from sqlalchemy import select, text

from bot import gorsel_eslestir, urun_gorsel
from catalog.database import SessionLocal
from catalog.sa_models import Urun


class Command(BaseCommand):
    help = "Ürün fotoğraflarını tarif edip vektör kataloğuna yazar."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0,
                            help="en fazla kaç ürün işlensin (0 = hepsi)")
        parser.add_argument("--bekle", type=float, default=1.5,
                            help="ürünler arası bekleme (saniye)")
        parser.add_argument("--durum", action="store_true",
                            help="yalnız ilerlemeyi göster, işlem yapma")

    def handle(self, *args, **secenekler):
        gorsel_eslestir.tablo_kur()
        session = SessionLocal()
        try:
            islenmis = set(session.execute(
                text("SELECT sku FROM urun_gorsel_vektor")).scalars().all())
            adaylar = session.execute(
                select(Urun.sku, Urun.urun_adi_tam)
                .where(Urun.son_perakende_fiyat > 0,
                       Urun.url.isnot(None), Urun.url != "")
                .order_by(Urun.urun_adi_tam)).all()
        finally:
            session.close()

        kalan = [(s, a) for s, a in adaylar if s not in islenmis]
        self.stdout.write(
            f"aday {len(adaylar)} · islenmis {len(islenmis)} · kalan {len(kalan)}")
        if secenekler["durum"]:
            return
        if secenekler["limit"]:
            kalan = kalan[:secenekler["limit"]]

        basarili = atlanan = 0
        for i, (sku, ad) in enumerate(kalan, 1):
            try:
                url = urun_gorsel.url_bul(sku)
                if not url:
                    atlanan += 1
                    self.stdout.write(f"  {i}/{len(kalan)} ATLA (foto yok) {ad[:40]}")
                    continue
                tarif = gorsel_eslestir.tarif_uret(gorsel_url=url)
                if not tarif:
                    atlanan += 1
                    self.stdout.write(f"  {i}/{len(kalan)} ATLA (tarif yok) {ad[:40]}")
                    continue
                v = gorsel_eslestir.vektor(tarif)
                if not v:
                    atlanan += 1
                    self.stdout.write(f"  {i}/{len(kalan)} ATLA (vektor yok) {ad[:40]}")
                    continue
                s2 = SessionLocal()
                try:
                    s2.execute(text("""
                        INSERT INTO urun_gorsel_vektor
                               (sku, gorsel_url, tarif, vektor, guncelleme)
                        VALUES (:sku, :url, :tarif, CAST(:v AS vector), now())
                        ON CONFLICT (sku) DO UPDATE SET
                            gorsel_url = EXCLUDED.gorsel_url,
                            tarif      = EXCLUDED.tarif,
                            vektor     = EXCLUDED.vektor,
                            guncelleme = now()
                    """), {"sku": sku, "url": url, "tarif": tarif, "v": str(v)})
                    s2.commit()
                finally:
                    s2.close()
                basarili += 1
                if i % 10 == 0 or i == len(kalan):
                    self.stdout.write(f"  {i}/{len(kalan)} · {ad[:34]} · {tarif[:52]}")
            except Exception as e:                      # tek ürün işi durdurmasın
                atlanan += 1
                self.stdout.write(f"  {i}/{len(kalan)} HATA {type(e).__name__} {ad[:34]}")
            time.sleep(secenekler["bekle"])

        self.stdout.write(self.style.SUCCESS(
            f"bitti — yazilan {basarili}, atlanan {atlanan}"))
