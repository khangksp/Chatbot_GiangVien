import logging
import requests
import re
import time
from unidecode import unidecode
import difflib

# Import Key Manager nếu cần dùng trong Restorer
from .key_manager import GeminiApiKeyManager

logger = logging.getLogger(__name__)

class SimpleVietnameseRestorer:
    def __init__(self, key_manager):
        self.key_manager = key_manager
        self.model_name = "gemini-2.5-flash"
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        self.cache = {}
        self.max_cache_size = 500
        logger.info("✅ SimpleVietnameseRestorer initialized.")
    
    def has_vietnamese_accents(self, text: str) -> bool:
        vietnamese_chars = 'àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ'
        vietnamese_chars += vietnamese_chars.upper()
        return any(char in vietnamese_chars for char in text)
    
    def restore_vietnamese_tone(self, input_text: str, retry_count=0) -> str:
        if not input_text or not input_text.strip():
            return input_text
        
        input_text = input_text.strip()
        cache_key = input_text.lower()
        
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        if self.has_vietnamese_accents(input_text):
            self.cache[cache_key] = input_text
            return input_text

        api_key_to_use = self.key_manager.get_key()
        if not api_key_to_use:
            logger.error("Tone Restorer: All keys are rate-limited. Skipping.")
            return input_text

        prompt = f'Hãy viết lại câu sau thành tiếng Việt có dấu đầy đủ, không thay đổi ý nghĩa: "{input_text}"'
        
        try:
            headers = {'Content-Type': 'application/json'}
            data = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 100}
            }
            
            url = f"{self.base_url}?key={api_key_to_use}"
            response = requests.post(url, headers=headers, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates']:
                    candidate = result['candidates'][0]
                    if 'content' in candidate and 'parts' in candidate['content']:
                        restored_text = candidate['content']['parts'][0]['text'].strip()
                        # Clean up quotes/prefixes
                        restored_text = re.sub(r'^["\'](.*)["\']$', r'\1', restored_text)
                        restored_text = re.sub(r'^(Câu đã có dấu:|Kết quả:|Trả lời:)\s*', '', restored_text, flags=re.IGNORECASE)
                        
                        if self._is_valid_restoration(input_text, restored_text):
                            self._cache_result(cache_key, restored_text)
                            return restored_text
            
            elif response.status_code == 429:
                self.key_manager.report_failure(api_key_to_use)
                if retry_count == 0:
                    return self.restore_vietnamese_tone(input_text, retry_count=1)
                
        except Exception as e:
            logger.error(f"❌ Error restoring tone: {e}")
        
        return input_text
    
    def _is_valid_restoration(self, original: str, restored: str) -> bool:
        if not restored: return False
        if abs(len(restored) - len(original)) > len(original) * 0.5: return False
        
        original_no_accent = unidecode(original).lower()
        restored_no_accent = unidecode(restored).lower()
        
        similarity = difflib.SequenceMatcher(None, original_no_accent, restored_no_accent).ratio()
        return similarity >= 0.8
    
    def _cache_result(self, key: str, result: str):
        self.cache[key] = result
        if len(self.cache) > self.max_cache_size:
            keys_to_remove = list(self.cache.keys())[:int(self.max_cache_size * 0.2)]
            for k in keys_to_remove:
                del self.cache[k]

def build_personalized_system_prompt(user_memory_prompt: str = None, personal_address: str = "giảng viên"):
    # ✅ FIX: Sửa lại Prompt để tránh lặp từ "Thầy Tuấn Thầy Tuấn"
    base_prompt = f"""Bạn là ChatBDU, một trợ lý AI chuyên nghiệp và tận tâm của Đại học Bình Dương (BDU). Sứ mệnh của bạn là hỗ trợ các giảng viên của trường một cách hiệu quả nhất.

🎯 QUY TẮC NỀN TẢNG (CÓ THỂ BỊ GHI ĐÈ BỞI CHỈ DẪN RIÊNG):
1.  **Xưng hô:** Bắt đầu câu trả lời bằng "Dạ {personal_address}," và xưng là "em".
2.  **Kết thúc:** Kết thúc bằng một lời đề nghị hỗ trợ ngắn gọn và lịch sự (ví dụ: "Em có thể hỗ trợ thêm gì không ạ?"). **Tuyệt đối không lặp lại tên/danh xưng ở cuối câu nếu không cần thiết.**
3.  **Văn phong:** Tự nhiên, mạch lạc, không lặp từ.
4.  **Tính chính xác:** Không được bịa đặt thông tin. Nếu không biết, hãy trả lời là "Dạ em chưa có thông tin về vấn đề này." và gợi ý kênh liên hệ khác.
5.  **Phạm vi:** Chỉ trả lời các câu hỏi liên quan đến công việc, quy định, thông báo và các hoạt động tại Đại học Bình Dương.
"""
    if user_memory_prompt and user_memory_prompt.strip():
        base_prompt += f"""
---
📜 GHI NHỚ VÀ CHỈ DẪN RIÊNG TỪ GIẢNG VIÊN:
{user_memory_prompt.strip()}
---
"""
    return base_prompt