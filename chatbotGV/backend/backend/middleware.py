import re
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

class CSRFExemptMiddleware(MiddlewareMixin):
    """
    Middleware to exempt certain URLs from CSRF validation
    CHỈ DÙNG CHO DEVELOPMENT
    """
    
    def process_request(self, request):
        if not settings.DEBUG:
            return None
            
        # List of URL patterns to exempt from CSRF
        exempt_patterns = [
            r'^/api/auth/.*',
            r'^/api/chat/.*',
            r'^/api/personalized-.*',
            r'^/api/system-status-.*',
        ]
        
        # Check if current path matches any exempt pattern
        path = request.path
        for pattern in exempt_patterns:
            if re.match(pattern, path):
                setattr(request, '_dont_enforce_csrf_checks', True)
                break
        
        return None