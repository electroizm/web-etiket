"""Dış (public) API — instALL köprü sunucusu buradan menü + fiyat verisi çeker.

Kullanıcı akışı (Instagram/WhatsApp):
  1) GET /api/kategoriler/                         → kategori seç
  2) GET /api/koleksiyonlar/?kategori_id=..        → kombinasyonu olan koleksiyonlar
  3) GET /api/kombinasyonlar/?koleksiyon_id=..     → kombinasyonlar (fiyatlı)
  4) GET /api/kombinasyon/?id=..                   → seçilen kombinasyonun fiyat detayı
  (ayrıca) GET /api/fiyat/?sku=..                  → tek ürün fiyatı (doğrudan SKU)

Kimlik: `X-API-Key` header'ı, settings.ETIKET_API_KEY ile sabit-zamanlı karşılaştırılır.
Veri kaynağı: Supabase Postgres (SQLAlchemy). Fiyatlar TL, tam sayı.
"""
import functools
import hmac

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from catalog.database import SessionLocal
from catalog.sa_models import Kategori, Koleksiyon, Kombinasyon, KombinasyonUrun, Urun
from catalog.services.kombinasyon import hesapla_kombinasyon_toplam, kombinasyon_listele


def _api_key_gecerli(request) -> bool:
    """X-API-Key header'ı settings.ETIKET_API_KEY ile eşleşiyor mu? (sabit zamanlı)."""
    beklenen = settings.ETIKET_API_KEY
    if not beklenen:
        return False  # anahtar tanımlı değilse API kapalı
    gelen = request.headers.get("X-API-Key", "")
    return hmac.compare_digest(gelen, beklenen)


def api_key_gerekli(view):
    """X-API-Key doğrulamasını zorunlu kılan dekoratör (geçersizse 401)."""
    @functools.wraps(view)
    def _wrap(request, *args, **kwargs):
        if not _api_key_gecerli(request):
            return JsonResponse({"hata": "yetkisiz"}, status=401)
        return view(request, *args, **kwargs)
    return _wrap


def _int_param(request, ad: str):
    """Zorunlu integer query parametresi oku. (deger, hata_response) döner."""
    ham = (request.GET.get(ad) or "").strip()
    if not ham:
        return None, JsonResponse({"hata": f"{ad} parametresi gerekli"}, status=400)
    try:
        return int(ham), None
    except ValueError:
        return None, JsonResponse({"hata": f"{ad} sayı olmalı"}, status=400)


def _toplam_ozet(kombi) -> dict:
    """hesapla_kombinasyon_toplam çıktısını API alan adlarıyla düzleştir."""
    t = hesapla_kombinasyon_toplam(kombi)
    return {
        "urun_sayisi": t["urun_sayisi"],
        "toplam_adet": t["toplam_adet"],
        "toplam_liste": t["toplam_liste"],
        "toplam_perakende": t["toplam_perakende"],
        "indirim_yuzde": t["indirim_yuzde"],
    }


# ─── 1) Kategoriler ───────────────────────────────────────────────────────────
@require_GET
@api_key_gerekli
def kategoriler(request):
    """En az bir kombinasyonu olan koleksiyon içeren kategoriler."""
    session = SessionLocal()
    try:
        kombi_var = (
            select(Kombinasyon.id)
            .join(Koleksiyon, Koleksiyon.id == Kombinasyon.koleksiyon_id)
            .where(Koleksiyon.kategori_id == Kategori.id)
            .exists()
        )
        rows = session.scalars(
            select(Kategori).where(kombi_var).order_by(Kategori.sira, Kategori.ad)
        ).all()
        data = [{"id": k.id, "ad": k.ad} for k in rows]
    finally:
        session.close()
    return JsonResponse({"kategoriler": data})


# ─── 2) Koleksiyonlar (kombinasyon sayısı > 0) ────────────────────────────────
@require_GET
@api_key_gerekli
def koleksiyonlar(request):
    """Bir kategorideki koleksiyonlar — sadece kombinasyon_sayisi > 0 olanlar."""
    kategori_id, hata = _int_param(request, "kategori_id")
    if hata:
        return hata

    session = SessionLocal()
    try:
        kategori = session.get(Kategori, kategori_id)
        if kategori is None:
            return JsonResponse({"hata": "kategori bulunamadi"}, status=404)

        kombi_say = (
            select(func.count(Kombinasyon.id))
            .where(Kombinasyon.koleksiyon_id == Koleksiyon.id)
            .correlate(Koleksiyon)
            .scalar_subquery()
        )
        rows = session.execute(
            select(Koleksiyon.id, Koleksiyon.ad, kombi_say.label("ks"))
            .where(Koleksiyon.kategori_id == kategori_id)
            .order_by(Koleksiyon.ad)
        ).all()
        data = [
            {"id": r.id, "ad": r.ad, "kombinasyon_sayisi": r.ks}
            for r in rows if (r.ks or 0) > 0
        ]
        kategori_ozet = {"id": kategori.id, "ad": kategori.ad}
    finally:
        session.close()
    return JsonResponse({"kategori": kategori_ozet, "koleksiyonlar": data})


# ─── 3) Kombinasyonlar (fiyatlı liste) ────────────────────────────────────────
@require_GET
@api_key_gerekli
def kombinasyonlar(request):
    """Bir koleksiyonun kombinasyonları, toplam fiyat özetiyle."""
    koleksiyon_id, hata = _int_param(request, "koleksiyon_id")
    if hata:
        return hata

    session = SessionLocal()
    try:
        koleksiyon = session.get(Koleksiyon, koleksiyon_id)
        if koleksiyon is None:
            return JsonResponse({"hata": "koleksiyon bulunamadi"}, status=404)

        kombi_list = kombinasyon_listele(session, koleksiyon_id)
        data = [{"id": k.id, "ad": k.ad, **_toplam_ozet(k)} for k in kombi_list]
        koleksiyon_ozet = {"id": koleksiyon.id, "ad": koleksiyon.ad}
    finally:
        session.close()
    return JsonResponse({"koleksiyon": koleksiyon_ozet, "kombinasyonlar": data})


# ─── 4) Tek kombinasyon — fiyat detayı ────────────────────────────────────────
@require_GET
@api_key_gerekli
def kombinasyon(request):
    """Seçilen kombinasyonun fiyat detayı + içindeki ürünler."""
    kombi_id, hata = _int_param(request, "id")
    if hata:
        return hata

    session = SessionLocal()
    try:
        kombi = session.scalar(
            select(Kombinasyon)
            .where(Kombinasyon.id == kombi_id)
            .options(selectinload(Kombinasyon.urunler).selectinload(KombinasyonUrun.urun))
        )
        if kombi is None:
            return JsonResponse({"hata": "kombinasyon bulunamadi"}, status=404)

        koleksiyon = session.get(Koleksiyon, kombi.koleksiyon_id)
        urunler = [
            {
                "sku": ku.urun.sku,
                "urun": ku.urun.urun_adi_tam,
                "miktar": ku.miktar,
                "perakende_fiyat": ku.urun.son_perakende_fiyat,
            }
            for ku in kombi.urunler if ku.urun is not None
        ]
        govde = {
            "id": kombi.id,
            "ad": kombi.ad,
            "koleksiyon": {"id": koleksiyon.id, "ad": koleksiyon.ad} if koleksiyon else None,
            **_toplam_ozet(kombi),
            "para_birimi": "TL",
            "urunler": urunler,
        }
    finally:
        session.close()
    return JsonResponse(govde)


# ─── (ek) Tek ürün fiyatı — doğrudan SKU ──────────────────────────────────────
@require_GET
@api_key_gerekli
def fiyat(request):
    """GET /api/fiyat/?sku=KANEPE-01  → tek ürünün perakende fiyatı."""
    sku = (request.GET.get("sku") or "").strip()
    if not sku:
        return JsonResponse({"hata": "sku parametresi gerekli"}, status=400)

    session = SessionLocal()
    try:
        urun = session.scalar(select(Urun).where(Urun.sku == sku))
    finally:
        session.close()

    if urun is None:
        return JsonResponse({"hata": "urun bulunamadi"}, status=404)

    return JsonResponse({
        "sku": urun.sku,
        "urun": urun.urun_adi_tam,
        "perakende_fiyat": urun.son_perakende_fiyat,
        "para_birimi": "TL",
        "guncelleme": urun.son_guncelleme.isoformat() if urun.son_guncelleme else None,
    })
