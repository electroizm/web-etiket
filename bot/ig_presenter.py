"""Bot cevabını Instagram (Messenger Platform) mesaj payload'larına çevirir.

wa_presenter ile **aynı fonksiyon adlarını** sunar; router platformdan bağımsız
kalır.

Quick reply / carousel üreticileri 2026-07-29'da SİLİNDİ: bot 2026-07-21'de
AI-only akışa geçti ve o fonksiyonlar o tarihten beri hiç çağrılmıyordu. Bugün
router yalnız şu üçünü kullanıyor: metin_mesaji, gorsel_mesaji, yetkili_mesaji.
Eski sürüm git geçmişinde duruyor.
"""
from __future__ import annotations


def _kirp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def metin_mesaji(govde: str) -> dict:
    """Düz metin mesajı (AI cevabı ve router'ın hazır metinleri için)."""
    return {"text": govde}


def gorsel_mesaji(url: str, altyazi: str = "") -> dict:
    """Ürün fotoğrafı. IG mesaj eki altyazı TAŞIMAZ — altyazı ayrı metin
    mesajı olarak gider (router fotoğrafı metnin ardına ekler)."""
    return {"attachment": {"type": "image", "payload": {"url": url}}}


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
