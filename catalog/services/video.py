"""YouTube video linki — ayrıştırma, doğrulama, kanonik biçim.

**Neden video DOSYASI değil LİNK** (İsmail kararı 2026-08-02): WhatsApp Cloud
API linkten çektiği videoda 16 MB sınırı koyuyor ve yalnız H.264/AAC mp4 kabul
ediyor. Telefonla çekilen 1080p 30sn video 10-17 MB, 4K ise 40-80 MB; Render
ücretsiz katmanında video sıkıştıracak araç (ffmpeg) YOK ve kurulamıyor.
Yani dosya yolunda panel büyük videoyu reddetmek zorunda kalırdı. Link
yolunda boyut sınırı yok, bant genişliğini YouTube karşılıyor.
Bedeli kabul edildi: müşteri videoyu izlemek için WhatsApp'tan çıkıyor.

Doğrulama YouTube'un oEmbed ucuyla yapılır — **anahtar/kota gerektirmez**.
Aynı istek hem "bu video var mı" hem "başlığı ne" sorusunu cevaplar; panel
başlığı ve küçük resmi gösterince İsmail yanlış link yapıştırdığını anında
görür. Video gizliyse (private) oEmbed hata verir ve link REDDEDİLİR —
gizli videonun linkini müşteriye göndermek "video açılmıyor" demektir.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("catalog.video")

# YouTube video numarası her zaman 11 karakterdir.
_KIMLIK = r"([A-Za-z0-9_-]{11})"
# Kabul edilen biçimler — İsmail hangisini yapıştırırsa yapıştırsın çalışsın.
# (paylaş düğmesi 'shorts/...?feature=share' verir, masaüstü 'watch?v=' verir)
_KALIPLAR = (
    re.compile(r"youtube\.com/shorts/" + _KIMLIK),
    re.compile(r"youtube\.com/live/" + _KIMLIK),
    re.compile(r"youtube\.com/embed/" + _KIMLIK),
    re.compile(r"youtube\.com/watch\?(?:.*&)?v=" + _KIMLIK),
    re.compile(r"youtu\.be/" + _KIMLIK),
)


class VideoHatasi(Exception):
    """Link kabul edilemedi — panel kullanıcıya bu metni gösterir."""


def kimlik(url: str) -> str | None:
    """Herhangi bir YouTube adresinden 11 karakterlik video numarasını çıkar."""
    u = (url or "").strip()
    if not u:
        return None
    for kalip in _KALIPLAR:
        bulunan = kalip.search(u)
        if bulunan:
            return bulunan.group(1)
    return None


def kanonik(vid: str) -> str:
    """Saklanacak biçim. WhatsApp önizleme kartını bu adreste güvenilir üretir."""
    return f"https://www.youtube.com/watch?v={vid}"


def kucuk_resim(url_ya_da_id: str) -> str | None:
    """Panelde gösterilecek küçük resim (YouTube'dan, anahtarsız)."""
    vid = kimlik(url_ya_da_id) or (
        url_ya_da_id if re.fullmatch(_KIMLIK, url_ya_da_id or "") else None)
    return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg" if vid else None


def dogrula(url: str) -> dict:
    """Linki kanonik hâle getir ve videonun GERÇEKTEN açılabilir olduğunu kanıtla.

    Döner: {"url": kanonik, "id": vid, "baslik": ..., "kucuk_resim": ...}
    Hata durumunda VideoHatasi — panel mesajı doğrudan kullanıcıya gösterir.
    """
    vid = kimlik(url)
    if not vid:
        raise VideoHatasi(
            "Bu bir YouTube linki değil. Videoyu YouTube'da açıp 'Paylaş' "
            "ile kopyaladığın adresi yapıştır.")
    kanonik_url = kanonik(vid)
    try:
        import requests
        r = requests.get("https://www.youtube.com/oembed",
                         params={"format": "json", "url": kanonik_url},
                         timeout=12)
    except Exception as e:
        # Ağ hatası videonun kötü olduğu anlamına GELMEZ — linki kabul et,
        # başlığı boş bırak. İsmail'i geçici bir kesinti yüzünden engellemeyelim.
        log.warning("oembed'e ulasilamadi (%s)", vid, exc_info=True)
        return {"url": kanonik_url, "id": vid, "baslik": "", "hata": str(e)[:80],
                "kucuk_resim": kucuk_resim(vid)}
    if r.status_code in (401, 403):
        raise VideoHatasi(
            "Bu video GİZLİ (private) görünüyor — müşteri açamaz. "
            "YouTube'da videoyu 'Herkese açık' ya da 'Liste dışı' yap.")
    if not r.ok:
        raise VideoHatasi(
            "Bu numarada bir YouTube videosu bulunamadı; link yanlış olabilir.")
    try:
        veri = r.json()
    except ValueError:
        veri = {}
    return {"url": kanonik_url, "id": vid,
            "baslik": (veri.get("title") or "")[:200],
            "kanal": (veri.get("author_name") or "")[:120],
            "kucuk_resim": kucuk_resim(vid)}


# ─── Panel: kayıtlara video atama ────────────────────────────────────────────
# İki tabloya birden video konabiliyor (İsmail kararı 2026-08-02): koleksiyon
# (262 kayıt — katalog sorana ulaşır) ve teşhir (mağazadaki gerçek mal).
# Panel ikisini tek listede gösterir; "tür" hangi tabloya yazılacağını söyler.
TURLER = ("koleksiyon", "teshir")


def _kayit(session, tur: str, kid: int):
    from catalog.sa_models import Koleksiyon, Teshir
    if tur not in TURLER:
        raise VideoHatasi("Bilinmeyen kayıt türü.")
    return session.get(Koleksiyon if tur == "koleksiyon" else Teshir, int(kid))


def _gorunum(session, tur: str, k) -> dict:
    from catalog.sa_models import Kategori, Koleksiyon
    if tur == "koleksiyon":
        kat = session.get(Kategori, k.kategori_id) if k.kategori_id else None
        ad, kategori = k.ad, (kat.ad if kat else "")
    else:
        kol = session.get(Koleksiyon, k.koleksiyon_id) if k.koleksiyon_id else None
        ad = (k.baslik or "").strip() or (kol.ad if kol else (k.koleksiyon_adi or "?"))
        # Kategori: bağlı kayıtta koleksiyondan, MANUEL kayıtta kaydın kendi
        # alanından (teshir._coz ile aynı kural — yoksa manuel kayıtlarda boş
        # görünüyor ve aynı adlı kayıtlar birbirinden ayırt edilemiyor).
        kat_id = kol.kategori_id if kol else k.kategori_id
        kat = session.get(Kategori, kat_id) if kat_id else None
        kategori = kat.ad if kat else ""
    return {"tur": tur, "id": k.id, "ad": ad, "kategori": kategori,
            "video_url": k.video_url,
            "kucuk_resim": kucuk_resim(k.video_url or "") if k.video_url else None}


def ara(q: str, limit: int = 40) -> list[dict]:
    """Ada göre koleksiyon + teşhir kayıtlarını bul (Türkçe karakter duyarsız)."""
    from sqlalchemy import select

    from catalog.database import SessionLocal
    from catalog.sa_models import Koleksiyon, Teshir
    from catalog.services.menu_veri import _ad_gibi

    q = (q or "").strip()
    if len(q) < 2:
        return []
    session = SessionLocal()
    try:
        sonuc = [_gorunum(session, "koleksiyon", k) for k in session.scalars(
            select(Koleksiyon).where(_ad_gibi(Koleksiyon.ad, q))
            .order_by(Koleksiyon.ad).limit(limit)).all()]
        # Teşhirde ad iki alandan gelebilir (baslik ya da elle yazılmış
        # koleksiyon_adi) — ikisinde de ara, yoksa manuel kayıtlar bulunamaz.
        from sqlalchemy import or_
        sonuc += [_gorunum(session, "teshir", t) for t in session.scalars(
            select(Teshir).where(or_(_ad_gibi(Teshir.baslik, q),
                                     _ad_gibi(Teshir.koleksiyon_adi, q)))
            .limit(limit)).all()]
        return sonuc
    finally:
        session.close()


def videolu() -> list[dict]:
    """Videosu OLAN tüm kayıtlar — panelin varsayılan listesi."""
    from sqlalchemy import select

    from catalog.database import SessionLocal
    from catalog.sa_models import Koleksiyon, Teshir

    session = SessionLocal()
    try:
        sonuc = [_gorunum(session, "koleksiyon", k) for k in session.scalars(
            select(Koleksiyon).where(Koleksiyon.video_url.isnot(None))
            .order_by(Koleksiyon.ad)).all()]
        sonuc += [_gorunum(session, "teshir", t) for t in session.scalars(
            select(Teshir).where(Teshir.video_url.isnot(None))).all()]
        return sonuc
    finally:
        session.close()


def ata(tur: str, kid: int, url: str) -> dict:
    """Kaydı doğrulanmış videoya bağla. Doğrulama BAŞARISIZSA hiçbir şey yazılmaz."""
    from catalog.database import SessionLocal

    bilgi = dogrula(url)              # önce doğrula — hatalıysa buradan çıkar
    session = SessionLocal()
    try:
        k = _kayit(session, tur, kid)
        if k is None:
            raise VideoHatasi("Kayıt bulunamadı.")
        k.video_url = bilgi["url"]
        session.commit()
        return bilgi
    finally:
        session.close()


def kaldir(tur: str, kid: int) -> bool:
    """Videoyu kayıttan çıkar (YouTube'daki videoya DOKUNMAZ)."""
    from catalog.database import SessionLocal

    session = SessionLocal()
    try:
        k = _kayit(session, tur, kid)
        if k is None or not k.video_url:
            return False
        k.video_url = None
        session.commit()
        return True
    finally:
        session.close()


def video_var_mi(tur: str, kid: int) -> str | None:
    """Kaydın video adresi (bot gönderirken çözer). Yoksa None."""
    from catalog.database import SessionLocal

    session = SessionLocal()
    try:
        k = _kayit(session, tur, kid)
        return (k.video_url or None) if k is not None else None
    except (VideoHatasi, TypeError, ValueError):
        return None
    finally:
        session.close()
