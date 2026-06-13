# web-etiket

Doğtaş mobilya ürünlerinin fiyatlarını her gün otomatik tarayan ve fiyatı
değişen ürünler için mağaza içi **etiket PDF'leri** üreten Django uygulaması.

**Stack:** Django 5 (web katmanı) · SQLAlchemy 2 (DB erişimi) · Supabase
(Auth + Postgres) · ReportLab (PDF) · aiohttp + BeautifulSoup (scraper) ·
Render.com (hosting)

> Not: Django ORM kullanılmaz — tüm veritabanı erişimi SQLAlchemy iledir,
> şema `catalog/migrations/*.sql` dosyalarındaki ham SQL ile yönetilir
> (Supabase SQL Editor'den elle uygulanır).

---

## Ne yapar?

1. **Fiyat takibi:** `scrape_dogtas` komutu dogtas.com'un tüm kataloğunu tarar.
   Yeni ürünleri kategori/koleksiyon hiyerarşisiyle birlikte ekler; mevcut
   ürünlerde perakende fiyat ≥70 TL değiştiyse günceller ve tarihçeye yazar.
   Lokal Windows makinesinde Görev Zamanlayıcı ile her gün 07:07'de çalışır
   (`run_scraper.bat`, log: `D:\GoogleDrive\~ DogtasCom.txt`).
2. **Bildirim:** Tarama fiyat değişikliği bulduğunda özeti veritabanına bırakır;
   `bildirim_gonder` komutu (Görev Zamanlayıcı, her gün 10:07) bunu e-posta ile
   yollar. Tarama hata ile durursa ayrı bir hata e-postası gönderilir. Güncelleme
   yoksa hiç e-posta gitmez.
3. **Etiket üretimi:** Web arayüzünden koleksiyonlara takım atanır, etikete
   girecek ürünler/kombinasyonlar işaretlenir (max 15 satır); "Etiket Yazdır"
   ekranı mağaza (EXC/ŞUBE) + (son yazdırma / tarih) filtresiyle fiyatı değişen
   koleksiyonları listeler ve tek PDF'te (koleksiyon başına bir A4 landscape
   sayfa) basar. Yazdırılan koleksiyonlara mağaza bazlı "son yazdırma" damgası
   vurulur; tarih boş bırakılırsa varsayılan filtre "son basımdan beri değişenler".

## Hızlı Başlangıç

```powershell
cd C:\Users\GUNES\git\web-etiket
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # değerleri doldur (Supabase + DATABASE_URL)
python manage.py runserver
```

→ <http://127.0.0.1:8000/>

Scraper testi: `python manage.py scrape_dogtas --max-pages 1 --dry-run`
Bildirim testi: `python manage.py bildirim_gonder` (bekleyen özet varsa e-posta yollar)

## Auth Mimarisi

Giriş/kayıt tarayıcıda Supabase JS SDK ile yapılır; Django şifre görmez.
Supabase'in verdiği JWT, `/accounts/api/session/sync/` endpoint'inde PyJWT ile
doğrulanıp Django session'a çevrilir. `SupabaseAuthMiddleware` her istekte
session'dan `request.supabase_user`'ı kurar; korumalı view'lar
`@login_required_supabase` (sayfa) / `@login_required_supabase_api` (JSON) ile
gate'lenir.

## Klasör Yapısı

```
web-etiket/
├── etiket_project/        # settings, urls, wsgi
├── accounts/              # Supabase auth köprüsü + profil
├── dashboard/             # tüm ekranlar (views.py) + template'ler
├── catalog/
│   ├── sa_models/         # SQLAlchemy modelleri (kategori, urun, kombinasyon, ayar)
│   ├── services/          # scraper, etiket_pdf, kombinasyon, oto_kombinasyon, ayarlar, bildirim
│   ├── migrations/        # ham SQL migration'lar 0001-0013 (Supabase'e elle uygulanır)
│   └── management/commands/  # scrape_dogtas, bildirim_gonder, db_check
├── static/  templates/    # CSS/JS, base template
├── run_scraper.bat        # Görev Zamanlayıcı: tarama (her gün 07:07)
├── run_bildirim.bat       # Görev Zamanlayıcı: e-posta bildirimi (her gün 10:07)
├── render.yaml  build.sh  # Render.com deploy (IaC)
└── requirements.txt
```

## Zamanlanmış Görevler (lokal Windows)

Web uygulamasından bağımsız, lokal makinede Görev Zamanlayıcı ile çalışır.
Her ikisinde de "kaçırılan başlangıcı telafi et" kapalıdır — makine o saatte
açık değilse o gün çalışmazlar.

| Görev | Saat | Script |
|---|---|---|
| Dogtas Scraper | 07:07 | `run_scraper.bat` → `manage.py scrape_dogtas` |
| web-etiket Eposta Bildirimi | 10:07 | `run_bildirim.bat` → `manage.py bildirim_gonder` |

E-posta `.env`'de yapılandırılır: `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
(Gmail uygulama şifresi), `BILDIRIM_EPOSTA_ALICILAR`, `HATA_EPOSTA_ALICILAR`.
Boşsa bildirim sessizce devre dışıdır.

## Deployment (Render.com)

- `main`'e push → otomatik deploy (Blueprint, `render.yaml`).
- Canlı: <https://etiket.gunesler.info> (free plan; deploy sırasında kısa
  kesinti normaldir).
- Start: `gunicorn etiket_project.wsgi:application --timeout 120`
  (uzun toplu PDF üretimleri için yüksek timeout).
- Secrets Dashboard'dan girilir: `SUPABASE_*`, `DATABASE_URL`,
  `DJANGO_CSRF_TRUSTED_ORIGINS`.

## Bilgi Tabanı

Projenin ayrıntılı dokümantasyonu (mimari, veri modeli, bileşen makaleleri,
kullanım kılavuzu) Obsidian bilgi tabanındadır:
`D:\GoogleDrive\PRG\Obsidian\Etiket\wiki\00-Index.md`
