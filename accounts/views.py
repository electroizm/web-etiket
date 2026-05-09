"""Accounts views.

Auth mimarisi:
  1. Kullanıcı login.html / signup.html üzerinden Supabase JS Client ile
     credentials gönderir.
  2. Supabase JS başarılı olursa access_token'ı /accounts/api/session/sync/
     endpoint'ine POST eder.
  3. Bu view JWT'yi SUPABASE_JWT_SECRET ile doğrular ve Django session'a
     {supabase_user_id, supabase_email, supabase_token} yazar.
  4. SupabaseAuthMiddleware her istekte session'ı okuyup request.supabase_user'ı
     kurar; @login_required_supabase decorator'ı korumalı view'ları gateler.
  5. Logout: Supabase JS signOut() + /accounts/api/session/clear/ ile session
     anahtarları silinir.
"""
import json
import jwt
from functools import lru_cache
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect, csrf_exempt


@lru_cache(maxsize=1)
def _jwks_client():
    """Supabase JWKS endpoint için PyJWKClient (key rotation'ı destekler)."""
    if not settings.SUPABASE_URL:
        return None
    url = settings.SUPABASE_URL.rstrip('/') + '/auth/v1/.well-known/jwks.json'
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=300)


def _decode_supabase_jwt(access_token: str) -> dict:
    """Erişim token'ını uygun şemayla doğrular.

    Token header'ındaki `alg`'a göre yol seçer:
      - HS256                 → SUPABASE_JWT_SECRET (legacy shared secret)
      - ES256 / RS256 / ...   → JWKS endpoint'inden kid match (öncelikli),
                                başarısızsa SUPABASE_JWT_JWK fallback.
    """
    header = jwt.get_unverified_header(access_token)
    alg = header.get('alg', '')
    kid = header.get('kid')

    common = {'audience': 'authenticated'}

    # ---- HS256 (legacy) ----
    if alg == 'HS256':
        if not settings.SUPABASE_JWT_SECRET:
            raise RuntimeError(
                "Token HS256 ile imzalanmış ama SUPABASE_JWT_SECRET tanımlı değil. "
                "Supabase → Project Settings → API → JWT Settings → JWT Secret değerini .env'e ekle."
            )
        return jwt.decode(access_token, settings.SUPABASE_JWT_SECRET, algorithms=['HS256'], **common)

    # ---- Asymmetric (ES256 / RS256 / EdDSA / ...) ----
    jwks_err = None
    client = _jwks_client()
    if client is not None:
        try:
            signing_key = client.get_signing_key_from_jwt(access_token).key
            return jwt.decode(access_token, signing_key, algorithms=[alg], **common)
        except Exception as e:
            jwks_err = f"{type(e).__name__}: {e}"

    # JWKS başarısız → statik JWK fallback
    if settings.SUPABASE_JWT_JWK:
        try:
            jwk_dict = json.loads(settings.SUPABASE_JWT_JWK)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"SUPABASE_JWT_JWK geçerli JSON değil: {e}")
        env_kid = jwk_dict.get('kid')
        if kid and env_kid and kid != env_kid:
            raise RuntimeError(
                f"Anahtar uyumsuz: token kid='{kid}', .env JWK kid='{env_kid}'. "
                f"JWKS endpoint başarısız ({jwks_err}). Doğru JWK'yı .env'e koy "
                f"veya SUPABASE_URL'in proje URL'i olduğundan emin ol."
            )
        key = jwt.PyJWK(jwk_dict).key
        return jwt.decode(access_token, key, algorithms=[alg], **common)

    raise RuntimeError(
        f"Token {alg} ile imzalanmış. JWKS denemesi başarısız ({jwks_err}) "
        f"ve SUPABASE_JWT_JWK tanımlı değil."
    )


def _redirect_if_authenticated(request):
    user = getattr(request, 'supabase_user', None)
    if user and user.is_authenticated:
        return redirect('dashboard:home')
    return None


def login_view(request):
    if (r := _redirect_if_authenticated(request)) is not None:
        return r
    return render(request, 'accounts/login.html', {
        'next': request.GET.get('next', ''),
    })


def signup_view(request):
    if (r := _redirect_if_authenticated(request)) is not None:
        return r
    return render(request, 'accounts/signup.html')


def forgot_password_view(request):
    return render(request, 'accounts/forgot_password.html')


def logout_view(request):
    """Hem GET hem POST destekler — link veya form'dan çağrılabilir."""
    request.session.flush()
    return redirect('accounts:login')


def profile_view(request):
    """GET /accounts/profile/ — Kullanıcı profili sayfası.

    İsim güncelleme + şifre değiştirme. Tüm Supabase Auth çağrıları
    client-side (supabase JS) yapılır; başarı sonrası syncSessionWithDjango
    ile Django session'ı yenilenir (yeni full_name JWT'den okunur).
    """
    user = getattr(request, 'supabase_user', None)
    if user is None or not user.is_authenticated:
        return redirect(f"/accounts/login/?next=/accounts/profile/")
    return render(request, 'accounts/profile.html')


# ---------------------------------------------------------------------------
# JSON API endpoints (Supabase JS ile köprü)
# ---------------------------------------------------------------------------

@csrf_protect
@require_http_methods(["POST"])
def api_session_sync(request):
    """Supabase JS başarılı login/signup sonrası bu endpoint'e access_token POST eder.
    JWT doğrulanır, kullanıcı bilgisi Django session'a yazılır."""
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Geçersiz istek formatı.'}, status=400)

    access_token = (data.get('access_token') or '').strip()
    if not access_token:
        return JsonResponse({'ok': False, 'error': 'access_token gerekli.'}, status=400)

    try:
        payload = _decode_supabase_jwt(access_token)
    except jwt.ExpiredSignatureError:
        return JsonResponse({'ok': False, 'error': 'Oturum süresi dolmuş.'}, status=401)
    except jwt.InvalidTokenError as e:
        # Hata ayıklama için header bilgisini de döndür
        try:
            header = jwt.get_unverified_header(access_token)
        except Exception:
            header = {}
        return JsonResponse({
            'ok': False,
            'error': f'Geçersiz oturum: {e}',
            'token_alg': header.get('alg'),
            'token_kid': header.get('kid'),
        }, status=401)
    except RuntimeError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

    user_id = payload.get('sub')
    email = payload.get('email', '')
    if not user_id:
        return JsonResponse({'ok': False, 'error': 'Token içinde kullanıcı yok.'}, status=400)

    # Supabase JWT user_metadata içindeki 'full_name' (varsa) — profil
    # sayfasında ve topbar'da gösterilir. updateUser sonrası yeni token
    # ile bu endpoint tekrar çağrılırsa session güncellenir.
    user_meta = payload.get('user_metadata') or {}
    full_name = (user_meta.get('full_name') or '').strip()

    request.session['supabase_user_id'] = user_id
    request.session['supabase_email'] = email
    request.session['supabase_token'] = access_token
    request.session['supabase_full_name'] = full_name

    return JsonResponse({
        'ok': True,
        'user': {'id': user_id, 'email': email, 'full_name': full_name},
        'redirect': '/app/',
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_session_clear(request):
    """Idempotent logout endpoint — CSRF'siz çalışır.

    Logout güvenliği açısından CSRF beklenmez (kötü niyetli site bir kullanıcıyı
    zorla logout edebilir; sonuç sadece "tekrar login ol", veri kaybı yok).
    Bu sayede eski cached client'lar veya CSRF token'ı eksik olan sayfalar
    da düzgün logout olur.
    """
    request.session.flush()
    return JsonResponse({'ok': True, 'redirect': '/accounts/login/'})


# ---------------------------------------------------------------------------
# Profile API — Supabase Admin API ile güncelleme
# ---------------------------------------------------------------------------

@csrf_protect
@require_http_methods(["POST"])
def api_profile_update_name(request):
    """POST /accounts/api/profile/update-name/  body: {"full_name": "..."}

    Admin API ile auth.users.user_metadata.full_name'i günceller. Mevcut
    metadata'nın diğer alanları korunur. Başarıdan sonra Django session'daki
    supabase_full_name de yenilenir → topbar anında doğru gözükür.
    """
    user = getattr(request, 'supabase_user', None)
    if user is None or not user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'Oturum gerekli.'}, status=401)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Geçersiz istek.'}, status=400)

    full_name = (data.get('full_name') or '').strip()
    if not full_name:
        return JsonResponse({'ok': False, 'error': 'Ad Soyad boş olamaz.'}, status=400)
    if len(full_name) > 120:
        return JsonResponse({'ok': False, 'error': 'En fazla 120 karakter olabilir.'}, status=400)

    try:
        from accounts.supabase_client import get_supabase_admin
        admin = get_supabase_admin()

        # Mevcut metadata'yı koruyarak full_name'i güncelle
        existing_meta: dict = {}
        try:
            existing_resp = admin.auth.admin.get_user_by_id(user.id)
            if existing_resp and getattr(existing_resp, 'user', None):
                existing_meta = dict(existing_resp.user.user_metadata or {})
        except Exception:
            # Mevcut metadata okunamazsa sıfırdan yaz
            existing_meta = {}

        new_meta = {**existing_meta, 'full_name': full_name}
        admin.auth.admin.update_user_by_id(
            user.id,
            {'user_metadata': new_meta},
        )
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'Güncelleme başarısız: {e}'}, status=500)

    request.session['supabase_full_name'] = full_name
    return JsonResponse({'ok': True, 'full_name': full_name})


@csrf_protect
@require_http_methods(["POST"])
def api_profile_change_password(request):
    """POST /accounts/api/profile/change-password/
    body: {"current_password": "...", "new_password": "..."}

    1) Mevcut şifre Supabase /auth/v1/token endpoint'ine istek atılarak doğrulanır.
       Yanıt 200 değilse "mevcut şifre hatalı" döner.
    2) Doğruysa Admin API ile yeni şifre yazılır.
    """
    user = getattr(request, 'supabase_user', None)
    if user is None or not user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'Oturum gerekli.'}, status=401)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Geçersiz istek.'}, status=400)

    current = data.get('current_password') or ''
    new = data.get('new_password') or ''

    if not current:
        return JsonResponse({'ok': False, 'error': 'Mevcut şifre zorunlu.'}, status=400)
    if not new:
        return JsonResponse({'ok': False, 'error': 'Yeni şifre zorunlu.'}, status=400)
    if len(new) < 8:
        return JsonResponse({'ok': False, 'error': 'Yeni şifre en az 8 karakter olmalı.'}, status=400)
    if current == new:
        return JsonResponse({'ok': False, 'error': 'Yeni şifre eskisi ile aynı olamaz.'}, status=400)
    if not user.email:
        return JsonResponse({'ok': False, 'error': 'Kullanıcı e-postası bulunamadı.'}, status=400)

    # 1) Mevcut şifreyi doğrula — direct REST ile (anon client'ın singleton state'ini bozmaz)
    import requests as _req
    try:
        verify = _req.post(
            f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={
                'apikey': settings.SUPABASE_ANON_KEY,
                'Content-Type': 'application/json',
            },
            json={'email': user.email, 'password': current},
            timeout=10,
        )
    except _req.RequestException as e:
        return JsonResponse({'ok': False, 'error': f'Bağlantı hatası: {e}'}, status=500)

    if verify.status_code != 200:
        # 400 invalid_grant veya 401 → mevcut şifre yanlış
        return JsonResponse({'ok': False, 'error': 'Mevcut şifre hatalı.'}, status=400)

    # 2) Admin API ile yeni şifreyi yaz
    try:
        from accounts.supabase_client import get_supabase_admin
        admin = get_supabase_admin()
        admin.auth.admin.update_user_by_id(user.id, {'password': new})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'Güncelleme başarısız: {e}'}, status=500)

    return JsonResponse({'ok': True})


def api_auth_diagnose(request):
    """GET /accounts/api/auth/diagnose/?token=<jwt>
    Token'ın header'ını ve env'de tanımlı doğrulama kaynaklarını listeler.
    DEBUG modda kullanılır, prod'da kapat."""
    if not settings.DEBUG:
        return JsonResponse({'ok': False, 'error': 'Sadece DEBUG modunda.'}, status=403)

    token = request.GET.get('token', '').strip()
    info = {
        'env': {
            'SUPABASE_URL': settings.SUPABASE_URL or None,
            'has_SUPABASE_ANON_KEY': bool(settings.SUPABASE_ANON_KEY),
            'has_SUPABASE_JWT_JWK': bool(settings.SUPABASE_JWT_JWK),
            'has_SUPABASE_JWT_SECRET': bool(settings.SUPABASE_JWT_SECRET),
        },
    }

    # Env JWK kid
    if settings.SUPABASE_JWT_JWK:
        try:
            info['env_jwk_kid'] = json.loads(settings.SUPABASE_JWT_JWK).get('kid')
        except Exception as e:
            info['env_jwk_error'] = str(e)

    # JWKS endpoint'inden ne dönüyor?
    try:
        client = _jwks_client()
        if client is not None:
            jwks_data = client.get_jwk_set()
            info['jwks'] = {
                'url': settings.SUPABASE_URL.rstrip('/') + '/auth/v1/.well-known/jwks.json',
                'kids': [k.key_id for k in jwks_data.keys],
            }
    except Exception as e:
        info['jwks_error'] = f"{type(e).__name__}: {e}"

    if token:
        try:
            info['token_header'] = jwt.get_unverified_header(token)
        except Exception as e:
            info['token_header_error'] = str(e)
        try:
            info['decode_attempt'] = _decode_supabase_jwt(token)
            info['decode_ok'] = True
        except Exception as e:
            info['decode_attempt_error'] = f"{type(e).__name__}: {e}"
            info['decode_ok'] = False

    return JsonResponse(info, json_dumps_params={'indent': 2})
