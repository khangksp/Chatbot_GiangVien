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
import pandas as pd
from django.db.models.signals import post_save, post_delete
from .signals import qa_entry_post_save_handler, qa_entry_post_delete_handler
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
        'delete_selected_silent',
    ]
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('tools/', self.tools_view, name='qa_tools'),
            path('import-from-drive/', self.import_from_drive_view, name='qa_import_from_drive'),
            path('export-to-drive/', self.export_to_drive_view, name='qa_export_to_drive'),
            path('sync-status/', self.sync_status_view, name='qa_sync_status'),
            path('bulk-import/', self.bulk_import_view, name='qa_bulk_import'),
        ]
        return custom_urls + urls
    
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['tools_url'] = '../tools/'
        return super().changelist_view(request, extra_context)
    
    # ========== DISPLAY METHODS ==========
    
    def question_preview(self, obj):
        if len(obj.question) > 80: return obj.question[:80] + "..."
        return obj.question
    question_preview.short_description = "Câu hỏi"
    
    def answer_preview(self, obj):
        if len(obj.answer) > 60: return obj.answer[:60] + "..."
        return obj.answer
    answer_preview.short_description = "Câu trả lời"
    
    def sync_status_icon(self, obj):
        icons = {'pending': '⏳', 'synced': '✅', 'error': '❌'}
        icon = icons.get(obj.sync_status, '❓')
        color = {'pending': '#ffa500', 'synced': '#28a745', 'error': '#dc3545'}.get(obj.sync_status, '#6c757d')
        return format_html('<span style="color: {}; font-size: 16px;">{}</span> {}', color, icon, obj.get_sync_status_display())
    sync_status_icon.short_description = "Sync Status"
    
    def last_sync_info(self, obj):
        if obj.last_synced_to_drive:
            age = (timezone.now() - obj.last_synced_to_drive).total_seconds() / 60
            if age < 60: return f"{int(age)}m ago"
            elif age < 1440: return f"{int(age/60)}h ago"
            return f"{int(age/1440)}d ago"
        return "Never"
    last_sync_info.short_description = "Last Sync"
    
    def sync_selected_entries(self, request, queryset):
        try:
            count = queryset.count()
            if count == 0:
                self.message_user(request, "❌ Chưa chọn entry nào", level=messages.WARNING)
                return
            self.message_user(request, f"⏳ Đang sync {count} entries (Batch mode)...")
            result = drive_service.sync_batch_entries(queryset)
            if result['success']:
                self.message_user(request, f"✅ Đã sync thành công {result['count']} entries lên Drive.")
            else:
                self.message_user(request, f"❌ Lỗi sync: {result.get('error')}", level=messages.ERROR)
        except Exception as e:
            self.message_user(request, f"❌ Lỗi hệ thống: {str(e)}", level=messages.ERROR)
    sync_selected_entries.short_description = "🔄 Sync các entries đã chọn lên Drive (An toàn)"
    
    def mark_as_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"✅ Đã kích hoạt {updated} entries")
    mark_as_active.short_description = "✅ Kích hoạt các entries đã chọn"
    
    def mark_as_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"⏸️ Đã vô hiệu hóa {updated} entries")
    mark_as_inactive.short_description = "⏸️ Vô hiệu hóa các entries đã chọn"
    
    def export_selected_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="qa_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['STT', 'question', 'answer', 'category'])
        for entry in queryset:
            writer.writerow([entry.stt, entry.question, entry.answer, entry.category])
        return response
    export_selected_csv.short_description = "📥 Export các entries đã chọn ra CSV"
        
    def tools_view(self, request):
        try:
            total_entries = QAEntry.objects.count()
            active_entries = QAEntry.objects.filter(is_active=True).count()
            synced_entries = QAEntry.objects.filter(sync_status='synced').count()
            pending_entries = QAEntry.objects.filter(sync_status='pending').count()
            error_entries = QAEntry.objects.filter(sync_status='error').count()
            never_synced = QAEntry.objects.filter(last_synced_to_drive__isnull=True).count()
            recent_logs = QASyncLog.objects.order_by('-started_at')[:5]
            drive_status = drive_service.get_drive_status()
            context = {
                'title': 'QA Management Tools',
                'subtitle': 'Công cụ quản lý toàn bộ hệ thống Q&A',
                'opts': self.model._meta,
                'has_permission': True,
                'app_label': self.model._meta.app_label,
                'stats': {
                    'total_entries': total_entries,
                    'active_entries': active_entries,
                    'synced_entries': synced_entries,
                    'pending_entries': pending_entries,
                    'error_entries': error_entries,
                    'never_synced': never_synced,
                },
                'drive_status': drive_status,
                'recent_logs': recent_logs,
                'import_url': '../import-from-drive/',
                'export_url': '../export-to-drive/',
                'sync_status_url': '../sync-status/',
                'bulk_import_url': '../bulk-import/',
            }
            return render(request, 'admin/qa_management/tools.html', context)
        except Exception as e:
            messages.error(request, f"❌ Không thể tải tools page: {str(e)}")
            return redirect('..')
    
    def import_from_drive_view(self, request):
        """
        🔥 UPGRADED: Import từ Drive VÀ Reload Chatbot AI Memory (Hot Reload)
        """
        if request.method == 'POST':
            try:
                # BƯỚC 1: Kéo dữ liệu từ Drive về Server (Disk)
                # (Hàm này trong services.py đã được cập nhật thành V3 Wipe & Replace)
                result = drive_service.import_from_drive()
                
                if result['success']:
                    # Lấy thông báo chi tiết từ service (VD: "Đã xóa 6000 cũ -> Nạp 7148 mới")
                    msg = f"✅ {result.get('message', 'Import thành công')}. "
                    
                    # BƯỚC 2: Gọi Chatbot reload RAM (Hot Reload)
                    try:
                        # 👇 SỬA LỖI QUAN TRỌNG Ở ĐÂY: Dùng import tuyệt đối an toàn
                        import sys
                        
                        # Kiểm tra module đã load chưa
                        if 'ai_models.services' in sys.modules:
                            from ai_models.services import chatbot_ai
                        else:
                            # Fallback import trực tiếp từ gốc project
                            from ai_models.services import chatbot_ai
                        
                        # Thực hiện reload
                        if chatbot_ai and hasattr(chatbot_ai, 'reload_knowledge'):
                            reload_stats = chatbot_ai.reload_knowledge()
                            count = reload_stats.get('total_entries', 'all')
                            msg += f"🧠 AI đã học lại {count} kiến thức mới!"
                        else:
                            msg += "⚠️ Chatbot chưa sẵn sàng để reload RAM (nhưng DB đã cập nhật)."
                            
                    except ImportError:
                        msg += "⚠️ Không thể load module AI (ImportError)."
                    except Exception as e:
                        # Log lỗi nhưng không chặn thông báo thành công của bước 1
                        logger.error(f"Hot reload error: {e}")
                        msg += f"(Lỗi reload RAM: {str(e)})"

                    messages.success(request, msg)
                else:
                    messages.error(request, f"❌ Import thất bại: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                logger.error(f"View error: {e}")
                messages.error(request, f"❌ Lỗi hệ thống: {str(e)}")
            
            return redirect('../tools/')
        
        # GET request - show confirmation page
        context = {
            'title': 'Import & Hot Reload',
            'opts': self.model._meta,
            'has_permission': True,
            'description': 'Hành động này sẽ tải dữ liệu mới nhất từ Google Drive và nạp ngay lập tức vào bộ nhớ AI (Không cần khởi động lại Server).'
        }
        return render(request, 'admin/qa_management/import_from_drive.html', context)
    
    def export_to_drive_view(self, request):
        if request.method == 'POST':
            try:
                result = drive_service.export_all_to_drive()
                if result['success']:
                    messages.success(request, f"✅ Export thành công: {result['total_entries']} entries lên Drive")
                else:
                    messages.error(request, f"❌ Export thất bại: {result.get('error')}")
            except Exception as e:
                messages.error(request, f"❌ Lỗi export: {str(e)}")
            return redirect('../tools/')
        context = {'title': 'Export lên Google Drive', 'total_entries': QAEntry.objects.count(), 'opts': self.model._meta, 'has_permission': True}
        return render(request, 'admin/qa_management/export_to_drive.html', context)
    
    def delete_selected_silent(self, request, queryset):
        """
        🗑️ Xóa nhanh hàng loạt mà không bắn Signals (Tránh treo server)
        """
        count = queryset.count()
        
        # 1. NGẮT CẦU DAO (Disconnect Signals)
        post_save.disconnect(qa_entry_post_save_handler, sender=QAEntry)
        post_delete.disconnect(qa_entry_post_delete_handler, sender=QAEntry)
        
        try:
            # 2. Xóa sạch (Bulk Delete)
            queryset.delete()
            
            # 3. Reload AI thủ công 1 lần duy nhất
            try:
                # Import an toàn
                import sys
                if 'ai_models.services' in sys.modules:
                    from ai_models.services import chatbot_ai
                else:
                    from ai_models.services import chatbot_ai
                
                if hasattr(chatbot_ai, 'reload_knowledge'):
                    chatbot_ai.reload_knowledge()
            except Exception as e:
                logger.error(f"Reload error after delete: {e}")

            self.message_user(request, f"✅ Đã xóa vĩnh viễn {count} entries và làm mới bộ nhớ AI.")
            
        except Exception as e:
            self.message_user(request, f"❌ Lỗi xóa: {str(e)}", level=messages.ERROR)
            
        finally:
            # 4. BẬT LẠI CẦU DAO (Reconnect)
            post_save.connect(qa_entry_post_save_handler, sender=QAEntry)
            post_delete.connect(qa_entry_post_delete_handler, sender=QAEntry)

    delete_selected_silent.short_description = "🗑️ Xóa nhanh các dòng đã chọn (Không log rác)"
    
    def sync_status_view(self, request):
        """Show sync status dashboard"""
        try:
            total_entries = QAEntry.objects.count()
            synced_entries = QAEntry.objects.filter(sync_status='synced').count()
            pending_entries = QAEntry.objects.filter(sync_status='pending').count()
            error_entries = QAEntry.objects.filter(sync_status='error').count()
            never_synced = QAEntry.objects.filter(last_synced_to_drive__isnull=True).count()
            recent_logs = QASyncLog.objects.order_by('-started_at')[:10]
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
            messages.error(request, f"❌ Error: {str(e)}")
            return redirect('../tools/')
    
    def bulk_import_view(self, request):
        """Bulk import từ file CSV upload lên"""
        if request.method == 'POST' and request.FILES.get('csv_file'):
            try:
                csv_file = request.FILES['csv_file']
                
                # Dùng Pandas đọc cho chuẩn (giống service Import Drive)
                try:
                    df = pd.read_csv(csv_file, dtype=str) # dtype=str để giữ số 0 ở đầu (VD: 01)
                    df.columns = df.columns.str.strip() # Xóa khoảng trắng tên cột
                except Exception as e:
                    messages.error(request, f"❌ Lỗi đọc file CSV: {str(e)}")
                    return redirect('../tools/')

                # Kiểm tra cột bắt buộc
                required_cols = ['STT', 'question', 'answer']
                if not all(col in df.columns for col in required_cols):
                    messages.error(request, f"❌ File thiếu cột bắt buộc: {required_cols}")
                    return redirect('../tools/')

                df = df.fillna('')
                imported_count = 0
                updated_count = 0
                now = timezone.now()
                
                # Dùng transaction để an toàn
                with transaction.atomic():
                    for _, row in df.iterrows():
                        stt = str(row['STT']).strip()
                        question = str(row['question']).strip()
                        answer = str(row['answer']).strip()
                        category = str(row.get('category', 'Giảng viên')).strip()
                        
                        if not question or not answer:
                            continue
                            
                        # Update or Create
                        obj, created = QAEntry.objects.update_or_create(
                            stt=stt,
                            defaults={
                                'question': question,
                                'answer': answer,
                                'category': category,
                                'sync_status': 'pending', # Đánh dấu là chưa sync lên Drive
                                'updated_at': now
                            }
                        )
                        
                        if created:
                            imported_count += 1
                        else:
                            updated_count += 1
                
                messages.success(request, f"✅ Đã import thành công: {imported_count} mới, {updated_count} cập nhật.")
                
                # Gợi ý người dùng sync lên Drive sau khi import xong
                messages.warning(request, "⚠️ Lưu ý: Dữ liệu này mới chỉ nằm trong Database. Hãy bấm 'Export lên Drive' nếu muốn đồng bộ ngược lên Google Drive.")

            except Exception as e:
                messages.error(request, f"❌ Lỗi hệ thống: {str(e)}")
            
            return redirect('../tools/')
        
        context = {
            'title': 'Bulk Import từ CSV',
            'opts': self.model._meta,
            'has_permission': True
        }
        return render(request, 'admin/qa_management/bulk_import.html', context)

@admin.register(QASyncLog)
class QASyncLogAdmin(admin.ModelAdmin):
    list_display = [
        'operation', 
        'status', 
        'started_at', 
        'duration_display', 
        'entries_summary', 
        'success_rate_display'
    ]
    
    list_filter = ['operation', 'status', 'started_at']
    
    # ✅ QUAN TRỌNG: Khóa tất cả các trường lại thành chỉ đọc
    readonly_fields = [
        'operation', 'status', 'started_at', 'completed_at',
        'entries_processed', 'entries_success', 'entries_failed',
        'error_message', 'details'
    ]

    # Chặn thêm mới
    def has_add_permission(self, request):
        return False

    # Chặn xóa (để bảo vệ Logs)
    def has_delete_permission(self, request, obj=None):
        return False

    # ✅ QUAN TRỌNG: Phải trả về True để Django tạo URL (nhưng vì có readonly_fields nên vẫn an toàn)
    def has_change_permission(self, request, obj=None):
        return True

    # Cho phép xem
    def has_view_permission(self, request, obj=None):
        return True

    # --- Các hàm hiển thị đẹp ---
    
    def duration_display(self, obj):
        return f"{obj.duration_seconds:.1f}s" if obj.duration_seconds else "Running..."
    duration_display.short_description = "Duration"

    def entries_summary(self, obj):
        return f"{obj.entries_processed} / {obj.entries_success} / {obj.entries_failed}"
    entries_summary.short_description = "Processed/Success/Failed"

    def success_rate_display(self, obj): 
        rate = float(obj.success_rate) if obj.success_rate is not None else 0.0
        
        if rate >= 95:
            color = "#28a745"  # Xanh
        elif rate >= 80:
            color = "#ffc107"  # Vàng
        else:
            color = "#dc3545"  # Đỏ
            
        # Sửa lại cách format string cho an toàn tuyệt đối
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color,
            rate
        )
    success_rate_display.short_description = "Success Rate"