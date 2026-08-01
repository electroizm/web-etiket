"""Gözden geçirme — botun tökezlediği anları konuşma kayıtlarından çıkarır.

Neden var (2026-08-01): o gün bulunan üç hatanın ÜÇÜ de İsmail'in panele bakıp
"bu neden böyle?" demesiyle çıktı; hiçbiri testlerde görünmüyordu. Gerçek
müşteri konuşması elimizdeki en güçlü hata bulma yöntemi ama tesadüfe bağlıydı.
Bu modül o bakışı otomatikleştirir.

Tamamen KURAL TABANLI — LLM yok. Gemini kotası dolu olsa da çalışır, aynı veri
için hep aynı sonucu verir, test edilebilir. (Sıcak müşteri tespiti AYRI bir iş
ve zaten var: bot/firsat.py. Burası satış değil ARIZA arar.)

Süzgeçler ölçümle tasarlandı (995 mesaj / 92 konuşma):
- Ham "ürün bulunamadı" 28 olayın çoğu ("park yeri var mı", "elden taksit")
  botun DOĞRU cevabıydı. Katalog adı şartı yanlış alarmın %72'sini kesti ve
  kalanda İKİ GERÇEK kaçırılmış satış çıktı (MASSIMO i/İ tuzağı, BEND'e
  "Luxembourg bulunmuyor" cevabı).
- Ham "müşteri son yazan, cevap yok" olaylarının çoğu [yorum] kaydıydı; yoruma
  DM atılamaz, cevapsızlık DOĞRU davranıştır (bkz. bot/views.py yorum akışı).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

log = logging.getLogger("bot.gozden_gecirme")

# Önem: 1 = müşteri cevapsız kaldı, 2 = satış kaçmış olabilir, 3 = incele.
KRITIK, YUKSEK, ORTA = 1, 2, 3

TURLER = {
    "cevapsiz":       ("🔴", "Müşteri cevapsız kaldı", KRITIK),
    "pazarlik_oldu":  ("🤝", "Pazarlık isteğine fiyat verilmedi", YUKSEK),
    "urun_kacirildi": ("📦", "Katalogda VAR ama 'yok' denmiş", YUKSEK),
    "uydurma_ad":     ("👻", "Botun uydurduğu ürün adı", YUKSEK),
    "yetkiliye_atti": ("🙋", "Yetkiliye yönlendirdi", ORTA),
}

_FIYAT = re.compile(r"\d{1,3}(?:\.\d{3})+\s*TL")
# Aday ürün adı: cümle başındaki HER büyük harfli kelime değil, YALNIZ ürün adı
# görevinde duran kelime. İlk deneme "Merhabalar", "Mağazamızda" gibi sıradan
# kelimeleri uydurma ad sanıyordu; ayırt edici olan ardından gelen kalıptır
# ("Luxembourg ADINDA bir yatak odası koleksiyonumuz bulunmuyor").
_ADAY_AD = re.compile(
    r"\b([A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]{3,})\s+"
    r"(?:ad[ıi]nda|ad[ıi]yla|isimli|isminde|seri(?:si|sinde|miz)|"
    r"koleksiyonu(?:muz)?|modeli|tak[ıi]m[ıi])\b")


def _kelimeler(metin: str) -> set[str]:
    """Sade kelime kümesi — ALT DİZE eşleşmesini engeller.

    'rene' katalogda bir seri; 'öğRENEbilir miyim' cümlesinde alt dize olarak
    geçtiği için o soru "ürün kaçırıldı" sanılıyordu. Karşılaştırma artık
    kelime bazında.
    """
    from catalog.services import menu_veri
    return {k for k in re.split(r"[^0-9a-zçğıöşü]+", menu_veri._duz(metin)) if k}


def _ad_geciyor_mu(ad: str, kelimeler: set[str]) -> bool:
    """Çok kelimeli seri adı ('charm genc') için TÜM parçaları ara."""
    parca = [p for p in ad.split() if p]
    return bool(parca) and all(p in kelimeler for p in parca)

_YOK_KALIPLARI = ("bulunmuyor", "bulunamadı", "mevcut değil", "kayıtlı değil")
# Pazarlık niyeti — bot/firsat.py ile aynı sözlük (tek doğru kaynak orası).
_PAZARLIK = ("indirim", "son fiyat", "en son", "pazarlık", "pazarlik",
             "ucuzlat", "olmaz mı", "olmaz mi", "kaça olur", "kaca olur")
# Merdiven bittiğinde verilen DOĞRU cevap — pazarlık arızası sayılmamalı.
_MERDIVEN_BITTI = ("en son fiyat", "son fiyatımız", "daha fazla in",
                   "verebileceğimiz en")


def _katalog_adlari(session) -> set[str]:
    """Botun MEŞRU olarak bilebileceği tüm ürün/seri adları (sade, 4+ harf).

    Üç kaynak da şart — biri eksik olursa "uydurma ad" sinyali yanlış alarm
    üretir. Canlıda görüldü: bot "Melori serisinde sehpa yok" dedi, MELORI
    koleksiyon tablosunda YOK ama TEŞHİR kaydı olarak var; teşhir eklenmeseydi
    doğru cevap "uydurma" diye işaretlenecekti.

    4 harf altı atlanır: "eva", "loft" gibi kısa adlar günlük konuşmada
    tesadüfen geçip yanlış alarm üretiyor.
    """
    from sqlalchemy import select

    from catalog.sa_models import Koleksiyon, Teshir, Urun
    from catalog.services import menu_veri

    def _al(*parcalar):
        for p in parcalar:
            d = menu_veri._duz((p or "").strip())
            if len(d) >= 4:
                adlar.add(d)

    adlar: set[str] = set()
    for k in session.scalars(select(Koleksiyon)).all():
        _al(k.ad)
    for t in session.scalars(select(Teshir)).all():
        _al(t.koleksiyon_adi, t.baslik)
    # Ürün adının İLK kelimesi seri adıdır ("MARLIN Üçlü Koltuk" → MARLIN).
    for u in session.scalars(select(Urun.urun_adi_tam)).all():
        parca = (u or "").strip().split()
        if parca:
            _al(parca[0])
    return adlar


def _musteri_sorusu_mu(metin: str) -> bool:
    """[yorum] kayıtları müşterinin bize yazdığı mesaj DEĞİLDİR.

    Yorumdan-DM akışında hem müşterinin yorumu hem botun yorum altı notu bu
    önekle kaydediliyor; ikisi de "soru" sayılmamalı (bkz. modül docstring'i).
    """
    t = (metin or "").strip()
    return bool(t) and not t.startswith(("[yorum", "[görsel — çözülemedi]",
                                         "[ses — çözülemedi]"))


def _soru_metni(metin: str) -> str:
    """Görsel/ses mesajlarında okunan metni soru olarak kullan."""
    t = (metin or "").strip()
    for onek in ("[görsel]", "[ses]"):
        if t.startswith(onek):
            return t[len(onek):].strip()
    return t


def olaylar(gun_sayisi: int = 7) -> list[dict]:
    """Son N günün konuşmalarından arıza olaylarını çıkar (önem sırasında)."""
    from sqlalchemy import select

    from bot.router import AI_KAPALI_METNI, YETKILI_URL
    from catalog.database import SessionLocal
    from catalog.services import menu_veri

    esik = datetime.now(timezone.utc) - timedelta(days=gun_sayisi)
    ozur = AI_KAPALI_METNI[:40]
    session = SessionLocal()
    try:
        from catalog.sa_models import BotMesaj
        satirlar = list(session.scalars(
            select(BotMesaj).where(BotMesaj.olusturma >= esik)
            .order_by(BotMesaj.id)).all())
        adlar = _katalog_adlari(session)
    finally:
        session.close()

    sohbetler: dict[tuple[str, str], list] = {}
    for m in satirlar:
        sohbetler.setdefault((m.platform, m.kullanici), []).append(m)

    cikti: list[dict] = []

    def ekle(tur, msj, soru, cevap):
        simge, baslik, onem = TURLER[tur]
        cikti.append({
            "tur": tur, "simge": simge, "baslik": baslik, "onem": onem,
            "tarih": msj.olusturma, "platform": msj.platform,
            "kullanici": msj.kullanici,
            "anahtar": f"{msj.platform}:{msj.kullanici}",   # panel bağlantısı
            "soru": (soru or "")[:220], "cevap": (cevap or "")[:220],
        })

    for msjlar in sohbetler.values():
        for i, m in enumerate(msjlar):
            if m.yon != "giden":
                continue
            cevap = m.metin or ""
            # Bu cevaptan ÖNCEKİ gerçek müşteri sorusu
            soru_msj = next((x for x in reversed(msjlar[:i])
                             if x.yon == "gelen" and _musteri_sorusu_mu(x.metin)),
                            None)
            soru = _soru_metni(soru_msj.metin) if soru_msj else ""

            # 1) Ajan cevap üretemedi → özür metni gitti. Kesin arıza.
            if cevap.startswith(ozur):
                ekle("cevapsiz", m, soru, cevap)
                continue        # aşağıdaki dallar bunu TEKRAR saymasın

            yok_diyor = any(k in cevap.lower() for k in _YOK_KALIPLARI)
            fiyat_var = bool(_FIYAT.search(cevap))

            # 2) Pazarlık istendi ama fiyat gelmedi.
            if soru_msj and not fiyat_var:
                s = soru.lower()
                if any(p in s for p in _PAZARLIK):
                    # Merdiven bitmişse "daha fazla inemem" DOĞRU cevaptır.
                    if not any(b in cevap.lower() for b in _MERDIVEN_BITTI):
                        ekle("pazarlik_oldu", m, soru, cevap)

            if yok_diyor and not fiyat_var:
                soru_kel = _kelimeler(soru)
                # 3) Müşterinin sorduğu ad KATALOGDA VAR ama bot "yok" dedi.
                #    AMA: "Calmera SERİSİNDE orta sehpa bulunmuyor" bir kaçırma
                #    DEĞİL — bot seriyi bulmuş, o seride o parça gerçekten yok.
                #    Kaçırma, serinin KENDİSİNİN yok sayılmasıdır ("Massimo
                #    isimli ürünümüz bulunamadı" — oysa MASSIMO katalogda var).
                duz_cevap = menu_veri._duz(cevap)
                eslesen = [a for a in adlar
                           if _ad_geciyor_mu(a, soru_kel)
                           and not any(f"{a} {k}" in duz_cevap for k in
                                       ("serisinde", "serisinin", "koleksiyonunda",
                                        "takiminda", "serimizde"))]
                if eslesen:
                    ekle("urun_kacirildi", m, soru,
                         f"[katalogda var: {', '.join(sorted(eslesen)[:3]).upper()}] {cevap}")
                else:
                    # 4) Bot, ne müşterinin yazdığı ne katalogda olan bir ad
                    #    uydurup "yok" demiş (canlı: BEND soruldu, "Luxembourg
                    #    bulunmuyor" cevabı geldi).
                    for aday in _ADAY_AD.findall(cevap):
                        d = menu_veri._duz(aday)
                        if len(d) >= 4 and d not in adlar and d not in soru_kel:
                            ekle("uydurma_ad", m, soru, f"[uydurulan: {aday}] {cevap}")
                            break

            # 5) Yetkiliye yönlendirme — bilgi amaçlı, arıza olmayabilir.
            elif YETKILI_URL and YETKILI_URL in cevap:
                ekle("yetkiliye_atti", m, soru, cevap)

    cikti.sort(key=lambda o: (o["onem"], -o["tarih"].timestamp()))
    return cikti


def haftalik_satirlar(gun_sayisi: int = 7) -> list[str]:
    """Sabah özetine girecek kısa blok. Olay YOKSA boş liste — sessiz kal.

    Sayfayı İsmail'in hatırlaması gerekmesin diye var; ayrıntı sayfada kalır,
    özete yalnız "bak" demeye yetecek kadarı girer. Sessizlik ilkesi sabah
    özetinin geneliyle aynı (söylenecek bir şey yoksa satır ekleme).
    """
    olay = olaylar(gun_sayisi)
    if not olay:
        return []
    sayim: dict[str, int] = {}
    for o in olay:
        sayim[o["tur"]] = sayim.get(o["tur"], 0) + 1
    satir = [f"🔍 Geçen hafta botun tökezlediği {len(olay)} an var:"]
    for tur, _simge_baslik in sorted(
            sayim.items(), key=lambda x: (TURLER[x[0]][2], -x[1])):
        simge, baslik, _ = TURLER[tur]
        satir.append(f"- {sayim[tur]} × {simge} {baslik}")
    satir.append("Ayrıntı: etiket.gunesler.info/app/bot/gozden-gecirme")
    return satir


def ozet(gun_sayisi: int = 7) -> dict:
    """Panel için: sayımlar + olay listesi. Hata yutulmaz — çağıran karar verir."""
    olay = olaylar(gun_sayisi)
    sayim: dict[str, int] = {}
    for o in olay:
        sayim[o["tur"]] = sayim.get(o["tur"], 0) + 1
    return {
        "olaylar": olay,
        "sayim": sayim,
        "gun_sayisi": gun_sayisi,
        "toplam": len(olay),
        # Önemli olan bu: müşteri gerçekten cevapsız kaldı mı?
        "kritik": sum(1 for o in olay if o["onem"] == KRITIK),
        "turler": TURLER,
    }
