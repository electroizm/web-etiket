"""Telegram bildirimi.

Scraper tarama sonuçlarını (ve hataları) Telegram'a iletir. TELEGRAM_BOT_TOKEN
veya TELEGRAM_CHAT_ID tanımlı değilse sessizce devre dışıdır — bildirim
hiçbir zaman asıl işi (tarama/DB yazımı) engellememelidir.

Kurulum: @BotFather'dan bot oluştur → token'ı .env'ye TELEGRAM_BOT_TOKEN olarak
yaz; botla bir kez konuşma başlat; chat id'yi .env'ye TELEGRAM_CHAT_ID yaz.
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
