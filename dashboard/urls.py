from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('bot/', views.bot_konusmalar, name='bot_konusmalar'),
    path('bot/cevap/', views.bot_cevap, name='bot_cevap'),
    path('bot/durum/', views.bot_durum, name='bot_durum'),
    path('bot/sil/', views.bot_sil, name='bot_sil'),
    path('bot/bilgi/', views.bot_bilgi, name='bot_bilgi'),
    path('ayarlar/', views.ayarlar, name='ayarlar'),
    path('ayarlar/slogan/', views.ayarlar_slogan, name='ayarlar_slogan'),
    path('ayarlar/yerli-uretim/', views.ayarlar_yerli_uretim, name='ayarlar_yerli_uretim'),
    path('teshir/', views.teshir, name='teshir'),
    path('teshir/secenekler/', views.teshir_secenekler, name='teshir_secenekler'),
    path('urunler/', views.urunler_list, name='urunler_list'),
    path('urun/yeni/', views.urun_yeni, name='urun_yeni'),
    path('etiket-yazdir/', views.etiket_yazdir, name='etiket_yazdir'),
    path('etiket-yazdir/pdf/', views.etiket_yazdir_pdf, name='etiket_yazdir_pdf'),
    path('kategoriler/', views.kategoriler_list, name='kategoriler_list'),
    path('kategoriler/<int:kategori_id>/', views.kategori_detail, name='kategori_detail'),
    path('koleksiyon/<int:koleksiyon_id>/rename/', views.koleksiyon_rename, name='koleksiyon_rename'),
    path('koleksiyon/<int:koleksiyon_id>/bayrak/', views.koleksiyon_bayrak_toggle, name='koleksiyon_bayrak'),
    path('koleksiyon/<int:koleksiyon_id>/takim-candidates/', views.koleksiyon_takim_candidates, name='koleksiyon_takim_candidates'),
    path('koleksiyon/<int:koleksiyon_id>/takim/', views.koleksiyon_takim_set, name='koleksiyon_takim_set'),
    path('urun/<int:urun_id>/rename/', views.urun_rename, name='urun_rename'),
    path('urun/<int:urun_id>/sil/', views.urun_sil, name='urun_sil'),
    path('koleksiyon/<int:koleksiyon_id>/urun/<int:urun_id>/etiket-secimi/', views.koleksiyon_urun_secim, name='koleksiyon_urun_secim'),
    path('koleksiyon/<int:koleksiyon_id>/urun/<int:urun_id>/kaldir/', views.koleksiyon_urun_kaldir, name='koleksiyon_urun_kaldir'),
    path('koleksiyon/<int:koleksiyon_id>/urun-ekle/', views.koleksiyon_urun_ekle, name='koleksiyon_urun_ekle'),
    path('koleksiyon/<int:koleksiyon_id>/urun-ekle/search/', views.koleksiyon_urun_ekle_search, name='koleksiyon_urun_ekle_search'),
    path('koleksiyon/<int:koleksiyon_id>/etiket-pdf/', views.koleksiyon_etiket_pdf, name='koleksiyon_etiket_pdf'),

    # Kombinasyon
    path('koleksiyon/<int:koleksiyon_id>/kombinasyon/yeni/', views.kombinasyon_yeni, name='kombinasyon_yeni'),
    path('koleksiyon/<int:koleksiyon_id>/kombinasyon/otomatik/', views.kombinasyon_otomatik, name='kombinasyon_otomatik'),
    path('kombinasyon/<int:kombinasyon_id>/duzenle/', views.kombinasyon_duzenle, name='kombinasyon_duzenle'),
    path('kombinasyon/<int:kombinasyon_id>/sil/', views.kombinasyon_sil_view, name='kombinasyon_sil'),
    path('kombinasyon/<int:kombinasyon_id>/etiket-toggle/', views.kombinasyon_etiket_toggle, name='kombinasyon_etiket_toggle'),
    path('koleksiyon/<int:koleksiyon_id>/kombinasyon-sira/', views.kombinasyon_sira_toplu, name='kombinasyon_sira_toplu'),
    path('koleksiyon/<int:koleksiyon_id>/urun-sira/', views.urun_sira_toplu, name='urun_sira_toplu'),
]
