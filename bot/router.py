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
    # "Yetkilimiz" → "Mağaza Müdürü" (İsmail 2026-09-18): müşteriye kimin
    # cevap vereceğini somut söylemek güven veriyor.
    return f"👤 Mağaza Müdürü: {YETKILI_TEL_GORUNEN}"


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


# Video işareti: [video:teshir:<id>] ya da [video:kol:<id>]. Fotoğraftan AYRI
# tutuluyor çünkü gönderim biçimi bambaşka — fotoğraf bir görsel mesajı olarak
# gider, video ise ÖNİZLEMELİ METİN linki (YouTube; gerekçe catalog/services/
# video.py'de). İkisi aynı cevapta olabilir: önce metin, sonra fotoğraflar,
# en sonda video linki.
VIDEO_ISARETI = re.compile(r"\s*\[video:\s*(teshir|kol)\s*:\s*(\d{1,12})\s*\]\s*")


def _video_ayikla(cevap: str) -> tuple[str, str | None]:
    """Cevaptan [video:tur:id] işaretini çıkar; (temiz metin, video adresi)."""
    bulunan = VIDEO_ISARETI.search(cevap or "")
    if not bulunan:
        return cevap, None
    temiz = VIDEO_ISARETI.sub(" ", cevap).strip()
    from catalog.services import video as video_servis
    tur = "teshir" if bulunan.group(1) == "teshir" else "koleksiyon"
    return temiz, video_servis.video_var_mi(tur, int(bulunan.group(2)))


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


# ── Numaralı seçim butonları (İsmail isteği 2026-09-17) ─────────────────────
# Ajan takım seçeneklerini listelediğinde cevabın sonuna [secenekler:kol:<id>]
# koyar; router bunu butonlara çevirir. Menü DEĞİL — tek adımlık seçim:
# müşteri numaraya basar, o kombinasyonun fiyatı KOD tarafından üretilir
# (AI çağrısı yok → anında cevap, kota harcanmaz).
SECENEK_ISARETI = re.compile(r"\s*\[secenekler:\s*kol\s*:\s*(\d{1,12})\s*\]\s*")
# Aynı seri birden çok kategorideyse (MILENA) kategori sorusu da BUTONLU sorulur;
# müşteri "yatak odası" diye yazmak zorunda kalmasın (2026-09-18).
SERI_ISARETI = re.compile(r"\s*\[seriler:\s*([^\]\n]{1,60}?)\s*\]\s*")
# Tek ürün fiyatı: butonları kurabilmek için hangi SKU olduğunu bilmek gerek.
PARCA_ISARETI = re.compile(r"\s*\[parca:\s*([A-Za-z0-9\-_.]{1,40})\s*\]\s*")
# Takım (kombinasyon) fiyatı: 📉 İndirim / ⬅️ Geri butonlarını kurabilmek için.
KOMBINASYON_ISARETI = re.compile(r"\s*\[kombinasyon:\s*(\d{1,12})\s*\]\s*")
# Pazarlık bitti → müdür kartı cevabın ARDINDAN ayrı mesaj olarak gider
# (İsmail 2026-09-20: "yetkili yazın" yerine kartı doğrudan göster).
YETKILI_ISARETI = re.compile(r"\s*\[yetkili\]\s*")
GERI_BUTONU = "⬅️ Geri"
YETKILI_BUTONU = "👤 Mağaza Müdürü"     # WhatsApp buton başlığı sınırı 20 karakter
INDIRIM_BUTONU = "📉 İndirim"
# WhatsApp listesi en çok 10 satır; 2'si Geri + Yetkili için ayrılır.
SECENEK_MAX = 8
PAZARLIK_DAVETI = "Size özel bir fiyat çalışması yapmak isteriz. 😊"
# Pazarlık bitti: son fiyattan sonra müşteriye kalan tek adım insana bağlanmak
# (İsmail 2026-09-20). Buton başlığı tek başına yeterli değil — açık soru
# sorulunca müşteri cevap veriyor. ajan._MUDUR_SORUSU ile AYNI cümle olmalı:
# aynı ana iki yoldan gelinir (buton cevabı burada, serbest pazarlık ajanda).
MUDUR_SORUSU = "Mağaza müdürümüzle uygun bir vakitte görüşmek ister misiniz?"


def _secenek_ayikla(cevap: str) -> tuple[str, int | None]:
    """Cevaptan [secenekler:kol:<id>] işaretini çıkar; (temiz metin, kol id)."""
    bulunan = SECENEK_ISARETI.search(cevap or "")
    if not bulunan:
        return cevap, None
    return SECENEK_ISARETI.sub(" ", cevap).strip(), int(bulunan.group(1))


def _parca_ayikla(cevap: str) -> tuple[str, str | None]:
    """Cevaptan [parca:<SKU>] işaretini çıkar; (temiz metin, SKU)."""
    bulunan = PARCA_ISARETI.search(cevap or "")
    if not bulunan:
        return cevap, None
    return PARCA_ISARETI.sub(" ", cevap).strip(), bulunan.group(1)


def _seri_ayikla(cevap: str) -> tuple[str, str | None]:
    """Cevaptan [seriler:<ad>] işaretini çıkar; (temiz metin, seri adı)."""
    bulunan = SERI_ISARETI.search(cevap or "")
    if not bulunan:
        return cevap, None
    return SERI_ISARETI.sub(" ", cevap).strip(), bulunan.group(1).strip()


def _kombinasyon_ayikla(cevap: str) -> tuple[str, int | None]:
    """Cevaptan [kombinasyon:<id>] işaretini çıkar; (temiz metin, kombi id)."""
    bulunan = KOMBINASYON_ISARETI.search(cevap or "")
    if not bulunan:
        return cevap, None
    return KOMBINASYON_ISARETI.sub(" ", cevap).strip(), int(bulunan.group(1))


def _yetkili_ayikla(cevap: str) -> tuple[str, bool]:
    """Cevaptan [yetkili] işaretini çıkar; (temiz metin, kart gönderilsin mi).

    Pazarlık merdiveni bitince ajan bu işareti koyar (bkz. ajan._mudur_karti_
    teklif_et): müşteri "yetkili" yazmayı beklemeden müdür kartı cevabın
    ardından gider.
    """
    if not YETKILI_ISARETI.search(cevap or ""):
        return cevap, False
    return YETKILI_ISARETI.sub(" ", cevap).strip(), True


def _secenekler_mesaji(koleksiyon_id: int, P, metin: str = "",
                       tek_ise_fiyat: bool = True) -> dict | None:
    """Koleksiyonun numaralı takım seçenekleri + Geri/Yetkili butonları.

    Numaralar `menu_veri.kombinasyonlar` sırasından gelir — metindeki "3" ile
    butondaki "3" AYNI kombinasyonu gösterir. Tek seçenek varsa buton üretmeye
    gerek yok, doğrudan fiyat gider.
    """
    from catalog.services import menu_veri
    veri = menu_veri.kombinasyonlar(koleksiyon_id)
    kombiler = (veri or {}).get("kombinasyonlar") or []
    if not kombiler:
        return None
    if len(kombiler) == 1:
        # Butona basılarak gelindiyse tek seçeneği sormanın anlamı yok, fiyatı
        # ver. Ajan işaretinden gelindiyse (tek_ise_fiyat=False) cevabı model
        # zaten yazdı — üstüne kod metni bindirme.
        return _kombinasyon_fiyat_mesaji(kombiler[0]["id"], P) if tek_ise_fiyat else None
    kol = veri["koleksiyon"]
    if not metin:
        # Liste metnini KOD yazar, model DEĞİL (İsmail 2026-09-18): canlıda
        # model dört seçeneği tek paragrafa dizdi ("1. ..., 2. ..., 3. ... ve
        # 4. ...") ve okunmaz hâle geldi. Her seçenek KENDİ satırında.
        metin = (f"{kol['tam_ad']} için seçeneklerimiz:\n\n"
                 f"{veri['secenek_metni']}\n\n"
                 f"Hangisini istersiniz? 😊")
    # Buton/satır başlığı YALNIZ NUMARA (İsmail 2026-09-18). Ada da yer versek
    # platform sınırında kırpılıyor ("1. Dörtlü, Tekno, Üçlü,…") ve hemen
    # altındaki açıklamayı tekrarlıyordu. Tam ad açıklamada (WhatsApp) ve zaten
    # mesaj gövdesindeki numaralı listede duruyor.
    # Listede YALNIZ seçenekler (İsmail 2026-09-18): Geri/Yetkili satırları
    # buradan kaldırıldı — müşteri bu ekranda ürün seçer, gezinmez. Yetkiliye
    # ulaşmak için "yetkili" yazmak yeterli (ajan uygun anlarda hatırlatıyor).
    secenekler = [(f"{k['no']}.", f"KOM:{k['id']}", k["ad"])
                  for k in kombiler[:SECENEK_MAX]]
    return P.secim_mesaji(metin, secenekler)


def _kombinasyon_fiyat_mesaji(kombinasyon_id: int, P) -> dict | None:
    """Seçilen kombinasyonun fiyatı — KOD üretir, model çağrılmaz.

    Fiyat bloğu (ad + Liste/Size Özel) menu_veri'den hazır gelir; buraya yalnız
    pazarlık daveti ile Geri/Yetkili butonları eklenir. Pazarlık daveti metni
    ajan tarafındakiyle AYNI olmalı: ajan bir sonraki turda müşterinin "olur"
    cevabını bu cümleden tanıyor (_davete_olumlu_mu).
    """
    from catalog.services import menu_veri
    veri = menu_veri.kombinasyon(kombinasyon_id)
    if not veri or not veri.get("fiyat_cumlesi"):
        return None
    metin = f"{veri['fiyat_cumlesi']}\n\n{PAZARLIK_DAVETI}"
    kol = veri.get("koleksiyon") or {}
    butonlar = []
    # 📉 İndirim (İsmail isteği 2026-09-18): tek dokunuşla merdivenin SON
    # kademesi (Müdür fiyatı). Merdiven yoksa — toptanı olmayan ya da şüpheli
    # kayıt — buton hiç GÖSTERİLMEZ, yoksa basana verecek indirim olmaz.
    if veri.get("_merdiven"):
        butonlar.append((INDIRIM_BUTONU, f"IND:{kombinasyon_id}", ""))
    if kol.get("id"):
        butonlar.append((GERI_BUTONU, f"KOL:{kol['id']}", ""))
    # Yetkili butonu BURADA yok (İsmail 2026-09-18): fiyatı yeni görmüş
    # müşteriyi insana yönlendirmek yerine önce indirim/geri seçenekleri
    # dursun. İndirim cevabında Yetkili yine var.
    return P.secim_mesaji(metin, butonlar)


def _parca_fiyat_butonlari(sku: str, P, metin: str) -> dict | None:
    """Tek ürün fiyatına da 📉 İndirim / ⬅️ Geri butonlarını iliştir.

    Kombinasyonlarda butonlar vardı, tekil üründe yoktu (İsmail 2026-09-18).
    Metni model yazar (fiyat bloğu araçtan hazır geliyor), butonları kod kurar.
    """
    from catalog.services import menu_veri
    veri = menu_veri.urun(sku)
    if not veri:
        return None
    butonlar = []
    if veri.get("_merdiven"):
        butonlar.append((INDIRIM_BUTONU, f"PIND:{sku}", ""))
    if veri.get("koleksiyon_id"):
        butonlar.append((GERI_BUTONU, f"KOL:{veri['koleksiyon_id']}", ""))
    if not butonlar:
        return None
    return P.secim_mesaji(metin, butonlar)


def _kombinasyon_fiyat_butonlari(kombinasyon_id: int, P,
                                 metin: str) -> dict | None:
    """AI'nın verdiği TAKIM fiyatına 📉 İndirim / ⬅️ Geri butonlarını iliştir.

    _parca_fiyat_butonlari ile aynı desen: metni model yazar (fiyat bloğu
    araçtan hazır geliyor), butonları kod kurar. Buton eskiden yalnız numaralı
    seçimden gelen cevapta vardı (_kombinasyon_fiyat_mesaji); müşteri ürünü
    yazarak sorduğunda kayboluyordu (İsmail 2026-09-20, LIVORNO story yanıtı).
    """
    from catalog.services import menu_veri
    veri = menu_veri.kombinasyon(kombinasyon_id)
    if not veri:
        return None
    butonlar = []
    # Merdiven yoksa (toptanı eksik/şüpheli kayıt) indirim butonu GÖSTERİLMEZ —
    # basana verecek indirim olmaz.
    if veri.get("_merdiven"):
        butonlar.append((INDIRIM_BUTONU, f"IND:{kombinasyon_id}", ""))
    kol = veri.get("koleksiyon") or {}
    if kol.get("id"):
        butonlar.append((GERI_BUTONU, f"KOL:{kol['id']}", ""))
    if not butonlar:
        return None
    return P.secim_mesaji(metin, butonlar)


def _parca_indirim_mesaji(sku: str, P) -> dict | None:
    """Tek üründe 📉 İndirim: merdivenin SON kademesi + Yetkili butonu."""
    from catalog.services import menu_veri
    veri = menu_veri.urun(sku)
    merdiven = (veri or {}).get("_merdiven")
    if not veri or not merdiven:
        return None
    metin = (f"{veri['ad']}\n\n"
             f"Size özel fiyatımız: {menu_veri._tl(merdiven[-1])}\n"
             f"Bu bizim son fiyatımız 😊\n\n{MUDUR_SORUSU}")
    return P.secim_mesaji(metin, [(YETKILI_BUTONU, YETKILI_PAYLOAD, "")])


def _kombinasyon_indirim_mesaji(kombinasyon_id: int, P) -> dict | None:
    """📉 İndirim butonunun cevabı: merdivenin SON kademesi (Müdür fiyatı).

    Merdivenin iki kademesi var (ilk = ×1,37, son = ×1,31); buton doğrudan
    sonuncuyu verir. Altına inilecek bir adım kalmadığı için cevapta İndirim
    butonu TEKRAR gösterilmez — müşteri "biraz daha" yazarsa ajan devreye
    girer ve ADIM DURUMU zaten "merdiven bitti" der (rakam giden mesajdan
    okunuyor).
    """
    from catalog.services import menu_veri
    veri = menu_veri.kombinasyon(kombinasyon_id)
    merdiven = (veri or {}).get("_merdiven")
    if not veri or not merdiven:
        return None
    metin = (f"{veri['baslik']}\n\n"
             f"Size özel fiyatımız: {menu_veri._tl(merdiven[-1])}\n"
             f"Bu bizim son fiyatımız 😊\n\n{MUDUR_SORUSU}")
    # Son fiyattan sonra TEK buton: Yetkili (İsmail 2026-09-18). Pazarlık
    # bitti; müşteriye kalan tek adım insana bağlanmak.
    return P.secim_mesaji(metin, [(YETKILI_BUTONU, YETKILI_PAYLOAD, "")])


def _koleksiyon_secim_mesaji(ad: str, P, metin: str = "") -> dict | None:
    """Aynı seri birden çok kategorideyse (LEGNA) kategori seçimi.

    Seçenek listesindeki "Geri" buraya döner: müşteri yanlış kategoriye
    girdiyse seriyi yeniden yazmadan düzeltebilsin (İsmail kararı 2026-09-17).
    """
    from catalog.services import menu_veri
    eslesmeler = menu_veri.koleksiyon_ara(ad or "")
    if not eslesmeler:
        return None
    if len(eslesmeler) == 1:
        return _secenekler_mesaji(eslesmeler[0]["id"], P)
    # Yalnız kategoriler — Yetkili butonu YOK (İsmail 2026-09-18: yetkili
    # yalnız SON indirimden sonra çıksın, her ekranda değil).
    secenekler = [(k.get("kategori") or k["ad"], f"KOL:{k['id']}", "")
                  for k in eslesmeler[:SECENEK_MAX]]
    # Kategori adları butonların üstünde zaten yazıyor; modelin sorusu varsa
    # onu kullan (doğal dili daha iyi), yoksa kısa varsayılan soru.
    return P.secim_mesaji(metin or f"{eslesmeler[0]['ad']} hangi kategoride olsun?",
                          secenekler)


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
    cevap, video_url = _video_ayikla(cevap)
    cevap, kol_id = _secenek_ayikla(cevap)
    cevap, seri_adi = _seri_ayikla(cevap)
    cevap, parca_sku = _parca_ayikla(cevap)
    cevap, kombi_id = _kombinasyon_ayikla(cevap)
    cevap, mudur_karti = _yetkili_ayikla(cevap)
    if not cevap and not kod and not video_url and not kol_id:   # hiçbir şey yok
        return None
    # Seçenek listesi: METNİ DE BUTONLARI DA KOD yazar (İsmail 2026-09-18).
    # Modelin yazdığı liste metni BİLEREK atılır — canlıda dört seçeneği tek
    # paragrafa dizip okunmaz hâle getirdi. Model yalnız "listeyi göster"
    # işaretini koyar; düzen bizim.
    butonlu = (_secenekler_mesaji(kol_id, P, tek_ise_fiyat=False)
               if kol_id else None)
    # Kategori sorusu: modelin sorduğu cümle kalır, seçenekler butona döner.
    # (Seçenek listesinin aksine metni modelden alıyoruz: burada liste
    # butonlarda duruyor, modelin yazdığı yalnızca soru cümlesi.)
    if butonlu is None and seri_adi:
        butonlu = _koleksiyon_secim_mesaji(seri_adi, P, metin=cevap)
    # Tek ürün fiyatı: metin modelin, butonlar kodun.
    # SKU iki yerden gelebilir: [parca:<SKU>] işareti (arama TEK ürün
    # döndürdüğünde konur) ya da fotoğraf işareti [gorsel:<SKU>]. İkincisi
    # şart: "KIERA Berjer" gibi çok kayıtlı aramalarda model bir tanesini
    # seçip fiyat veriyor, [parca:] konmuyordu ve butonlar kayboluyordu
    # (İsmail 2026-09-18). Fotoğraf işareti yalnız TEK ürün cevabında konur
    # (çoklu listede yasak), dolayısıyla doğru çapa.
    if butonlu is None and cevap and kombi_id:
        butonlu = _kombinasyon_fiyat_butonlari(kombi_id, P, cevap)
    if butonlu is None and cevap:
        sku = parca_sku or (kod if kod and not kod.startswith("teshir:") else None)
        if sku:
            butonlu = _parca_fiyat_butonlari(sku, P, cevap)
    if not cevap:
        if butonlu:
            return butonlu
        # Model YALNIZ işareti yazdı — "evet gönderin" gibi kısa isteklerde
        # doğal davranış (canlıda görüldü 2026-08-02). Eskiden burada None
        # dönülüyordu: medya da metin de gitmiyor, müşteri boş kalıyordu.
        cevap = "Buyurun, mağazadaki hâli 👇"
    mesajlar = [butonlu or P.metin_mesaji(cevap)]
    if kod and hasattr(P, "gorsel_mesaji"):
        mesajlar += [P.gorsel_mesaji(u) for u in _gorsel_urlleri(kod)]
    if video_url and hasattr(P, "video_mesaji"):
        mesajlar.append(P.video_mesaji(video_url))
    if mudur_karti and hasattr(P, "yetkili_mesaji"):
        mesajlar.append(P.yetkili_mesaji(yetkili_metni(), YETKILI_URL,
                                         YETKILI_ARA_URL))
    return mesajlar if len(mesajlar) > 1 else mesajlar[0]


def yanit_uret(tetik: str, P=_default_P, platform: str = "",
               kullanici: str = "", gecmissiz: bool = False) -> dict:
    """Tetik token'ından mesaj üret — AI-only akış.

    Sıra:
      1. "Yetkiliyle görüş" (yazı, eski YETKILI ya da eski BENIARA butonu) →
         yetkili kartı. İnsana yönlendirmenin TEK yolu budur (İsmail 2026-07-27:
         "beni ara" geri arama akışı kaldırıldı).
      2. Numaralı seçim butonları (KOM/KOL/GERI, 2026-09-17) → cevabı kod üretir.
      3. Kalan eski menü butonu (KAT/START) ya da boş mesaj → yazmaya yönlendir.
      4. Her serbest metin (selam dahil) → AI. Üretemezse metin fallback.
    """
    tur, _deger = parse_secim(tetik)

    # 1) İnsana yönlendirme — menü değil, escalation (buton ya da yazı).
    #    Eski mesajlardaki BENIARA butonu da buraya düşer: geri arama akışı
    #    kaldırıldığı için müşteri boşa düşmesin, yetkiliye yönlendirilsin.
    if _yetkili_mi(tur, tetik) or tur == BENIARA_PAYLOAD:
        return P.yetkili_mesaji(yetkili_metni(), YETKILI_URL, YETKILI_ARA_URL)

    # 2) Numaralı seçim butonları (2026-09-17). Cevabı KOD üretir — model
    #    çağrılmaz: müşteri anında cevap alır, kota harcanmaz. Kayıt (silinmiş
    #    kombinasyon, değişmiş id) bulunamazsa aşağıdaki eski-buton dalına
    #    düşer ve müşteri yazmaya yönlendirilir.
    if tur == "KOM" and (_deger or "").isdigit():
        mesaj = _kombinasyon_fiyat_mesaji(int(_deger), P)
        if mesaj:
            return mesaj
    if tur == "IND" and (_deger or "").isdigit():
        mesaj = _kombinasyon_indirim_mesaji(int(_deger), P)
        if mesaj:
            return mesaj
    if tur == "PIND" and _deger:
        mesaj = _parca_indirim_mesaji(_deger, P)
        if mesaj:
            return mesaj
    if tur == "KOL" and (_deger or "").isdigit():
        mesaj = _secenekler_mesaji(int(_deger), P)
        if mesaj:
            return mesaj
    if tur == "GERI":
        deger = _deger or ""
        if deger.upper().startswith("ARA:"):
            mesaj = _koleksiyon_secim_mesaji(deger[4:], P)
            if mesaj:
                return mesaj
        return P.metin_mesaji(YAZMAYA_YONLENDIR)

    # 3) Eski menü butonu ya da boş mesaj → menü yok, yazmaya yönlendir.
    if tur in ("KAT", "KOL", "KOM", "START"):
        return P.metin_mesaji(YAZMAYA_YONLENDIR)

    # 4) Her serbest metin → AI. Üretemezse (kapalı/kota/hata) metin fallback.
    if platform and kullanici:
        cevap = _ai_cevabi(tetik, platform, kullanici, gecmissiz, P)
        if cevap is not None:
            return cevap
    return P.metin_mesaji(AI_KAPALI_METNI)
