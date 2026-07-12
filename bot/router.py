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
from bot.webhook_core import KOMBI_ONAY_SORUSU, parse_secim

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


# ── Kombinasyon onayı → pazarlık daveti ──────────────────────────────────────
# Menü akışının kombinasyon detayı KOMBI_ONAY_SORUSU ile biter (presenter'lar).
# Müşteri kısa olumlu cevap verirse pazarlık daveti gönderilir (şablon —
# bedava, AI kotası harcamaz; İsmail kararı 2026-07-12: menüden seçilen
# kombinasyonda da AI akışındaki gibi fiyat çalışması teklif edilsin).
# Sonraki mesajı AI devralır — davet + kombinasyon detayı bot_mesaj
# geçmişinde olduğundan hangi ürünün pazarlığı olduğunu bilir.
ONAY_KELIMELER = ("evet", "uygun", "olur", "tamam", "olabilir", "isterim",
                  "beğendim", "begendim", "yapalım", "yapalim")


def davet_metni() -> str:
    return "Harika! 👍 Size özel bir fiyat çalışması yapmak isteriz. 😊"


def _onay_cevabi_mi(tetik: str) -> bool:
    """Kısa, olumlu, sinyalsiz cevap mı? ("evet", "uygundur", "olur"...)

    Fiyat/soru sinyali taşıyanlar ("indirim olur mu", "evet fiyatı ne olur")
    onay sayılmaz — onlar AI'ya gitmeli ki soru cevapsız kalmasın."""
    metin = (tetik or "").strip().lower()
    if not metin or len(metin) > 24 or _ai_gerekli_mi(metin) or _selam_mi(metin):
        return False
    return any(k in metin for k in ONAY_KELIMELER)


def _kombi_onay_bekleniyor_mu(platform: str, kullanici: str) -> bool:
    """Bota ait SON giden mesaj kombinasyon onay sorusu mu?

    ('in' ile aranır: IG kaydında metnin sonuna '[menü]' etiketi eklenir.)"""
    son = _son_giden(platform, kullanici)
    return son is not None and son is not _DB_HATA \
        and KOMBI_ONAY_SORUSU in (son.metin or "")


_DB_HATA = object()   # _son_giden: "okunamadı" (hata) ile "hiç mesaj yok" (None) ayrımı


def _son_giden(platform: str, kullanici: str):
    """Bota ait SON giden mesaj kaydı; hiç yoksa None, DB hatasında _DB_HATA."""
    if not (platform and kullanici):
        return _DB_HATA
    try:
        from catalog.database import SessionLocal   # geç import: testte DB yok
        from catalog.sa_models import BotMesaj
        from sqlalchemy import select
        session = SessionLocal()
        try:
            return session.scalar(
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
        return _DB_HATA


def _ara_bekleniyor_mu(platform: str, kullanici: str) -> bool:
    """Bota gönderilen SON mesaj 'Beni arayın' sorusu mu?

    Öyleyse müşterinin şimdiki serbest metni numara+saat cevabıdır.
    Müşteri soru yerine bir butona basarsa akış normal menüden sürer ve
    bir sonraki giden mesaj soruyu ezer → bekleme kendiliğinden düşer.
    """
    son = _son_giden(platform, kullanici)
    return son is not None and son is not _DB_HATA \
        and (son.metin or "").startswith(ARA_SORU_ISARET)


def _ilk_temas_mi(platform: str, kullanici: str) -> bool:
    """Bot bu müşteriye daha önce HİÇ mesaj göndermemiş mi? (yeni konuşma)

    AI cevabının ardından karşılama+menünün yalnız İLK temasta eklenmesi için;
    süren sohbette (örn. pazarlık) her cevaba menü yapıştırmak gürültü olur.
    DB hatasında False — emin değilsek fazladan karşılama gönderme.
    """
    return _son_giden(platform, kullanici) is None


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


# ── AI yönlendirme (Faz 5, soru-cevap öncelikli hibrit) ──────────────────────
# İlke (İsmail, 2026-07-11): müşterinin sorusu ASLA cevapsız menüye düşmesin —
# önce sorunun cevabı, menü sonra. Sinyalli net sorular AI'ya ÖNCE gider (yazarak
# menü navigasyonundan bile önce); sinyalsiz serbest metin önce bedava yollara
# (selam şablonu, kategori/koleksiyon adı) bakar, hiçbiri tutmazsa YİNE AI'ya
# gider (eskiden burada doğrudan menüye düşülüyordu — "alakasız menü" şikâyeti).
# Menü artık yalnız AI kapalı/kota dolu/hatalıyken son emniyet ağıdır.
AI_SINYAL_KELIMELER = (
    # fiyat niyeti
    "fiyat", "ne kadar", "kaç para", "kaça", "kaç lira", "kaç tl", "ücret",
    "tutar", "indirim", "kampanya", "taksit", "kaç bin", "peşin",
    # arama / soru niyeti
    "var mı", "varmı", "nedir", "hangi", "nasıl", "arıyorum", "ariyorum",
    "istiyorum", "bakıyorum", "bakiyorum", "lazım", "lazim", "önerir", "onerir",
    "modeli", "ölçü", "olcu", "renk",
    # mağaza bilgisi niyeti → AI, magaza_bilgi tool'undan (bot_bilgi) cevaplar;
    # DB'de yoksa soru bot_soru'ya düşer, İsmail /app/bot/bilgi'den cevaplar.
    "adres", "konum", "nerede", "neredesiniz", "mesai", "açık mı", "acik mi",
    "kaça kadar", "kaca kadar", "kaçta", "kacta", "kargo", "teslimat",
    "gönderim", "gonderim", "iade", "garanti", "montaj", "kurulum",
    "telefon", "numaranız", "numaraniz",
)


def _ai_gerekli_mi(tetik: str) -> bool:
    """Serbest metin NET ürün/fiyat sorusu mu? (AI'ya ÖNCELİKLİ gitsin)

    True → AI, yazarak menü navigasyonundan önce denenir ("vermont ne kadar").
    False → önce bedava yollar (kategori/koleksiyon adı) denenir; onlar da
    tutmazsa metin yine AI'ya düşer (yanit_uret 5. adım) — soru cevapsız kalmaz.
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


def _ai_cevabi(tetik: str, platform: str, kullanici: str, gecmissiz: bool,
               veri, P) -> dict | list | None:
    """AI'dan cevap iste; üretemezse None (çağıran menüye düşer).

    İLK temasta (bot müşteriye daha önce hiç yazmamışsa) cevabın ardına
    karşılama + kategori menüsü eklenir: önce sorunun cevabı, sonra
    "Merhaba, hoş geldiniz…" (İsmail'in istediği sıra). Süren sohbette
    yalnız cevap gider — pazarlık ortasında menü yapıştırılmaz.
    """
    from bot import ajan  # geç import: testlerde/ajan kapalıyken yük yok
    cevap = ajan.cevapla(tetik, platform, kullanici, gecmissiz=gecmissiz)
    if not cevap:
        return None
    if _ilk_temas_mi(platform, kullanici):
        return [P.metin_mesaji(cevap),
                P.metin_mesaji(selam_metni()),
                P.kategoriler_mesaji(veri.kategoriler())]
    return P.metin_mesaji(cevap)


def yanit_uret(tetik: str, veri=_default_veri, P=_default_P,
               platform: str = "", kullanici: str = "", gecmissiz: bool = False) -> dict:
    """Tetik token'ından (START / KAT:.. / KOL:.. / KOM:.. / YETKILI) mesaj üret.

    Payload'lar sayfa taşıyabilir: 'KAT:48:2' = 48 no'lu kategorinin 2. sayfası,
    'START:2' = kategori menüsünün 2. sayfası (bkz. presenter sayfalama).

    Hibrit akış (soru-cevap öncelikli): buton payload'ları menü mantığında kalır.
    Serbest metin için:
      1. Selam → sıcak karşılama metni + kategori menüsü (ikisi de bedava, şablon).
      2. Net ürün/fiyat sorusu (fiyat, ne kadar, "?"…) → AI; ilk temasta cevabın
         ardına karşılama + menü eklenir (_ai_cevabi).
      3. Yazılan kategori adı → o kategorinin ürün grupları (yazarak menü navigasyonu).
      4. Yazılan koleksiyon/ürün adı → o grubun kombinasyonları.
      5. Hiçbiri tutmayan serbest metin → YİNE AI: soru/sohbet cevapsız kalmasın
         (eskiden doğrudan menüye düşerdi — müşteri "alakasız menü" görüyordu).
      6. AI kapalı/kota dolu/hatalı → kategori menüsü (son emniyet ağı;
         müşteri asla cevapsız kalmaz).
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

    # 0c) Kombinasyon detayındaki onay sorusuna kısa olumlu cevap ("evet",
    #     "uygundur") → pazarlık daveti. Müşterinin sonraki mesajı ("olur",
    #     "ne kadar olur") AI'ya düşer ve pazarlık merdiveni oradan işler.
    if platform and kullanici and _onay_cevabi_mi(tetik) \
            and _kombi_onay_bekleniyor_mu(platform, kullanici):
        return P.metin_mesaji(davet_metni())

    # 1) Sadece selam (fiyat/soru sinyali yoksa) → sıcak karşılama + menü (iki mesaj)
    if _selam_mi(tetik) and not _ai_gerekli_mi(tetik):
        return [P.metin_mesaji(selam_metni()),
                P.kategoriler_mesaji(veri.kategoriler())]

    # 2) Net ürün/fiyat sorusu → AI önce (başarısızsa aşağı, menüye düşer)
    if platform and kullanici and _ai_gerekli_mi(tetik):
        cevap = _ai_cevabi(tetik, platform, kullanici, gecmissiz, veri, P)
        if cevap is not None:
            return cevap

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

    # 5) Menü ögesine uymayan serbest metin → yine AI: soru cevapsız kalmasın.
    #    (Sinyalliler 2. adımda zaten denendi — AI o an düştüyse burada tekrar
    #    denemek aynı hatayı bekletip yaşatır, o yüzden yalnız sinyalsizler.)
    if platform and kullanici and not _ai_gerekli_mi(tetik):
        cevap = _ai_cevabi(tetik, platform, kullanici, gecmissiz, veri, P)
        if cevap is not None:
            return cevap

    # 6) Son emniyet ağı (AI kapalı/kota/hata) → kategori menüsü
    return P.kategoriler_mesaji(veri.kategoriler())
