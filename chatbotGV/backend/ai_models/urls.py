from django.urls import path
from . import views

app_name = 'ai_models'

urlpatterns = [
    # Public endpoints (no authentication required)
    path('health/', views.health_check, name='health_check'),
    path('speech-status/', views.speech_status, name='speech_status'),
    
    # Protected endpoints (authentication required)
    path('speech-to-text/', views.speech_to_text, name='speech_to_text'),
    
    # ✅ MỚI: Google Drive endpoints
    path('drive/refresh/', views.force_refresh_drive_data, name='force_refresh_drive'),
    path('drive/status/', views.google_drive_status, name='google_drive_status'),
]