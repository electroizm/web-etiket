"""Görsel (resim / story ekran görüntüsü) → metin — Gemini vision ile.

Kullanım senaryosu (İsmail isteği, 2026-07-07): müşteri Instagram story'sine
"fiyat" diye yanıt yazar ya da ürün fotoğrafı/ekran görüntüsü atar → görseldeki
metin (ör. "Lumeris Köşe Takımı") okunur, müşterinin metniyle birleştirilip
normal router akışına verilir. Fiyat YINE yalnız tool/DB'den gelir — görseldeki
"%20 indirim" gibi pazarlama metni fiyata dönüşmez (ajan kuralı zaten koruyor).

İndirme yardımcıları bot/ses.py'den yeniden kullanılır (aynı Meta medya akışı).
Hiçbir hata müşteri akışını bozmaz: her adım None dönebilir, çağıran devam eder.
"""
from __future__ import annotations

import base64
import logging

from django.conf import settings

log = logging.getLogger("bot.gorsel")

# Son görsel-okuma hatası — /saglik teşhisi için (Render loguna erişim yok).
SON_HATA: str | None = None

# Katalogda ARANABİLİR tip kelimeleri. Modelin serbest tarif yerine bu
# sözlükten seçmesi şart: ölçüm (2026-07-28) gösterdi ki üründe RENK ve
# MALZEME bilgisi yok (1.764 üründen 11'inde renk geçiyor), yani "bej kumaş
# koltuk" tarifi katalogda hiçbir şey bulmaz. Ad okunabiliyorsa zaten ad
# kullanılır; tarif YALNIZCA ad yokken devreye girer.
TIP_SOZLUGU = (
    "üçlü koltuk, ikili koltuk, tekli koltuk, köşe takımı, yataklı koltuk, "
    "berjer, puf, orta sehpa, zigon sehpa, yan sehpa, tv ünitesi, konsol, "
    "yemek masası, sandalye, vitrin, gardırop, dolap, şifonyer, komodin, "
    "karyola, baza, başlık, yatak, çalışma masası, kitaplık, ranza"
)

OKUMA_TALIMAT = (
    "Bu görsel bir mobilya mağazasının ürün fotoğrafı, Instagram hikâyesi ya da "
    "bir web sayfasının ekran görüntüsü olabilir. Görseldeki TÜM metni oku.\n"
    "- Bir ürün/koleksiyon/model adı bulursan (örn. 'LUMERIS Köşe Takımı', "
    "'NOR Orta Sehpa', 'Lea Yatak Odası Takımı') YALNIZCA o adı yaz.\n"
    "- Görselde 'teşhir', 'teşhire özel', 'sergi' ya da 'mağazaya özel' gibi bir "
    "ifade geçiyorsa ürün adının sonuna ' (teşhirdeki ürün)' ekle — bu, fiyatın "
    "mağaza teşhir kaydından sorgulanmasını sağlar.\n"
    "- Ürün adı yoksa ama başka metin varsa okuduğun metni kısaca yaz.\n"
    "- Görselde HİÇ ürün adı yazmıyorsa ve bir MOBİLYA görüyorsan, tek satır "
    "şu biçimde yaz: '(görsel tarifi: <tarif>)'. <tarif> şu alanları TAM BU "
    "SIRAYLA, aralarına ' | ' koyarak içerir:\n"
    "  tip | koltuk/kapak sayısı | ana renk | ikincil renk | döşeme/kaplama "
    "malzemesi | ayak tipi ve rengi | kolçak/kenar biçimi | belirgin detay\n"
    f"  <tip> için şu listeden en uygununu seç: {TIP_SOZLUGU}. Bilinmeyen "
    "alana 'yok' yaz. Model/seri adı TAHMİN ETME — bilemezsin.\n"
    "- Görselde ne metin ne mobilya varsa tek kelime yaz: YOK\n"
    "Açıklama, yorum, tırnak, fiyat, indirim ORANI/TUTARI ekleme."
)


_TARIF_ONEKI = "(görsel tarifi:"


def _benzerlerle_zenginlestir(okunan: str | None) -> str | None:
    """Görselde ürün ADI yoksa tarifi ürün fotoğrafı kataloğunda ara.

    Ürün adı okunduysa dokunulmaz — o zaten kesin bilgi. Tarif çıktıysa
    (müşteri yazısız fotoğraf atmış) tarif, katalogdaki ürün fotoğraflarının
    tarifleriyle karşılaştırılır ve en yakın adaylar mesaja eklenir. Eşleştirme
    çalışmazsa mesaj OLDUĞU GİBİ kalır — akış bozulmaz, ajan tip aramasına düşer.
    """
    if not okunan or _TARIF_ONEKI not in okunan:
        return okunan
    try:
        bas = okunan.index(_TARIF_ONEKI) + len(_TARIF_ONEKI)
        son = okunan.index(")", bas)
        tarif = okunan[bas:son].strip()
        if not tarif:
            return okunan
        from bot import gorsel_eslestir
        adaylar = gorsel_eslestir.benzerleri_bul(tarif, limit=3)
        if not adaylar:
            return okunan
        # SKU'lar da yazılır: ajan tek çağrıda (skulari_fiyatla) hepsinin
        # fiyatını alabilsin. Fiyatlar YİNE araçtan gelir — uydurma kalkanı
        # bozulmaz. Panelde bu satır göründüğü için ad da tutulur.
        liste = ", ".join(f"{a['ad']} [{a['sku']}]" for a in adaylar)
        return f"{okunan} (benzer ürünler: {liste})"
    except Exception:
        log.exception("benzer ürün araması başarısız")
        return okunan


def coz(gorsel: dict) -> str | None:
    """Webhook'un çıkardığı görsel bilgisini indir + metnini oku. Hata → None."""
    global SON_HATA
    try:
        from bot import ses as _ses   # indirme yardımcıları ortak (aynı Meta akışı)
        if gorsel.get("tip") == "wa":
            indirilen = _ses._wa_indir(gorsel.get("media_id", ""))
        else:   # "ig" (resim eki) ve "ig_story" (story medyası) — ikisi de CDN URL
            indirilen = _ses._ig_indir(gorsel.get("url", ""))
        if not indirilen:
            return None
        veri, mime = indirilen
        okunan = oku(veri, mime)
        return _benzerlerle_zenginlestir(okunan)
    except Exception as e:
        from datetime import datetime
        SON_HATA = f"{datetime.now():%H:%M:%S} coz {type(e).__name__}: {str(e)[:200]}"
        log.exception("görsel çözülemedi: %s", {k: v for k, v in gorsel.items()
                                                if k != "url"})
        return None


def oku(veri: bytes, mime: str) -> str | None:
    """Görsel baytlarından metni/ürün adını çıkar (ajanla aynı model zinciri).

    Story medyası video da olabilir (mime video/*) — Gemini kısa videoları da
    okuyabilir; boyut sınırını aşan indirmeler zaten _ig_indir'de elenir.
    """
    global SON_HATA
    if not settings.AJAN_AKTIF:
        return None
    import litellm
    litellm.suppress_debug_info = True

    b64 = base64.b64encode(veri).decode("ascii")
    if mime.startswith("image/"):
        ek = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    else:   # video/* — LiteLLM'in genel dosya biçimi (ses.py ile aynı kalıp)
        ek = {"type": "file", "file": {"file_data": f"data:{mime};base64,{b64}"}}
    mesajlar = [{
        "role": "user",
        "content": [{"type": "text", "text": OKUMA_TALIMAT}, ek],
    }]
    from datetime import datetime

    from bot import kota
    # Görüntü alabilen zincir (Groq modelleri görsel ALMAZ — bkz. settings).
    if kota.hepsi_kapali_mi(settings.AJAN_MEDYA_MODELLER):
        kota.kapalilari_ac()
    for model in settings.AJAN_MEDYA_MODELLER:
        if kota.kapali_mi(model):
            continue
        try:
            yanit = litellm.completion(model=model, messages=mesajlar,
                                       max_tokens=200, timeout=25)
            metin = (yanit.choices[0].message.content or "").strip()
            kota.say(model, "gorsel", "basari" if metin else "bos")
            if metin and metin.upper() != "YOK":
                return metin[:300]
            if metin:            # model "YOK" dedi — görselde metin yok, aramayı bırak
                return None
        except Exception as e:
            kotali = "429" in str(e) or "quota" in str(e).lower()
            kota.say(model, "gorsel", "kota" if kotali else "hata")
            if kotali:
                kota.limiti_ogren(model, e)
                kota.kapat(model, e)
            SON_HATA = f"{datetime.now():%H:%M:%S} [{model}] {type(e).__name__}: {str(e)[:200]}"
            log.warning("görsel okuma: %s başarısız (%s), sıradaki model",
                        model, type(e).__name__)
    log.error("görsel okuma: tüm modeller başarısız")
    return None
