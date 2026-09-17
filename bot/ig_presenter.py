"""Bot cevabını Instagram (Messenger Platform) mesaj payload'larına çevirir.

wa_presenter ile **aynı fonksiyon adlarını** sunar; router platformdan bağımsız
kalır.

Eski menü (kategori→koleksiyon gezintisi, sayfalama) 2026-07-29'da silindi.
2026-09-17'de İsmail SEÇİM BUTONLARINI geri istedi — yalnız takım seçenekleri
için: numaralı hızlı yanıtlar + Geri + Yetkili.

Sınırlar: quick reply başlığı ≤20 karakter, en çok 13 adet. WhatsApp'ın
aksine hepsi tek mesajda yan yana görünür (liste açmaya gerek yok).
"""
from __future__ import annotations

QR_BASLIK = 20
QR_MAX = 13


def _kirp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def metin_mesaji(govde: str) -> dict:
    """Düz metin mesajı (AI cevabı ve router'ın hazır metinleri için)."""
    return {"text": govde}


def video_mesaji(url: str) -> dict:
    """YouTube videosu — düz metin linki.

    Instagram DM'de link önizlemesi Meta'nın kendi kararı; API'de açıp
    kapatan bir alan YOK (WhatsApp'taki preview_url'in karşılığı yok).
    Önizleme çıkmasa bile link tıklanabilir kalır.
    """
    return {"text": url}


def gorsel_mesaji(url: str, altyazi: str = "") -> dict:
    """Ürün fotoğrafı. IG mesaj eki altyazı TAŞIMAZ — altyazı ayrı metin
    mesajı olarak gider (router fotoğrafı metnin ardına ekler)."""
    return {"attachment": {"type": "image", "payload": {"url": url}}}


def secim_mesaji(metin: str, secenekler: list[tuple[str, str, str]]) -> dict:
    """Numaralı seçim — hızlı yanıt (quick reply) mesajı.

    secenekler: [(başlık, payload, açıklama), ...]. Açıklama IG'de gösterilemez
    (alan yok), yalnız WhatsApp liste satırında kullanılır — imza ortak kalsın
    diye burada sessizce yok sayılır.
    """
    if not secenekler:
        return {"text": metin}
    return {
        "text": metin,
        "quick_replies": [
            {"content_type": "text", "title": _kirp(baslik, QR_BASLIK),
             "payload": payload}
            for baslik, payload, _ in secenekler[:QR_MAX]
        ],
    }


def yetkili_mesaji(metin: str, url: str, ara_url: str) -> dict:
    """Yetkiliye yönlendirme: tek kartta iki web_url butonu —
    WhatsApp'ta yaz (0532 sohbeti) + Sesli arama (arama ekranını açan /ara sayfası)."""
    return {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": "generic",
                "elements": [{
                    "title": "👤 Yetkiliyle görüş",
                    "subtitle": _kirp(metin, 80),
                    "buttons": [
                        {"type": "web_url", "url": url, "title": "📱 WhatsApp'ta yaz"},
                        {"type": "web_url", "url": ara_url, "title": "📞 Sesli arama yap"},
                    ],
                }],
            },
        }
    }
