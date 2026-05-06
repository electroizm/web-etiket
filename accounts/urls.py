from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('forgot/', views.forgot_password_view, name='forgot_password'),
    path('logout/', views.logout_view, name='logout'),

    # JSON API
    path('api/session/sync/', views.api_session_sync, name='api_session_sync'),
    path('api/session/clear/', views.api_session_clear, name='api_session_clear'),
    path('api/auth/diagnose/', views.api_auth_diagnose, name='api_auth_diagnose'),
]
