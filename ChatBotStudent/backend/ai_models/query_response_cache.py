import time
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from django.core.cache import cache as django_cache
from django.conf import settings

from .interaction_logger_service import interaction_logger
logger = logging.getLogger(__name__)

class QueryResponseCache:
    """
    🚀 Lớp Cache hiệu quả cho câu trả lời chatbot BDU
    Triển khai cache với TTL, kiểm soát chất lượng và chuẩn hóa key
    """
    
    def __init__(self, default_ttl: int = 300): 
        """
        Khởi tạo cache với TTL mặc định
        
        Args:
            default_ttl: Thời gian sống mặc định (giây) - 1800s = 30 phút
        """
        self.default_ttl = default_ttl
        self.cache_prefix = "bdu_chatbot_qr_"
        self.min_confidence_threshold = 0.6  # Chỉ cache câu trả lời có confidence > 0.6
        self.cache_stats = {
            'hits': 0,
            'misses': 0,
            'stores': 0,
            'rejections_low_confidence': 0,
            'rejections_personal_api': 0,
            'total_requests': 0
        }
        
        # Từ khóa đánh dấu câu hỏi cá nhân (không cache)
        self.personal_keywords = {
            'lịch của tôi', 'lich cua toi', 'tkb của tôi', 'lịch giảng của tôi',
            'tôi giảng', 'toi giang', 'tôi dạy', 'toi day', 'hôm nay tôi',    
            'tôi là ai', 'toi la ai', 'thông tin của tôi', 'email của tôi',
            'my schedule', 'my teaching', 'who am i'
        }
        
        logger.info(f"🚀 QueryResponseCache initialized with TTL={default_ttl}s, min_confidence={self.min_confidence_threshold}")

    def _normalize_query(self, query: str) -> str:
        """
        Chuẩn hóa câu hỏi để tạo key cache nhất quán
        
        Args:
            query: Câu hỏi gốc
            
        Returns:
            str: Câu hỏi đã được chuẩn hóa
        """
        if not query:
            return ""
        
        # Chuyển về chữ thường
        normalized = query.lower().strip()
        
        # Bỏ khoảng trắng thừa
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Bỏ dấu câu ở đầu và cuối
        normalized = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', normalized)
        
        # Chuẩn hóa một số ký tự đặc biệt tiếng Việt
        replacements = {
            'ă': 'a', 'â': 'a', 'á': 'a', 'à': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
            'ê': 'e', 'é': 'e', 'è': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
            'í': 'i', 'ì': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
            'ô': 'o', 'ơ': 'o', 'ó': 'o', 'ò': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
            'ư': 'u', 'ú': 'u', 'ù': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
            'ý': 'y', 'ỳ': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
            'đ': 'd'
        }
        
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        
        return normalized

    def _generate_cache_key(self, query: str) -> str:
        """
        Tạo key cache từ câu hỏi đã chuẩn hóa
        
        Args:
            query: Câu hỏi đã chuẩn hóa
            
        Returns:
            str: Cache key duy nhất
        """
        # Sử dụng MD5 hash để đảm bảo key ngắn gọn và duy nhất
        query_hash = hashlib.md5(query.encode('utf-8')).hexdigest()
        return f"{self.cache_prefix}{query_hash}"

    def _is_personal_query(self, query: str) -> bool:
        """
        Kiểm tra xem câu hỏi có phải là thông tin cá nhân không
        
        Args:
            query: Câu hỏi gốc
            
        Returns:
            bool: True nếu là câu hỏi cá nhân (không nên cache)
        """
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in self.personal_keywords)

    def _is_cacheable_response(self, response_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Kiểm tra xem response có đủ điều kiện để cache không
        
        Args:
            response_data: Dữ liệu response từ chatbot
            
        Returns:
            Tuple[bool, str]: (có thể cache không, lý do)
        """
        # Kiểm tra confidence
        confidence = response_data.get('confidence', 0.0)
        if confidence <= self.min_confidence_threshold:
            return False, f"confidence_too_low_{confidence}"
        
        # Kiểm tra method (không cache external API)
        method = response_data.get('method', '')
        if method in ['external_api', 'external_api_processing', 'authentication_required']:
            return False, f"method_not_cacheable_{method}"
        
        # Kiểm tra error
        if 'error' in response_data:
            return False, "has_error"
        
        # Kiểm tra response có nội dung không
        response_text = response_data.get('response', '').strip()
        if not response_text or len(response_text) < 10:
            return False, "response_too_short"
        
        # Kiểm tra các flag đặc biệt
        if response_data.get('external_api_used', False):
            return False, "external_api_used"
        
        if response_data.get('authentication_required', False):
            return False, "authentication_required"
        
        return True, "cacheable"

    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Lấy response từ cache
        
        Args:
            query: Câu hỏi gốc
            
        Returns:
            Dict hoặc None: Response data nếu có trong cache, None nếu không có
        """
        self.cache_stats['total_requests'] += 1
        
        # Kiểm tra câu hỏi cá nhân
        if self._is_personal_query(query):
            logger.debug(f"🚫 Personal query detected, skipping cache: '{query[:50]}...'")
            self.cache_stats['misses'] += 1
            return None
        
        # Chuẩn hóa và tạo key
        normalized_query = self._normalize_query(query)
        cache_key = self._generate_cache_key(normalized_query)
        
        try:
            # Thử lấy từ Django cache trước
            cached_data = django_cache.get(cache_key)
            
            if cached_data:
                # Kiểm tra TTL thủ công (phòng trường hợp Django cache không tự xóa)
                if 'cached_at' in cached_data:
                    cached_time = datetime.fromisoformat(cached_data['cached_at'])
                    if datetime.now() - cached_time > timedelta(seconds=self.default_ttl):
                        logger.debug(f"🕒 Cache expired manually, removing: {cache_key}")
                        django_cache.delete(cache_key)
                        self.cache_stats['misses'] += 1
                        return None
                
                logger.info(f"🎯 Cache HIT for query: '{query[:50]}...' (key: {cache_key[:20]}...)")
                self.cache_stats['hits'] += 1
                
                # Cập nhật thông tin cache hit
                result = cached_data['response_data'].copy()
                result['cache_hit'] = True
                result['cached_at'] = cached_data['cached_at']
                result['cache_ttl_remaining'] = self.default_ttl - int((datetime.now() - datetime.fromisoformat(cached_data['cached_at'])).total_seconds())
                
                return result
            
        except Exception as e:
            logger.error(f"❌ Cache get error: {str(e)}")
        
        logger.debug(f"💨 Cache MISS for query: '{query[:50]}...'")
        self.cache_stats['misses'] += 1
        return None

    def set(self, query: str, response_data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """
        Lưu response vào cache
        
        Args:
            query: Câu hỏi gốc
            response_data: Dữ liệu response từ chatbot
            ttl: Time-to-live tùy chỉnh (giây), None để dùng default
            
        Returns:
            bool: True nếu lưu thành công, False nếu không
        """
        # Kiểm tra câu hỏi cá nhân
        if self._is_personal_query(query):
            logger.debug(f"🚫 Personal query, not caching: '{query[:50]}...'")
            self.cache_stats['rejections_personal_api'] += 1
            return False
        
        # Kiểm tra response có đủ điều kiện cache không
        cacheable, reason = self._is_cacheable_response(response_data)
        if not cacheable:
            logger.debug(f"🚫 Response not cacheable, reason: {reason} for query: '{query[:50]}...'")

            # Ghi lại câu hỏi này vì nó không đủ chất lượng để cache
            interaction_logger.log_interaction(
                query=query,
                response=response_data.get('response', ''),
                confidence=response_data.get('confidence', 0.0),
                method=response_data.get('method', 'unknown'),
                reason=f"cache_rejected_{reason}"
            )
            
            if 'confidence_too_low' in reason:
                self.cache_stats['rejections_low_confidence'] += 1
            else:
                self.cache_stats['rejections_personal_api'] += 1
            return False
        
        # Chuẩn hóa và tạo key
        normalized_query = self._normalize_query(query)
        cache_key = self._generate_cache_key(normalized_query)
        
        # Chuẩn bị dữ liệu cache
        cache_data = {
            'response_data': response_data.copy(),
            'original_query': query,
            'normalized_query': normalized_query,
            'cached_at': datetime.now().isoformat(),
            'confidence': response_data.get('confidence', 0.0),
            'method': response_data.get('method', 'unknown')
        }
        
        # Xóa một số field không cần thiết để tiết kiệm space
        cache_data['response_data'].pop('processing_time', None)
        cache_data['response_data'].pop('generation_time', None)
        
        try:
            # Sử dụng TTL tùy chỉnh hoặc default
            effective_ttl = ttl or self.default_ttl
            
            # Lưu vào Django cache
            django_cache.set(cache_key, cache_data, timeout=effective_ttl)
            
            logger.info(f"💾 Cache STORED for query: '{query[:50]}...' (confidence: {cache_data['confidence']}, ttl: {effective_ttl}s)")
            self.cache_stats['stores'] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Cache set error: {str(e)}")
            return False

    def clear_cache(self, pattern: Optional[str] = None) -> int:
        """
        Xóa cache (development/testing)
        
        Args:
            pattern: Pattern để xóa cache cụ thể (không implement trong Django cache)
            
        Returns:
            int: Số lượng entries đã xóa (ước tính)
        """
        try:
            if hasattr(django_cache, 'clear'):
                django_cache.clear()
                logger.info("🗑️ Cache cleared successfully")
                return 1  # Django cache không trả về số lượng cụ thể
            else:
                logger.warning("⚠️ Cache clear not supported by current backend")
                return 0
        except Exception as e:
            logger.error(f"❌ Cache clear error: {str(e)}")
            return 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Lấy thống kê cache
        
        Returns:
            Dict: Thống kê cache hiện tại
        """
        total_requests = self.cache_stats['total_requests']
        hit_rate = (self.cache_stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'cache_stats': self.cache_stats.copy(),
            'hit_rate_percentage': round(hit_rate, 2),
            'configuration': {
                'default_ttl_seconds': self.default_ttl,
                'min_confidence_threshold': self.min_confidence_threshold,
                'cache_prefix': self.cache_prefix,
                'personal_keywords_count': len(self.personal_keywords)
            },
            'cache_info': {
                'backend': str(type(django_cache)),
                'supports_ttl': True,
                'supports_pattern_delete': False
            }
        }

    def update_ttl(self, new_ttl: int) -> None:
        """
        Cập nhật TTL mặc định
        
        Args:
            new_ttl: TTL mới (giây)
        """
        old_ttl = self.default_ttl
        self.default_ttl = new_ttl
        logger.info(f"🔄 Cache TTL updated: {old_ttl}s -> {new_ttl}s")

# Singleton instance
query_response_cache = QueryResponseCache()