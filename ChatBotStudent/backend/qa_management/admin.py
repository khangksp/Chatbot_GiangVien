from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib.admin import SimpleListFilter
from django.utils import timezone
import csv
import io
import json
import time
from datetime import datetime, timedelta
import logging

from .models import QAEntry, QASyncLog
from .services import drive_service

logger = logging.getLogger(__name__)

class SyncStatusFilter(SimpleListFilter):
    """Custom filter for sync status"""
    title = 'Trạng thái Sync'
    parameter_name = 'sync_status'

    def lookups(self, request, model_admin):
        return (
            ('pending', 'Chờ sync'),
            ('synced', 'Đã sync'),
            ('error', 'Lỗi sync'),
            ('never_synced', 'Chưa sync bao giờ'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'never_synced':
            return queryset.filter(last_synced_to_drive__isnull=True)
        elif self.value():
            return queryset.filter(sync_status=self.value())
        return queryset

class RecentlyUpdatedFilter(SimpleListFilter):
    """Filter for recently updated entries"""
    title = 'Cập nhật gần đây'
    parameter_name = 'recent_updated'

    def lookups(self, request, model_admin):
        return (
            ('1hour', '1 giờ qua'),
            ('1day', '24 giờ qua'),
            ('1week', '7 ngày qua'),
        )

    def queryset(self, request, queryset):
        now = datetime.now()
        if self.value() == '1hour':
            return queryset.filter(updated_at__gte=now - timedelta(hours=1))
        elif self.value() == '1day':
            return queryset.filter(updated_at__gte=now - timedelta(days=1))
        elif self.value() == '1week':
            return queryset.filter(updated_at__gte=now - timedelta(days=7))
        return queryset

# ========== MAIN QA ENTRY ADMIN ==========

@admin.register(QAEntry)
class QAEntryAdmin(admin.ModelAdmin):
    """
    ✅ RESTRUCTURED: Enhanced admin for Q&A entries with cleaner actions
    Global tools moved to separate Tools page
    """
    
    list_display = [
        'stt', 
        'question_preview', 
        'answer_preview', 
        'category',
        'is_active', 
        'sync_status_icon',
        'last_sync_info',
        'updated_at'
    ]
    
    list_filter = [
        'is_active',
        SyncStatusFilter,
        'category',
        RecentlyUpdatedFilter,
        'created_at',
    ]
    
    search_fields = ['stt', 'question', 'answer']
    list_editable = ['is_active', 'category']
    readonly_fields = ['created_at', 'updated_at', 'last_synced_to_drive', 'sync_status']
    
    fieldsets = (
        ('Thông tin cơ bản', {
            'fields': ('stt', 'question', 'answer', 'category', 'is_active')
        }),
        ('Metadata', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Thông tin Sync', {
            'fields': ('sync_status', 'last_synced_to_drive', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    list_per_page = 50
    
    # ✅ CLEANED UP: Only entry-specific actions remain
    actions = [
        'sync_selected_entries',
        'mark_as_active',
        'mark_as_inactive', 
        'export_selected_csv',
    ]
    
    def get_urls(self):
        """✅ RESTRUCTURED: Add tools page and keep existing functionality"""
        urls = super().get_urls()
        custom_urls = [
            # ✅ NEW: Tools page for global operations
            path('tools/', self.tools_view, name='qa_tools'),
            
            # Existing individual operation endpoints
            path('import-from-drive/', self.import_from_drive_view, name='qa_import_from_drive'),
            path('export-to-drive/', self.export_to_drive_view, name='qa_export_to_drive'),
            path('sync-status/', self.sync_status_view, name='qa_sync_status'),
            path('bulk-import/', self.bulk_import_view, name='qa_bulk_import'),
        ]
        return custom_urls + urls
    
    def changelist_view(self, request, extra_context=None):
        """✅ ADD: Tools button in changelist view"""
        extra_context = extra_context or {}
        extra_context['tools_url'] = '../tools/'
        return super().changelist_view(request, extra_context)
    
    # ========== DISPLAY METHODS ==========
    
    def question_preview(self, obj):
        """Show truncated question"""
        if len(obj.question) > 80:
            return obj.question[:80] + "..."
        return obj.question
    question_preview.short_description = "Câu hỏi"
    
    def answer_preview(self, obj):
        """Show truncated answer"""
        if len(obj.answer) > 60:
            return obj.answer[:60] + "..."
        return obj.answer
    answer_preview.short_description = "Câu trả lời"
    
    def sync_status_icon(self, obj):
        """Show sync status with icon"""
        icons = {
            'pending': '⏳',
            'synced': '✅',
            'error': '❌',
        }
        icon = icons.get(obj.sync_status, '❓')
        
        color = {
            'pending': '#ffa500',
            'synced': '#28a745',
            'error': '#dc3545',
        }.get(obj.sync_status, '#6c757d')
        
        return format_html(
            '<span style="color: {}; font-size: 16px;">{}</span> {}',
            color,
            icon,
            obj.get_sync_status_display()
        )
    sync_status_icon.short_description = "Sync Status"
    
    def last_sync_info(self, obj):
        """Show last sync time"""
        if obj.last_synced_to_drive:
            age_minutes = obj.sync_age_minutes
            if age_minutes < 60:
                return f"{int(age_minutes)}m ago"
            elif age_minutes < 1440:  # 24 hours
                return f"{int(age_minutes/60)}h ago"
            else:
                return f"{int(age_minutes/1440)}d ago"
        return "Never"
    last_sync_info.short_description = "Last Sync"
    
    # ========== ENTRY-SPECIFIC ACTIONS ==========
    
    def sync_selected_entries(self, request, queryset):
        """✅ IMPROVED: Sync selected entries individually with progress tracking"""
        try:
            selected_entries = list(queryset)
            if not selected_entries:
                self.message_user(request, "❌ Không có entries nào được chọn", level=messages.WARNING)
                return
            
            success_count = 0
            error_count = 0
            
            # Add delay between syncs to avoid race conditions
            for i, entry in enumerate(selected_entries):
                try:
                    logger.info(f"🔄 Syncing entry {i+1}/{len(selected_entries)}: {entry.stt}")
                    
                    if drive_service.sync_single_entry(entry):
                        success_count += 1
                    else:
                        error_count += 1
                    
                    # Small delay to avoid overwhelming Drive API
                    if i < len(selected_entries) - 1:
                        time.sleep(0.5)
                        
                except Exception as e:
                    logger.error(f"❌ Error syncing {entry.stt}: {str(e)}")
                    error_count += 1
            
            if error_count == 0:
                self.message_user(request, f"✅ Đã sync {success_count} entries lên Drive")
            else:
                self.message_user(
                    request, 
                    f"⚠️ Sync hoàn thành: {success_count} thành công, {error_count} lỗi",
                    level=messages.WARNING
                )
                
        except Exception as e:
            self.message_user(request, f"❌ Lỗi sync: {str(e)}", level=messages.ERROR)
    sync_selected_entries.short_description = "🔄 Sync các entries đã chọn lên Drive"
    
    def mark_as_active(self, request, queryset):
        """Mark selected entries as active"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f"✅ Đã kích hoạt {updated} entries")
    mark_as_active.short_description = "✅ Kích hoạt các entries đã chọn"
    
    def mark_as_inactive(self, request, queryset):
        """Mark selected entries as inactive"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f"⏸️ Đã vô hiệu hóa {updated} entries")
    mark_as_inactive.short_description = "⏸️ Vô hiệu hóa các entries đã chọn"
    
    def export_selected_csv(self, request, queryset):
        """Export selected entries to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="qa_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['STT', 'question', 'answer', '', ''])
        
        for entry in queryset:
            writer.writerow([entry.stt, entry.question, entry.answer, '', ''])
        
        return response
    export_selected_csv.short_description = "📥 Export các entries đã chọn ra CSV"
    
    # ========== TOOLS PAGE (NEW) ==========
    
    def tools_view(self, request):
        """
        ✅ NEW: Dedicated tools page for global operations
        Replaces scattered global actions with organized interface
        """
        try:
            # Get statistics
            total_entries = QAEntry.objects.count()
            active_entries = QAEntry.objects.filter(is_active=True).count()
            synced_entries = QAEntry.objects.filter(sync_status='synced').count()
            pending_entries = QAEntry.objects.filter(sync_status='pending').count()
            error_entries = QAEntry.objects.filter(sync_status='error').count()
            never_synced = QAEntry.objects.filter(last_synced_to_drive__isnull=True).count()
            
            # Get recent sync logs
            recent_logs = QASyncLog.objects.order_by('-started_at')[:5]
            
            # Get Drive status
            drive_status = drive_service.get_drive_status()
            
            context = {
                'title': 'QA Management Tools',
                'subtitle': 'Công cụ quản lý toàn bộ hệ thống Q&A',
                'opts': self.model._meta,
                'has_permission': True,
                'app_label': self.model._meta.app_label,
                
                # Statistics
                'stats': {
                    'total_entries': total_entries,
                    'active_entries': active_entries,
                    'synced_entries': synced_entries,
                    'pending_entries': pending_entries,
                    'error_entries': error_entries,
                    'never_synced': never_synced,
                },
                
                # Drive status
                'drive_status': drive_status,
                'recent_logs': recent_logs,
                
                # URLs for actions
                'import_url': '../import-from-drive/',
                'export_url': '../export-to-drive/',
                'sync_status_url': '../sync-status/',
                'bulk_import_url': '../bulk-import/',
            }
            
            return render(request, 'admin/qa_management/tools.html', context)
            
        except Exception as e:
            messages.error(request, f"❌ Không thể tải tools page: {str(e)}")
            return redirect('..')
    
    # ========== EXISTING INDIVIDUAL OPERATION VIEWS ==========
    
    def import_from_drive_view(self, request):
        """Import Q&A from Google Drive"""
        if request.method == 'POST':
            try:
                result = drive_service.import_from_drive()
                
                if result['success']:
                    messages.success(
                        request, 
                        f"✅ Import thành công: {result['imported']} entries từ Drive"
                    )
                else:
                    messages.error(request, f"❌ Import thất bại: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                messages.error(request, f"❌ Lỗi import: {str(e)}")
            
            return redirect('../tools/')  # ✅ Redirect to tools page
        
        # GET request - show confirmation page
        context = {
            'title': 'Import từ Google Drive',
            'opts': self.model._meta,
            'has_permission': True,
        }
        return render(request, 'admin/qa_management/import_from_drive.html', context)
    
    def export_to_drive_view(self, request):
        """Export all Q&A to Google Drive"""
        if request.method == 'POST':
            try:
                result = drive_service.export_all_to_drive()
                
                if result['success']:
                    messages.success(
                        request, 
                        f"✅ Export thành công: {result['total_entries']} entries lên Drive"
                    )
                else:
                    messages.error(request, f"❌ Export thất bại: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                messages.error(request, f"❌ Lỗi export: {str(e)}")
            
            return redirect('../tools/')  # ✅ Redirect to tools page
        
        # GET request - show confirmation page
        total_entries = QAEntry.objects.count()
        context = {
            'title': 'Export lên Google Drive',
            'total_entries': total_entries,
            'opts': self.model._meta,
            'has_permission': True,
        }
        return render(request, 'admin/qa_management/export_to_drive.html', context)
    
    def sync_status_view(self, request):
        """Show sync status dashboard"""
        try:
            # Get statistics
            total_entries = QAEntry.objects.count()
            synced_entries = QAEntry.objects.filter(sync_status='synced').count()
            pending_entries = QAEntry.objects.filter(sync_status='pending').count()
            error_entries = QAEntry.objects.filter(sync_status='error').count()
            never_synced = QAEntry.objects.filter(last_synced_to_drive__isnull=True).count()
            
            # Get recent sync logs
            recent_logs = QASyncLog.objects.order_by('-started_at')[:10]
            
            # Get Drive status
            drive_status = drive_service.get_drive_status()
            
            context = {
                'title': 'Sync Status Dashboard',
                'total_entries': total_entries,
                'synced_entries': synced_entries,
                'pending_entries': pending_entries,
                'error_entries': error_entries,
                'never_synced': never_synced,
                'recent_logs': recent_logs,
                'drive_status': drive_status,
                'opts': self.model._meta,
                'has_permission': True,
            }
            return render(request, 'admin/qa_management/sync_status.html', context)
            
        except Exception as e:
            messages.error(request, f"❌ Không thể tải sync status: {str(e)}")
            return redirect('../tools/')  # ✅ Redirect to tools page
    
    def bulk_import_view(self, request):
        """Bulk import from uploaded CSV"""
        if request.method == 'POST' and request.FILES.get('csv_file'):
            try:
                csv_file = request.FILES['csv_file']
                
                # Read and parse CSV
                file_data = csv_file.read().decode('utf-8')
                csv_reader = csv.DictReader(io.StringIO(file_data))
                
                imported_count = 0
                error_count = 0
                errors = []
                
                with transaction.atomic():
                    for row_num, row in enumerate(csv_reader, start=2):
                        try:
                            stt = row.get('STT', '').strip()
                            question = row.get('question', '').strip()
                            answer = row.get('answer', '').strip()
                            
                            if not stt or not question or not answer:
                                errors.append(f"Row {row_num}: Missing required fields")
                                error_count += 1
                                continue
                            
                            # Create new entry (allows duplicate STT)
                            entry = QAEntry.objects.create(
                                stt=stt,
                                question=question,
                                answer=answer,
                                category=row.get('category', 'Giảng viên'),
                                sync_status='pending'
                            )
                            imported_count += 1
                            
                        except Exception as e:
                            errors.append(f"Row {row_num}: {str(e)}")
                            error_count += 1
                
                if error_count == 0:
                    messages.success(request, f"✅ Import thành công {imported_count} entries")
                else:
                    messages.warning(
                        request, 
                        f"⚠️ Import hoàn thành: {imported_count} thành công, {error_count} lỗi"
                    )
                    
            except Exception as e:
                messages.error(request, f"❌ Lỗi import: {str(e)}")
            
            return redirect('../tools/')  # ✅ Redirect to tools page
        
        # GET request - show upload form
        context = {
            'title': 'Bulk Import từ CSV',
            'opts': self.model._meta,
            'has_permission': True,
        }
        return render(request, 'admin/qa_management/bulk_import.html', context)

# ========== SYNC LOG ADMIN ==========

@admin.register(QASyncLog)
class QASyncLogAdmin(admin.ModelAdmin):
    """Admin for sync logs"""
    
    list_display = [
        'operation',
        'status',
        'started_at',
        'duration_display',
        'entries_summary',
        'success_rate_display'
    ]
    
    list_filter = [
        'operation',
        'status',
        'started_at',
    ]
    
    readonly_fields = [
        'operation', 'status', 'started_at', 'completed_at',
        'entries_processed', 'entries_success', 'entries_failed',
        'error_message', 'details'
    ]
    
    def has_add_permission(self, request):
        """Prevent manual addition of logs"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Make logs read-only"""
        return False
    
    def duration_display(self, obj):
        """Show operation duration"""
        if obj.duration_seconds:
            return f"{obj.duration_seconds:.1f}s"
        return "In progress..."
    duration_display.short_description = "Duration"
    
    def entries_summary(self, obj):
        """Show processed/success/failed summary"""
        return f"{obj.entries_processed} / {obj.entries_success} / {obj.entries_failed}"
    entries_summary.short_description = "Processed/Success/Failed"
    
    def success_rate_display(self, obj):
        """Show success rate with color"""
        rate = obj.success_rate
        if rate >= 95:
            color = "#28a745"  # green
        elif rate >= 80:
            color = "#ffc107"  # yellow
        else:
            color = "#dc3545"  # red
            
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color,
            rate
        )
    success_rate_display.short_description = "Success Rate"