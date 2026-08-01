"""Supabase Storage — panelden yüklenen fotoğrafların kalıcı deposu.

**Neden Render'ın diskine yazmıyoruz:** Render ücretsiz katmanda dosya sistemi
GEÇİCİDİR. Her deploy'da (bazı günler 4-5 kez) yüklenen dosyalar silinir. Teşhir
fotoğrafı bir kez çekilip aylarca kullanılacak bir veri; diske yazmak sessiz
veri kaybı demekti.

Bucket `etiket-assets` zaten vardı ve public'ti (etiket görselleri orada);
teşhir fotoğrafları `teshir/<id>/` klasörüne konur — yeni kurulum gerekmedi.

**Neden public:** WhatsApp Cloud API ve Instagram fotoğrafı bizden dosya olarak
ALMAZ; verdiğimiz linkten kendisi indirir. Bu yüzden URL herkese açık olmak
zorunda. Fotoğraflar mağaza vitrini, gizli veri değil.

Yükleme sırasında fotoğraf **küçültülür ve EXIF'i silinir**:
  * Telefon fotoğrafı 3-5 MB gelir; WhatsApp'a gitmeden ~200-400 KB'a iner.
  * EXIF konum etiketi taşır — mağaza fotoğrafıyla birlikte GPS koordinatı
    müşteriye gitmesin diye tamamen atılır (yalnız dönme bilgisi uygulanır).
"""
from __future__ import annotations

import io
import logging
import uuid

log = logging.getLogger("catalog.depo")

BUCKET = "etiket-assets"

# WhatsApp görsel sınırı 5 MB; biz çok daha altını hedefliyoruz. Girdi sınırı
# yükleme sırasında bellek şişmesini de engeller.
MAKS_GIRDI_BAYT = 25 * 1024 * 1024
MAKS_KENAR = 1600           # px — telefon ekranında fazlasının faydası yok
KALITE = 82                 # JPEG kalitesi; 82 gözle farksız, dosya yarı yarıya


class DepoHatasi(Exception):
    """Yükleme/silme başarısız — çağıran kullanıcıya nazik mesaj gösterir."""


def _istemci():
    from django.conf import settings
    from supabase import create_client

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise DepoHatasi("Supabase ayarları eksik (URL / servis anahtarı).")
    # Servis anahtarı ŞART: anon anahtar bucket'a yazamaz (RLS).
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def hazirla(baytlar: bytes) -> bytes:
    """Fotoğrafı küçült, EXIF'ini at, JPEG'e çevir.

    Gerçek bir görsel olduğunu da DOĞRULAR: Pillow açamıyorsa yükleme yapılmaz
    (panelden gelen dosyanın uzantısına güvenilmez).
    """
    from PIL import Image, ImageOps

    if not baytlar:
        raise DepoHatasi("Dosya boş.")
    if len(baytlar) > MAKS_GIRDI_BAYT:
        raise DepoHatasi(
            f"Dosya çok büyük ({len(baytlar) // (1024 * 1024)} MB). "
            f"En fazla {MAKS_GIRDI_BAYT // (1024 * 1024)} MB.")
    try:
        gorsel = Image.open(io.BytesIO(baytlar))
        gorsel.load()                       # bozuk dosya burada patlar
    except Exception as e:
        raise DepoHatasi("Bu dosya bir fotoğraf değil ya da bozuk.") from e

    # Telefonlar fotoğrafı düz kaydedip "şu kadar döndür" bilgisini EXIF'e
    # yazar. Önce dönmeyi uygula, SONRA EXIF'i at — yoksa yan yatmış görünür.
    gorsel = ImageOps.exif_transpose(gorsel)
    if gorsel.mode not in ("RGB", "L"):     # PNG şeffaflığı JPEG'de siyah olur
        gorsel = gorsel.convert("RGB")
    gorsel.thumbnail((MAKS_KENAR, MAKS_KENAR), Image.LANCZOS)

    cikti = io.BytesIO()
    # exif= verilmiyor → konum/cihaz bilgisi kopyalanmaz.
    gorsel.save(cikti, format="JPEG", quality=KALITE, optimize=True)
    return cikti.getvalue()


def yukle(baytlar: bytes, klasor: str) -> str:
    """Fotoğrafı depoya koy, herkese açık URL'ini döndür.

    Dosya adı rastgele (uuid): aynı anda iki yükleme çakışmaz ve tahmin
    edilemez. Yükleme başarısızsa DepoHatasi — çağıran hiçbir şey kaydetmez.
    """
    hazir = hazirla(baytlar)
    yol = f"{klasor.strip('/')}/{uuid.uuid4().hex[:12]}.jpg"
    try:
        istemci = _istemci()
        istemci.storage.from_(BUCKET).upload(
            path=yol, file=hazir,
            file_options={"content-type": "image/jpeg",
                          "cache-control": "31536000"},   # 1 yıl: dosya değişmez
        )
        # get_public_url boş bir '?' ekliyor; WhatsApp/Instagram'a giden linkte
        # gereksiz ve bazı istemcilerde tuhaf görünüyor — kırp.
        return istemci.storage.from_(BUCKET).get_public_url(yol).rstrip("?")
    except DepoHatasi:
        raise
    except Exception as e:
        log.warning("depoya yukleme basarisiz (yol=%s)", yol, exc_info=True)
        raise DepoHatasi(f"Depoya yüklenemedi: {e}") from e


def _yolu_coz(url: str) -> str | None:
    """Public URL'den bucket içi yolu çıkar; bu depoya ait değilse None."""
    isaret = f"/storage/v1/object/public/{BUCKET}/"
    if not url or isaret not in url:
        return None
    return url.split(isaret, 1)[1].split("?", 1)[0] or None


def sil(url: str) -> bool:
    """Depodaki dosyayı sil. Zaten yoksa/başkasının URL'iyse sessizce False.

    Silinemese bile çağıran kaydı güncellemeye devam eder: panelde görünmeyen
    ama depoda kalan dosya, silinmiş sanılıp müşteriye giden dosyadan iyidir.
    """
    yol = _yolu_coz(url)
    if not yol:
        return False
    try:
        _istemci().storage.from_(BUCKET).remove([yol])
        return True
    except Exception:
        log.warning("depodan silinemedi (yol=%s)", yol, exc_info=True)
        return False
