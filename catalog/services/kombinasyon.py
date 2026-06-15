"""Kombinasyon iş mantığı (CRUD + toplam fiyat hesabı).

Toplam fiyat anlık hesaplanır (cache yok) — scraper fiyat değiştirdiğinde
otomatik güncel görünür.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from catalog.sa_models import Kombinasyon, KombinasyonUrun


class KombinasyonAdiCakismasiError(ValueError):
    """Bu koleksiyonda bu adda kombinasyon zaten var."""


def kombinasyon_listele(
    db: Session, koleksiyon_id: int
) -> list[Kombinasyon]:
    """Bir koleksiyonun tüm kombinasyonları (urunler + urun ilişkisi yüklü)."""
    return list(
        db.scalars(
            select(Kombinasyon)
            .where(Kombinasyon.koleksiyon_id == koleksiyon_id)
            .order_by(Kombinasyon.sira, Kombinasyon.ad)
            .options(
                selectinload(Kombinasyon.urunler).selectinload(KombinasyonUrun.urun)
            )
        ).all()
    )


def kombinasyon_olustur(
    db: Session,
    koleksiyon_id: int,
    ad: str,
    urun_miktarlari: list[tuple[int, int]],
) -> Kombinasyon:
    """Yeni kombinasyon oluştur.

    Args:
        urun_miktarlari: [(urun_id, miktar), ...]  miktar < 1 olanlar atlanır.
    """
    ad = (ad or "").strip()
    if not ad:
        raise ValueError("Kombinasyon adı boş olamaz")

    mevcut = db.scalar(
        select(Kombinasyon).where(
            Kombinasyon.koleksiyon_id == koleksiyon_id,
            Kombinasyon.ad == ad,
        )
    )
    if mevcut is not None:
        raise KombinasyonAdiCakismasiError(f"'{ad}' adında kombinasyon zaten var")

    # Sıra: koleksiyondaki en yüksek + 1
    max_sira = (
        db.scalar(
            select(Kombinasyon.sira)
            .where(Kombinasyon.koleksiyon_id == koleksiyon_id)
            .order_by(Kombinasyon.sira.desc())
            .limit(1)
        )
        or 0
    )

    kombi = Kombinasyon(koleksiyon_id=koleksiyon_id, ad=ad, sira=max_sira + 1)
    db.add(kombi)
    db.flush()

    for urun_id, miktar in urun_miktarlari:
        if miktar < 1:
            continue
        db.add(KombinasyonUrun(kombinasyon_id=kombi.id, urun_id=urun_id, miktar=miktar))

    db.commit()
    db.refresh(kombi)
    return kombi


def kombinasyon_guncelle(
    db: Session,
    kombinasyon_id: int,
    ad: str,
    urun_miktarlari: list[tuple[int, int]],
) -> Kombinasyon:
    """Mevcut kombinasyonu güncelle. Ürün listesini sıfırdan yazar."""
    kombi = db.get(Kombinasyon, kombinasyon_id)
    if kombi is None:
        raise ValueError(f"Kombinasyon {kombinasyon_id} bulunamadı")

    ad = (ad or "").strip()
    if not ad:
        raise ValueError("Kombinasyon adı boş olamaz")

    if kombi.ad != ad:
        cakisma = db.scalar(
            select(Kombinasyon).where(
                Kombinasyon.koleksiyon_id == kombi.koleksiyon_id,
                Kombinasyon.ad == ad,
                Kombinasyon.id != kombinasyon_id,
            )
        )
        if cakisma is not None:
            raise KombinasyonAdiCakismasiError(f"'{ad}' adında başka kombinasyon var")
        kombi.ad = ad

    # Eski ürün bağlantılarını temizle
    for ku in list(kombi.urunler):
        db.delete(ku)
    db.flush()

    for urun_id, miktar in urun_miktarlari:
        if miktar < 1:
            continue
        db.add(KombinasyonUrun(kombinasyon_id=kombi.id, urun_id=urun_id, miktar=miktar))

    db.commit()
    db.refresh(kombi)
    return kombi


def kombinasyon_sil(db: Session, kombinasyon_id: int) -> int | None:
    """Kombinasyonu sil. İçindeki koleksiyon_id'yi döner (redirect için)."""
    kombi = db.get(Kombinasyon, kombinasyon_id)
    if kombi is None:
        return None
    koleksiyon_id = kombi.koleksiyon_id
    db.delete(kombi)
    db.commit()
    return koleksiyon_id


# ─── Toplam fiyat (anlık) ────────────────────────────────────────────────────


def hesapla_kombinasyon_toplam(kombi: Kombinasyon) -> dict:
    """Kombinasyon × miktar üzerinden toplamları hesapla.

    Returns: {
        "toplam_liste": int (TL) | None,
        "toplam_perakende": int (TL) | None,
        "indirim_yuzde": int | None,
        "urun_sayisi": int,
        "toplam_adet": int,
    }
    """
    toplam_liste = 0
    toplam_perakende = 0
    has_liste = False
    has_perakende = False
    urun_sayisi = 0
    toplam_adet = 0

    for ku in kombi.urunler:
        urun_sayisi += 1
        toplam_adet += ku.miktar
        u = ku.urun
        if u and u.son_liste_fiyat is not None:
            toplam_liste += u.son_liste_fiyat * ku.miktar
            has_liste = True
        if u and u.son_perakende_fiyat is not None:
            toplam_perakende += u.son_perakende_fiyat * ku.miktar
            has_perakende = True

    indirim = None
    if has_liste and has_perakende and toplam_liste > 0 and toplam_perakende < toplam_liste:
        indirim = int(round((1 - toplam_perakende / toplam_liste) * 100))

    return {
        "toplam_liste": toplam_liste if has_liste else None,
        "toplam_perakende": toplam_perakende if has_perakende else None,
        "indirim_yuzde": indirim,
        "urun_sayisi": urun_sayisi,
        "toplam_adet": toplam_adet,
    }
