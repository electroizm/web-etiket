"""
Uygulama geneli ayarlar — DB key-value erişimi + Supabase Storage upload.

Kayıtlı anahtarlar:
  - 'etiket_slogan_url'   → Etikette header görseli (sol üst banner)
  - 'yerli_uretim_url'    → Etikette sağ alt köşe logosu

Bucket: 'etiket-assets' (public read, authenticated write)
"""
from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from catalog.sa_models import AppAyari


BUCKET_ETIKET_ASSETS = "etiket-assets"

# Yüklenecek görseller — (storage path, DB anahtarı) çiftleri
SLOGAN_PATH = "slogan/aktif.png"
ANAHTAR_SLOGAN_URL = "etiket_slogan_url"

YERLI_URETIM_PATH = "yerli-uretim/aktif.png"
ANAHTAR_YERLI_URETIM_URL = "yerli_uretim_url"


# ─── Generic key-value getter/setter ─────────────────────────────────────────


def get_ayar(session: Session, anahtar: str) -> Optional[str]:
    """DB'den anahtara karşılık gelen değeri çek. Yoksa None."""
    row = session.scalar(select(AppAyari).where(AppAyari.anahtar == anahtar))
    return row.deger if row else None


def set_ayar(session: Session, anahtar: str, deger: Optional[str]) -> None:
    """Upsert: anahtar varsa güncelle, yoksa ekle. Commit caller'a ait."""
    from sqlalchemy import func as sa_func
    stmt = pg_insert(AppAyari).values(
        anahtar=anahtar,
        deger=deger,
    ).on_conflict_do_update(
        index_elements=["anahtar"],
        set_={"deger": deger, "guncellenme_tarihi": sa_func.now()},
    )
    session.execute(stmt)


# ─── Supabase Storage upload (generic) ───────────────────────────────────────


def _storage_upload(file_bytes: bytes, path: str, content_type: str) -> str:
    """Verilen path'e dosyayı upsert et, public URL'i döner.

    Cache busting için sona ?v=<unix_ts> ekleniyor — Storage CDN public
    URL'leri uzun süre cache'liyor, yenilemenin görünmesi için gerekli.
    """
    from accounts.supabase_client import get_supabase_admin

    supabase = get_supabase_admin()

    supabase.storage.from_(BUCKET_ETIKET_ASSETS).upload(
        path=path,
        file=file_bytes,
        file_options={
            "content-type": content_type,
            "upsert": "true",
            "cache-control": "no-cache",
        },
    )
    public_url = supabase.storage.from_(BUCKET_ETIKET_ASSETS).get_public_url(path)
    public_url = public_url.rstrip("?")
    return f"{public_url}?v={int(time.time())}"


# ─── Slogan (etiket header banner) ───────────────────────────────────────────


def slogan_yukle(file_bytes: bytes, content_type: str = "image/png") -> str:
    """Slogan görselini yükle ve public URL'i döner."""
    return _storage_upload(file_bytes, SLOGAN_PATH, content_type)


def slogan_url_aktif(session: Session) -> Optional[str]:
    return get_ayar(session, ANAHTAR_SLOGAN_URL)


# ─── Yerli Üretim (etiket sağ alt logo) ──────────────────────────────────────


def yerli_uretim_yukle(file_bytes: bytes, content_type: str = "image/png") -> str:
    """Yerli Üretim logosunu yükle ve public URL'i döner."""
    return _storage_upload(file_bytes, YERLI_URETIM_PATH, content_type)


def yerli_uretim_url_aktif(session: Session) -> Optional[str]:
    return get_ayar(session, ANAHTAR_YERLI_URETIM_URL)
