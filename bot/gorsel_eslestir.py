"""Görselden ürün eşleştirme — "Lens mantığı" (metin köprüsü yöntemi).

NEDEN METİN KÖPRÜSÜ: gerçek görsel (multimodal) embedding elimizdeki
anahtarlarla YOK — Gemini'nin embedding modelleri görsel almıyor (denendi:
"The text content is empty"), OpenRouter'ın embedding ucu da metin. Bu yüzden
köprü kuruyoruz:

    ürün fotoğrafı ──(görsel model)──> yapılandırılmış TARİF ──> metin vektörü
    müşteri fotoğrafı ──(aynı model)──> aynı biçimde TARİF ──> metin vektörü
                                   └── en yakın komşu (pgvector) ──> SKU

Kazanç: eşleştirme artık ürün ADINA değil, ürünün GERÇEK FOTOĞRAFINA dayanıyor.
Renk, kumaş, ayak tipi, kolçak biçimi gibi katalog metninde HİÇ olmayan
bilgiler devreye giriyor (ölçüm: 1.764 üründen yalnız 11'inde renk geçiyor).

Sınır (dürüstlük): mobilyada benzerlik zor — müşterinin salon fotoğrafı ile
stüdyo çekimi ışık/açı olarak farklı. Bu yüzden sonuç TEK ürün olarak değil,
en yakın 3 aday olarak sunulur ve müşteriye SORULUR.
"""
from __future__ import annotations

import logging

from django.conf import settings

log = logging.getLogger("bot.gorsel_eslestir")

# Vektör boyutu — openai/text-embedding-3-small (OpenRouter üzerinden).
VEKTOR_BOYUT = 1536
EMBED_MODEL = "openai/text-embedding-3-small"

# Tarif talimatı: SABİT alan sırası şart. İki taraf (katalog fotoğrafı ve
# müşteri fotoğrafı) aynı kalıpta tarif edilmezse vektörler kıyaslanamaz.
TARIF_TALIMAT = (
    "Bu bir mobilya ürün fotoğrafı. Ürünü ARAYAN biri için tarif et. "
    "Yalnızca şu alanları, tam bu sırayla, tek satırda, aralarına ' | ' "
    "koyarak yaz — başka hiçbir şey yazma:\n"
    "tip | koltuk/kapak sayısı | ana renk | ikincil renk | döşeme veya kaplama "
    "malzemesi | ayak tipi ve rengi | kolçak/kenar biçimi | belirgin detay\n"
    "Bilinmeyen alana 'yok' yaz. Marka/model adı YAZMA (bilemezsin). "
    "Örnek: koltuk üçlü | 3 kişilik | bej | yok | kumaş | ahşap kahve | "
    "geniş yuvarlak kolçak | sırtta dikey dikiş"
)


def _tarif_gecerli_mi(tarif: str) -> bool:
    """Tarif işe yarar mı? Çoğu alanı 'yok' olan tarif eşleştirmeyi KİRLETİR.

    Canlı örnek (2026-07-28): "ARIANE Sandalye" için model
    "yok | yok | yok | yok | yok | yok | yok | yok" döndürdü — böyle bir kayıt
    katalogda dururken alakasız fotoğraflar ona yakın çıkar.
    """
    if not tarif or "|" not in tarif:
        return False
    alanlar = [a.strip().lower() for a in tarif.split("|")]
    dolu = [a for a in alanlar if a and a not in ("yok", "-", "bilinmiyor")]
    return len(dolu) >= 3


def _model_zinciri() -> list[str]:
    """Görsel alabilen zincir (ses/görsel ile aynı)."""
    return list(settings.AJAN_MEDYA_MODELLER)


def tarif_uret(gorsel_url: str = "", veri: bytes = b"", mime: str = "") -> str | None:
    """Fotoğrafı sabit kalıpta tarif et. URL ya da ham bayt kabul eder."""
    import base64

    import litellm
    litellm.suppress_debug_info = True

    if gorsel_url:
        ek = {"type": "image_url", "image_url": {"url": gorsel_url}}
    elif veri:
        b64 = base64.b64encode(veri).decode("ascii")
        ek = {"type": "image_url",
              "image_url": {"url": f"data:{mime or 'image/jpeg'};base64,{b64}"}}
    else:
        return None

    mesajlar = [{"role": "user", "content": [
        {"type": "text", "text": TARIF_TALIMAT}, ek]}]
    from bot import kota
    for model in _model_zinciri():
        if kota.kapali_mi(model):
            continue
        try:
            y = litellm.completion(model=model, messages=mesajlar,
                                   max_tokens=150, timeout=40)
            metin = (y.choices[0].message.content or "").strip()
            gecerli = _tarif_gecerli_mi(metin)
            kota.say(model, "gorsel", "basari" if gecerli else "bos")
            if gecerli:
                return metin[:400]
            if metin:   # model cevap verdi ama boş tarif — sıradakini dene
                log.info("bos tarif (%s): %s", model, metin[:80])
        except Exception as e:
            kotali = "429" in str(e) or "quota" in str(e).lower()
            kota.say(model, "gorsel", "kota" if kotali else "hata")
            if kotali:
                kota.kapat(model, e)
            log.warning("tarif üretilemedi (%s): %s", model, str(e)[:120])
    return None


def vektor(metin: str) -> list[float] | None:
    """Tarif metnini vektöre çevir (OpenRouter embedding ucu)."""
    import os

    import requests
    anahtar = os.getenv("OPENROUTER_API_KEY", "")
    if not (anahtar and (metin or "").strip()):
        return None
    try:
        r = requests.post("https://openrouter.ai/api/v1/embeddings",
                          headers={"Authorization": f"Bearer {anahtar}"},
                          json={"model": EMBED_MODEL, "input": metin[:2000]},
                          timeout=30)
        if r.status_code != 200:
            log.warning("embedding hatası %s: %s", r.status_code, r.text[:160])
            return None
        return (r.json()["data"][0]["embedding"])
    except Exception:
        log.warning("embedding istisnası", exc_info=True)
        return None


# Katalog yeterince dolmadan eşleştirme AÇILMAMALI: en yakın komşu her zaman
# bir sonuç döndürür, ama 100 ürünlük havuzda o sonuç büyük ihtimalle YANLIŞ
# üründür — müşteriye kötü aday göstermektense tip aramasına düşmek yeğdir.
# Katalog arka planda dolarken bu eşik özelliği KENDİLİĞİNDEN açar.
KAPSAM_ESIGI = 0.5
_KAPSAM: tuple[float, bool] | None = None
_KAPSAM_TTL = 300


def kapsam_yeterli_mi() -> bool:
    """İşlenmiş ürün oranı eşiği geçti mi? (5 dk önbellekli)"""
    global _KAPSAM
    import time
    simdi = time.monotonic()
    if _KAPSAM and simdi - _KAPSAM[0] < _KAPSAM_TTL:
        return _KAPSAM[1]
    yeterli = False
    try:
        from sqlalchemy import text

        from catalog.database import SessionLocal
        session = SessionLocal()
        try:
            islenmis = session.execute(text(
                "SELECT count(*) FROM urun_gorsel_vektor")).scalar() or 0
            toplam = session.execute(text(
                "SELECT count(*) FROM urunler WHERE son_perakende_fiyat > 0"
            )).scalar() or 0
        finally:
            session.close()
        yeterli = bool(toplam) and (islenmis / toplam) >= KAPSAM_ESIGI
        log.info("gorsel katalog kapsami: %s/%s -> %s",
                 islenmis, toplam, "yeterli" if yeterli else "YETERSIZ")
    except Exception:
        log.warning("kapsam olculemedi", exc_info=True)
    _KAPSAM = (simdi, yeterli)
    return yeterli


def benzerleri_bul(tarif: str, limit: int = 3) -> list[dict]:
    """Tarife en yakın ürünler (pgvector kosinüs mesafesi). Hata → boş liste."""
    if not kapsam_yeterli_mi():
        return []
    v = vektor(tarif)
    if not v:
        return []
    try:
        from sqlalchemy import text

        from catalog.database import SessionLocal
        session = SessionLocal()
        try:
            satirlar = session.execute(text("""
                SELECT g.sku, u.urun_adi_tam, g.tarif,
                       1 - (g.vektor <=> CAST(:v AS vector)) AS benzerlik
                FROM urun_gorsel_vektor g
                JOIN urunler u ON u.sku = g.sku
                WHERE u.son_perakende_fiyat > 0
                ORDER BY g.vektor <=> CAST(:v AS vector)
                LIMIT :n
            """), {"v": str(v), "n": limit}).all()
        finally:
            session.close()
        return [{"sku": r[0], "ad": r[1], "tarif": r[2],
                 "benzerlik": round(float(r[3]), 3)} for r in satirlar]
    except Exception:
        log.warning("benzerlik aramasi basarisiz", exc_info=True)
        return []


def tablo_kur() -> None:
    """urun_gorsel_vektor tablosunu (ve pgvector'ü) hazırla — tekrarlanabilir."""
    from sqlalchemy import text

    from catalog.database import SessionLocal
    session = SessionLocal()
    try:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.execute(text(f"""
            CREATE TABLE IF NOT EXISTS urun_gorsel_vektor (
                sku         varchar(50) PRIMARY KEY,
                gorsel_url  text NOT NULL,
                tarif       text NOT NULL,
                vektor      vector({VEKTOR_BOYUT}) NOT NULL,
                guncelleme  timestamptz NOT NULL DEFAULT now()
            )
        """))
        session.commit()
    finally:
        session.close()
