from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class QAEntry(models.Model):
    """
    Model for Q&A entries that sync with Google Drive CSV
    FIXED VERSION - Allows duplicate STT
    """
    stt = models.CharField(
        max_length=50, 
        unique=False,  # ✅ FIXED: Allow duplicate STT
        verbose_name="STT",
        help_text="Số thứ tự/ID (ví dụ: TB_1252) - Có thể trùng lặp",
        validators=[
            RegexValidator(
                regex=r'^[A-Za-z0-9_-]+$',
                message='STT chỉ được chứa chữ cái, số, dấu _ và -'
            )
        ]
    )
    
    question = models.TextField(
        verbose_name="Câu hỏi",
        help_text="Câu hỏi từ giảng viên"
    )
    
    answer = models.TextField(
        verbose_name="Câu trả lời",
        help_text="Câu trả lời chi tiết"
    )
    
    category = models.CharField(
        max_length=100,
        default="Giảng viên",
        verbose_name="Danh mục",
        help_text="Danh mục phân loại (mặc định: Giảng viên)"
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name="Kích hoạt",
        help_text="Chỉ các Q&A được kích hoạt mới hiển thị trong chatbot"
    )
    
    # Metadata fields
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Ngày tạo"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Ngày cập nhật"
    )
    
    last_synced_to_drive = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Lần cuối sync lên Drive"
    )
    
    sync_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Chờ sync'),
            ('synced', 'Đã sync'),
            ('error', 'Lỗi sync'),
        ],
        default='pending',
        verbose_name="Trạng thái sync"
    )
    
    notes = models.TextField(
        blank=True,
        verbose_name="Ghi chú",
        help_text="Ghi chú nội bộ (không hiển thị trong chatbot)"
    )
    
    class Meta:
        ordering = ['stt']
        verbose_name = "Q&A Entry"
        verbose_name_plural = "Q&A Entries"
        db_table = 'qa_management_entry'
        # ✅ REMOVED: unique_together constraint to allow duplicate STT
    
    def __str__(self):
        return f"{self.stt}: {self.question[:50]}..."
    
    def save(self, *args, **kwargs):
        """Override save to handle auto-sync"""
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Mark as pending sync if changed (but not for new entries during bulk operations)
        if not is_new and not getattr(self, '_bulk_operation', False):
            self.sync_status = 'pending'
            super().save(update_fields=['sync_status'])
        
        logger.info(f"✅ QA Entry saved: {self.stt}")
    
    @property
    def is_synced(self):
        """Check if entry is synced with Drive"""
        return self.sync_status == 'synced' and self.last_synced_to_drive is not None
    
    @property
    def sync_age_minutes(self):
        """Get minutes since last sync"""
        if not self.last_synced_to_drive:
            return None
        return (timezone.now() - self.last_synced_to_drive).total_seconds() / 60
    
    def mark_synced(self):
        """Mark entry as successfully synced"""
        self.sync_status = 'synced'
        self.last_synced_to_drive = timezone.now()
        self.save(update_fields=['sync_status', 'last_synced_to_drive'])
    
    def mark_sync_error(self):
        """Mark entry as sync error"""
        self.sync_status = 'error'
        self.save(update_fields=['sync_status'])


class QASyncLog(models.Model):
    """
    Log for tracking sync operations with Google Drive
    """
    OPERATION_CHOICES = [
        ('import_from_drive', 'Import từ Drive'),
        ('export_to_drive', 'Export lên Drive'),
        ('sync_single', 'Sync đơn lẻ'),
        ('bulk_sync', 'Sync hàng loạt'),
    ]
    
    STATUS_CHOICES = [
        ('success', 'Thành công'),
        ('partial', 'Một phần'),
        ('failed', 'Thất bại'),
    ]
    
    operation = models.CharField(
        max_length=20,
        choices=OPERATION_CHOICES,
        verbose_name="Loại thao tác"
    )
    
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        verbose_name="Trạng thái"
    )
    
    started_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Bắt đầu"
    )
    
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Hoàn thành"
    )
    
    entries_processed = models.PositiveIntegerField(
        default=0,
        verbose_name="Số Q&A đã xử lý"
    )
    
    entries_success = models.PositiveIntegerField(
        default=0,
        verbose_name="Số Q&A thành công"
    )
    
    entries_failed = models.PositiveIntegerField(
        default=0,
        verbose_name="Số Q&A thất bại"
    )
    
    error_message = models.TextField(
        blank=True,
        verbose_name="Lỗi chi tiết"
    )
    
    details = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Chi tiết thao tác"
    )
    
    class Meta:
        ordering = ['-started_at']
        verbose_name = "Sync Log"
        verbose_name_plural = "Sync Logs"
    
    def __str__(self):
        return f"{self.get_operation_display()} - {self.get_status_display()} ({self.started_at})"
    
    @property
    def duration_seconds(self):
        """Calculate operation duration"""
        if not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds()
    
    @property
    def success_rate(self):
        """Calculate success rate"""
        if self.entries_processed == 0:
            return 0
        return (self.entries_success / self.entries_processed) * 100