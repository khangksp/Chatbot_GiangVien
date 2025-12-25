"""
Views for QA Management

Currently, all functionality is handled through Django Admin custom views.
This file is reserved for future API endpoints or standalone views.
"""

from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json

# Future API views can be implemented here
# For now, all functionality is in admin.py

@staff_member_required
@require_http_methods(["GET"])
def qa_status_api(request):
    """
    API endpoint for Q&A status (for future use)
    Currently all status is handled through admin dashboard
    """
    try:
        from .models import QAEntry, QASyncLog
        from .services import drive_service
        
        # Get basic statistics
        total_entries = QAEntry.objects.count()
        active_entries = QAEntry.objects.filter(is_active=True).count()
        synced_entries = QAEntry.objects.filter(sync_status='synced').count()
        pending_entries = QAEntry.objects.filter(sync_status='pending').count()
        error_entries = QAEntry.objects.filter(sync_status='error').count()
        
        # Get Drive status
        drive_status = drive_service.get_drive_status()
        
        # Get recent sync log
        recent_sync = QASyncLog.objects.order_by('-started_at').first()
        
        return JsonResponse({
            'status': 'success',
            'statistics': {
                'total_entries': total_entries,
                'active_entries': active_entries,
                'synced_entries': synced_entries,
                'pending_entries': pending_entries,
                'error_entries': error_entries,
                'sync_percentage': round((synced_entries / total_entries * 100) if total_entries > 0 else 0, 1)
            },
            'drive_status': drive_status,
            'recent_sync': {
                'operation': recent_sync.get_operation_display() if recent_sync else None,
                'status': recent_sync.get_status_display() if recent_sync else None,
                'started_at': recent_sync.started_at.isoformat() if recent_sync else None,
                'entries_processed': recent_sync.entries_processed if recent_sync else 0,
                'success_rate': recent_sync.success_rate if recent_sync else 0
            } if recent_sync else None
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': str(e)
        }, status=500)

# Example view for future integrations
def health_check(request):
    """
    Health check endpoint for QA Management system
    """
    try:
        from .services import drive_service
        
        # Check database connection
        from .models import QAEntry
        db_count = QAEntry.objects.count()
        
        # Check Drive connection
        drive_status = drive_service.get_drive_status()
        
        return JsonResponse({
            'status': 'healthy',
            'database': {
                'connected': True,
                'entries_count': db_count
            },
            'google_drive': {
                'connected': drive_status['connected'],
                'file_exists': drive_status.get('file_exists', False)
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e)
        }, status=500)