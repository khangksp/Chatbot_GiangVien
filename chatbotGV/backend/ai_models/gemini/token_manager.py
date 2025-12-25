import re
from typing import Dict, Any
import logging
logger = logging.getLogger(__name__)

class SmartTokenManager:    
    def __init__(self):
        self.adaptive_token_range = {
            'min': 100, 
            'optimal': 1000, 
            'max': 2026,
            'expected_sentences': 3, 
            'avg_chars_per_sentence': 80
        }
        
        # Các pattern báo hiệu câu bị cắt giữa chừng
        self.incomplete_patterns = [
            r'[^.!?"]\s*$',  # Không kết thúc bằng dấu câu (trừ khi là quote)
            r'\b(và|hoặc|với|để|khi|nếu|tại|về|cho|trong|của|từ)\s*$', # Kết thúc bằng giới từ/liên từ
            r'\b(em|sẽ|có|được|phải|cần|nên)\s*$', # Kết thúc bằng động từ khuyết thiếu
            r'[,;:]\s*$', # Kết thúc bằng dấu phẩy
        ]
        
        logger.info("✅ SmartTokenManager initialized (Relaxed Mode)")

    def calculate_optimal_tokens(self, prompt_length: int, complexity_hint: str = None) -> int:        
        base_tokens = self.adaptive_token_range['optimal']
        
        if prompt_length > 3000:
            base_tokens += 300
        elif prompt_length < 500:
            base_tokens -= 50

        if complexity_hint:
            high_token_hints = [
                'enhanced_generation', 'detailed_explanation', 
                'document_context', 'two_stage_reranking', 
                'direct_enhance', 'direct_answer'
            ]
            if complexity_hint in high_token_hints:
                base_tokens += 300
            elif complexity_hint in ['quick_clarify', 'simple_answer']:
                base_tokens -= 40
        
        return max(self.adaptive_token_range['min'], 
                   min(self.adaptive_token_range['max'], base_tokens))

    def check_response_completion(self, response: str) -> Dict[str, Any]:
        """
        Kiểm tra xem câu trả lời có bị cắt cụt không.
        Phiên bản này đã được nới lỏng để không bắt buộc phải có 'Dạ/ạ' 
        (để hỗ trợ xưng hô bạn bè/thoải mái).
        """
        if not response:
            return {'incomplete': True, 'reason': 'empty_response', 'confidence': 1.0}
            
        response = response.strip()
        
        # 1. Kiểm tra các pattern báo hiệu cắt giữa chừng rõ ràng
        for pattern in self.incomplete_patterns:
            if re.search(pattern, response):
                return {
                    'incomplete': True, 
                    'reason': 'matched_incomplete_pattern',
                    'pattern': pattern,
                    'confidence': 0.8
                }

        # 2. Kiểm tra ký tự kết thúc hợp lệ (quan trọng nhất)
        # Chấp nhận ., !, ?, ", và cả emoji nếu cần
        valid_ending = r'[.!?"]\s*$'
        if not re.search(valid_ending, response):
             return {
                'incomplete': True,
                'reason': 'missing_punctuation_ending',
                'confidence': 0.7
            }

        # ✅ ĐÃ BỎ: Check "Dạ... ạ" bắt buộc.
        # Lý do: Để tránh conflict khi user muốn xưng hô "bạn - tôi" hoặc "Khang".

        return {'incomplete': False, 'reason': 'complete', 'confidence': 0.9}

    def estimate_completion_tokens(self, incomplete_response: str) -> int:        
        # Ước lượng cần thêm bao nhiêu token nữa
        return 300 # Mặc định cho an toàn