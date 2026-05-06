"""Auth decorators."""
from functools import wraps
from urllib.parse import urlencode
from django.shortcuts import redirect
from django.http import JsonResponse


def login_required_supabase(view_func):
    """Supabase oturumu olmayan kullanıcıyı /accounts/login/?next=... adresine yönlendirir."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = getattr(request, 'supabase_user', None)
        if user and user.is_authenticated:
            return view_func(request, *args, **kwargs)
        qs = urlencode({'next': request.get_full_path()})
        return redirect(f'/accounts/login/?{qs}')
    return _wrapped


def login_required_supabase_api(view_func):
    """API endpoint'leri için: 401 JSON döner."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = getattr(request, 'supabase_user', None)
        if user and user.is_authenticated:
            return view_func(request, *args, **kwargs)
        return JsonResponse({'ok': False, 'error': 'Yetkisiz.'}, status=401)
    return _wrapped
