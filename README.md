# Etiket Studio

Mobil-öncelikli, Django tabanlı Etiket / PDF üretim uygulaması.

**Stack:** Django 5 · Supabase (Auth & DB) · PyJWT · WeasyPrint · Render.com

---

## Hızlı Başlangıç

```powershell
cd C:\Users\GUNES\git\web-etiket

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

copy .env.example .env
# .env'i doldur (aşağıdaki "Supabase Setup" bölümüne bak)

python manage.py migrate
python manage.py runserver
```

→ <http://127.0.0.1:8000/>

---

## Supabase Setup

### 1) Proje oluştur

[supabase.com](https://supabase.com) → "New project" → bölge ve şifreyi seç.

### 2) Credentials'ı al

**Project Settings → API** sayfasından:

| .env değişkeni | Nereden | Public? |
|---|---|---|
| `SUPABASE_URL` | Project URL | ✓ |
| `SUPABASE_ANON_KEY` | `anon public` key | ✓ |
| `SUPABASE_SERVICE_ROLE_KEY` | `service_role` key | ✗ asla commitleme |
| `SUPABASE_JWT_SECRET` | JWT Settings → JWT Secret | ✗ asla commitleme |

### 3) Auth ayarları

**Authentication → Providers → Email** açık olsun.
**Authentication → URL Configuration → Site URL** = `http://127.0.0.1:8000` (prod'da Render URL'in).
**Redirect URLs** listesine `http://127.0.0.1:8000/accounts/login/` ve prod login URL'in ekle.

> **Geliştirme için:** "Confirm email" özelliğini kapatırsan kayıt sonrası anında giriş yapılır. Açıksa, kullanıcının e-posta onaylaması gerekir.

---

## Auth Mimarisi (uçtan uca)

```
┌─────────────┐  signInWithPassword   ┌───────────┐
│ login.html  │ ────────────────────▶ │ Supabase  │
│ (Supabase JS│ ◀──── access_token ── │   Auth    │
└─────┬───────┘                        └───────────┘
      │ POST /accounts/api/session/sync/  { access_token }
      ▼
┌─────────────────────────┐
│ Django api_session_sync │  PyJWT ile HS256 doğrula
│  → request.session      │  (SUPABASE_JWT_SECRET kullanır)
└─────────┬───────────────┘
          │
          ▼
┌──────────────────────────────┐
│ SupabaseAuthMiddleware       │  her istekte session → request.supabase_user
│ @login_required_supabase     │  korumalı view'ları gateler
└──────────────────────────────┘
```

**URL haritası:**
- `/`                       → `/app/` redirect (giriş yoksa `/accounts/login/`)
- `/accounts/login/`        → Giriş
- `/accounts/signup/`       → Kayıt
- `/accounts/forgot/`       → Şifre sıfırlama maili
- `/accounts/logout/`       → Çıkış (GET ile direkt link)
- `/accounts/api/session/sync/`  → Supabase JWT'yi Django session'a çevirir
- `/accounts/api/session/clear/` → Session'ı boşaltır
- `/app/`                   → Korumalı dashboard (ileride etiket listesi)

---

## Klasör Yapısı

```
web-etiket/
├── manage.py
├── requirements.txt        # Django, supabase-py, PyJWT, weasyprint, ...
├── .env.example
├── etiket_project/
│   ├── settings.py
│   └── urls.py
├── accounts/
│   ├── views.py            # login_view, signup_view, api_session_sync, ...
│   ├── urls.py
│   ├── middleware.py       # SupabaseAuthMiddleware
│   ├── decorators.py       # @login_required_supabase
│   ├── supabase_client.py  # backend Supabase singleton (admin & anon)
│   ├── context_processors.py
│   └── templates/accounts/
│       ├── _supabase_init.html
│       ├── login.html
│       ├── signup.html
│       └── forgot_password.html
├── dashboard/
│   ├── views.py            # @login_required_supabase home
│   ├── urls.py
│   └── templates/dashboard/home.html
├── templates/base.html
└── static/
    ├── css/login.css       # Auth sayfaları (paylaşılır)
    ├── css/dashboard.css
    └── js/
        ├── auth-common.js  # showStatus, syncSession, logout, ...
        ├── login.js
        ├── signup.js
        └── forgot_password.js
```

---

## Render.com Deployment

- Build:
  ```
  pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
  ```
- Start:
  ```
  gunicorn etiket_project.wsgi
  ```
- Env vars: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS=<render-url>`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`.

---

## Roadmap

- [x] Login + Signup + Forgot password ekranları
- [x] Supabase JWT ↔ Django session köprüsü (middleware + decorator)
- [x] Logout + dashboard scaffold
- [ ] **Adım 3:** Etiket veri modeli + Supabase tabloları (`labels`, `templates`) + RLS policy'leri
- [ ] **Adım 4:** Etiket tasarım editörü (mobil-öncelikli WYSIWYG)
- [ ] **Adım 5:** WeasyPrint ile PDF üretim endpoint'i
- [ ] **Adım 6:** Şablon kütüphanesi (barkod, QR, ürün etiketi tipleri)
