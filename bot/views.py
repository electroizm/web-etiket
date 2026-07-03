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
        "dry_run": settings.BOT_DRY_RUN,
        "dry_run_ig": settings.BOT_DRY_RUN_IG,
    })


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
                mesaj = yanit_uret(olay.tetik, P=ig_presenter)
                meta_client.gonder_instagram(olay.gonderen, mesaj)
            else:
                mesaj = yanit_uret(olay.tetik, P=wa_presenter)
                meta_client.gonder_whatsapp(olay.gonderen, mesaj)
            kaydet(olay.platform, olay.gonderen, "giden", ozet_giden(mesaj))
        except Exception:
            log.exception("olay işlenemedi: %s", olay)

    # Meta 200 bekler; yoksa olayı tekrar gönderir.
    return HttpResponse(status=200)
