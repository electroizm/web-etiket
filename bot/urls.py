"""Bot (WhatsApp/Instagram) webhook rotaları — kök URL'ye bağlanır.

Meta Callback URL:  https://etiket.gunesler.info/webhook
Sağlık/ping ucu:    https://etiket.gunesler.info/saglik
"""
from django.urls import path

from . import views

app_name = 'bot'

urlpatterns = [
    path('webhook', views.webhook, name='webhook'),
    path('saglik', views.saglik, name='saglik'),
    path('ara', views.ara, name='ara'),   # 📞 Sesli arama butonu → tel: yönlendirme
]
