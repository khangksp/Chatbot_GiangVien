import logging
import time
import requests
import re
import random
import json
from typing import Dict, Any, Optional, List
from unidecode import unidecode
import difflib
import pandas as pd
import os
from ..ner_service import SimpleEntityExtractor
from bs4 import BeautifulSoup
from .key_manager import GeminiApiKeyManager

logger = logging.getLogger(__name__)

class SimpleVietnameseRestorer:
    def __init__(self, key_manager: GeminiApiKeyManager):
        self.key_manager = key_manager
        self.model_name = "gemini-2.5-flash"
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        self.cache = {}
        self.max_cache_size = 500
        logger.info("✅ SimpleVietnameseRestorer initialized with Key Manager.")
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
            logger.debug(f"🎯 Tone-restorer cache hit for: '{input_text}'")
            return self.cache[cache_key]
        if self.has_vietnamese_accents(input_text):
            self.cache[cache_key] = input_text
            return input_text
        api_key_to_use = self.key_manager.get_key()
        if not api_key_to_use:
            logger.error("Tone Restorer: All keys are rate-limited. Skipping restoration.")
            self._cache_result(cache_key, input_text)
            return input_text
        prompt = f'Hãy viết lại câu sau thành tiếng Việt có dấu đầy đủ, không thay đổi ý nghĩa: "{input_text}"'
        try:
            headers = {'Content-Type': 'application/json'}
            data = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 100, "topP": 0.8}
            }
            url = f"{self.base_url}?key={api_key_to_use}"
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates']:
                    candidate = result['candidates'][0]
                    if 'content' in candidate and 'parts' in candidate['content']:
                        restored_text = candidate['content']['parts'][0]['text'].strip()
                        restored_text = re.sub(r'^["\'](.*)["\']$', r'\1', restored_text)
                        restored_text = re.sub(r'^(Câu đã có dấu:|Kết quả:|Trả lời:)\s*', '', restored_text, flags=re.IGNORECASE)
                        
                        if self._is_valid_restoration(input_text, restored_text):
                            logger.info(f"✅ Restored: '{input_text}' -> '{restored_text}'")
                            self._cache_result(cache_key, restored_text)
                            return restored_text
                        else:
                            logger.warning(f"⚠️ Invalid restoration: '{restored_text}'")
            elif response.status_code == 429:
                self.key_manager.report_failure(api_key_to_use)
                if retry_count == 0:
                    logger.warning("Tone Restorer: Rate limit hit, retrying with new key...")
                    return self.restore_vietnamese_tone(input_text, retry_count=1)
            else:
                logger.error(f"❌ Gemini API Error {response.status_code} for tone restorer")
        except Exception as e:
            logger.error(f"❌ Error restoring tone: {e}")
        self._cache_result(cache_key, input_text)
        return input_text
    def _is_valid_restoration(self, original: str, restored: str) -> bool:
        if not restored or len(restored.strip()) == 0:
            return False
        if abs(len(restored) - len(original)) > len(original) * 0.5:
            return False
        original_no_accent = unidecode(original).lower()
        restored_no_accent = unidecode(restored).lower()
        similarity = difflib.SequenceMatcher(None, original_no_accent, restored_no_accent).ratio()
        return similarity >= 0.8
    def _cache_result(self, key: str, result: str):
        self.cache[key] = result
        if len(self.cache) > self.max_cache_size:
            items_to_remove = len(self.cache) // 5
            keys_to_remove = list(self.cache.keys())[:items_to_remove]
            for k in keys_to_remove:
                del self.cache[k]