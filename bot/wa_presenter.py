"""Menü verisini WhatsApp Cloud API mesaj payload'larına çevirir.

ig_presenter ile **aynı fonksiyon adlarını** sunar; böylece router platformdan
bağımsız kalır (yanit_uret'e hangi presenter verilirse onu üretir).

WhatsApp'ın Messenger'dan farkı (sınırlar Meta dokümanından):
- "quick_replies"/"generic carousel" YOK. Yerine iki interaktif tip var:
  * button : en çok 3 yanıt butonu (kısa menüler).
  * list   : tek butonla açılan, en çok 10 satırlık liste (uzun menüler).
- Buton başlığı ≤20, liste satır başlığı ≤24, satır açıklaması ≤72 karakter.
Bu modül dönüşü "to/messaging_product" içermez — onu meta_client ekler.
"""
from __future__ import annotations

BUTON_BASLIK = 20
BUTON_MAX = 3
SATIR_BASLIK = 24
SATIR_ACIKLAMA = 72
LISTE_MAX = 10
LISTE_BUTON = "Seçenekler"


def _kirp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _tl(n) -> str:
    return f"{n:,.0f} TL".replace(",", ".") if n is not None else "—"


def _metin(govde: str) -> dict:
    return {"type": "text", "text": {"body": govde}}


def metin_mesaji(govde: str) -> dict:
    """Düz metin mesajı (router'ın yetkili yönlendirmesi gibi hazır metinler için)."""
    return _metin(govde)


def _butonlar(metin: str, secenekler: list[tuple[str, str]]) -> dict:
    """secenekler: [(baslik, id), ...] — en çok 3 → button tipi."""
    butonlar = [
        {"type": "reply", "reply": {"id": _id, "title": _kirp(baslik, BUTON_BASLIK)}}
        for baslik, _id in secenekler[:BUTON_MAX]
    ]
    return {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": metin},
            "action": {"buttons": butonlar},
        },
    }


def _liste(metin: str, secenekler: list[tuple[str, str, str]]) -> dict:
    """secenekler: [(baslik, id, aciklama), ...] — en çok 10 → list tipi."""
    satirlar = []
    for baslik, _id, aciklama in secenekler[:LISTE_MAX]:
        satir = {"id": _id, "title": _kirp(baslik, SATIR_BASLIK)}
        if aciklama:
            satir["description"] = _kirp(aciklama, SATIR_ACIKLAMA)
        satirlar.append(satir)
    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": metin},
            "action": {
                "button": LISTE_BUTON,
                "sections": [{"rows": satirlar}],
            },
        },
    }


def _secim_mesaji(metin: str, secenekler: list[tuple[str, str, str]]) -> dict:
    """≤3 seçenek → buton, fazlası → liste. secenekler: (baslik, id, aciklama)."""
    if len(secenekler) <= BUTON_MAX and all(not a for *_, a in secenekler):
        return _butonlar(metin, [(b, i) for b, i, _ in secenekler])
    return _liste(metin, secenekler)


def kategoriler_mesaji(kategoriler: list[dict]) -> dict:
    if not kategoriler:
        return _metin("Şu an gösterilecek kategori yok.")
    sec = [(k["ad"], f"KAT:{k['id']}", "") for k in kategoriler]
    # Son satır: yetkiliye yönlendirme. (WhatsApp list en çok 10 satır — kategori
    # sayısı 9'u aşarsa bu seçenek görünmez; şu an ~8 kategori var, sığıyor.)
    sec.append(("👤 Yetkiliyle görüş", "YETKILI", ""))
    return _secim_mesaji("Hangi kategoriye bakmak istersin?", sec)


def koleksiyonlar_mesaji(veri: dict) -> dict:
    kols = (veri or {}).get("koleksiyonlar", [])
    kat = (veri or {}).get("kategori", {}).get("ad", "")
    if not kols:
        return _metin("Bu kategoride uygun ürün grubu yok.")
    sec = [(k["ad"], f"KOL:{k['id']}", "") for k in kols]
    return _secim_mesaji(f"{kat} → bir ürün grubu seç:", sec)


def kombinasyonlar_mesaji(veri: dict) -> dict:
    """Her satır: kombinasyon adı (başlık) + fiyat/indirim (açıklama), id=KOM:.."""
    kombis = (veri or {}).get("kombinasyonlar", [])
    if not kombis:
        return _metin("Bu grupta hazır kombinasyon yok.")
    sec = []
    for k in kombis:
        eski, yeni, ind = k.get("toplam_liste"), k.get("toplam_perakende"), k.get("indirim_yuzde")
        if ind:
            ack = f"{_tl(yeni)} (eski {_tl(eski)} · −%{ind})"
        else:
            ack = _tl(yeni)
        sec.append((k["ad"], f"KOM:{k['id']}", ack))
    return _liste("Hazır kombinasyonlar — birini seç:", sec)


def kombinasyon_detay_mesaji(veri: dict) -> dict:
    if not veri:
        return _metin("Kombinasyon bulunamadı.")
    ind = veri.get("indirim_yuzde")
    satirlar = [f"🛋️ {veri.get('ad', '')}"]
    if veri.get("koleksiyon"):
        satirlar.append(f"({veri['koleksiyon'].get('ad', '')})")
    satirlar.append("")
    for u in veri.get("urunler", []):
        satirlar.append(f"• {u.get('miktar', 1)}× {u.get('urun', '')}")
    satirlar.append("")
    if ind:
        satirlar.append(f"Liste: {_tl(veri.get('toplam_liste'))}")
        satirlar.append(f"Fiyat: {_tl(veri.get('toplam_perakende'))}  (−%{ind})")
    else:
        satirlar.append(f"Fiyat: {_tl(veri.get('toplam_perakende'))}")
    return _metin("\n".join(satirlar))
