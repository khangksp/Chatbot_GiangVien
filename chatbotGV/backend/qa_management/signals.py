from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver
from django.utils import timezone
from django.conf import settings
import logging
import threading

logger = logging.getLogger(__name__)

def get_chatbot_retriever():
    """
    ✅ FIXED: Truy cập Chatbot Retriever an toàn bằng Import Tuyệt Đối.
    Dựa trên cấu trúc: ai_models/chatbot_logic/chatbot_service.py
    """
    try:
        # 1. IMPORT TUYỆT ĐỐI (Không dùng dấu ..)
        # Django chạy từ manage.py nên 'ai_models' là package cấp cao nhất
        from ai_models.services import chatbot_ai
        
        # 2. Kiểm tra xem biến chatbot_ai có tồn tại và đã khởi tạo chưa
        if chatbot_ai is None:
            return None

        # 3. Tìm Retriever bên trong instance chatbot_ai
        # Ưu tiên 1: Thuộc tính .retriever chuẩn
        if hasattr(chatbot_ai, 'retriever'):
            return chatbot_ai.retriever
            
        # Ưu tiên 2: Thuộc tính .hybrid_retriever
        if hasattr(chatbot_ai, 'hybrid_retriever'):
            return chatbot_ai.hybrid_retriever

        # Ưu tiên 3: Thuộc tính .sbert_retriever
        if hasattr(chatbot_ai, 'sbert_retriever'):
            return chatbot_ai.sbert_retriever
            
        logger.warning("⚠️ Found chatbot_ai but no retriever attribute (retriever/hybrid_retriever)")
        return None
        
    except ImportError:
        # Trường hợp chưa load được module (thường xảy ra khi server đang khởi động)
        return None
    except Exception as e:
        logger.error(f"❌ Error accessing chatbot retriever: {str(e)}")
        return None

def reload_chatbot_knowledge():
    """
    ✅ SAFE: Reload chatbot knowledge base in background thread
    """
    def _reload():
        try:
            retriever = get_chatbot_retriever()
            if retriever and hasattr(retriever, 'load_knowledge_base'):
                # Gọi hàm load lại dữ liệu
                retriever.load_knowledge_base()
                
                # Nếu cần build lại index FAISS (quan trọng cho tìm kiếm vector)
                if hasattr(retriever, 'build_faiss_index'):
                    retriever.build_faiss_index()
                    
                logger.info("✅ Chatbot knowledge base reloaded successfully (Background)")
            else:
                # Không log warning spam nếu retriever chưa sẵn sàng
                pass
        except Exception as e:
            logger.error(f"❌ Failed to reload chatbot knowledge base: {str(e)}")
    
    # Run in background thread to avoid blocking
    reload_thread = threading.Thread(target=_reload)
    reload_thread.daemon = True
    reload_thread.start()

def sync_entry_to_drive(instance):
    """
    ✅ SAFE: Auto-sync entry to Drive in background
    """
    def _sync():
        try:
            # Mark to prevent recursive sync
            instance._syncing = True
            
            from .services import drive_service
            
            result = drive_service.sync_single_entry(instance)
            if result:
                logger.info(f"✅ Auto-sync successful for entry: {instance.stt}")
            else:
                logger.warning(f"⚠️ Auto-sync failed for entry: {instance.stt}")
                
        except Exception as e:
            logger.error(f"❌ Auto-sync error for {instance.stt}: {str(e)}")
        finally:
            # Remove syncing flag
            if hasattr(instance, '_syncing'):
                delattr(instance, '_syncing')
    
    # Run sync in background thread
    sync_thread = threading.Thread(target=_sync)
    sync_thread.daemon = True
    sync_thread.start()

def clear_chatbot_cache():
    """
    ✅ SAFE: Clear chatbot and drive cache
    """
    try:
        # Clear chatbot cache
        retriever = get_chatbot_retriever()
        if retriever:
            if hasattr(retriever, 'cached_data'):
                retriever.cached_data = None
            if hasattr(retriever, 'cache_timestamp'):
                retriever.cache_timestamp = 0
        
        # Clear Google Drive cache
        try:
            from .services import drive_service
            if hasattr(drive_service, 'clear_cache'):
                drive_service.clear_cache()
        except Exception as e:
            logger.debug(f"Drive cache clear failed: {str(e)}")
        
        logger.info("🗑️ Chatbot and drive cache cleared")
        
    except Exception as e:
        logger.error(f"❌ Cache clearing error: {str(e)}")

@receiver(post_save, sender='qa_management.QAEntry')
def qa_entry_post_save_handler(sender, instance, created, **kwargs):
    """
    ✅ CONSOLIDATED: Handle all post-save operations for QA Entry
    Combines: auto-reload, auto-sync, cache invalidation, notifications, audit
    """
    try:
        action = "created" if created else "updated"
        logger.info(f"🔄 QA Entry {action}: {instance.stt}")
        
        # 1. Update sync status (only for updates, not new entries)
        if not created and not getattr(instance, '_syncing', False):
            sender.objects.filter(pk=instance.pk).update(sync_status='pending')
        
        # 2. Get settings
        chatbot_integration = getattr(settings, 'CHATBOT_INTEGRATION', {})
        qa_settings = getattr(settings, 'QA_MANAGEMENT', {})
        
        # 3. Auto-reload chatbot knowledge base
        auto_rebuild = chatbot_integration.get('AUTO_REBUILD_INDEX', True)
        if auto_rebuild:
            reload_chatbot_knowledge()
        
        # 4. Auto-sync to Google Drive (if enabled and not during bulk operations)
        auto_sync = qa_settings.get('AUTO_SYNC_ON_SAVE', False)
        if (auto_sync and not created and 
            not getattr(instance, '_syncing', False) and 
            not getattr(instance, '_bulk_operation', False) and
            not instance.stt.startswith(('DEBUG_TEST_', 'QUICK_TEST_'))):
            
            logger.info(f"🔄 Auto-sync triggered for: {instance.stt}")
            sync_entry_to_drive(instance)
        
        # 5. Cache invalidation
        cache_invalidation = chatbot_integration.get('CACHE_INVALIDATION', True)
        if cache_invalidation:
            clear_chatbot_cache()
        
        # 6. Audit logging
        audit_enabled = qa_settings.get('AUDIT_LOG_ENABLED', True)
        if audit_enabled:
            logger.info(f"📋 AUDIT: {action.upper()} QA Entry {instance.stt} - '{instance.question[:30]}...'")
            
    except Exception as e:
        logger.error(f"❌ QA Entry post-save signal error: {str(e)}")

@receiver(post_delete, sender='qa_management.QAEntry')
def qa_entry_post_delete_handler(sender, instance, **kwargs):
    """
    ✅ CONSOLIDATED: Handle all post-delete operations for QA Entry
    """
    try:
        logger.info(f"🗑️ QA Entry deleted: {instance.stt}")
        
        # Get settings
        chatbot_integration = getattr(settings, 'CHATBOT_INTEGRATION', {})
        qa_settings = getattr(settings, 'QA_MANAGEMENT', {})
        
        # 1. Auto-reload chatbot knowledge base
        auto_rebuild = chatbot_integration.get('AUTO_REBUILD_INDEX', True)
        if auto_rebuild:
            reload_chatbot_knowledge()
        
        # 2. Cache invalidation
        cache_invalidation = chatbot_integration.get('CACHE_INVALIDATION', True)
        if cache_invalidation:
            clear_chatbot_cache()
        
        # 3. Audit logging
        audit_enabled = qa_settings.get('AUDIT_LOG_ENABLED', True)
        if audit_enabled:
            logger.info(f"📋 AUDIT: DELETED QA Entry {instance.stt} - '{instance.question[:30]}...'")
        
    except Exception as e:
        logger.error(f"❌ QA Entry post-delete signal error: {str(e)}")

@receiver(pre_delete, sender='qa_management.QAEntry')
def qa_entry_pre_delete_handler(sender, instance, **kwargs):
    """
    ✅ AUDIT: Handle before deletion - log for audit trail
    """
    try:
        logger.info(f"📝 Preparing to delete QA Entry: {instance.stt} - '{instance.question[:50]}...'")
    except Exception as e:
        logger.error(f"❌ QA Entry pre-delete signal error: {str(e)}")

@receiver(post_save, sender='qa_management.QASyncLog')
def sync_log_created(sender, instance, created, **kwargs):
    """
    Handle sync log creation
    """
    if created:
        try:
            logger.info(f"📊 Sync operation logged: {instance.operation} - {instance.status}")
            if instance.status == 'failed':
                logger.warning(f"⚠️ Sync operation failed: {instance.operation}")
        except Exception as e:
            logger.error(f"❌ Sync log signal error: {str(e)}")

def trigger_chatbot_reload():
    """Public function to trigger chatbot reload from external code"""
    reload_chatbot_knowledge()

def trigger_cache_clear():
    """Public function to clear cache from external code"""
    clear_chatbot_cache()

def get_signal_status():
    """Get status of signal integrations for debugging"""
    try:
        retriever = get_chatbot_retriever()
        from .services import drive_service
        drive_connected = drive_service.service is not None
        
        return {
            'chatbot_retriever_available': retriever is not None,
            'drive_service_connected': drive_connected,
            'signals_working': True
        }
    except Exception as e:
        return {
            'chatbot_retriever_available': False,
            'drive_service_connected': False,
            'signals_working': False,
            'error': str(e)
        }