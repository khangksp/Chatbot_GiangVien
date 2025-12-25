from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

def home_view(request):
    """Trang chủ API với personalization info"""
    return JsonResponse({
        'message': 'Chào mừng đến với Chatbot cá nhân hóa của Đại học Bình Dương!',
        'version': '2.0.0',  # ✅ NÂNG CẤP VERSION
        'features': [
            'Natural Language Processing',
            'Speech-to-Text Integration', 
            'Faculty Personalization',  # ✅ THÊM
            'Department-specific Responses',  # ✅ THÊM
            'Role-based Chatbot Prompts'  # ✅ THÊM
        ],
        'endpoints': {
            'admin': '/admin/',
            'health': '/api/health/',
            'chat': '/api/chat/',
            'knowledge': '/api/knowledge/',
            'authentication': '/api/auth/',
            'personalized_chat': '/api/personalized-context/',  # ✅ THÊM
            'api_docs': '/api/',
        },
        'personalization': {
            'enabled': True,
            'supported_departments': [
                'Công nghệ thông tin', 'Dược', 'Điện tử viễn thông',
                'Cơ khí', 'Y khoa', 'Kinh tế', 'Luật'
            ],
            'supported_positions': [
                'Giảng viên', 'Trợ giảng', 'Trưởng khoa', 
                'Phó trưởng khoa', 'Trưởng bộ môn', 'Cán bộ'
            ]
        },
        'status': 'running'
    })

urlpatterns = [
    path('', home_view, name='home'),
    path('admin/', admin.site.urls),
    path('api/', include('chat.urls')),
    path('api/knowledge/', include('knowledge.urls')),
    path('api/auth/', include('authentication.urls')),
    path('api/qa/', include('qa_management.urls')),
]

admin.site.site_header = "BDU Chatbot Administration"
admin.site.site_title = "BDU Admin"
admin.site.index_title = "BDU Chatbot Management System"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

