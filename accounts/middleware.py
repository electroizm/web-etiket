"""SupabaseAuthMiddleware

Django session içinde saklanan supabase_user_id / email değerlerini her istek
başında request.supabase_user'a yerleştirir.

Session içeriği aşağıdaki anahtarları kullanır:
  - supabase_user_id  (str)  : Supabase auth kullanıcı UUID'si
  - supabase_email    (str)  : Kullanıcının e-postası
  - supabase_token    (str)  : access_token (RLS'li sorgular için forward edilebilir)
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SupabaseUser:
    id: str
    email: str
    token: str

    @property
    def is_authenticated(self) -> bool:
        return bool(self.id)


class SupabaseAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.supabase_user = self._user_from_session(request)
        return self.get_response(request)

    @staticmethod
    def _user_from_session(request) -> Optional[SupabaseUser]:
        sess = getattr(request, 'session', None)
        if not sess:
            return None
        uid = sess.get('supabase_user_id')
        if not uid:
            return None
        return SupabaseUser(
            id=uid,
            email=sess.get('supabase_email', ''),
            token=sess.get('supabase_token', ''),
        )
