"""Bot cevabını WhatsApp Cloud API mesaj payload'larına çevirir.

ig_presenter ile **aynı fonksiyon adlarını** sunar; böylece router platformdan
bağımsız kalır (yanit_uret'e hangi presenter verilirse onu üretir).

Eski menü (kategori→koleksiyon→kombinasyon gezintisi, sayfalama) 2026-07-29'da
silindi; bot AI-only akışa geçmişti. 2026-09-17'de İsmail SEÇİM BUTONLARINI
geri istedi — ama menü olarak değil: yalnız takım seçenekleri numaralı
listelenir, müşteri numaraya basınca o kombinasyonun fiyatı gider.

WhatsApp'ın Messenger'dan farkı (sınırlar Meta dokümanından):
- "quick_replies" YOK. Yerine iki interaktif tip var:
  * button : en çok 3 yanıt butonu (kısa seçimler).
  * list   : tek butonla açılan, en çok 10 satırlık liste (uzun seçimler).
- Buton başlığı ≤20, liste satır başlığı ≤24, satır açıklaması ≤72 karakter.
4 seçenek + Geri + Yetkili = 6 satır → liste tipi kullanılır (İsmail kararı
2026-09-17: "Liste menüsü").

Bu modül dönüşü "to/messaging_product" içermez — onu meta_client ekler.
"""
from __future__ import annotations

BUTON_BASLIK = 20
BUTON_MAX = 3
SATIR_BASLIK = 24
SATIR_ACIKLAMA = 72
LISTE_MAX = 10
LISTE_BUTON = "Seçenekler"


def _kirp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _metin(govde: str) -> dict:
    return {"type": "text", "text": {"body": govde}}


def metin_mesaji(govde: str) -> dict:
    """Düz metin mesajı (AI cevabı ve router'ın hazır metinleri için)."""
    return _metin(govde)


def video_mesaji(url: str) -> dict:
    """YouTube videosu — LİNK olarak gider, dosya olarak değil.

    preview_url=true: WhatsApp linki kendisi çekip küçük resim + başlık taşıyan
    önizleme kartı çizer; müşteri çıplak mavi link yerine videonun karesini
    görür ve karta dokununca YouTube açılır. YALNIZ bu mesajda açılıyor —
    diğer metin mesajlarının görünümü değişmesin.

    Neden video dosyası gönderilmiyor: Cloud API linkten çekilen videoda 16 MB
    ve H.264/AAC sınırı var, Render'da sıkıştırma aracı yok (bkz.
    catalog/services/video.py).
    """
    return {"type": "text", "text": {"preview_url": True, "body": url}}


def gorsel_mesaji(url: str, altyazi: str = "") -> dict:
    """Ürün fotoğrafı. Cloud API görseli PUBLIC LINKTEN kendisi çeker —
    dosya yüklemeye gerek yok. Altyazı (caption) 1024 karakterle sınırlı."""
    govde: dict = {"type": "image", "image": {"link": url}}
    if altyazi:
        govde["image"]["caption"] = altyazi[:1024]
    return govde


def _cta(metin: str, buton: str, url: str) -> dict:
    """Tek URL butonlu mesaj (cta_url). WhatsApp cta_url'de yalnız 1 buton olabilir."""
    return {
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "body": {"text": metin},
            "action": {
                "name": "cta_url",
                "parameters": {"display_text": buton, "url": url},
            },
        },
    }


def _butonlar(metin: str, secenekler: list[tuple[str, str, str]]) -> dict:
    """secenekler: [(baslik, payload, aciklama), ...] — en çok 3 → button tipi."""
    return {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": metin},
            "action": {"buttons": [
                {"type": "reply",
                 "reply": {"id": payload, "title": _kirp(baslik, BUTON_BASLIK)}}
                for baslik, payload, _ in secenekler[:BUTON_MAX]
            ]},
        },
    }


def _liste(metin: str, secenekler: list[tuple[str, str, str]]) -> dict:
    """secenekler: [(baslik, payload, aciklama), ...] — en çok 10 → list tipi."""
    satirlar = []
    for baslik, payload, aciklama in secenekler[:LISTE_MAX]:
        baslik = (baslik or "").strip()
        # Başlık 24 karakterde kırpılır (platform sınırı); kırpılıyorsa ve
        # açıklama boşsa tam ad açıklamada gösterilsin — hiçbir ad kaybolmasın.
        if not aciklama and len(baslik) > SATIR_BASLIK:
            aciklama = baslik
        satir = {"id": payload, "title": _kirp(baslik, SATIR_BASLIK)}
        if aciklama:
            satir["description"] = _kirp(aciklama, SATIR_ACIKLAMA)
        satirlar.append(satir)
    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": metin},
            "action": {"button": LISTE_BUTON, "sections": [{"rows": satirlar}]},
        },
    }


def secim_mesaji(metin: str, secenekler: list[tuple[str, str, str]]) -> dict:
    """≤3 seçenek → buton, fazlası → liste. secenekler: (başlık, payload, açıklama).

    Buton tipinde açıklama alanı yoktur ve başlık 20 karakterle sınırlıdır;
    ad sığmıyorsa liste tipine geçilir (24 + 72 karakterlik açıklama ile tam
    ad gösterilebiliyor).
    """
    if not secenekler:
        return _metin(metin)
    if (len(secenekler) <= BUTON_MAX
            and all(not a for *_, a in secenekler)
            and all(len((b or "").strip()) <= BUTON_BASLIK for b, *_ in secenekler)):
        return _butonlar(metin, secenekler)
    return _liste(metin, secenekler)


def yetkili_mesaji(metin: str, url: str, ara_url: str) -> dict:
    """Yetkiliye yönlendirme — TEK mesaj (İsmail 2026-09-18).

    Eskiden iki ayrı buton mesajı gidiyordu, sohbette üst üste iki kart
    görünüyordu. WhatsApp Cloud API bir mesajda YALNIZ BİR link butonu
    (cta_url) taşır — iki URL butonlu tek mesaj ancak onaylı şablonlarla
    mümkün. İki eylem şöyle paylaştırıldı:
      • BUTON = SESLİ ARAMA (/ara sayfası telefonun arama ekranını açar).
        İlk denemede buton "WhatsApp'tan yaz" idi ve arama, gövdedeki
        numaraya bırakılmıştı; ama WhatsApp numaraya dokununca kendi
        menüsünü ("... ile sohbet et / Kişilere ekle") açıyor, GERÇEK ARAMA
        yapmıyor (İsmail'in ekran görüntüsü). Arama tek dokunuş olmalı.
      • GÖVDEDEKİ NUMARA = WhatsApp'tan yazma yolu; WhatsApp'ın kendi menüsü
        zaten "sohbet et" seçeneğini veriyor.
    Instagram'da iki buton tek kartta çıkıyor (generic template iki web_url
    destekliyor), orada bölüştürmeye gerek yok.
    """
    return _cta(f"{metin}\n\n📱 WhatsApp'tan yazmak için numaraya dokunun.",
                "📞 Sesli arama yap", ara_url)
