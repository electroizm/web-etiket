"""Bot cevabını WhatsApp Cloud API mesaj payload'larına çevirir.

ig_presenter ile **aynı fonksiyon adlarını** sunar; böylece router platformdan
bağımsız kalır (yanit_uret'e hangi presenter verilirse onu üretir).

Menü/liste/buton üreticileri 2026-07-29'da SİLİNDİ: bot 2026-07-21'de AI-only
akışa geçti (menü, kategori seçimi, sayfalama kaldırıldı) ve o fonksiyonlar o
tarihten beri hiç çağrılmıyordu. Bugün router yalnız şu üçünü kullanıyor:
metin_mesaji, gorsel_mesaji, yetkili_mesaji. Eski sürüm git geçmişinde duruyor.

Bu modül dönüşü "to/messaging_product" içermez — onu meta_client ekler.
"""
from __future__ import annotations


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


def yetkili_mesaji(metin: str, url: str, ara_url: str) -> list[dict]:
    """Yetkiliye yönlendirme: iki art arda buton mesajı (cta_url tek buton taşır) —
    WhatsApp'ta yaz (0532 sohbeti) + Sesli arama (arama ekranını açan /ara sayfası)."""
    return [
        _cta(metin, "📱 WhatsApp'ta yaz", url),
        _cta("📞 Aramak için 👇", "📞 Sesli arama yap", ara_url),
    ]
