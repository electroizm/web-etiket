"""Menü durum makinesi: kullanıcının seçimine göre bir sonraki mesajı üretir.

Durum butonun payload'ında taşınır (KAT/KOL/KOM), köprü stateless kalır.
İki şey enjekte edilebilir: veri kaynağı (test için sahte) ve P (sunum modülü).
P, platforma göre ig_presenter ya da wa_presenter olur — ikisi de aynı fonksiyon
adlarını sunduğu için menü mantığı tek yerde kalır (DRY).
"""
from __future__ import annotations

from catalog.services import menu_veri as _default_veri
from bot import ig_presenter as _default_P
from bot.webhook_core import parse_secim


def _int(s: str | None) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def yanit_uret(tetik: str, veri=_default_veri, P=_default_P) -> dict:
    """Tetik token'ından (START / KAT:.. / KOL:.. / KOM:..) mesaj payload'ı üret."""
    tur, deger = parse_secim(tetik)
    _id = _int(deger)

    if tur == "KAT" and _id is not None:
        return P.koleksiyonlar_mesaji(veri.koleksiyonlar(_id))
    if tur == "KOL" and _id is not None:
        return P.kombinasyonlar_mesaji(veri.kombinasyonlar(_id))
    if tur == "KOM" and _id is not None:
        return P.kombinasyon_detay_mesaji(veri.kombinasyon(_id))

    # START veya tanınmayan serbest metin → baştan kategori menüsü.
    return P.kategoriler_mesaji(veri.kategoriler())
