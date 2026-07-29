"""Gemini istek sayacı — model başına günlük kullanım, deploy'a dayanıklı.

Neden var (2026-07-28): `/saglik`'taki sayaç bellekte tutuluyordu, her deploy'da
sıfırlanıyordu — "kota neden doldu" sorusuna bakacak veri yoktu. Asıl sürpriz
şuydu: ücretsiz katmanda `gemini-flash-latest` (= gemini-3.6-flash) günde
YALNIZ 20 istek kabul ediyor, üstelik Google artık limit tablosunu kamuya
yayımlamıyor. Yani gerçek limiti ancak 429 cevabının içinden öğrenebiliyoruz;
bu modül onu da yakalayıp saklar.

Sayım neden mesaj sayısından fazla: bot bir mesaja cevap verirken araç (tool)
döngüsü çalıştırır ve HER tur ayrı bir model çağrısıdır. Ayrıca görsel OCR,
sesli mesaj çözümü ve sabah özeti de aynı kotayı yer — bu yüzden "iş" boyutu
tutulur, hangi işin ne kadar yediği görünsün.

Depolama: ayrı tablo YOK — mevcut `app_ayarlari` key-value tablosu kullanılır
(İsmail'in Supabase'e elle SQL yapıştırması gerekmesin). Artırma Postgres
ON CONFLICT DO UPDATE ile ATOMİK yapılır; eşzamanlı isteklerde sayı kaybolmaz.

Anahtar biçimi:
    kota:<YYYY-MM-DD>:<model>:<is>:<sonuc>  → sayı
    kotalimit:<model>                        → 429'dan okunan gerçek günlük limit

Hiçbir hata botu düşürmez: sayaç yazılamazsa sessizce geçilir (yutulur).
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from sqlalchemy import String, cast, delete, func as sa_func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.types import Integer

log = logging.getLogger("bot.kota")

ONEK = "kota:"
LIMIT_ONEK = "kotalimit:"
# "Bu model bugün GÜNLÜK hakkını doldurdu" işareti. Dakikalık (RPM/TPM) 429
# buraya YAZILMAZ — o geçicidir, modeli gün boyu kapatmaz.
BITTI_ONEK = "kotabitti:"
SAKLAMA_GUN = 14          # bundan eski satırlar temizlenir

# İş türleri — hangi özellik ne kadar kota yiyor?
ISLER = ("sohbet", "gorsel", "ses", "ozet")
# Sonuçlar — ajan.MODEL_SAYAC ile aynı sözlük.
SONUCLAR = ("basari", "bos", "kota", "hata")

# Panelde 💚 ücretsiz / 💳 ücretli rozeti bundan çıkar. Google'ın ücretsiz
# katmanı tek bedava kaynağımız; OpenRouter kullandıkça ödenir. Zincire yeni bir
# ücretsiz sağlayıcı girerse öneki buraya eklenmeli (bkz. settings.AJAN_MODEL).
UCRETSIZ_ONEKLER = ("gemini/",)


def _anahtar(gun: date, model: str, is_adi: str, sonuc: str) -> str:
    return f"{ONEK}{gun:%Y-%m-%d}:{model}:{is_adi}:{sonuc}"


def say(model: str, is_adi: str, sonuc: str, gun: date | None = None) -> None:
    """Bir model çağrısını kaydet (atomik +1). Hata yutulur — bot durmaz."""
    if sonuc not in SONUCLAR:
        sonuc = "hata"
    if is_adi not in ISLER:
        is_adi = "sohbet"
    try:
        from catalog.database import SessionLocal
        from catalog.sa_models import AppAyari
        session = SessionLocal()
        try:
            stmt = pg_insert(AppAyari).values(
                anahtar=_anahtar(gun or date.today(), model, is_adi, sonuc),
                deger="1",
            ).on_conflict_do_update(
                index_elements=["anahtar"],
                # DİKKAT: buradaki AppAyari.deger MEVCUT satırın değeridir
                # (EXCLUDED değil) — artırma bu yüzden atomiktir.
                set_={"deger": cast(cast(AppAyari.deger, Integer) + 1, String),
                      "guncellenme_tarihi": sa_func.now()},
            )
            session.execute(stmt)
            session.commit()
        finally:
            session.close()
    except Exception:
        log.warning("kota sayaci yazilamadi (%s/%s/%s)", model, is_adi, sonuc,
                    exc_info=True)


# 429 gövdesinden gerçek limiti çıkar:
#   "limit: 20, model: gemini-3.6-flash"  ya da  "quotaValue": "20"
_LIMIT_KALIBI = re.compile(r'limit:\s*(\d+)|"quotaValue":\s*"(\d+)"')


def limiti_ogren(model: str, hata: Exception) -> int | None:
    """429 metninden günlük limiti oku ve sakla (Google artık yayımlamıyor)."""
    m = _LIMIT_KALIBI.search(str(hata))
    if not m:
        return None
    deger = int(m.group(1) or m.group(2))
    try:
        from catalog.database import SessionLocal
        from catalog.services.ayarlar import set_ayar
        session = SessionLocal()
        try:
            set_ayar(session, f"{LIMIT_ONEK}{model}", str(deger))
            session.commit()
        finally:
            session.close()
    except Exception:
        log.warning("kota limiti yazilamadi (%s)", model, exc_info=True)
    return deger


# ─── Günlük kotası dolan modeli atlama ───────────────────────────────────────
# Kota dolduktan sonra da her istekte önce o model deneniyordu: günde ~150 boşa
# gidiş-geliş ve her cevaba ~1 sn gecikme. Bellekte tutulur — deploy'da
# sıfırlanır, en fazla model başına BİR deneme israfı olur (kabul edilebilir).
_BITTI: dict[str, str] = {}       # model -> "YYYY-MM-DD"


def _bugun() -> str:
    return f"{date.today():%Y-%m-%d}"


def gunluk_bitti_mi(hata: Exception) -> bool:
    """429 GÜNLÜK kota mı, dakikalık mı?

    Ayrım şart: dakikalık (RPM/TPM) 429 birkaç saniyede kendiliğinden düzelir —
    onun yüzünden modeli gün boyu kapatmak koca bir kayıptır. Ücretsiz
    katmanlarda dakikalık sınır çok sık tetiklenir (~4K token'lık isteklerimizde
    12K TPM ≈ dakikada 3 çağrı). Sağlayıcılar ayrımı farklı yazıyor:
      Google     : quotaId "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
      Groq/diğer : "...on requests per day (RPD)" / "tokens per day (TPD)"
    OpenRouter sağlayıcının hatasını olduğu gibi geçirdiği için aynı kalıplar
    orada da tutar.
    """
    m = str(hata)
    d = m.lower()
    return ("PerDay" in m or "per day" in d or "_per_day" in m
            or "(rpd)" in d or "(tpd)" in d)


def kapat(model: str, hata: Exception) -> bool:
    """Günlük kota dolduysa modeli bugünlük kapat. Kapatıldıysa True.

    İşaret hem bellekte (hızlı kontrol) hem DB'de tutulur: panel ayrı bir
    süreçte/işçide çalışabildiği için "günlük hakkı bitti" bilgisini bellekten
    okuyamaz. DB kaydı olmadan panel her 429'u günlük bitiş sanıyordu —
    dakikalık hız sınırı da öyle görünüyordu (İsmail 2026-07-29'da fark etti:
    "OpenRouter ücret ödedim, neden günlük hak bitti yazıyor").
    """
    if not gunluk_bitti_mi(hata):
        return False
    _BITTI[model] = _bugun()
    try:
        from catalog.database import SessionLocal
        from catalog.services.ayarlar import set_ayar
        session = SessionLocal()
        try:
            set_ayar(session, f"{BITTI_ONEK}{_bugun()}:{model}", "1")
            session.commit()
        finally:
            session.close()
    except Exception:
        log.warning("gunluk bitti isareti yazilamadi (%s)", model, exc_info=True)
    log.warning("kota: %s bugunluk kapatildi (gunluk limit doldu)", model)
    return True


def kapali_mi(model: str) -> bool:
    return _BITTI.get(model) == _bugun()


def hepsi_kapali_mi(modeller) -> bool:
    return bool(modeller) and all(kapali_mi(m) for m in modeller)


def kapalilari_ac() -> None:
    """Tüm zincir kapalıysa son çare: işaretleri sil, bir tur daha denensin.

    Yanlış bir işaret (ör. Google mesaj biçimini değiştirirse) botu gün boyu
    susturmasın — susmaktansa boşa istek atmak yeğdir.
    """
    if _BITTI:
        log.warning("kota: tum zincir kapali gorundu, isaretler sifirlandi")
        _BITTI.clear()


def _satirlari_oku(gun_sayisi: int) -> tuple[dict, dict]:
    """(sayaclar, limitler) — sayaclar[(gun, model, is, sonuc)] = adet."""
    from catalog.database import SessionLocal
    from catalog.sa_models import AppAyari

    esik = (date.today() - timedelta(days=gun_sayisi - 1)).strftime("%Y-%m-%d")
    sayaclar: dict[tuple[str, str, str, str], int] = {}
    limitler: dict[str, int] = {}
    session = SessionLocal()
    try:
        for r in session.scalars(select(AppAyari).where(
                AppAyari.anahtar.like(f"{ONEK}%"))).all():
            parcalar = r.anahtar[len(ONEK):].split(":")
            if len(parcalar) != 4 or parcalar[0] < esik:
                continue
            try:
                sayaclar[tuple(parcalar)] = int(r.deger or 0)
            except ValueError:
                continue
        for r in session.scalars(select(AppAyari).where(
                AppAyari.anahtar.like(f"{LIMIT_ONEK}%"))).all():
            try:
                limitler[r.anahtar[len(LIMIT_ONEK):]] = int(r.deger or 0)
            except ValueError:
                continue
    finally:
        session.close()
    return sayaclar, limitler


def _bugun_bitenler() -> set[str]:
    """Bugün GÜNLÜK hakkı gerçekten dolan modeller (dakikalık 429 sayılmaz)."""
    from catalog.database import SessionLocal
    from catalog.sa_models import AppAyari

    onek = f"{BITTI_ONEK}{_bugun()}:"
    session = SessionLocal()
    try:
        return {r.anahtar[len(onek):] for r in session.scalars(
            select(AppAyari).where(AppAyari.anahtar.like(f"{onek}%"))).all()}
    finally:
        session.close()


def musteri_ozeti() -> dict:
    """Bugün kaç müşteri mesajı geldi, kaçı CEVAPSIZ kaldı?

    Kota sayfasının en önemli rakamı budur: model/kota ayrıntısı teknik detay,
    asıl soru müşterinin cevap alıp almadığıdır. "Cevapsız" = ajan cevap
    üretemeyip router'ın özür metnine düştüğü an (bkz. router.AI_KAPALI_METNI).
    Hata yutulur; sayfa bu yüzden düşmesin.
    """
    from datetime import datetime, time, timezone

    from sqlalchemy import func as _f

    from bot.router import AI_KAPALI_METNI
    from catalog.database import SessionLocal
    from catalog.sa_models import BotMesaj

    # Gün sınırı sayaçlarla aynı olsun (kota anahtarları date.today() kullanır).
    basla = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    session = SessionLocal()
    try:
        gelen = session.scalar(select(_f.count()).select_from(BotMesaj).where(
            BotMesaj.yon == "gelen", BotMesaj.olusturma >= basla)) or 0
        cevapsiz = session.scalar(select(_f.count()).select_from(BotMesaj).where(
            BotMesaj.yon == "giden", BotMesaj.olusturma >= basla,
            BotMesaj.metin.startswith(AI_KAPALI_METNI[:40]))) or 0
    finally:
        session.close()
    return {"musteri_mesaji": gelen, "cevapsiz": cevapsiz}


def ozet(gun_sayisi: int = 7, zincir=None) -> dict:
    """Panel için: bugünün model kırılımı + iş kırılımı + günlük geçmiş.

    `zincir` verilirse (settings.AJAN_MODELLER) kartlar rastgele değil ZİNCİR
    SIRASINA dizilir ve her modele okunur bir durum yazılır — sayfa böylece
    "hangi model ne kadar" listesi değil, isteğin izlediği MERDİVEN olur.
    """
    sayaclar, limitler = _satirlari_oku(gun_sayisi)
    bugun = f"{date.today():%Y-%m-%d}"

    modeller: dict[str, dict] = {}
    isler: dict[str, int] = {}
    gunler: dict[str, dict] = {}

    for (gun, model, is_adi, sonuc), adet in sayaclar.items():
        g = gunler.setdefault(gun, {"gun": gun, "toplam": 0, "kota": 0})
        g["toplam"] += adet
        if sonuc == "kota":
            g["kota"] += adet
        if gun == bugun:
            m = modeller.setdefault(model, {"model": model, "toplam": 0,
                                            **{s: 0 for s in SONUCLAR}})
            m["toplam"] += adet
            m[sonuc] += adet
            isler[is_adi] = isler.get(is_adi, 0) + adet

    try:
        bitenler = _bugun_bitenler()
    except Exception:
        log.warning("gunluk biten model listesi okunamadi", exc_info=True)
        bitenler = set()

    # Zincirde olup bugün hiç kullanılmayan model de kart alsın: merdivenin
    # tamamı görünmezse "sırada bekliyor" bilgisi verilemez.
    zincir = list(zincir or [])
    for ad in zincir:
        modeller.setdefault(ad, {"model": ad, "toplam": 0,
                                 **{s: 0 for s in SONUCLAR}})
    # Şu an işi hangisi yapıyor: zincirde günlük hakkı BİTMEMİŞ ilk model.
    aktif = next((ad for ad in zincir if ad not in bitenler), None)

    for m in modeller.values():
        m["limit"] = limitler.get(m["model"])
        # Limite sayılan istek: kota hatasıyla REDDEDİLEN istek kotadan düşmez.
        m["kullanilan"] = m["toplam"] - m["kota"]
        m["yuzde"] = (min(100, round(m["kullanilan"] * 100 / m["limit"]))
                      if m["limit"] else None)
        # "Günlük hak bitti" YALNIZ gerçek günlük kota reddinde doğrudur.
        # Dakikalık (RPM/TPM) 429 geçicidir — ücretli hesapta da olur, panelde
        # "hakkın bitti" diye göstermek yanıltıcıydı.
        m["gunluk_bitti"] = m["model"] in bitenler
        m["gecici_sinir"] = bool(m["kota"]) and not m["gunluk_bitti"]

        m["sira"] = zincir.index(m["model"]) + 1 if m["model"] in zincir else 0
        m["ucretli"] = not m["model"].startswith(UCRETSIZ_ONEKLER)
        # Kısa ad: "gemini/gemini-flash-latest" → "gemini-flash-latest".
        m["kisa_ad"] = m["model"].split("/")[-1]
        if m["gunluk_bitti"]:
            m["durum"] = "kapandi"
        elif m["model"] == aktif:
            m["durum"] = "aktif"
        elif m["sira"]:
            m["durum"] = "bekliyor"
        else:
            m["durum"] = "eski"     # zincirden çıkarılmış, yalnız geçmiş veri

    return {
        "bugun": bugun,
        # Zincir sırası (1→2→3→4); zincir dışı eski modeller en sona.
        "modeller": sorted(modeller.values(),
                           key=lambda x: (x["sira"] or 99, x["model"])),
        "isler": sorted(isler.items(), key=lambda x: -x[1]),
        "gunler": sorted(gunler.values(), key=lambda x: x["gun"], reverse=True),
        "toplam_bugun": sum(m["toplam"] for m in modeller.values()),
        "ucretli_bugun": sum(m["toplam"] for m in modeller.values()
                             if m["ucretli"]),
    }


def temizle() -> int:
    """SAKLAMA_GUN'den eski sayaç satırlarını sil. Panel açılışında çağrılır."""
    from catalog.database import SessionLocal
    from catalog.sa_models import AppAyari

    esik = (date.today() - timedelta(days=SAKLAMA_GUN)).strftime("%Y-%m-%d")
    session = SessionLocal()
    try:
        sonuc = session.execute(delete(AppAyari).where(
            AppAyari.anahtar.like(f"{ONEK}%"),
            AppAyari.anahtar < f"{ONEK}{esik}"))
        session.commit()
        return sonuc.rowcount or 0
    finally:
        session.close()
