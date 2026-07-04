"""WhatsApp + Instagram webhook uçları (Django).

Tek uç (`/webhook`) hem Meta'nın GET el sıkışmasını hem gelen mesaj POST'unu
karşılar. WhatsApp ve Instagram aynı uca düşer; gövdeye göre ayrıştırılır.

Not: Meta CSRF token göndermez → `csrf_exempt`. Meta 200 dışında bir yanıtta
olayı tekrar tekrar gönderir; bu yüzden işleme hatalarını yutup daima 200 döneriz.
"""
import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from bot import ig_presenter, meta_client, wa_presenter
from bot.kayit import kaydet, ozet_gelen, ozet_giden
from bot.router import yanit_uret
from bot.webhook_core import extract_events, verify_challenge

log = logging.getLogger("bot")


@require_http_methods(["GET"])
def saglik(request):
    """Basit sağlık ucu — izleme/ping için."""
    return JsonResponse({
        "durum": "ayakta",
        "surum": settings.APP_SURUM,
        "dry_run": settings.BOT_DRY_RUN,
        "dry_run_ig": settings.BOT_DRY_RUN_IG,
    })


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
    try:
        govde = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        log.warning("webhook: geçersiz JSON gövdesi")
        return HttpResponse(status=200)

    for olay in extract_events(govde):
        try:
            kaydet(olay.platform, olay.gonderen, "gelen", ozet_gelen(olay))
            if olay.platform == "instagram":
                cevap = yanit_uret(olay.tetik, P=ig_presenter)
                gonder = meta_client.gonder_instagram
            else:
                cevap = yanit_uret(olay.tetik, P=wa_presenter)
                gonder = meta_client.gonder_whatsapp
            # Presenter tek mesaj (dict) ya da art arda birkaç mesaj (list) dönebilir.
            for mesaj in ([cevap] if isinstance(cevap, dict) else cevap):
                gonder(olay.gonderen, mesaj)
                kaydet(olay.platform, olay.gonderen, "giden", ozet_giden(mesaj))
        except Exception:
            log.exception("olay işlenemedi: %s", olay)

    # Meta 200 bekler; yoksa olayı tekrar gönderir.
    return HttpResponse(status=200)
