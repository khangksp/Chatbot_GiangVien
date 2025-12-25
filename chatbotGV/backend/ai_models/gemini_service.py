import logging
# Import từ package mới - BẮT BUỘC để dùng logic mới đã fix lỗi
from .gemini.core import GeminiResponseGenerator
from .gemini.utils import SimpleVietnameseRestorer, build_personalized_system_prompt
from .ner_service import SimpleEntityExtractor 

logger = logging.getLogger(__name__)

# Khởi tạo instance global từ class mới
gemini_response_generator = GeminiResponseGenerator()

logger.info("🚀 Gemini Service Facade loaded successfully pointing to modular structure.")