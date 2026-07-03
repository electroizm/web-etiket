from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView, TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('bot.urls')),   # /webhook (Meta) + /saglik (ping)
    path('', RedirectView.as_view(pattern_name='dashboard:home', permanent=False)),
    path('gizlilik/', TemplateView.as_view(template_name='gizlilik.html')),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('app/', include('dashboard.urls', namespace='dashboard')),
    path('api/', include('catalog.urls', namespace='catalog_api')),
]
