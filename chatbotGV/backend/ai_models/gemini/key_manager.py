import os
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

class GeminiApiKeyManager:
    def __init__(self):
        self.keys = []
        self._load_keys_from_env()
        self.current_key_index = 0
        self.key_status = {k: {'is_rate_limited': False, 'limited_until': 0} for k in self.keys}
        if not self.keys:
            logger.error("CRITICAL: No Gemini API keys found in .env file (e.g., GEMINI_API_KEY, GEMINI_API_KEY2)!")
        else:
            logger.info(f"✅ GeminiApiKeyManager initialized with {len(self.keys)} keys.")

    def _load_keys_from_env(self):
        """Tự động tải các key từ file .env, không yêu cầu thứ tự liên tục."""
        # Tải key chính (không có số)
        main_key = os.getenv('GEMINI_API_KEY')
        if main_key:
            self.keys.append(main_key)

        # Quét các key có số thứ tự (ví dụ: từ 2 đến 20)
        # Vòng lặp này sẽ kiểm tra từng key một, kể cả khi có key bị thiếu ở giữa
        for i in range(2, 21):  # Quét từ GEMINI_API_KEY2 đến GEMINI_API_KEY20
            extra_key = os.getenv(f'GEMINI_API_KEY{i}')
            if extra_key:
                self.keys.append(extra_key)
    
    def get_key(self) -> Optional[str]:
        """Lấy một API key hợp lệ để sử dụng (xoay vòng)."""
        if not self.keys:
            return None
            
        start_index = self.current_key_index
        for i in range(len(self.keys)):
            index = (start_index + i) % len(self.keys)
            key = self.keys[index]
            status = self.key_status[key]
            
            if status['is_rate_limited'] and time.time() > status['limited_until']:
                status['is_rate_limited'] = False
                logger.info(f"🔑 API Key '{key[:4]}...{key[-4:]}' is now available again.")

            if not status['is_rate_limited']:
                self.current_key_index = (index + 1) % len(self.keys)
                logger.info(f"🔑 Using API Key #{index + 1} ('{key[:4]}...{key[-4:]}')")
                return key
                
        logger.warning("⚠️ All Gemini API keys are currently rate-limited.")
        return None

    def report_failure(self, key: str):
        """Báo cáo một key đã bị lỗi 429 (rate limit)."""
        if key in self.key_status:
            self.key_status[key]['is_rate_limited'] = True
            self.key_status[key]['limited_until'] = time.time() + 61 
            logger.warning(f"RATE LIMIT: Key '{key[:4]}...{key[-4:]}' is now rate-limited for 61 seconds.")