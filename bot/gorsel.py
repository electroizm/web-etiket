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

OKUMA_TALIMAT = (
    "Bu görsel bir mobilya mağazasının ürün fotoğrafı, Instagram hikâyesi ya da "
    "bir web sayfasının ekran görüntüsü olabilir. Görseldeki TÜM metni oku.\n"
    "- Bir ürün/koleksiyon/model adı bulursan (örn. 'LUMERIS Köşe Takımı', "
    "'NOR Orta Sehpa', 'Lea Yatak Odası Takımı') YALNIZCA o adı yaz.\n"
    "- Ürün adı yoksa ama başka metin varsa okuduğun metni kısaca yaz.\n"
    "- Görselde hiç metin yoksa tek kelime yaz: YOK\n"
    "Açıklama, yorum, tırnak, fiyat, indirim oranı EKLEME."
)


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
        return oku(veri, mime)
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
    for model in settings.AJAN_MODELLER:
        try:
            yanit = litellm.completion(model=model, messages=mesajlar,
                                       max_tokens=200, timeout=25)
            metin = (yanit.choices[0].message.content or "").strip()
            if metin and metin.upper() != "YOK":
                return metin[:300]
            if metin:            # model "YOK" dedi — görselde metin yok, aramayı bırak
                return None
        except Exception as e:
            SON_HATA = f"{datetime.now():%H:%M:%S} [{model}] {type(e).__name__}: {str(e)[:200]}"
            log.warning("görsel okuma: %s başarısız (%s), sıradaki model",
                        model, type(e).__name__)
    log.error("görsel okuma: tüm modeller başarısız")
    return None
