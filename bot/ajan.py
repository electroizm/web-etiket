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
4. Fiyat verirken ürün/kombinasyon adını da yaz (örn. "MARIZA Köşe Takımı: 85.000 TL").
   Söylediğin fiyat HER ZAMAN toplam_perakende (asıl satış fiyatımız) olmalı —
   bunu ASLA "liste fiyatı" diye sunma. Araç sonucunda toplam_liste VE
   indirim_yuzde de varsa (gerçek indirim var demektir): önce liste fiyatını
   belirt, sonra "size X TL indirim yaptık" cümlesiyle vurgula — örn. "Liste
   fiyatı 75.000 TL'den size 8.339 TL indirim yaptık, fiyatımız 66.661 TL."
   indirim_yuzde YOKSA liste fiyatından hiç bahsetme, sadece perakende fiyatı
   ver — indirim UYDURMA.
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
12. PAZARLIK (yalnız teşhir ürünlerinde): teshir_bilgi sonucunda
    "pazarlik_taban_fiyat" alanı VARSA ve müşteri pazarlık ederse ("indirim olur
    mu", "son fiyat ne", "kaça bırakırsın") indirim yapabilirsin. Kurallar:
    - pazarlik_taban_fiyat, teklif edebileceğin EN DÜŞÜK fiyattır. O fiyatı
      teklif etmek SERBESTTİR; yasak olan tek şey onun ALTINA inmektir.
    - İstersen önce taban ile perakende arasında ARA bir fiyat söyleyebilirsin;
      ara fiyata "son fiyat" DEME ("size ... TL yapabilirim" de). Müşteri ısrar
      ederse ("biraz daha", "olmaz mı", daha düşük rakam isterse) pazarlik_taban_fiyat'a
      İN ve ancak o zaman "size özel son fiyatımız X TL" de (X = pazarlik_taban_fiyat).
      Müşterinin istediği rakam tabana eşit ya da üstündeyse KABUL ET — "mümkün
      değil" deme; tabanın altındaysa taban fiyatı teklif et.
    - Tabana indikten sonra daha aşağı inme. "taban", "limit", "sistemin izin
      verdiği" gibi ifadeler ASLA kullanma — müşteri bir iç limit olduğunu
      bilmemeli. Müşteri pazarlık etmeden kendiliğinden indirim önerme.
    "pazarlik_taban_fiyat" alanı YOKSA pazarlık yapma — mağazaya ya da "yetkili"
    yazmaya yönlendir.

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
            "description": "Mağazada sergilenen (teşhirdeki) ürünlerin listesi, "
                           "içeriği ve mağaza fiyatları. Çağır: (a) müşteri "
                           "mağazadaki/teşhirdeki üründen bahsederse; (b) mesajda "
                           "'(teşhirdeki ürün)' ipucu varsa; (c) SON ÇARE — ürünü "
                           "normal katalogda bulamayınca ya da kategori uyuşmayınca, "
                           "pes etmeden önce teşhirde var mı diye bak. koleksiyon_id "
                           "verilirse o koleksiyonla sınırlar; vermezsen tüm teşhir "
                           "listesi döner (adı kendin eşleştirebilirsin).",
            "parameters": {
                "type": "object",
                "properties": {
                    "koleksiyon_id": {"type": "integer",
                                      "description": "Opsiyonel — koleksiyon_ara sonucundaki id"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fiyat_detay",
            "description": "Bir kombinasyonun fiyat detayını ve içindeki ürünleri verir. "
                           "Müşteriye fiyat söylemeden önce MUTLAKA bu (veya "
                           "kombinasyonlari_listele) çağrılmış olmalı.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kombinasyon_id": {"type": "integer"},
                },
                "required": ["kombinasyon_id"],
            },
        },
    },
]


def _tool_calistir(ad: str, argumanlar: dict,
                   platform: str = "", kullanici: str = ""):
    """Modelin istediği aracı gerçek veriyle çalıştır."""
    if ad == "koleksiyon_ara":
        return menu_veri.koleksiyon_ara(str(argumanlar.get("q", "")))
    if ad == "kategorileri_listele":
        return menu_veri.kategoriler()
    if ad == "koleksiyonlari_listele":
        return menu_veri.koleksiyonlar(int(argumanlar["kategori_id"]))
    if ad == "kombinasyonlari_listele":
        return menu_veri.kombinasyonlar(int(argumanlar["koleksiyon_id"]))
    if ad == "fiyat_detay":
        return menu_veri.kombinasyon(int(argumanlar["kombinasyon_id"]))
    if ad == "teshir_bilgi":
        from catalog.services import teshir as teshir_servis
        kol = argumanlar.get("koleksiyon_id")
        kayitlar = teshir_servis.ajan_icin(int(kol) if kol else None)
        if kayitlar:
            return {"teshir": kayitlar,
                    "pazarlik_kurali": "pazarlik_taban_fiyat alanı olan üründe müşteri "
                                       "pazarlık ederse EN DÜŞÜK o rakamı teklif edebilirsin; "
                                       "onun ALTINDA bir rakamı ASLA telaffuz etme. Müşteri "
                                       "ısrar ederse tam pazarlik_taban_fiyat'ı 'size özel son "
                                       "fiyatımız' diye söyle. Alan yoksa pazarlık yapma."}
        return {"bulunamadi": True,
                "not": "Teşhirde eşleşen kayıt yok — normal fiyat akışını kullan."}
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


def _pazarlik_kalkani(cevap: str, mesajlar: list[dict]) -> str:
    """Teşhir pazarlığı bağlamında taban altı fiyat teklifini tabana çek.

    Yalnız konuşmada teşhir geçiyorsa VE cevap pazarlık dili içeriyorsa devreye
    girer; normal fiyat cevaplarına dokunmaz. Taban altı ama tabanın %60'ından
    büyük TL tutarları (fiyat teklifi görünümlü) ilgili tabana yükseltilir —
    "5.000 TL indirim" gibi küçük tutarlar etkilenmez.
    """
    baglam = cevap + " " + " ".join(str(m.get("content", "")) for m in mesajlar)
    baglam = baglam.lower()
    if "teşhir" not in baglam and "teshir" not in baglam:
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
        for taban in tabanlar:      # küçükten büyüğe — en yakın üst taban
            if taban * 0.6 <= deger < taban:
                log.warning("ajan: pazarlık kalkanı — %s TL taban altı, %s TL yapıldı",
                            deger, taban)
                return f"{taban:,} TL".replace(",", ".")
        return m.group(0)

    return _TL_KALIBI.sub(duzelt, cevap)


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
    for model in settings.AJAN_MODELLER:
        try:
            return _cevapla(metin, platform, kullanici, model, gecmissiz=gecmissiz)
        except Exception as e:
            SON_HATA = f"{datetime.now():%H:%M:%S} [{model}] {type(e).__name__}: {str(e)[:200]}"
            log.warning("ajan: %s başarısız (%s), sıradaki model deneniyor",
                        model, type(e).__name__)
    log.error("ajan: tüm modeller başarısız, menüye düşülüyor")
    return None


def _cevapla(metin: str, platform: str, kullanici: str, model: str,
             gecmissiz: bool = False) -> str | None:
    import litellm
    litellm.suppress_debug_info = True

    kategoriler = ", ".join(f"{k['ad']} (id:{k['id']})" for k in menu_veri.kategoriler())
    gecmis = [] if gecmissiz else _gecmis(platform, kullanici, metin)
    mesajlar = [
        {"role": "system", "content": SISTEM_PROMPTU.format(kategoriler=kategoriler)},
        *gecmis,
        {"role": "user", "content": metin[:1000]},
    ]

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
            if cevap:
                cevap = _pazarlik_kalkani(cevap, mesajlar)
            return cevap[:MAKS_CEVAP_KR] if cevap else None

        # Modelin istediği araçları çalıştır, sonuçları konuşmaya ekle.
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
            mesajlar.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(sonuc, ensure_ascii=False, default=str)[:6000],
            })

    global SON_HATA
    from datetime import datetime
    SON_HATA = f"{datetime.now():%H:%M:%S} ToolTuruAsildi: {MAKS_TOOL_TURU} tur yetmedi"
    log.warning("ajan: %s tool turu aşıldı, menüye düşülüyor", MAKS_TOOL_TURU)
    return None
