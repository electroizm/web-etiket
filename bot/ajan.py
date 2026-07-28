"""AI ajan (Faz 5) — serbest yazılan müşteri mesajını anlar, gerekirse sohbet eder.

Tasarım ilkeleri (bkz. Obsidian: instALL/outputs/faz5-model-arastirmasi.md):
- Sağlayıcı-bağımsız: LiteLLM üzerinden çağrı; model adı settings.AJAN_MODEL
  (env: AJAN_MODEL). Varsayılan Gemini Flash (ücretsiz katman); yetmezse
  gemini-flash-lite-latest ya da başka sağlayıcıya tek env değişikliğiyle geçilir.
- Fiyat ASLA modelden gelmez: model yalnızca aşağıdaki tool'ları çağırarak
  veritabanındaki gerçek fiyatı okur. Tool sonucu olmadan fiyat yazması yasak
  (sistem promptunda da tembihlenir).
- Zarif düşüş: anahtar yok / kota doldu / hata → None döner, router düz metin
  fallback'i gönderir (menü değil — İsmail kararı 2026-07-21). Müşteri hiçbir
  durumda cevapsız kalmaz.
- Bağlam: bot_mesaj tablosundaki son konuşmalar (settings.AJAN_GECMIS_LIMIT).
"""
from __future__ import annotations

import json
import logging
import re

from django.conf import settings
from sqlalchemy import select

from bot.webhook_core import KOMBI_ONAY_SORUSU
from catalog.database import SessionLocal
from catalog.sa_models import BotMesaj
from catalog.services import menu_veri

log = logging.getLogger("bot.ajan")

MAKS_TOOL_TURU = 6      # tool çağrısı döngüsü üst sınırı (sonsuz döngü emniyeti)
MAKS_CEVAP_KR = 900     # WA/IG'de rahat okunur üst sınır (tek mesaj)

# Son ajan hatası — Render loguna erişim olmadan teşhis için /saglik'ta gösterilir.
SON_HATA: str | None = None

# ── Model zinciri izleme (Gemini kota/yedek teşhisi) ─────────────────────────
# Süreç içi sayaçlar — /saglik'ta gösterilir. Render restart'ında sıfırlanır
# (baslangic damgası o yüzden var); günlük eğilim için yeterli. Alanlar:
#   basari = model cevap üretti;  bos = model döndü ama kalkan/tur limiti
#   cevabı düşürdü (menüye düşüldü);  kota = 429/RateLimit (Gemini ücretsiz
#   kota doldu → zincir sıradakine geçti);  hata = diğer istisnalar.
MODEL_SAYAC: dict[str, dict[str, int]] = {}
SAYAC_BASLANGIC: str | None = None


def _sayac(model: str, alan: str, is_adi: str = "sohbet") -> None:
    global SAYAC_BASLANGIC
    from datetime import datetime
    if SAYAC_BASLANGIC is None:
        SAYAC_BASLANGIC = f"{datetime.now():%d.%m %H:%M}"
    MODEL_SAYAC.setdefault(
        model, {"basari": 0, "bos": 0, "kota": 0, "hata": 0})[alan] += 1
    # Kalıcı sayaç (deploy'da sıfırlanmaz) — panel /app/bot/kota buradan okur.
    from bot import kota
    kota.say(model, is_adi, alan)


def _kota_mu(e: Exception) -> bool:
    """İstisna Gemini kota aşımı mı? (LiteLLM RateLimitError / 429 / quota)"""
    metin = str(e).lower()
    return ("RateLimit" in type(e).__name__ or "429" in str(e)
            or "quota" in metin or "resource_exhausted" in metin)

# ─── Sistem promptu ──────────────────────────────────────────────────────────
# 2026-07-28'de %60 kısaltıldı (13.657 → ~5.400 karakter). Neden:
#   • Bu metin ARAÇ TANIMLARIYLA BİRLİKTE HER çağrıda baştan gider. Ölçüm:
#     6.996 token/çağrı — bir cevabın maliyetinin ~%90'ı buydu.
#   • Ücretsiz alternatiflerin çoğunda DAKİKALIK TOKEN sınırı var (Groq free:
#     6-12K TPM). 7K'lık prompt tek isteği bile sınıra dayıyordu; kısaltmadan
#     Gemini dışına çıkmak mümkün değildi.
#   • Uzun talimat zayıf modeli boğuyor — kural takibi düşüyor (canlıda görüldü).
# Kısaltma yöntemi: HİÇBİR kural silinmedi; gerekçeler, tekrarlar ve vaka
# anlatıları çıkarıldı (onların yeri kod yorumları). Kurallar konu başlıkları
# altında toplandı; numaralı liste kalktı.
SISTEM_PROMPTU = """Sen Doğtaş Çevreyolu mobilya mağazasının WhatsApp/Instagram asistanısın.
Kısa, sıcak ve Türkçe konuş ("siz" diye hitap et): en fazla 3-4 cümle, az emoji.
Markdown işareti KULLANMA (**, ##, madde imi) — WhatsApp/Instagram göstermez.
Konu dışına girme (siyaset, başka markalar), kibarca mobilyaya dön.

ASLA OYALAMA CEVABI VERME. "Biraz bekleyin", "hemen kontrol ediyorum",
"bakıyorum", "birazdan dönerim" gibi cümleler KURMA — sonradan mesaj
gönderemezsin, müşteri cevapsız kalır. Gereken aracı ŞİMDİ çağır ve sonucu
AYNI cevapta ver; ulaşamıyorsan bilmediğini söyle, "yetkili" yazmasını öner.

FİYAT — EN KATI KURAL
- Fiyat ve ürün bilgisini YALNIZCA araçlardan al. Araç sonucu yoksa fiyat
  SÖYLEME; ürünü netleştir ya da "yetkili" yazmasını öner.
- Fiyatı araçtaki "fiyat_cumlesi"nden AYNEN kopyala: önce ürün adı kendi
  satırına, altına fiyat_cumlesi kaç satırsa o kadar satırıyla. Örnek:
    LUMERIS Köşe Takımı
    Liste Fiyatı: 66.661 TL
    İndirim: 12.665 TL
    İndirimli Fiyat: 53.996 TL
- Rakamları değiştirme/yuvarlama/yeniden hesaplama, satır ekleme/atlama.
  "Size şu kadar indirim yaptık" gibi süs cümlesi KURMA.
- Söylediğin her TL tutarı araç sonucunda birebir geçmeli. Birden fazla ürün
  listelerken her ürünün KENDİ fiyat_cumlesi'ni yaz, rakamları karıştırma.

MENÜ YOK — İNSANA YÖNLENDİRME
- Menü/kategori/buton yok; "menüye bak" DEME, yalnız metinle cevap ver.
- İnsana yönlendirmenin TEK yolu "yetkili" yazmasıdır; uygun anlarda bunu
  KENDİLİĞİNDEN hatırlat (müşteri bu seçeneği ancak senden duyar).
- "beni ara"/"geri arayalım" seçeneği YOK — önerme, numara/uygun saat SORMA.

MAĞAZA BİLGİSİ (adres, mesai, telefon, kargo, iade, garanti, taksit, montaj)
- YALNIZCA magaza_bilgi aracından al, kendi bilginden ASLA. "bulunamadi"
  dönerse bilmediğini söyle, yetkiliye iletildiğini belirt, "yetkili" öner.
- İSTİSNA — BAŞKA ŞEHİR/İLÇE: müşteri Batman dışı bir yer adı geçirip mağaza
  sorarsa ("Elazığ'da mağazanız var mı", "Van'a gönderiyor musunuz")
  "mağazamız yok" DEME, Batman adresini de cevap diye okuma — uzak diye
  vazgeçmesin. magaza_bilgi'yi "şube" ile çağır, gönderim/servis cevabını ver.
  Adres AÇIKÇA sorulursa ("neredesiniz") elbette Batman adresini ver.

ÜRÜN BULMA — HANGİ ARACI NE ZAMAN
- Müşteri adı yanlış yazabilir ("mariza") — arama araçlarıyla en yakınını bul.
- Aynı seri birden çok kategoride olabilir (VERMONT). koleksiyon_ara çok sonuç
  dönerse: mesajdan kategori belliyse seç, belli değilse fiyat vermeden SOR.
- kombinasyonlari_listele zaten toplam fiyatı döndürür; fiyat_detay'ı yalnız
  TEK kombinasyonun içeriği sorulunca çağır. Gereksiz araç çağırma.
- parca_ara: (a) tek ürün sorulmuşsa ("zigon sehpa", "berjer", "komodin"),
  (b) "sadece/tek başına" vurgusu varsa, (c) koleksiyon akışında BULAMADIYSAN —
  "bulamadım" demeden ÖNCE mutlaka dene. Yalnız sorulanın fiyatını ver, seti
  dayatma. Dönen adlar müşterinin yazdığından farklıysa hangisini kastettiğini
  SOR. Müşteri tüm odayı/seti soruyorsa bu aracı kullanma.
- en_uygun_ara: müşteri SERİ ADI vermeden genel tip söylerse ("çekyat",
  "koltuk", "2 tane çekyat", "çekyat kaç para"). Yetkiliye yönlendirme, "hangi
  model" diye takılma; dönen 2-3 seçeneği fiyatlarıyla listele, sonra tüm
  kataloğu tek mesajda dökemediğini söyleyip aklındaki seri adını sor. Seri adı
  verilmişse ("Calmera çekyat") bu aracı KULLANMA. Araç boşsa fiyat UYDURMA.
- GÖRSELDEN GELEN TARİF: mesajda "(görsel tarifi: <tip>)" geçiyorsa müşteri
  ürün adı YAZMAYAN bir fotoğraf göndermiş demektir. Fotoğraftaki ürünün hangi
  model olduğunu ASLA TAHMİN ETME, "bu CALMERA" gibi bir iddiada BULUNMA —
  bilemezsin. Bunun yerine en_uygun_ara'yı o tiple çağır, dönen 2-3 seçeneği
  fiyatlarıyla listele ve "fotoğraftakine benzer modellerimiz şunlar, bunlardan
  biri mi?" diye SOR. Araç boş dönerse ürün adını ya da hangi kategoride
  olduğunu sor. (Görselde ürün ADI okunduysa bu kural geçerli değil — normal
  akışla o adı ara.)
- teshir_bilgi: (a) müşteri mağazadaki/teşhirdeki üründen bahsederse,
  (b) mesajda "(teşhirdeki ürün)" geçerse, (c) ürünü katalogda bulamazsan ya da
  bulduğun kategori müşterinin dediğiyle uyuşmazsa — "bulamadım" demeden ÖNCE.
  Bunların DIŞINDA teşhir fiyatını kendiliğinden açma.
  Genel "teşhirde ne var" sorusunda ARGÜMANSIZ çağır: yalnız isimler döner
  (fiyatsız). İsimleri kategoriye göre grupla, RAKAM YAZMA, hangisinin fiyatını
  istediğini sor, "fiyatlarımızda cüzi pazarlık payımız var 😊" ekle. Belirli
  ürün istenince ad="<ürün adı>" ile çağır — fiyat ve pazarlık notu orada.

PAZARLIK
- DAVET: yalnız TEK bir ürün/kombinasyon fiyatı verdiğin cevabın sonuna BİR KEZ
  aynen şunu ekle: "Size özel bir fiyat çalışması yapmak isteriz. 😊"
  (değiştirme; müşteri pazarlığa başladıysa hiç ekleme). ÇOKLU listeye EKLEME —
  onun yerine hangisini istediğini SOR, seçince fiyatını verip daveti o cevaba ekle.
- Müşteri pazarlık ederse ("indirim olur mu", "son fiyat ne", "son ne olur",
  "kaça olur") ya da davetten sonra kısa olumlu dönerse ("olur", "evet"):
  ilgili aracı HER SEFERİNDE YENİDEN çağır (kombinasyon→fiyat_detay, tek
  ürün→parca_ara, teşhir→teshir_bilgi). pazarlik_notu'nun sonundaki "ADIM
  DURUMU" satırı hangi fiyatı teklif edeceğini hazır söyler — kendin sayaç
  tutma, ona uy. Her ısrarda yalnız BİR adım in; son fiyatın ALTINA ASLA inme.
  Müşterinin istediği rakam son fiyata eşit ya da üstündeyse KABUL ET.
  Ara fiyat verirken "son fiyat" DEME ("size ... TL yapabilirim" de).
- Geçmişte "indirim yapamıyorum" demiş olman ŞİMDİ de yapamayacağın anlamına
  GELMEZ — reddetmeden önce MUTLAKA aracı çağırıp ADIM DURUMU'na bak.
- ÜRÜN SABİT: pazarlık, konuşmada EN SON fiyat verilen ürün üzerinedir. Müşteri
  açıkça başka ürün adı yazmadıkça ürün DEĞİŞTİRME, başka ürün ARAMA, aynı
  serinin başka kombinasyonuna geçme; merdiven bitince de başka ürüne ATLAMA,
  aynı ürünün son fiyatını kibarca tekrarla. "en uygun olanın son fiyatı" gibi
  bir cümle YENİ ürün arama emri DEĞİLDİR — konuşulan üründe kal. Ürün
  belirtilmediyse: tek ürün fiyatı zaten verdiysen O üründe kal, vermediysen
  listedeki EN UCUZ (ilk) ürünü kastediyor say.
- pazarlik_notu YOKSA: önce o ürün için ilgili aracı ÇAĞIR. Bağlamda not
  görmemek TEK BAŞINA RET SEBEBİ DEĞİLDİR — liste araçları (en_uygun_ara,
  kombinasyonlari_listele) not taşımaz. Aracı çağırdın ve o da not
  döndürmediyse pazarlığı bırak, "yetkili" öner. Notta "DİKKAT" uyarısı varsa
  fiyat VERME — önce hangi ürünü kastettiğini sor.
- Kendiliğinden indirim önerme; merdiven ancak müşteri pazarlık edince işler.
- Müşteriye yazdığın cevapta "taban", "limit", "sistem", "merdiven", "adım",
  "ADIM DURUMU", "pazarlik_notu" gibi İÇ terimleri ASLA kullanma.

Mağazadaki kategoriler: {kategoriler}
"""

# ─── Tool tanımları (OpenAI/LiteLLM function calling formatı) ────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "koleksiyon_ara",
            "description": "Koleksiyon (ürün serisi) adıyla arama yapar. Müşteri bir "
                           "ürün/seri adı geçirdiğinde önce bunu çağır. Aynı ad birden "
                           "fazla kategoride olabilir — sonuçtaki 'kategori' alanına bak, "
                           "birden çok eşleşme varsa müşteriye hangisi olduğunu sor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Aranacak ad, örn. 'mariza'"},
                },
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kategorileri_listele",
            "description": "Mağazadaki ürün kategorilerini (id + ad) listeler.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "koleksiyonlari_listele",
            "description": "Bir kategorideki koleksiyonları listeler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kategori_id": {"type": "integer"},
                },
                "required": ["kategori_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kombinasyonlari_listele",
            "description": "Bir koleksiyonun kombinasyonlarını (takım seçenekleri) "
                           "toplam fiyat özetiyle listeler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "koleksiyon_id": {"type": "integer"},
                },
                "required": ["koleksiyon_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "magaza_bilgi",
            "description": "Mağaza hakkında operasyonel bilgi getirir: adres/konum, "
                           "mesai saatleri, telefon, kargo/teslimat, iade, garanti, "
                           "taksit, montaj vb. Müşteri mağazayla ilgili bir bilgi "
                           "sorduğunda MUTLAKA önce bunu çağır; cevabında YALNIZCA "
                           "buradan dönen bilgiyi kullan. 'bulunamadi' dönerse "
                           "bilmediğini söyle ve yetkiliye yönlendir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "soru": {"type": "string",
                             "description": "Müşterinin sorusu, örn. 'mağazanız nerede'"},
                },
                "required": ["soru"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "en_uygun_ara",
            "description": "Bir ürün TİPİNİN en uygun fiyatlı 2-3 seçeneğini "
                           "fiyatlarıyla getirir. Müşteri SERİ ADI vermeden genel "
                           "konuşuyorsa çağır: 'çekyat', 'kanepe', 'koltuk', "
                           "'üçlü koltuk', '2 tane çekyat', 'en ucuz koltuk ne "
                           "kadar' gibi. Müşteri belirli bir seri adı yazdıysa "
                           "(örn. 'Calmera koltuk') bunu KULLANMA — koleksiyon "
                           "akışını kullan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tip": {"type": "string",
                            "description": "Genel ürün tipi, örn. 'çekyat' ya da "
                                           "'üçlü koltuk'"},
                },
                "required": ["tip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "teshir_bilgi",
            "description": "Mağazada sergilenen (teşhirdeki) ürünler. Çağır: (a) müşteri "
                           "mağazadaki/teşhirdeki üründen bahsederse; (b) mesajda "
                           "'(teşhirdeki ürün)' ipucu varsa; (c) SON ÇARE — ürünü "
                           "normal katalogda bulamayınca ya da kategori uyuşmayınca, "
                           "pes etmeden önce teşhirde var mı diye bak. HİÇBİR argüman "
                           "vermezsen yalnız ürün İSİMLERİ döner (fiyatsız — genel "
                           "'teşhirde ne var' listesi için). Belirli bir ürünün "
                           "FİYATINI ve pazarlık tabanını almak için ad='<ürün adı>' "
                           "(ya da koleksiyon_id) geçir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "koleksiyon_id": {"type": "integer",
                                      "description": "Opsiyonel — koleksiyon_ara sonucundaki id"},
                    "ad": {"type": "string",
                           "description": "Opsiyonel — belirli bir teşhir ürününün adı "
                                          "(örn. 'LORENTA'). Verilirse yalnız o ürünün "
                                          "fiyatı+pazarlık tabanı döner."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fiyat_detay",
            "description": "Bir kombinasyonun fiyat detayını, içindeki ürünleri VE "
                           "pazarlık merdivenini (pazarlik_notu) verir. Müşteriye fiyat "
                           "söylemeden önce MUTLAKA bu (veya kombinasyonlari_listele) "
                           "çağrılmış olmalı. Müşteri bir kombinasyonda PAZARLIK "
                           "ederse de bunu çağır — pazarlık fiyatları buradan gelir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kombinasyon_id": {"type": "integer"},
                },
                "required": ["kombinasyon_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "parca_ara",
            "description": "TEK bir ürünün/parçanın (set/oda DEĞİL, tek parça) kendi "
                           "fiyatını ada göre verir. Müşteri tek bir ürün adı sorduğunda "
                           "('zigon sehpa', 'berjer', 'sadece 5 kapaklı dolap') — "
                           "'sadece/tek' demese bile — ya da sorduğu ürünü "
                           "koleksiyon/kombinasyon akışında bulamadığında çağır. "
                           "Ürün adını olabildiğince tam yaz. Tüm oda/set fiyatı için bunu "
                           "KULLANMA — koleksiyon/kombinasyon araçlarını kullan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string",
                          "description": "Parça adı, örn. 'legna 5 kapaklı dolap'"},
                },
                "required": ["q"],
            },
        },
    },
]


def _patron_mu(kullanici: str) -> bool:
    """Gönderen patron beyaz listesinde mi? (settings.BOT_PATRON_KIMLIKLER)

    Kimlik Meta tarafından doğrulanır (WA telefon / IG IGSID) — taklit
    edilemez. ŞU AN hiçbir akış çağırmıyor: Toptan satırı bot cevaplarından
    kaldırıldı (İsmail kararı 2026-07-12). Beyaz liste ve bu yardımcı,
    ileride patrona özel bir özellik gerekirse hazır dursun diye korunuyor
    (örn. toptan_dahil=_patron_mu(kullanici) ile tek satırda geri açılır).
    """
    return bool(kullanici) and kullanici in settings.BOT_PATRON_KIMLIKLER


def _tool_calistir(ad: str, argumanlar: dict,
                   platform: str = "", kullanici: str = ""):
    """Modelin istediği aracı gerçek veriyle çalıştır.

    NOT: Toptan satırı bot cevaplarından KALDIRILDI (İsmail kararı 2026-07-12;
    pazarlık merdiveni toptanı zaten içeride kullanıyor, ayrıca göstermek
    gürültüydü). Beyaz liste (_patron_mu) ve menu_veri'nin toptan_dahil
    altyapısı ileride gerekirse tek satırla geri açılmak üzere duruyor.
    """
    if ad == "koleksiyon_ara":
        return menu_veri.koleksiyon_ara(str(argumanlar.get("q", "")))
    if ad == "kategorileri_listele":
        return menu_veri.kategoriler()
    if ad == "koleksiyonlari_listele":
        return menu_veri.koleksiyonlar(int(argumanlar["kategori_id"]))
    if ad == "kombinasyonlari_listele":
        # Modele SADE görünüm ver: ham rakamlar yerine fiyat_cumlesi. Fiyat kalkanı
        # için gerçek tutarlar fiyat_cumlesi metninden okunur (uydurma tespiti korunur).
        sonuc = _ham_fiyat_gizle(menu_veri.kombinasyonlar(
            int(argumanlar["koleksiyon_id"])))
        if sonuc and len(sonuc.get("kombinasyonlar") or []) > 1:
            # Pazarlık daveti seçimden ÖNCE gitmesin (İsmail kararı 2026-07-12):
            # listede davet olunca pazarlığın hangi kombinasyon üzerinde
            # başlayacağı belirsiz kalıyor. Önce seçim, davet tek ürün cevabında.
            sonuc["not"] = ("Birden fazla kombinasyon listeliyorsun: cevabın "
                            "sonunda hangi kombinasyonu istediğini SOR. 'Size "
                            "özel bir fiyat çalışması' cümlesini BU cevaba "
                            "EKLEME — müşteri bir kombinasyon seçince ekle.")
        return sonuc
    if ad == "fiyat_detay":
        return _ham_fiyat_gizle(menu_veri.kombinasyon(
            int(argumanlar["kombinasyon_id"])))
    if ad == "parca_ara":
        # Tekil parça fiyatı: kayıtlarda yalnız fiyat_cumlesi var (ham rakam alanı yok).
        parcalar = menu_veri.urun_ara(str(argumanlar.get("q", "")))
        if not parcalar:
            return {"bulunamadi": True,
                    "not": "Bu parça bulunamadı — fiyat UYDURMA. Bilmediğini söyle, "
                           "'yetkili' yazmasını öner."}
        return {"parcalar": parcalar,
                "not": "Yalnız sorulan parçanın fiyat_cumlesi'ni AYNEN ver. Seti "
                       "kendiliğinden önerme. Birden çok eşleşme varsa ya da dönen "
                       "adlar müşterinin yazdığından farklıysa (arama yakın adları "
                       "da getirir) fiyat vermeden önce hangisini kastettiğini SOR."}
    if ad == "en_uygun_ara":
        urunler = menu_veri.en_uygun(str(argumanlar.get("tip", "")))
        if not urunler:
            return {"bulunamadi": True,
                    "not": "Bu tipte ürün bulunamadı — fiyat UYDURMA. Müşteriye "
                           "hangi ürünü aradığını sor ya da 'yetkili' yazmasını öner."}
        return {"urunler": urunler,
                "not": "En uygun fiyatlı seçenekler (ucuzdan pahalıya). Her ürünün "
                       "KENDİ fiyat_cumlesi'ni AYNEN yaz, rakamları karıştırma. "
                       "Bu ÇOKLU bir listedir: 'Size özel bir fiyat çalışması' "
                       "cümlesini EKLEME. Listeden sonra tüm kataloğu tek mesajda "
                       "dökemediğini kibarca söyle ve aklındaki seri/ürün adını sor. "
                       "PAZARLIK: burada pazarlik_notu YOK. Müşteri bundan sonra "
                       "son fiyat/indirim isterse REDDETME ve 'yetkili'ye yönlendirme; "
                       "bu aracı tekrar çağırma — ürünün ADIYLA parca_ara'yı çağır, "
                       "merdiven orada gelir. Ürün belirtilmediyse: konuşmada tek bir "
                       "ürünün fiyatını zaten verdiysen O üründe kal (ürün sabit), "
                       "vermediysen listedeki EN UCUZ (ilk) ürünü kastediyor say."}
    if ad == "teshir_bilgi":
        from catalog.services import teshir as teshir_servis
        kol = argumanlar.get("koleksiyon_id")
        urun_adi = (argumanlar.get("ad") or "").strip()
        kayitlar = teshir_servis.ajan_icin(int(kol) if kol else None, ad=urun_adi or None)
        if not kayitlar:
            return {"bulunamadi": True,
                    "not": "Teşhirde eşleşen kayıt yok — normal fiyat akışını kullan."}
        if kol or urun_adi:
            # Tekil ürün / pazarlık bağlamı. Modele LOOSE taban rakamı VERME —
            # canlıda 22.000 taban "İndirim: 22.000" oldu (model ayrı rakamı
            # fiyat_cumlesi satırına karıştırdı). Taban artık atomik pazarlik_notu
            # metni; ham int alanı (pazarlik_taban_fiyat) gizlenir. Pazarlık aralığı
            # (taban..İndirimli) fiyat kalkanı için ayrıca toplanır, modele GİTMEZ.
            gorunum = _ham_fiyat_gizle(kayitlar, ekstra=("pazarlik_taban_fiyat",))
            araliklar = []
            for ham, gk in zip(kayitlar, gorunum):
                taban = ham.get("pazarlik_taban_fiyat")
                perakende = ham.get("perakende_fiyat")
                if taban:
                    gk["pazarlik_notu"] = (
                        f"Müşteri ısrarla pazarlık ederse bu üründe en fazla "
                        f"{menu_veri._tl(taban)}'ye inebilirsin; ALTINA inme. "
                        f"Kendiliğinden indirim önerme.")
                    if perakende:
                        araliklar.append((int(taban), int(perakende)))
            return {"teshir": gorunum,
                    "pazarlik_kurali": "Fiyatı fiyat_cumlesi'nden AYNEN kopyala; rakam "
                                       "ekleme/yuvarlama YAPMA. Pazarlık için ilgili ürünün "
                                       "pazarlik_notu'na uy; notu olmayan üründe pazarlık yapma.",
                    "_pazarlik_araliklari": araliklar}
        # Genel liste (argümansız): SADECE isim + kategori — fiyat/indirim/taban/içerik
        # YOK. Model rakam göremediği için karıştıramaz/uyduramaz; kategoriye göre
        # gruplayıp fiyat sorulacak ürünü ad ile TEKRAR sordurur.
        isimler = [{"ad": k["ad"], "kategori": k.get("kategori", "")} for k in kayitlar]
        return {"teshir_isimleri": isimler,
                "not": "Bunlar teşhirdeki ürünlerin İSİMLERİ. Müşteriye SADECE isimleri, "
                       "KATEGORİYE GÖRE GRUPLAYARAK yaz — fiyat/indirim/rakam/içerik YAZMA. "
                       "Sonunda hangisinin fiyatını istediğini sor ve 'fiyatlarımızda cüzi "
                       "pazarlık payımız var' gibi kısa bir not ekle. Müşteri bir ürünün "
                       "fiyatını sorunca o ürünün adıyla teshir_bilgi'yi ad=... ile TEKRAR çağır."}
    if ad == "magaza_bilgi":
        soru = str(argumanlar.get("soru", ""))
        bilgiler = menu_veri.bilgi_ara(soru)
        if bilgiler:
            return {"bilgiler": bilgiler}
        # DB'de yok → soruyu İsmail'in cevaplaması için kaydet (panel: /app/bot/bilgi)
        menu_veri.soru_kaydet(platform, kullanici, soru)
        return {"bulunamadi": True,
                "not": "Bu bilgi kayıtlı değil. Müşteriye bilmediğini söyle, "
                       "yetkiliye iletildiğini belirt ve 'yetkili' yazmasını öner."}
    return {"hata": f"bilinmeyen araç: {ad}"}


# ─── Pazarlık kalkanı — kod seviyesi taban koruması ──────────────────────────
# Prompt tembihine rağmen model (özellikle lite zincir yedekleri) tabanın altında
# rakam uydurabiliyor (canlıda görüldü: taban 40.000 iken 38.000 teklif etti).
# Bu kalkan pazarlık bağlamındaki cevaplarda taban altı TL tutarını tabana yükseltir.
_PAZARLIK_IPUCLARI = ("son fiyat", "özel fiyat", "indirim", "pazarlık", "pazarlik",
                      "inemiyorum", "inemem", "bırak", "yapabilirim", "kampanya")
_TL_KALIBI = re.compile(r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})\s*TL\b", re.IGNORECASE)


def _pazarlik_kalkani(cevap: str, teshir_baglami: bool,
                      legit: set[int] = frozenset()) -> str:
    """Teşhir pazarlığı bağlamında taban altı fiyat teklifini tabana çek.

    YALNIZ bu turda teshir_bilgi aracı çağrıldıysa (gerçek pazarlık bağlamı)
    devreye girer. ÖNEMLİ: bağlam tespiti için mesaj metnini TARAMAZ — sistem
    promptu "TEŞHİR" kelimesini içerdiği için o yöntem normal katalog fiyat
    cevaplarında da tetikleniyor ve gerçek fiyatları (66.661/53.996) teşhir
    tabanına (70.000) yükseltip bozuyordu (canlıda görüldü). Sinyal artık
    aracın çağrılıp çağrılmadığı. Taban altı ama tabanın %60'ından büyük TL
    tutarları ilgili tabana yükseltilir; küçük tutarlar ("5.000 TL indirim") etkilenmez.

    legit: bu turda araçların döndürdüğü GERÇEK tutarlar — bunlara dokunma.
    Katalog pazarlık merdiveni fiyatları (2026-07-12) bir teşhir tabanının
    altında kalabilir; kalkan onları teşhir tabanına yükseltip bozmasın.
    """
    if not teshir_baglami:
        return cevap
    if not any(i in cevap.lower() for i in _PAZARLIK_IPUCLARI):
        return cevap
    if not _TL_KALIBI.search(cevap):
        return cevap
    try:
        from catalog.services import teshir as teshir_servis
        tabanlar = sorted({k["pazarlik_taban_fiyat"] for k in teshir_servis.ajan_icin()
                           if k.get("pazarlik_taban_fiyat")})
    except Exception:
        log.exception("ajan: pazarlık kalkanı taban okunamadı")
        return cevap
    if not tabanlar:
        return cevap

    def duzelt(m: re.Match) -> str:
        deger = int(re.sub(r"[.\s]", "", m.group(1)))
        if any(abs(deger - g) <= 1 for g in legit):
            return m.group(0)       # araçtan gelen gerçek tutar — dokunma
        for taban in tabanlar:      # küçükten büyüğe — en yakın üst taban
            if taban * 0.6 <= deger < taban:
                log.warning("ajan: pazarlık kalkanı — %s TL taban altı, %s TL yapıldı",
                            deger, taban)
                return f"{taban:,} TL".replace(",", ".")
        return m.group(0)

    return _TL_KALIBI.sub(duzelt, cevap)


# Müşteri bir İÇ LİMİT olduğunu duymamalı (kural 12/14: "sistem/taban/limit"
# deme). Prompt tembihine rağmen lite yedek model "sistemin izin verdiği son
# fiyat" diyebiliyor (canlıda görüldü) — bilinen kalıplar doğal söze çevrilir.
_SISTEM_KALIPLARI = (
    (re.compile(r"sistem\w*\s+izin\s+verdiği", re.IGNORECASE), "size özel"),
    (re.compile(r"sistem\w*\s+(mevcut\s+)?fiyatland\w+\s+kurallar\w*\s+gereği",
                re.IGNORECASE), "mağaza politikamız gereği"),
    # canlıda görüldü: "sistemin bana tanımladığı son fiyat merdivenini tamamladık"
    (re.compile(r"sistem\w*\s+(bana\s+)?tanımlad\w+\s+son\s+fiyat\s+merdiven\w+\s+"
                r"tamamlad\w+", re.IGNORECASE), "size sunabileceğim son fiyata ulaştık"),
    (re.compile(r"(son\s+)?fiyat\s+merdiven\w+", re.IGNORECASE), "son fiyat"),
)


def _sistem_sozu_temizle(cevap: str) -> str:
    for kalip, yerine in _SISTEM_KALIPLARI:
        cevap = kalip.sub(yerine, cevap)
    return cevap


# ─── Pazarlık daveti yeri ────────────────────────────────────────────────────
# Davet cümlesi yalnız TEK ürünün fiyatı verilen cevaba eklenir (İsmail kararı
# 2026-07-12): birden çok kombinasyon listelenen cevapta davet olursa pazarlık
# hangi ürün üzerinde başlayacağı belirsiz kalıyor — önce seçim sorulmalı.
# Prompt kuralı (14) + araç notu modele bunu söyler; model unutursa bu süzgeç
# cümleyi liste cevabından düşürür ve soru yoksa seçim sorusu ekler.
_DAVET_KALIBI = re.compile(
    r"[ \t]*Size özel bir fiyat çalışması yapmak isteriz\.?\s*(?:😊\s*)?",
    re.IGNORECASE)
# fiyat_cumlesi blokları: indirimli üç satırlık biçim "İndirimli Fiyat:" ile,
# indirimsiz tek satır "Fiyatı:" ile biter ("Liste Fiyatı:" sayılmaz).
_FIYAT_BLOK_KALIBI = re.compile(r"İndirimli Fiyat:|(?<!Liste )Fiyatı:")


def _davet_yeri_duzelt(cevap: str) -> str:
    if len(_FIYAT_BLOK_KALIBI.findall(cevap)) < 2:
        return cevap
    if not _DAVET_KALIBI.search(cevap):
        return cevap
    cevap = _DAVET_KALIBI.sub("", cevap).strip()
    if "?" not in cevap:
        cevap += "\n\nHangi kombinasyon ilginizi çeker? 😊"
    return cevap


# ─── Fiyat kalkanı — uydurma fiyat koruması ──────────────────────────────────
# Model, araçtan gelen gerçek fiyatı cümleye çevirirken rakamı bozabiliyor
# (canlıda görüldü: 66.661/53.996 → 70.000/70.000). fiyat_cumlesi verbatim
# kopyalama bunu büyük ölçüde önler; bu kalkan son emniyet: cevaptaki her TL
# tutarı bu turda araçların döndürdüğü GERÇEK fiyatlardan biri değilse uydurma
# var demektir → bir kez düzelttir, yine uyduruyorsa menüye düş (yasal risk:
# müşteriye asla sahte fiyat/indirim gönderme). Teşhir pazarlığında ara fiyat
# meşru olduğundan bu kalkan devre dışı — orada _pazarlik_kalkani taban korur.
_FIYAT_KALIBI = re.compile(r"(\d{1,3}(?:[.\s]\d{3})+|\d{4,7})\s*TL", re.IGNORECASE)
_FIYAT_ANAHTARLARI = ("toplam_liste", "toplam_perakende", "liste_fiyat",
                      "perakende_fiyat", "pazarlik_taban_fiyat", "fiyat")


def _fiyatlari_topla(sonuc, kume: set[int]) -> None:
    """Araç sonucundaki gerçek fiyat tutarlarını (+ liste−perakende farkını) topla."""
    if isinstance(sonuc, dict):
        for anahtar in _FIYAT_ANAHTARLARI:
            v = sonuc.get(anahtar)
            if isinstance(v, (int, float)):
                kume.add(round(v))
        liste = sonuc.get("toplam_liste") or sonuc.get("liste_fiyat")
        perakende = sonuc.get("toplam_perakende") or sonuc.get("perakende_fiyat")
        if isinstance(liste, (int, float)) and isinstance(perakende, (int, float)):
            kume.add(round(liste) - round(perakende))
            kume.add(round(liste - perakende))
        for v in sonuc.values():
            _fiyatlari_topla(v, kume)
    elif isinstance(sonuc, list):
        for v in sonuc:
            _fiyatlari_topla(v, kume)
    elif isinstance(sonuc, str):
        # Metin alanlarındaki TL tutarları da meşru (örn. magaza_bilgi: "kargo 500 TL").
        for m in _FIYAT_KALIBI.finditer(sonuc):
            kume.add(int(re.sub(r"[.\s]", "", m.group(1))))


def _fiyat_uydurma_var_mi(cevap: str, legit: set[int],
                          araliklar: list[tuple[int, int]] = ()) -> bool:
    """Cevaptaki bir TL tutarı meşru değilse True.

    Meşru = (a) gerçek fiyat kümesindeki bir değere ±1 eşit, YA DA (b) bir teşhir
    pazarlık aralığı [taban, İndirimli] içinde. (b) sayesinde pazarlıkta ara fiyat
    (örn. taban 22.000 ile İndirimli 25.000 arasında 23.500) meşru sayılır; ama
    aralık DIŞI uydurma (55.000, 33.000) yakalanır — kalkan teşhirde de açık kalır.
    """
    for m in _FIYAT_KALIBI.finditer(cevap):
        deger = int(re.sub(r"[.\s]", "", m.group(1)))
        if any(abs(deger - g) <= 1 for g in legit):
            continue
        if any(lo <= deger <= hi for lo, hi in araliklar):
            continue
        return True
    return False


# ── Pazarlık adım takibi — merdivende nerede kaldık, KOD söyler ──────────────
# Geçmişteki bot fiyatları modele redakte gösterilir ("(güncel fiyat)") — model
# kaldığı adımı bilemiyordu (canlıda görüldü: yer tutucuyu aynen okudu, fiyat
# düşmedi). bot_mesaj tam metni redaksiyonsuz sakladığı için verilen teklifler
# oradan KESİN tespit edilir; nota hazır "ŞİMDİ şunu teklif et" satırı eklenir.
_MERDIVEN_GIDEN_LIMIT = 12   # taranacak son giden mesaj sayısı (pazarlık oturumu kısa)

# Müşterinin mesajı pazarlık isteği mi? (araçsız pazarlık cevabı yasağı için)
# Canlı vaka (2026-07-28, 904882180424): müşteri 6 kez son fiyat sordu, bunların
# 4'ü hiçbir kalıba UYMADI ("en son ne olur", "son fiystı" (yazım hatası),
# "son ne olur söyler misin", "işte son ne olur") → araçsız-pazarlık zorlaması
# hiç devreye girmedi. "son fiyat" yerine "son fiy" (yazım hatasını da yakalar)
# ve "son ne"/"en son" kalıpları eklendi.
_PAZARLIK_ISTEK_KALIPLARI = ("indirim", "pazarl", "son fiy", "olmaz mı", "olmaz mi",
                             "biraz daha", "daha in", "daha düş", "daha dus",
                             "kaça olur", "kaca olur", "kaça verirsin", "ucuz",
                             "bırak", "birak", "son ne", "en son", "son kaç",
                             "son kac", "net fiyat", "netini", "kaç yapar",
                             "kac yapar", "en aşağı", "en asagi", "son teklif")


def _pazarlik_istegi_mi(metin: str) -> bool:
    low = (metin or "").lower()
    return any(k in low for k in _PAZARLIK_ISTEK_KALIPLARI)


# Davet cümlesinin değişmez çekirdeği (menü şablonu ve AI cevabı aynı cümleyi
# kullanır: "Size özel bir fiyat çalışması yapmak isteriz. 😊").
_DAVET_ISARETI = "fiyat çalışması yapmak isteriz"
_DAVET_ONAY_KELIMELERI = ("evet", "olur", "tamam", "olabilir", "uygun",
                          "isterim", "yapalım", "yapalim")


def _davete_olumlu_mu(metin: str, platform: str, kullanici: str) -> bool:
    """Bot az önce pazarlık daveti gönderdi ve müşteri kısa olumlu mu döndü?

    "olur"/"evet" pazarlık kalıbı içermez ama davetin hemen ardından pazarlık
    BAŞLANGICIDIR — araçsız cevap yasağından geçmeli ki model fiyat_detay
    çağırıp merdivenin ilk adımını teklif etsin (menüden gelen akışta müşteri
    başka hiçbir pazarlık kelimesi yazmadan bu noktaya ulaşır)."""
    m = (metin or "").strip().lower()
    if not m or len(m) > 24 or not any(k in m for k in _DAVET_ONAY_KELIMELERI):
        return False
    for yon, mt in _son_mesajlar(platform, kullanici):
        if yon == "giden":                       # en yeni giden mesaj
            return _DAVET_ISARETI in mt
    return False


def _son_mesajlar(platform: str, kullanici: str) -> list[tuple[str, str]]:
    """Son konuşma satırları (yon, TAM metin — redaksiyonsuz).

    İki iş görür: giden'lerden verilen pazarlık teklifleri tespit edilir
    (adım takibi), gelen+giden bütününden pazarlık edilen ÜRÜN doğrulanır
    (model çıplak "indirim olur mu" mesajında alakasız ürüne atlayabiliyor —
    canlıda görüldü: Milena pazarlığı LEGNA fiyatına sıçradı).

    Yalnız son BOT_PAZARLIK_HAFIZA_SAAT saat taranır (İsmail kararı: 24):
    süre içinde merdiven kaldığı yerden sürer, dolunca aynı müşteriye
    pazarlık 1. adımdan yeniden başlar ("kampanya güncellendi" davranışı).
    """
    if not (platform and kullanici):
        return []
    try:
        from datetime import datetime, timedelta, timezone
        esik = datetime.now(timezone.utc) - timedelta(
            hours=settings.BOT_PAZARLIK_HAFIZA_SAAT)
        session = SessionLocal()
        try:
            rows = session.scalars(
                select(BotMesaj)
                .where(BotMesaj.platform == platform,
                       BotMesaj.kullanici == kullanici,
                       BotMesaj.olusturma >= esik)
                .order_by(BotMesaj.id.desc())
                .limit(_MERDIVEN_GIDEN_LIMIT * 2)
            ).all()
        finally:
            session.close()
        return [(r.yon, r.metin or "") for r in rows]
    except Exception:
        log.exception("ajan: pazarlık adım geçmişi okunamadı")
        return []


def _adim_notu(merdiven: list[int], gidenler: list[str]) -> str:
    """Merdiven adım durumu — pazarlik_notu sonuna eklenecek hazır talimat."""
    blob = "\n".join(gidenler)
    verilen_idx = -1
    for i, tutar in enumerate(merdiven):
        # "13.000 TL" biçimiyle ara; önünde rakam/nokta olmasın (113.000 ≠ 13.000).
        kalip = r"(?<![\d.])" + re.escape(menu_veri._tl(tutar)[:-3]).rstrip() + r"\s*TL"
        if re.search(kalip, blob):
            verilen_idx = max(verilen_idx, i)
    if verilen_idx < 0:
        return (f" ADIM DURUMU: henüz pazarlık teklifi verilmedi — müşteri pazarlık "
                f"ederse İLK teklifin {menu_veri._tl(merdiven[0])} olsun.")
    if verilen_idx + 1 < len(merdiven):
        siradaki = merdiven[verilen_idx + 1]
        son_mu = " (bu merdivenin SON fiyatı — sonrasında daha fazla inme)" \
            if verilen_idx + 1 == len(merdiven) - 1 else ""
        return (f" ADIM DURUMU: daha önce {menu_veri._tl(merdiven[verilen_idx])} teklif "
                f"edildi — müşteri yine pazarlık ederse ŞİMDİ {menu_veri._tl(siradaki)} "
                f"teklif et{son_mu}.")
    return (f" ADIM DURUMU: merdiven bitti — {menu_veri._tl(merdiven[-1])} SON fiyattır; "
            f"daha fazla inme, kibarca son fiyatın bu olduğunu söyle.")


# Ürün adlarında hemen her üründe geçen jenerik kelimeler — ürünü AYIRT ETMEZLER.
# Seri adı ("LOFT", "MARLIN", "CALMERA") ayırt edicidir; pazarlık kontrolünde
# ürünün gerçekten konuşulduğu ancak ayırt edici kelimeyle anlaşılır.
_JENERIK_URUN_KELIMELERI = frozenset((
    "koltuk", "uclu", "ikili", "tekli", "dortlu", "yatakli", "sandikli",
    "sehpali", "sehpa", "berjer", "kose", "takim", "takimi", "oda", "odasi",
    "grubu", "grup", "yemek", "yatak", "genc", "cocuk", "mutfak", "bahce",
    "plus", "line", "kollu", "kolsuz", "acili", "modul", "moduler", "set",
    "seti", "sol", "sag", "kapakli", "karyola", "baza", "baslik",
))


def _urun_konusuldu_mu(kayit: dict, konusma_duz: str) -> bool:
    """Pazarlık edilen ürün/kombinasyon son konuşmalarda gerçekten geçti mi?

    Model çıplak "indirim olur mu" mesajında alakasız kayda atlayabiliyor
    (canlıda üç kez görüldü: Milena pazarlığı LEGNA'ya, sonra AYNI serinin
    başka kombinasyonuna — 6 Kapaklı Baza pazarlığı "Dörtlü, Üçlü, Kiera"
    oturma grubuna — sıçradı; fiyat 89.400'den 112.100'e "yükseldi").
    Yalnız seri adına bakmak yetmedi; artık koleksiyon adı + kayıt adının
    anlamlı kelimeleri aranır ve ÇOĞUNLUĞU konuşmada geçmelidir. Geçmiyorsa
    nota DİKKAT düşülür — model fiyat vermek yerine ürünü netleştirir.
    """
    tam_ad = f"{(kayit.get('koleksiyon') or {}).get('ad') or ''} {kayit.get('ad') or ''}"
    kelimeler = [k for k in re.split(r"[^0-9a-zçğıöşü]+", menu_veri._duz(tam_ad))
                 if len(k) >= 3 or (k.isdigit() and len(k) >= 2)]
    if not kelimeler:      # ayırt edici kelime yok — kontrolü atla
        return True
    # SERİ ADI ŞARTI (2026-07-28 canlı vakası): "LOFT Üçlü Koltuk" için "üçlü"
    # ve "koltuk" konuşmada geçtiğinden çoğunluk testi geçiyordu, seri adı LOFT
    # hiç geçmemesine rağmen — bot müşteriye HİÇ göstermediği ürüne pazarlık
    # fiyatı verdi. Jenerik mobilya kelimeleri ürünü ayırt etmez; adda ayırt
    # edici bir kelime varsa en az biri konuşmada geçmeli.
    ayirt_edici = [k for k in kelimeler if k not in _JENERIK_URUN_KELIMELERI]
    if ayirt_edici and not any(k in konusma_duz for k in ayirt_edici):
        return False
    bulunan = sum(1 for k in kelimeler if k in konusma_duz)
    return bulunan * 2 >= len(kelimeler)   # en az yarısı konuşmada geçmeli


def _merdiven_isle(sonuc, gidenler: list[str], konusma_duz: str) -> None:
    """Araç sonucundaki _merdiven alanlarını düşür, adım durumunu nota işle.

    _merdiven modele GİTMEZ (ham basamak listesi); pazarlik_notu'na eklenen
    ADIM DURUMU cümlesiyle model yalnız söyleneni uygular — sayaç tutmaz.
    Ürün son konuşmalarda hiç geçmediyse DİKKAT uyarısı eklenir (yanlış
    ürüne pazarlık fiyatı verilmesin).
    """
    if isinstance(sonuc, dict):
        merdiven = sonuc.pop("_merdiven", None)
        if merdiven and sonuc.get("pazarlik_notu"):
            if _urun_konusuldu_mu(sonuc, konusma_duz):
                sonuc["pazarlik_notu"] += _adim_notu(list(merdiven), gidenler)
            else:
                # Konuşulmamış ürün: uyarı YETMİYOR (2026-07-28 canlı denemesi —
                # kota yüzünden devreye giren zayıf yedek model DİKKAT'i
                # görmezden gelip LOFT'a 19.200 TL teklif etti). Merdiven
                # RAKAMLARINI hiç verme: model görmediği rakamı teklif edemez,
                # uydurursa fiyat kalkanı yakalar. Liste fiyatı (fiyat_cumlesi)
                # yerinde kalır — ürünü tanıtmak serbest, indirim vermek değil.
                sonuc["pazarlik_notu"] = (
                    "DİKKAT: bu ürün müşteriyle konuşulan ürün DEĞİL. Bu üründe "
                    "pazarlık/indirim fiyatı VERME, rakam teklif etme; önce "
                    "hangi ürün için fiyat istediğini müşteriye SOR.")
        for v in sonuc.values():
            _merdiven_isle(v, gidenler, konusma_duz)
    elif isinstance(sonuc, list):
        for v in sonuc:
            _merdiven_isle(v, gidenler, konusma_duz)


# OYALAMA CEVABI — model araç çağırmak yerine "bakıyorum" deyip susuyor.
# Canlı vaka (2026-07-28, 904882180424): "milena tv 180 fiyatı nedir?" →
# "Biraz bekleyin lütfen, hemen kontrol ediyorum." ve devamı HİÇ gelmedi.
# Müşteri cevapsız kalıyor; İsmail'in "fiyat almak neden zor" şikâyeti buydu.
# Bot tek atımlıktır: sonraki mesajı müşteri yazmadıkça devam edemez, bu yüzden
# "birazdan dönerim" demek = cevap vermemek.
_OYALAMA_KALIPLARI = (
    "bekleyin", "bekleyiniz", "birazdan", "az sonra", "hemen kontrol",
    "kontrol ediyorum", "kontrol edeyim", "bakıyorum", "bakayım",
    "araştırıyorum", "iletiyorum size", "dönüş yapacağım", "dönüş yaparım",
    "size döneceğim", "hazırlıyorum", "birkaç dakika",
)


def _oyalama_mi(cevap: str) -> bool:
    """Cevap 'şimdi bakıyorum' türü bir oyalama mı? (rakam/fiyat vermeden)"""
    d = menu_veri._duz(cevap or "")
    if not d:
        return False
    # İçinde gerçek fiyat satırı varsa oyalama değildir (bilgi verilmiş).
    if "fiyat" in d and any(ch.isdigit() for ch in d):
        return False
    return any(menu_veri._duz(k) in d for k in _OYALAMA_KALIPLARI)


# Modele giden görünümden çıkarılan ham fiyat alanları. Model bu ayrı rakamları
# (liste/perakende/indirim/taban) yeniden cümleye çevirirken — özellikle çok
# ürünlü teşhir listesinde — birbirine karıştırıyor (canlıda görüldü: 9 üründe
# fiyatlar ve tabanlar birbirine geçti). Yalnız atomik fiyat_cumlesi bırakınca
# modelin kopyalamaktan başka seçeneği kalmaz; şablona rakam sokamaz.
_HAM_FIYAT_ALANLARI = ("toplam_liste", "toplam_perakende", "indirim_yuzde",
                       "liste_fiyat", "perakende_fiyat")


def _ham_fiyat_gizle(obj, ekstra: tuple = ()):
    """obj içindeki ham fiyat rakamı alanlarını (fiyat_cumlesi HARİÇ) recursive çıkar."""
    gizli = set(_HAM_FIYAT_ALANLARI) | set(ekstra)
    if isinstance(obj, dict):
        return {k: _ham_fiyat_gizle(v, ekstra) for k, v in obj.items() if k not in gizli}
    if isinstance(obj, list):
        return [_ham_fiyat_gizle(v, ekstra) for v in obj]
    return obj


def _gecmis(platform: str, kullanici: str, guncel_metin: str) -> list[dict]:
    """bot_mesaj'dan son konuşmaları user/assistant rollerine çevir.

    Menü payload'ları ve uzun menü metinleri atlanır (bağlamı şişirir);
    yalnız serbest metinler alınır. Güncel gelen mesaj (webhook az önce
    kaydettiği için) listeden düşülür — modele ayrıca verilecek.
    """
    try:
        session = SessionLocal()
        try:
            rows = session.scalars(
                select(BotMesaj)
                .where(BotMesaj.platform == platform, BotMesaj.kullanici == kullanici)
                .order_by(BotMesaj.id.desc())
                .limit(settings.AJAN_GECMIS_LIMIT * 2)
            ).all()
        finally:
            session.close()
    except Exception:
        log.exception("ajan: geçmiş okunamadı (%s/%s)", platform, kullanici)
        return []

    rows = list(reversed(rows))
    # Az önce kaydedilen güncel mesajı düş (en sondaki 'gelen' aynı metinse).
    if rows and rows[-1].yon == "gelen" and (rows[-1].metin or "").strip() == guncel_metin.strip():
        rows = rows[:-1]

    mesajlar: list[dict] = []
    for r in rows:
        metin = (r.metin or "").strip()
        if "[menü]" in metin and KOMBI_ONAY_SORUSU in metin:
            # IG'de kombinasyon detayı quick reply ile gider ("[menü]" etiketi
            # alır) ama bağlam için kritiktir: müşterinin menüden HANGİ
            # kombinasyonu seçtiğini model ancak buradan öğrenir. Atlamak
            # yerine etiketi temizleyip tut.
            metin = metin.replace("[menü]", "").strip()
        elif not metin or metin.startswith("[buton]") or "[menü]" in metin \
                or metin.startswith("[kart") or metin.startswith("[sohbeti") \
                or metin.startswith("[ses —") or metin.startswith("[görsel —"):
            continue
        if metin.startswith("[ses] "):     # transkript: işareti at, içeriği kullan
            metin = metin[len("[ses] "):]
        if metin.startswith("[görsel] "):  # OCR sonucu: işareti at, içeriği kullan
            metin = metin[len("[görsel] "):]
        rol = "user" if r.yon == "gelen" else "assistant"
        if rol == "assistant":
            # Geçmişteki fiyat rakamlarını RedAKTe et: eski/yanlış bir fiyat
            # (canlıda görüldü: bozuk 70.000) sonraki turda modeli yanıltıp
            # tekrar ettiriyordu. Rakamı silince model fiyatı aracı yeniden
            # çağırarak taze almak zorunda kalır — poison zinciri kırılır.
            metin = _FIYAT_KALIBI.sub("(güncel fiyat)", metin)
        mesajlar.append({"role": rol, "content": metin[:400]})
    return mesajlar[-settings.AJAN_GECMIS_LIMIT:]


def cevapla(metin: str, platform: str, kullanici: str,
            gecmissiz: bool = False) -> str | None:
    """Serbest metne AI cevabı üret. Ajan kapalıysa/hata olursa None (→ menüye düş).

    Model zinciri: settings.AJAN_MODELLER soldan denenir. Kota (429) ya da başka
    hata alan model atlanır, sıradaki denenir — her Gemini modelinin ücretsiz
    kotası ayrı sayıldığı için zincir kota direncini katlar.

    gecmissiz=True: konuşma geçmişini bağlama ALMA (yorumdan-DM gibi, tetiğin
    kendisi tek başına yeterli bağlamı taşıdığı durumlar için — eski konuşma
    yanlış ürünü ele geçirmesin).
    """
    global SON_HATA
    if not settings.AJAN_AKTIF:
        return None
    from datetime import datetime
    from time import monotonic
    from bot import kota as kota_modul
    if kota_modul.hepsi_kapali_mi(settings.AJAN_MODELLER):
        kota_modul.kapalilari_ac()   # son çare: susmaktansa bir tur daha dene
    for model in settings.AJAN_MODELLER:
        if kota_modul.kapali_mi(model):
            continue                 # günlük kotası dolmuş, boşuna deneme
        basla = monotonic()
        try:
            cevap = _cevapla(metin, platform, kullanici, model, gecmissiz=gecmissiz)
        except Exception as e:
            _sayac(model, "kota" if _kota_mu(e) else "hata")
            if _kota_mu(e):
                # Google günlük limit tablosunu artık yayımlamıyor; gerçek
                # sayıyı yalnız 429 gövdesinden öğrenebiliyoruz — sakla.
                kota_modul.limiti_ogren(model, e)
                kota_modul.kapat(model, e)   # günlükse bugünlük atla
            SON_HATA = f"{datetime.now():%H:%M:%S} [{model}] {type(e).__name__}: {str(e)[:200]}"
            log.warning("ajan: %s başarısız (%s%s), sıradaki model deneniyor",
                        model, type(e).__name__, " — KOTA" if _kota_mu(e) else "")
            continue
        _sayac(model, "basari" if cevap else "bos")
        if model != settings.AJAN_MODELLER[0]:
            # Yedek model devrede = birincil Gemini kotası dolmuş/hatalı demek;
            # sıklaşırsa /saglik'taki ajan_model_sayac ile teyit et.
            log.warning("ajan: YEDEK model %s cevapladı (birincil düştü)", model)
        log.info("ajan: %s %.1fs'de %s (%s)", model, monotonic() - basla,
                 "cevapladı" if cevap else "boş döndü (kalkan/tur limiti)", platform)
        return cevap
    log.error("ajan: tüm modeller başarısız, menüye düşülüyor")
    return None


def _cevapla(metin: str, platform: str, kullanici: str, model: str,
             gecmissiz: bool = False) -> str | None:
    global SON_HATA
    import litellm
    from datetime import datetime
    litellm.suppress_debug_info = True

    kategoriler = ", ".join(f"{k['ad']} (id:{k['id']})" for k in menu_veri.kategoriler())
    gecmis = [] if gecmissiz else _gecmis(platform, kullanici, metin)
    mesajlar = [
        {"role": "system", "content": SISTEM_PROMPTU.format(kategoriler=kategoriler)},
        *gecmis,
        {"role": "user", "content": metin[:1000]},
    ]

    # Bu turda meşru sayılan TL tutarları: araçların döndürdüğü fiyatlar +
    # müşterinin KENDİ yazdığı tutarlar (kendi bütçesini tekrar etmek uydurma değil).
    legit_fiyatlar: set[int] = set()
    for _m in _FIYAT_KALIBI.finditer(metin):
        legit_fiyatlar.add(int(re.sub(r"[.\s]", "", _m.group(1))))
    teshir_cagrildi = False            # teşhir pazarlığında _pazarlik_kalkani sinyali
    pazarlik_araliklari: list[tuple[int, int]] = []   # [taban, İndirimli] — ara fiyat meşru
    duzeltme_denendi = False           # uydurma fiyat için tek düzeltme hakkı
    arac_cagrildi = False              # bu istekte en az bir araç çalıştı mı
    pazarlik_zorlandi = False          # araçsız pazarlık cevabına tek zorlama hakkı
    oyalama_zorlandi = False           # "bekleyin, bakıyorum" cevabına tek zorlama hakkı
    # Pazarlık niyeti: açık kalıp ("indirim olur mu") YA DA az önce gönderilen
    # davete kısa olumlu dönüş ("olur", "evet" — menü akışından gelen müşteri).
    pazarlik_niyeti = _pazarlik_istegi_mi(metin) or _davete_olumlu_mu(
        metin, platform, kullanici)

    for _ in range(MAKS_TOOL_TURU):
        yanit = litellm.completion(
            model=model,
            messages=mesajlar,
            tools=TOOLS,
            max_tokens=600,
            timeout=15,
        )
        secim = yanit.choices[0].message

        if not getattr(secim, "tool_calls", None):
            cevap = (secim.content or "").strip()
            # Pazarlık isteğine ARAÇSIZ cevap yasak: geçmişteki (redakte) ret
            # cevapları modeli araç çağırmadan "indirim yapamıyorum" demeye
            # itiyor (canlıda görüldü) — merdivende adım varken pazarlık ölüyor.
            # ADIM DURUMU'nu görmeden karar veremez; bir kez araca zorla.
            if (cevap and pazarlik_niyeti and not arac_cagrildi
                    and not pazarlik_zorlandi):
                pazarlik_zorlandi = True
                mesajlar.append({"role": "assistant", "content": cevap})
                mesajlar.append({"role": "user", "content":
                    "DUR: Müşteri pazarlık istiyor. Araç çağırmadan pazarlık "
                    "cevabı verme (geçmişteki eski cevaplarına da güvenme). "
                    "Önce ilgili ürünün fiyat_detay (kombinasyon) ya da "
                    "parca_ara (tek parça) aracını çağır; pazarlik_notu'nun "
                    "sonundaki ADIM DURUMU satırı ne diyorsa AYNEN onu yap — "
                    "teklif edilecek fiyat orada hazır yazıyor."})
                continue
            # Oyalama cevabı ("hemen kontrol ediyorum") = cevapsız müşteri:
            # bot tek atımlıktır, sonraki mesajı kendi gönderemez. Bir kez zorla.
            if cevap and not oyalama_zorlandi and _oyalama_mi(cevap):
                oyalama_zorlandi = True
                mesajlar.append({"role": "assistant", "content": cevap})
                mesajlar.append({"role": "user", "content":
                    "DUR: 'bekleyin/kontrol ediyorum/birazdan' gibi oyalama "
                    "cevabı VERME — sonradan mesaj gönderemezsin, müşteri "
                    "cevapsız kalır. Gereken aracı ŞİMDİ çağır ve sonucu bu "
                    "cevapta ver. Bilgiye ulaşamıyorsan bilmediğini söyle ve "
                    "'yetkili' yazmasını öner."})
                continue
            if cevap:
                cevap = _davet_yeri_duzelt(_sistem_sozu_temizle(
                    _pazarlik_kalkani(cevap, teshir_cagrildi, legit=legit_fiyatlar)))
            # Fiyat kalkanı (teşhir DAHİL, artık her zaman açık): cevaptaki bir TL
            # tutarı ne araçların döndürdüğü gerçek fiyat, ne müşterinin yazdığı
            # tutar, ne de bir teşhir pazarlık aralığı [taban, İndirimli] içindeyse
            # UYDURMA demektir — teşhirde hallüsine fiyat (55.000/33.000) buradan
            # yakalanır; meşru ara pazarlık fiyatı aralık sayesinde geçer. Araç hiç
            # çağrılmadan yazılan fiyat da düşer. Bir kez düzelttir; ısrarla
            # uyduruyorsa menüye düş — müşteriye asla sahte fiyat gönderme.
            # "(güncel fiyat)" geçmiş REDAKSİYON yer tutucusudur — model onu
            # cevaba kopyalarsa müşteri fiyatsız saçma cümle görür (canlıda
            # görüldü: "son fiyatımız (güncel fiyat) şeklindedir"). Uydurma
            # fiyatla aynı düzeltme hakkını kullanır.
            yer_tutucu = bool(cevap) and "güncel fiyat)" in cevap
            if cevap and (yer_tutucu
                          or _fiyat_uydurma_var_mi(cevap, legit_fiyatlar,
                                                   pazarlik_araliklari)):
                if not duzeltme_denendi:
                    duzeltme_denendi = True
                    mesajlar.append({"role": "assistant", "content": cevap})
                    mesajlar.append({"role": "user", "content":
                        "DUR: Cevabındaki fiyat/tutar araç sonucundaki gerçek "
                        "verilerle uyuşmuyor (ya da hiç araç çağırmadan rakam "
                        "yazdın). '(güncel fiyat)' gibi YER TUTUCU metinleri de "
                        "ASLA yazma — o, geçmişteki eski fiyatın maskesidir. "
                        "Fiyatı YALNIZCA ilgili aracı çağırıp araç "
                        "sonucundaki fiyat_cumlesi'nden (pazarlıkta pazarlik_notu "
                        "ADIM DURUMU satırından), rakamları hiç değiştirmeden "
                        "AYNEN al. Şimdi doğru aracı çağırıp gerçek fiyatı ver."})
                    continue
                SON_HATA = (f"{datetime.now():%H:%M:%S} FiyatUydurma: "
                            f"model gerçek fiyatı yazmadı")
                log.warning("ajan: fiyat kalkanı — uydurma/yer tutucu, menüye düşülüyor")
                return None
            if not cevap:
                return None
            return cevap[:MAKS_CEVAP_KR]

        # Modelin istediği araçları çalıştır, sonuçları konuşmaya ekle.
        arac_cagrildi = True
        mesajlar.append(secim.model_dump())
        for tc in secim.tool_calls:
            try:
                argumanlar = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                argumanlar = {}
            try:
                sonuc = _tool_calistir(tc.function.name, argumanlar,
                                       platform=platform, kullanici=kullanici)
            except Exception:
                log.exception("ajan: araç hatası %s(%s)", tc.function.name, argumanlar)
                sonuc = {"hata": "veri okunamadı"}
            # Fiyat kalkanı yalnız BELİRLİ teşhir sorgusunda (kol/ad = fiyat+pazarlık
            # bağlamı) devre dışı kalsın. Argümansız isim listesinde fiyat yoktur;
            # kalkan açık kalsın ki model oraya rakam uydurursa yakalansın.
            if tc.function.name == "teshir_bilgi" and (
                    argumanlar.get("koleksiyon_id") or (argumanlar.get("ad") or "").strip()):
                teshir_cagrildi = True
            # Pazarlık aralıklarını AL ve modele gitmeden ÇIKAR (özel _ anahtar).
            if isinstance(sonuc, dict) and "_pazarlik_araliklari" in sonuc:
                pazarlik_araliklari.extend(
                    (int(lo), int(hi)) for lo, hi in sonuc.pop("_pazarlik_araliklari"))
            if tc.function.name in ("fiyat_detay", "parca_ara"):
                # Pazarlık adım durumu: verilen teklifler bot_mesaj'dan tespit
                # edilir, nota "ŞİMDİ şunu teklif et" eklenir (_merdiven düşer);
                # konuşulmamış ürüne DİKKAT uyarısı düşer (yanlış ürün ataması).
                satirlar = _son_mesajlar(platform, kullanici)
                _merdiven_isle(sonuc,
                               [m for y, m in satirlar if y == "giden"],
                               menu_veri._duz(" ".join(m for _, m in satirlar)))
            _fiyatlari_topla(sonuc, legit_fiyatlar)
            mesajlar.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(sonuc, ensure_ascii=False, default=str)[:6000],
            })

    SON_HATA = f"{datetime.now():%H:%M:%S} ToolTuruAsildi: {MAKS_TOOL_TURU} tur yetmedi"
    log.warning("ajan: %s tool turu aşıldı, menüye düşülüyor", MAKS_TOOL_TURU)
    return None
