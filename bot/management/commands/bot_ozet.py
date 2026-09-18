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

        # İsmail'e giden bildirimler (alarm/sistem uyarısı) müşteri konuşması değildir.
        alarmlar = sum(1 for r in rows
                       if r.kullanici == YETKILI_WA and r.yon == "giden"
                       and (r.metin or "").startswith("⚠️ MEMNUNİYETSİZLİK"))
        # Panel deneme sohbeti de müşteri değildir (bkz. bot.kayit.DENEME_KULLANICI).
        from bot.kayit import deneme_mi
        rows = [r for r in rows
                if r.kullanici != YETKILI_WA and not deneme_mi(r.kullanici)]

        konusmalar: dict[tuple[str, str], list] = {}
        for r in rows:
            konusmalar.setdefault((r.platform, r.kullanici), []).append(r)

        # Instagram anahtarı sağlam mı? (2026-09-18 eklendi) Token 05.09'da
        # doldu ve bot Instagram'da 13 GÜN sessiz kaldı; kimse fark etmedi
        # çünkü hiçbir yerde uyarı çıkmıyordu. Artık günlük özet bunu söylüyor
        # ve uyarı VARSA özet sessiz kalmıyor — asıl tehlike zaten konuşmanın
        # kesilmesi, yani "söylenecek bir şey yok" hâli.
        ig_uyari = _ig_token_uyarisi()

        if not konusmalar and not sorular and not ig_uyari:
            self.stdout.write("Son 24 saatte konuşma yok, açık soru yok — sessiz.")
            return

        gelen_sayisi = sum(1 for r in rows if r.yon == "gelen")
        simdi = datetime.now()
        satirlar = [
            f"🤖 instALL ajan — sabah özeti ({simdi:%d.%m.%Y %H:%M})",
            "",
            f"Konuşma: {len(konusmalar)} · Gelen mesaj: {gelen_sayisi}"
            + (f" · ⚠️ Memnuniyetsizlik alarmı: {alarmlar}" if alarmlar else ""),
        ]
        if ig_uyari:
            satirlar += ["", ig_uyari]      # en üstte: kanal kapalıysa önce bu

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

        # Haftalık gözden geçirme — YALNIZ pazartesi. Her gün gitse gürültü
        # olur ve okunmaz hâle gelir; haftada bir bakış zaten yeterli
        # (bkz. projects/plan-haftalik-gozden-gecirme). Hata özeti düşürmesin.
        if simdi.weekday() == 0 or opts["kuru"]:
            try:
                from bot import gozden_gecirme
                gg_satir = gozden_gecirme.haftalik_satirlar(7)
                if gg_satir:
                    satirlar += [""] + gg_satir
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "haftalık gözden geçirme satırı üretilemedi")

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

    from bot import kota
    for model in settings.AJAN_MODELLER:
        try:
            yanit = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": icerik[:30000]}],
                max_tokens=800, timeout=30)
            metin = (yanit.choices[0].message.content or "").strip()
            kota.say(model, "ozet", "basari" if metin else "bos")
            if metin:
                return metin
        except Exception as e:
            kotali = "429" in str(e) or "quota" in str(e).lower()
            kota.say(model, "ozet", "kota" if kotali else "hata")
            continue
    return None


def _ig_token_uyarisi() -> str | None:
    """Instagram anahtarı çalışıyor mu? Sorun varsa özete konacak uyarı satırı.

    Neden VAR (2026-09-18): IG token'ı 05.09'da doldu, Instagram tarafı 13 gün
    boyunca sessizce cevapsız kaldı ve hiçbir yerde uyarı çıkmadı — /saglik
    ucunda yazıyordu ama oraya kimse bakmıyor. Haftalık yenileme görevi de
    kurulmamıştı, dolayısıyla "yenilenemedi" alarmı hiç tetiklenmedi.

    Depolanan bitiş tarihine GÜVENMEZ, anahtarı Meta'ya SORAR: kayıt eksik ya
    da eski olabilir, tek doğru kaynak Meta'nın cevabı. Ek olarak bitiş tarihi
    biliniyorsa 14 günden az kalınca erken uyarı verir.

    Hiçbir hata özeti düşürmez: sorun çıkarsa None döner (özet normal gider).
    """
    try:
        import requests

        from bot import meta_client
        token = meta_client.aktif_ig_token()
        if not token:
            return ("🔴 Instagram anahtarı YOK — Instagram mesajlarına cevap "
                    "gidemiyor. Yeni anahtar alıp şu komutla besle: "
                    "manage.py ig_token_yenile --tohum <TOKEN>")
        r = requests.get("https://graph.instagram.com/me",
                         params={"fields": "user_id", "access_token": token},
                         timeout=15)
        hata = (r.json() or {}).get("error") if r.status_code != 200 else None
        if hata:
            return ("🔴 Instagram anahtarı GEÇERSİZ — Instagram'a cevap "
                    f"GİTMİYOR ({str(hata.get('message'))[:120]}). Yeni anahtar "
                    "alıp: manage.py ig_token_yenile --tohum <TOKEN>")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("IG token kontrolü yapılamadı")
        return None

    # Anahtar geçerli — bitişe az kaldıysa erken uyar (haftalık görev çalışmıyor
    # olabilir; 14 gün elle müdahale için bol zaman bırakır).
    try:
        from catalog.database import SessionLocal
        from catalog.services.ayarlar import get_ayar
        session = SessionLocal()
        try:
            expires = get_ayar(session, "ig_token_expires")
        finally:
            session.close()
        if expires and expires != "bilinmiyor":
            kalan = (datetime.fromisoformat(expires)
                     - datetime.now(timezone.utc)).days
            if kalan <= 14:
                return (f"🟠 Instagram anahtarı {kalan} gün sonra doluyor — "
                        "haftalık yenileme görevi çalışmıyor olabilir "
                        "(run_ig_token_yenile.bat).")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("IG token bitiş tarihi okunamadı")
    return None
