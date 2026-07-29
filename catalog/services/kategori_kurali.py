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


# NOT: Kural CRUD fonksiyonları (kurali_listele / kural_olustur / kural_sil /
# kural_toggle) 2026-07-29'da silindi — hiçbir yerden çağrılmıyorlardı. Kurallar
# panelde değil, doğrudan veritabanından yönetiliyor; scraper yalnız aşağıdaki
# okuma fonksiyonlarını kullanır. Gerekirse git geçmişinden geri alınabilir.


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
