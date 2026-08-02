"""Teşhir servisi — mağazada sergilenen ürünler + efektif fiyat çözümü.

"Bağlı + gerekirse ez" modeli (2026-07-06 kararı):
- Kayıttaki fiyat/içerik alanı DOLUYSA o geçerli ("magaza" kaynağı).
- BOŞSA bağlı kombinasyonun güncel web verisi geçerli ("web" kaynağı).
- Kombinasyon bağlı değilse ve alan boşsa → None (fiyat belirtilmemiş).

Panel (/app/teshir/) ve AI ajanın teshir_bilgi aracı bu modülü kullanır.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from catalog.database import SessionLocal
from catalog.sa_models import Kategori, Koleksiyon, Kombinasyon, KombinasyonUrun, Teshir
from catalog.services.kombinasyon import hesapla_kombinasyon_toplam

# Kayıt başına fotoğraf sınırı. İsmail kararı 2026-08-02: 2-4 açı — teşhir malı
# sergilenmiş/kullanılmış olabildiği için müşteri kolunu, arkasını, yakın
# çekimini görmek ister. Üst sınır müşteriye 10 fotoğraf yağdırmayı engeller.
MAKS_FOTOGRAF = 4


def _kombi_yukle(session, kombi_id: int) -> Kombinasyon | None:
    return session.scalar(
        select(Kombinasyon)
        .where(Kombinasyon.id == kombi_id)
        .options(selectinload(Kombinasyon.urunler).selectinload(KombinasyonUrun.urun))
    )


def _kombi_icerik(kombi: Kombinasyon) -> str:
    return ", ".join(
        f"{ku.miktar}× {ku.urun.urun_adi_tam}"
        for ku in kombi.urunler if ku.urun is not None
    )


def _coz(session, t: Teshir) -> dict:
    """Tek teşhir kaydını efektif değerleriyle sözlüğe çevir."""
    kol = session.get(Koleksiyon, t.koleksiyon_id) if t.koleksiyon_id else None
    # Kategori: bağlı kayıtta koleksiyondan, manuel kayıtta doğrudan kayıttan.
    kat_id = kol.kategori_id if kol else t.kategori_id
    kat = session.get(Kategori, kat_id) if kat_id else None
    kol_ad = kol.ad if kol else ((t.koleksiyon_adi or "").strip() or "?")

    kombi = _kombi_yukle(session, t.kombinasyon_id) if t.kombinasyon_id else None
    web = hesapla_kombinasyon_toplam(kombi) if kombi else {}

    liste = t.liste_fiyat if t.liste_fiyat is not None else web.get("toplam_liste")
    perakende = (t.perakende_fiyat if t.perakende_fiyat is not None
                 else web.get("toplam_perakende"))
    icerik = (t.icerik or "").strip() or (_kombi_icerik(kombi) if kombi else "")
    pay = t.pazarlik_payi
    taban = (perakende - pay) if (perakende and pay and pay < perakende) else None

    return {
        "id": t.id,
        "baslik": (t.baslik or "").strip() or kol_ad,
        "kategori": kat.ad if kat else "",
        "kategori_id": kat_id,
        "koleksiyon": kol_ad,
        "koleksiyon_id": t.koleksiyon_id,
        "manuel": t.koleksiyon_id is None,
        "kombinasyon": kombi.ad if kombi else "",
        "kombinasyon_id": t.kombinasyon_id,
        "icerik": icerik,
        "liste_fiyat": liste,
        "perakende_fiyat": perakende,
        "pazarlik_payi": pay,
        "pazarlik_taban": taban,
        # Panelde "mağaza fiyatı mı web fiyatı mı" rozetleri için:
        "fiyat_kaynak": "magaza" if (t.liste_fiyat is not None
                                     or t.perakende_fiyat is not None) else "web",
        "icerik_kaynak": "magaza" if (t.icerik or "").strip() else "web",
        # Ham değerler (düzenleme formu doldurmak için):
        "ham_baslik": t.baslik or "",
        "ham_icerik": t.icerik or "",
        "ham_liste": t.liste_fiyat,
        "ham_perakende": t.perakende_fiyat,
        "ham_koleksiyon_adi": t.koleksiyon_adi or "",
        "notlar": t.notlar or "",
        "fotograflar": list(t.fotograflar or []),
        "video_url": t.video_url or "",
        "guncelleme": t.guncelleme,
    }


def listele() -> list[dict]:
    """Tüm teşhir kayıtları (panel listesi) — kategori/koleksiyon adına göre sıralı."""
    session = SessionLocal()
    try:
        rows = session.scalars(select(Teshir)).all()
        data = [_coz(session, t) for t in rows]
        data.sort(key=lambda d: (d["kategori"], d["koleksiyon"], d["baslik"]))
        return data
    finally:
        session.close()


def fotograflar(teshir_id: int) -> list[str]:
    """Bir teşhir kaydının fotoğraf URL'leri (sıralı, ilki ana fotoğraf).

    Router müşteriye göndermek için çağırır. Kayıt yoksa ya da fotoğrafı yoksa
    boş liste — akış bozulmaz, metin yine gider.
    """
    session = SessionLocal()
    try:
        kayit = session.get(Teshir, int(teshir_id))
        return [u for u in (kayit.fotograflar or []) if isinstance(u, str) and u] \
            if kayit else []
    except (TypeError, ValueError):
        return []
    finally:
        session.close()


def foto_ekle(teshir_id: int, baytlar: bytes) -> str:
    """Fotoğrafı depoya yükle ve kayda ekle; eklenen URL'i döner.

    Depoya yükleme ile DB güncellemesi ayrı iki adım: yükleme başarısızsa
    DepoHatasi yükselir ve kayda hiçbir şey yazılmaz. Tersi (yüklendi ama DB
    yazılamadı) durumunda depoda sahipsiz dosya kalır — zararsız, yer kaplar.
    """
    from catalog.services import depo

    session = SessionLocal()
    try:
        kayit = session.get(Teshir, int(teshir_id))
        if kayit is None:
            raise depo.DepoHatasi("Teşhir kaydı bulunamadı.")
        if len(kayit.fotograflar or []) >= MAKS_FOTOGRAF:
            raise depo.DepoHatasi(
                f"En fazla {MAKS_FOTOGRAF} fotoğraf eklenebilir. "
                "Yeni eklemek için birini sil.")
        url = depo.yukle(baytlar, f"teshir/{kayit.id}")
        # JSONB listesi YERİNDE değiştirilirse SQLAlchemy değişikliği görmez
        # (mutable izleme yok) ve commit sessizce hiçbir şey yazmaz.
        kayit.fotograflar = list(kayit.fotograflar or []) + [url]
        session.commit()
        return url
    finally:
        session.close()


def foto_sil(teshir_id: int, url: str) -> bool:
    """Fotoğrafı kayıttan çıkar ve depodan sil. Kayıtta yoksa False."""
    from catalog.services import depo

    session = SessionLocal()
    try:
        kayit = session.get(Teshir, int(teshir_id))
        mevcut = list(kayit.fotograflar or []) if kayit else []
        if not kayit or url not in mevcut:
            return False
        kayit.fotograflar = [u for u in mevcut if u != url]
        session.commit()
        # Önce kayıt güncellenir: depodan silinemese bile müşteriye ARTIK
        # gitmez. Ters sırada olsaydı silinmiş dosyanın linki kayıtta kalırdı.
        depo.sil(url)
        return True
    finally:
        session.close()


def ajan_icin(koleksiyon_id: int | None = None,
              ad: str | None = None) -> list[dict]:
    """AI ajanın teshir_bilgi aracı için sade görünüm.

    Yalnızca müşteriye söylenebilecek alanlar döner (iç notlar HARİÇ).
    pazarlik_taban_fiyat: müşteri pazarlık ederse ajanın inebileceği EN DÜŞÜK
    fiyat (perakende − pazarlık payı). Payın kendisi ajana verilmez.

    ad verilirse (belirli bir teşhir ürününün fiyatı sorulduğunda) sonuç, adı ya
    da koleksiyonu bu metni içeren kayıtlarla sınırlanır. Manuel (koleksiyona
    bağlı olmayan) teşhir kayıtları da böyle bulunabilir — koleksiyon_id yoktur.
    Eşleşme Türkçe-duyarsız (_duz) ve çok-kelimelidir ("legna 5 kapaklı" gibi).
    """
    from catalog.services import menu_veri
    session = SessionLocal()
    try:
        sorgu = select(Teshir)
        if koleksiyon_id:
            sorgu = sorgu.where(Teshir.koleksiyon_id == int(koleksiyon_id))
        rows = session.scalars(sorgu).all()
        sonuc = []
        for t in rows:
            d = _coz(session, t)
            kayit = {
                # id ŞART: müşteri fotoğrafı isteyince ajan [gorsel:teshir:<id>]
                # işaretini bu numarayla kurar (bkz. bot/router.py).
                "id": d["id"],
                "ad": d["baslik"],
                "kategori": d["kategori"],
                "koleksiyon": d["koleksiyon"],
                "icerik": d["icerik"],
                "liste_fiyat": d["liste_fiyat"],
                "perakende_fiyat": d["perakende_fiyat"],
                "para_birimi": "TL",
                # Yalnız SAYI/VAR-YOK gider, URL DEĞİL — adresi router çözer.
                # Model uzun bir adresi kopyalarken bozabilir (ürün fotoğrafında
                # da aynı sebeple SKU verilmişti, İsmail kararı 2026-07-28).
                "fotograf_sayisi": len(d["fotograflar"]),
                "video_var": bool(d["video_url"]),
            }
            cumle = menu_veri.fiyat_cumlesi(d["liste_fiyat"], d["perakende_fiyat"])
            if cumle:
                kayit["fiyat_cumlesi"] = cumle
            if d["pazarlik_taban"]:
                kayit["pazarlik_taban_fiyat"] = d["pazarlik_taban"]
            sonuc.append(kayit)
        if ad and ad.strip():
            istek = [t for t in (menu_veri._duz(x) for x in ad.split()) if t]
            if istek:
                istek_kume = set(istek)
                secilen = []
                for k in sonuc:
                    ad_alani = menu_veri._duz(f"{k['ad']} {k['koleksiyon']}")
                    # (a) İleri: müşterinin her kelimesi kayıt adında geçiyor
                    #     (kısa/tam sorgu: "melori", "melori koltuk").
                    ileri = all(t in ad_alani for t in istek)
                    # (b) Geri: kaydın KENDİ adı(baslik) müşteri cümlesinde geçiyor
                    #     — müşteri/story fazladan kelime eklediğinde ("Melori Koltuk
                    #     Takımı" ama baslik yalnız "MELORI"). Jenerik/kısa token
                    #     kaçağını önlemek için ≥3 harfli en az bir ad token'ı şart.
                    ad_tokenlari = [t for t in menu_veri._duz(k["ad"]).split() if t]
                    geri = (ad_tokenlari
                            and all(t in istek_kume for t in ad_tokenlari)
                            and any(len(t) >= 3 for t in ad_tokenlari))
                    if ileri or geri:
                        secilen.append(k)
                sonuc = secilen
        return sonuc
    finally:
        session.close()
