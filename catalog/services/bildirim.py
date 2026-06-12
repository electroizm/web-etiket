"""E-posta bildirimi (Gmail SMTP).

Scraper tarama özetini (ve hataları) e-posta ile iletir. EMAIL_HOST_USER /
EMAIL_HOST_PASSWORD / BILDIRIM_EPOSTA_ALICILAR boşsa sessizce devre dışıdır —
bildirim hiçbir zaman asıl işi (tarama/DB yazımı) engellememelidir.

Kurulum:
  1. Gönderici Gmail hesabında 2 Adımlı Doğrulama açık olmalı
  2. https://myaccount.google.com/apppasswords → 16 haneli uygulama şifresi üret
  3. .env → EMAIL_HOST_USER=hesap@gmail.com, EMAIL_HOST_PASSWORD=<uygulama şifresi>
  4. .env → BILDIRIM_EPOSTA_ALICILAR=alici1@gmail.com,alici2@gmail.com

(Not: Telegram/WhatsApp bildirimi 2026-06-12'de denendi ve kullanıcı kararıyla
kaldırıldı — kanal artık yalnızca e-posta.)
"""
from __future__ import annotations

import logging

from django.conf import settings

log = logging.getLogger(__name__)


def eposta_aktif() -> bool:
    return bool(
        getattr(settings, "EMAIL_HOST_USER", "")
        and getattr(settings, "EMAIL_HOST_PASSWORD", "")
        and getattr(settings, "BILDIRIM_EPOSTA_ALICILAR", [])
    )


def eposta_gonder(konu: str, mesaj: str, alicilar: list[str] | None = None) -> bool:
    """Bildirim e-postasını alıcılara gönder. Başarı durumunu döner;
    asla exception atmaz. alicilar verilmezse BILDIRIM_EPOSTA_ALICILAR kullanılır."""
    if not eposta_aktif():
        log.debug("E-posta yapılandırılmamış, bildirim atlandı.")
        return False
    try:
        from django.core.mail import send_mail

        gonderilen = send_mail(
            subject=konu,
            message=mesaj,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=alicilar or settings.BILDIRIM_EPOSTA_ALICILAR,
            fail_silently=False,
        )
        return gonderilen > 0
    except Exception as e:
        log.warning("Bildirim e-postası gönderilemedi: %s", e)
        return False


def scrape_raporu_mesaji(rapor: dict, *, sure_sn: float, basarili: int, toplam: int) -> str:
    """db_upsert raporundan insan-okur e-posta gövdesi üret."""
    satirlar = [
        "dogtas.com taraması tamamlandı.",
        "",
        f"Süre: {sure_sn / 60:.0f} dk · {basarili}/{toplam} ürün okundu",
        f"Güncellenen: {rapor.get('guncellenen', 0)}",
        f"Yeni ürün: {rapor.get('yeni_urun', 0)}",
    ]
    if rapor.get("yeni_koleksiyon"):
        satirlar.append(f"Yeni koleksiyon: {rapor['yeni_koleksiyon']}")
    if rapor.get("yeni_kategori"):
        satirlar.append(f"Yeni kategori: {rapor['yeni_kategori']}")
    if rapor.get("hata"):
        satirlar.append(f"Okunamayan ürün: {rapor['hata']}")
    satirlar.append(
        f"Atlanan: {rapor.get('atlanan_fark_az', 0)}, "
        f"filtrelenen: {rapor.get('filtrelenen', 0)}"
    )
    satirlar += [
        "",
        "Etiketleri basmak için:",
        "https://etiket.gunesler.info/app/etiket-yazdir/",
    ]
    return "\n".join(satirlar)
