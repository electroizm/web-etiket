"""Bot menü + fiyat verisi — süreç-içi (HTTP yok).

instALL köprüsü eskiden bu veriyi `/api/` uçlarından HTTP ile çekiyordu. Köprü
artık aynı Django süreci içinde çalıştığı için (Render tek servis birleştirme),
veriyi doğrudan buradan okur — self-HTTP çağrısı ve uyanma gecikmesi olmaz.

Dönen sözlükler `api_views` çıktısıyla birebir aynı şekildedir (presenter'lar bu
alan adlarına bağlı). Bulunamayan kayıt için None döner; çağıran nazik mesaj gösterir.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from catalog.database import SessionLocal
from catalog.sa_models import Kategori, Koleksiyon, Kombinasyon, KombinasyonUrun, Urun
from catalog.services.kombinasyon import hesapla_kombinasyon_toplam, kombinasyon_listele

log = logging.getLogger(__name__)


def _tl(n) -> str:
    return f"{round(n):,}".replace(",", ".") + " TL"


# ─── Satış fiyatı — TOPTANDAN hesaplanır (İsmail kararı 2026-09-17) ──────────
# Eskiden müşteriye söylenen fiyat etiket toplamıydı (parça perakende toplamı).
# Artık fiyat BAYİ ALIŞ (toptan) tutarından türetilir — PRGv2'nin pazarlık
# merdiveniyle aynı hesap, iki kademe:
#     ilk fiyat = toptan × bot_marj_ilk   (vars. 1,37 — PRGv2'de "Sepet")
#     son fiyat = toptan × bot_marj_son   (vars. 1,31 — PRGv2'de "Müdür")
# İkisi de 100'e YUKARI yuvarlanır (marj asla aşağı kırpılmaz). Çarpanlar
# app_ayarlari'ndan okunur, panelden değiştirilebilir. settings.BOT_PAZARLIK_MARJ
# (1,27) KOD TABANIDIR: ayar yanlış girilse bile hiçbir teklif toptan × 1,27'nin
# altına inemez. Ham toptan bu modülden DIŞARI SIZMAZ — dönen her tutar
# türetilmiş satış fiyatıdır.
AYAR_MARJ_ILK = "bot_marj_ilk"
AYAR_MARJ_SON = "bot_marj_son"
VARSAYILAN_MARJ_ILK = 1.37
VARSAYILAN_MARJ_SON = 1.31
_MARJ_ONBELLEK_SN = 300
_marj_onbellek: tuple[float, tuple[float, float]] | None = None


def _marjlar() -> tuple[float, float]:
    """(ilk, son) marj çarpanları — DB ayarından, 5 dakikalık önbellekle.

    Her fiyat hesabında DB'ye gitmek mesaj başına birkaç sorgu ekler, oysa
    ayarlar nadiren değişir. Ayar yoksa/bozuksa (boş, metin, sıra ters)
    varsayılana düşülür — fiyat akışı tek bir ayar yüzünden durmaz.
    """
    global _marj_onbellek
    from time import monotonic
    simdi = monotonic()
    if _marj_onbellek and simdi - _marj_onbellek[0] < _MARJ_ONBELLEK_SN:
        return _marj_onbellek[1]
    ilk, son = VARSAYILAN_MARJ_ILK, VARSAYILAN_MARJ_SON
    try:
        from catalog.services.ayarlar import get_ayar
        session = SessionLocal()
        try:
            ilk = float((get_ayar(session, AYAR_MARJ_ILK) or "").replace(",", ".")
                        or VARSAYILAN_MARJ_ILK)
            son = float((get_ayar(session, AYAR_MARJ_SON) or "").replace(",", ".")
                        or VARSAYILAN_MARJ_SON)
        finally:
            session.close()
    except Exception:
        ilk, son = VARSAYILAN_MARJ_ILK, VARSAYILAN_MARJ_SON
    if not (0 < son <= ilk):        # bozuk/ters ayar → varsayılan
        ilk, son = VARSAYILAN_MARJ_ILK, VARSAYILAN_MARJ_SON
    _marj_onbellek = (simdi, (ilk, son))
    return ilk, son


def _yuz_yukari(x: float) -> int:
    """100 TL'ye YUKARI yuvarla (88.092 → 88.100) — PRGv2 ile aynı kural."""
    import math
    return math.ceil(x / 100) * 100


def satis_fiyatlari(toptan) -> tuple[int, int] | None:
    """Toptan tutardan (ilk fiyat, son fiyat). Toptan kayıtlı değilse None."""
    from django.conf import settings
    if not toptan or toptan <= 0:
        return None
    ilk_marj, son_marj = _marjlar()
    taban = _yuz_yukari(toptan * settings.BOT_PAZARLIK_MARJ)   # kod kalkanı
    son = max(_yuz_yukari(toptan * son_marj), taban)
    ilk = max(_yuz_yukari(toptan * ilk_marj), son)
    return ilk, son


def fiyat_cumlesi(liste, satis) -> str:
    """Modelin AYNEN kopyalayacağı hazır fiyat metni (İsmail kararı 2026-09-17).

    Model ayrı ayrı sayı alanlarını cümleye çevirirken rakamları bozabiliyor
    (canlıda görüldü: 66.661 / 53.996 → 70.000 / 70.000). Rakamları tek bir
    hazır metin olarak vermek bu transkripsiyon hatasını büyük ölçüde önler.

    Biçim İKİ satır: çapa olarak liste fiyatı, altında müşteriye söylenen fiyat.
    Hesaplanan fiyat listeye eşit/üstündeyse (katalogda 3 kombinasyonda oluyor)
    çapa YAZILMAZ — "indirim" diye artı bir rakam göstermek güveni bozar.
    """
    if not satis:
        return ""
    if liste and round(liste) > round(satis):
        return (f"Liste Fiyatı: {_tl(liste)}\n"
                f"Size Özel: {_tl(satis)}")
    return f"Fiyatı: {_tl(satis)}"


# Toptan verisi akla yatkın mı? Ölçüm (2026-09-17, toptanı olan 1.611 ürün):
# perakende/toptan oranı medyan 1,58 — %5-%95 aralığı 1,32-1,67, yani veri
# normalde çok dar bir bantta. Bandın DIŞINDAKİ kayıtlarda toptan bozuktur:
#   • oran çok YÜKSEK (BOLD Kitaplık 5,71 · MAYER Üçlü Yataklı 4,47) → yanlış
#     SAP eşleşmesi; bu kayıttan hesaplanan fiyat 32.582 TL'lik çekyatı
#     10.000 TL'ye satar.
#   • oran çok DÜŞÜK (ROBIN'in dört varyantına da 49.500 toptan yazılmış,
#     perakendesi 15.999-42.999) → takım fiyatı parçaya yazılmış; hesaplanan
#     fiyat web fiyatının 4 katı çıkar.
# Şüpheli kayıtta toptan KULLANILMAZ: bugünkü davranışa (web perakende fiyatı,
# pazarlıksız) düşülür ve uyarı loglanır. Bandı daraltmak/genişletmek gerekirse
# tek yer burasıdır; şu an katalogun ~%4'ü bu yola düşüyor.
ORAN_ALT, ORAN_UST = 1.25, 2.05


def fiyat_paketi(liste, perakende, toptan) -> dict:
    """Katalog fiyatı: hazır fiyat cümlesi + (varsa) iki adımlı pazarlık merdiveni.

    Toptan kayıtlıysa fiyat ondan hesaplanır; müşteri pazarlık ederse TEK adım
    inilir (ilk → son). Toptan YOKSA — katalogda ~70 parça, ayrıca takım
    SKU'larının tamamı — ya da toptan ŞÜPHELİYSE (bkz. ORAN_ALT/ORAN_UST) web
    perakende fiyatı söylenir ve pazarlık YAPILMAZ: maliyetini bilmediğimiz
    üründe indirim vermek risklidir (İsmail 2026-09-17).

    `_merdiven` alanı modele GİTMEZ; çağıran (ajan tool döngüsü) onu düşürüp
    yerine "ADIM DURUMU" notunu koyar. Bu yüzden yalnız pazarlık bağlamı olan
    tekil çağrılarda üretilir — çoklu listede pazarlık hangi ürüne ait olacağı
    belirsiz kalır.
    """
    if perakende and toptan and toptan > 0:
        oran = perakende / toptan
        if not (ORAN_ALT <= oran <= ORAN_UST):
            log.warning("fiyat: toptan ŞÜPHELİ (oran %.2f — perakende %s, toptan %s); "
                        "web fiyatına düşüldü, pazarlık kapalı", oran, perakende, toptan)
            return {"fiyat_cumlesi": fiyat_cumlesi(liste, perakende)}
    fiyatlar = satis_fiyatlari(toptan)
    if fiyatlar:
        ilk, son = fiyatlar
        paket = {"fiyat_cumlesi": fiyat_cumlesi(liste, ilk)}
        if son < ilk:
            paket["_merdiven"] = [ilk, son]
        return paket
    if perakende:
        return {"fiyat_cumlesi": fiyat_cumlesi(liste, perakende)}
    return {}


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
            f"et. Sen rakam uydurma, yalnız bu merdivendeki fiyatları kullan. "
            # BİÇİM kuralı: canlıda (2026-08-03) model pazarlık fiyatını
            # "İndirimli Fiyat" satırına yazdı ve blok tutarsız kaldı
            # (70.894 − 13.471 = 57.423, ama satırda 54.800 yazıyordu).
            # Müşteri hesabı yapınca yanlış/oyun gibi görünüyor.
            f"BİÇİM: pazarlık fiyatını verirken 'Liste Fiyatı/Size Özel' "
            f"bloğunu TEKRAR YAZMA — o blok ilk fiyattır, pazarlık değil. "
            f"Yalnız TEK satır yaz: 'Size özel fiyatımız: <tutar> TL'. "
            f"Pazarlık teklifi verdiğin cevapta müşteriyi 'yetkili'ye YÖNLENDİRME.")


def _toplam_ozet(kombi, pazarlik: bool = False) -> dict:
    """Kombinasyonun fiyat özeti. pazarlik=False ise merdiven ÜRETİLMEZ.

    Merdiven yalnız tekil (fiyat_detay) bağlamda anlamlıdır; çoklu listede
    hangi ürünün pazarlığı olduğu belirsiz kalır. `_merdiven` alanını ajan tool
    döngüsü düşürür — pazarlik=False'ta hiç doğmasın diye burada ayıklanır.
    """
    t = hesapla_kombinasyon_toplam(kombi)
    ozet = {
        "urun_sayisi": t["urun_sayisi"],
        "toplam_adet": t["toplam_adet"],
        **fiyat_paketi(t["toplam_liste"], t["toplam_perakende"],
                       t.get("toplam_toptan")),
    }
    merdiven = ozet.pop("_merdiven", None)
    if pazarlik and merdiven:
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


def kombinasyonlar(koleksiyon_id: int, fiyatli: bool = False) -> dict | None:
    """Bir koleksiyonun takım seçenekleri — NUMARALI.

    Varsayılan FİYATSIZ (İsmail kararı 2026-09-17): müşteriye önce seçenekler
    sunulur, fiyat ancak seçtiği kombinasyon için verilir (fiyat_detay). Böylece
    hem mesaj kısalır hem pazarlık hangi ürün üzerine olduğu belirsiz kalmaz.

    Numaralandırma (İsmail isteği 2026-09-17): her seçeneğin sabit bir sırası
    (`no`) vardır ve `secenek_metni` bu sırayla hazır metin olarak döner. Sıra
    KODDA belirlenir, modelde değil — çünkü aynı numaralar butonlara da
    basılıyor (bkz. router `KOM:` payload'ı) ve metindeki "3" ile butondaki
    "3" aynı kombinasyonu göstermek ZORUNDA.
    """
    session = SessionLocal()
    try:
        koleksiyon = session.get(Koleksiyon, koleksiyon_id)
        if koleksiyon is None:
            return None
        kombi_list = kombinasyon_listele(session, koleksiyon_id)
        kategori = (session.get(Kategori, koleksiyon.kategori_id)
                    if koleksiyon.kategori_id else None)
        data = []
        for no, k in enumerate(kombi_list, 1):
            kayit = {"no": no, "id": k.id, "ad": k.ad}
            if fiyatli:
                kayit.update(_toplam_ozet(k))
            else:
                t = hesapla_kombinasyon_toplam(k)
                kayit["urun_sayisi"] = t["urun_sayisi"]
                kayit["toplam_adet"] = t["toplam_adet"]
            data.append(kayit)
        return {"koleksiyon": {"id": koleksiyon.id, "ad": koleksiyon.ad,
                               "kategori": kategori.ad if kategori else None,
                               "tam_ad": koleksiyon_tam_ad(koleksiyon.ad,
                                                           kategori.ad if kategori else None),
                               "video_var": bool(koleksiyon.video_url)},
                "kombinasyonlar": data,
                "secenek_metni": secenek_metni(data)}
    finally:
        session.close()


def koleksiyon_tam_ad(koleksiyon_ad: str, kategori_ad: str | None) -> str:
    """'LEGNA' + 'Yatak Odası' → 'LEGNA Yatak Odası' (müşteriye görünen başlık).

    Kategori adı koleksiyon adında zaten geçiyorsa tekrar edilmez. Kategori
    adındaki "Doğtaş" öneki atılır: kendi mağazamızın mesajında marka adını
    tekrarlamak gereksiz ("NORTH Doğtaş Genç ve Çocuk Odası" → "NORTH Genç ve
    Çocuk Odası").
    """
    kol = (koleksiyon_ad or "").strip()
    kat = (kategori_ad or "").strip()
    if kat.lower().startswith("doğtaş ") or kat.lower().startswith("dogtas "):
        kat = kat.split(" ", 1)[1].strip()
    if not kat or _duz(kat) in _duz(kol):
        return kol
    return f"{kol} {kat}"


def secenek_metni(kombinasyonlar_listesi: list[dict]) -> str:
    """Numaralı seçenek listesi — modelin AYNEN kopyalayacağı hazır metin.

    Biçim (İsmail 2026-09-17):
        1. 5 Kapaklı 160 Karyola
        2. 5 Kapaklı Baza
    """
    return "\n".join(f"{k['no']}. {k['ad']}" for k in kombinasyonlar_listesi)


# ─── Türkçe karakter duyarsız arama ──────────────────────────────────────────
# Postgres'in lower()'ı Türkçe bilmez: lower('Şifonyer') = 'şifonyer', dolayısıyla
# ilike('%sifonyer%') TUTMAZ. Aynı şekilde lower('MASSİMO') = 'massi̇mo' olduğu
# için ASCII yazılmış 'MASSIMO' ile eşleşmez. Tuzak İKİ YÖNLÜ ve büyük:
#
#   Ölçüm (2026-08-02, canlı katalog):
#     • Fiyatlı 1.783 üründen 876'sı (yarısı) müşteri Türkçe karakter
#       yazmadan arayınca ERİŞİLEMİYORDU — "sifonyer", "tv unitesi",
#       "calisma masasi", "genc odasi" hepsi 0 sonuç.
#     • Ters yönde 124 koleksiyon varyantı boş dönüyordu: katalogdaki ASCII
#       'FIOREN/CALISTA/LILY/KALIA/ARIANE' adlarını Türkçe klavyeyle yazan
#       müşteri ('FİOREN') bulamıyordu.
#     • Canlı kayıp müşteri (28.07): "MASSİMO Fiyat ogrenebilirmiyim" →
#       "sistemimizde bulunamadı", oysa MASSIMO katalogda var.
#
# Çözüm: karşılaştırmanın İKİ tarafını da tr_norm() ile ASCII'ye katla.
# tr_norm() Postgres tarafında migration 0006 ile tanımlı; Python karşılığı
# _duz(). İkisinin aynı sonucu verdiğini test tüm katalog adlarında doğrular.
#
# Bu bir BENZERLİK/fuzzy araması DEĞİL (İsmail kararı 2026-07-12): normalize
# edilmiş metinde KESİN alt dize eşleşmesi. 'kira' → 'KIERA' hâlâ eşleşmez.
_TR_DUZLE = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def _duz(s: str) -> str:
    """Türkçe karakterleri ASCII'ye katla + küçült. SQL tr_norm() ile aynı sonuç."""
    s = (s or "").strip().translate(_TR_DUZLE).lower().translate(_TR_DUZLE)
    return s.replace("̇", "")   # İ.lower() birleşik noktası (U+0307)


def _kalip(ifade: str) -> str:
    """Kullanıcı metnini LIKE kalıbına çevirir; % ve _ arama karakteri sayılmaz."""
    d = _duz(ifade).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{d}%"


def _ad_gibi(kolon, ifade: str):
    """`kolon` içinde `ifade` geçiyor mu — Türkçe karakter farkını yok sayarak."""
    return func.tr_norm(kolon).like(_kalip(ifade), escape="\\")


# ─── Kategori ipucu ayıklaması ───────────────────────────────────────────────
# Müşterinin kategoriyi söylerken kullandığı kelimeler ↔ katalog kategorisi.
# "yatak odası takımı" → Yatak Odası. Tek kelime yeter ("yatak", "tv").
# (Önce yalnız teşhir tarafındaydı; 2026-09-18'de katalog araması da aynı
# ayıklamayı kullansın diye buraya taşındı — canlı vaka: müşteri "milena
# YATAK ODASI fiyatı ne kadar" yazdı, bot yine de "hangi kategori?" diye
# sordu, oysa cevap mesajın içindeydi.)
KATEGORI_IPUCLARI = {
    "yatak odasi": ("yatak",),
    "yemek odasi": ("yemek",),
    "oturma grubu": ("oturma", "koltuk", "kanepe", "berjer"),
    "tv uniteleri": ("tv", "unite", "unitesi"),
    "dogtas genc ve cocuk odasi": ("genc", "cocuk"),
}
# Kategori adlarında ORTAK geçen, hiçbir şeyi AYIRT ETMEYEN kelimeler.
# "odasi" hem Yatak Odası'nda hem Yemek Odası'nda var: müşteri "yatak odası"
# dediğinde "odasi" yüzünden Yemek Odası da eşleşiyordu.
KATEGORI_JENERIK = frozenset((
    "odasi", "oda", "grubu", "grup", "takimi", "takim", "uniteleri",
    "urunleri", "seti", "dogtas", "genc",
))


def kategori_geciyor_mu(kategori: str | None, istek_kume: set[str]) -> bool:
    """Müşterinin cümlesi bu kategoriyi işaret ediyor mu?"""
    if not kategori:
        return False
    duz = _duz(kategori)
    ipuclari = set(KATEGORI_IPUCLARI.get(duz, ()))
    # Haritada olmayan kategoriler için ad kelimelerine düş — ama JENERİK
    # olanları AT, yoksa "odasi" iki kategoriyi birden eşleştirir.
    ipuclari.update(t for t in duz.split()
                    if len(t) >= 3 and t not in KATEGORI_JENERIK)
    return bool(ipuclari & istek_kume)


def kategoriye_gore_suz(kayitlar: list[dict], metin: str) -> list[dict]:
    """Serbest metinde kategori geçiyorsa eşleşmeleri ona indir.

    Hiçbiri tutmazsa liste OLDUĞU GİBİ döner — süzgeç sonuç kaybettirmez,
    yalnız müşterinin söylediği kategori varsa onu öne çıkarır.
    """
    if not kayitlar or not metin:
        return kayitlar
    istek = {t for t in _duz(metin).split() if t}
    if not istek:
        return kayitlar
    secilen = [k for k in kayitlar
               if kategori_geciyor_mu(k.get("kategori"), istek)]
    return secilen or kayitlar


def koleksiyon_ara(q: str) -> list[dict]:
    """Ad içinde arama — AI ajanın 'MARIZA fiyatı?' gibi serbest metinden koleksiyon
    bulması için. Kombinasyonu olan koleksiyonlarda, büyük/küçük harf duyarsız.

    Eşleşme Türkçe karakterden bağımsızdır (_ad_gibi): müşteri 'FİOREN' yazsa da
    katalogdaki 'FIOREN' bulunur, tersi de geçerlidir.

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
            .where(_ad_gibi(Koleksiyon.ad, ifade))
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


# Ürün aramasında anlam taşımayan dolgu kelimeler (_duz'lanmış halleriyle).
# Model bazen tüm cümleyi aratıyor ("zigon sehpa fiyatı" gibi); her token'ı
# adda arayan kesin eşleşme dolgu kelime yüzünden boş dönüyordu.
_ARAMA_GURULTU = frozenset((
    "fiyat", "fiyati", "fiyatlar", "fiyatlari", "ne", "kadar", "kac", "para",
    "tl", "icin", "sadece", "tek", "yalniz", "basina", "bilgi", "bilgisi",
    "adet", "tane", "lutfen", "acaba", "istiyorum", "isterim", "alabilir",
    "verir", "miyim", "misin", "olur", "olabilir", "rica", "urun", "urunu",
))


def urun_ara(q: str) -> list[dict]:
    """Tek bir ürünün/parçanın (SET DEĞİL, tek SKU) fiyatını ad ile bul.

    Müşteri "sadece 5 kapaklı dolap" gibi TEK parça fiyatı sorduğunda kullanılır;
    ürünün kendi son_liste/son_perakende fiyatını döner. Kombinasyon toplamı değil.

    Eşleşme Türkçe karakterden bağımsızdır (_ad_gibi → tr_norm): müşteri
    "sifonyer" yazsa da katalogdaki "Şifonyer" bulunur. Her token adda GEÇMEK
    ZORUNDA (AND). Fiyatı olmayan ürünler elenir; en fazla 10 sonuç.

    Tam eşleşme boş kalırsa kelime kelime KESİN yedek devreye girer
    (benzerlik/fuzzy DEĞİL — İsmail kararı 2026-07-12): eşleşen token'lar
    gerçek adları bulur, en çok token tutturan öne gelir, model müşteriye
    hangisini kastettiğini sorar.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []
    tokens = [t for t in re.split(r"\s+", q) if len(t) >= 2 or t.isdigit()]
    tokens = [t for t in tokens if _duz(t) not in _ARAMA_GURULTU] or tokens
    if not tokens:
        return []
    session = SessionLocal()
    try:
        stmt = select(Urun).where(Urun.son_perakende_fiyat.isnot(None))
        for t in tokens:
            stmt = stmt.where(_ad_gibi(Urun.urun_adi_tam, t))
        rows = session.scalars(stmt.order_by(Urun.urun_adi_tam).limit(80)).all()
        istek = [_duz(t) for t in tokens]
        if not rows:
            # Kelime kelime KESİN yedek (benzerlik DEĞİL): "milana zigon sehpa"
            # hiçbir adla tam eşleşmez (canlı vaka 2026-07-12: sesli mesaj
            # transkripti "Milena"yı "Milana" yazdı) ama "zigon"/"sehpa"
            # token'ları gerçek adları bulur. En çok token tutturan adlar öne
            # gelir; model müşteriye hangisini kastettiğini sorar
            # (koleksiyon_ara'daki tam-ifade yedeğiyle aynı desen).
            aday = {}
            for t in tokens:
                if len(t) < 3:
                    continue
                for u in session.scalars(
                        select(Urun)
                        .where(Urun.son_perakende_fiyat.isnot(None),
                               _ad_gibi(Urun.urun_adi_tam, t))
                        .limit(40)).all():
                    aday[u.id] = u

            def _skor(u) -> int:
                ad = _duz(u.urun_adi_tam)
                return sum(1 for t in istek if t in ad)

            rows = sorted((u for u in aday.values() if _skor(u) > 0),
                          key=lambda u: (-_skor(u), u.urun_adi_tam))
        sonuc = []
        for u in rows:
            # Tek parçada da pazarlık merdiveni (İsmail kararı 2026-07-12);
            # fiyat ve merdiven artık toptandan hesaplanır (2026-09-17).
            paket = fiyat_paketi(u.son_liste_fiyat, u.son_perakende_fiyat,
                                 u.son_toptan_fiyat)
            kayit = {
                "sku": u.sku,
                "ad": u.urun_adi_tam,
                "para_birimi": "TL",
                **paket,
            }
            merdiven = kayit.get("_merdiven")
            if merdiven:
                kayit["pazarlik_notu"] = _pazarlik_notu(u.urun_adi_tam, merdiven)
            sonuc.append(kayit)
            if len(sonuc) >= 10:
                break
        return sonuc
    finally:
        session.close()


# ─── "En uygun fiyatlı" listesi ──────────────────────────────────────────────
# Müşteri seri adı vermeden "çekyat / kanepe / koltuk" derse yetkiliye
# yönlendirmek yerine en ucuz birkaç seçeneği fiyatıyla sun (İsmail 2026-07-28).
#
# Katalog gerçekleri (2026-07-28'de ölçüldü — tasarımı bunlar belirledi):
#   • "çekyat" ve "kanepe" diye ÜRÜN YOK (0 kayıt). Karşılıkları "... Yataklı
#     Koltuk". Bu yüzden tip → ad token'ı eşlemesi şart.
#   • 19 ürünün fiyatı 0 TL. Ham "en ucuz" sıralaması bunları başa alır ve bot
#     "en uygun seçeneğimiz 0 TL" derdi → fiyat > 0 filtresi ZORUNLU.
#   • Aynı model onlarca SKU ile tekrarlıyor (LEA Üçlü Yataklı Koltuk 12 kayıt)
#     → ada göre tekilleştirilmezse liste aynı ismi 3 kez yazar.
#
# Değer: adda AYNI ANDA geçmesi gereken token'lar (_duz'lanmış hâlleriyle).
# Türkçe karakter derdi yok — eşleşme _ad_gibi/tr_norm ile yapılır, "yatakli"
# katalogdaki "Yataklı" ile eşleşir.
# "uclu" her ikisinde de var: İsmail kararı (2026-07-28) çekyatta da yalnız
# ÜÇLÜ modeller listelensin — İkili modeller daha ucuz olduğu için listeyi
# domine ediyordu (ilk üç sıra ikiliydi), oysa müşteriye üçlü sunulmak isteniyor.
EN_UYGUN_TIPLERI: dict[str, tuple[str, ...]] = {
    "cekyat": ("uclu", "yatakli", "koltuk"),
    "koltuk": ("uclu", "koltuk"),
}
# "çekyat" niyetini ele veren kelimeler (_duz'lanmış). Bunlar YOKSA ve mesajda
# "koltuk/oturma" varsa düz üçlü koltuk listesi verilir.
_CEKYAT_KELIMELERI = ("cekyat", "cek yat", "kanepe", "yatakli", "yatak olan",
                      "yataga donusen", "yatakli koltuk")

# Adı token'lara uysa da bu listeye girmemesi gereken ürünler. "Bahçe" koltuğu
# fiyatça ucuz olduğu için listenin başına geçiyordu (TEONA/WINONA canlı veride
# 2. ve 7. sıradaydı); salon koltuğu soran müşteriye bahçe mobilyası önerilmesin.
_EN_UYGUN_HARIC = ("bahce",)

# Ana ürün DEĞİL, parça/aksesuar olan kayıtlar. Ucuz oldukları için "en ucuz"
# sıralamasının başına geçiyorlardı: "gardırop" araması "Dolap İçi Dar Raf",
# "şifonyer" araması "Konsol - Şifonyer AYNASI" döndürüyordu (2026-07-28).
# Müşteriye fotoğrafındaki mobilyaya karşılık raf/ayna göstermek işe yaramaz.
# NOT: "modul" BİLEREK listede yok — katalog modüler, TV ünitesi/dolap gerçekten
# modül olarak satılıyor; onu elesek satılan ürünün kendisini elemiş oluruz.
_PARCA_KELIMELERI = ("raf", "ayna", "minder", "cep", "aksesuar", "ici",
                     "tekerlek", "aparat", "govde")


# Görselden gelen tarifte geçen ama katalogda BULUNMAYAN kelimeler. Ölçüm
# (2026-07-28): 1.764 fiyatlı üründen yalnız 11'inde renk adı geçiyor — renge
# göre arama boş döner. Model "bej üçlü koltuk" derse "bej"i atıp "üçlü koltuk"
# ile aramalıyız, yoksa hiçbir şey bulunmaz.
_ESLESMEYEN_KELIMELER = frozenset((
    # renkler
    "bej", "gri", "antrasit", "krem", "kahve", "kahverengi", "mavi", "yesil",
    "beyaz", "siyah", "bordo", "lacivert", "pudra", "vizon", "turuncu",
    "sari", "mor", "pembe", "haki", "somon", "tas", "acik", "koyu",
    # malzeme / doku / biçim — üründe yazmıyor
    "kumas", "deri", "suet", "kadife", "ahsap", "metal", "cam", "mermer",
    "ayakli", "ayak", "modern", "klasik", "sik", "genis", "buyuk", "kucuk",
    "renkli", "renk", "desenli", "duz",
))


def _tip_tokenlari(tip: str) -> list[str]:
    """Serbest tarifi katalogda aranabilir token'lara indir (renk/malzeme atılır)."""
    d = _duz(tip)
    tokenlar = [t for t in re.split(r"[^0-9a-z]+", d) if len(t) >= 3]
    süzülmüş = [_TIP_ES_ANLAM.get(t, t) for t in tokenlar
                if t not in _ARAMA_GURULTU and t not in _ESLESMEYEN_KELIMELER]
    return süzülmüş or tokenlar


# Müşterinin/görselin kullandığı kelime ile katalogdaki kelime farklı olabilir.
# Ölçüldü (2026-07-28): "gardırop" katalogda HİÇ geçmiyor, karşılığı "Dolap".
_TIP_ES_ANLAM = {"gardirop": "dolap", "gardrop": "dolap", "elbiselik": "dolap"}

# "koltuk" kısayolu (= üçlü koltuk) YALNIZ tip genelken çalışmalı. Müşteri
# koltuk sayısını/çeşidini söylediyse ("ikili koltuk", "köşe koltuk") kısayol
# devreye girerse yanlış ürün döner — canlı öncesi testte yakalandı:
# "ikili koltuk" ve "tekli koltuk" ÜÇLÜ koltuk döndürüyordu.
_KOLTUK_GENEL_TOKENLARI = frozenset(("koltuk", "oturma", "grubu", "grup",
                                     "takim", "takimi"))


def _en_uygun_tip(tip: str) -> tuple[str, ...] | None:
    """Müşterinin dediği tipi katalog token'larına çevir; tanımadıysa None."""
    d = _duz(tip)
    if any(k in d for k in _CEKYAT_KELIMELERI):
        return EN_UYGUN_TIPLERI["cekyat"]
    anlamli = set(_tip_tokenlari(tip))
    if ("koltuk" in d or "oturma" in d) and anlamli <= _KOLTUK_GENEL_TOKENLARI:
        return EN_UYGUN_TIPLERI["koltuk"]
    # Bilinen kısayol yoksa serbest tarifle ara (görselden gelen "şifonyer",
    # "tv ünitesi", "yemek masası" gibi tipler buraya düşer).
    return tuple(_tip_tokenlari(tip)) or None


def en_uygun(tip: str, limit: int = 3) -> list[dict]:
    """Bir ürün tipinin EN UYGUN FİYATLI ilk `limit` seçeneği.

    Fiyatı 0/boş olanlar elenir, aynı model bir kez görünür (en ucuz SKU'su),
    sonuç ucuzdan pahalıya sıralıdır. Kayıt biçimi urun_ara ile aynıdır ki
    model fiyatı yine hazır fiyat_cumlesi'nden kopyalasın.

    pazarlik_notu BİLEREK yok: bu bir ÇOKLU listedir, pazarlık hangi ürün
    üzerine olacağı belirsiz kalır (kombinasyonlari_listele ile aynı ilke).
    Müşteri birini seçince model parca_ara'yı çağırır, merdiven orada gelir.
    """
    tokenlar = _en_uygun_tip(tip)
    if not tokenlar:
        return []
    # Bahçe ürünleri normalde elenir (ucuz oldukları için salon listesinin
    # başına geçiyorlardı), AMA müşteri/görsel açıkça bahçe diyorsa elenmemeli.
    haric = () if "bahce" in _duz(tip) else _EN_UYGUN_HARIC
    # Parça/aksesuar kayıtları elenir — AMA müşteri açıkça onu istediyse
    # ("dolap içi raf", "başlık minderi") elenmemeli.
    istenen = set(_tip_tokenlari(tip))
    haric = tuple(haric) + tuple(p for p in _PARCA_KELIMELERI
                                 if p not in istenen)
    session = SessionLocal()
    try:
        stmt = select(Urun).where(Urun.son_perakende_fiyat > 0)  # 0 TL/NULL elenir
        for t in tokenlar:   # daraltma SQL'de — Türkçe karakter sorun değil
            stmt = stmt.where(_ad_gibi(Urun.urun_adi_tam, t))
        # sku ikincil ölçüt: aynı fiyatlı ürünlerde sıra aksi halde BELİRSİZ
        # kalıyor ve aynı sorgu farklı SKU döndürebiliyordu (fiyat/ad aynı ama
        # [gorsel:SKU] ve pazarlık o SKU'ya bağlı). Sonuç artık tekrarlanabilir.
        rows = session.scalars(
            stmt.order_by(Urun.son_perakende_fiyat, Urun.sku)).all()
        gorulen: set[str] = set()
        sonuc: list[dict] = []
        for u in rows:
            ad = _duz(u.urun_adi_tam)
            if (ad in gorulen or not all(t in ad for t in tokenlar)
                    or any(h in ad for h in haric)):
                continue
            gorulen.add(ad)
            paket = fiyat_paketi(u.son_liste_fiyat, u.son_perakende_fiyat,
                                 u.son_toptan_fiyat)
            paket.pop("_merdiven", None)      # ÇOKLU liste: pazarlık yok (aşağı bak)
            sonuc.append({
                "sku": u.sku,
                "ad": u.urun_adi_tam,
                "para_birimi": "TL",
                **paket,
            })
            if len(sonuc) >= limit:
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
        # Başlık: koleksiyon adı + (seçenek varsa) NUMARALI seçenek satırı —
        # İsmail isteği 2026-09-17. Numara, seçenek listesindekiyle AYNI sırada
        # olmak zorunda; bu yüzden aynı kaynaktan (kombinasyon_listele) sayılır.
        kardesler = (kombinasyon_listele(session, kombi.koleksiyon_id)
                     if kombi.koleksiyon_id else [])
        no = next((i for i, k in enumerate(kardesler, 1) if k.id == kombi.id), None)
        tam_ad = koleksiyon_tam_ad(koleksiyon.ad if koleksiyon else "",
                                   kategori.ad if kategori else None)
        # Başlıkta seçenek NUMARASI yazılmaz (İsmail 2026-09-18): numara yalnız
        # seçim listesinde işe yarar, fiyat cevabında gereksiz duruyordu.
        if tam_ad:
            baslik = f"{tam_ad}\n{kombi.ad}" if kombi.ad else tam_ad
        else:
            baslik = kombi.ad or ""
        # İÇİNDEKİLER (İsmail isteği 2026-09-18): seçenek adı ("3 Kapaklı, 100
        # Karyola, Çalışma Masası") tek satırda okununca karışıyor; müşteri
        # takımda TAM olarak ne olduğunu görsün. Fiyat satırlarından ÖNCE,
        # başlığın hemen altında madde madde yazılır.
        icerik = "\n".join(
            f"• {ku.urun.urun_adi_tam}" + (f" ×{ku.miktar}" if ku.miktar > 1 else "")
            for ku in kombi.urunler if ku.urun is not None
        )
        # baslik = yalnız AD satırları (indirim mesajı gibi kısa cevaplarda
        # içindekileri tekrarlamayalım); tam blok fiyat_cumlesi'nde kurulur.
        tam_baslik = f"{baslik}\n\n{icerik}" if (baslik and icerik) else (baslik or icerik)
        ozet = _toplam_ozet(kombi, pazarlik=True)
        if ozet.get("fiyat_cumlesi") and tam_baslik:
            # Ad, içindekiler ve fiyat TEK blok: model bunları ayrı yazarken
            # eşleştirmeyi kaçırabiliyor (canlıda fiyat başka ürünün adıyla
            # gitti). Boş satır, fiyatı içindekilerden görsel olarak ayırır.
            ozet["fiyat_cumlesi"] = f"{tam_baslik}\n\n{ozet['fiyat_cumlesi']}"
        return {
            "id": kombi.id,
            "ad": kombi.ad,
            "no": no,
            "baslik": baslik,              # yalnız ad satırları
            "icerik_metni": icerik,        # madde madde parçalar
            # kategori adı: menü detay başlığı "BEND Oturma Grubu için ..."
            # (wa/ig_presenter.kombinasyon_detay_mesaji) için gerekli.
            # video_var: koleksiyonun YouTube tanıtım videosu var mı. Yalnız
            # VAR/YOK gider, adres DEĞİL — linki router çözer (ajan.py'deki
            # medya notu [video:kol:<id>] işaretini bu id ile kurdurur).
            "koleksiyon": {"id": koleksiyon.id, "ad": koleksiyon.ad,
                           "kategori": kategori.ad if kategori else None,
                           "video_var": bool(koleksiyon.video_url)}
                          if koleksiyon else None,
            # pazarlik=True: fiyat_detay tekil bağlamdır — pazarlık merdiveni
            # yalnız burada gelir (listede N ayrı merdiven modeli karıştırırdı).
            **ozet,
            "para_birimi": "TL",
            "urunler": urunler,
        }
    finally:
        session.close()
