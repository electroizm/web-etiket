"""AI ajan (Faz 5) — serbest yazılan müşteri mesajını anlar, gerekirse sohbet eder.

Tasarım ilkeleri (bkz. Obsidian: instALL/outputs/faz5-model-arastirmasi.md):
- Sağlayıcı-bağımsız: LiteLLM üzerinden çağrı; model adı settings.AJAN_MODEL
  (env: AJAN_MODEL). Varsayılan Gemini Flash (ücretsiz katman); yetmezse
  gemini-flash-lite-latest ya da başka sağlayıcıya tek env değişikliğiyle geçilir.
- Fiyat ASLA modelden gelmez: model yalnızca aşağıdaki tool'ları çağırarak
  veritabanındaki gerçek fiyatı okur. Tool sonucu olmadan fiyat yazması yasak
  (sistem promptunda da tembihlenir).
- Zarif düşüş: anahtar yok / kota doldu / hata → None döner, router menüye düşer.
  Müşteri hiçbir durumda cevapsız kalmaz.
- Bağlam: bot_mesaj tablosundaki son konuşmalar (settings.AJAN_GECMIS_LIMIT).
"""
from __future__ import annotations

import json
import logging
import re

from django.conf import settings
from sqlalchemy import select

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


def _sayac(model: str, alan: str) -> None:
    global SAYAC_BASLANGIC
    from datetime import datetime
    if SAYAC_BASLANGIC is None:
        SAYAC_BASLANGIC = f"{datetime.now():%d.%m %H:%M}"
    MODEL_SAYAC.setdefault(
        model, {"basari": 0, "bos": 0, "kota": 0, "hata": 0})[alan] += 1


def _kota_mu(e: Exception) -> bool:
    """İstisna Gemini kota aşımı mı? (LiteLLM RateLimitError / 429 / quota)"""
    metin = str(e).lower()
    return ("RateLimit" in type(e).__name__ or "429" in str(e)
            or "quota" in metin or "resource_exhausted" in metin)

# ─── Sistem promptu ──────────────────────────────────────────────────────────
SISTEM_PROMPTU = """Sen Doğtaş Çevreyolu mobilya mağazasının WhatsApp/Instagram asistanısın.
Görevin: müşteriye ürün ve fiyat konusunda yardımcı olmak, kısa ve samimi sohbet etmek.

KURALLAR (kesin):
1. FİYAT UYDURMA. Fiyat ve ürün bilgisini YALNIZCA sana verilen araçlardan (tool) al.
   Araç sonucu yoksa fiyat söyleme; "menüden bakalım" de.
2. Kısa yaz — bu bir mesajlaşma sohbeti. En fazla 3-4 cümle. Emoji az ve yerinde.
   İPUCU: kombinasyonlari_listele zaten her kombinasyonun toplam fiyatını döndürür —
   fiyat sorusu için o yeterli; fiyat_detay'ı yalnızca TEK bir kombinasyonun içeriği
   (hangi ürünler var) sorulduğunda çağır. Gereksiz araç çağrısı yapma.
3. Türkçe konuş, "siz" diye hitap et, sıcak ve yardımsever ol.
4. FİYATI ARACIN "fiyat_cumlesi" ALANINDAN AYNEN KOPYALA. Araç sonucunda her
   ürün/kombinasyon için hazır, ÇOK SATIRLI bir "fiyat_cumlesi" gelir (örn. üç satır:
   "Liste Fiyatı: 66.661 TL" / "İndirim: 12.665 TL" / "İndirimli Fiyat: 53.996 TL" —
   bazen EK SATIR da içerebilir). Fiyatı SÖYLERKEN önce ürün/kombinasyon adını KENDİ
   satırına yaz, ALT SATIRA fiyat_cumlesi'ni OLDUĞU GİBİ, KAÇ SATIRSA O KADAR
   SATIRIYLA yapıştır — satır ATLAMA, satır EKLEME. Örn:
     LUMERIS Köşe Takımı
     Liste Fiyatı: 66.661 TL
     İndirim: 12.665 TL
     İndirimli Fiyat: 53.996 TL
   Metindeki rakamları ASLA değiştirme/yuvarlama/yeniden hesaplama; satır
   düzenini bozma. Fazladan söz EKLEME — "size şu kadar indirim yaptık",
   "güncel perakende fiyatımız" gibi cümleler KURMA; müşteriyi yormayacak kadar
   kısa tut. fiyat_cumlesi yoksa fiyat söyleme. Kendi kafandan rakam (özellikle
   yuvarlak sayı) YAZMA; söylediğin her TL tutarı araç sonucunda birebir geçmeli.
   BİRDEN FAZLA ürün listelerken her ürünün KENDİ fiyat_cumlesi'ni yaz; bir
   ürünün rakamını başka ürüne TAŞIMA. Emin değilsen ilgili aracı yeniden çağır.
5. Müşteri insanla görüşmek isterse ya da çözemediğin bir konu olursa
   "yetkili" yazmasını söyle (bot onu mağaza yetkilisine yönlendirir).
6. Konu dışı sorularda (siyaset, genel bilgi, başka markalar...) kibarca
   mobilya konusuna dön; tartışmaya girme.
7. MAĞAZA BİLGİSİ UYDURMA (adres, konum, mesai saati, telefon, kargo,
   teslimat, iade, garanti, taksit, montaj...): bu bilgileri YALNIZCA
   magaza_bilgi aracından al. Araç "bulunamadi" dönerse bilgiyi BİLMEDİĞİNİ
   söyle ve "yetkili" yazmasını öner — sorusu yetkiliye iletilmiştir, de.
   Kendi genel bilginden ya da internetten mağaza bilgisi verme; başka
   şehirlerdeki/şubelerdeki Doğtaş mağazalarının bilgisi BİZİM bilgimiz değildir.
8. Müşteri kategori/koleksiyon adını yanlış yazabilir (örn. "mariza", "yatak odsı")
   — arama aracını kullanıp en yakınını bul.
9. Markdown/biçimlendirme işareti KULLANMA (**, ##, madde imi vb.) — WhatsApp ve
   Instagram bunları göstermez, olduğu gibi görünür. Düz metin + emoji yaz.
10. Aynı seri adı birden fazla kategoride olabilir (örn. VERMONT hem Yemek Odası
    hem Yatak Odası). koleksiyon_ara birden çok sonuç dönerse: müşterinin
    mesajından kategori belliyse onu seç; belli değilse fiyat vermeden önce
    hangi kategoriyi istediğini sor.
11. TEŞHİR (mağazada sergilenen ürünler). teshir_bilgi aracını ŞU üç durumda çağır:
    (a) Müşteri özellikle mağazadaki/teşhirdeki/sergideki üründen bahsederse
        ("mağazanızda gördüm", "teşhirdeki fiyatı ne", "vitrindeki takım").
    (b) Mesajda "(teşhirdeki ürün)" ipucu geçiyorsa (görselden okunmuş demektir).
    (c) SON ÇARE: müşterinin sorduğu ürünü normal katalogda BULAMAZSAN ya da
        bulduğun ürün müşterinin belirttiği KATEGORİYLE UYUŞMUYORSA (örn. müşteri
        "Lea yatak odası" diyor ama koleksiyon_ara Lea'yı yalnız Oturma Grubu'nda
        buluyor) → "bulamadım/yanlış kategori" demeden ÖNCE teshir_bilgi'ye bak;
        ürün teşhirde olabilir. Teşhirde varsa fiyatı oradan ver.
    Bu üç durumda fiyatı ve içeriği teşhir kaydından söyle, teşhir ürünü olduğunu
    belirt. Bunların DIŞINDA (müşteri sormadı, ipucu yok, ürün normal katalogda
    temiz bulundu) teşhir fiyatını kendiliğinden açma — her zamanki araçları kullan.
    TEŞHİR LİSTESİ SUNUMU (önemli): Müşteri "teşhirde ürün var mı" gibi GENEL
    sorduğunda teshir_bilgi'yi koleksiyon_id/ad VERMEDEN çağır — yalnız ürün
    İSİMLERİ döner (fiyatsız). Bu isimleri KATEGORİYE GÖRE GRUPLAYARAK yaz
    (örn. "Yatak Odası: LEA, MARGO" gibi), FİYAT/İNDİRİM/RAKAM YAZMA, içerik
    dökme. Sonunda hangisinin fiyatını istediğini SOR ve "fiyatlarımızda cüzi
    pazarlık payımız var 😊" gibi KISA bir not ekle. Müşteri BELİRLİ bir teşhir
    ürününün fiyatını isteyince teshir_bilgi'yi ad="<ürün adı>" ile ÇAĞIR —
    o ürünün fiyat_cumlesi'si ve pazarlık tabanı öyle gelir. Fiyat vereceğin
    her teşhir ürününde MUTLAKA ad (ya da koleksiyon_id) geçir; isimsiz genel
    listeden fiyat OKUMA (orada fiyat yoktur).
12. PAZARLIK — TEŞHİR ürünleri: teshir_bilgi sonucunda bir ürünün
    "pazarlik_notu" alanı VARSA ve müşteri pazarlık ederse ("indirim olur mu",
    "son fiyat ne", "kaça bırakırsın") indirim yapabilirsin. pazarlik_notu, o
    ürün için inebileceğin EN DÜŞÜK fiyatı söyleyen hazır bir talimattır. Kurallar:
    - Nottaki en düşük fiyat, teklif edebileceğin EN DÜŞÜK rakamdır. Onu teklif
      etmek SERBESTTİR; yasak olan tek şey onun ALTINA inmektir.
    - İstersen önce o taban ile İndirimli Fiyat arasında ARA bir fiyat
      söyleyebilirsin; ara fiyata "son fiyat" DEME ("size ... TL yapabilirim" de).
      Müşteri ısrar ederse ("biraz daha", "olmaz mı", daha düşük rakam isterse)
      nottaki en düşük fiyata İN ve ancak o zaman "size özel son fiyatımız X TL"
      de. Müşterinin istediği rakam o tabana eşit ya da üstündeyse KABUL ET —
      "mümkün değil" deme; altındaysa taban fiyatı teklif et.
    - Tabana indikten sonra daha aşağı inme. "taban", "limit", "sistemin izin
      verdiği" gibi ifadeler ASLA kullanma — müşteri bir iç limit olduğunu
      bilmemeli. Müşteri pazarlık etmeden kendiliğinden indirim önerme.
    - Fiyatı HER ZAMAN fiyat_cumlesi'nden AYNEN al; nottaki rakam dışında
      kendin rakam UYDURMA/yuvarlama yapma.
    "pazarlik_notu" alanı YOKSA pazarlık yapma — mağazaya ya da "yetkili"
    yazmaya yönlendir.
13. TEK PARÇA FİYATI. Müşteri bir setin/odanın SADECE tek bir parçasını sorarsa
    ("sadece 5 kapaklı dolap", "tek başına komodin", "yalnız yatak fiyatı" gibi
    "sadece/tek/yalnız" vurgusuyla) parca_ara aracını o parçanın adıyla çağır ve
    YALNIZ o parçanın fiyatını (fiyat_cumlesi) ver. Seti KENDİLİĞİNDEN önerme,
    dayatma; müşteri set/oda sormadıkça sete geçme. Birden çok eşleşme dönerse
    hangisini kastettiğini sor. parca_ara boş dönerse fiyatı UYDURMA — bilmiyorum
    de, "yetkili" yazmasını öner. (Müşteri tüm odayı/seti soruyorsa bu aracı
    KULLANMA; her zamanki koleksiyon/kombinasyon akışını kullan.)
14. PAZARLIK — KATALOG (kombinasyon ve tek parça). Katalog fiyatı verdiğin
    cevabın SONUNA BİR KEZ "Fiyatlarımızda pazarlık payımız var 😊" notu ekle
    (ürün başına değil, cevap başına bir kez; müşteri pazarlığa zaten
    başladıysa tekrar etme). Müşteri pazarlık ederse ("indirim olur mu",
    "son fiyat ne", "kaça olur"): araç sonucundaki "pazarlik_notu" alanına
    AYNEN uy — merdivendeki fiyatları SIRAYLA, her ısrarda yalnız BİR adım
    inerek teklif et; merdivenin SON fiyatının altına ASLA inme; "taban",
    "limit", "sistem" gibi sözler kullanma; notu müşteriye okuma, UYGULA.
    Kombinasyonun pazarlik_notu'su fiyat_detay aracında gelir — müşteri hangi
    kombinasyonda pazarlık ediyorsa ONUN fiyat_detay'ını çağır (hangisi
    olduğu belli değilse önce sor). Tek parçada pazarlik_notu parca_ara
    sonucunda vardır. HER pazarlık mesajında ilgili aracı YENİDEN çağır:
    pazarlik_notu'nun sonundaki "ADIM DURUMU" satırı hangi fiyatı teklif
    edeceğini hazır söyler — kendin sayaç tutma, o satıra uy. Geçmişte
    "indirim yapamıyorum" demiş olman ŞİMDİ de yapamayacağın anlamına
    GELMEZ — pazarlığı reddetmeden önce MUTLAKA aracı çağırıp ADIM
    DURUMU'na bak; ancak "merdiven bitti" diyorsa reddet. ÜRÜN SABİT:
    pazarlık, konuşmada EN SON fiyat verilen ürün üzerinedir — müşteri
    açıkça başka ürün adı yazmadıkça ürün DEĞİŞTİRME, başka ürünün
    fiyatını ARAMA; merdiven bitince de başka ürüne atlama, aynı ürünün
    son fiyatını kibarca tekrarla. kombinasyon_id'yi TAHMİN ETME: pazarlık
    hangi kombinasyona fiyat verdiysen ONUN id'siyle sürer — aynı serinin
    BAŞKA kombinasyonuna (başka kategoriye) geçme; id'den emin değilsen
    fiyat verdiğin kombinasyonu kombinasyonlari_listele ile bulup doğrula. pazarlik_notu'nda "DİKKAT" uyarısı
    varsa fiyat verme — önce hangi ürünü kastettiğini sor. pazarlik_notu
    YOKSA o üründe pazarlık yapma — kibarca "yetkili" yazmasını öner.
    Kendiliğinden indirimli teklif verme; merdiven ancak müşteri pazarlık
    edince işler. Müşteriye yazdığın cevapta "merdiven", "adım",
    "ADIM DURUMU", "pazarlik_notu" gibi İÇ terimleri ASLA kullanma —
    bunlar senin talimatındır, müşteri bir mekanizma olduğunu bilmemeli.

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
                           "fiyatını ada göre verir. YALNIZCA müşteri bir setin tek bir "
                           "parçasını 'sadece/tek başına/yalnız' diye özellikle sorduğunda "
                           "kullan (örn. 'sadece 5 kapaklı dolap', 'tek başına komodin'). "
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
        # Modele SADE görünüm ver: ham rakamlar yerine fiyat_cumlesi. Fiyat kalkanı
        # için gerçek tutarlar fiyat_cumlesi metninden okunur (uydurma tespiti korunur).
        return _ham_fiyat_gizle(menu_veri.kombinasyonlar(
            int(argumanlar["koleksiyon_id"])))
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
                       "kendiliğinden önerme. Birden çok eşleşme varsa hangisi olduğunu sor."}
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
_PAZARLIK_ISTEK_KALIPLARI = ("indirim", "pazarl", "son fiyat", "olmaz mı", "olmaz mi",
                             "biraz daha", "daha in", "daha düş", "daha dus",
                             "kaça olur", "kaca olur", "kaça verirsin", "ucuz",
                             "bırak", "birak")


def _pazarlik_istegi_mi(metin: str) -> bool:
    low = (metin or "").lower()
    return any(k in low for k in _PAZARLIK_ISTEK_KALIPLARI)


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
            sonuc["pazarlik_notu"] += _adim_notu(list(merdiven), gidenler)
            if not _urun_konusuldu_mu(sonuc, konusma_duz):
                sonuc["pazarlik_notu"] += (
                    " DİKKAT: bu ürün müşteriyle SON KONUŞULAN ürün DEĞİL "
                    "görünüyor — müşteri bu ürünü açıkça istemediyse bu fiyatı "
                    "VERME; pazarlığı hangi ürün için istediğini SOR.")
        for v in sonuc.values():
            _merdiven_isle(v, gidenler, konusma_duz)
    elif isinstance(sonuc, list):
        for v in sonuc:
            _merdiven_isle(v, gidenler, konusma_duz)


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
        if not metin or metin.startswith("[buton]") or "[menü]" in metin \
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
    for model in settings.AJAN_MODELLER:
        basla = monotonic()
        try:
            cevap = _cevapla(metin, platform, kullanici, model, gecmissiz=gecmissiz)
        except Exception as e:
            _sayac(model, "kota" if _kota_mu(e) else "hata")
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
            if (cevap and _pazarlik_istegi_mi(metin) and not arac_cagrildi
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
            if cevap:
                cevap = _sistem_sozu_temizle(
                    _pazarlik_kalkani(cevap, teshir_cagrildi, legit=legit_fiyatlar))
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
