"""SQLAlchemy modelleri (Django ORM ile karışmasın diye `sa_models` adı verildi)."""
from catalog.sa_models.ayar import AppAyari
from catalog.sa_models.bot_bilgi import BotBilgi, BotSoru
from catalog.sa_models.bot_kisi import BotKisi
from catalog.sa_models.bot_mesaj import BotMesaj
from catalog.sa_models.kategori import Kategori, KategoriKurali, Koleksiyon
from catalog.sa_models.kombinasyon import (
    KategoriKombinasyonKurali,
    Kombinasyon,
    KombinasyonUrun,
)
from catalog.sa_models.urun import Fiyat, Urun, urun_koleksiyon

__all__ = [
    "AppAyari",
    "BotBilgi",
    "BotSoru",
    "BotKisi",
    "BotMesaj",
    "Kategori",
    "KategoriKurali",
    "Koleksiyon",
    "Urun",
    "Fiyat",
    "urun_koleksiyon",
    "Kombinasyon",
    "KombinasyonUrun",
    "KategoriKombinasyonKurali",
]
