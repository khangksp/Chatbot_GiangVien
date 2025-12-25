from django.db import models
from django.utils import timezone

class KnowledgeBase(models.Model):
    question = models.TextField(verbose_name="Câu hỏi")
    answer = models.TextField(verbose_name="Câu trả lời")
    category = models.CharField(max_length=100, blank=True, null=True, verbose_name="Danh mục")
    embedding_id = models.IntegerField(null=True, blank=True, verbose_name="ID embedding")
    is_active = models.BooleanField(default=True, verbose_name="Kích hoạt")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Ngày cập nhật")
    
    class Meta:
        db_table = 'knowledge_base'
        verbose_name = "Cơ sở tri thức"
        verbose_name_plural = "Cơ sở tri thức"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Q: {self.question[:50]}..."

class ChatHistory(models.Model):
    session_id = models.CharField(max_length=100, verbose_name="ID phiên")
    user_message = models.TextField(verbose_name="Tin nhắn người dùng")
    bot_response = models.TextField(verbose_name="Phản hồi bot")
    confidence_score = models.FloatField(default=0.0, verbose_name="Điểm tin cậy")
    response_time = models.FloatField(default=0.0, verbose_name="Thời gian phản hồi (s)")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian")
    user_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP người dùng")
    intent = models.CharField(max_length=50, blank=True, null=True, help_text="Detected intent")
    method = models.CharField(max_length=50, blank=True, null=True, help_text="Response generation method")
    strategy = models.CharField(max_length=50, blank=True, null=True, help_text="Response strategy used")
    entities = models.JSONField(blank=True, null=True, help_text="Extracted entities")
    
    user = models.ForeignKey(
        'authentication.Faculty',  # Tham chiếu đến Faculty model
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='chat_history',
        verbose_name="Người dùng"
    )
    mssv = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="Mã số sinh viên",
        help_text="MSSV của sinh viên (nếu là sinh viên)"
    )
    session_title = models.CharField(
        max_length=200, 
        blank=True, 
        null=True,
        verbose_name="Tiêu đề phiên chat"
    )
    
    class Meta:
        db_table = 'chat_history'
        ordering = ['-timestamp']
        verbose_name = "Lịch sử chat"
        verbose_name_plural = "Lịch sử chat"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'session_id'], name='idx_user_session'),
            models.Index(fields=['user', '-timestamp'], name='idx_user_timestamp'),
            models.Index(fields=['session_id', '-timestamp'], name='idx_session_timestamp'),
        ]
    
    def __str__(self):
        user_info = f"{self.user.faculty_code} - " if self.user else "Anonymous - "
        return f"{user_info}Session {self.session_id} - {self.timestamp}"

    def get_session_summary(self):
        """Lấy summary của session này"""
        return {
            'session_id': self.session_id,
            'session_title': self.session_title,
            'user_message_preview': self.user_message[:50] + '...' if len(self.user_message) > 50 else self.user_message,
            'timestamp': self.timestamp,
            'user': self.user.faculty_code if self.user else 'Anonymous'
        }
class UserFeedback(models.Model):
    FEEDBACK_CHOICES = [
        ('like', 'Thích'),
        ('dislike', 'Không thích'),
        ('report', 'Báo cáo'),
    ]
    
    chat_history = models.ForeignKey(ChatHistory, on_delete=models.CASCADE, related_name='feedbacks')
    feedback_type = models.CharField(max_length=10, choices=FEEDBACK_CHOICES)
    comment = models.TextField(blank=True, null=True, verbose_name="Bình luận")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'user_feedback'
        verbose_name = "Phản hồi người dùng"
        verbose_name_plural = "Phản hồi người dùng"
    
    def __str__(self):
        return f"{self.feedback_type} - {self.created_at}"
