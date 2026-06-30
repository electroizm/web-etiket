from django.conf import settings


def supabase_settings(request):
    """Supabase URL ve anon key'i template'lere expose eder.
    login.html içindeki JS bunları kullanarak supabase-js'yi initialize eder."""
    return {
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }


def app_surum(request):
    """Telif satırı + sürümü template'lere expose eder (tek kaynak: settings).
    Footer'larda `{{ APP_TELIF }} • v{{ APP_SURUM }}` olarak gösterilir."""
    return {
        'APP_SURUM': settings.APP_SURUM,
        'APP_TELIF': settings.APP_TELIF,
    }
