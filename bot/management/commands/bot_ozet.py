"""Bot sabah özeti — Görev Zamanlayıcı her gün 09:00'da çalıştırır.

Son 24 saatin bot konuşmalarını toplar, Gemini ile konuşma başına tek satır
özetler (başında memnuniyet göstergesi: 😊 memnun / 😐 nötr / 😟 memnuniyetsiz),
açık cevapsız soruları ekler ve e-posta ile gönderir (scraper bildirimleriyle
aynı SMTP). Gemini başarısızsa yalnız sayılarla düz özet gider — özet asla
tamamen düşmez.

Konuşma da açık soru da yoksa SESSİZ kalır (kullanıcı kararı 2026-06-12:
söylenecek bir şey yoksa bildirim gitmesin — scraper ile aynı ilke).

Kullanım: python manage.py bot_ozet [--kuru]   (--kuru: e-posta yok, ekrana yaz)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Son 24 saatin bot konuşma özetini e-posta ile gönderir (günlük 09:00)."

    def add_arguments(self, parser):
        parser.add_argument("--kuru", action="store_true",
                            help="E-posta gönderme, özeti ekrana yaz (deneme).")

    def handle(self, *args, **opts):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")

        from sqlalchemy import select

        from bot.router import YETKILI_WA
        from catalog.database import SessionLocal
        from catalog.sa_models import BotKisi, BotMesaj, BotSoru

        baslangic = datetime.now(timezone.utc) - timedelta(hours=24)
        session = SessionLocal()
        try:
            rows = session.scalars(
                select(BotMesaj)
                .where(BotMesaj.olusturma >= baslangic)
                .order_by(BotMesaj.id)
            ).all()
            sorular = session.scalars(
                select(BotSoru).where(BotSoru.durum == "acik").order_by(BotSoru.id)
            ).all()
            adlar = {(k.platform, k.kullanici): k.ad
                     for k in session.scalars(select(BotKisi)).all()}
        finally:
            session.close()

        # İsmail'e giden bildirimler (geri arama/alarm) müşteri konuşması değildir.
        geri_arama = sum(1 for r in rows
                         if r.kullanici == YETKILI_WA and r.yon == "giden"
                         and (r.metin or "").startswith("📞 GERİ ARAMA"))
        alarmlar = sum(1 for r in rows
                       if r.kullanici == YETKILI_WA and r.yon == "giden"
                       and (r.metin or "").startswith("⚠️ MEMNUNİYETSİZLİK"))
        rows = [r for r in rows if r.kullanici != YETKILI_WA]

        konusmalar: dict[tuple[str, str], list] = {}
        for r in rows:
            konusmalar.setdefault((r.platform, r.kullanici), []).append(r)

        if not konusmalar and not sorular:
            self.stdout.write("Son 24 saatte konuşma yok, açık soru yok — sessiz.")
            return

        gelen_sayisi = sum(1 for r in rows if r.yon == "gelen")
        simdi = datetime.now()
        satirlar = [
            f"🤖 instALL ajan — sabah özeti ({simdi:%d.%m.%Y %H:%M})",
            "",
            f"Konuşma: {len(konusmalar)} · Gelen mesaj: {gelen_sayisi}"
            f" · Geri arama talebi: {geri_arama}"
            + (f" · ⚠️ Memnuniyetsizlik alarmı: {alarmlar}" if alarmlar else ""),
        ]

        # Fırsat defteri — sıcak müşteriler en üstte (aksiyon alınacak kısım).
        from bot import firsat
        firsatlar = firsat.sicak_musteriler(konusmalar, adlar) if konusmalar else []
        if firsatlar:
            satirlar += ["", f"🔥 Sıcak müşteriler ({len(firsatlar)}) — aramaya değer:"]
            satirlar += firsat.ozet_satirlari(firsatlar)

        ai_ozet = _ai_ozet(konusmalar, adlar) if konusmalar else None
        if ai_ozet:
            satirlar += ["", ai_ozet]
        elif konusmalar:
            satirlar.append("")
            for (platform, kullanici), mesajlar in konusmalar.items():
                ad = adlar.get((platform, kullanici)) or kullanici
                satirlar.append(f"- {ad} ({platform}): {len(mesajlar)} mesaj")
            satirlar.append("(AI özeti üretilemedi — yalnız sayılar)")

        if sorular:
            satirlar += ["", f"❓ Cevapsız sorular ({len(sorular)}) — "
                             "cevaplamak için: etiket.gunesler.info/app/bot/bilgi"]
            satirlar += [f"- {s.soru}" for s in sorular[:15]]

        satirlar += ["", "Panel: etiket.gunesler.info/app/bot"]
        govde = "\n".join(satirlar)

        if opts["kuru"]:
            self.stdout.write(govde)
            self.stdout.write(self.style.SUCCESS("\n(--kuru: e-posta gönderilmedi)"))
            return

        from catalog.services.bildirim import eposta_aktif, eposta_gonder
        if not eposta_aktif():
            self.stdout.write("E-posta yapılandırılmamış — özet gönderilemedi.")
            return
        if eposta_gonder("instALL ajan — sabah özeti", govde):
            self.stdout.write(self.style.SUCCESS("Sabah özeti gönderildi."))
        else:
            self.stderr.write("Gönderim başarısız.")


def _ai_ozet(konusmalar: dict, adlar: dict) -> str | None:
    """Konuşmaları Gemini'ye özetlet — konuşma başına 1 satır + memnuniyet emojisi.

    Model zinciri ajanla aynı (settings.AJAN_MODELLER); hepsi düşerse None,
    çağıran sayısal özete geri düşer. Fiyat/bilgi üretimi yok — yalnız özetleme,
    o yüzden tool gerekmez ve halüsinasyon riski düşüktür.
    """
    from django.conf import settings
    if not settings.AJAN_AKTIF:
        return None

    parcalar = []
    for (platform, kullanici), mesajlar in list(konusmalar.items())[:20]:
        ad = adlar.get((platform, kullanici)) or kullanici
        satirlar = []
        for m in mesajlar[-30:]:
            metin = (m.metin or "").strip()
            if not metin or metin.startswith("[buton]") or "[menü]" in metin \
                    or metin.startswith("[kart") or metin.startswith("[sohbeti"):
                continue
            kim = "Müşteri" if m.yon == "gelen" else "Bot"
            satirlar.append(f"{kim}: {metin[:200]}")
        if satirlar:
            parcalar.append(f"### {ad} ({platform})\n" + "\n".join(satirlar))
    if not parcalar:
        return None

    talimat = (
        "Aşağıda bir mobilya mağazasının bot konuşmaları var. Her konuşma için "
        "TEK satır yaz, şu biçimde:\n"
        "<emoji> <müşteri adı> (<platform>): <ne istedi / ne oldu>; "
        "gerekiyorsa 'yapılacak: ...' ekle.\n"
        "Emoji müşterinin memnuniyetini göstersin: 😊 memnun, 😐 nötr/belirsiz, "
        "😟 memnuniyetsiz/şikâyetçi. Satış fırsatı ya da şikâyet varsa mutlaka "
        "'yapılacak' yaz. Başka hiçbir şey yazma; madde imi, başlık, markdown yok."
    )
    icerik = talimat + "\n\n" + "\n\n".join(parcalar)

    import litellm
    litellm.suppress_debug_info = True
    for model in settings.AJAN_MODELLER:
        try:
            yanit = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": icerik[:30000]}],
                max_tokens=800, timeout=30)
            metin = (yanit.choices[0].message.content or "").strip()
            if metin:
                return metin
        except Exception:
            continue
    return None
