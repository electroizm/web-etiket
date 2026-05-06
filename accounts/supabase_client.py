"""Supabase backend client (singleton).

İki client export ediyor:
  - get_supabase()        → anon client (kullanıcı işlemleri için)
  - get_supabase_admin()  → service-role client (RLS bypass, admin işlemler)
"""
from functools import lru_cache
from django.conf import settings
from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_ANON_KEY .env içinde tanımlı değil."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


@lru_cache(maxsize=1)
def get_supabase_admin() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY .env içinde tanımlı değil."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
