"""
URLs for QA Management
All main functionality is handled through Django Admin custom views.
"""

from django.urls import path
from . import views

app_name = 'qa_management'

urlpatterns = [
    # Health check endpoints
    path('api/status/', views.qa_status_api, name='qa_status_api'),
    path('api/health/', views.health_check, name='qa_health_check'),
]