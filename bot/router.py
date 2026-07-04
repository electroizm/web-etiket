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

from catalog.services import menu_veri as _default_veri
from bot import ig_presenter as _default_P
from bot.webhook_core import parse_secim

# ── Yetkiliye yönlendirme ────────────────────────────────────────────────────
YETKILI_WA = "905321370627"            # wa.me linki (0532 137 06 27)
YETKILI_URL = f"https://wa.me/{YETKILI_WA}"   # https şart: IG/WA ancak böyle tıklanabilir yapar
# Butonlar tel: linki kabul etmez (yalnız https) → /ara sayfası telefonun
# arama ekranını tetikler (bot/views.ara).
YETKILI_ARA_URL = "https://etiket.gunesler.info/ara"
YETKILI_TEL_GORUNEN = "0532 137 06 27"
YETKILI_PAYLOAD = "YETKILI"
# Serbest metinde yetkili talebi sayılan kelimeler (küçük harfte aranır).
YETKILI_KELIMELER = ("yetkili", "temsilci", "canlı", "canli", "insanla",
                     "danış", "danis", "müşteri hizmet", "musteri hizmet")


def yetkili_metni() -> str:
    """Tek satır — İsmail'in isteği: uzun açıklama olmasın, butona basıp geçilsin."""
    return f"👤 Yetkilimiz: {YETKILI_TEL_GORUNEN} 👇"


def _int(s: str | None) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _id_sayfa(deger: str | None) -> tuple[int | None, int]:
    """Payload değerinden (id, sayfa) çöz: '48' → (48,1); '48:2' → (48,2)."""
    if not deger:
        return None, 1
    parca, _, sayfa_s = deger.partition(":")
    return _int(parca), (_int(sayfa_s) or 1)


def _yetkili_mi(tur: str, tetik: str) -> bool:
    if tur == YETKILI_PAYLOAD:
        return True
    low = tetik.lower()
    return any(k in low for k in YETKILI_KELIMELER)


def yanit_uret(tetik: str, veri=_default_veri, P=_default_P,
               platform: str = "", kullanici: str = "") -> dict:
    """Tetik token'ından (START / KAT:.. / KOL:.. / KOM:.. / YETKILI) mesaj üret.

    Payload'lar sayfa taşıyabilir: 'KAT:48:2' = 48 no'lu kategorinin 2. sayfası,
    'START:2' = kategori menüsünün 2. sayfası (bkz. presenter sayfalama).

    Faz 5 hibrit akış: buton payload'ları menü mantığında kalır; TANINMAYAN
    serbest metin AI ajana gider (bot/ajan.py). Ajan kapalıysa ya da hata
    verirse eski davranış korunur: kategori menüsü gösterilir.
    """
    tur, deger = parse_secim(tetik)

    if _yetkili_mi(tur, tetik):
        return P.yetkili_mesaji(yetkili_metni(), YETKILI_URL, YETKILI_ARA_URL)

    _id, sayfa = _id_sayfa(deger)
    if tur == "KAT" and _id is not None:
        return P.koleksiyonlar_mesaji(veri.koleksiyonlar(_id), sayfa=sayfa)
    if tur == "KOL" and _id is not None:
        return P.kombinasyonlar_mesaji(veri.kombinasyonlar(_id), sayfa=sayfa)
    if tur == "KOM" and _id is not None:
        return P.kombinasyon_detay_mesaji(veri.kombinasyon(_id))
    if tur == "START":
        return P.kategoriler_mesaji(veri.kategoriler(), sayfa=_int(deger) or 1)

    # ── Tanınmayan serbest metin → AI ajan (Faz 5) ──
    if platform and kullanici:
        from bot import ajan  # geç import: testlerde/ajan kapalıyken yük yok
        cevap = ajan.cevapla(tetik, platform, kullanici)
        if cevap:
            return P.metin_mesaji(cevap)

    # Ajan kapalı/başarısız → eski davranış: kategori menüsü.
    return P.kategoriler_mesaji(veri.kategoriler())
