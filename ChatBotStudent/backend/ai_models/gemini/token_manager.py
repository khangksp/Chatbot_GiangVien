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

logger = logging.getLogger(__name__)

class SmartTokenManager:    
    def __init__(self):
        self.adaptive_token_range = {
            'min': 80, 
            'optimal': 250, 
            'max': 2026,
            'expected_sentences': 3, 
            'avg_chars_per_sentence': 80
        }
        self.incomplete_patterns = [
            r'[^.!?]\s*$',
            r'\b(và|hoặc|với|để|khi|nếu|tại|về|cho|trong|của|từ)\s*$',
            r'\b(em|sẽ|có|được|phải|cần|nên)\s*$',
            r'[,;:]\s*$',
            r'\b(Dạ|Ạ|thầy|cô|sinh viên)\s*$',
        ]
        self.complete_endings = [
            r'[.!?]\s*$',
            r'ạ[.!?]\s*$',
            r'không\?\s*$',
            r'🎓\s*$',
            r'@bdu\.edu\.vn\s*$',
        ]
        logger.info("✅ SmartTokenManager initialized with adaptive token range")
    def calculate_optimal_tokens(self, prompt_length: int, complexity_hint: str = None, data_type: str = 'general') -> int:
        """
        Tính toán số lượng token tối ưu, có xét đến loại dữ liệu.
        """
        base_tokens = self.adaptive_token_range['optimal']
        if prompt_length > 1000: # Tăng ngưỡng kiểm tra prompt dài
            base_tokens += 100
        elif prompt_length < 300: # Tăng ngưỡng kiểm tra prompt ngắn
            base_tokens -= 50
        if complexity_hint:
            if complexity_hint in ['enhanced_generation', 'detailed_explanation', 'document_context', 'two_stage_reranking']:
                base_tokens += 1500 # Giữ nguyên mức tăng lớn
            elif complexity_hint in ['quick_clarify', 'simple_answer']:
                base_tokens -= 40
        if data_type == "tuition":
            boost = 1200 # Tăng thêm 1200 token cho học phí
            base_tokens += boost
            logger.info(f"🧠 SMART TOKENS: Applied +{boost} token boost for tuition data.")
        elif data_type == "schedule":
             boost = 500 # Tăng nhẹ 500 token cho lịch học
             base_tokens += boost
             logger.info(f"🧠 SMART TOKENS: Applied +{boost} token boost for schedule data.")
        min_tokens = self.adaptive_token_range['min']
        max_tokens = self.adaptive_token_range['max']
        calculated_tokens = max(min_tokens, min(max_tokens, base_tokens))
        logger.info(f"🧠 SMART TOKENS calculated: {calculated_tokens} (prompt_len: {prompt_length}, base: {base_tokens}, hint: {complexity_hint}, data_type: {data_type})")
        return calculated_tokens
    def is_response_incomplete(self, response: str) -> Dict[str, Any]:        
        if not response or not response.strip():
            return {'incomplete': True, 'reason': 'empty_response', 'confidence': 1.0}
        response = response.strip()
        for pattern in self.incomplete_patterns:
            if re.search(pattern, response):
                return {
                    'incomplete': True, 
                    'reason': 'incomplete_pattern',
                    'pattern': pattern,
                    'confidence': 0.8
                }
        expected_sentences = self.adaptive_token_range['expected_sentences']
        actual_sentences = len(re.findall(r'[.!?]+', response))
        if actual_sentences < expected_sentences * 0.7:
            return {
                'incomplete': True,
                'reason': 'insufficient_sentences',
                'expected': expected_sentences,
                'actual': actual_sentences,
                'confidence': 0.7
            }
        soft_endings = r'([.!?])\s*$'
        if not re.search(soft_endings, response):
            return {
                'incomplete': True,
                'reason': 'missing_sentence_ending',
                'confidence': 0.4
            }
        return {'incomplete': False, 'reason': 'complete', 'confidence': 0.9}
    def estimate_completion_tokens(self, incomplete_response: str) -> int:        
        current_tokens = len(incomplete_response) // 3
        target_tokens = self.adaptive_token_range['optimal']
        additional_needed = max(20, target_tokens - current_tokens)
        return min(additional_needed, 150)
