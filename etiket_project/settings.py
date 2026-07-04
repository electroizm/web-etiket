"""
Django settings for etiket_project.
Mobil-öncelikli Etiket / PDF üretim uygulaması.
"""
from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-not-for-production')
DEBUG = os.getenv('DJANGO_DEBUG', 'True').lower() == 'true'
ALLOWED_HOSTS = [h.strip() for h in os.getenv('DJANGO_ALLOWED_HOSTS', '*').split(',')]

# Production CSRF: HTTPS origin'lerini açıkça izin ver (Render: https://*.onrender.com)
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()
]

# Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY', '')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
SUPABASE_JWT_SECRET = os.getenv('SUPABASE_JWT_SECRET', '')   # legacy HS256
SUPABASE_JWT_JWK = os.getenv('SUPABASE_JWT_JWK', '')         # yeni ES256 public JWK (JSON string)

# Fiyat API (instALL köprü sunucusu buradan fiyat sorgular) — X-API-Key header'ında bu değer beklenir.
ETIKET_API_KEY = os.getenv('ETIKET_API_KEY', '')

# ─── WhatsApp/Instagram bot (instALL köprüsü — artık bu app içinde, tek Render servisi) ──
# Webhook doğrulaması için Meta'ya verilen gizli kelime (hub.verify_token ile karşılaştırılır).
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN', '')
# WhatsApp Cloud API (graph.facebook.com) — gönderim token'ı + numara kimliği.
META_TOKEN = os.getenv('META_TOKEN', '')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID', '')
# Instagram Login API (graph.instagram.com) — ayrı token, ayrı host.
IG_TOKEN = os.getenv('IG_TOKEN', '')
IG_ID = os.getenv('IG_ID', 'me')
GRAPH_API_VERSION = os.getenv('GRAPH_API_VERSION', 'v22.0')
# Token yoksa gerçek gönderim yapılmaz, payload loglanır (geliştirme kolaylığı).
BOT_DRY_RUN = not META_TOKEN        # WhatsApp
BOT_DRY_RUN_IG = not IG_TOKEN       # Instagram

# ─── AI ajan (Faz 5) — serbest metinleri anlayan model katmanı ──
# Sağlayıcı-bağımsız: LiteLLM model adı (örn. gemini/gemini-flash-latest,
# gemini/gemini-flash-lite-latest, anthropic/claude-sonnet-5). Model değişimi = env değişimi.
AJAN_MODEL = os.getenv('AJAN_MODEL', 'gemini/gemini-flash-latest')
# Gemini anahtarı LiteLLM tarafından GEMINI_API_KEY env'inden okunur.
# Anahtar yoksa ajan devre dışı kalır ve bot eski davranışa (menü) düşer.
AJAN_AKTIF = bool(os.getenv('GEMINI_API_KEY') or os.getenv('ANTHROPIC_API_KEY')) \
    and os.getenv('AJAN_KAPALI', '') != '1'
# Konuşma bağlamı: bot_mesaj tablosundan alınacak son mesaj sayısı.
AJAN_GECMIS_LIMIT = int(os.getenv('AJAN_GECMIS_LIMIT', '10'))

# Scraper — Supabase Postgres direct connection (SQLAlchemy)
DATABASE_URL = os.getenv('DATABASE_URL', '')
SCRAPER_CONCURRENCY = int(os.getenv('SCRAPER_CONCURRENCY', '2'))
SCRAPER_RATE_DELAY_MIN = float(os.getenv('SCRAPER_RATE_DELAY_MIN', '1.0'))
SCRAPER_RATE_DELAY_MAX = float(os.getenv('SCRAPER_RATE_DELAY_MAX', '3.0'))
SCRAPER_SKIP_KATEGORILER = [
    k.strip() for k in os.getenv('SCRAPER_SKIP_KATEGORILER', 'Doğtaş Home').split(',') if k.strip()
]

# E-posta bildirimi (scraper özeti) — Gmail SMTP + uygulama şifresi.
# Üçü de doluysa aktif: EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, BILDIRIM_EPOSTA_ALICILAR
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
BILDIRIM_EPOSTA_ALICILAR = [
    a.strip() for a in os.getenv('BILDIRIM_EPOSTA_ALICILAR', '').split(',') if a.strip()
]
# Tarama HATA bildirimi alıcıları (boşsa normal alıcılara gider)
HATA_EPOSTA_ALICILAR = [
    a.strip() for a in os.getenv('HATA_EPOSTA_ALICILAR', '').split(',') if a.strip()
] or BILDIRIM_EPOSTA_ALICILAR

# Sentry — hata izleme (DSN doluysa aktif; prod'da Render env var'ı)
SENTRY_DSN = os.getenv('SENTRY_DSN', '')
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=0.0,   # sadece hatalar, performans izleme yok
    )

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'dashboard',
    'catalog',
    'bot',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'accounts.middleware.SupabaseAuthMiddleware',
]

ROOT_URLCONF = 'etiket_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.supabase_settings',
                'accounts.context_processors.app_surum',
            ],
        },
    },
]

# Telif + sürüm (alt yazı). TEK KAYNAK — context processor ile tüm template'lere geçer.
# APP_SURUM = son deploy tarihi (vYYAA.GG); HER deploy öncesi güncellenir.
# APP_TELIF = ilk yayın yılı SABİT (bu proje 2026'da başladı; takvim yılıyla değişmez).
APP_SURUM = "2607.04.5"
APP_TELIF = "© 2026 İsmail Güneş"

WSGI_APPLICATION = 'etiket_project.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'tr-tr'
TIME_ZONE = 'Europe/Istanbul'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'accounts:login'

# ─── Session: signed cookie tabanlı (DB gerektirmez) ──────────────────────────
# Render free tier'da filesystem ephemeral; sqlite session tablosu yeniden
# başlamada sıfırlanır. Cookie'de imzalı saklamak hem hızlı hem stateless.
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 gün

# ─── Production güvenlik (DEBUG=False'tayken aktif) ───────────────────────────
if not DEBUG:
    # HTTPS zorla
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    # Cookies sadece HTTPS üzerinden
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HSTS — tarayıcı 1 yıl boyunca HTTPS'i hatırlasın
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Diğer header'lar
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
