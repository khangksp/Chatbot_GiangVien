from django.urls import path
from . import views

app_name = 'chat_api'

urlpatterns = [
    # ✅ API ROOT - Shows all available endpoints
    path('', views.APIRootView.as_view(), name='api-root'),
    
    # ✅ CORE CHAT ENDPOINTS
    path('chat/', views.ChatView.as_view(), name='chat'),
    path('health/', views.HealthCheckView.as_view(), name='health-check'),
    
    # ✅ CHAT HISTORY AND SESSIONS
    path('history/student/', views.StudentChatHistoryView.as_view(), name='student_chat_history'),
    path('sessions/student/', views.StudentChatSessionsView.as_view(), name='student_chat_sessions'),
    path('history/', views.ChatHistoryView.as_view(), name='chat-history'),
    path('history/<str:session_id>/', views.ChatHistoryView.as_view(), name='chat-history-session'),
    path('feedback/', views.FeedbackView.as_view(), name='feedback'),
    
    # ✅ CHAT SESSIONS MANAGEMENT
    path('chat-sessions/', views.ChatSessionsView.as_view(), name='chat-sessions'),
    path('chat-sessions/<str:session_id>/', views.ChatSessionDetailView.as_view(), name='chat-session-detail'),
    
    # ✅ SPEECH-TO-TEXT ENDPOINTS
    path('speech-to-text/', views.SpeechToTextView.as_view(), name='speech-to-text'),
    path('speech-status/', views.SpeechStatusView.as_view(), name='speech-status'),
    
    # ✅ TEXT-TO-SPEECH ENDPOINTS
    path('text-to-speech-test/', views.TextToSpeechTestView.as_view(), name='text-to-speech-test'),
    
    # ✅ PERSONALIZATION ENDPOINTS
    path('personalized-context/', views.PersonalizedChatContextView.as_view(), name='personalized-chat-context'),
    path('system-status-personalized/', views.PersonalizedSystemStatusView.as_view(), name='system-status-personalized'),
    
    # # ✅ RETRIEVER TRAINING ENDPOINTS
    # path('train-retriever/', views.TrainRetrieverView.as_view(), name='train-retriever'),
]