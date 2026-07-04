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


# ── AI yönlendirme (Faz 5, menü-öncelikli mod) ───────────────────────────────
# Menü varsayılan yoldur (bedava, güvenilir, günlük 1500 Gemini kotasını harcamaz).
# AI YALNIZCA aşağıdaki net ürün/fiyat sorusu sinyallerinde devreye girer; selam
# ve belirsiz mesajlar doğrudan kategori menüsüne düşer.
AI_SINYAL_KELIMELER = (
    # fiyat niyeti
    "fiyat", "ne kadar", "kaç para", "kaça", "kaç lira", "kaç tl", "ücret",
    "tutar", "indirim", "kampanya", "taksit", "kaç bin", "peşin",
    # arama / soru niyeti
    "var mı", "varmı", "nedir", "hangi", "nasıl", "arıyorum", "ariyorum",
    "istiyorum", "bakıyorum", "bakiyorum", "lazım", "lazim", "önerir", "onerir",
    "modeli", "ölçü", "olcu", "renk",
)


def _ai_gerekli_mi(tetik: str) -> bool:
    """Serbest metin AI'ya mı gitsin (net ürün/fiyat sorusu), yoksa menüye mi?

    Muhafazakâr: emin değilsek MENÜ (bedava + güvenilir). Böylece selam/kısa
    mesajlar kotayı harcamaz, sadece gerçek sorular AI'ya gider.
    """
    metin = (tetik or "").strip()
    low = " " + metin.lower() + " "
    if any(s in low for s in AI_SINYAL_KELIMELER):
        return True
    # Net soru işareti + yeterli içerik (tek "?" değil)
    if "?" in metin and len(metin) >= 6:
        return True
    return False


# ── Hibrit karşılama + yazarak menü navigasyonu ──────────────────────────────
SELAM_KELIMELER = (
    "merhaba", "meraba", "selam", "slm", "mrb", "mrhb", "sa", "selamun",
    "selamünaleyküm", "selamunaleykum", "iyi günler", "iyi gunler", "günaydın",
    "gunaydin", "iyi akşamlar", "iyi aksamlar", "iyi geceler", "hey", "alo",
    "hoş buldum", "hos buldum", "kolay gelsin",
)


def _selam_mi(tetik: str) -> bool:
    """Kısa ve selamlama içeren mesaj mı? (uzun/içerikli mesaj selam sayılmaz)"""
    metin = (tetik or "").strip().lower()
    if not metin or len(metin) > 28:
        return False
    if metin in SELAM_KELIMELER:
        return True
    kelimeler = metin.split()
    return any(k in SELAM_KELIMELER for k in kelimeler) or \
        any(metin.startswith(s) for s in SELAM_KELIMELER)


def selam_metni() -> str:
    """Sıcak karşılama (sabit şablon — bedava, kota harcamaz)."""
    return ("Merhaba, hoş geldiniz! 😊 Size nasıl yardımcı olabilirim?\n"
            "Aşağıdaki menüden ilerleyebilir ya da aradığınız ürünü/fiyatı "
            "doğrudan yazabilirsiniz.")


# Türkçe karakterleri sadeleştir: müşteri "yatak odasi" yazsa da "Yatak Odası" eşleşsin.
_TR_DUZLE = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def _duzle(s: str) -> str:
    # Önce çevir (İ→i büyükken yakalansın), sonra küçült, kalan Türkçe harfleri çevir;
    # Python'un "İ".lower() çıktısındaki birleşik noktayı (U+0307) da at.
    s = (s or "").strip().translate(_TR_DUZLE).lower().translate(_TR_DUZLE)
    return s.replace("̇", "")


def _kategori_bul(tetik: str, veri) -> dict | None:
    """Yazılan metin bir kategori adına uyuyor mu? (yazarak menü navigasyonu)"""
    metin = _duzle(tetik)
    if len(metin) < 3:
        return None
    for k in veri.kategoriler():
        ad = _duzle(k.get("ad"))
        if ad and (ad in metin or metin in ad):
            return k
    return None


def _koleksiyon_bul(tetik: str, veri) -> list[dict]:
    """Yazılan metne uyan koleksiyonları (ürün gruplarını) bul — HEPSİNİ döndürür.

    Aynı ad birden fazla kategoride olabilir (ör. VERMONT hem Yemek Odası hem
    Yatak Odası); ilkini körlemesine seçmek yanlış kategoriye götürür. Birden
    fazla eşleşmede metinde geçen kategori kelimesiyle daraltılır ("vermont
    yatak" → Yatak Odası); daralmıyorsa çağıran seçim menüsü gösterir.
    """
    metin = (tetik or "").strip()
    if len(metin) < 3:
        return []
    try:
        sonuc = veri.koleksiyon_ara(metin)
        if not sonuc:
            # "vermont yatak" gibi ad+kategori yazımı tam aramada boş döner:
            # ilk kelimeyle ara, kategori daraltması aşağıda devreye girer.
            kelimeler = metin.split()
            if len(kelimeler) > 1 and len(kelimeler[0]) >= 3:
                sonuc = veri.koleksiyon_ara(kelimeler[0])
    except Exception:
        return []
    if len(sonuc) > 1:
        d = _duzle(metin)
        daralt = [k for k in sonuc
                  if any(p in d for p in _duzle(k.get("kategori", "")).split()
                         if len(p) >= 4)]
        if daralt:
            return daralt
    return sonuc


def yanit_uret(tetik: str, veri=_default_veri, P=_default_P,
               platform: str = "", kullanici: str = "") -> dict:
    """Tetik token'ından (START / KAT:.. / KOL:.. / KOM:.. / YETKILI) mesaj üret.

    Payload'lar sayfa taşıyabilir: 'KAT:48:2' = 48 no'lu kategorinin 2. sayfası,
    'START:2' = kategori menüsünün 2. sayfası (bkz. presenter sayfalama).

    Faz 5 hibrit akış: buton payload'ları menü mantığında kalır. Serbest metin için:
      1. Selam → sıcak karşılama metni + kategori menüsü (ikisi de bedava, şablon).
      2. Net ürün/fiyat sorusu (fiyat, ne kadar, "?"…) → AI (_ai_gerekli_mi).
      3. Yazılan kategori adı → o kategorinin ürün grupları (yazarak menü navigasyonu).
      4. Yazılan koleksiyon/ürün adı → o grubun kombinasyonları.
      5. Aksi halde → kategori menüsü.
    Menü ve yazarak ilerleme her adımda birlikte çalışır; AI kapalı/kota dolu ise
    de akış menüyle sürer (müşteri asla cevapsız kalmaz).
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

    # ── Serbest metin: hibrit karşılama + yazarak navigasyon ──
    # 1) Sadece selam (fiyat/soru sinyali yoksa) → sıcak karşılama + menü (iki mesaj)
    if _selam_mi(tetik) and not _ai_gerekli_mi(tetik):
        return [P.metin_mesaji(selam_metni()),
                P.kategoriler_mesaji(veri.kategoriler())]

    # 2) Net ürün/fiyat sorusu → AI (başarısızsa aşağı, menüye düşer)
    if platform and kullanici and _ai_gerekli_mi(tetik):
        from bot import ajan  # geç import: testlerde/ajan kapalıyken yük yok
        cevap = ajan.cevapla(tetik, platform, kullanici)
        if cevap:
            return P.metin_mesaji(cevap)

    # 3) Yazarak menü navigasyonu (bedava): kategori adı → ürün grupları
    kat = _kategori_bul(tetik, veri)
    if kat is not None:
        return P.koleksiyonlar_mesaji(veri.koleksiyonlar(kat["id"]))
    # 4) koleksiyon/ürün adı → kombinasyonlar (tek eşleşmede);
    #    aynı ad birden fazla kategorideyse kategorili seçim menüsü
    kols = _koleksiyon_bul(tetik, veri)
    if len(kols) == 1:
        return P.kombinasyonlar_mesaji(veri.kombinasyonlar(kols[0]["id"]))
    if len(kols) > 1:
        return P.koleksiyon_secim_mesaji(kols)

    # 5) Varsayılan → kategori menüsü
    return P.kategoriler_mesaji(veri.kategoriler())
