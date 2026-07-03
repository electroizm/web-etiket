"""Menü durum makinesi: kullanıcının seçimine göre bir sonraki mesajı üretir.

Durum butonun payload'ında taşınır (KAT/KOL/KOM), köprü stateless kalır.
İki şey enjekte edilebilir: veri kaynağı (test için sahte) ve P (sunum modülü).
P, platforma göre ig_presenter ya da wa_presenter olur — ikisi de aynı fonksiyon
adlarını sunduğu için menü mantığı tek yerde kalır (DRY).

Ayrıca "Yetkiliyle görüş" akışı: müşteri butona basar ya da "yetkili/temsilci/canlı"
gibi yazarsa, botun 0488 Cloud API kutusunu İsmail elle göremediği için müşteri
İsmail'in kişisel WhatsApp'ına (0532) yönlendirilir.
"""
from __future__ import annotations

from django.utils import timezone

from catalog.services import menu_veri as _default_veri
from bot import ig_presenter as _default_P
from bot.webhook_core import parse_secim

# ── Yetkiliye yönlendirme ────────────────────────────────────────────────────
YETKILI_WA = "905321370627"            # wa.me linki (0532 137 06 27)
YETKILI_TEL_GORUNEN = "0532 137 06 27"
YETKILI_PAYLOAD = "YETKILI"
# Serbest metinde yetkili talebi sayılan kelimeler (küçük harfte aranır).
YETKILI_KELIMELER = ("yetkili", "temsilci", "canlı", "canli", "insanla",
                     "danış", "danis", "müşteri hizmet", "musteri hizmet")


def _acik_mi() -> bool:
    """Mesai: Pazartesi–Cumartesi 10:00–19:00, Pazar kapalı (Europe/Istanbul)."""
    now = timezone.localtime()          # settings.TIME_ZONE = Europe/Istanbul
    return now.weekday() != 6 and 10 <= now.hour < 19


def yetkili_metni() -> str:
    durum = ("Şu an açığız, size hemen yardımcı olalım. 🙂" if _acik_mi()
             else "Şu an kapalıyız; mesai saatlerinde size hemen dönüş yapılır.")
    return (
        "Sizi yetkilimize bağlayalım 👇\n"
        f"📱 wa.me/{YETKILI_WA}  ({YETKILI_TEL_GORUNEN})\n\n"
        "🕙 Pazartesi–Cumartesi 10:00–19:00 (Pazar kapalı)\n"
        f"{durum}"
    )


def _int(s: str | None) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _yetkili_mi(tur: str, tetik: str) -> bool:
    if tur == YETKILI_PAYLOAD:
        return True
    low = tetik.lower()
    return any(k in low for k in YETKILI_KELIMELER)


def yanit_uret(tetik: str, veri=_default_veri, P=_default_P) -> dict:
    """Tetik token'ından (START / KAT:.. / KOL:.. / KOM:.. / YETKILI) mesaj üret."""
    tur, deger = parse_secim(tetik)

    if _yetkili_mi(tur, tetik):
        return P.metin_mesaji(yetkili_metni())

    _id = _int(deger)
    if tur == "KAT" and _id is not None:
        return P.koleksiyonlar_mesaji(veri.koleksiyonlar(_id))
    if tur == "KOL" and _id is not None:
        return P.kombinasyonlar_mesaji(veri.kombinasyonlar(_id))
    if tur == "KOM" and _id is not None:
        return P.kombinasyon_detay_mesaji(veri.kombinasyon(_id))

    # START veya tanınmayan serbest metin → baştan kategori menüsü.
    return P.kategoriler_mesaji(veri.kategoriler())
