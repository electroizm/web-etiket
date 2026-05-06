"""Otomatik kombinasyon servisi — DB'deki regex kurallarıyla eşleştirme.

Akış:
  1. Koleksiyonun kategorisi için kategori_kombinasyon_kurallari'dan kuralları çek
  2. Her kural için (her bir slot regex'i için) koleksiyondaki ürünlerden ilk eşleşeni bul
  3. Adet override'ları uygula (komodin 2x, sandalye 6x gibi)
  4. Preview döner ya da gerçekten kombinasyon kayıtları oluşturur
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog.sa_models import (
    KategoriKombinasyonKurali,
    Koleksiyon,
    Urun,
    urun_koleksiyon,
)
from catalog.services.kombinasyon import (
    KombinasyonAdiCakismasiError,
    kombinasyon_olustur,
)


class OtoKombinasyonError(Exception):
    """Otomatik kombinasyon işleminde hata."""


class EslesmeYok(Exception):
    """Hiçbir slot için eşleşme bulunamadı."""


def _safe_search(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text or "", re.IGNORECASE) is not None
    except re.error:
        return False


def otomatik_kombinasyon_preview(db: Session, koleksiyon_id: int) -> dict:
    """Preview döndürür — bulunan ürünleri ve adet bilgisini gösterir.

    Returns: {
      "kategori_ad": "...",
      "kombinasyonlar": [
        {
          "ad": "6 Kapaklı, Karyola",
          "slots": [
            {"pattern": "...", "matched": True,
             "urun": {"id": ..., "sku": ..., "ad": "..."}, "miktar": 1},
            {"pattern": "...", "matched": False, "urun": None, "miktar": 1},
            ...
          ],
          "tum_eslesti": True,
        },
        ...
      ]
    }
    """
    koleksiyon = db.scalar(
        select(Koleksiyon).where(Koleksiyon.id == koleksiyon_id)
    )
    if koleksiyon is None:
        raise OtoKombinasyonError("Koleksiyon bulunamadı.")

    # Kategoriyi bul
    from catalog.sa_models import Kategori
    kategori = db.scalar(select(Kategori).where(Kategori.id == koleksiyon.kategori_id))
    if kategori is None:
        raise OtoKombinasyonError("Kategori bulunamadı.")

    # Aktif kuralları çek
    kurallar = list(db.scalars(
        select(KategoriKombinasyonKurali)
        .where(
            KategoriKombinasyonKurali.kategori_id == kategori.id,
            KategoriKombinasyonKurali.aktif.is_(True),
        )
        .order_by(KategoriKombinasyonKurali.sira, KategoriKombinasyonKurali.kombinasyon_adi)
    ).all())

    if not kurallar:
        raise OtoKombinasyonError(
            f"'{kategori.ad}' kategorisi için tanımlı otomatik kombinasyon kuralı yok."
        )

    # Koleksiyondaki SADECE etiket_secili=True ürünleri al — kullanıcı çoktan
    # işaretlediği ürünler üzerinden otomatik kombinasyon kurulur.
    urunler: list[Urun] = list(db.scalars(
        select(Urun)
        .join(urun_koleksiyon, urun_koleksiyon.c.urun_id == Urun.id)
        .where(
            urun_koleksiyon.c.koleksiyon_id == koleksiyon_id,
            urun_koleksiyon.c.etiket_secili.is_(True),
        )
        .order_by(Urun.urun_adi_tam)
    ).all())

    if not urunler:
        raise EslesmeYok(
            "Etiket için işaretli ürün yok. Önce koleksiyon sayfasında en az "
            "bir ürünü işaretleyin."
        )

    sonuc_kombinasyonlar = []
    for kural in kurallar:
        patterns = list(kural.patterns or [])
        adet_overrides = dict(kural.adet_overrides or {})

        slots = []
        tum_eslesti = True
        for pattern in patterns:
            # Bu pattern için ilk eşleşen ürün
            matched_urun: Urun | None = None
            for u in urunler:
                if _safe_search(pattern, u.urun_adi_tam):
                    matched_urun = u
                    break

            # Adet
            miktar = adet_overrides.get(pattern, 1)
            try:
                miktar = max(1, int(miktar))
            except (TypeError, ValueError):
                miktar = 1

            if matched_urun is None:
                tum_eslesti = False
                slots.append({
                    "pattern": pattern,
                    "matched": False,
                    "urun": None,
                    "miktar": miktar,
                })
            else:
                slots.append({
                    "pattern": pattern,
                    "matched": True,
                    "urun": {
                        "id": matched_urun.id,
                        "sku": matched_urun.sku,
                        "ad": matched_urun.urun_adi_tam,
                    },
                    "miktar": miktar,
                })

        sonuc_kombinasyonlar.append({
            "ad": kural.kombinasyon_adi,
            "slots": slots,
            "tum_eslesti": tum_eslesti,
        })

    return {
        "kategori_ad": kategori.ad,
        "kombinasyonlar": sonuc_kombinasyonlar,
    }


def otomatik_kombinasyon_olustur(db: Session, koleksiyon_id: int) -> dict:
    """Preview'i hesapla, eşleşen ürünleri kombinasyon olarak DB'ye kaydet.

    - Sadece tüm slot'ları eşleşen kombinasyonlar oluşturulur (parça eksikse atlanır).
    - Aynı isimde kombinasyon zaten varsa SKIP edilir (KombinasyonAdiCakismasiError yakalanır).

    Returns: {"olusturuldu": [{ad, urun_sayisi}, ...], "atlandi": [{ad, sebep}, ...]}
    """
    preview = otomatik_kombinasyon_preview(db, koleksiyon_id)

    olusturuldu: list[dict] = []
    atlandi: list[dict] = []

    for kombi in preview["kombinasyonlar"]:
        if not kombi["tum_eslesti"]:
            atlandi.append({
                "ad": kombi["ad"],
                "sebep": "Bazı parçalar eşleşmedi",
            })
            continue

        urun_miktarlari = [
            (slot["urun"]["id"], slot["miktar"])
            for slot in kombi["slots"]
            if slot["matched"]
        ]
        # Aynı ürün birden fazla slot'ta eşleşmiş olabilir — birleştir (max miktar)
        merged: dict[int, int] = {}
        for uid, m in urun_miktarlari:
            merged[uid] = max(merged.get(uid, 0), m)

        try:
            yeni = kombinasyon_olustur(
                db, koleksiyon_id, kombi["ad"], list(merged.items())
            )
            olusturuldu.append({
                "ad": yeni.ad,
                "id": yeni.id,
                "urun_sayisi": len(merged),
            })
        except KombinasyonAdiCakismasiError:
            atlandi.append({
                "ad": kombi["ad"],
                "sebep": "Aynı isimde kombinasyon zaten var",
            })

    return {"olusturuldu": olusturuldu, "atlandi": atlandi}
