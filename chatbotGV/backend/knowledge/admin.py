from django.contrib import admin
from .models import KnowledgeBase, ChatHistory, UserFeedback

@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ['question_short', 'category', 'is_active', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['question', 'answer']
    list_editable = ['is_active']
    
    def question_short(self, obj):
        return obj.question[:50] + "..." if len(obj.question) > 50 else obj.question
    question_short.short_description = "Câu hỏi"

@admin.register(ChatHistory)
class ChatHistoryAdmin(admin.ModelAdmin):
    list_display = ['session_id', 'user_message_short', 'confidence_score', 'response_time', 'timestamp']
    list_filter = ['timestamp', 'confidence_score']
    search_fields = ['session_id', 'user_message', 'bot_response']
    readonly_fields = ['timestamp']
    
    def user_message_short(self, obj):
        return obj.user_message[:30] + "..." if len(obj.user_message) > 30 else obj.user_message
    user_message_short.short_description = "Tin nhắn"

@admin.register(UserFeedback)
class UserFeedbackAdmin(admin.ModelAdmin):
    list_display = ['feedback_type', 'chat_history', 'created_at']
    list_filter = ['feedback_type', 'created_at']