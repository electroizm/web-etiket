"""Tek bir fotoğrafla görsel eşleştirmeyi dene — canlıya dokunmadan.

    python manage.py gorsel_dene "C:\\Users\\GUNES\\Desktop\\koltuk.jpg"
    python manage.py gorsel_dene https://ornek.com/koltuk.jpg

Ne yapar: fotoğrafı botun kullandığı görsel modelle TARİF ettirir, tarifi
katalogdaki ürün fotoğrafı tarifleriyle karşılaştırır ve en yakın adayları
fiyatlarıyla listeler.

KAPSAM KAPISINI ATLAR (--zorla varsayılan açık): katalog henüz yarıya
gelmemişken de sonucu görebilesin diye. Canlı bot bu kapıya uyar; buradaki
sonuç "katalog dolunca ne olacak"ın önizlemesidir. Katalog küçükken adayların
yanlış çıkması NORMALDİR — kapının varlık sebebi tam olarak budur.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand
from sqlalchemy import select, text

from bot import gorsel_eslestir
from catalog.database import SessionLocal
from catalog.sa_models import Urun


class Command(BaseCommand):
    help = "Bir fotoğrafı katalogla eşleştirip en yakın ürünleri gösterir."

    def add_arguments(self, parser):
        parser.add_argument("kaynak", help="fotoğraf dosya yolu ya da http(s) adresi")
        parser.add_argument("--adet", type=int, default=5, help="kaç aday")

    def handle(self, *args, **secenekler):
        kaynak = secenekler["kaynak"]

        session = SessionLocal()
        try:
            islenmis = session.execute(text(
                "SELECT count(*) FROM urun_gorsel_vektor")).scalar() or 0
            toplam = session.execute(text(
                "SELECT count(*) FROM urunler WHERE son_perakende_fiyat > 0"
            )).scalar() or 0
        finally:
            session.close()
        oran = round(islenmis * 100 / toplam) if toplam else 0
        self.stdout.write(f"katalog kapsami: {islenmis}/{toplam} (%{oran}) "
                          f"— canli botta esik %{int(gorsel_eslestir.KAPSAM_ESIGI*100)}")
        if oran < gorsel_eslestir.KAPSAM_ESIGI * 100:
            self.stdout.write(self.style.WARNING(
                "  UYARI: katalog yarisi dolmadi. Canli bot bu ozelligi HENUZ "
                "kullanmiyor; asagidaki sonuc onizlemedir ve yanlis cikabilir."))

        # ── 1) Fotoğrafı tarif ettir
        self.stdout.write("\nfotograf tarif ediliyor...")
        if kaynak.startswith(("http://", "https://")):
            tarif = gorsel_eslestir.tarif_uret(gorsel_url=kaynak)
        else:
            if not os.path.exists(kaynak):
                self.stderr.write(f"dosya bulunamadi: {kaynak}")
                return
            with open(kaynak, "rb") as f:
                veri = f.read()
            uzanti = os.path.splitext(kaynak)[1].lower().lstrip(".") or "jpeg"
            mime = f"image/{'jpeg' if uzanti in ('jpg', 'jpeg') else uzanti}"
            tarif = gorsel_eslestir.tarif_uret(veri=veri, mime=mime)

        if not tarif:
            self.stderr.write("tarif uretilemedi (model kotasi ya da okunamayan gorsel)")
            return
        self.stdout.write(self.style.SUCCESS(f"  TARIF: {tarif}"))

        # ── 2) Katalogda ara (kapsam kapısını atlayarak)
        _asil = gorsel_eslestir.kapsam_yeterli_mi
        gorsel_eslestir.kapsam_yeterli_mi = lambda: True
        try:
            adaylar = gorsel_eslestir.benzerleri_bul(tarif, limit=secenekler["adet"])
        finally:
            gorsel_eslestir.kapsam_yeterli_mi = _asil

        if not adaylar:
            self.stdout.write("  katalogda aday bulunamadi (katalog bos olabilir)")
            return

        self.stdout.write("\nEN YAKIN URUNLER:")
        session = SessionLocal()
        try:
            for i, a in enumerate(adaylar, 1):
                u = session.scalars(
                    select(Urun).where(Urun.sku == a["sku"]).limit(1)).first()
                fiyat = (f"{u.son_perakende_fiyat:,} TL".replace(",", ".")
                         if u and u.son_perakende_fiyat else "fiyat yok")
                self.stdout.write(f"  {i}. {a['ad'][:46]:48} {fiyat:>14}"
                                  f"   benzerlik {a['benzerlik']}")
                self.stdout.write(f"     katalog tarifi: {(a['tarif'] or '')[:96]}")
        finally:
            session.close()
