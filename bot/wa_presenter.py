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
    """Düz metin mesajı (router'ın hazır metinleri için)."""
    return _metin(govde)


def _cta(metin: str, buton: str, url: str) -> dict:
    """Tek URL butonlu mesaj (cta_url). WhatsApp cta_url'de yalnız 1 buton olabilir."""
    return {
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "body": {"text": metin},
            "action": {
                "name": "cta_url",
                "parameters": {"display_text": buton, "url": url},
            },
        },
    }


def yetkili_mesaji(metin: str, url: str, ara_url: str) -> list[dict]:
    """Yetkiliye yönlendirme: iki art arda buton mesajı (cta_url tek buton taşır) —
    WhatsApp'ta yaz (0532 sohbeti) + Sesli arama (arama ekranını açan /ara sayfası)."""
    return [
        _cta(metin, "📱 WhatsApp'ta yaz", url),
        _cta("📞 Aramak için 👇", "📞 Sesli arama yap", ara_url),
    ]


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
        baslik = (baslik or "").strip()
        # Başlık 24 karakterde kırpılır (platform sınırı); kırpılıyorsa ve
        # açıklama boşsa tam ad açıklamada gösterilsin — hiçbir ad kaybolmasın.
        if not aciklama and len(baslik) > SATIR_BASLIK:
            aciklama = baslik
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
    """≤3 seçenek → buton, fazlası → liste. secenekler: (baslik, id, aciklama).

    Buton başlığı 20 karakterde kırpılır ve açıklama alanı yoktur; ad sığmıyorsa
    liste tipine geç (24 + 72 karakterlik açıklamayla tam ad gösterilebiliyor).
    """
    if (len(secenekler) <= BUTON_MAX
            and all(not a for *_, a in secenekler)
            and all(len((b or "").strip()) <= BUTON_BASLIK for b, *_ in secenekler)):
        return _butonlar(metin, [(b, i) for b, i, _ in secenekler])
    return _liste(metin, secenekler)


# ─── Sayfalama ────────────────────────────────────────────────────────────────
# WhatsApp list en çok 10 satır. 10'u aşan menüler sayfalanır: her sayfada
# (10 − 1 devam − sabit sayısı) seçenek + "➡️ Devamını gör" + sabit satır(lar).
# Sayfa numarası payload'da taşınır (KAT:48:2) — köprü stateless kalır.
ANA_MENU = ("⬅️ Ana Menü", "START", "")
BENI_ARA = ("📞 Beni arayın", "BENIARA", "")


def _sayfali_liste(metin: str, secenekler: list[tuple[str, str, str]],
                   sayfa: int, devam_prefix: str,
                   sabit: list[tuple[str, str, str]]) -> dict:
    """Uzun listeyi sayfala. devam_prefix: 'KAT:48' → devam payload'ı 'KAT:48:2'."""
    satir_basi = LISTE_MAX - 1 - len(sabit)   # sabitler + Devamı hep sığsın
    toplam = len(secenekler)
    bas = max(0, (sayfa - 1)) * satir_basi
    dilim = secenekler[bas:bas + satir_basi]
    rows = list(dilim)
    kalan = toplam - (bas + len(dilim))
    if kalan > 0:
        rows.append(("➡️ Devamını gör", f"{devam_prefix}:{sayfa + 1}",
                     f"{kalan} seçenek daha"))
    rows.extend(sabit)
    return _liste(metin, rows)


def kategoriler_mesaji(kategoriler: list[dict], sayfa: int = 1) -> dict:
    if not kategoriler:
        return _metin("Şu an gösterilecek kategori yok.")
    sec = [(k["ad"], f"KAT:{k['id']}", "") for k in kategoriler]
    sabit = [("👤 Yetkiliyle görüş", "YETKILI", ""), BENI_ARA]
    metin = "Hangi kategoriye bakmak istersin?"
    if sayfa == 1 and len(sec) + len(sabit) <= LISTE_MAX:
        return _secim_mesaji(metin, sec + sabit)
    return _sayfali_liste(metin, sec, sayfa, "START", sabit)


def koleksiyonlar_mesaji(veri: dict, sayfa: int = 1) -> dict:
    kols = (veri or {}).get("koleksiyonlar", [])
    kat_bilgi = (veri or {}).get("kategori", {})
    kat, kat_id = kat_bilgi.get("ad", ""), kat_bilgi.get("id")
    if not kols:
        return _metin("Bu kategoride uygun ürün grubu yok.")
    sec = [(k["ad"], f"KOL:{k['id']}", "") for k in kols]
    metin = f"{kat} → bir ürün grubu seç:"
    if sayfa == 1 and len(sec) + 1 <= LISTE_MAX:
        return _secim_mesaji(metin, sec + [ANA_MENU])
    return _sayfali_liste(metin, sec, sayfa, f"KAT:{kat_id}", [ANA_MENU])


def koleksiyon_secim_mesaji(eslesmeler: list[dict]) -> dict:
    """Aynı ad birden fazla kategoride bulunduğunda (ör. VERMONT hem Yemek hem
    Yatak Odası) kategorisiyle listeleyip müşteriye seçtirir. Satır: ad + kategori."""
    sec = [(k["ad"], f"KOL:{k['id']}", k.get("kategori") or "") for k in eslesmeler]
    metin = "Birden fazla grupta bulundu — hangisine bakalım?"
    return _liste(metin, sec[:LISTE_MAX - 1] + [ANA_MENU])


def kombinasyonlar_mesaji(veri: dict, sayfa: int = 1) -> dict:
    """Her satır: kombinasyon adı (başlık) + fiyat/indirim (açıklama), id=KOM:.."""
    kombis = (veri or {}).get("kombinasyonlar", [])
    kol_id = ((veri or {}).get("koleksiyon") or {}).get("id")
    if not kombis:
        return _metin("Bu grupta hazır kombinasyon yok.")
    sec = []
    for k in kombis:
        eski, yeni, ind = k.get("toplam_liste"), k.get("toplam_perakende"), k.get("indirim_yuzde")
        if ind:
            ack = f"{_tl(yeni)} (eski {_tl(eski)} · −%{ind})"
        else:
            ack = _tl(yeni)
        ad = (k["ad"] or "").strip()
        if len(ad) > SATIR_BASLIK:   # başlık kırpılacak → tam ad açıklamanın başına
            ack = f"{ad} · {ack}"
        sec.append((ad, f"KOM:{k['id']}", ack))
    metin = "Hazır kombinasyonlar — birini seç:"
    if sayfa == 1 and len(sec) + 1 <= LISTE_MAX:
        return _liste(metin, sec + [ANA_MENU])
    return _sayfali_liste(metin, sec, sayfa, f"KOL:{kol_id}", [ANA_MENU])


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
    satirlar.append("")
    satirlar.append("⬅️ Menüye dönmek için bir mesaj yazman yeterli.")
    return _metin("\n".join(satirlar))
