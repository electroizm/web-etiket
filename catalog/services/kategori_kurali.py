"""
KategoriKurali servisi: CRUD + match logic.

İki tür kural:
- "filtre"      → eşleşen ürünleri DB'ye yazma
- "duplikasyon" → ürünü hedef_kategori altında da koleksiyona bağla
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog.sa_models import KategoriKurali


# ─── Tür sabitleri ───────────────────────────────────────────────────────────

TUR_FILTRE = "filtre"
TUR_DUPLIKASYON = "duplikasyon"
GECERLI_TURLER = {TUR_FILTRE, TUR_DUPLIKASYON}


# ─── Hatalar ─────────────────────────────────────────────────────────────────


class KuralHatasi(ValueError):
    """Kural validation hatası."""


# ─── CRUD ────────────────────────────────────────────────────────────────────


def kurali_listele(db: Session, tur: str | None = None) -> list[KategoriKurali]:
    """Tüm kuralları (veya belirli tür) listele."""
    stmt = select(KategoriKurali).order_by(
        KategoriKurali.tur, KategoriKurali.olusturma_tarihi.desc()
    )
    if tur:
        stmt = stmt.where(KategoriKurali.tur == tur)
    return list(db.scalars(stmt).all())


def kural_olustur(
    db: Session,
    *,
    tur: str,
    kaynak_kategori: str | None,
    hedef_kategori: str | None,
    kelimeler: str | None,
) -> KategoriKurali:
    """Yeni kural ekle. Validation yapar."""
    if tur not in GECERLI_TURLER:
        raise KuralHatasi(f"Geçersiz tür: {tur}")

    # Boş string'leri NULL'a çevir
    kaynak = (kaynak_kategori or "").strip() or None
    hedef = (hedef_kategori or "").strip() or None
    kelime_csv = (kelimeler or "").strip() or None

    if tur == TUR_DUPLIKASYON:
        if not kaynak:
            raise KuralHatasi("Duplikasyon için kaynak_kategori zorunlu")
        if not hedef:
            raise KuralHatasi("Duplikasyon için hedef_kategori zorunlu")
        if not kelime_csv:
            raise KuralHatasi("Duplikasyon için kelimeler zorunlu")

    if tur == TUR_FILTRE:
        if not kaynak and not kelime_csv:
            raise KuralHatasi(
                "Filtre için en az kaynak_kategori veya kelimeler dolu olmalı"
            )

    kural = KategoriKurali(
        tur=tur,
        kaynak_kategori=kaynak,
        hedef_kategori=hedef if tur == TUR_DUPLIKASYON else None,
        kelimeler=kelime_csv,
        aktif=True,
    )
    db.add(kural)
    db.commit()
    db.refresh(kural)
    return kural


def kural_sil(db: Session, kural_id: int) -> bool:
    """Kuralı sil. Yoksa False."""
    kural = db.get(KategoriKurali, kural_id)
    if kural is None:
        return False
    db.delete(kural)
    db.commit()
    return True


def kural_toggle(db: Session, kural_id: int) -> KategoriKurali | None:
    """Aktif/pasif değiştir."""
    kural = db.get(KategoriKurali, kural_id)
    if kural is None:
        return None
    kural.aktif = not kural.aktif
    db.commit()
    db.refresh(kural)
    return kural


# ─── Match logic (scraper için) ──────────────────────────────────────────────


@dataclass(frozen=True)
class FiltreKurali:
    """Tek filtre kuralının hafif kopyası (scraper'da kullanılır)."""
    kaynak_kategori: str | None  # boş → boş kategoriyi hedefler
    kelimeler: tuple[str, ...]   # küçük harf, tuple


@dataclass(frozen=True)
class DuplikasyonKuralı:
    kaynak_kategori: str
    hedef_kategori: str
    kelimeler: tuple[str, ...]


def aktif_filtre_kurallari(db: Session) -> list[FiltreKurali]:
    """Aktif filtre kurallarını döndür."""
    rows = db.scalars(
        select(KategoriKurali).where(
            KategoriKurali.tur == TUR_FILTRE,
            KategoriKurali.aktif.is_(True),
        )
    ).all()
    return [
        FiltreKurali(
            kaynak_kategori=(r.kaynak_kategori or "").strip() or None,
            kelimeler=tuple(r.kelime_listesi()),
        )
        for r in rows
    ]


def aktif_duplikasyon_kurallari(db: Session) -> list[DuplikasyonKuralı]:
    """Aktif duplikasyon kurallarını döndür."""
    rows = db.scalars(
        select(KategoriKurali).where(
            KategoriKurali.tur == TUR_DUPLIKASYON,
            KategoriKurali.aktif.is_(True),
        )
    ).all()
    sonuc: list[DuplikasyonKuralı] = []
    for r in rows:
        if not r.kaynak_kategori or not r.hedef_kategori:
            continue
        kelimeler = tuple(r.kelime_listesi())
        if not kelimeler:
            continue
        sonuc.append(
            DuplikasyonKuralı(
                kaynak_kategori=r.kaynak_kategori.strip(),
                hedef_kategori=r.hedef_kategori.strip(),
                kelimeler=kelimeler,
            )
        )
    return sonuc


def filtrele_mi(
    *,
    kategori: str,
    urun_adi: str,
    kurallar: list[FiltreKurali],
) -> bool:
    """
    True = ürün filtrelenmeli (atlanmalı)

    Kural semantik:
    - kaynak_kategori dolu, kelimeler boş → kategori match → at
    - kaynak_kategori boş/None, kelimeler dolu → kategori boş + kelime match → at
    - kaynak_kategori dolu, kelimeler dolu → kategori match + kelime match → at
    """
    kategori_lower = (kategori or "").strip().lower()
    urun_lower = (urun_adi or "").lower()

    for kural in kurallar:
        kaynak_lower = (kural.kaynak_kategori or "").lower()

        # Kategori match kontrolü
        if kaynak_lower:
            if kategori_lower != kaynak_lower:
                continue
        else:
            # kaynak boş → sadece "kategori boş" durumunda match
            if kategori_lower:
                continue

        # Kelime match kontrolü
        if kural.kelimeler:
            if not any(k in urun_lower for k in kural.kelimeler):
                continue

        return True

    return False


def duplikasyon_hedefleri(
    *,
    kategori: str,
    urun_adi: str,
    kurallar: list[DuplikasyonKuralı],
) -> list[str]:
    """Eşleşen duplikasyon kuralları için hedef kategori adlarını döndür."""
    kategori_lower = (kategori or "").strip().lower()
    urun_lower = (urun_adi or "").lower()
    hedefler: list[str] = []

    for kural in kurallar:
        if kategori_lower != kural.kaynak_kategori.lower():
            continue
        if not any(k in urun_lower for k in kural.kelimeler):
            continue
        hedefler.append(kural.hedef_kategori)

    return hedefler
