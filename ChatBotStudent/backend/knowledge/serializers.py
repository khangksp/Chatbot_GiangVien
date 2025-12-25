from rest_framework import serializers
from .models import KnowledgeBase, ChatHistory, UserFeedback

class KnowledgeBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeBase
        fields = ['id', 'question', 'answer', 'category', 'is_active', 'created_at']

class ChatHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatHistory
        fields = ['id', 'session_id', 'user_message', 'bot_response', 
                 'confidence_score', 'response_time', 'timestamp']

class UserFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserFeedback
        fields = ['id', 'feedback_type', 'comment', 'created_at']
