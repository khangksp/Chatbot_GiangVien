from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'knowledge', views.KnowledgeBaseViewSet)
router.register(r'history', views.ChatHistoryViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('upload-csv/', views.UploadCSVView.as_view(), name='upload-csv'),
]