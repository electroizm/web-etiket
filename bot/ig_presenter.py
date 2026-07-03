"""Menü verisini Instagram (Messenger Platform) mesaj payload'larına çevirir.

Sınırlar:
- Quick reply başlığı ~20 karakter → kırpılır.
- Quick reply en çok 13 adet; generic template en çok 10 kart.
Bu yüzden uzun adlarda quick reply yerine carousel/numaralı liste tercih edilir.
"""
from __future__ import annotations

QR_BASLIK_LIMIT = 20
QR_MAX = 13
KART_MAX = 10


def _kirp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _tl(n) -> str:
    return f"{n:,.0f} TL".replace(",", ".") if n is not None else "—"


def quick_replies(metin: str, secenekler: list[tuple[str, str]]) -> dict:
    """secenekler: [(baslik, payload), ...] → quick reply mesajı."""
    qrs = [
        {"content_type": "text",
         "title": _kirp(baslik, QR_BASLIK_LIMIT),
         "payload": payload}
        for baslik, payload in secenekler[:QR_MAX]
    ]
    return {"text": metin, "quick_replies": qrs}


def kategoriler_mesaji(kategoriler: list[dict]) -> dict:
    if not kategoriler:
        return {"text": "Şu an gösterilecek kategori yok."}
    sec = [(k["ad"], f"KAT:{k['id']}") for k in kategoriler]
    return quick_replies("Hangi kategoriye bakmak istersin?", sec)


def koleksiyonlar_mesaji(veri: dict) -> dict:
    kols = (veri or {}).get("koleksiyonlar", [])
    kat = (veri or {}).get("kategori", {}).get("ad", "")
    if not kols:
        return {"text": "Bu kategoride uygun ürün grubu yok."}
    sec = [(k["ad"], f"KOL:{k['id']}") for k in kols]
    return quick_replies(f"{kat} → bir ürün grubu seç:", sec)


def kombinasyonlar_mesaji(veri: dict) -> dict:
    """Carousel (generic template) — her kart: ad + fiyat + 'Detay' butonu."""
    kombis = (veri or {}).get("kombinasyonlar", [])
    if not kombis:
        return {"text": "Bu grupta hazır kombinasyon yok."}
    kartlar = []
    for k in kombis[:KART_MAX]:
        eski, yeni, ind = k.get("toplam_liste"), k.get("toplam_perakende"), k.get("indirim_yuzde")
        if ind:
            alt = f"{_tl(yeni)}  (eski {_tl(eski)} · −%{ind})"
        else:
            alt = _tl(yeni)
        kartlar.append({
            "title": _kirp(k["ad"], 80),
            "subtitle": f"{k.get('urun_sayisi', 0)} ürün · {k.get('toplam_adet', 0)} adet\n{alt}",
            "buttons": [{"type": "postback", "title": "Fiyat detayı",
                         "payload": f"KOM:{k['id']}"}],
        })
    return {
        "attachment": {
            "type": "template",
            "payload": {"template_type": "generic", "elements": kartlar},
        }
    }


def kombinasyon_detay_mesaji(veri: dict) -> dict:
    if not veri:
        return {"text": "Kombinasyon bulunamadı."}
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
    return {"text": "\n".join(satirlar)}
