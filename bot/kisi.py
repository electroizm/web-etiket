"""Bot müşterisi profil bilgisi (bot_kisi tablosu) — id yerine isim/foto.

WhatsApp: ad her gelen mesajın webhook'unda bedava geliyor (contacts[].profile.name);
Meta müşteri fotoğrafını Cloud API'ye vermez → WA'da foto yok.
Instagram: Graph API'den ad + kullanıcı adı + profil fotoğrafı çekilir; foto URL'si
CDN imzalı (süreli) olduğu için TAZELEME_SAAT'te bir yenilenir.

Hatalar webhook'u asla bozmaz: yut, logla, devam et.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from catalog.database import SessionLocal
from catalog.sa_models import BotKisi

log = logging.getLogger("bot.kisi")

TAZELEME_SAAT = 24   # IG profili en fazla bu sıklıkta yeniden çekilir


def _upsert(platform: str, kullanici: str, **alanlar) -> None:
    session = SessionLocal()
    try:
        kisi = session.scalar(
            select(BotKisi).where(BotKisi.platform == platform,
                                  BotKisi.kullanici == kullanici)
        )
        if kisi is None:
            kisi = BotKisi(platform=platform, kullanici=kullanici)
            session.add(kisi)
        for k, v in alanlar.items():
            setattr(kisi, k, v)
        kisi.guncelleme = datetime.now(timezone.utc)
        session.commit()
    finally:
        session.close()


def guncelle_wa(kullanici: str, ad: str | None) -> None:
    """WhatsApp adını kaydet (webhook'tan geldiyse). Ucuz — her mesajda çağrılabilir."""
    if not ad:
        return
    try:
        _upsert("whatsapp", kullanici, ad=ad[:128])
    except Exception:
        log.exception("bot_kisi WA güncellenemedi (%s)", kullanici)


def guncelle_ig(kullanici: str) -> None:
    """IG profilini gerekiyorsa Graph API'den tazele (24 saatte bir)."""
    try:
        session = SessionLocal()
        try:
            kisi = session.scalar(
                select(BotKisi).where(BotKisi.platform == "instagram",
                                      BotKisi.kullanici == kullanici)
            )
            if kisi is not None and kisi.guncelleme is not None:
                yas = datetime.now(timezone.utc) - kisi.guncelleme
                if yas < timedelta(hours=TAZELEME_SAAT) and kisi.kullanici_adi:
                    return  # taze — API'yi yorma
        finally:
            session.close()

        from bot import meta_client
        profil = meta_client.profil_instagram(kullanici)
        if not profil:
            return
        _upsert("instagram", kullanici,
                ad=(profil.get("name") or None),
                kullanici_adi=(profil.get("username") or None),
                foto_url=(profil.get("profile_pic") or None))
    except Exception:
        log.exception("bot_kisi IG güncellenemedi (%s)", kullanici)


def profil_haritasi() -> dict[tuple[str, str], dict]:
    """(platform, kullanici) → {ad, kullanici_adi, foto_url}. Dashboard için."""
    try:
        session = SessionLocal()
        try:
            rows = session.scalars(select(BotKisi)).all()
        finally:
            session.close()
        return {
            (r.platform, r.kullanici): {
                "ad": r.ad, "kullanici_adi": r.kullanici_adi, "foto_url": r.foto_url,
            }
            for r in rows
        }
    except Exception:
        log.exception("bot_kisi okunamadı")
        return {}
