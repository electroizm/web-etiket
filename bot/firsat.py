"""Fırsat defteri — sıcak müşteri radarı (Faz 5).

Son 24 saatin konuşmalarından satın almaya yakın ("sıcak") müşterileri çıkarır
ve sabah özetine "🔥 Sıcak müşteriler" bölümü olarak girer. Tamamen kural
tabanlıdır — LLM kullanmaz, Gemini kotası dolu olsa da çalışır.

Sinyaller ve puanlar (eşik: 3):
- pazarlık dili (gelen)      +3   almaya en yakın müşteri pazarlık edendir
- "yetkili" istedi (gelen)   +2
- teşhirle ilgilendi         +2
- ajan fiyat verdi (giden)   +1
- 3+ gelen mesaj             +1
"""
from __future__ import annotations

import logging
import re
from zoneinfo import ZoneInfo

log = logging.getLogger("bot.firsat")

_TR = ZoneInfo("Europe/Istanbul")

# Gelen mesajda pazarlık niyeti sayılan kalıplar (küçük harfle aranır).
PAZARLIK_KALIPLARI = ("pazarlık", "pazarlik", "indirim", "son fiyat",
                      "bırak", "birak", "olmaz mı", "olmaz mi",
                      "ne kadar olur", "kaça olur", "kaca olur", "en son ne")

_FIYAT_KALIBI = re.compile(r"\d[\d.,]*\s*TL", re.IGNORECASE)


def _urun_adlari() -> list[str]:
    """Bilinen seri adları: koleksiyonlar + teşhirdeki manuel adlar (DB'den).

    Ajanın cevaplarında geçen ürünü yakalamak için kullanılır. DB hatasında
    boş liste döner — radar ürünsüz de çalışır.
    """
    try:
        from sqlalchemy import select

        from catalog.database import SessionLocal
        from catalog.sa_models import Koleksiyon, Teshir
        session = SessionLocal()
        try:
            adlar = set(session.scalars(select(Koleksiyon.ad)).all())
            adlar |= {a for a in session.scalars(select(Teshir.koleksiyon_adi)).all() if a}
        finally:
            session.close()
    except Exception:
        log.exception("firsat: ürün adları okunamadı")
        return []
    # Çok kısa adlar (SET vb.) düz kelimelere takılır — 4+ harf şartı.
    return sorted((a.strip() for a in adlar if len(a.strip()) >= 4), key=len, reverse=True)


def _telefon(platform: str, kullanici: str) -> str | None:
    """WA kullanıcı kimliğini okunur telefona çevir: 905321339826 → 0532 133 98 26."""
    if platform != "whatsapp" or not kullanici.isdigit():
        return None
    n = kullanici
    if n.startswith("90") and len(n) == 12:
        n = "0" + n[2:]
    if len(n) == 11:
        return f"{n[:4]} {n[4:7]} {n[7:9]} {n[9:]}"
    return n


def sicak_musteriler(konusmalar: dict, adlar: dict) -> list[dict]:
    """Konuşma sözlüğünden sıcak müşteri listesi (puana göre sıralı).

    konusmalar: {(platform, kullanici): [BotMesaj, ...]} — bot_ozet ile aynı yapı.
    adlar: {(platform, kullanici): ad} — bot_kisi'den.
    """
    urunler = _urun_adlari()
    firsatlar = []
    for (platform, kullanici), mesajlar in konusmalar.items():
        gelenler, tum_metin = [], []
        fiyat_verildi = False
        for m in mesajlar:
            metin = (m.metin or "").strip()
            if not metin or metin.startswith("[buton]") or "[menü]" in metin \
                    or metin.startswith("[kart") or metin.startswith("[sohbeti"):
                continue
            tum_metin.append(metin)
            if m.yon == "gelen":
                gelenler.append(metin.lower())
            elif _FIYAT_KALIBI.search(metin):
                fiyat_verildi = True

        gelen_birlesik = " ".join(gelenler)
        hepsi_kucuk = " ".join(tum_metin).lower()

        puan, sinyaller = 0, []
        if any(k in gelen_birlesik for k in PAZARLIK_KALIPLARI):
            puan += 3
            sinyaller.append("pazarlık etti")
        if "yetkili" in gelen_birlesik:
            puan += 2
            sinyaller.append("yetkili istedi")
        if "teşhir" in hepsi_kucuk or "teshir" in hepsi_kucuk:
            puan += 2
            sinyaller.append("teşhirle ilgilendi")
        if fiyat_verildi:
            puan += 1
            sinyaller.append("fiyat aldı")
        if len(gelenler) >= 3:
            puan += 1

        if puan < 3:
            continue

        bulunan = []
        for u in urunler:
            if re.search(rf"\b{re.escape(u.lower())}\b", hepsi_kucuk):
                bulunan.append(u.upper())
            if len(bulunan) == 3:
                break

        son = mesajlar[-1].olusturma
        try:
            son_saat = son.astimezone(_TR).strftime("%H:%M")
        except Exception:
            son_saat = son.strftime("%H:%M") if son else "?"

        firsatlar.append({
            "platform": platform,
            "kullanici": kullanici,
            "ad": adlar.get((platform, kullanici)),
            "telefon": _telefon(platform, kullanici),
            "urunler": bulunan,
            "sinyaller": sinyaller,
            "gelen_sayisi": len(gelenler),
            "son_saat": son_saat,
            "puan": puan,
        })
    return sorted(firsatlar, key=lambda f: -f["puan"])


def ozet_satirlari(firsatlar: list[dict]) -> list[str]:
    """Sabah özeti e-postası için satırlar üret."""
    satirlar = []
    for f in firsatlar[:10]:
        kim = f["ad"] or f["telefon"] or f["kullanici"]
        if f["ad"] and f["telefon"]:
            kim = f"{f['ad']} {f['telefon']}"
        platform = "WhatsApp" if f["platform"] == "whatsapp" else "Instagram"
        urun = "/".join(f["urunler"]) if f["urunler"] else "ürün net değil"
        satirlar.append(f"- {kim} ({platform}): {urun} — {', '.join(f['sinyaller'])}"
                        f" · {f['gelen_sayisi']} mesaj, son {f['son_saat']}")
    return satirlar
