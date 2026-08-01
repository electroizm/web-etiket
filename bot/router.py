"""AI-öncelikli yönlendirici: gelen her mesaj AI ajanına verilir.

İsmail kararı (2026-07-21): kategori/menü ile seçim TAMAMEN kaldırıldı — bot
artık YALNIZCA AI cevabıyla ilerler. Menü butonu üretilmez; müşteri aradığı
ürünü/fiyatı doğrudan yazar, ajan tool'lardan gerçek fiyatı okuyup cevaplar.
(Menü sonrası buton kalabalığı müşteride karışıklık yaratıyordu.)

AI dışında YALNIZ TEK şablon akış korunur — bu menü değil, insana
yönlendirmedir; ajan uygun anlarda kendiliğinden de önerir (menü olmadığı için
müşteri bunu ancak ajandan/metinden duyar — bkz. ajan sistem promptu):
  - "Yetkiliyle görüş": müşteri "yetkili/temsilci/canlı" yazarsa (ya da eski bir
    YETKILI butonuna basarsa) İsmail'in kişisel WhatsApp'ına (0532) yönlendirilir;
    botun 0488 Cloud API kutusunu İsmail elle göremediği için.

İsmail kararı (2026-07-27): "Beni arayın" (geri arama talebi) akışı TAMAMEN
kaldırıldı — insana yönlendirme yalnız "yetkili" ile olur. Eski mesajlardan
BENIARA butonuna basılırsa yetkili kartı gösterilir.

P (sunum modülü) platforma göre ig_presenter ya da wa_presenter olur; ikisi de
aynı fonksiyon adlarını sunduğu için yönlendirici platformdan bağımsız kalır.
Test için P enjekte edilebilir.
"""
from __future__ import annotations

import re

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


# Eski mesajlarda kalan "📞 Beni arayın" butonunun payload'ı. Akış kaldırıldı
# (İsmail 2026-07-27); butona basan müşteri yetkili kartına yönlendirilir.
BENIARA_PAYLOAD = "BENIARA"


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
# Ajan fotoğraf göstermek istediğinde cevabın SONUNA bu işareti koyar.
# İki biçim var:
#   [gorsel:<SKU>]          → katalog fotoğrafı (dogtas.com fabrika çekimi)
#   [gorsel:teshir:<id>]    → MAĞAZADAKİ gerçek malın fotoğrafları (2-4 açı)
# Neden URL değil kısa kod (İsmail isteği 2026-07-28): uzun CDN adresini model
# kopyalarken bozabilir; SKU/id kısa ve zaten araç sonucunda birebir duruyor.
# Adresi router çözer, müşteri işareti GÖRMEZ.
GORSEL_ISARETI = re.compile(r"\s*\[gorsel:\s*((?:teshir:)?[A-Za-z0-9\-_.]{1,40})\s*\]\s*")


def _gorsel_ayikla(cevap: str) -> tuple[str, str | None]:
    """Cevaptan [gorsel:...] işaretini çıkar; (temiz metin, kod) döner."""
    bulunan = GORSEL_ISARETI.search(cevap or "")
    if not bulunan:
        return cevap, None
    return GORSEL_ISARETI.sub(" ", cevap).strip(), bulunan.group(1)


def _gorsel_urlleri(kod: str) -> list[str]:
    """İşaretteki kodu gönderilecek fotoğraf adreslerine çevir.

    Teşhirde birden fazla açı olabilir (İsmail kararı 2026-08-02), katalogda
    tek fotoğraf. Bulunamazsa boş liste — metin yine gider, müşteri cevapsız
    kalmaz.
    """
    if kod.startswith("teshir:"):
        ham = kod.split(":", 1)[1]
        if not ham.isdigit():
            return []
        from catalog.services import teshir as teshir_servis
        return teshir_servis.fotograflar(int(ham))
    from bot import urun_gorsel
    url = urun_gorsel.url_bul(kod)
    return [url] if url else []


def _ai_cevabi(tetik: str, platform: str, kullanici: str, gecmissiz: bool,
               P) -> dict | list[dict] | None:
    """AI'dan cevap iste; üretemezse None (çağıran metin fallback'ine düşer).

    Normalde TEK düz metin mesajı döner — menü/karşılama eklenmez (İsmail
    kararı 2026-07-21). İSTİSNA: ajan cevabın sonuna [gorsel:...] koyduysa
    metnin ARDINDAN fotoğraf(lar) da gönderilir (İsmail kararı 2026-07-28:
    fotoğraf yalnız TEK ürün konuşulurken gitsin, listede değil).
    Teşhir işaretinde birden fazla açı olabilir (2026-08-02).
    Fotoğraf alınamazsa metin yine gider — müşteri cevapsız kalmaz.
    """
    from bot import ajan  # geç import: testlerde/ajan kapalıyken yük yok
    cevap = ajan.cevapla(tetik, platform, kullanici, gecmissiz=gecmissiz)
    if not cevap:
        return None
    cevap, kod = _gorsel_ayikla(cevap)
    if not cevap and not kod:           # işaret de yok, metin de yok
        return None
    if not cevap:
        # Model YALNIZ işareti yazdı — "evet gönderin" gibi kısa isteklerde
        # doğal davranış (canlıda görüldü 2026-08-02). Eskiden burada None
        # dönülüyordu: fotoğraf da metin de gitmiyor, müşteri boş kalıyordu.
        cevap = "Buyurun, mağazadaki hâli 👇"
    metin = P.metin_mesaji(cevap)
    if not kod or not hasattr(P, "gorsel_mesaji"):
        return metin
    urller = _gorsel_urlleri(kod)
    if not urller:
        return metin
    return [metin] + [P.gorsel_mesaji(u) for u in urller]


def yanit_uret(tetik: str, P=_default_P, platform: str = "",
               kullanici: str = "", gecmissiz: bool = False) -> dict:
    """Tetik token'ından mesaj üret — AI-only akış.

    Sıra:
      1. "Yetkiliyle görüş" (yazı, eski YETKILI ya da eski BENIARA butonu) →
         yetkili kartı. İnsana yönlendirmenin TEK yolu budur (İsmail 2026-07-27:
         "beni ara" geri arama akışı kaldırıldı).
      2. Eski menü butonu (KAT/KOL/KOM/START) ya da boş mesaj → yazmaya yönlendir
         (menü üretilmez — bu butonlar yalnız geçmiş mesajlardan gelebilir).
      3. Her serbest metin (selam dahil) → AI. Üretemezse metin fallback.
    """
    tur, _deger = parse_secim(tetik)

    # 1) İnsana yönlendirme — menü değil, escalation (buton ya da yazı).
    #    Eski mesajlardaki BENIARA butonu da buraya düşer: geri arama akışı
    #    kaldırıldığı için müşteri boşa düşmesin, yetkiliye yönlendirilsin.
    if _yetkili_mi(tur, tetik) or tur == BENIARA_PAYLOAD:
        return P.yetkili_mesaji(yetkili_metni(), YETKILI_URL, YETKILI_ARA_URL)

    # 2) Eski menü butonu ya da boş mesaj → menü yok, yazmaya yönlendir.
    if tur in ("KAT", "KOL", "KOM", "START"):
        return P.metin_mesaji(YAZMAYA_YONLENDIR)

    # 3) Her serbest metin → AI. Üretemezse (kapalı/kota/hata) metin fallback.
    if platform and kullanici:
        cevap = _ai_cevabi(tetik, platform, kullanici, gecmissiz, P)
        if cevap is not None:
            return cevap
    return P.metin_mesaji(AI_KAPALI_METNI)
