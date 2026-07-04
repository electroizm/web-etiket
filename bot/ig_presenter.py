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


def metin_mesaji(govde: str) -> dict:
    """Düz metin mesajı (router'ın hazır metinleri için)."""
    return {"text": govde}


def yetkili_mesaji(metin: str, url: str, ara_url: str) -> dict:
    """Yetkiliye yönlendirme: tek kartta iki web_url butonu —
    WhatsApp'ta yaz (0532 sohbeti) + Sesli arama (arama ekranını açan /ara sayfası)."""
    return {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": "generic",
                "elements": [{
                    "title": "👤 Yetkiliyle görüş",
                    "subtitle": _kirp(metin, 80),
                    "buttons": [
                        {"type": "web_url", "url": url, "title": "📱 WhatsApp'ta yaz"},
                        {"type": "web_url", "url": ara_url, "title": "📞 Sesli arama yap"},
                    ],
                }],
            },
        }
    }


def _tam_adlar_eki(metin: str, secenekler: list[tuple[str, str]]) -> str:
    """Quick reply başlığı 20 karakterde kırpılır (platform sınırı, açıklama alanı yok).
    Kırpılan adların tamamını mesaj gövdesine ekle — hiçbir ad kaybolmasın."""
    uzunlar = [(b or "").strip() for b, _ in secenekler
               if len((b or "").strip()) > QR_BASLIK_LIMIT]
    if not uzunlar:
        return metin
    return metin + "\n\nTam adlar:\n" + "\n".join(f"• {a}" for a in uzunlar)


def quick_replies(metin: str, secenekler: list[tuple[str, str]]) -> dict:
    """secenekler: [(baslik, payload), ...] → quick reply mesajı."""
    qrs = [
        {"content_type": "text",
         "title": _kirp(baslik, QR_BASLIK_LIMIT),
         "payload": payload}
        for baslik, payload in secenekler[:QR_MAX]
    ]
    return {"text": metin, "quick_replies": qrs}


# ─── Sayfalama ────────────────────────────────────────────────────────────────
# Quick reply en çok 13, carousel en çok 10 kart. Aşan menüler sayfalanır;
# sayfa numarası payload'da taşınır (KAT:48:2) — köprü stateless kalır.
SAYFA_QR = QR_MAX - 2      # 11 seçenek + Devamı + sabit (Ana Menü/Yetkili)
SAYFA_KART = KART_MAX - 2  # 8 kart + Devamı kartı + Ana Menü kartı

ANA_MENU_QR = ("⬅️ Ana Menü", "START")


def _sayfali_qr(metin: str, secenekler: list[tuple[str, str]],
                sayfa: int, devam_prefix: str,
                sabit: list[tuple[str, str]]) -> dict:
    toplam = len(secenekler)
    bas = max(0, (sayfa - 1)) * SAYFA_QR
    dilim = list(secenekler[bas:bas + SAYFA_QR])
    kalan = toplam - (bas + len(dilim))
    metin = _tam_adlar_eki(metin, dilim)   # bu sayfada kırpılan adların tam hali gövdeye
    if kalan > 0:
        dilim.append(("➡️ Devamını gör", f"{devam_prefix}:{sayfa + 1}"))
    dilim.extend(sabit)
    return quick_replies(metin, dilim)


def kategoriler_mesaji(kategoriler: list[dict], sayfa: int = 1) -> dict:
    if not kategoriler:
        return {"text": "Şu an gösterilecek kategori yok."}
    sec = [(k["ad"], f"KAT:{k['id']}") for k in kategoriler]
    yetkili = ("👤 Yetkiliyle görüş", "YETKILI")
    metin = "Hangi kategoriye bakmak istersin?"
    if sayfa == 1 and len(sec) + 1 <= QR_MAX:
        return quick_replies(_tam_adlar_eki(metin, sec), sec + [yetkili])
    return _sayfali_qr(metin, sec, sayfa, "START", [yetkili])


def koleksiyonlar_mesaji(veri: dict, sayfa: int = 1) -> dict:
    kols = (veri or {}).get("koleksiyonlar", [])
    kat_bilgi = (veri or {}).get("kategori", {})
    kat, kat_id = kat_bilgi.get("ad", ""), kat_bilgi.get("id")
    if not kols:
        return {"text": "Bu kategoride uygun ürün grubu yok."}
    sec = [(k["ad"], f"KOL:{k['id']}") for k in kols]
    metin = f"{kat} → bir ürün grubu seç:"
    if sayfa == 1 and len(sec) + 1 <= QR_MAX:
        return quick_replies(_tam_adlar_eki(metin, sec), sec + [ANA_MENU_QR])
    return _sayfali_qr(metin, sec, sayfa, f"KAT:{kat_id}", [ANA_MENU_QR])


def kombinasyonlar_mesaji(veri: dict, sayfa: int = 1) -> dict:
    """Carousel (generic template) — her kart: ad + fiyat + 'Detay' butonu.
    10'dan çok kombinasyon → 8 kart + 'Devamını gör' + 'Ana Menü' kartları."""
    kombis = (veri or {}).get("kombinasyonlar", [])
    kol_id = ((veri or {}).get("koleksiyon") or {}).get("id")
    if not kombis:
        return {"text": "Bu grupta hazır kombinasyon yok."}

    toplam = len(kombis)
    sayfali = toplam > KART_MAX
    bas = max(0, (sayfa - 1)) * SAYFA_KART if sayfali else 0
    dilim = kombis[bas:bas + (SAYFA_KART if sayfali else KART_MAX)]

    kartlar = []
    for k in dilim:
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
    if sayfali:
        kalan = toplam - (bas + len(dilim))
        if kalan > 0:
            kartlar.append({
                "title": "➡️ Devamını gör",
                "subtitle": f"{kalan} seçenek daha",
                "buttons": [{"type": "postback", "title": "Devamını gör",
                             "payload": f"KOL:{kol_id}:{sayfa + 1}"}],
            })
        kartlar.append({
            "title": "⬅️ Ana Menü",
            "subtitle": "Kategorilere geri dön",
            "buttons": [{"type": "postback", "title": "Ana Menü",
                         "payload": "START"}],
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
    # Fiyat sonrası çıkmaz sokak olmasın: menüye dönüş + yetkili kısayolu.
    return quick_replies("\n".join(satirlar),
                         [ANA_MENU_QR, ("👤 Yetkiliyle görüş", "YETKILI")])
