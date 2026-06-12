"""Telegram + WhatsApp (CallMeBot) bildirimi.

Scraper tarama sonuçlarını (ve hataları) Telegram'a ve isteğe bağlı olarak
WhatsApp alıcılarına iletir. İlgili env değişkenleri boşsa kanal sessizce
devre dışıdır — bildirim hiçbir zaman asıl işi (tarama/DB yazımı) engellememelidir.

Telegram kurulumu: @BotFather'dan bot oluştur → token'ı .env'ye
TELEGRAM_BOT_TOKEN olarak yaz; botla bir kez konuşma başlat; chat id'yi
.env'ye TELEGRAM_CHAT_ID yaz.

WhatsApp kurulumu (CallMeBot, kişi başına bir kez):
  1. Alıcı, +34 644 81 58 78 numarasını rehberine ekler
  2. O numaraya WhatsApp'tan "I allow callmebot to send me messages" yazar
  3. Gelen cevaptaki apikey'i alır
  4. .env → WHATSAPP_ALICILAR=+90555...:apikey1,+90555...:apikey2
Not: CallMeBot üçüncü taraf ücretsiz bir servistir; teslimat garantisi yoktur.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def telegram_aktif() -> bool:
    return bool(
        getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        and getattr(settings, "TELEGRAM_CHAT_ID", "")
    )


def telegram_gonder(mesaj: str) -> bool:
    """Mesajı Telegram'a gönder. Başarı durumunu döner; asla exception atmaz."""
    if not telegram_aktif():
        log.debug("Telegram yapılandırılmamış, bildirim atlandı.")
        return False
    try:
        r = requests.post(
            _API_URL.format(token=settings.TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": mesaj[:4000],  # Telegram limiti 4096
            },
            timeout=15,
        )
        if r.status_code == 200:
            return True
        log.warning("Telegram bildirimi reddedildi: HTTP %s — %s",
                    r.status_code, r.text[:200])
    except Exception as e:
        log.warning("Telegram bildirimi gönderilemedi: %s", e)
    return False


_CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def whatsapp_aktif() -> bool:
    return bool(getattr(settings, "WHATSAPP_ALICILAR", []))


def whatsapp_gonder(mesaj: str) -> int:
    """Mesajı tüm CallMeBot alıcılarına gönder. Başarılı alıcı sayısını döner;
    asla exception atmaz. Alıcılar: settings.WHATSAPP_ALICILAR = [(telefon, apikey), ...]
    """
    basarili = 0
    for telefon, apikey in getattr(settings, "WHATSAPP_ALICILAR", []):
        try:
            r = requests.get(
                _CALLMEBOT_URL,
                params={"phone": telefon, "text": mesaj[:1500], "apikey": apikey},
                timeout=30,
            )
            if r.status_code == 200:
                basarili += 1
            else:
                log.warning("WhatsApp (CallMeBot) reddetti: %s HTTP %s — %s",
                            telefon, r.status_code, r.text[:200])
        except Exception as e:
            log.warning("WhatsApp (CallMeBot) gönderilemedi: %s — %s", telefon, e)
    return basarili


def scrape_raporu_mesaji(rapor: dict, *, sure_sn: float, basarili: int, toplam: int) -> str:
    """db_upsert raporundan insan-okur Telegram özeti üret."""
    satirlar = [
        "✅ Doğtaş taraması tamamlandı",
        f"⏱ Süre: {sure_sn / 60:.0f} dk · {basarili}/{toplam} ürün okundu",
        f"💰 Fiyat güncellenen: {rapor.get('guncellenen', 0)}",
        f"🆕 Yeni ürün: {rapor.get('yeni_urun', 0)}",
    ]
    if rapor.get("yeni_koleksiyon"):
        satirlar.append(f"📦 Yeni koleksiyon: {rapor['yeni_koleksiyon']}")
    if rapor.get("yeni_kategori"):
        satirlar.append(f"🗂 Yeni kategori: {rapor['yeni_kategori']}")
    if rapor.get("hata"):
        satirlar.append(f"⚠️ Okunamayan ürün: {rapor['hata']}")
    satirlar.append(
        f"(fark<70TL atlanan: {rapor.get('atlanan_fark_az', 0)}, "
        f"filtrelenen: {rapor.get('filtrelenen', 0)})"
    )
    if rapor.get("guncellenen"):
        satirlar.append("👉 Etiket Yazdır: https://etiket.gunesler.info/app/etiket-yazdir/")
    return "\n".join(satirlar)
