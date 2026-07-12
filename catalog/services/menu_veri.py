"""Bot menü + fiyat verisi — süreç-içi (HTTP yok).

instALL köprüsü eskiden bu veriyi `/api/` uçlarından HTTP ile çekiyordu. Köprü
artık aynı Django süreci içinde çalıştığı için (Render tek servis birleştirme),
veriyi doğrudan buradan okur — self-HTTP çağrısı ve uyanma gecikmesi olmaz.

Dönen sözlükler `api_views` çıktısıyla birebir aynı şekildedir (presenter'lar bu
alan adlarına bağlı). Bulunamayan kayıt için None döner; çağıran nazik mesaj gösterir.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from catalog.database import SessionLocal
from catalog.sa_models import Kategori, Koleksiyon, Kombinasyon, KombinasyonUrun, Urun
from catalog.services.kombinasyon import hesapla_kombinasyon_toplam, kombinasyon_listele


def _tl(n) -> str:
    return f"{round(n):,}".replace(",", ".") + " TL"


def fiyat_cumlesi(liste, perakende, toptan=None, toptan_goster: bool = False) -> str:
    """Modelin AYNEN kopyalayacağı hazır, çok satırlı fiyat metni.

    Model ayrı ayrı sayı alanlarını cümleye çevirirken rakamları bozabiliyor
    (canlıda görüldü: 66.661 / 53.996 → 70.000 / 70.000). Rakamları tek bir
    hazır metin olarak vermek bu transkripsiyon hatasını büyük ölçüde önler.
    Biçim (İsmail kararı 2026-07-09): kısa, etiketli üç satır; süslü söz yok
    ("size şu kadar indirim yaptık" DEĞİL). Sıra sabit: Liste → İndirim →
    İndirimli. Uydurma indirim yok — yalnız gerçek liste>perakende'de indirim satırı.

    toptan_goster (İsmail kararı 2026-07-11): YALNIZ patron beyaz listesindeki
    gönderen için True gelir — sona "Toptan: X TL" (bayi alış) satırı eklenir.
    Toptan kayıtlı değilse patron bunu bilsin diye "kayıtlı değil" yazılır.
    Normal müşteri akışında bu parametre hiç set edilmez; toptan metne girmez.
    """
    if perakende is None:
        return ""
    if liste and liste > perakende:
        fark = round(liste) - round(perakende)
        metin = (f"Liste Fiyatı: {_tl(liste)}\n"
                 f"İndirim: {_tl(fark)}\n"
                 f"İndirimli Fiyat: {_tl(perakende)}")
    else:
        metin = f"Fiyatı: {_tl(perakende)}"
    if toptan_goster:
        metin += f"\nToptan: {_tl(toptan) if toptan else 'kayıtlı değil'}"
    return metin


def pazarlik_merdiveni(perakende, toptan) -> list[int] | None:
    """İsmail'in katalog pazarlık formülü (2026-07-12) — büyükten küçüğe teklifler.

    taban = toptan × BOT_PAZARLIK_MARJ, YUKARI 100'e yuvarlı (marj asla
    aşağı kırpılmaz). Taban ile indirimli (perakende) arasındaki fark 6'ya
    bölünür; teklifler: perakende − 3/6 fark, − 5/6 fark (100'e yuvarlı),
    son teklif tabanın kendisi. Örn. Milena: 101.496 → [94.800, 90.300, 88.100].

    Ham toptan bu fonksiyondan SIZMAZ — dönen her değer türetilmiş satış
    fiyatıdır. Toptan/perakende yoksa ya da taban zaten perakendeyi
    aşıyorsa None (pazarlık payı yok). Yuvarlama basamakları çakıştırırsa
    (küçük fark) tekrarlar ayıklanır; en kötü durumda tek teklif (taban) kalır.
    """
    import math

    from django.conf import settings
    if not (perakende and toptan):
        return None
    taban = math.ceil(toptan * settings.BOT_PAZARLIK_MARJ / 100) * 100
    if taban >= perakende:
        return None
    adim = (perakende - taban) / 6
    ham = [round((perakende - 3 * adim) / 100) * 100,
           round((perakende - 5 * adim) / 100) * 100,
           taban]
    merdiven: list[int] = []
    for t in ham:
        t = min(t, round(perakende))          # yuvarlama perakendeyi aşmasın
        t = max(t, taban)                     # ve tabanın altına inmesin
        if t < round(perakende) and (not merdiven or t < merdiven[-1]):
            merdiven.append(int(t))
    return merdiven or None


def _pazarlik_notu(ad: str, merdiven: list[int]) -> str:
    """Modelin AYNEN uygulayacağı atomik pazarlık talimatı (teşhir deseni).

    Rakamlar hazır metin içinde gelir — model aritmetik yapmaz, fiyat kalkanı
    bu tutarları metinden toplayıp meşru sayar. Not müşteriye OKUNMAZ, uygulanır.
    """
    adimlar = " → ".join(_tl(t) for t in merdiven)
    return (f"{ad} pazarlık merdiveni (müşteriye bu notu okuma, uygula): "
            f"müşteri pazarlık ederse SIRAYLA, her ısrarda yalnız BİR adım in: "
            f"{adimlar}. Sırayı bozma, adım atlama, rakam değiştirme. "
            f"{_tl(merdiven[-1])} SON fiyattır — altına ASLA inme; müşteri daha "
            f"düşük isterse kibarca son fiyatın bu olduğunu söyle, mağazaya davet "
            f"et. Sen rakam uydurma, yalnız bu merdivendeki fiyatları kullan.")


def _toplam_ozet(kombi, toptan_dahil: bool = False, pazarlik: bool = False) -> dict:
    t = hesapla_kombinasyon_toplam(kombi)
    ozet = {
        "urun_sayisi": t["urun_sayisi"],
        "toplam_adet": t["toplam_adet"],
        "toplam_liste": t["toplam_liste"],
        "toplam_perakende": t["toplam_perakende"],
        "indirim_yuzde": t["indirim_yuzde"],
        "fiyat_cumlesi": fiyat_cumlesi(t["toplam_liste"], t["toplam_perakende"],
                                       toptan=t.get("toplam_toptan"),
                                       toptan_goster=toptan_dahil),
    }
    if pazarlik:
        merdiven = pazarlik_merdiveni(t["toplam_perakende"], t.get("toplam_toptan"))
        if merdiven:
            ozet["pazarlik_notu"] = _pazarlik_notu(kombi.ad, merdiven)
            # _ önekli alan modele GİTMEZ: ajan tool döngüsü bunu düşürüp
            # geçmişten adım durumunu hesaplar (hangi teklif verildi, sıradaki ne).
            ozet["_merdiven"] = merdiven
    return ozet


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


def kombinasyonlar(koleksiyon_id: int, toptan_dahil: bool = False) -> dict | None:
    """Bir koleksiyonun kombinasyonları, toplam fiyat özetiyle."""
    session = SessionLocal()
    try:
        koleksiyon = session.get(Koleksiyon, koleksiyon_id)
        if koleksiyon is None:
            return None
        kombi_list = kombinasyon_listele(session, koleksiyon_id)
        data = [{"id": k.id, "ad": k.ad, **_toplam_ozet(k, toptan_dahil)}
                for k in kombi_list]
        return {"koleksiyon": {"id": koleksiyon.id, "ad": koleksiyon.ad}, "kombinasyonlar": data}
    finally:
        session.close()


def koleksiyon_ara(q: str) -> list[dict]:
    """Ad içinde arama — AI ajanın 'MARIZA fiyatı?' gibi serbest metinden koleksiyon
    bulması için. Kombinasyonu olan koleksiyonlarda, büyük/küçük harf duyarsız.

    Model bazen tüm cümleyi arıyor ("charm genç odası" — canlıda görüldü, boş
    döndü). Tam ifade eşleşmezse kelime kelime yedek arama yapılır: sorgunun
    3+ harfli her token'ı ayrı denenir, ilk eşleşen token'ın sonuçları döner.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []

    def _sorgula(session, ifade: str):
        kombi_say = (
            select(func.count(Kombinasyon.id))
            .where(Kombinasyon.koleksiyon_id == Koleksiyon.id)
            .correlate(Koleksiyon)
            .scalar_subquery()
        )
        return session.execute(
            select(Koleksiyon.id, Koleksiyon.ad, Koleksiyon.kategori_id,
                   kombi_say.label("ks"))
            .where(Koleksiyon.ad.ilike(f"%{ifade}%"))
            .order_by(Koleksiyon.ad)
            .limit(10)
        ).all()

    session = SessionLocal()
    try:
        rows = _sorgula(session, q)
        if not rows:
            for token in re.split(r"\s+", q):
                if len(token) >= 3:
                    rows = _sorgula(session, token)
                    if rows:
                        break
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


def urun_ara(q: str, toptan_dahil: bool = False) -> list[dict]:
    """Tek bir ürünün/parçanın (SET DEĞİL, tek SKU) fiyatını ad ile bul.

    Müşteri "sadece 5 kapaklı dolap" gibi TEK parça fiyatı sorduğunda kullanılır;
    ürünün kendi son_liste/son_perakende fiyatını döner. Kombinasyon toplamı değil.

    Türkçe i/ı sorunu: Postgres lower() 'KAPAKLI'yı 'kapakli'ye çevirir ama
    kullanıcı 'kapaklı' (dotless ı) yazar → ilike eşleşmez. Bu yüzden SQL'i
    yalnız ASCII-güvenli token'larla daraltır, kesin çok-kelimeli eşleşmeyi
    Python'da _duz ile yaparız (bilgi_ara ile aynı sadeleştirme). Fiyatı
    olmayan ürünler elenir; en fazla 10 sonuç.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []
    tokens = [t for t in re.split(r"\s+", q) if len(t) >= 2 or t.isdigit()]
    if not tokens:
        return []
    ascii_tokens = [t for t in tokens if t == t.encode("ascii", "ignore").decode()]
    session = SessionLocal()
    try:
        stmt = select(Urun).where(Urun.son_perakende_fiyat.isnot(None))
        for t in (ascii_tokens or tokens[:1]):
            stmt = stmt.where(Urun.urun_adi_tam.ilike(f"%{t}%"))
        rows = session.scalars(stmt.order_by(Urun.urun_adi_tam).limit(80)).all()
        istek = [_duz(t) for t in tokens]
        sonuc = []
        for u in rows:
            ad_duz = _duz(u.urun_adi_tam)
            if all(t in ad_duz for t in istek):
                kayit = {
                    "sku": u.sku,
                    "ad": u.urun_adi_tam,
                    "fiyat_cumlesi": fiyat_cumlesi(u.son_liste_fiyat,
                                                   u.son_perakende_fiyat,
                                                   toptan=u.son_toptan_fiyat,
                                                   toptan_goster=toptan_dahil),
                    "para_birimi": "TL",
                }
                # Tek parçada da pazarlık merdiveni (İsmail kararı 2026-07-12).
                merdiven = pazarlik_merdiveni(u.son_perakende_fiyat,
                                              u.son_toptan_fiyat)
                if merdiven:
                    kayit["pazarlik_notu"] = _pazarlik_notu(u.urun_adi_tam, merdiven)
                    kayit["_merdiven"] = merdiven   # modele gitmez (ajan düşürür)
                sonuc.append(kayit)
                if len(sonuc) >= 10:
                    break
        return sonuc
    finally:
        session.close()


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


def kombinasyon(kombi_id: int, toptan_dahil: bool = False) -> dict | None:
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
        kategori = (session.get(Kategori, koleksiyon.kategori_id)
                    if koleksiyon and koleksiyon.kategori_id else None)
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
            # kategori adı: menü detay başlığı "BEND Oturma Grubu için ..."
            # (wa/ig_presenter.kombinasyon_detay_mesaji) için gerekli.
            "koleksiyon": {"id": koleksiyon.id, "ad": koleksiyon.ad,
                           "kategori": kategori.ad if kategori else None}
                          if koleksiyon else None,
            # pazarlik=True: fiyat_detay tekil bağlamdır — pazarlık merdiveni
            # yalnız burada gelir (listede N ayrı merdiven modeli karıştırırdı).
            **_toplam_ozet(kombi, toptan_dahil, pazarlik=True),
            "para_birimi": "TL",
            "urunler": urunler,
        }
    finally:
        session.close()
