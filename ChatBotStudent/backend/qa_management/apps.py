from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class QaManagementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'qa_management'
    verbose_name = 'Q&A Management'
    
    def ready(self):
        """
        Called when the app is ready.
        Initialize any background services or connections.
        """
        try:
            # Import signals to register them
            from . import signals
            
            # Import services to ensure they're initialized
            from .services import drive_service
            
            # Check initial connection
            drive_status = drive_service.get_drive_status()
            if drive_status['connected']:
                logger.info("QA Management: Google Drive connection established")
            else:
                logger.warning(f"QA Management: Google Drive connection failed - {drive_status.get('error', 'Unknown error')}")
            
            logger.info("QA Management app ready with signals registered")
            
        except Exception as e:
            logger.error(f"QA Management app initialization error: {str(e)}")