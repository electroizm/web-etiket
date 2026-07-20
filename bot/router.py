"""AI-öncelikli yönlendirici: gelen her mesaj AI ajanına verilir.

İsmail kararı (2026-07-21): kategori/menü ile seçim TAMAMEN kaldırıldı — bot
artık YALNIZCA AI cevabıyla ilerler. Menü butonu üretilmez; müşteri aradığı
ürünü/fiyatı doğrudan yazar, ajan tool'lardan gerçek fiyatı okuyup cevaplar.
(Menü sonrası buton kalabalığı müşteride karışıklık yaratıyordu.)

AI dışında YALNIZ iki şablon akış korunur — bunlar menü değil, insana
yönlendirmedir; ajan uygun anlarda kendiliğinden de önerir (menü olmadığı için
müşteri bunları ancak ajandan/metinden duyar — bkz. ajan sistem promptu):
  - "Yetkiliyle görüş": müşteri "yetkili/temsilci/canlı" yazarsa (ya da eski bir
    YETKILI butonuna basarsa) İsmail'in kişisel WhatsApp'ına (0532) yönlendirilir;
    botun 0488 Cloud API kutusunu İsmail elle göremediği için.
  - "Beni arayın": müşteri geri arama isterse numara + uygun saat sorulur; cevabı
    İsmail'e bildirim olarak gider (bot/bildirim.py).

P (sunum modülü) platforma göre ig_presenter ya da wa_presenter olur; ikisi de
aynı fonksiyon adlarını sunduğu için yönlendirici platformdan bağımsız kalır.
Test için P enjekte edilebilir.
"""
from __future__ import annotations

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
# Müşteri isteyince numarası + uygun saati sorulur; cevabı İsmail'in 0532
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
            "Başka bir sorunuz olursa yazmanız yeterli.")


def _beniara_mi(tur: str, tetik: str) -> bool:
    if tur == BENIARA_PAYLOAD:
        return True
    low = (tetik or "").lower()
    return any(k in low for k in BENIARA_KELIMELER)


# ── Metin şablonları: AI kapalı + eski menü butonu / boş mesaj ───────────────
# Menü kalktığı için "son emniyet ağı" artık kategori menüsü değil düz metindir.
# AI kapalı/kota dolu/hatalı olduğunda müşteri cevapsız kalmasın; yetkili
# seçeneğini de burada hatırlatırız (menü olmadığı için tek görünürlük burası).
AI_KAPALI_METNI = ("Şu an size hemen yardımcı olamıyorum, kusura bakmayın 🙏 "
                   "Birazdan tekrar yazabilir ya da bir yetkiliyle görüşmek "
                   "için 'yetkili' yazabilirsiniz.")
# Eski mesajlardaki menü butonlarına (KAT/KOL/KOM/START) basılırsa ya da boş
# mesaj gelirse: menü YOK — müşteriyi doğrudan yazmaya yönlendir. Bu butonlar
# artık üretilmiyor; yalnız geçmiş mesajlardan tıklanabilir.
YAZMAYA_YONLENDIR = ("Merhaba! 😊 Aradığınız ürünü ya da fiyatı doğrudan "
                     "yazmanız yeterli — size hemen yardımcı olayım.")


# ── bot_mesaj geçmişi yardımcıları ───────────────────────────────────────────
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
    """
    son = _son_giden(platform, kullanici)
    return son is not None and son is not _DB_HATA \
        and (son.metin or "").startswith(ARA_SORU_ISARET)


def _ara_talebi_isle(platform: str, kullanici: str, metin: str) -> None:
    """Cevabı yetkiliye ilet (bildirim hatası müşteri akışını bozmaz)."""
    try:
        from bot import bildirim   # geç import: testte Django/DB gerekmesin
        bildirim.geri_arama_bildir(platform, kullanici, metin)
    except Exception:
        pass


def _yetkili_mi(tur: str, tetik: str) -> bool:
    if tur == YETKILI_PAYLOAD:
        return True
    low = tetik.lower()
    return any(k in low for k in YETKILI_KELIMELER)


# Türkçe karakterleri sadeleştir (bot/yorum.py de kullanır: tetik kelimesi eşleşsin).
_TR_DUZLE = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def _duzle(s: str) -> str:
    # Önce çevir (İ→i büyükken yakalansın), sonra küçült, kalan Türkçe harfleri çevir;
    # Python'un "İ".lower() çıktısındaki birleşik noktayı (U+0307) da at.
    s = (s or "").strip().translate(_TR_DUZLE).lower().translate(_TR_DUZLE)
    return s.replace("̇", "")


# ── AI cevabı ────────────────────────────────────────────────────────────────
def _ai_cevabi(tetik: str, platform: str, kullanici: str, gecmissiz: bool,
               P) -> dict | None:
    """AI'dan cevap iste; üretemezse None (çağıran metin fallback'ine düşer).

    Cevap her zaman TEK düz metin mesajıdır — menü/karşılama eklenmez
    (İsmail kararı 2026-07-21: AI sonrası menü karışıklık yaratıyordu).
    """
    from bot import ajan  # geç import: testlerde/ajan kapalıyken yük yok
    cevap = ajan.cevapla(tetik, platform, kullanici, gecmissiz=gecmissiz)
    if not cevap:
        return None
    return P.metin_mesaji(cevap)


def yanit_uret(tetik: str, P=_default_P, platform: str = "",
               kullanici: str = "", gecmissiz: bool = False) -> dict:
    """Tetik token'ından mesaj üret — AI-only akış.

    Sıra:
      1. "Yetkiliyle görüş" (yazı ya da eski YETKILI butonu) → yetkili kartı.
      2. "Beni arayın" isteği/sorusu → numara+saat sor / cevabı yetkiliye ilet.
      3. Eski menü butonu (KAT/KOL/KOM/START) ya da boş mesaj → yazmaya yönlendir
         (menü üretilmez — bu butonlar yalnız geçmiş mesajlardan gelebilir).
      4. Her serbest metin (selam dahil) → AI. Üretemezse metin fallback.
    """
    tur, _deger = parse_secim(tetik)

    # 1) İnsana yönlendirme — menü değil, escalation (buton ya da yazı).
    if _yetkili_mi(tur, tetik):
        return P.yetkili_mesaji(yetkili_metni(), YETKILI_URL, YETKILI_ARA_URL)

    # 2a) "📞 Beni arayın" BUTONU → numara + uygun saat sorulur. (Yazıyla
    #     tetikleme aşağıda, bekleme kontrolünden SONRA — cevaptaki "arayın"
    #     kelimesi soruyu yeniden tetiklemesin.)
    if tur == BENIARA_PAYLOAD:
        return P.metin_mesaji(ara_soru_metni())

    # 2b) "Beni arayın" sorusuna cevap bekleniyorsa bu metin numara+saat'tir:
    #     yetkiliye bildir, müşteriye teşekkür et. (AI kontrolünden ÖNCE —
    #     cevap "fiyat" gibi kelimeler içerse bile AI'ya kaçmasın.)
    if platform and kullanici and _ara_bekleniyor_mu(platform, kullanici):
        _ara_talebi_isle(platform, kullanici, tetik)
        return P.metin_mesaji(ara_tesekkur_metni())

    # 2c) Yazıyla geri arama isteği ("beni arayın", "geri ara"…) → soruyu sor.
    if _beniara_mi(tur, tetik):
        return P.metin_mesaji(ara_soru_metni())

    # 3) Eski menü butonu ya da boş mesaj → menü yok, yazmaya yönlendir.
    if tur in ("KAT", "KOL", "KOM", "START"):
        return P.metin_mesaji(YAZMAYA_YONLENDIR)

    # 4) Her serbest metin → AI. Üretemezse (kapalı/kota/hata) metin fallback.
    if platform and kullanici:
        cevap = _ai_cevabi(tetik, platform, kullanici, gecmissiz, P)
        if cevap is not None:
            return cevap
    return P.metin_mesaji(AI_KAPALI_METNI)
