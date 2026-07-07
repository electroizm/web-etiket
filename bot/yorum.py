"""Yorumdan-DM (comment-to-DM): tetikleyici kelime içeren yorumlara özel (private)
DM ile cevap verir.

Tasarım kararı: post→ürün kodu eşlemesi YOK. Yorum metni, normal bir DM'in ilk
mesajı gibi mevcut `router.yanit_uret`'e verilir — aynı menü/AI akışı çalışır
(fiyat sorusu → ajan tool'dan gerçek fiyat, belirsizse kategori sorar). Ayrı bir
veri yapısı/eşleme tablosu gerekmez (DRY); zaten test edilmiş akış yeniden kullanılır.

Kısıtlar (İsmail kararı, faz-4):
- Kişi başı TEK tetikleme — aynı yorumcuya bir daha private-reply atılmaz (spam olmaz).
- Saatte ~200 üst sınır — Meta rate limit + maliyet güvenliği.
- Yalnızca private reply (DM); genel/public yorum cevabı kapsam dışı bırakıldı.

Hatalar webhook'u asla bozmaz: yut, logla, devam et (diğer modüllerle aynı ilke).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from bot.router import _duzle
from bot.webhook_core import GelenYorum

log = logging.getLogger("bot.yorum")

# Fiyat/bilgi niyeti sinyalleri — router'daki AI_SINYAL_KELIMELER'in daraltılmış
# hali (yorumlarda daha sıkı olmalı: "merhaba" gibi alakasız yorumlar tetiklemesin).
TETIK_KELIMELER = (
    "fiyat", "kaç para", "kac para", "kaça", "kaca", "ne kadar", "kaç lira",
    "kac lira", "kaç tl", "kac tl", "bilgi verir misiniz", "bilgi alabilir",
    "fiyatı", "fiyati", "kaça mal", "kaca mal",
)

SAATLIK_LIMIT = 200
_ISARET = "[yorum-dm]"   # giden kayıtta bu önekle işaretlenir (throttle/dedup sorgusu bunu arar)


def tetikleyici_mi(metin: str) -> bool:
    d = _duzle(metin)
    return any(_duzle(k) in d for k in TETIK_KELIMELER)


def _daha_once_tetiklendi_mi(igsid: str) -> bool:
    """Bu kişiye daha önce yorumdan-DM private reply atıldı mı? (kişi başı tek tetikleme)"""
    try:
        from sqlalchemy import select
        from catalog.database import SessionLocal
        from catalog.sa_models import BotMesaj
        session = SessionLocal()
        try:
            var = session.scalar(
                select(BotMesaj.id)
                .where(BotMesaj.platform == "instagram",
                       BotMesaj.kullanici == igsid,
                       BotMesaj.yon == "giden",
                       BotMesaj.metin.like(f"{_ISARET}%"))
                .limit(1)
            )
            return var is not None
        finally:
            session.close()
    except Exception:
        log.exception("tetiklenme kontrolü başarısız (%s) — temkinli: atlanıyor", igsid)
        return True   # DB erişilemezse spam riskini göze alma, sessizce atla


def _saatlik_limit_asildi_mi() -> bool:
    try:
        from sqlalchemy import select, func
        from catalog.database import SessionLocal
        from catalog.sa_models import BotMesaj
        bir_saat_once = datetime.now(timezone.utc) - timedelta(hours=1)
        session = SessionLocal()
        try:
            sayi = session.scalar(
                select(func.count(BotMesaj.id))
                .where(BotMesaj.platform == "instagram",
                       BotMesaj.yon == "giden",
                       BotMesaj.metin.like(f"{_ISARET}%"),
                       BotMesaj.olusturma >= bir_saat_once)
            )
            return (sayi or 0) >= SAATLIK_LIMIT
        finally:
            session.close()
    except Exception:
        log.exception("saatlik limit kontrolü başarısız — temkinli: atlanıyor")
        return True


def isle(yorum: GelenYorum) -> None:
    """Bir GelenYorum'u değerlendir: tetik + throttle geçerse private reply gönderir."""
    if not tetikleyici_mi(yorum.metin):
        return
    if _daha_once_tetiklendi_mi(yorum.yorumcu_id):
        log.info("yorumdan-DM: %s zaten tetiklemiş, atlandı", yorum.yorumcu_id)
        return
    if _saatlik_limit_asildi_mi():
        log.warning("yorumdan-DM: saatlik limit (%d) doldu, yorum atlandı", SAATLIK_LIMIT)
        return

    from bot import ig_presenter, meta_client
    from bot.kayit import kaydet, ozet_giden
    from bot.router import yanit_uret

    cevap = yanit_uret(yorum.metin, P=ig_presenter,
                       platform="instagram", kullanici=yorum.yorumcu_id)
    mesajlar = [cevap] if isinstance(cevap, dict) else cevap

    ilk_basarili = False
    for i, mesaj in enumerate(mesajlar):
        if i == 0:
            sonuc = meta_client.gonder_instagram_private_reply(yorum.comment_id, mesaj)
            if sonuc is None:
                log.error("yorumdan-DM private reply gönderilemedi (yorum %s)", yorum.comment_id)
                return   # ilk mesaj gitmediyse devamını da göndermeye çalışma
            ilk_basarili = True
        else:
            # Private reply yorum başına yalnız bir kez kullanılır; devam
            # mesajları artık açık olan normal DM kanalından gider.
            meta_client.gonder_instagram(yorum.yorumcu_id, mesaj)
        kaydet("instagram", yorum.yorumcu_id, "giden", f"{_ISARET} " + ozet_giden(mesaj))

    if ilk_basarili:
        kaydet("instagram", yorum.yorumcu_id, "gelen", f"[yorum] {yorum.metin}")
        try:
            from bot import kisi
            kisi.guncelle_ig(yorum.yorumcu_id)   # artık mesaj alıcısı sayılır, profil çekilebilir
        except Exception:
            log.exception("yorumdan-DM: profil güncellenemedi (%s)", yorum.yorumcu_id)
