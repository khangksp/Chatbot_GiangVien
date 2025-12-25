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

PERSONAL_PRONOUNS = {
    'default': {
        'user': ['bạn', 'cậu', '{first_name}'],
        'bot': ['mình', 'tớ']
    },
    'casual': {
        'user': ['cậu', '{first_name}'],
        'bot': ['tớ', 'mình']
    },
    'friendly': {
        'user': ['bạn', 'cậu', '{first_name}'],
        'bot': ['mình', 'tớ']
    }
}
def build_personalized_system_prompt(user_memory_prompt: str = None, user_address: List[str] = None, 
                                     bot_pronoun: List[str] = None, profile: Optional[Dict[str, Any]] = None):
    if user_address is None:
        user_address = PERSONAL_PRONOUNS['default']['user']
    if bot_pronoun is None:
        bot_pronoun = PERSONAL_PRONOUNS['default']['bot']

    base_prompt = f"""Bạn là ChatBDU, một trợ lý AI thân thiện và hữu ích của Đại học Bình Dương (BDU). Sứ mệnh của bạn là hỗ trợ các sinh viên của trường một cách hiệu quả nhất.
🎯 QUY TẮC NỀN TẢNG:
1. Xưng hô cá nhân: Xưng hô với người dùng là "{user_address}" và tự xưng là "{bot_pronoun}". Hãy linh hoạt và tự nhiên.
2. Chào hỏi: Chỉ chào hỏi ở lượt đầu tiên hoặc khi phù hợp. Không lặp lại.

"""

    profile_section = ""
    if profile:
        name = profile.get('full_name', '')
        mssv = profile.get('mssv', '')
        lop = profile.get('class_name', '')
        khoa = profile.get('faculty', '')
        name_parts = name.split() if name else []
        display_name = name_parts[-1] if name_parts else name
        
        profile_section = f"""
---
👤 THÔNG TIN SINH VIÊN (DÙNG ĐỂ TRẢ LỜI CÁ NHÂN):
- Tên đầy đủ: {name}
- MSSV: {mssv}
- Lớp: {lop}
- Khoa: {khoa}
💡 LƯU Ý: 
- Với query như 'tôi là ai' hoặc 'lớp nào', dùng info này trực tiếp. Không nói 'không biết' hoặc bịa data.
- Khi xưng hô với sinh viên, sử dụng tên riêng '{display_name}' thay vì họ. VD: "Chào {display_name}!" chứ không dùng "Chào Lê!".
---
        """
        logger.info(f"👤 Profile section added to prompt: {name}")

    return base_prompt + profile_section + "Trả lời tự nhiên, ngắn gọn, không lặp từ 'AI assistant'."

