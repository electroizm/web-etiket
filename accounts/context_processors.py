from django.conf import settings


def supabase_settings(request):
    """Supabase URL ve anon key'i template'lere expose eder.
    login.html içindeki JS bunları kullanarak supabase-js'yi initialize eder."""
    return {
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }
