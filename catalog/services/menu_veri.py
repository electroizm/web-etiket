"""Bot menü + fiyat verisi — süreç-içi (HTTP yok).

instALL köprüsü eskiden bu veriyi `/api/` uçlarından HTTP ile çekiyordu. Köprü
artık aynı Django süreci içinde çalıştığı için (Render tek servis birleştirme),
veriyi doğrudan buradan okur — self-HTTP çağrısı ve uyanma gecikmesi olmaz.

Dönen sözlükler `api_views` çıktısıyla birebir aynı şekildedir (presenter'lar bu
alan adlarına bağlı). Bulunamayan kayıt için None döner; çağıran nazik mesaj gösterir.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from catalog.database import SessionLocal
from catalog.sa_models import Kategori, Koleksiyon, Kombinasyon, KombinasyonUrun
from catalog.services.kombinasyon import hesapla_kombinasyon_toplam, kombinasyon_listele


def _tl(n) -> str:
    return f"{round(n):,}".replace(",", ".") + " TL"


def fiyat_cumlesi(liste, perakende) -> str:
    """Modelin AYNEN kopyalayacağı hazır fiyat cümlesi.

    Model ayrı ayrı sayı alanlarını cümleye çevirirken rakamları bozabiliyor
    (canlıda görüldü: 66.661 / 53.996 → 70.000 / 70.000). Rakamları tek bir
    bitişik metin olarak vermek bu transkripsiyon hatasını büyük ölçüde önler.
    İfade Rule 4 standardıyla aynı: perakende asıl fiyattır, indirim liste
    üzerinden vurgulanır. Uydurma indirim yok — yalnız gerçek liste>perakende.
    """
    if perakende is None:
        return ""
    if liste and liste > perakende:
        fark = round(liste) - round(perakende)
        return (f"Liste fiyatı {_tl(liste)}'den size {_tl(fark)} indirim yaptık, "
                f"güncel perakende fiyatımız {_tl(perakende)}.")
    return f"Perakende fiyatımız {_tl(perakende)}."


def _toplam_ozet(kombi) -> dict:
    t = hesapla_kombinasyon_toplam(kombi)
    return {
        "urun_sayisi": t["urun_sayisi"],
        "toplam_adet": t["toplam_adet"],
        "toplam_liste": t["toplam_liste"],
        "toplam_perakende": t["toplam_perakende"],
        "indirim_yuzde": t["indirim_yuzde"],
        "fiyat_cumlesi": fiyat_cumlesi(t["toplam_liste"], t["toplam_perakende"]),
    }


def kategoriler() -> list[dict]:
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
        return [{"id": k.id, "ad": k.ad} for k in rows]
    finally:
        session.close()


def koleksiyonlar(kategori_id: int) -> dict | None:
    """Bir kategorideki koleksiyonlar — sadece kombinasyon_sayisi > 0 olanlar."""
    session = SessionLocal()
    try:
        kategori = session.get(Kategori, kategori_id)
        if kategori is None:
            return None
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
        return {"kategori": {"id": kategori.id, "ad": kategori.ad}, "koleksiyonlar": data}
    finally:
        session.close()


def kombinasyonlar(koleksiyon_id: int) -> dict | None:
    """Bir koleksiyonun kombinasyonları, toplam fiyat özetiyle."""
    session = SessionLocal()
    try:
        koleksiyon = session.get(Koleksiyon, koleksiyon_id)
        if koleksiyon is None:
            return None
        kombi_list = kombinasyon_listele(session, koleksiyon_id)
        data = [{"id": k.id, "ad": k.ad, **_toplam_ozet(k)} for k in kombi_list]
        return {"koleksiyon": {"id": koleksiyon.id, "ad": koleksiyon.ad}, "kombinasyonlar": data}
    finally:
        session.close()


def koleksiyon_ara(q: str) -> list[dict]:
    """Ad içinde arama — AI ajanın 'MARIZA fiyatı?' gibi serbest metinden koleksiyon
    bulması için. Kombinasyonu olan koleksiyonlarda, büyük/küçük harf duyarsız."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    session = SessionLocal()
    try:
        kombi_say = (
            select(func.count(Kombinasyon.id))
            .where(Kombinasyon.koleksiyon_id == Koleksiyon.id)
            .correlate(Koleksiyon)
            .scalar_subquery()
        )
        rows = session.execute(
            select(Koleksiyon.id, Koleksiyon.ad, Koleksiyon.kategori_id,
                   kombi_say.label("ks"))
            .where(Koleksiyon.ad.ilike(f"%{q}%"))
            .order_by(Koleksiyon.ad)
            .limit(10)
        ).all()
        kategori_adlari = {k.id: k.ad for k in session.scalars(select(Kategori)).all()}
        return [
            {"id": r.id, "ad": r.ad,
             "kategori_id": r.kategori_id,
             "kategori": kategori_adlari.get(r.kategori_id, ""),
             "kombinasyon_sayisi": r.ks}
            for r in rows if (r.ks or 0) > 0
        ]
    finally:
        session.close()


# ─── Mağaza bilgi tabanı (bot_bilgi) ─────────────────────────────────────────
# Türkçe karakter sadeleştirme — "mesai" / "MESAİ" / "mesaı" hepsi eşleşsin.
_TR_DUZLE = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def _duz(s: str) -> str:
    s = (s or "").strip().translate(_TR_DUZLE).lower().translate(_TR_DUZLE)
    return s.replace("̇", "")   # İ.lower() birleşik noktası (U+0307)


def bilgi_ara(soru: str) -> list[dict]:
    """Mağaza bilgi kayıtlarında anahtar kelime eşleşmesi.

    Her bot_bilgi satırının `anahtar` alanı virgüllü kelime listesidir
    ("adres, konum, nerede"). Sorunun düzleştirilmiş halinde bu kelimelerden
    biri geçiyorsa kayıt eşleşir. AI ajan mağaza bilgisini YALNIZCA buradan
    alır — boş dönerse uydurmak yerine yetkiliye yönlendirir.
    """
    from catalog.sa_models import BotBilgi
    d = _duz(soru)
    if not d:
        return []
    session = SessionLocal()
    try:
        rows = session.scalars(select(BotBilgi)).all()
        sonuc = []
        for r in rows:
            kelimeler = [_duz(k) for k in (r.anahtar or "").split(",")]
            if any(k and k in d for k in kelimeler):
                sonuc.append({"baslik": r.baslik, "cevap": r.cevap})
        return sonuc
    finally:
        session.close()


def soru_kaydet(platform: str, kullanici: str, soru: str) -> None:
    """Cevapsız kalan müşteri sorusunu bot_soru'ya yaz (İsmail panelden cevaplar).

    Aynı kullanıcının aynı açık sorusu varsa mükerrer yazılmaz. Hata akışı
    bozmasın: yut (bilgi kaydı, müşteri cevabından önemli değil).
    """
    from catalog.sa_models import BotSoru
    soru = (soru or "").strip()[:500]
    if not soru:
        return
    try:
        session = SessionLocal()
        try:
            var = session.scalar(
                select(BotSoru).where(BotSoru.platform == platform,
                                      BotSoru.kullanici == kullanici,
                                      BotSoru.soru == soru,
                                      BotSoru.durum == "acik")
            )
            if var is None:
                session.add(BotSoru(platform=platform, kullanici=kullanici, soru=soru))
                session.commit()
        finally:
            session.close()
    except Exception:
        pass


def kombinasyon(kombi_id: int) -> dict | None:
    """Seçilen kombinasyonun fiyat detayı + içindeki ürünler."""
    session = SessionLocal()
    try:
        kombi = session.scalar(
            select(Kombinasyon)
            .where(Kombinasyon.id == kombi_id)
            .options(selectinload(Kombinasyon.urunler).selectinload(KombinasyonUrun.urun))
        )
        if kombi is None:
            return None
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
        return {
            "id": kombi.id,
            "ad": kombi.ad,
            "koleksiyon": {"id": koleksiyon.id, "ad": koleksiyon.ad} if koleksiyon else None,
            **_toplam_ozet(kombi),
            "para_birimi": "TL",
            "urunler": urunler,
        }
    finally:
        session.close()
