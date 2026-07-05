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


# ── "Beni arayın" (geri arama talebi) ────────────────────────────────────────
# Müşteri seçince numarası + uygun saati sorulur; cevabı İsmail'in 0532
# WhatsApp'ına bildirim olarak gider (bot/bildirim.py — WA olmadıysa e-posta).
# Akış stateless: "soru soruldu mu?" durumu bot_mesaj geçmişinden okunur
# (son giden mesaj ARA_SORU ise sıradaki serbest metin = cevap).
BENIARA_PAYLOAD = "BENIARA"
BENIARA_KELIMELER = ("beni ara", "geri ara", "arar mısın", "arar misin",
                     "arayın", "arayin", "beni arasın", "beni arasin")
ARA_SORU_ISARET = "📞 Sizi arayalım"     # giden kayıtta bu başlangıç aranır


def ara_soru_metni() -> str:
    return (f"{ARA_SORU_ISARET}!\n"
            "Lütfen telefon numaranızı ve size uygun saati yazın.\n"
            "Örn: 0555 111 22 33 — öğleden sonra")


def ara_tesekkur_metni() -> str:
    return ("✅ Talebiniz alındı, en kısa sürede sizi arayacağız. 🙏\n"
            "⬅️ Menüye dönmek için bir mesaj yazmanız yeterli.")


def _beniara_mi(tur: str, tetik: str) -> bool:
    if tur == BENIARA_PAYLOAD:
        return True
    low = (tetik or "").lower()
    return any(k in low for k in BENIARA_KELIMELER)


def _ara_bekleniyor_mu(platform: str, kullanici: str) -> bool:
    """Bota gönderilen SON mesaj 'Beni arayın' sorusu mu?

    Öyleyse müşterinin şimdiki serbest metni numara+saat cevabıdır.
    Müşteri soru yerine bir butona basarsa akış normal menüden sürer ve
    bir sonraki giden mesaj soruyu ezer → bekleme kendiliğinden düşer.
    """
    if not (platform and kullanici):
        return False
    try:
        from catalog.database import SessionLocal   # geç import: testte DB yok
        from catalog.sa_models import BotMesaj
        from sqlalchemy import select
        session = SessionLocal()
        try:
            son = session.scalar(
                select(BotMesaj)
                .where(BotMesaj.platform == platform,
                       BotMesaj.kullanici == kullanici,
                       BotMesaj.yon == "giden")
                .order_by(BotMesaj.id.desc())
                .limit(1)
            )
        finally:
            session.close()
    except Exception:
        return False
    return son is not None and (son.metin or "").startswith(ARA_SORU_ISARET)


def _ara_talebi_isle(platform: str, kullanici: str, metin: str) -> None:
    """Cevabı yetkiliye ilet (bildirim hatası müşteri akışını bozmaz)."""
    try:
        from bot import bildirim   # geç import: testte Django/DB gerekmesin
        bildirim.geri_arama_bildir(platform, kullanici, metin)
    except Exception:
        pass


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


def _mevcut_kategori_id(platform: str, kullanici: str) -> int | None:
    """Müşterinin ŞU AN gezindiği kategori id'sini konuşma geçmişinden çıkar.

    Menü stateless: durum buton payload'ında taşınır ama serbest metin bunu
    bilmez. Müşteri "TV Üniteleri" kategorisine girip (KAT:1702) sonra "vermont"
    yazınca, aramayı o kategoriye daraltabilmek için son basılan KAT butonunu
    geçmişten okuruz. Arada "Ana Menü" (START) varsa bağlam sıfırlanmış sayılır.
    """
    if not (platform and kullanici):
        return None
    try:
        from catalog.database import SessionLocal   # geç import: testte DB yok
        from catalog.sa_models import BotMesaj
        from sqlalchemy import select
        session = SessionLocal()
        try:
            rows = session.scalars(
                select(BotMesaj)
                .where(BotMesaj.platform == platform,
                       BotMesaj.kullanici == kullanici,
                       BotMesaj.yon == "gelen")
                .order_by(BotMesaj.id.desc())
                .limit(8)
            ).all()
        finally:
            session.close()
    except Exception:
        return None
    for r in rows:
        m = (r.metin or "").strip()
        if m.startswith("[buton] KAT:"):
            kid, _, _ = m[len("[buton] KAT:"):].partition(":")
            return _int(kid)
        if m.startswith("[buton] START"):
            return None   # ana menüye dönmüş → kategori bağlamı yok
    return None


def _koleksiyon_bul(tetik: str, veri, kategori_id: int | None = None) -> list[dict]:
    """Yazılan metne uyan koleksiyonları (ürün gruplarını) bul — HEPSİNİ döndürür.

    Aynı ad birden fazla kategoride olabilir (ör. VERMONT; Yemek/Yatak/Oturma/Tv).
    İlkini körlemesine seçmek yanlış kategoriye götürür. Birden fazla eşleşmede
    öncelik sırası:
      1. Metinde kategori kelimesi açıkça geçiyorsa ona daralt ("vermont yatak").
      2. Müşteri şu an bir kategori içindeyse (kategori_id) ORAYA daralt
         ("Tv Üniteleri"ndeyken "vermont" → sadece Tv Üniteleri VERMONT'u).
      3. Hâlâ birden fazlaysa → çağıran kategorili seçim menüsü gösterir.
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
        # 1) Metinde açıkça kategori kelimesi (en güçlü sinyal) → ona daralt.
        d = _duzle(metin)
        daralt = [k for k in sonuc
                  if any(p in d for p in _duzle(k.get("kategori", "")).split()
                         if len(p) >= 4)]
        if daralt:
            return daralt
        # 2) Aksi halde müşteri bir kategori içindeyse o kategoriye daralt.
        if kategori_id is not None:
            iceride = [k for k in sonuc if k.get("kategori_id") == kategori_id]
            if iceride:
                return iceride
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

    # "📞 Beni arayın" BUTONU → numara + uygun saat sorulur. (Yazıyla tetikleme
    # serbest metin bölümünde, bekleme kontrolünden SONRA — cevaptaki "arayın"
    # kelimesi soruyu yeniden tetiklemesin.)
    if tur == BENIARA_PAYLOAD:
        return P.metin_mesaji(ara_soru_metni())

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
    # 0) "Beni arayın" sorusuna cevap bekleniyorsa bu metin numara+saat'tir:
    #    yetkiliye bildir, müşteriye teşekkür et. (Selam/AI kontrollerinden ÖNCE —
    #    cevap "fiyat" gibi kelimeler içerse bile AI'ya kaçmasın.)
    if platform and kullanici and _ara_bekleniyor_mu(platform, kullanici):
        _ara_talebi_isle(platform, kullanici, tetik)
        return P.metin_mesaji(ara_tesekkur_metni())

    # 0b) Yazıyla geri arama isteği ("beni arayın", "geri ara"…) → soruyu sor.
    if _beniara_mi(tur, tetik):
        return P.metin_mesaji(ara_soru_metni())

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
    #    aynı ad birden fazla kategorideyse önce mevcut kategoriye daralt,
    #    hâlâ birden fazlaysa kategorili seçim menüsü göster.
    kat_baglam = _mevcut_kategori_id(platform, kullanici)
    kols = _koleksiyon_bul(tetik, veri, kategori_id=kat_baglam)
    if len(kols) == 1:
        return P.kombinasyonlar_mesaji(veri.kombinasyonlar(kols[0]["id"]))
    if len(kols) > 1:
        return P.koleksiyon_secim_mesaji(kols)

    # 5) Varsayılan → kategori menüsü
    return P.kategoriler_mesaji(veri.kategoriler())
