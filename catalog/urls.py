"""Dış API rotaları (catalog). `/api/` altında bağlanır — bkz. etiket_project/urls.py.

Akış: kategoriler → koleksiyonlar(kategori_id) → kombinasyonlar(koleksiyon_id) → kombinasyon(id).
"""
from django.urls import path

from . import api_views

app_name = 'catalog_api'

urlpatterns = [
    path('kategoriler/', api_views.kategoriler, name='kategoriler'),
    path('koleksiyonlar/', api_views.koleksiyonlar, name='koleksiyonlar'),
    path('kombinasyonlar/', api_views.kombinasyonlar, name='kombinasyonlar'),
    path('kombinasyon/', api_views.kombinasyon, name='kombinasyon'),
    path('fiyat/', api_views.fiyat, name='fiyat'),
]
