"""
Doğtaş Web Scraper — Katalog tarayıcı (Django entegrasyonlu)

- "Tümü" sayfasını sayfa sayfa gez (https://www.dogtas.com/tumu-c-0?siralama=a-z&sayfa=N)
- Her sayfanın ürün URL'lerini çıkar
- Her ürün detayından: SKU, ad, kategori, koleksiyon, liste/perakende fiyat, indirim
- Yeni ürün → DB'ye ekle (Kategori + Koleksiyon otomatik)
- Mevcut ürün → fiyat güncelle (Fiyat tablosuna verification kaydı)

Anti-bot:
- Cookie warming (anasayfa → kategori → ürün)
- Rastgele User-Agent + sec-ch-ua header'ları
- Random jitter (insan davranışı)
- aiohttp.CookieJar ile sticky session
- Retry + exponential backoff

Tetikleme: `python manage.py scrape_dogtas` — bu modül doğrudan değil,
Django management command üzerinden çalıştırılır.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from django.conf import settings
from sqlalchemy import select

from catalog.database import SessionLocal
from catalog.sa_models import Fiyat, Kategori, Koleksiyon, Urun

log = logging.getLogger("catalog.scraper")


# ─── Sabitler ────────────────────────────────────────────────────────────────

BASE_URL = "https://www.dogtas.com"
KATALOG_URL = f"{BASE_URL}/tumu-c-0?siralama=a-z&sayfa={{page}}"

USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
]


def base_headers(user_agent: str, referer: str | None = None) -> dict[str, str]:
    """Modern Chrome browser fingerprint'ine yakın header set."""
    h = {
        "User-Agent": user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": '"Chromium";v="127", "Not(A:Brand";v="99", "Google Chrome";v="127"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Sec-Fetch-User": "?1",
    }
    if referer:
        h["Referer"] = referer
    return h


@dataclass
class ScrapeSonucu:
    """Tek bir scrape edilmiş ürünün sonucu."""

    url: str
    sku: str | None = None
    urun_adi_tam: str | None = None
    kategori: str | None = None
    koleksiyon: str | None = None
    liste_fiyat: int | None = None       # TL cinsinden tam sayı
    perakende_fiyat: int | None = None   # TL cinsinden tam sayı
    indirim_yuzde: int | None = None
    hata: str | None = None

    @property
    def basarili(self) -> bool:
        return self.hata is None and self.sku is not None and self.urun_adi_tam is not None


# ─── Yardımcı parse fonksiyonları ────────────────────────────────────────────


def parse_fiyat(text: str | None) -> int | None:
    """'12.500 TL' → 12500, '12.500,50 TL' → 15251 (banker's round).

    Decimal ile hassas parse edilir, ardından TL cinsinden int'e yuvarlanır.
    Geçerli aralık: 10 ≤ deger ≤ 1.000.000 TL.
    """
    if not text:
        return None
    temiz = re.sub(r"[^\d.,]", "", text)
    if not temiz:
        return None
    try:
        if "," in temiz and "." in temiz:
            if temiz.rindex(".") < temiz.rindex(","):
                temiz = temiz.replace(".", "").replace(",", ".")
            else:
                temiz = temiz.replace(",", "")
        elif "," in temiz:
            temiz = temiz.replace(",", ".")
        elif "." in temiz:
            parts = temiz.split(".")
            if len(parts[-1]) != 2:
                temiz = temiz.replace(".", "")
        deger = Decimal(temiz)
        if Decimal(10) <= deger <= Decimal(1_000_000):
            return int(round(deger))   # banker's rounding (15250.50 → 15250, 15250.51 → 15251)
    except Exception:
        pass
    return None


def parse_indirim_yuzde(text: str | None) -> int | None:
    """'-15%' → 15"""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s*%", text)
    if m:
        v = int(m.group(1))
        if 0 < v <= 99:
            return v
    return None


_SKU_URL_PATTERN = re.compile(r"-(\d{6,})/?$")


def sku_from_url(url: str) -> str | None:
    """URL'in sonundaki uzun rakam dizisini SKU olarak çıkar.
    Örn: '/bend-6-kapakli-dolap-3200418676' → '3200418676'.
    """
    m = _SKU_URL_PATTERN.search(url.split("?")[0])
    return m.group(1) if m else None


# ─── Scraper sınıfı ──────────────────────────────────────────────────────────


class DogtasScraper:
    """
    Doğtaş.com kataloğunu tarar:
      tarama_yap(): "Tümü" sayfasını sayfa sayfa gezer, tüm ürünleri keşfeder.
    """

    def __init__(
        self,
        *,
        concurrency: int = 2,
        delay_min: float = 1.0,
        delay_max: float = 3.0,
        timeout: int = 30,
        retry: int = 3,
    ):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.retry = retry
        # Oturum boyunca tek UA — daha doğal (gerçek browser UA değiştirmez).
        self.user_agent = random.choice(USER_AGENTS)
        # Doğal navigasyon için "son ziyaret edilen URL" (Referer)
        self._son_url: str = BASE_URL

    async def _wait_jitter(self) -> None:
        await asyncio.sleep(random.uniform(self.delay_min, self.delay_max))

    async def _fetch(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> str | None:
        """Tek sayfa indir. Doğal navigasyon: Referer önceki ziyaret."""
        headers = base_headers(self.user_agent, referer=self._son_url)
        for attempt in range(1, self.retry + 1):
            try:
                async with self.semaphore, session.get(
                    url, headers=headers, timeout=self.timeout
                ) as r:
                    if r.status == 200:
                        data = await r.text()
                        # Başarılı navigasyon → Referer güncelle
                        self._son_url = url
                        return data
                    if r.status == 404:
                        return None
                    log.warning("HTTP %s — %s", r.status, url)
            except (TimeoutError, aiohttp.ClientError) as e:
                log.warning("[%s/%s] %s — %s", attempt, self.retry, type(e).__name__, url)
                await asyncio.sleep(2 ** attempt + random.random())
        return None

    # ─── Cookie warming + doğal navigasyon ──────────────────────────────────

    async def warmup(self, session: aiohttp.ClientSession) -> None:
        """
        Cloudflare'in cookie'lerini almak için doğal akış:
        Anasayfa → biraz bekle → Tümü sayfası 1
        İlk gerçek istekten önce gerçek tarayıcı gibi davran.
        """
        log.info("Warmup: anasayfa ziyareti...")
        await self._fetch(session, BASE_URL)
        await self._wait_jitter()
        log.info("Warmup: katalog girişi...")
        await self._fetch(session, BASE_URL + "/tumu-c-0")
        await self._wait_jitter()

    # ─── "Tümü" sayfasından ürün linkleri ───────────────────────────────────

    @staticmethod
    def _extract_urun_links(soup: BeautifulSoup) -> list[str]:
        """
        Katalog sayfasındaki ürün detay URL'lerini çıkar.

        Doğtaş katalog HTML yapısı:
            .card-product → .image-wrapper → .image → .carousel
                → .carousel-inner → .carousel-item.active → <a>

        Sadece her ürünün ANA görsel linkini istiyoruz (carousel'de aktif slide).
        """
        if not soup:
            return []

        seen: set[str] = set()
        urls: list[str] = []

        for el in soup.select(".card-product .carousel-item.active a"):
            href = (el.get("href") or "").strip()
            if not href or href.startswith("javascript:") or href.startswith("#"):
                continue
            if "#" in href:
                href = href.split("#")[0]
            full = urljoin(BASE_URL, href)
            if "dogtas.com" not in full or full in seen:
                continue
            seen.add(full)
            urls.append(full)

        return urls

    @staticmethod
    def _son_sayfa_mi(soup: BeautifulSoup | None) -> bool:
        """'Ürün bulunamadı' uyarısı varsa son sayfaya geldik."""
        if not soup:
            return True
        warn = soup.find(class_="alert alert-warning")
        return bool(warn and "Ürün bulunamadı" in warn.get_text())

    async def listele_sayfa(
        self, session: aiohttp.ClientSession, page: int
    ) -> list[str] | None:
        """Tek bir kategori sayfasının ürün URL'lerini al. Son sayfaysa None döner."""
        page_url = KATALOG_URL.format(page=page)
        html = await self._fetch(session, page_url)
        if not html:
            return None
        soup = BeautifulSoup(html, "lxml")
        if self._son_sayfa_mi(soup):
            return None
        return self._extract_urun_links(soup)

    # ─── Detail parse ───────────────────────────────────────────────────────

    @staticmethod
    def _jsonld_data(soup: BeautifulSoup) -> dict | None:
        """Schema.org Product JSON-LD'sini bul."""
        for tag in soup.find_all("script", type="application/ld+json"):
            if not tag.string:
                continue
            try:
                data = json.loads(tag.string)
            except (json.JSONDecodeError, TypeError):
                continue
            adaylar = data if isinstance(data, list) else [data]
            for item in adaylar:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return item
        return None

    @classmethod
    def _jsonld_price(cls, soup: BeautifulSoup) -> int | None:
        """JSON-LD'deki price → TL int (banker's round)."""
        item = cls._jsonld_data(soup)
        if not item:
            return None
        offers = item.get("offers", {})
        if isinstance(offers, list) and offers:
            offers = offers[0]
        if isinstance(offers, dict):
            try:
                return int(round(Decimal(str(offers.get("price")))))
            except Exception:
                return None
        return None

    @staticmethod
    def _kategori_breadcrumb(soup: BeautifulSoup) -> str | None:
        """Breadcrumb'tan ana kategoriyi al (ilk gerçek seviye)."""
        bc = soup.find("ol", class_="breadcrumb") or soup.find(class_="breadcrumb")
        if not bc:
            return None
        items: list[str] = []
        for li in bc.find_all("li"):
            text = li.get_text(strip=True)
            if not text or text in ("Ana Sayfa", "Home"):
                continue
            items.append(text)
        return items[0] if items else None

    @staticmethod
    def _h1_koleksiyon_ad(soup: BeautifulSoup) -> tuple[str | None, str | None]:
        """
        <h1 class="title"><span>BEND</span> 6 Kapaklı Dolap</h1>
            → ('BEND', 'BEND 6 Kapaklı Dolap')
        """
        h1 = soup.find("h1", class_="title") or soup.find("h1")
        if not h1:
            return None, None
        span = h1.find("span")
        koleksiyon = span.get_text(strip=True) if span else None
        raw = h1.get_text(" ", strip=True)
        urun_adi_tam = re.sub(r"\s+", " ", raw).strip() or None
        return koleksiyon, urun_adi_tam

    async def scrape_detail(
        self, session: aiohttp.ClientSession, url: str
    ) -> ScrapeSonucu:
        """Bir ürün sayfasını çek ve parse et."""
        sonuc = ScrapeSonucu(url=url)

        html = await self._fetch(session, url)
        if not html:
            sonuc.hata = "HTML çekilemedi"
            return sonuc

        soup = BeautifulSoup(html, "lxml")

        # SKU: önce HTML'den, sonra URL'den
        sku_el = soup.find(class_="sku")
        sku: str | None = None
        if sku_el:
            m = re.search(r"(\d{6,})", sku_el.get_text(" ", strip=True))
            if m:
                sku = m.group(1)
        if not sku:
            sku = sku_from_url(url)
        sonuc.sku = sku

        # Başlık + koleksiyon
        sonuc.koleksiyon, sonuc.urun_adi_tam = self._h1_koleksiyon_ad(soup)

        # Kategori (breadcrumb)
        sonuc.kategori = self._kategori_breadcrumb(soup)

        # Liste fiyat (ana göstergeli fiyat — her zaman vardır)
        liste_fiyat: int | None = None
        for sel in [
            "div.sale-price[data-total-price]",
            "div.sale-price.dgts-special-price",
            "div.sale-price.sale-variant-price",
            ".product-price-group .sale-price",
            "div.sale-price",
        ]:
            el = soup.select_one(sel)
            if el and (v := parse_fiyat(el.get_text(" ", strip=True))):
                liste_fiyat = v
                break

        # Perakende fiyat (SADECE indirim varsa sepet sonrası fiyat).
        # discount-price class'ı sadece indirimli ürünlerde var; yan ürünler hariç.
        perakende_fiyat: int | None = None
        for sel in [
            "div.new-sale-price.discount-price[data-discount-price]",
            "div.new-sale-price[data-discount-price]",
            "div.new-sale-price.discount-price",
        ]:
            el = soup.select_one(sel)
            if el and (v := parse_fiyat(el.get_text(" ", strip=True))):
                perakende_fiyat = v
                break

        # İndirim yoksa perakende = liste
        if perakende_fiyat is None:
            perakende_fiyat = liste_fiyat

        # JSON-LD fallback (DOM'dan bilinemiyorsa)
        if liste_fiyat is None:
            liste_fiyat = self._jsonld_price(soup)
            if perakende_fiyat is None:
                perakende_fiyat = liste_fiyat

        sonuc.liste_fiyat = liste_fiyat
        sonuc.perakende_fiyat = perakende_fiyat

        # İndirim yüzdesi
        if liste_fiyat and perakende_fiyat and liste_fiyat > 0:
            farkorani = (liste_fiyat - perakende_fiyat) / liste_fiyat * 100
            if 0 < farkorani < 100:
                sonuc.indirim_yuzde = int(round(farkorani))
        if sonuc.indirim_yuzde is None:
            for sel in [".discount-rate", ".badge-discount", ".discount-name"]:
                el = soup.select_one(sel)
                if el and (v := parse_indirim_yuzde(el.get_text(" ", strip=True))):
                    sonuc.indirim_yuzde = v
                    break

        return sonuc

    # ─── Tarama akışı ───────────────────────────────────────────────────────

    async def tarama_yap(
        self,
        max_pages: int | None = None,
        start_page: int = 1,
        ilerle_callback=None,
    ) -> list[ScrapeSonucu]:
        """
        Doğtaş kataloğunu sayfa sayfa gez, tüm ürünleri scrape et.

        Args:
            max_pages: ilk N sayfa (test için). None = tüm sayfalar.
            start_page: hangi sayfadan başla (kalınan yerden devam için).
            ilerle_callback: her ürün bittikten sonra çağrılır (sayfa, idx, sonuc).
        """
        sonuclar: list[ScrapeSonucu] = []
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=4)
        async with aiohttp.ClientSession(
            connector=connector,
            cookie_jar=aiohttp.CookieJar(),  # sticky cookies
        ) as session:
            await self.warmup(session)

            page = start_page
            while True:
                if max_pages and (page - start_page + 1) > max_pages:
                    log.info("Max sayfa limit: %d", max_pages)
                    break

                log.info("─── Sayfa %d ─────────────────", page)
                urls = await self.listele_sayfa(session, page)
                if urls is None:
                    log.info("Son sayfa: %d. Tarama bitti.", page - 1)
                    break
                if not urls:
                    log.warning("Sayfa %d boş ürün döndü, atlandı", page)
                    page += 1
                    continue

                log.info("Sayfa %d: %d ürün", page, len(urls))

                for idx, url in enumerate(urls, 1):
                    await self._wait_jitter()
                    try:
                        sonuc = await self.scrape_detail(session, url)
                    except Exception as e:
                        log.exception("Beklenmeyen hata %s", url)
                        sonuc = ScrapeSonucu(url=url, hata=f"{type(e).__name__}: {e}")
                    sonuclar.append(sonuc)
                    if sonuc.basarili:
                        log.info(
                            "  [%d/%d] OK %s — %s (L:%s P:%s)",
                            idx,
                            len(urls),
                            sonuc.sku,
                            (sonuc.urun_adi_tam or "")[:50],
                            sonuc.liste_fiyat,
                            sonuc.perakende_fiyat,
                        )
                    else:
                        log.warning(
                            "  [%d/%d] FAIL %s: %s",
                            idx,
                            len(urls),
                            sonuc.sku or "?",
                            sonuc.hata or "ad/sku eksik",
                        )
                    if ilerle_callback:
                        ilerle_callback(page, idx, sonuc)

                # Sayfa arası ekstra bekleme
                await self._wait_jitter()
                page += 1

        return sonuclar


# ─── DB upsert ───────────────────────────────────────────────────────────────


# Mevcut bir SKU'da fiyat güncellemesi için minimum mutlak fark (TL).
# Bu eşiğin altındaki dalgalanmalar gürültü kabul edilir; DB'ye dokunulmaz.
FIYAT_GUNCELLEME_ESIGI_TL = 70


def db_upsert(sonuclar: Iterable[ScrapeSonucu], *, dry_run: bool = False) -> dict:
    """
    Scrape sonuçlarını Supabase'e yaz.

    Yeni SKU (DB'de yok):
      - SCRAPER_SKIP_KATEGORILER'deki kategoriler atlanır
      - Aktif KategoriKurali (filtre) eşleşen ürünler atlanır
      - Kategori + Koleksiyon bul/oluştur
      - Urun ekle, koleksiyona M2M bağla
      - Aktif KategoriKurali (duplikasyon) → ek M2M bağla
      - Fiyat history'ye satır yaz

    Mevcut SKU (DB'de var):
      - perakende fiyat farkı |x| < FIYAT_GUNCELLEME_ESIGI_TL → ATLANIR (hiçbir yazım yok)
      - fark ≥ eşik → SADECE şu alanlar güncellenir:
          son_liste_fiyat, son_perakende_fiyat, url, son_guncelleme
        + Fiyat tablosuna history satırı + scrape yeni koleksiyon görüyorsa M2M ekle
        (eski M2M satırları SİLİNMEZ — kategori/koleksiyon ilişkileri donmuş kabul)
      - urun_adi_tam mevcut SKU'da değiştirilmez (manuel düzenlemeler korunur)

    Tek transaction; hata olursa ROLLBACK.
    """
    from catalog.services.kategori_kurali import (
        aktif_duplikasyon_kurallari,
        aktif_filtre_kurallari,
        duplikasyon_hedefleri,
        filtrele_mi,
    )

    skip_kategoriler = set(settings.SCRAPER_SKIP_KATEGORILER)
    rapor = {
        "yeni_urun": 0,
        "guncellenen": 0,         # mevcut SKU, fark ≥ eşik → güncellendi
        "atlanan_fark_az": 0,     # mevcut SKU, fark < eşik → atlandı
        "yeni_kategori": 0,
        "yeni_koleksiyon": 0,
        "atlanan_kategori": 0,    # skip listesindeki kategoriler (sadece yeni SKU için)
        "filtrelenen": 0,         # KategoriKurali (filtre) ile atlanan (sadece yeni SKU için)
        "duplike_edilen": 0,      # KategoriKurali (duplikasyon) ile çoğaltılan (yeni SKU)
        "yeni_koleksiyon_eklendi": 0,  # mevcut SKU'ya scrape yeni koleksiyon ekledi
        "hata": 0,
    }

    session = SessionLocal()
    try:
        # Kategori/Koleksiyon cache (sorgu sayısını azaltır)
        kat_cache: dict[str, Kategori] = {
            k.ad: k for k in session.scalars(select(Kategori)).all()
        }
        kol_cache: dict[tuple[int, str], Koleksiyon] = {
            (k.kategori_id, k.ad): k
            for k in session.scalars(select(Koleksiyon)).all()
        }

        # Aktif kuralları yükle (her ürün için tekrar sorgu atmayalım)
        filtre_kurallari = aktif_filtre_kurallari(session)
        dupli_kurallari = aktif_duplikasyon_kurallari(session)

        def _kategori_bul_olustur(ad: str) -> Kategori:
            kategori = kat_cache.get(ad)
            if kategori is None:
                kategori = Kategori(ad=ad, sira=999)
                session.add(kategori)
                session.flush()
                kat_cache[ad] = kategori
                rapor["yeni_kategori"] += 1
            return kategori

        def _koleksiyon_bul_olustur(kategori: Kategori, ad: str) -> Koleksiyon:
            key = (kategori.id, ad)
            koleksiyon = kol_cache.get(key)
            if koleksiyon is None:
                koleksiyon = Koleksiyon(kategori_id=kategori.id, ad=ad)
                session.add(koleksiyon)
                session.flush()
                kol_cache[key] = koleksiyon
                rapor["yeni_koleksiyon"] += 1
            return koleksiyon

        for s in sonuclar:
            if not s.basarili:
                rapor["hata"] += 1
                continue

            # Mevcut SKU'yu önce ara — varsa filtre/skip kuralları uygulanmaz
            urun = session.scalar(select(Urun).where(Urun.sku == s.sku))

            # ─── Mevcut SKU: sadece fiyat eşiğine göre değerlendir ─────────
            if urun is not None:
                # Mutlak perakende fiyat farkı
                eski_perakende = urun.son_perakende_fiyat or 0
                yeni_perakende = s.perakende_fiyat or 0
                fark = abs(yeni_perakende - eski_perakende)

                if fark < FIYAT_GUNCELLEME_ESIGI_TL:
                    rapor["atlanan_fark_az"] += 1
                    continue

                # Eşik aşıldı → sadece izin verilen alanları güncelle
                urun.son_liste_fiyat = s.liste_fiyat
                urun.son_perakende_fiyat = s.perakende_fiyat
                if s.url and urun.url != s.url:
                    urun.url = s.url
                # son_guncelleme: şu anki zamana çek (server_default sadece insert'te çalışır)
                urun.son_guncelleme = datetime.now(timezone.utc)

                # Fiyat history satırı (gerçek değişim için kayıt)
                session.add(
                    Fiyat(
                        urun_id=urun.id,
                        liste_fiyat=s.liste_fiyat,
                        perakende_fiyat=s.perakende_fiyat,
                        kaynak="dogtas_com",
                    )
                )

                # Scrape sırasında yeni koleksiyon görüldüyse M2M ekle (eski silinmez).
                # Kategori bilgisi yoksa M2M dokunmaz (kategori değiştirme riskine girme).
                if s.kategori and s.koleksiyon:
                    kat_ad = s.kategori.strip()
                    kol_ad = s.koleksiyon.strip() or "(adsız)"
                    # Yeni kategori/koleksiyon yaratma sadece zaten varsa kullan;
                    # mevcut SKU için hiç yoktan kategori yaratmak istemiyoruz.
                    kategori = kat_cache.get(kat_ad)
                    if kategori is not None:
                        koleksiyon = kol_cache.get((kategori.id, kol_ad))
                        if koleksiyon is not None and koleksiyon not in urun.koleksiyonlar:
                            urun.koleksiyonlar.append(koleksiyon)
                            rapor["yeni_koleksiyon_eklendi"] += 1

                rapor["guncellenen"] += 1
                continue

            # ─── Yeni SKU: tam pipeline ────────────────────────────────────
            kat_ad = (s.kategori or "Tanımsız").strip()

            # Skip listesindeki kategoriler atlanır (sadece yeni SKU için)
            if kat_ad in skip_kategoriler:
                rapor["atlanan_kategori"] += 1
                continue

            # Filtre kuralları (sadece yeni SKU için)
            if filtrele_mi(
                kategori=s.kategori or "",
                urun_adi=s.urun_adi_tam or "",
                kurallar=filtre_kurallari,
            ):
                rapor["filtrelenen"] += 1
                continue

            kategori = _kategori_bul_olustur(kat_ad)
            kol_ad = (s.koleksiyon or "(adsız)").strip() or "(adsız)"
            koleksiyon = _koleksiyon_bul_olustur(kategori, kol_ad)

            urun = Urun(
                sku=s.sku,
                urun_adi_tam=s.urun_adi_tam,
                url=s.url,
                son_liste_fiyat=s.liste_fiyat,
                son_perakende_fiyat=s.perakende_fiyat,
            )
            session.add(urun)
            session.flush()
            rapor["yeni_urun"] += 1

            # Ana koleksiyona M2M bağla
            urun.koleksiyonlar.append(koleksiyon)

            # Duplikasyon kuralları: hedef kategorilerde aynı koleksiyon
            # adı altında ek M2M bağla
            hedef_katlar = duplikasyon_hedefleri(
                kategori=s.kategori or "",
                urun_adi=s.urun_adi_tam or "",
                kurallar=dupli_kurallari,
            )
            for hedef_kat_ad in hedef_katlar:
                if hedef_kat_ad.strip().lower() == kat_ad.lower():
                    continue
                hedef_kategori = _kategori_bul_olustur(hedef_kat_ad.strip())
                hedef_koleksiyon = _koleksiyon_bul_olustur(hedef_kategori, kol_ad)
                if hedef_koleksiyon not in urun.koleksiyonlar:
                    urun.koleksiyonlar.append(hedef_koleksiyon)
                    rapor["duplike_edilen"] += 1

            # Fiyat history satırı (yeni ürün için ilk kayıt)
            session.add(
                Fiyat(
                    urun_id=urun.id,
                    liste_fiyat=s.liste_fiyat,
                    perakende_fiyat=s.perakende_fiyat,
                    kaynak="dogtas_com",
                )
            )

        if dry_run:
            log.info("[DRY-RUN] ROLLBACK")
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return rapor
