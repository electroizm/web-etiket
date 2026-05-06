"""Dashboard views.

Veri kaynağı: Supabase Postgres (SQLAlchemy ile direct connection).
Auth gate: @login_required_supabase (Supabase JWT → Django session).
"""
import json

from sqlalchemy import and_, func, or_, select

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.decorators import login_required_supabase, login_required_supabase_api
from catalog.database import SessionLocal
from catalog.sa_models import (
    Kategori,
    Kombinasyon,
    KombinasyonUrun,
    Koleksiyon,
    Urun,
    urun_koleksiyon,
)
from catalog.services.kombinasyon import (
    KombinasyonAdiCakismasiError,
    hesapla_kombinasyon_toplam,
    kombinasyon_guncelle,
    kombinasyon_listele,
    kombinasyon_olustur,
    kombinasyon_sil,
)
from catalog.services.oto_kombinasyon import (
    EslesmeYok,
    OtoKombinasyonError,
    otomatik_kombinasyon_olustur,
    otomatik_kombinasyon_preview,
)


PER_PAGE = 24

# Türkçe karakter → ASCII normalize (arama için).
# Postgres'teki public.tr_norm() fonksiyonu ile aynı eşleme.
_TR_NORM_TABLE = str.maketrans("IİŞĞÜÖÇışğüöç", "iisguocisguoc")


def tr_norm(s: str) -> str:
    """Lower + Türkçe karakter ASCII'ye düşür. tr_norm() SQL fonksiyonu ile uyumlu."""
    return (s or "").translate(_TR_NORM_TABLE).lower()


# Trigram benzerlik eşiği. Default pg_trgm.similarity_threshold = 0.3.
# 0.2 daha esnek (kısmi parçalar 'ber iera' → 'KIERA Berjer' yakalanır).
SEARCH_SIMILARITY_THRESHOLD = 0.2


@login_required_supabase
def home(request):
    """Dashboard ana sayfası — özet istatistikler + ürün listesine giriş."""
    session = SessionLocal()
    try:
        stats = {
            "urun":       session.scalar(select(func.count()).select_from(Urun)) or 0,
            "kategori":   session.scalar(select(func.count()).select_from(Kategori)) or 0,
            "koleksiyon": session.scalar(select(func.count()).select_from(Koleksiyon)) or 0,
        }
    except Exception:
        stats = {"urun": 0, "kategori": 0, "koleksiyon": 0, "_err": True}
    finally:
        session.close()

    return render(request, "dashboard/home.html", {
        "user_email": request.supabase_user.email,
        "user_id": request.supabase_user.id,
        "stats": stats,
    })


@login_required_supabase
def kategoriler_list(request):
    """Tüm kategoriler + koleksiyon ve ürün sayıları.
    Her kart tıklanınca o kategorideki ürünlere yönlendirir."""
    session = SessionLocal()
    try:
        # Kategori başına koleksiyon sayısı
        kol_say = (
            select(
                Kategori.id.label("kid"),
                Kategori.ad.label("ad"),
                func.count(Koleksiyon.id).label("koleksiyon_sayisi"),
            )
            .outerjoin(Koleksiyon, Koleksiyon.kategori_id == Kategori.id)
            .group_by(Kategori.id, Kategori.ad)
            .order_by(Kategori.ad)
        )
        kol_rows = session.execute(kol_say).all()

        # Kategori başına ürün sayısı (M2M üzerinden distinct)
        urun_say_stmt = (
            select(
                Koleksiyon.kategori_id.label("kid"),
                func.count(func.distinct(urun_koleksiyon.c.urun_id)).label("urun_sayisi"),
            )
            .select_from(Koleksiyon)
            .join(urun_koleksiyon, urun_koleksiyon.c.koleksiyon_id == Koleksiyon.id)
            .group_by(Koleksiyon.kategori_id)
        )
        urun_map = {r.kid: r.urun_sayisi for r in session.execute(urun_say_stmt).all()}

        kategoriler = [
            {
                "id": r.kid,
                "ad": r.ad,
                "koleksiyon_sayisi": r.koleksiyon_sayisi,
                "urun_sayisi": urun_map.get(r.kid, 0),
            }
            for r in kol_rows
        ]
    finally:
        session.close()

    return render(request, "dashboard/kategoriler_list.html", {
        "kategoriler": kategoriler,
        "toplam_kategori": len(kategoriler),
    })


@login_required_supabase
def kategori_detail(request, kategori_id: int):
    """Tek bir kategori → koleksiyon tablosu.
    Tablo görseldeki gibi: Koleksiyon | Takım | Bayraklar | Kombinasyon | İşlemler
    Takım/Bayraklar/Kombinasyon kolonları henüz veri yok — yer tutucu olarak gösterilir,
    ileride Takım/TakimKombinasyonu modelleri portlanınca dolacak.
    """
    session = SessionLocal()
    try:
        kategori = session.scalar(select(Kategori).where(Kategori.id == kategori_id))
        if kategori is None:
            raise Http404("Kategori bulunamadı.")

        # Koleksiyon başına ürün sayısı (M2M)
        urun_say_subq = (
            select(func.count(func.distinct(urun_koleksiyon.c.urun_id)))
            .where(urun_koleksiyon.c.koleksiyon_id == Koleksiyon.id)
            .scalar_subquery()
        )

        # Koleksiyon başına kombinasyon sayısı
        kombi_say_subq = (
            select(func.count(Kombinasyon.id))
            .where(Kombinasyon.koleksiyon_id == Koleksiyon.id)
            .scalar_subquery()
        )

        stmt = (
            select(
                Koleksiyon.id.label("id"),
                Koleksiyon.ad.label("ad"),
                Koleksiyon.takim_adi.label("takim_adi"),
                Koleksiyon.bayrak_exc.label("bayrak_exc"),
                Koleksiyon.bayrak_sube.label("bayrak_sube"),
                urun_say_subq.label("urun_sayisi"),
                kombi_say_subq.label("kombinasyon_sayisi"),
            )
            .where(Koleksiyon.kategori_id == kategori_id)
            .order_by(Koleksiyon.ad)
        )
        rows = session.execute(stmt).all()

        koleksiyonlar = [
            {
                "id": r.id,
                "ad": r.ad,
                "urun_sayisi": r.urun_sayisi or 0,
                "takim_adi": r.takim_adi,                  # boşsa EXC/ŞUBE disabled
                "bayrak_exc": bool(r.bayrak_exc),
                "bayrak_sube": bool(r.bayrak_sube),
                "kombinasyon_sayisi": r.kombinasyon_sayisi or 0,
            }
            for r in rows
        ]

        kategori_data = {"id": kategori.id, "ad": kategori.ad}
    finally:
        session.close()

    return render(request, "dashboard/kategori_detail.html", {
        "kategori": kategori_data,
        "koleksiyonlar": koleksiyonlar,
        "toplam_koleksiyon": len(koleksiyonlar),
    })


@login_required_supabase
def urunler_list(request):
    """Ürün listesi — arama, kategori filtresi, sıralama, pagination."""
    q = (request.GET.get("q") or "").strip()
    kategori_id = (request.GET.get("kategori") or "").strip()
    koleksiyon_id = (request.GET.get("koleksiyon") or "").strip()
    sort = (request.GET.get("sort") or "ad").strip()
    try:
        page = max(1, int(request.GET.get("page") or 1))
    except ValueError:
        page = 1

    session = SessionLocal()
    try:
        # ── filtre koşullarını ortak hazırla ──
        where_clauses = []
        if q:
            term = f"%{q}%"
            where_clauses.append(or_(
                Urun.sku.ilike(term),
                Urun.urun_adi_tam.ilike(term),
            ))

        if kategori_id.isdigit():
            kid = int(kategori_id)
            in_kat = select(urun_koleksiyon.c.urun_id).join(
                Koleksiyon, urun_koleksiyon.c.koleksiyon_id == Koleksiyon.id
            ).where(Koleksiyon.kategori_id == kid)
            where_clauses.append(Urun.id.in_(in_kat))

        if koleksiyon_id.isdigit():
            kolid = int(koleksiyon_id)
            in_kol = select(urun_koleksiyon.c.urun_id).where(
                urun_koleksiyon.c.koleksiyon_id == kolid
            )
            where_clauses.append(Urun.id.in_(in_kol))

        # ── total count ──
        count_stmt = select(func.count()).select_from(Urun)
        for c in where_clauses:
            count_stmt = count_stmt.where(c)
        total = session.scalar(count_stmt) or 0
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = min(page, total_pages)

        # ── ana query ──
        stmt = select(Urun)
        for c in where_clauses:
            stmt = stmt.where(c)

        # Koleksiyon filtresi varsa: işaretli ürünler önce gelsin (etiket_secili
        # DESC) — scalar subquery ile order_by, mevcut where_clauses bozulmuyor.
        secili_order = None
        if koleksiyon_id.isdigit():
            kolid_int = int(koleksiyon_id)
            secili_order = (
                select(urun_koleksiyon.c.etiket_secili)
                .where(
                    urun_koleksiyon.c.koleksiyon_id == kolid_int,
                    urun_koleksiyon.c.urun_id == Urun.id,
                )
                .scalar_subquery()
            )

        # sıralama
        if sort == "fiyat_artan":
            base_order = [Urun.son_perakende_fiyat.asc().nulls_last(), Urun.urun_adi_tam.asc()]
        elif sort == "fiyat_azalan":
            base_order = [Urun.son_perakende_fiyat.desc().nulls_last(), Urun.urun_adi_tam.asc()]
        elif sort == "yeni":
            base_order = [Urun.son_guncelleme.desc()]
        else:  # 'ad'
            base_order = [Urun.urun_adi_tam.asc()]
            sort = "ad"
        if secili_order is not None:
            stmt = stmt.order_by(secili_order.desc(), *base_order)
        else:
            stmt = stmt.order_by(*base_order)

        stmt = stmt.limit(PER_PAGE).offset((page - 1) * PER_PAGE)
        urunler = list(session.scalars(stmt).all())

        # session kapanmadan dict snapshot (template'te lazy load olmasın)
        urunler_data = []
        for u in urunler:
            indirim = 0
            if u.son_liste_fiyat and u.son_perakende_fiyat and u.son_liste_fiyat > u.son_perakende_fiyat:
                indirim = int(round(
                    (u.son_liste_fiyat - u.son_perakende_fiyat) / u.son_liste_fiyat * 100
                ))
            urunler_data.append({
                "id": u.id,
                "sku": u.sku,
                "urun_adi_tam": u.urun_adi_tam,
                "url": u.url,
                "son_liste_fiyat": u.son_liste_fiyat,
                "son_perakende_fiyat": u.son_perakende_fiyat,
                "indirim_yuzde": indirim,
                "indirimli": indirim > 0,
            })

        kategoriler = list(session.scalars(
            select(Kategori).order_by(Kategori.ad)
        ).all())
        kategoriler_data = [{"id": k.id, "ad": k.ad} for k in kategoriler]

        # ── Koleksiyon filtresi varsa: koleksiyon bilgisini de gönder
        # (Takım Seç butonu + breadcrumb + per-ürün etiket_secili için)
        koleksiyon_info = None
        kombinasyonlar_data: list[dict] = []
        if koleksiyon_id.isdigit():
            kol_int_id = int(koleksiyon_id)
            kol = session.scalar(select(Koleksiyon).where(Koleksiyon.id == kol_int_id))
            if kol:
                koleksiyon_info = {
                    "id": kol.id,
                    "ad": kol.ad,
                    "takim_adi": kol.takim_adi,
                    "takim_urun_id": kol.takim_urun_id,
                    "kategori_id": kol.kategori_id,
                }
                # Bu sayfadaki ürünler için etiket_secili durumlarını çek
                if urunler_data:
                    urun_ids = [u["id"] for u in urunler_data]
                    secili_rows = session.execute(
                        select(
                            urun_koleksiyon.c.urun_id,
                            urun_koleksiyon.c.etiket_secili,
                        ).where(
                            urun_koleksiyon.c.koleksiyon_id == kol_int_id,
                            urun_koleksiyon.c.urun_id.in_(urun_ids),
                        )
                    ).all()
                    secili_map = {r.urun_id: bool(r.etiket_secili) for r in secili_rows}
                    for u in urunler_data:
                        u["etiket_secili"] = secili_map.get(u["id"], True)

        # ── Bu koleksiyonun kombinasyonları (banner altında listelenecek)
        if koleksiyon_info is not None:
            kombi_list = kombinasyon_listele(session, koleksiyon_info["id"])
            for k in kombi_list:
                toplam = hesapla_kombinasyon_toplam(k)
                kombinasyonlar_data.append({
                    "id": k.id,
                    "ad": k.ad,
                    "etiket_secili": bool(k.etiket_secili),
                    "urun_sayisi": toplam["urun_sayisi"],
                    "toplam_adet": toplam["toplam_adet"],
                    "toplam_liste": toplam["toplam_liste"],
                    "toplam_perakende": toplam["toplam_perakende"],
                    "indirim_yuzde": toplam["indirim_yuzde"],
                    "urunler": [
                        {
                            "urun_id": ku.urun_id,
                            "sku": ku.urun.sku if ku.urun else None,
                            "ad": ku.urun.urun_adi_tam if ku.urun else None,
                            "miktar": ku.miktar,
                        }
                        for ku in k.urunler
                    ],
                })
    finally:
        session.close()

    # pagination link helper
    def page_window(current: int, total: int, span: int = 2) -> list[int]:
        """[1, ..., 4, 5, 6, 7, ..., 12] tarzı pagination penceresi."""
        if total <= 1:
            return [1]
        a = max(1, current - span)
        b = min(total, current + span)
        out = list(range(a, b + 1))
        if a > 1:
            out = [1] + ([0] if a > 2 else []) + out  # 0 = ellipsis
        if b < total:
            out = out + ([0] if b < total - 1 else []) + [total]
        return out

    return render(request, "dashboard/urunler_list.html", {
        "urunler": urunler_data,
        "kategoriler": kategoriler_data,
        "q": q,
        "kategori_id": kategori_id,
        "koleksiyon_id": koleksiyon_id,
        "sort": sort,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "per_page": PER_PAGE,
        "page_window": page_window(page, total_pages),
        "koleksiyon_info": koleksiyon_info,
        "kombinasyonlar": kombinasyonlar_data,
    })


# ─── JSON API: koleksiyon rename (with merge) ────────────────────────────────

@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase_api
def koleksiyon_rename(request, koleksiyon_id: int):
    """POST /app/koleksiyon/<id>/rename/  body: {"ad": "yeni ad", "confirm_merge": false}

    - Aynı kategoride aynı isim YOKSA: ad güncellenir.
    - Aynı kategoride aynı isim VARSA + confirm_merge=False: 409 + requires_merge:true döner.
      Frontend kullanıcıdan onay alır.
    - confirm_merge=True: kaynak koleksiyonun ürünleri hedef koleksiyona taşınır
      (urun_koleksiyon M2M satırları), sonra kaynak koleksiyon silinir.
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Geçersiz istek formatı."}, status=400)

    yeni_ad = (data.get("ad") or "").strip()
    confirm_merge = bool(data.get("confirm_merge"))

    if not yeni_ad:
        return JsonResponse({"ok": False, "error": "Koleksiyon adı boş olamaz."}, status=400)
    if len(yeni_ad) > 200:
        return JsonResponse({"ok": False, "error": "Koleksiyon adı en fazla 200 karakter olabilir."}, status=400)

    session = SessionLocal()
    try:
        kol = session.scalar(select(Koleksiyon).where(Koleksiyon.id == koleksiyon_id))
        if kol is None:
            return JsonResponse({"ok": False, "error": "Koleksiyon bulunamadı."}, status=404)

        if kol.ad == yeni_ad:
            return JsonResponse({"ok": True, "ad": kol.ad, "unchanged": True})

        existing = session.scalar(
            select(Koleksiyon).where(
                Koleksiyon.kategori_id == kol.kategori_id,
                Koleksiyon.ad == yeni_ad,
                Koleksiyon.id != koleksiyon_id,
            )
        )

        # --- Çakışma yoksa basit rename ---
        if existing is None:
            kol.ad = yeni_ad
            session.commit()
            return JsonResponse({"ok": True, "ad": yeni_ad})

        # --- Çakışma var, onay verilmemiş → kullanıcıdan onay iste ---
        if not confirm_merge:
            # Kaç ürün taşınacak?
            kaynak_urun_count = session.scalar(
                select(func.count()).select_from(urun_koleksiyon).where(
                    urun_koleksiyon.c.koleksiyon_id == kol.id
                )
            ) or 0
            return JsonResponse({
                "ok": False,
                "requires_merge": True,
                "error": f'"{yeni_ad}" adında başka bir koleksiyon zaten var.',
                "source": {"id": kol.id, "ad": kol.ad, "urun_sayisi": kaynak_urun_count},
                "target": {"id": existing.id, "ad": existing.ad},
            }, status=409)

        # --- confirm_merge=True → birleştir ---
        # 1) Kaynaktaki ürünleri hedef koleksiyona ekle (mevcutları atla)
        from sqlalchemy import insert, delete
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        kaynak_urun_ids = [
            row[0] for row in session.execute(
                select(urun_koleksiyon.c.urun_id).where(
                    urun_koleksiyon.c.koleksiyon_id == kol.id
                )
            ).all()
        ]
        tasinan = 0
        if kaynak_urun_ids:
            stmt_insert = pg_insert(urun_koleksiyon).values([
                {"urun_id": uid, "koleksiyon_id": existing.id}
                for uid in kaynak_urun_ids
            ]).on_conflict_do_nothing(index_elements=["urun_id", "koleksiyon_id"])
            result = session.execute(stmt_insert)
            tasinan = result.rowcount or 0

        # 2) Kaynak koleksiyonun M2M satırlarını sil (CASCADE de silebilir ama açıkça)
        session.execute(
            delete(urun_koleksiyon).where(urun_koleksiyon.c.koleksiyon_id == kol.id)
        )

        # 3) Kaynak koleksiyonu sil
        session.delete(kol)
        session.commit()

        return JsonResponse({
            "ok": True,
            "merged": True,
            "target_id": existing.id,
            "target_ad": existing.ad,
            "tasinan_urun": tasinan,
        })
    except Exception as e:
        session.rollback()
        return JsonResponse({"ok": False, "error": f"Sunucu hatası: {e}"}, status=500)
    finally:
        session.close()


# ─── JSON API: ürün adı düzenleme ────────────────────────────────────────────

@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase_api
def urun_rename(request, urun_id: int):
    """POST /app/urun/<id>/rename/  body: {"ad": "yeni ad"}

    urun_adi_tam alanını günceller. Scraper bu alanı mevcut SKU'lar için
    artık dokunmuyor (manuel düzenlemeler korunur).
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Geçersiz istek formatı."}, status=400)

    yeni_ad = (data.get("ad") or "").strip()
    if not yeni_ad:
        return JsonResponse({"ok": False, "error": "Ürün adı boş olamaz."}, status=400)
    if len(yeni_ad) > 300:
        return JsonResponse({"ok": False, "error": "Ürün adı en fazla 300 karakter olabilir."}, status=400)

    session = SessionLocal()
    try:
        urun = session.scalar(select(Urun).where(Urun.id == urun_id))
        if urun is None:
            return JsonResponse({"ok": False, "error": "Ürün bulunamadı."}, status=404)

        if urun.urun_adi_tam == yeni_ad:
            return JsonResponse({"ok": True, "ad": urun.urun_adi_tam, "unchanged": True})

        urun.urun_adi_tam = yeni_ad
        session.commit()
        return JsonResponse({"ok": True, "ad": yeni_ad})
    except Exception as e:
        session.rollback()
        return JsonResponse({"ok": False, "error": f"Sunucu hatası: {e}"}, status=500)
    finally:
        session.close()


# ─── JSON API: koleksiyon bayrak toggle ──────────────────────────────────────

VALID_BAYRAKLAR = {"exc", "sube"}


@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase_api
def koleksiyon_bayrak_toggle(request, koleksiyon_id: int):
    """POST /app/koleksiyon/<id>/bayrak/  body: {"bayrak": "exc"|"sube", "value": true|false}

    Koleksiyona takım atanmamışsa (takim_adi boş) bayrak değiştirilemez.
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Geçersiz istek formatı."}, status=400)

    bayrak = (data.get("bayrak") or "").strip().lower()
    if bayrak not in VALID_BAYRAKLAR:
        return JsonResponse({"ok": False, "error": "Bilinmeyen bayrak."}, status=400)

    value = bool(data.get("value"))

    session = SessionLocal()
    try:
        kol = session.scalar(select(Koleksiyon).where(Koleksiyon.id == koleksiyon_id))
        if kol is None:
            return JsonResponse({"ok": False, "error": "Koleksiyon bulunamadı."}, status=404)

        if not (kol.takim_adi or "").strip():
            return JsonResponse({
                "ok": False,
                "error": "Bayrak ataması için önce takım adı girin.",
            }, status=409)

        if bayrak == "exc":
            kol.bayrak_exc = value
        else:  # sube
            kol.bayrak_sube = value

        session.commit()
        return JsonResponse({
            "ok": True,
            "bayrak": bayrak,
            "value": value,
            "bayrak_exc": kol.bayrak_exc,
            "bayrak_sube": kol.bayrak_sube,
        })
    except Exception as e:
        session.rollback()
        return JsonResponse({"ok": False, "error": f"Sunucu hatası: {e}"}, status=500)
    finally:
        session.close()


# ─── JSON API: takım aday ürünleri (SKU pattern: 1xxxxx ya da 3xxxxxxxxx) ────

@require_http_methods(["GET"])
@login_required_supabase_api
def koleksiyon_takim_candidates(request, koleksiyon_id: int):
    """GET /app/koleksiyon/<id>/takim-candidates/

    Koleksiyona bağlı ürünlerden takım adayı olabilecekleri döner:
      - Önce sku LIKE '1%' AND length(sku)=6  (set/takım ürünleri)
      - Yoksa sku LIKE '3%' AND length(sku)=10 (tekil ürünler) — fallback
      - O da yoksa boş liste + match_type='none'
    """
    session = SessionLocal()
    try:
        kol = session.scalar(select(Koleksiyon).where(Koleksiyon.id == koleksiyon_id))
        if kol is None:
            return JsonResponse({"ok": False, "error": "Koleksiyon bulunamadı."}, status=404)

        base_query = (
            select(Urun.id, Urun.sku, Urun.urun_adi_tam)
            .join(urun_koleksiyon, urun_koleksiyon.c.urun_id == Urun.id)
            .where(urun_koleksiyon.c.koleksiyon_id == koleksiyon_id)
        )

        # Pattern A: 1 ile başlayan, 6 hane
        rows_a = session.execute(
            base_query.where(and_(Urun.sku.like("1%"), func.length(Urun.sku) == 6))
                      .order_by(Urun.urun_adi_tam)
        ).all()

        if rows_a:
            candidates = rows_a
            match_type = "1-6"
        else:
            # Pattern B: 3 ile başlayan, 10 hane
            rows_b = session.execute(
                base_query.where(and_(Urun.sku.like("3%"), func.length(Urun.sku) == 10))
                          .order_by(Urun.urun_adi_tam)
            ).all()
            candidates = rows_b
            match_type = "3-10" if rows_b else "none"

        return JsonResponse({
            "ok": True,
            "koleksiyon": {"id": kol.id, "ad": kol.ad, "takim_adi": kol.takim_adi},
            "match_type": match_type,
            "candidates": [
                {"id": r.id, "sku": r.sku, "ad": r.urun_adi_tam}
                for r in candidates
            ],
        })
    finally:
        session.close()


# ─── JSON API: koleksiyon takım atama ────────────────────────────────────────

@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase_api
def koleksiyon_takim_set(request, koleksiyon_id: int):
    """POST /app/koleksiyon/<id>/takim/  body: {"takim_adi": "..."}

    Boş string veya null gönderilirse takım kaldırılır + bayraklar resetlenir.
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Geçersiz istek formatı."}, status=400)

    takim_adi = (data.get("takim_adi") or "").strip()
    if takim_adi and len(takim_adi) > 200:
        return JsonResponse({"ok": False, "error": "Takım adı en fazla 200 karakter olabilir."}, status=400)

    # Atanan takım ürününün id'si — PDF QR url'i için gerekli
    takim_urun_id_raw = data.get("takim_urun_id")
    takim_urun_id: int | None = None
    if takim_urun_id_raw not in (None, "", 0, "0"):
        try:
            takim_urun_id = int(takim_urun_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Geçersiz takim_urun_id."}, status=400)

    session = SessionLocal()
    try:
        kol = session.scalar(select(Koleksiyon).where(Koleksiyon.id == koleksiyon_id))
        if kol is None:
            return JsonResponse({"ok": False, "error": "Koleksiyon bulunamadı."}, status=404)

        kol.takim_adi = takim_adi or None
        # Takım kaldırılırsa: takim_urun_id ve bayraklar da resetlensin
        if not takim_adi:
            kol.takim_urun_id = None
            kol.bayrak_exc = False
            kol.bayrak_sube = False
        else:
            kol.takim_urun_id = takim_urun_id

        session.commit()
        return JsonResponse({
            "ok": True,
            "takim_adi": kol.takim_adi,
            "takim_urun_id": kol.takim_urun_id,
            "bayrak_exc": kol.bayrak_exc,
            "bayrak_sube": kol.bayrak_sube,
        })
    except Exception as e:
        session.rollback()
        return JsonResponse({"ok": False, "error": f"Sunucu hatası: {e}"}, status=500)
    finally:
        session.close()


# ─── Koleksiyona manuel ürün ekleme ──────────────────────────────────────────

@login_required_supabase
def koleksiyon_urun_ekle(request, koleksiyon_id: int):
    """GET: arama formu + sonuç listesi. POST: seçilen ürünü koleksiyona ekle.

    Arama: ad için ILIKE %q% (kısmi), SKU için tam eşleşme.
    Eklenen ürün etiket_secili=True ile eklenir; ardından koleksiyon
    sayfasına yönlendirilir.
    """
    from django.shortcuts import redirect as _redirect
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    session = SessionLocal()
    try:
        kol = session.scalar(select(Koleksiyon).where(Koleksiyon.id == koleksiyon_id))
        if kol is None:
            raise Http404("Koleksiyon bulunamadı.")
        kategori = session.scalar(select(Kategori).where(Kategori.id == kol.kategori_id))

        # ── POST: ürünü ekle ─────────────────────────────────────────────
        if request.method == "POST":
            try:
                urun_id = int(request.POST.get("urun_id") or 0)
            except (TypeError, ValueError):
                urun_id = 0
            if urun_id <= 0:
                return _redirect(f"/app/koleksiyon/{koleksiyon_id}/urun-ekle/")

            # Ürün gerçekten var mı?
            urun_exists = session.scalar(
                select(func.count()).select_from(Urun).where(Urun.id == urun_id)
            ) or 0
            if urun_exists == 0:
                return _redirect(f"/app/koleksiyon/{koleksiyon_id}/urun-ekle/")

            # Idempotent insert: yeni ekleme etiket_secili=False ile (kullanıcı
            # 15 satır limiti içinde manuel olarak işaretler). Zaten ekliyse
            # mevcut etiket_secili durumunu koru — kullanıcının önceki seçimini
            # ezme.
            stmt = pg_insert(urun_koleksiyon).values(
                urun_id=urun_id,
                koleksiyon_id=koleksiyon_id,
                etiket_secili=False,
            ).on_conflict_do_nothing(
                index_elements=["urun_id", "koleksiyon_id"],
            )
            session.execute(stmt)
            session.commit()
            return _redirect(f"/app/urunler/?koleksiyon={koleksiyon_id}")

        # ── GET: sadece sayfa render ─────────────────────────────────────
        # Arama ayrı JSON endpoint'inde yapılıyor (koleksiyon_urun_ekle_search).
        return render(request, "dashboard/urun_ekle.html", {
            "koleksiyon": {
                "id": kol.id,
                "ad": kol.ad,
                "kategori_id": kol.kategori_id,
                "kategori_ad": kategori.ad if kategori else None,
            },
        })
    finally:
        session.close()


# ─── JSON API: ürün arama (canlı arama için) ─────────────────────────────────

MIN_SEARCH_LEN = 3


@login_required_supabase_api
def koleksiyon_urun_ekle_search(request, koleksiyon_id: int):
    """GET /app/koleksiyon/<id>/urun-ekle/search/?q=...

    JSON dönen canlı arama endpoint'i. Bu koleksiyonda olmayan ürünler
    için trigram + TR-normalize fuzzy arama yapar.
    """
    q = (request.GET.get("q") or "").strip()
    if len(q) < MIN_SEARCH_LEN:
        return JsonResponse({"ok": True, "q": q, "results": []})

    session = SessionLocal()
    try:
        kol_exists = session.scalar(
            select(func.count()).select_from(Koleksiyon).where(Koleksiyon.id == koleksiyon_id)
        ) or 0
        if kol_exists == 0:
            return JsonResponse({"ok": False, "error": "Koleksiyon bulunamadı."}, status=404)

        q_norm = tr_norm(q)
        in_kol_subq = (
            select(urun_koleksiyon.c.urun_id)
            .where(urun_koleksiyon.c.koleksiyon_id == koleksiyon_id)
        )
        norm_name = func.tr_norm(Urun.urun_adi_tam)

        # Sorguyu kelimelere böl. Her kelime AYRI AYRI eşleşmek zorunda (AND).
        # Tek kelime için ILIKE substring veya trigram benzerlik yeterli.
        tokens = [t for t in q_norm.split() if t]
        word_clauses = [
            or_(
                norm_name.ilike(f"%{tok}%"),
                func.similarity(norm_name, tok) > SEARCH_SIMILARITY_THRESHOLD,
            )
            for tok in tokens
        ]
        # Tüm kelimeler eşleşmeli + tam string substring eşleşmesi (sıralama için)
        ilike_full = norm_name.ilike(f"%{q_norm}%")

        stmt = (
            select(
                Urun.id, Urun.sku, Urun.urun_adi_tam,
                Urun.son_liste_fiyat, Urun.son_perakende_fiyat,
            )
            .where(
                or_(
                    Urun.sku == q,
                    and_(*word_clauses) if word_clauses else False,
                ),
                Urun.id.notin_(in_kol_subq),
            )
            # Tam substring eşleşmeleri en üstte, sonra ad
            .order_by(
                ilike_full.desc(),
                Urun.urun_adi_tam.asc(),
            )
            .limit(50)
        )

        results = []
        for r in session.execute(stmt).all():
            results.append({
                "id": r.id,
                "sku": r.sku,
                "urun_adi_tam": r.urun_adi_tam,
                "son_liste_fiyat": r.son_liste_fiyat,
                "son_perakende_fiyat": r.son_perakende_fiyat,
            })
        return JsonResponse({"ok": True, "q": q, "results": results})
    finally:
        session.close()


# ─── JSON API: kombinasyon PDF işareti + sıra ────────────────────────────────

@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase_api
def kombinasyon_etiket_toggle(request, kombinasyon_id: int):
    """POST /app/kombinasyon/<id>/etiket-toggle/  body: {"value": true|false}

    Kombinasyonun etiket_secili alanını günceller.
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Geçersiz istek formatı."}, status=400)

    value = bool(data.get("value"))

    session = SessionLocal()
    try:
        kombi = session.scalar(select(Kombinasyon).where(Kombinasyon.id == kombinasyon_id))
        if kombi is None:
            return JsonResponse({"ok": False, "error": "Kombinasyon bulunamadı."}, status=404)
        kombi.etiket_secili = value
        session.commit()
        return JsonResponse({"ok": True, "etiket_secili": value})
    except Exception as e:
        session.rollback()
        return JsonResponse({"ok": False, "error": f"Sunucu hatası: {e}"}, status=500)
    finally:
        session.close()


@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase_api
def kombinasyon_sira_toplu(request, koleksiyon_id: int):
    """POST /app/koleksiyon/<id>/kombinasyon-sira/  body: {"ids": [3, 1, 4, 2]}

    Drag-and-drop sonrası tüm kombinasyonların yeni sırasını tek seferde
    yazar. Listede bulunan her kombinasyona index'ine göre sira atanır.
    Listede olmayan ya da başka koleksiyona ait id'ler yok sayılır.
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Geçersiz istek formatı."}, status=400)

    ids = data.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return JsonResponse({"ok": False, "error": "ids bir int listesi olmalı."}, status=400)

    session = SessionLocal()
    try:
        kombiler = list(session.scalars(
            select(Kombinasyon).where(Kombinasyon.koleksiyon_id == koleksiyon_id)
        ).all())
        kombi_map = {k.id: k for k in kombiler}

        # Verilen id'leri sırayla index'e göre sira ata
        for i, kid in enumerate(ids):
            k = kombi_map.get(kid)
            if k is not None:
                k.sira = i

        session.commit()
        return JsonResponse({"ok": True})
    except Exception as e:
        session.rollback()
        return JsonResponse({"ok": False, "error": f"Sunucu hatası: {e}"}, status=500)
    finally:
        session.close()


# ─── Etiket PDF üretimi ──────────────────────────────────────────────────────

@login_required_supabase
def koleksiyon_etiket_pdf(request, koleksiyon_id: int):
    """GET /app/koleksiyon/<id>/etiket-pdf/ → application/pdf

    Bu koleksiyonun fiyat etiketini A4 landscape PDF olarak üretir.
    Tarayıcıda açılır (inline). Sadece etiket_secili=True ürün/kombinasyon dahil.

    15 satır limiti aşılırsa PDF üretilmez, kullanıcıya HTML hata sayfası gösterilir.
    """
    from catalog.services.etiket_pdf import (
        EtiketBosSecim,
        EtiketSatirAsim,
        pdf_koleksiyon_etiketi,
    )

    session = SessionLocal()
    try:
        kol = session.scalar(select(Koleksiyon).where(Koleksiyon.id == koleksiyon_id))
        if kol is None:
            raise Http404("Koleksiyon bulunamadı.")

        try:
            pdf_bytes = pdf_koleksiyon_etiketi(session, koleksiyon_id)
        except (EtiketSatirAsim, EtiketBosSecim) as e:
            # Kullanıcı dostu HTML hata sayfası
            baslik = "Etiket sınırı aşıldı" if isinstance(e, EtiketSatirAsim) else "Etikete dahil edilecek satır yok"
            status = 413 if isinstance(e, EtiketSatirAsim) else 400
            geri_url = f"/app/urunler/?koleksiyon={koleksiyon_id}"
            return HttpResponse(
                f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
                <title>{baslik}</title>
                <style>
                  body {{ font-family: system-ui, sans-serif; max-width: 560px;
                          margin: 80px auto; padding: 24px; line-height: 1.6;
                          color: #1f2937; }}
                  h1 {{ font-size: 20px; color: #b91c1c; }}
                  .info {{ background: #fef3c7; padding: 12px 16px;
                           border-radius: 8px; border-left: 4px solid #f59e0b; }}
                  a {{ color: #6d28d9; }}
                </style></head><body>
                <h1>{baslik}</h1>
                <div class="info">{e}</div>
                <p style="margin-top: 24px;"><a href="{geri_url}">← Koleksiyona geri dön</a></p>
                </body></html>""",
                status=status,
            )
    finally:
        session.close()

    safe_name = (kol.takim_adi or kol.ad or "etiket").replace('"', "").replace("/", "-")
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{safe_name}.pdf"'
    return response


# ─── JSON API: ürünü koleksiyondan kaldır ────────────────────────────────────

@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase_api
def koleksiyon_urun_kaldir(request, koleksiyon_id: int, urun_id: int):
    """POST /app/koleksiyon/<kid>/urun/<uid>/kaldir/

    İki engel:
      1) Ürün etiket için işaretliyse (etiket_secili=True) → 409.
      2) Ürün bu koleksiyondaki herhangi bir kombinasyonda kullanılıyorsa → 409
         (kullanan kombinasyon adları döner).
    Aksi halde urun_koleksiyon satırı silinir (ürünün kendisi DB'de kalır).
    """
    from sqlalchemy import delete as _delete

    session = SessionLocal()
    try:
        # M2M satırını çek (etiket_secili kontrolü için)
        row = session.execute(
            select(urun_koleksiyon.c.etiket_secili).where(
                urun_koleksiyon.c.koleksiyon_id == koleksiyon_id,
                urun_koleksiyon.c.urun_id == urun_id,
            )
        ).first()
        if row is None:
            return JsonResponse({
                "ok": False,
                "error": "Bu ürün bu koleksiyonda kayıtlı değil.",
            }, status=404)

        if bool(row.etiket_secili):
            return JsonResponse({
                "ok": False,
                "error": "Ürün etiket için işaretli. Önce işareti kaldırın.",
                "reason": "secili",
            }, status=409)

        # Bu koleksiyondaki kombinasyonlardan herhangi birinde kullanılıyor mu?
        kombi_rows = session.execute(
            select(Kombinasyon.id, Kombinasyon.ad)
            .join(KombinasyonUrun, KombinasyonUrun.kombinasyon_id == Kombinasyon.id)
            .where(
                Kombinasyon.koleksiyon_id == koleksiyon_id,
                KombinasyonUrun.urun_id == urun_id,
            )
            .distinct()
        ).all()
        if kombi_rows:
            return JsonResponse({
                "ok": False,
                "error": "Ürün, koleksiyondaki kombinasyon(lar)da kullanılıyor.",
                "reason": "kombinasyon",
                "kombinasyonlar": [{"id": r.id, "ad": r.ad} for r in kombi_rows],
            }, status=409)

        # Sil
        session.execute(
            _delete(urun_koleksiyon).where(
                urun_koleksiyon.c.koleksiyon_id == koleksiyon_id,
                urun_koleksiyon.c.urun_id == urun_id,
            )
        )
        session.commit()
        return JsonResponse({"ok": True})
    except Exception as e:
        session.rollback()
        return JsonResponse({"ok": False, "error": f"Sunucu hatası: {e}"}, status=500)
    finally:
        session.close()


# ─── JSON API: ürünün koleksiyondaki etiket_secili durumu ────────────────────

@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase_api
def koleksiyon_urun_secim(request, koleksiyon_id: int, urun_id: int):
    """POST /app/koleksiyon/<kid>/urun/<uid>/etiket-secimi/  body: {"secili": true|false}

    M2M tablosundaki etiket_secili kolonunu günceller.
    Bu kolon, etiket basarken ürünün listede yer alıp almayacağını belirler.
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Geçersiz istek formatı."}, status=400)

    secili = bool(data.get("secili"))

    session = SessionLocal()
    try:
        from sqlalchemy import update
        result = session.execute(
            update(urun_koleksiyon)
            .where(
                urun_koleksiyon.c.koleksiyon_id == koleksiyon_id,
                urun_koleksiyon.c.urun_id == urun_id,
            )
            .values(etiket_secili=secili)
        )
        if (result.rowcount or 0) == 0:
            return JsonResponse({
                "ok": False,
                "error": "Bu ürün bu koleksiyonda kayıtlı değil.",
            }, status=404)
        session.commit()
        return JsonResponse({"ok": True, "secili": secili})
    except Exception as e:
        session.rollback()
        return JsonResponse({"ok": False, "error": f"Sunucu hatası: {e}"}, status=500)
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════
# Kombinasyon Views (manual + otomatik)
# ═══════════════════════════════════════════════════════════════════════════

def _parse_form_urun_miktarlari(post) -> list[tuple[int, int]]:
    """Form'dan urun_<id>_secili / urun_<id>_miktar parse eder."""
    sonuc: list[tuple[int, int]] = []
    for key in post:
        if not key.startswith("urun_") or not key.endswith("_secili"):
            continue
        try:
            urun_id = int(key.removeprefix("urun_").removesuffix("_secili"))
        except ValueError:
            continue
        miktar_str = post.get(f"urun_{urun_id}_miktar", "1")
        try:
            miktar = max(1, int(miktar_str))
        except (TypeError, ValueError):
            miktar = 1
        sonuc.append((urun_id, miktar))
    return sonuc


def _form_context(
    *,
    request,
    koleksiyon_data: dict,
    urun_list: list[dict],
    kombi_id: int | None = None,
    ad_value: str = "",
    secili_miktarlar: dict[int, int] | None = None,
    hata: str | None = None,
):
    secili_miktarlar = secili_miktarlar or {}
    urunler_view = []
    for u in urun_list:
        urunler_view.append({
            **u,
            "secili": u["id"] in secili_miktarlar,
            "miktar": secili_miktarlar.get(u["id"], 1),
        })
    return {
        "koleksiyon": koleksiyon_data,
        "urunler": urunler_view,
        "kombi_id": kombi_id,
        "ad_value": ad_value,
        "hata": hata,
        "is_edit": kombi_id is not None,
    }


def _koleksiyon_with_urunler(
    session,
    koleksiyon_id: int,
    *,
    sadece_secili: bool = False,
    force_include_urun_ids: list[int] | None = None,
):
    """Bir koleksiyonu + bağlı ürünleri (id, sku, urun_adi_tam) getirir.

    sadece_secili=True ise etiket_secili=True olanlar döner (kombinasyon
    formları için). force_include_urun_ids verilirse, bu ürünler etiket_secili
    olmasa bile döner (mevcut bir kombinasyonu düzenlerken eski ürünleri
    kaybetmemek için).
    """
    kol = session.scalar(select(Koleksiyon).where(Koleksiyon.id == koleksiyon_id))
    if kol is None:
        return None, []
    if sadece_secili:
        force_ids = list(force_include_urun_ids or [])
        if force_ids:
            secili_cond = or_(
                urun_koleksiyon.c.etiket_secili.is_(True),
                Urun.id.in_(force_ids),
            )
        else:
            secili_cond = urun_koleksiyon.c.etiket_secili.is_(True)
        where_extra = [secili_cond]
    else:
        where_extra = []
    rows = session.execute(
        select(Urun.id, Urun.sku, Urun.urun_adi_tam, Urun.son_liste_fiyat, Urun.son_perakende_fiyat)
        .join(urun_koleksiyon, urun_koleksiyon.c.urun_id == Urun.id)
        .where(urun_koleksiyon.c.koleksiyon_id == koleksiyon_id, *where_extra)
        .order_by(Urun.urun_adi_tam)
    ).all()
    urun_list = [
        {
            "id": r.id,
            "sku": r.sku,
            "urun_adi_tam": r.urun_adi_tam,
            "son_liste_fiyat": r.son_liste_fiyat,
            "son_perakende_fiyat": r.son_perakende_fiyat,
        }
        for r in rows
    ]
    kategori = session.scalar(select(Kategori).where(Kategori.id == kol.kategori_id))
    return {
        "id": kol.id,
        "ad": kol.ad,
        "kategori_id": kol.kategori_id,
        "kategori_ad": kategori.ad if kategori else None,
    }, urun_list


@login_required_supabase
def kombinasyon_yeni(request, koleksiyon_id: int):
    """GET form / POST olustur. Sadece etiket_secili=True ürünleri listeler."""
    session = SessionLocal()
    try:
        koleksiyon_data, urun_list = _koleksiyon_with_urunler(
            session, koleksiyon_id, sadece_secili=True
        )
        if koleksiyon_data is None:
            raise Http404("Koleksiyon bulunamadı.")

        if not urun_list:
            return render(request, "dashboard/kombinasyon_form.html", {
                "koleksiyon": koleksiyon_data,
                "urunler": [],
                "kombi_id": None,
                "ad_value": "",
                "is_edit": False,
                "hata": "Etiket için işaretli ürün yok. Önce koleksiyon sayfasında en az bir ürünü işaretleyin.",
                "no_secili": True,
            }, status=400)

        if request.method == "POST":
            ad = (request.POST.get("ad") or "").strip()
            urun_miktarlari = _parse_form_urun_miktarlari(request.POST)
            try:
                kombinasyon_olustur(session, koleksiyon_id, ad, urun_miktarlari)
                from django.shortcuts import redirect as _redirect
                return _redirect(f"/app/urunler/?koleksiyon={koleksiyon_id}")
            except (KombinasyonAdiCakismasiError, ValueError) as e:
                ctx = _form_context(
                    request=request,
                    koleksiyon_data=koleksiyon_data,
                    urun_list=urun_list,
                    ad_value=ad,
                    secili_miktarlar={uid: m for uid, m in urun_miktarlari},
                    hata=str(e),
                )
                return render(request, "dashboard/kombinasyon_form.html", ctx, status=400)

        # GET
        ctx = _form_context(
            request=request,
            koleksiyon_data=koleksiyon_data,
            urun_list=urun_list,
        )
        return render(request, "dashboard/kombinasyon_form.html", ctx)
    finally:
        session.close()


@login_required_supabase
def kombinasyon_duzenle(request, kombinasyon_id: int):
    """GET form / POST guncelle. Sadece etiket_secili=True ürünleri (+ bu
    kombinasyondaki mevcut ürünleri) listeler."""
    session = SessionLocal()
    try:
        from sqlalchemy.orm import selectinload as _sel
        kombi = session.scalar(
            select(Kombinasyon)
            .where(Kombinasyon.id == kombinasyon_id)
            .options(_sel(Kombinasyon.urunler))
        )
        if kombi is None:
            raise Http404("Kombinasyon bulunamadı.")

        mevcut_urun_ids = [ku.urun_id for ku in kombi.urunler]
        koleksiyon_data, urun_list = _koleksiyon_with_urunler(
            session,
            kombi.koleksiyon_id,
            sadece_secili=True,
            force_include_urun_ids=mevcut_urun_ids,
        )
        if koleksiyon_data is None:
            raise Http404("Koleksiyon bulunamadı.")

        if request.method == "POST":
            ad = (request.POST.get("ad") or "").strip()
            urun_miktarlari = _parse_form_urun_miktarlari(request.POST)
            try:
                kombi = kombinasyon_guncelle(session, kombinasyon_id, ad, urun_miktarlari)
                from django.shortcuts import redirect as _redirect
                return _redirect(f"/app/urunler/?koleksiyon={kombi.koleksiyon_id}")
            except (KombinasyonAdiCakismasiError, ValueError) as e:
                ctx = _form_context(
                    request=request,
                    koleksiyon_data=koleksiyon_data,
                    urun_list=urun_list,
                    kombi_id=kombinasyon_id,
                    ad_value=ad,
                    secili_miktarlar={uid: m for uid, m in urun_miktarlari},
                    hata=str(e),
                )
                return render(request, "dashboard/kombinasyon_form.html", ctx, status=400)

        # GET — mevcut seçimleri getir
        secili_miktarlar = {ku.urun_id: ku.miktar for ku in kombi.urunler}
        ctx = _form_context(
            request=request,
            koleksiyon_data=koleksiyon_data,
            urun_list=urun_list,
            kombi_id=kombinasyon_id,
            ad_value=kombi.ad,
            secili_miktarlar=secili_miktarlar,
        )
        return render(request, "dashboard/kombinasyon_form.html", ctx)
    finally:
        session.close()


@csrf_protect
@require_http_methods(["POST"])
@login_required_supabase
def kombinasyon_sil_view(request, kombinasyon_id: int):
    session = SessionLocal()
    try:
        kid = kombinasyon_sil(session, kombinasyon_id)
    finally:
        session.close()
    from django.shortcuts import redirect as _redirect
    if kid is None:
        return _redirect("/app/")
    return _redirect(f"/app/urunler/?koleksiyon={kid}")


@login_required_supabase
def kombinasyon_otomatik(request, koleksiyon_id: int):
    """GET preview / POST olustur ve yönlendir."""
    session = SessionLocal()
    try:
        koleksiyon_data, _ = _koleksiyon_with_urunler(session, koleksiyon_id)
        if koleksiyon_data is None:
            raise Http404("Koleksiyon bulunamadı.")

        if request.method == "POST":
            try:
                sonuc = otomatik_kombinasyon_olustur(session, koleksiyon_id)
                from django.shortcuts import redirect as _redirect
                return _redirect(f"/app/urunler/?koleksiyon={koleksiyon_id}")
            except (OtoKombinasyonError, EslesmeYok) as e:
                return render(request, "dashboard/kombinasyon_otomatik.html", {
                    "koleksiyon": koleksiyon_data,
                    "preview": None,
                    "hata": str(e),
                }, status=400)

        # GET — preview
        try:
            preview = otomatik_kombinasyon_preview(session, koleksiyon_id)
            return render(request, "dashboard/kombinasyon_otomatik.html", {
                "koleksiyon": koleksiyon_data,
                "preview": preview,
                "hata": None,
            })
        except (OtoKombinasyonError, EslesmeYok) as e:
            return render(request, "dashboard/kombinasyon_otomatik.html", {
                "koleksiyon": koleksiyon_data,
                "preview": None,
                "hata": str(e),
            }, status=400)
    finally:
        session.close()


# ─── Ayarlar (Slogan / vs.) ──────────────────────────────────────────────────

# Maks 5 MB — daha büyük dosyaları reddet
SLOGAN_MAX_BYTES = 5 * 1024 * 1024

ALLOWED_SLOGAN_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}


@login_required_supabase
def ayarlar(request):
    """GET /app/ayarlar/ — ayarlar ana sayfası, varsayılan: Slogan sekmesi."""
    from django.shortcuts import redirect as _redirect
    return _redirect("dashboard:ayarlar_slogan")


def _ayarlar_image_upload(
    request,
    *,
    form_field_name: str,
    db_key: str,
    upload_fn,
    redirect_url_name: str,
    success_msg: str,
):
    """Slogan / Yerli Üretim gibi tek-görsel ayarları için POST handler.

    upload_fn: bytes + content_type alıp public URL döner (slogan_yukle vs.)
    """
    from django.contrib import messages
    from django.shortcuts import redirect as _redirect
    from catalog.services.ayarlar import set_ayar

    f = request.FILES.get(form_field_name)
    if not f:
        messages.error(request, "Dosya seçilmedi.")
        return _redirect(redirect_url_name)

    if f.size > SLOGAN_MAX_BYTES:
        messages.error(request, f"Dosya çok büyük (max {SLOGAN_MAX_BYTES // (1024*1024)} MB).")
        return _redirect(redirect_url_name)

    content_type = (f.content_type or "image/png").lower()
    if content_type not in ALLOWED_SLOGAN_CONTENT_TYPES:
        messages.error(
            request,
            f"Desteklenmeyen dosya tipi: {content_type}. PNG/JPEG/WEBP yükle.",
        )
        return _redirect(redirect_url_name)

    try:
        file_bytes = f.read()
        public_url = upload_fn(file_bytes, content_type=content_type)
    except Exception as e:
        messages.error(request, f"Yükleme başarısız: {e}")
        return _redirect(redirect_url_name)

    session = SessionLocal()
    try:
        set_ayar(session, db_key, public_url)
        session.commit()
    except Exception as e:
        session.rollback()
        messages.error(request, f"Veritabanı hatası: {e}")
        return _redirect(redirect_url_name)
    finally:
        session.close()

    messages.success(request, success_msg)
    return _redirect(redirect_url_name)


@login_required_supabase
def ayarlar_slogan(request):
    """GET/POST /app/ayarlar/slogan/ — etiket header banner görseli."""
    from catalog.services.ayarlar import (
        ANAHTAR_SLOGAN_URL,
        slogan_url_aktif,
        slogan_yukle,
    )

    if request.method == "POST":
        return _ayarlar_image_upload(
            request,
            form_field_name="slogan",
            db_key=ANAHTAR_SLOGAN_URL,
            upload_fn=slogan_yukle,
            redirect_url_name="dashboard:ayarlar_slogan",
            success_msg="Slogan görseli güncellendi. PDF üretiminde kullanılacak.",
        )

    session = SessionLocal()
    try:
        mevcut_url = slogan_url_aktif(session)
    finally:
        session.close()

    return render(request, "dashboard/ayarlar_slogan.html", {
        "active_tab": "slogan",
        "slogan_url": mevcut_url,
        "max_mb": SLOGAN_MAX_BYTES // (1024 * 1024),
    })


@login_required_supabase
def ayarlar_yerli_uretim(request):
    """GET/POST /app/ayarlar/yerli-uretim/ — etiket sağ alt logo."""
    from catalog.services.ayarlar import (
        ANAHTAR_YERLI_URETIM_URL,
        yerli_uretim_url_aktif,
        yerli_uretim_yukle,
    )

    if request.method == "POST":
        return _ayarlar_image_upload(
            request,
            form_field_name="yerli_uretim",
            db_key=ANAHTAR_YERLI_URETIM_URL,
            upload_fn=yerli_uretim_yukle,
            redirect_url_name="dashboard:ayarlar_yerli_uretim",
            success_msg="Yerli Üretim logosu güncellendi. PDF üretiminde kullanılacak.",
        )

    session = SessionLocal()
    try:
        mevcut_url = yerli_uretim_url_aktif(session)
    finally:
        session.close()

    return render(request, "dashboard/ayarlar_yerli_uretim.html", {
        "active_tab": "yerli_uretim",
        "yerli_uretim_url": mevcut_url,
        "max_mb": SLOGAN_MAX_BYTES // (1024 * 1024),
    })
