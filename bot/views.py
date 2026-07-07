"""WhatsApp + Instagram webhook uçları (Django).

Tek uç (`/webhook`) hem Meta'nın GET el sıkışmasını hem gelen mesaj POST'unu
karşılar. WhatsApp ve Instagram aynı uca düşer; gövdeye göre ayrıştırılır.

Not: Meta CSRF token göndermez → `csrf_exempt`. Meta 200 dışında bir yanıtta
olayı tekrar tekrar gönderir; bu yüzden işleme hatalarını yutup daima 200 döneriz.
"""
import json
import logging
import threading

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from bot import ig_presenter, kisi, meta_client, wa_presenter
from bot.kayit import kaydet, ozet_gelen, ozet_giden
from bot.router import yanit_uret
from bot.webhook_core import extract_events, extract_yorumlar, verify_challenge

log = logging.getLogger("bot")

# Son webhook hatası — Render loguna erişim olmadan /saglik'tan teşhis için.
WEBHOOK_SON_HATA: str | None = None
# Son N webhook POST'unun HAM gövdesi (ayrıştırma başarısız/olay 0 çıksa bile).
# Tek slot WA durum bildirimleriyle (sık gelir) hemen ezilebiliyordu — halka
# tampon (ring buffer) son birkaç isteği tutar. Geçici teşhis amaçlı —
# customer içeriği taşıyabileceği için VERIFY_TOKEN ile korunur.
WEBHOOK_SON_GOVDELER: list[str] = []
_WEBHOOK_GOVDE_MAKS = 8


@require_http_methods(["GET"])
def saglik(request):
    """Basit sağlık ucu — izleme/ping için."""
    return JsonResponse({
        "durum": "ayakta",
        "surum": settings.APP_SURUM,
        "dry_run": settings.BOT_DRY_RUN,
        "dry_run_ig": settings.BOT_DRY_RUN_IG,
        "ajan": settings.AJAN_MODEL if settings.AJAN_AKTIF else "kapalı",
        "ajan_son_hata": _ajan_son_hata(),
        "ses_son_hata": _ses_son_hata(),
        "gorsel_son_hata": _gorsel_son_hata(),
        "webhook_son_hata": WEBHOOK_SON_HATA,
        "ig_gonderim_son_hata": meta_client.IG_SON_GONDERIM_HATA,
        # İçerik yok (KVKK) — sadece "en son ne zaman bir webhook POST'u geldi" saati.
        # Uzun süre güncellenmiyorsa Meta bize hiç istek atmıyor demektir (kod değil, ayar sorunu).
        "webhook_son_govde_saat": (WEBHOOK_SON_GOVDELER[-1].split(" ", 1)[0]
                                   if WEBHOOK_SON_GOVDELER else None),
        "ig_token": _ig_token_bilgi(),
    })


def _ajan_son_hata():
    from bot import ajan
    return ajan.SON_HATA


def _gorsel_son_hata():
    from bot import gorsel
    return gorsel.SON_HATA


def _ig_token_bilgi():
    """IG token'ının son yenilenme + bitiş tarihi (app_ayarlari'ndan). Oto-yenileme
    çalışıyor mu ve token ne zaman doluyor — Render loguna bakmadan teşhis için."""
    from datetime import datetime, timezone
    try:
        from catalog.database import SessionLocal
        from catalog.services.ayarlar import get_ayar
        session = SessionLocal()
        try:
            yenilenme = get_ayar(session, "ig_token_yenilenme")
            expires = get_ayar(session, "ig_token_expires")
        finally:
            session.close()
    except Exception:
        return None
    if not yenilenme and not expires:
        return "henüz oto-yenileme yapılmadı (env token kullanılıyor)"
    kalan = None
    try:
        if expires and expires != "bilinmiyor":
            fark = datetime.fromisoformat(expires) - datetime.now(timezone.utc)
            kalan = f"{fark.days} gün"
    except Exception:
        pass
    return {"yenilenme": yenilenme, "bitis": expires, "kalan": kalan}


def _ses_son_hata():
    from bot import ses
    return ses.SON_HATA


@require_http_methods(["GET"])
def saglik_wa(request):
    """WhatsApp numarasının Cloud API durumu (Graph API'den) — teşhis.

    'Bu kişi artık WhatsApp kullanmıyor' hatası numaranın bağlantısı mı düştü,
    yoksa sadece o cihazın önbelleği mi — bunu ayırmak için kullanılır.
    """
    import requests
    if settings.BOT_DRY_RUN:
        return JsonResponse({"hata": "META_TOKEN yok (dry_run)"}, status=200)
    url = (f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}"
           f"/{settings.PHONE_NUMBER_ID}")
    try:
        r = requests.get(url, params={
            "fields": "display_phone_number,verified_name,code_verification_status,"
                      "platform_type,quality_rating,name_status,status,messaging_limit_tier",
        }, headers={"Authorization": f"Bearer {settings.META_TOKEN}"}, timeout=10)
        return JsonResponse({"http": r.status_code, "graph": r.json()}, status=200)
    except requests.RequestException as e:
        return JsonResponse({"hata": str(e)}, status=200)


@require_http_methods(["GET"])
def ara(request):
    """📞 'Sesli arama yap' butonunun hedefi — telefonun arama ekranını açar.

    WA/IG butonları tel: linki kabul etmez (yalnız https); bu sayfa açılır açılmaz
    tel: linkine yönlendirir, olmazsa büyük 'Ara' düğmesi gösterir.
    """
    tel = "+905321370627"
    html = f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doğtaş Çevreyolu — Ara</title>
<style>
  body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
       justify-content:center;min-height:90vh;gap:18px;background:#0b1020;color:#fff;margin:0}}
  a.ara{{background:#22c55e;color:#fff;text-decoration:none;font-size:1.4rem;font-weight:700;
       padding:18px 34px;border-radius:999px}}
  p{{opacity:.7;text-align:center;padding:0 24px}}
</style></head><body>
<h2>📞 Doğtaş Çevreyolu</h2>
<a class="ara" href="tel:{tel}">0532 137 06 27'yi Ara</a>
<p>Arama ekranı otomatik açılmadıysa yukarıdaki düğmeye dokunun.</p>
<script>location.href="tel:{tel}";</script>
</body></html>"""
    return HttpResponse(html)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request):
    # ── GET: Meta doğrulaması (hub.challenge'ı geri yaz) ──
    if request.method == "GET":
        status, govde = verify_challenge(
            request.GET.get("hub.mode", ""),
            request.GET.get("hub.verify_token", ""),
            request.GET.get("hub.challenge", ""),
            settings.VERIFY_TOKEN,
        )
        return HttpResponse(govde, status=status, content_type="text/plain")

    # ── POST: gelen olayları işle ──
    # Meta 200 dışında her yanıtı "başarısız" sayıp olayı TEKRAR gönderir; bu yüzden
    # NE OLURSA OLSUN 200 döneriz (senkron yolda beklenmedik hata bile olsa).
    global WEBHOOK_SON_HATA
    from datetime import datetime
    raw = request.body or b"{}"
    # Ayrıştırma başarısız olsa/olay 0 çıksa bile HAM veriyi sakla — Meta'nın
    # gerçekten ne gönderdiğini görmeden ayrıştırma kodunu doğru yazamayız.
    WEBHOOK_SON_GOVDELER.append(
        f"{datetime.now():%H:%M:%S} " + raw.decode("utf-8", errors="replace")[:2000])
    del WEBHOOK_SON_GOVDELER[:-_WEBHOOK_GOVDE_MAKS]
    try:
        govde = json.loads(raw)
        # AI ajan cevabı 5-25 sn sürebilir → işleme arka plan thread'inde, 200 hemen döner.
        threading.Thread(target=_olaylari_isle, args=(govde,), daemon=True).start()
    except Exception as e:
        import traceback
        WEBHOOK_SON_HATA = f"{datetime.now():%H:%M:%S} {type(e).__name__}: {e}"
        log.exception("webhook senkron hata")
        traceback.print_exc()
    return HttpResponse(status=200)


@require_http_methods(["GET"])
def webhook_ham(request):
    """Son birkaç webhook POST'unun ham gövdesi — geçici teşhis ucu.

    Müşteri mesaj içeriği taşıyabileceği için VERIFY_TOKEN ile korunur
    (?token=... aynı gizli kelime, Meta'ya zaten veriyoruz).
    ?platform=instagram|whatsapp ile filtrelenebilir (object alanına bakar)."""
    if request.GET.get("token") != settings.VERIFY_TOKEN:
        return HttpResponse(status=403)
    govdeler = WEBHOOK_SON_GOVDELER
    platform = request.GET.get("platform")
    if platform:
        anahtar = "instagram" if platform == "instagram" else "whatsapp"
        govdeler = [g for g in govdeler if anahtar in g]
    metin = "\n\n---\n\n".join(reversed(govdeler)) or "(henüz webhook POST'u gelmedi)"
    return HttpResponse(metin, content_type="text/plain; charset=utf-8")


def _olaylari_isle(govde: dict) -> None:
    """Webhook olaylarını işle (arka plan thread'i). Hatalar yutulur, loglanır."""
    global WEBHOOK_SON_HATA
    try:
        olaylar = extract_events(govde)
        yorumlar = extract_yorumlar(govde)
    except Exception as e:
        from datetime import datetime
        WEBHOOK_SON_HATA = f"{datetime.now():%H:%M:%S} extract_events {type(e).__name__}: {e}"
        log.exception("webhook: extract_events hatası")
        return

    # 🏷️ Yorumdan-DM: tetikleyici kelime içeren yorumlara private reply.
    for y in yorumlar:
        try:
            from bot import yorum as yorum_modul
            yorum_modul.isle(y)
        except Exception as e:
            from datetime import datetime
            WEBHOOK_SON_HATA = f"{datetime.now():%H:%M:%S} yorum işleme {type(e).__name__}: {e}"
            log.exception("yorum işlenemedi: %s", y)

    for olay in olaylar:
        try:
            # 🎙️ Sesli mesaj → transkript (Gemini). Başarılıysa serbest metin gibi
            # akar; kayıtta "[ses] ..." izi kalır (ozet_gelen). Çözülemezse aşağıda
            # kibar bir özür mesajı gönderilir.
            if olay.ses and not olay.metin and not olay.secim:
                from bot import ses as ses_modul
                olay.metin = ses_modul.coz(olay.ses)
            # 🖼️ Görsel / story yanıtı → görseldeki metin (ürün adı) okunur,
            # müşterinin yazdığıyla birleştirilir: story'de "LUMERIS Köşe Takımı"
            # + müşteri "fiyat" → "LUMERIS Köşe Takımı fiyat" → normal akış.
            if olay.gorsel and not olay.secim:
                from bot import gorsel as gorsel_modul
                okunan = gorsel_modul.coz(olay.gorsel)
                if okunan:
                    olay.metin = (f"{okunan} {olay.metin}".strip()
                                  if olay.metin else okunan)
            kaydet(olay.platform, olay.gonderen, "gelen", ozet_gelen(olay))
            # Profil bilgisini güncelle (id yerine isim/foto göstermek için).
            if olay.platform == "whatsapp":
                kisi.guncelle_wa(olay.gonderen, olay.gonderen_ad)
            else:
                kisi.guncelle_ig(olay.gonderen)
            # Panelde "çözüldü" işaretli bir konuşmaya yeni mesaj geldiyse damgayı
            # kaldır — müşteri tekrar yazdıysa konu yeniden açık (bizden bilgi bekler).
            kisi.konusma_yeniden_ac(olay.platform, olay.gonderen)
            # ⚠️ Memnuniyetsizlik radarı: şikâyet sinyali varsa İsmail'e anında
            # bildirim (müşteri akışını değiştirmez, paralel gider).
            if olay.metin and not olay.secim:
                from bot import duygu
                duygu.kontrol_et(olay.platform, olay.gonderen, olay.metin)
            if olay.ses and not olay.metin and not olay.secim:
                # Ses indirilemedi/çözülemedi → menüye zorlamak yerine dürüst cevap.
                P = ig_presenter if olay.platform == "instagram" else wa_presenter
                gonder = (meta_client.gonder_instagram if olay.platform == "instagram"
                          else meta_client.gonder_whatsapp)
                mesaj = P.metin_mesaji("🎙️ Ses kaydınızı çözemedim, kusura bakmayın. "
                                       "Yazarak sorabilir misiniz?")
                gonder(olay.gonderen, mesaj)
                kaydet(olay.platform, olay.gonderen, "giden", ozet_giden(mesaj))
                continue
            if olay.gorsel and not olay.metin and not olay.secim:
                # Görsel okunamadı (metin de yok) → menü yerine dürüst cevap.
                P = ig_presenter if olay.platform == "instagram" else wa_presenter
                gonder = (meta_client.gonder_instagram if olay.platform == "instagram"
                          else meta_client.gonder_whatsapp)
                mesaj = P.metin_mesaji("🖼️ Görseldeki ürünü tanıyamadım, kusura "
                                       "bakmayın. Ürünün adını yazar mısınız?")
                gonder(olay.gonderen, mesaj)
                kaydet(olay.platform, olay.gonderen, "giden", ozet_giden(mesaj))
                continue
            if olay.platform == "instagram":
                cevap = yanit_uret(olay.tetik, P=ig_presenter,
                                   platform=olay.platform, kullanici=olay.gonderen)
                gonder = meta_client.gonder_instagram
            else:
                cevap = yanit_uret(olay.tetik, P=wa_presenter,
                                   platform=olay.platform, kullanici=olay.gonderen)
                gonder = meta_client.gonder_whatsapp
            # Presenter tek mesaj (dict) ya da art arda birkaç mesaj (list) dönebilir.
            for mesaj in ([cevap] if isinstance(cevap, dict) else cevap):
                gonder(olay.gonderen, mesaj)
                kaydet(olay.platform, olay.gonderen, "giden", ozet_giden(mesaj))
        except Exception as e:
            from datetime import datetime
            WEBHOOK_SON_HATA = f"{datetime.now():%H:%M:%S} işleme {type(e).__name__}: {e}"
            log.exception("olay işlenemedi: %s", olay)
