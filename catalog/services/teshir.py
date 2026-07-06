"""Teşhir servisi — mağazada sergilenen ürünler + efektif fiyat çözümü.

"Bağlı + gerekirse ez" modeli (2026-07-06 kararı):
- Kayıttaki fiyat/içerik alanı DOLUYSA o geçerli ("magaza" kaynağı).
- BOŞSA bağlı kombinasyonun güncel web verisi geçerli ("web" kaynağı).
- Kombinasyon bağlı değilse ve alan boşsa → None (fiyat belirtilmemiş).

Panel (/app/teshir/) ve AI ajanın teshir_bilgi aracı bu modülü kullanır.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from catalog.database import SessionLocal
from catalog.sa_models import Kategori, Koleksiyon, Kombinasyon, KombinasyonUrun, Teshir
from catalog.services.kombinasyon import hesapla_kombinasyon_toplam


def _kombi_yukle(session, kombi_id: int) -> Kombinasyon | None:
    return session.scalar(
        select(Kombinasyon)
        .where(Kombinasyon.id == kombi_id)
        .options(selectinload(Kombinasyon.urunler).selectinload(KombinasyonUrun.urun))
    )


def _kombi_icerik(kombi: Kombinasyon) -> str:
    return ", ".join(
        f"{ku.miktar}× {ku.urun.urun_adi_tam}"
        for ku in kombi.urunler if ku.urun is not None
    )


def _coz(session, t: Teshir) -> dict:
    """Tek teşhir kaydını efektif değerleriyle sözlüğe çevir."""
    kol = session.get(Koleksiyon, t.koleksiyon_id)
    kat = session.get(Kategori, kol.kategori_id) if kol else None

    kombi = _kombi_yukle(session, t.kombinasyon_id) if t.kombinasyon_id else None
    web = hesapla_kombinasyon_toplam(kombi) if kombi else {}

    liste = t.liste_fiyat if t.liste_fiyat is not None else web.get("toplam_liste")
    perakende = (t.perakende_fiyat if t.perakende_fiyat is not None
                 else web.get("toplam_perakende"))
    icerik = (t.icerik or "").strip() or (_kombi_icerik(kombi) if kombi else "")

    return {
        "id": t.id,
        "baslik": (t.baslik or "").strip() or (kol.ad if kol else "?"),
        "kategori": kat.ad if kat else "",
        "kategori_id": kol.kategori_id if kol else None,
        "koleksiyon": kol.ad if kol else "?",
        "koleksiyon_id": t.koleksiyon_id,
        "kombinasyon": kombi.ad if kombi else "",
        "kombinasyon_id": t.kombinasyon_id,
        "icerik": icerik,
        "liste_fiyat": liste,
        "perakende_fiyat": perakende,
        # Panelde "mağaza fiyatı mı web fiyatı mı" rozetleri için:
        "fiyat_kaynak": "magaza" if (t.liste_fiyat is not None
                                     or t.perakende_fiyat is not None) else "web",
        "icerik_kaynak": "magaza" if (t.icerik or "").strip() else "web",
        # Ham değerler (düzenleme formu doldurmak için):
        "ham_baslik": t.baslik or "",
        "ham_icerik": t.icerik or "",
        "ham_liste": t.liste_fiyat,
        "ham_perakende": t.perakende_fiyat,
        "notlar": t.notlar or "",
        "guncelleme": t.guncelleme,
    }


def listele() -> list[dict]:
    """Tüm teşhir kayıtları (panel listesi) — kategori/koleksiyon adına göre sıralı."""
    session = SessionLocal()
    try:
        rows = session.scalars(select(Teshir)).all()
        data = [_coz(session, t) for t in rows]
        data.sort(key=lambda d: (d["kategori"], d["koleksiyon"], d["baslik"]))
        return data
    finally:
        session.close()


def ajan_icin(koleksiyon_id: int | None = None) -> list[dict]:
    """AI ajanın teshir_bilgi aracı için sade görünüm.

    Yalnızca müşteriye söylenebilecek alanlar döner (iç notlar HARİÇ).
    """
    session = SessionLocal()
    try:
        sorgu = select(Teshir)
        if koleksiyon_id:
            sorgu = sorgu.where(Teshir.koleksiyon_id == int(koleksiyon_id))
        rows = session.scalars(sorgu).all()
        sonuc = []
        for t in rows:
            d = _coz(session, t)
            sonuc.append({
                "ad": d["baslik"],
                "kategori": d["kategori"],
                "koleksiyon": d["koleksiyon"],
                "icerik": d["icerik"],
                "liste_fiyat": d["liste_fiyat"],
                "perakende_fiyat": d["perakende_fiyat"],
                "para_birimi": "TL",
            })
        return sonuc
    finally:
        session.close()
