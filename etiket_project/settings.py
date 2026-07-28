"""
Django settings for etiket_project.
Mobil-Ã¶ncelikli Etiket / PDF Ã¼retim uygulamasÄ±.
"""
from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-not-for-production')
DEBUG = os.getenv('DJANGO_DEBUG', 'True').lower() == 'true'
ALLOWED_HOSTS = [h.strip() for h in os.getenv('DJANGO_ALLOWED_HOSTS', '*').split(',')]

# Production CSRF: HTTPS origin'lerini aÃ§Ä±kÃ§a izin ver (Render: https://*.onrender.com)
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()
]

# Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY', '')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
SUPABASE_JWT_SECRET = os.getenv('SUPABASE_JWT_SECRET', '')   # legacy HS256
SUPABASE_JWT_JWK = os.getenv('SUPABASE_JWT_JWK', '')         # yeni ES256 public JWK (JSON string)

# Fiyat API (instALL kÃ¶prÃ¼ sunucusu buradan fiyat sorgular) â€” X-API-Key header'Ä±nda bu deÄŸer beklenir.
ETIKET_API_KEY = os.getenv('ETIKET_API_KEY', '')

# â”€â”€â”€ WhatsApp/Instagram bot (instALL kÃ¶prÃ¼sÃ¼ â€” artÄ±k bu app iÃ§inde, tek Render servisi) â”€â”€
# Webhook doÄŸrulamasÄ± iÃ§in Meta'ya verilen gizli kelime (hub.verify_token ile karÅŸÄ±laÅŸtÄ±rÄ±lÄ±r).
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN', '')
# Webhook POST imza doÄŸrulamasÄ± (X-Hub-Signature-256) iÃ§in Meta App Secret.
# Meta for Developers â†’ App Settings â†’ Basic â†’ App Secret. BOÅSA imza doÄŸrulamasÄ±
# ATLANIR (yerel/geliÅŸtirme kolaylÄ±ÄŸÄ±); Ã¼retimde (Render) dolu olunca sahte webhook
# POST'larÄ± 403 ile reddedilir. Ä°smail Render'a girdi: 2026-07-27.
META_APP_SECRET = os.getenv('META_APP_SECRET', '')
# Instagram AYRI bir Meta uygulamasÄ±/secret'Ä± kullanabilir (graph.instagram.com,
# ayrÄ± token). Webhook tek uÃ§tan hem WA hem IG alÄ±r; IG webhook'larÄ± bu secret ile
# imzalanÄ±r. BoÅŸsa yalnÄ±z META_APP_SECRET denenir. Ä°mza kontrolÃ¼ ikisini de dener.
IG_APP_SECRET = os.getenv('IG_APP_SECRET', '')
# WhatsApp Cloud API (graph.facebook.com) â€” gÃ¶nderim token'Ä± + numara kimliÄŸi.
META_TOKEN = os.getenv('META_TOKEN', '')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID', '')
# Instagram Login API (graph.instagram.com) â€” ayrÄ± token, ayrÄ± host.
IG_TOKEN = os.getenv('IG_TOKEN', '')
IG_ID = os.getenv('IG_ID', 'me')
GRAPH_API_VERSION = os.getenv('GRAPH_API_VERSION', 'v22.0')
# Token yoksa gerÃ§ek gÃ¶nderim yapÄ±lmaz, payload loglanÄ±r (geliÅŸtirme kolaylÄ±ÄŸÄ±).
BOT_DRY_RUN = not META_TOKEN        # WhatsApp
BOT_DRY_RUN_IG = not IG_TOKEN       # Instagram

# â”€â”€â”€ AI ajan (Faz 5) â€” serbest metinleri anlayan model katmanÄ± â”€â”€
# SaÄŸlayÄ±cÄ±-baÄŸÄ±msÄ±z: LiteLLM model adlarÄ±, virgÃ¼lle ZÄ°NCÄ°R (soldan denenir;
# kota/hata â†’ sÄ±radaki). Her Gemini modelinin Ã¼cretsiz kotasÄ± AYRI sayÄ±lÄ±r.
# Zincir dÃ¼zeni (Ä°smail kararÄ± 2026-07-28): Ã–NCE Google'Ä±n ÃœCRETSÄ°Z kotalarÄ±,
# onlar bitince ÃœCRETLÄ° OpenRouter. BÃ¶ylece gÃ¼nÃ¼n bÃ¼yÃ¼k kÄ±smÄ± 0 â‚º'ye gider ve
# kota bitince bot susmaz â€” yalnÄ±z faturasÄ± OpenRouter'a geÃ§er.
#
# Ãœcretsiz katman gerÃ§eÄŸi (Google'Ä±n 429 gÃ¶vdesinden Ã¶lÃ§Ã¼ldÃ¼, 2026-07-28):
#   gemini-flash-latest gÃ¼nde YALNIZ 20 istek. 1.5-flash (eski 1500 hakkÄ±)
#   emekli oldu â€” API 404 veriyor. 2.0-flash'Ä±n Ã¼cretsiz hakkÄ± 0.
#   Kota MODEL BAÅINA ayrÄ± sayÄ±ldÄ±ÄŸÄ± iÃ§in Ã¼Ã§ Ã¼cretsiz halka arka arkaya dizildi.
#
# Yedek model YARIÅMAYLA seÃ§ildi (2026-07-28): gerÃ§ek sohbet geÃ§miÅŸi + 6
# senaryo, her senaryoda otomatik geÃ§ti/kaldÄ± Ã¶lÃ§Ã¼tÃ¼. SonuÃ§:
#   qwen/qwen3.7-flash                6/6  â† seÃ§ildi (ayrÄ±ca en ucuzu ve
#                                            GÃ–RSEL de okuyor)
#   mistralai/mistral-small-3.2-24b   3/6  mÃ¼ÅŸteriden TELEFON NUMARASI istedi
#                                          (kaldÄ±rdÄ±ÄŸÄ±mÄ±z "beni ara" akÄ±ÅŸÄ±)
#   google/gemini-2.5-flash-lite      2/6  mÃ¼ÅŸteriye Ä°Ã‡ DÃœÅÃœNCESÄ°NÄ° sÄ±zdÄ±rdÄ±
#                                          ("...tutarsÄ±zlÄ±k var, pazarlÄ±k
#                                          istenmiÅŸti ama...") + oyalama cevabÄ±
#   google/gemma-4-31b-it:free        0/6
# DERS: "tanÄ±dÄ±k/aynÄ± aile model daha iyidir" varsayÄ±mÄ± YANLIÅ Ã§Ä±ktÄ± â€” Ã¶nce
# gemini-2.5-flash-lite seÃ§ilmiÅŸti, test onu 2/6 ile eledi. Groq'ta da aynÄ±
# tuzaÄŸa dÃ¼ÅŸÃ¼lmÃ¼ÅŸtÃ¼. Model kararÄ±nÄ± YALNIZ gerÃ§ek akÄ±ÅŸ testi verir.
#
# Groq denendi ve Ã‡IKARILDI: kural takibi zayÄ±f (gerÃ§ek akÄ±ÅŸta 1/3; magaza_bilgi
# aracÄ±nÄ± Ã§aÄŸÄ±rmadan cevap uydurdu, mÃ¼ÅŸteriye "ilgili aracÄ± Ã§aÄŸÄ±rÄ±p" diye iÃ§
# terim sÄ±zdÄ±rdÄ±) ve dakikalÄ±k token sÄ±nÄ±rÄ± (12K TPM) tek mÃ¼ÅŸteri mesajÄ±nÄ± zor
# kaldÄ±rÄ±yordu. OpenRouter zaten Groq'un modellerini de tek anahtardan sunuyor.
AJAN_MODEL = os.getenv(
    'AJAN_MODEL',
    'gemini/gemini-flash-latest,'
    'gemini/gemini-flash-lite-latest,'
    'gemini/gemini-2.5-flash-lite,'
    'openrouter/qwen/qwen3.7-flash',
)
AJAN_MODELLER = [m.strip() for m in AJAN_MODEL.split(',') if m.strip()]

# GÃ¶rsel okuma (OCR) ve sesli mesaj Ã§Ã¶zÃ¼mÃ¼ AYRI zincir kullanÄ±r â€” her model
# gÃ¶rÃ¼ntÃ¼/ses ALMIYOR. AyrÄ± tutmak, sohbet zincirine ileride metin-only ucuz
# bir model konulsa bile medya iÅŸinin bozulmamasÄ±nÄ± garanti eder. Bu iÅŸ zaten
# dÃ¼ÅŸÃ¼k hacimli (gÃ¼nde birkaÃ§ Ã§aÄŸrÄ±), maliyeti ihmal edilebilir.
AJAN_MEDYA_MODEL = os.getenv(
    'AJAN_MEDYA_MODEL',
    'gemini/gemini-flash-latest,'
    'gemini/gemini-flash-lite-latest,'
    'gemini/gemini-2.5-flash-lite,'
    'openrouter/qwen/qwen3.7-flash',
)
AJAN_MEDYA_MODELLER = [m.strip() for m in AJAN_MEDYA_MODEL.split(',') if m.strip()]
# Gemini anahtarÄ± LiteLLM tarafÄ±ndan GEMINI_API_KEY env'inden okunur.
# Anahtar yoksa ajan devre dÄ±ÅŸÄ± kalÄ±r ve bot eski davranÄ±ÅŸa (menÃ¼) dÃ¼ÅŸer.
AJAN_AKTIF = bool(os.getenv('GEMINI_API_KEY') or os.getenv('OPENROUTER_API_KEY')
                  or os.getenv('ANTHROPIC_API_KEY')) \
    and os.getenv('AJAN_KAPALI', '') != '1'
# KonuÅŸma baÄŸlamÄ±: bot_mesaj tablosundan alÄ±nacak son mesaj sayÄ±sÄ±.
AJAN_GECMIS_LIMIT = int(os.getenv('AJAN_GECMIS_LIMIT', '10'))
# Patron beyaz listesi: bu gÃ¶nderen kimlikleri (WA telefon "9053...", IG IGSID)
# bota fiyat sorunca cevaba TOPTAN (bayi alÄ±ÅŸ) satÄ±rÄ± da eklenir. Toptan,
# Ä°smail'in maliyet bilgisidir â€” listede OLMAYAN hiÃ§ kimseye asla gÃ¶sterilmez
# (araÃ§ sonucuna bile girmez, model gÃ¶remez). Ä°smail kararÄ± 2026-07-11.
# VarsayÄ±lanlar: 0532 137 06 27 + 0532 133 98 26 (WA) + IG @guneslsmail (IGSID).
BOT_PATRON_KIMLIKLER = [k.strip() for k in os.getenv(
    'BOT_PATRON_KIMLIK',
    '905321370627,905321339826,1330726738631990').split(',') if k.strip()]
# Katalog pazarlÄ±k merdiveni (Ä°smail formÃ¼lÃ¼ 2026-07-12): pazarlÄ±k tabanÄ± =
# toptan Ã— MARJ (yukarÄ± 100'e yuvarlanÄ±r). Taban ile indirimli fiyat arasÄ±ndaki
# fark 6'ya bÃ¶lÃ¼nÃ¼r; teklifler indirimliâˆ’3/6 ve âˆ’5/6 (100'e yuvarlÄ±), son teklif
# tabanÄ±n kendisi. Marj deÄŸiÅŸirse env'den ayarlanÄ±r, kod deÄŸiÅŸmez.
BOT_PAZARLIK_MARJ = float(os.getenv('BOT_PAZARLIK_MARJ', '1.27'))
# Verilen teklifler bu kadar saat hatÄ±rlanÄ±r (Ä°smail kararÄ± 2026-07-12: 24).
# SÃ¼re iÃ§inde merdiven kaldÄ±ÄŸÄ± adÄ±mdan sÃ¼rer (12.100 diyen bot 13.000'e geri
# Ã‡IKMAZ); sÃ¼re dolunca aynÄ± mÃ¼ÅŸteriye pazarlÄ±k 1. adÄ±mdan yeniden baÅŸlar.
BOT_PAZARLIK_HAFIZA_SAAT = int(os.getenv('BOT_PAZARLIK_HAFIZA_SAAT', '24'))

# Scraper â€” Supabase Postgres direct connection (SQLAlchemy)
DATABASE_URL = os.getenv('DATABASE_URL', '')
SCRAPER_CONCURRENCY = int(os.getenv('SCRAPER_CONCURRENCY', '2'))
SCRAPER_RATE_DELAY_MIN = float(os.getenv('SCRAPER_RATE_DELAY_MIN', '1.0'))
SCRAPER_RATE_DELAY_MAX = float(os.getenv('SCRAPER_RATE_DELAY_MAX', '3.0'))
SCRAPER_SKIP_KATEGORILER = [
    k.strip() for k in os.getenv('SCRAPER_SKIP_KATEGORILER', 'DoÄŸtaÅŸ Home').split(',') if k.strip()
]

# E-posta bildirimi (scraper Ã¶zeti) â€” Gmail SMTP + uygulama ÅŸifresi.
# ÃœÃ§Ã¼ de doluysa aktif: EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, BILDIRIM_EPOSTA_ALICILAR
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
# Tarama HATA bildirimi alÄ±cÄ±larÄ± (boÅŸsa normal alÄ±cÄ±lara gider)
HATA_EPOSTA_ALICILAR = [
    a.strip() for a in os.getenv('HATA_EPOSTA_ALICILAR', '').split(',') if a.strip()
] or BILDIRIM_EPOSTA_ALICILAR

# Sentry â€” hata izleme (DSN doluysa aktif; prod'da Render env var'Ä±)
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

# Telif + sÃ¼rÃ¼m (alt yazÄ±). TEK KAYNAK â€” context processor ile tÃ¼m template'lere geÃ§er.
# APP_SURUM = son deploy tarihi (vYYAA.GG); HER deploy Ã¶ncesi gÃ¼ncellenir.
# APP_TELIF = ilk yayÄ±n yÄ±lÄ± SABÄ°T (bu proje 2026'da baÅŸladÄ±; takvim yÄ±lÄ±yla deÄŸiÅŸmez).
APP_SURUM = "2907.29.2"
APP_TELIF = "Â© 2026 Ä°smail GÃ¼neÅŸ"

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

# â”€â”€â”€ Session: signed cookie tabanlÄ± (DB gerektirmez) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Render free tier'da filesystem ephemeral; sqlite session tablosu yeniden
# baÅŸlamada sÄ±fÄ±rlanÄ±r. Cookie'de imzalÄ± saklamak hem hÄ±zlÄ± hem stateless.
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 gÃ¼n

# â”€â”€â”€ Production gÃ¼venlik (DEBUG=False'tayken aktif) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if not DEBUG:
    # HTTPS zorla
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    # Cookies sadece HTTPS Ã¼zerinden
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HSTS â€” tarayÄ±cÄ± 1 yÄ±l boyunca HTTPS'i hatÄ±rlasÄ±n
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # DiÄŸer header'lar
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
