# Supabase Setup

Bu klasör, Supabase projesini kurmak için gereken SQL migration'larını barındırır.

## Mimari

```
            ┌─────────────────────────────────────┐
            │  C:\Users\GUNES\git\web-etiket      │
            │  (tek proje)                         │
            │                                      │
            │  catalog/  ── scraper (CLI)          │
            │     │                                │
            │     │ SQLAlchemy + direct Postgres   │
            │     │ (postgres user → RLS BYPASS)   │
            │     ▼                                │
            │  ┌──────────────────────┐           │
            │  │ Supabase Postgres    │           │
            │  └──────────────────────┘           │
            │     ▲                                │
            │     │ supabase-py + JWT              │
            │     │ (authenticated → SELECT only)  │
            │     │                                │
            │  dashboard/, accounts/  ── web UI    │
            │  (login'li users)                    │
            └─────────────────────────────────────┘
```

Tek proje, tek venv, tek `.env`. Scraper Django management command olarak çalışır.

---

## 1) Şemayı kurmak

1. [Supabase Dashboard](https://supabase.com/dashboard) → projeni seç
2. Sol menüden **SQL Editor** → **New query**
3. [`migrations/0001_init_dogtas_schema.sql`](migrations/0001_init_dogtas_schema.sql) içeriğini yapıştır → **Run**

Doğrulama:

```sql
select tablename from pg_tables where schemaname='public' order by tablename;
```

→ 6 satır: `fiyatlar`, `kategori_kurallari`, `kategoriler`, `koleksiyonlar`, `urun_koleksiyon`, `urunler`.

---

## 2) DATABASE_URL'i .env'e koymak

Scraper Supabase'e direct Postgres connection ile yazar. **Bu hızlı yol** — REST'e göre 10–100x daha hızlı toplu insert.

### Connection string'i nereden alıyorsun

1. Supabase Dashboard → **Project Settings** (alt sol gear) → **Database**
2. **Connection string** sekmesi → **URI** seçili
3. Mode: **Session** (transaction pooler değil)
4. Aşağıdaki gibi bir URL göreceksin:

   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.pogmresaofixmdnatxzp.supabase.co:5432/postgres
   ```

5. `[YOUR-PASSWORD]` yerine **proje DB şifreni** koy. Hatırlamıyorsan aynı sayfada **Reset database password** ile yenisini oluşturabilirsin.

### `.env`'i güncelle

`C:\Users\GUNES\git\web-etiket\.env`'e şu satırı ekle (veya güncelle):

```env
DATABASE_URL=postgresql+psycopg2://postgres:DB_SIFREN@db.pogmresaofixmdnatxzp.supabase.co:5432/postgres
```

> **Önemli:** SQLAlchemy URL formatı `postgresql+psycopg2://...` ile başlar. Supabase düz `postgresql://...` veriyor — başına `+psycopg2` eklemeyi unutma. Sondaki `/postgres` veritabanı adı (kesilirse hata verir).

---

## 3) Bağımlılıkları yükle

Scraper aiohttp + lxml + SQLAlchemy + psycopg2 gerektiriyor:

```powershell
cd C:\Users\GUNES\git\web-etiket
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 4) Test çalıştırması

```powershell
# Önce küçük: 1 sayfa, dry-run (DB'ye yazmaz, raporlar)
python manage.py scrape_dogtas --max-pages 1 --dry-run

# Sonra gerçek yazım: ilk 2 sayfa
python manage.py scrape_dogtas --max-pages 2

# Tüm katalog (saatler sürebilir)
python manage.py scrape_dogtas
```

Tüm parametreler:

```powershell
python manage.py scrape_dogtas --help
```

Başarılı olursa Supabase SQL Editor'da:

```sql
select count(*) from public.urunler;
select count(*) from public.fiyatlar;
```

→ Sayılar artmış olmalı.

---

## 5) Sıradaki adım (Django web tarafı)

Veriler Supabase'de olunca:
- `dashboard/`'a yeni route → login'li kullanıcılar ürün listesini görsün
- Arama (sku/ad), kategori filtresi, fiyat sıralaması
- `supabase-py` ile REST üzerinden çekilir (RLS authenticated select izni var)

Bu adıma geçmeye hazır olunca söyle.

---

## RLS notları (gelecek için)

Şu an: tüm authenticated kullanıcılar her şeyi okuyabilir. Yazma sadece direct Postgres üzerinden (scraper, postgres superuser → RLS bypass).

Eğer ileride **kullanıcı bazlı izolasyon** istersen (ör. kullanıcı sadece kendi mağazasının fiyatlarını görsün):

- `urunler` tablosuna `magaza_id` kolonu
- `auth.users`'a profile bağla
- RLS policy: `using (magaza_id in (select magaza_id from profiles where user_id = auth.uid()))`

Şimdilik gereksiz; not edildi.
