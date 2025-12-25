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
    list_display = ['id', 'session_id', 'user_info', 'user_message_short', 'bot_response_short', 'confidence_score', 'response_time', 'timestamp']
    list_filter = ['timestamp', 'confidence_score', 'intent', 'method']
    search_fields = ['session_id', 'user_message', 'bot_response', 'mssv', 'user__faculty_code']
    readonly_fields = ['timestamp', 'session_id', 'user', 'mssv']
    list_per_page = 50
    ordering = ['-timestamp']
    
    fieldsets = (
        ('Thông tin phiên', {
            'fields': ('session_id', 'session_title', 'user', 'mssv', 'timestamp')
        }),
        ('Nội dung chat', {
            'fields': ('user_message', 'bot_response')
        }),
        ('Thông tin kỹ thuật', {
            'fields': ('confidence_score', 'response_time', 'intent', 'method', 'strategy', 'entities', 'user_ip'),
            'classes': ('collapse',)
        }),
    )
    
    def user_info(self, obj):
        if obj.user:
            return f"GV: {obj.user.faculty_code}"
        elif obj.mssv:
            return f"SV: {obj.mssv}"
        else:
            return "Anonymous"
    user_info.short_description = "Người dùng"
    
    def user_message_short(self, obj):
        return obj.user_message[:50] + "..." if len(obj.user_message) > 50 else obj.user_message
    user_message_short.short_description = "Câu hỏi"
    
    def bot_response_short(self, obj):
        return obj.bot_response[:50] + "..." if len(obj.bot_response) > 50 else obj.bot_response
    bot_response_short.short_description = "Câu trả lời"

@admin.register(UserFeedback)
class UserFeedbackAdmin(admin.ModelAdmin):
    list_display = ['feedback_type', 'chat_history', 'created_at']
    list_filter = ['feedback_type', 'created_at']