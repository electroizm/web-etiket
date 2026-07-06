"""Memnuniyetsizlik radarı — müşteri mesajında şikâyet sinyali arar.

Sinyal bulunursa İsmail'e ANINDA bildirim gider (geri arama talebiyle aynı
kanal: bot/bildirim.py → önce 0532 WhatsApp, olmazsa e-posta). Müşteri akışına
DOKUNMAZ: bot normal cevabını vermeye devam eder, alarm paralel gider —
amaç müşteri daha hattayken İsmail'in devreye girebilmesi.

Anahtar kelime tabanlı (bedava, Gemini kotası harcamaz); günlük derin analiz
sabah özetinde (bot_ozet) Gemini ile yapılır. Aynı müşteri için 6 saatte en
fazla 1 alarm (süreç içi sözlük; Render yeniden başlarsa sıfırlanır — kabul).
"""
from __future__ import annotations

import logging
import time

from bot.router import _duzle   # TR-normalize (aynı paket, tek kaynak)

log = logging.getLogger("bot.duygu")

# _duzle küçültüp Türkçe karakteri sadeleştirir → listede yalın biçim yeter.
# Yalın "iade"/"kotu" gibi tek kelimeler bilinçli DIŞARIDA: "iade şartları
# nedir" meşru bir sorudur, alarm gerektirmez. İfadeler şikâyet niyeti taşır.
SIKAYET_IFADELERI = (
    "sikayet", "rezalet", "berbat", "cok kotu", "kotu hizmet",
    "memnun degil", "memnun kalmad", "memnuniyetsiz",
    "iade et", "iade istiyorum", "iade edecegim", "geri iade",
    "parami geri", "para iadesi",
    "kirik", "kirildi", "hasarli", "hasar var", "cizik", "bozuk",
    "ariza", "eksik cikti", "eksik geldi", "eksik gonder",
    "yanlis urun", "yanlis geldi", "yanlis gonder",
    "gecikti", "gec kaldi", "hala gelmedi", "gelmedi", "nerede kaldi",
    "magdur", "pisman", "kandiril", "dolandir", "aldatil",
    "tuketici hakem", "tuketici mahkeme", "dava", "avukat", "sikayetvar",
    "ilgilenmiyor", "cevap vermiyor", "donus yapmadi", "donus yapilmadi",
)

_son_alarm: dict[tuple[str, str], float] = {}
ALARM_ARALIGI_SN = 6 * 3600


def sinyal_bul(metin: str) -> str | None:
    """Metinde şikâyet ifadesi var mı? Varsa yakalanan ifadeyi döndür."""
    duz = " " + _duzle(metin) + " "
    for ifade in SIKAYET_IFADELERI:
        if ifade in duz:
            return ifade
    return None


def kontrol_et(platform: str, kullanici: str, metin: str) -> None:
    """Serbest metni tara; sinyal varsa yetkiliye alarm gönder. Hata yutulur."""
    try:
        ifade = sinyal_bul(metin or "")
        if not ifade:
            return
        anahtar = (platform, kullanici)
        simdi = time.time()
        if simdi - _son_alarm.get(anahtar, 0) < ALARM_ARALIGI_SN:
            return   # aynı müşteri için yakın zamanda alarm gitti
        _son_alarm[anahtar] = simdi
        from bot import bildirim
        bildirim.memnuniyetsizlik_bildir(platform, kullanici, metin, ifade)
        log.info("memnuniyetsizlik alarmı: %s/%s (%s)", platform, kullanici, ifade)
    except Exception:
        log.exception("memnuniyetsizlik kontrolü başarısız")
