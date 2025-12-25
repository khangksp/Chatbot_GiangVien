import logging
import time
import requests
import json
import re
import os
from typing import Dict, Any, List, Optional

# Import các module con vừa tách
from .key_manager import GeminiApiKeyManager
from .token_manager import SmartTokenManager
from .confidence_manager import AdvancedConfidenceManager
from .memory import ConversationMemory
from .utils import SimpleVietnameseRestorer, build_personalized_system_prompt

# ⚠️ LƯU Ý: Import ner_service dùng 2 dấu chấm (..) vì nó nằm ở thư mục cha
try:
    from ..ner_service import SimpleEntityExtractor
except ImportError:
    # Fallback nếu chạy test độc lập
    import sys
    sys.path.append("..") 
    from ner_service import SimpleEntityExtractor

logger = logging.getLogger(__name__)

class GeminiResponseGenerator:    
    def __init__(self):
        self.key_manager = GeminiApiKeyManager()
        self.model_name = "gemini-2.5-flash" 
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        self.memory = ConversationMemory(max_history=30)
        self.vietnamese_restorer = SimpleVietnameseRestorer(self.key_manager)
        
        self.token_manager = SmartTokenManager()
        self.confidence_manager = AdvancedConfidenceManager()
        self._user_context_cache = {}
        
        self.default_generation_config = {
            "temperature": 0.4,
            "topP": 0.85
        }
        
        self.role_consistency_rules = {
            'identity': 'AI assistant của Đại học Bình Dương (BDU) hỗ trợ giảng viên',
            'personality': 'lịch sự, chuyên nghiệp, tôn trọng',
            'knowledge_scope': 'chuyên về thông tin BDU và hỗ trợ giảng viên',
            'addressing': 'luôn xưng hô đúng cách, không bao giờ dùng bạn/mình',
            'prohibited_roles': [
                'sinh viên', 'học sinh', 'phụ huynh', 'người ngoài trường'
            ]
        }
        
        logger.info("✅ Enhanced Gemini Response Generator initialized with Advanced Confidence Management, Smart Token Management, và Two-Stage Re-ranking Integration")

    def _build_document_context_prompt(self, query: str, document_text: str, session_id: str = None) -> str:
        system_prompt = self._get_personalized_system_prompt(session_id)
        personal_address = self._get_personal_address(session_id)
        
        conversation_context = self.memory.get_conversation_context(session_id) if session_id else {}
        recent_summary = conversation_context.get('recent_conversation_summary', '')
        
        context_section = ""
        if recent_summary:
            context_section = f"""
🗣️ NGỮ CẢNH HỘI THOẠI GẦN ĐÂY:
{recent_summary}

💡 LƯU Ý: Hãy tham khảo ngữ cảnh trên để tạo câu trả lời mạch lạc, tránh lặp lại thông tin đã thảo luận.
"""
        
        # Truncate document text if too long (keep within token limits)
        max_doc_length = 3000  # characters
        if len(document_text) > max_doc_length:
            document_text = document_text[:max_doc_length] + "\n\n[...tài liệu còn tiếp...]"
        
        # ⭐ NHIỆM VỤ 2: Thêm khối chỉ dẫn đặc biệt cho việc xử lý dữ liệu OCR "bẩn"
        ocr_guidance = """---
⭐ HƯỚNG DẪN XỬ LÝ DỮ LIỆU OCR ĐẶC BIỆT (Rất quan trọng)
Dữ liệu dưới đây được trích xuất tự động từ file PDF/DOCX, do đó có thể chứa các lỗi định dạng, đặc biệt là các bảng (table) bị chuyển thành văn bản thuần túy.
1.  **Xử lý bảng (Table):** Một dòng văn bản có thể chứa nhiều thông tin liên quan (ví dụ: số thứ tự, họ tên, chức vụ, nhiệm vụ). BẠN PHẢI TỰ SUY LUẬN để liên kết các thông tin có vẻ nằm trên cùng một hàng với nhau. Ví dụ: dòng "1 Bà A Chức vụ B Nhiệm vụ C" có nghĩa là Bà A có chức vụ B và nhiệm vụ C.
2.  **Đếm số lượng:** Nếu được hỏi "có mấy điều", "có bao nhiêu thành viên", hãy tìm và đếm số lần xuất hiện của các từ khóa như "Điều 1.", "Điều 2.", hoặc các số thứ tự trong danh sách (1, 2, 3...).
3.  **Tìm kiếm chính xác:** Hãy đọc thật kỹ và tìm kiếm chính xác các từ khóa trong câu hỏi của người dùng trong toàn bộ văn bản, ngay cả khi nó không có cấu trúc.
---"""

        prompt = f"""{system_prompt}

🎯 NHIỆM VỤ ĐẶC BIỆT: Trả lời câu hỏi dựa trên nội dung tài liệu được cung cấp

{ocr_guidance}

📄 NỘI DUNG TÀI LIỆU:
{document_text}

{context_section}

❓ CÂU HỎI CỦA GIẢNG VIÊN: {query}

📝 YÊU CẦU TRẢ LỜI QUAN TRỌNG:
- Xưng hô: "Dạ {personal_address},"
- CHỈ TRẢ LỜI DỰA VÀO nội dung tài liệu được cung cấp ở trên
- KHÔNG SỬ DỤNG kiến thức bên ngoài tài liệu
- Nếu tài liệu không chứa thông tin để trả lời câu hỏi, hãy nói rõ điều đó
- Trích dẫn cụ thể từ tài liệu khi có thể
- Tạo câu trả lời rõ ràng, dễ hiểu và mạch lạc
- Kết thúc: "{personal_address.title()} có cần em hỗ trợ thêm gì không ạ?"
- TUYỆT ĐỐI KHÔNG bịa đặt thông tin không có trong tài liệu

Trả lời:"""

        return prompt

    def _generate_external_api_response(self, query, context, session_id=None):        
        api_data = context.get('api_data', {})
        lecturer_info = api_data.get('lecturer_info', {})
        schedule_summary = api_data.get('schedule_summary', {})
        daily_schedule = api_data.get('daily_schedule', {})
        personal_address = self._get_personal_address_from_api_data(lecturer_info, session_id)
        conversation_context = self.memory.get_conversation_context(session_id) if session_id else {}
        recent_summary = conversation_context.get('recent_conversation_summary', '')
        prompt = self._build_external_api_prompt(
            query, api_data, personal_address, recent_summary
        )
        optimal_tokens = self.token_manager.calculate_optimal_tokens(
            len(prompt), 
            'external_api_processing'
        )
        logger.info(f"🌐 Processing external API data with {optimal_tokens} tokens")
        response = self._call_gemini_api_with_smart_tokens(
            prompt, 'external_api_processing', optimal_tokens, session_id
        )
        
        if not response:
            return self._get_external_api_fallback_response(api_data, personal_address)
        response = self._post_process_external_api_response(
            response, lecturer_info, query, session_id
        )
        return response
    
    def _build_external_api_prompt(self, query, api_data, personal_address, recent_summary=""):        
        lecturer_info = api_data.get('lecturer_info', {})
        schedule_summary = api_data.get('schedule_summary', {})
        daily_schedule = api_data.get('daily_schedule', {})
        query_context = api_data.get('query_context', '')
        
        ten_giang_vien = lecturer_info.get('ten_giang_vien', personal_address)
        ma_giang_vien = lecturer_info.get('ma_giang_vien', '')
        chuc_danh = lecturer_info.get('chuc_danh', '')
        gmail = lecturer_info.get('gmail', '')
        trinh_do = lecturer_info.get('trinh_do', '')
        
        total_classes = schedule_summary.get('total_classes', 0)
        unique_subjects = schedule_summary.get('unique_subjects', 0)
        total_periods = schedule_summary.get('total_periods', 0)
        
        schedule_text = self._format_schedule_for_prompt(daily_schedule)
        system_prompt = self._get_personalized_system_prompt_for_external_api(
            lecturer_info
        )
        
        context_section = ""
        if recent_summary:
            context_section = f"""
🗣️ NGỮ CẢNH HỘI THOẠI GẦN ĐÂY:
{recent_summary}

💡 LƯU Ý: Hãy tham khảo ngữ cảnh trên để tạo câu trả lời mạch lạc, tránh lặp lại thông tin đã nói.
"""
        
        prompt = f"""{system_prompt}

🎯 NHIỆM VỤ ĐẶC BIỆT: Xử lý thông tin CÁ NHÂN từ hệ thống của trường

📋 THÔNG TIN GIẢNG VIÊN:
- Mã giảng viên: {ma_giang_vien}
- Họ và tên: {ten_giang_vien}
- Chức danh: {chuc_danh}
- Trình độ: {trinh_do}
- Email: {gmail}

📅 TỔNG QUAN LỊCH GIẢNG DẠY:
- Tổng số buổi học: {total_classes}
- Số môn học: {unique_subjects}
- Tổng số tiết: {total_periods}

📖 CHI TIẾT LỊCH GIẢNG DẠY:
{schedule_text}

{context_section}

❓ CÂU HỎI CỦA GIẢNG VIÊN: {query}
🔍 NGỮ CẢNH TÌM KIẾM: {query_context}

📝 YÊU CẦU TRẢ LỜI:
- Xưng hô: "Dạ {personal_address},"
- Trả lời CHÍNH XÁC dựa trên dữ liệu thực tế từ hệ thống
- Tạo câu trả lời mạch lạc, tránh lặp lại thông tin đã thảo luận
- Định dạng thông tin dễ đọc, rõ ràng
- Bao gồm các chi tiết quan trọng: thời gian, địa điểm, môn học
- Kết thúc: "{personal_address.title()} có cần em hỗ trợ thêm gì không ạ?"
- KHÔNG CHẾ TẠO thông tin không có trong dữ liệu

Trả lời:"""
        return prompt
    
    def _format_schedule_for_prompt(self, daily_schedule):
        if not daily_schedule:
            return "Hiện tại không có lịch giảng dạy trong khoảng thời gian này."
        
        formatted_lines = []
        sorted_dates = sorted(daily_schedule.keys())
        
        for date_str in sorted_dates:
            classes = daily_schedule[date_str]
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date_str, '%d-%m-%Y')
                weekdays = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật']
                weekday = weekdays[date_obj.weekday()]
                formatted_date = f"{weekday}, {date_str}"
            except:
                formatted_date = date_str
            
            formatted_lines.append(f"\n📅 {formatted_date}:")
            sorted_classes = sorted(classes, key=lambda x: x.get('tiet_bat_dau', 0))
            
            for class_info in sorted_classes:
                ma_mon_hoc = class_info.get('ma_mon_hoc', '')
                ten_mon_hoc = class_info.get('ten_mon_hoc', '')
                ma_lop = class_info.get('ma_lop', '')
                ma_phong = class_info.get('ma_phong', '')
                tiet_bat_dau = class_info.get('tiet_bat_dau', '')
                so_tiet = class_info.get('so_tiet', '')
                so_luong_sv = class_info.get('so_luong_sv', '')
 
                class_line = f"   • {ten_mon_hoc} ({ma_mon_hoc})"
                class_line += f" - Lớp {ma_lop}"
                class_line += f" - Phòng {ma_phong}"
                class_line += f" - Tiết {tiet_bat_dau}"
                if so_tiet:
                    class_line += f" ({so_tiet} tiết)"
                if so_luong_sv:
                    class_line += f" - {so_luong_sv} SV"
                
                formatted_lines.append(class_line)
        
        return '\n'.join(formatted_lines) if formatted_lines else "Không có lịch giảng dạy."

    def _get_personalized_system_prompt_for_external_api(self, lecturer_info):        
        ten_giang_vien = lecturer_info.get('ten_giang_vien', '')
        gender = lecturer_info.get('gender', 'other')
        chuc_danh = lecturer_info.get('chuc_danh', '')
        
        if gender == 'male':
            salutation = 'thầy'
        elif gender == 'female':
            salutation = 'cô'
        else:
            salutation = 'giảng viên'
        
        name_parts = ten_giang_vien.split() if ten_giang_vien else []
        name_suffix = name_parts[-1] if name_parts else ''
        
        if salutation in ['thầy', 'cô']:
            personal_address = f"{salutation} {name_suffix}" if name_suffix else salutation
        else:
            personal_address = f"{salutation} {ten_giang_vien}" if ten_giang_vien else salutation
        
        base_prompt = f"""Bạn là AI assistant của Đại học Bình Dương (BDU), chuyên hỗ trợ giảng viên.

🎯 THÔNG TIN NGƯỜI DÙNG:
- Bạn đang trả lời cho {chuc_danh} {ten_giang_vien}
- Xưng hô: "{personal_address}" (TUYỆT ĐỐI KHÔNG dùng "bạn", "mình", "anh/chị")
- Đây là thông tin CÁ NHÂN từ hệ thống chính thức của trường

🎯 QUY TẮC QUAN TRỌNG:
- LUÔN bắt đầu: "Dạ {personal_address},"
- Kết thúc: "{personal_address.title()} có cần em hỗ trợ thêm gì không ạ?"
- SỬ DỤNG CHÍNH XÁC thông tin từ hệ thống - KHÔNG CHẾ TẠO
- Trình bày thông tin cá nhân một cách tự nhiên, dễ hiểu
- KHÔNG dùng format phức tạp với **1. **2. hay bullets khi không cần thiết"""

        return base_prompt

    def _get_personal_address_from_api_data(self, lecturer_info, session_id):
        ten_giang_vien = lecturer_info.get('ten_giang_vien', '')
        gender = lecturer_info.get('gender', 'other')
        
        if gender == 'male':
            salutation = 'thầy'
        elif gender == 'female':
            salutation = 'cô'
        else:
            salutation = 'giảng viên'
        
        if ten_giang_vien:
            if salutation in ['thầy', 'cô']:
                name_suffix = ten_giang_vien.split()[-1]
                return f"{salutation} {name_suffix}"
            else:
                return f"{salutation} {ten_giang_vien}"
        
        return self._get_personal_address(session_id)

    def _post_process_external_api_response(self, response, lecturer_info, query, session_id):
        if not response:
            return response
        ten_giang_vien = lecturer_info.get('ten_giang_vien', '')
        gender = lecturer_info.get('gender', 'other')
        
        if gender == 'male':
            salutation = 'thầy'
        elif gender == 'female':
            salutation = 'cô'
        else:
            salutation = 'giảng viên'
        
        if ten_giang_vien:
            if salutation in ['thầy', 'cô']:
                name_suffix = ten_giang_vien.split()[-1]
                personal_address = f"{salutation} {name_suffix}"
            else:
                personal_address = f"{salutation} {ten_giang_vien}"
        else:
            personal_address = salutation
        
        # 👇 FIX: Xử lý lỗi xưng hô "em là giảng viên" do Ollama dùng từ "tôi/mình"
        # Bắt các cụm từ như: "em là giảng viên", "tôi là giảng viên", "mình là giảng viên"
        # Đổi thành: "thầy Tuấn là giảng viên"
        response = re.sub(
            r'\b(em|tôi|mình)\s+(là|được ghi nhận là)\s+(một\s+)?(giảng viên|cán bộ|trưởng|phó|người)', 
            f'{personal_address} \\2 \\3\\4', 
            response, 
            flags=re.IGNORECASE
        )

        # Sau đó mới chạy các replacement đại từ chung
        response = re.sub(r'\bbạn\b', personal_address, response, flags=re.IGNORECASE)
        response = re.sub(r'\bmình\b', 'em', response, flags=re.IGNORECASE)
        response = re.sub(r'\btôi\b', 'em', response, flags=re.IGNORECASE)
        
        response_stripped = response.strip()
        personalized_start = f"Dạ {personal_address},"
        
        if not response_stripped.lower().startswith(f'dạ {personal_address.lower()}'):
            if response_stripped.lower().startswith('dạ'):
                response = personalized_start + ' ' + response_stripped[3:].strip()
            else:
                response = personalized_start + ' ' + response_stripped
        
        if not response.strip().endswith('có cần hỗ trợ thêm gì không ạ?'):
            response = re.sub(r'\s*(có cần.*?không ạ\?|Cần.*?không\?|Có.*?không\?)?\s*$', '', response.strip())
            response += f' {personal_address.title()} có cần em hỗ trợ thêm gì không ạ?'
        
        # Clean up formatting artifacts
        response = re.sub(r'\*\*\d+\.\s*', '', response)
        response = re.sub(r'^\s*\d+\.\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'^\s*[•\-\*]\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'\*\*(.*?)\*\*', r'\1', response)
        
        return response.strip()

    def _get_external_api_fallback_response(self, api_data, personal_address):
        lecturer_info = api_data.get('lecturer_info', {})
        schedule_summary = api_data.get('schedule_summary', {})
        
        ten_giang_vien = lecturer_info.get('ten_giang_vien', personal_address)
        total_classes = schedule_summary.get('total_classes', 0)
        
        return f"""Dạ {personal_address}, em đã tìm thấy thông tin từ hệ thống của trường:

👤 Thông tin của {ten_giang_vien}:
- Mã giảng viên: {lecturer_info.get('ma_giang_vien', 'Không xác định')}
- Chức danh: {lecturer_info.get('chuc_danh', 'Không xác định')}
- Email: {lecturer_info.get('gmail', 'Không có')}

📅 Lịch giảng dạy: {total_classes} buổi học được lên lịch

Để xem chi tiết, {personal_address} có thể truy cập hệ thống quản lý đào tạo của trường ạ. 🎓

{personal_address.title()} có cần hỗ trợ thêm gì không ạ?"""

    def set_user_context(self, session_id: str, user_context: dict):
        
        print("\n" + "="*20 + " DEBUG: set_user_context " + "="*20)
        print(f"🕵️‍♂️ [set_user_context] Đang cài đặt context cho session: {session_id}")
        print(f"🕵️‍♂️ [set_user_context] Dữ liệu context nhận được: {user_context}")
        if 'gender' in user_context:
            print(f"✅ [set_user_context] TÌM THẤY 'gender' trong context: '{user_context['gender']}'")
        else:
            print(f"❌ [set_user_context] KHÔNG TÌM THẤY 'gender' trong context!")
        print("="*60 + "\n")
        
        self._user_context_cache[session_id] = user_context
        logger.info(f"✅ Set user context for session {session_id}: {user_context.get('faculty_code', 'Unknown')}")

    def _get_personalized_system_prompt(self, session_id: str = None):
        try:
            personal_address = self._get_personal_address(session_id)
            user_context = self._user_context_cache.get(session_id, {})
            user_memory_prompt = user_context.get('preferences', {}).get('user_memory_prompt', '')
            return build_personalized_system_prompt(user_memory_prompt, personal_address)
        except Exception as e:
            logger.error(f"Error getting personalized prompt: {e}")
            return build_personalized_system_prompt()  # Fallback

    def generate_response(self, query: str, context: Optional[Dict] = None, 
                          intent_info: Optional[Dict] = None, entities: Optional[Dict] = None,
                          session_id: str = None) -> Dict[str, Any]:
        start_time = time.time()
        print(f"\n--- 🚀 ADVANCED RAG GENERATION REQUEST (Session: {session_id}) ---")
        
        try:
            # 🔥 NEW: Xử lý các Mode đặc biệt (Chat Only / General Knowledge)
            mode = context.get('mode') if context else None
            
            if mode in ['chat_only', 'general_knowledge']:
                personal_address = self._get_personal_address(session_id)
                
                if mode == 'chat_only':
                    # Prompt cho Chit-chat
                    prompt = f"""
                    Bạn là ChatBDU, trợ lý ảo của Đại học Bình Dương.
                    Người dùng (xưng hô là {personal_address}) đang chào hỏi hoặc hỏi về bạn. 
                    Hãy trả lời thân thiện, tự nhiên, ngắn gọn và xưng là 'em'.
                    
                    Người dùng: {query}
                    """
                    strategy = 'chat_only'
                else:
                    # Prompt cho kiến thức chung (Fallback)
                    prompt = f"""
                    Bạn là ChatBDU. Câu hỏi này nằm ngoài dữ liệu nội bộ của trường.
                    Người dùng (xưng hô là {personal_address}) đang hỏi: "{query}"
                    
                    Hãy trả lời hữu ích dựa trên kiến thức chung của bạn. 
                    Nếu câu hỏi quá chuyên sâu, hãy khéo léo từ chối và đề nghị liên hệ trực tiếp nhà trường.
                    Xưng hô là 'em'.
                    """
                    strategy = 'general_knowledge'

                # Gọi API (Ollama/Gemini)
                response = self._call_gemini_api_with_smart_tokens(
                    prompt, strategy, max_tokens=1000, session_id=session_id
                )
                
                if not response:
                    response = f"Dạ {personal_address}, em đang gặp chút trục trặc. {personal_address.title()} nói lại được không ạ? 😓"

                # Lưu Memory
                if session_id:
                    self.memory.add_interaction(session_id, query, response, intent_info, entities)

                return {
                    'response': response,
                    'method': mode,
                    'strategy': strategy,
                    'confidence': 1.0 if mode == 'chat_only' else 0.5,
                    'generation_time': time.time() - start_time,
                    'original_query': query,
                    'personalized': True
                }

            # =================================================================
            # LOGIC CŨ (GIỮ NGUYÊN CHO RAG VÀ API XỬ LÝ)
            # =================================================================
            
            original_query = query
            instruction = context.get('instruction', '') if context else ''
            
            if instruction == 'answer_from_document':
                logger.info("📄 DOCUMENT CONTEXT: Processing document-based query")
                
                document_text = context.get('document_text', '')
                if not document_text or not document_text.strip():
                    logger.warning("⚠️ Empty document text provided")
                    personal_address = self._get_personal_address(session_id)
                    response_confidence = self.confidence_manager.normalize_confidence(0.1, "document_error")
                    return {
                        'response': f"Dạ {personal_address}, em không nhận được nội dung tài liệu để trả lời câu hỏi. {personal_address.title()} có thể gửi lại tài liệu không ạ? 🎓",
                        'method': 'document_context_empty',
                        'strategy': 'document_error',
                        'confidence': response_confidence, 
                        'generation_time': time.time() - start_time,
                        'original_query': original_query,
                        'restored_query': query,
                        'vietnamese_restoration_used': False,
                        'personalized': bool(session_id in self._user_context_cache),
                        'document_context_processed': True,
                        'token_info': {'smart_tokens_used': False, 'method': 'document_error'}
                    }
                prompt = self._build_document_context_prompt(query, document_text, session_id)
                optimal_tokens = self.token_manager.calculate_optimal_tokens(
                    len(prompt), 
                    'document_context'
                )
                logger.info(f"📄 Processing document context with {optimal_tokens} tokens")
                response = self._call_gemini_api_with_smart_tokens(
                    prompt, 'document_context', optimal_tokens, session_id
                )
                if not response:
                    personal_address = self._get_personal_address(session_id)
                    response = f"Dạ {personal_address}, em gặp khó khăn kỹ thuật khi phân tích tài liệu. {personal_address.title()} có thể thử lại hoặc đặt câu hỏi cụ thể hơn không ạ? 🎓"
                response_confidence = self.confidence_manager.calculate_response_confidence(
                    semantic_score=0.85,
                    keyword_score=0.0,
                    context_bonus=0.1,
                    method='document_context'
                )

                if session_id:
                    self.memory.add_interaction(session_id, original_query, response, intent_info, entities)

                return {
                    'response': response,
                    'method': 'document_context_processing',
                    'strategy': 'document_context',
                    'confidence': response_confidence,
                    'generation_time': time.time() - start_time,
                    'original_query': original_query,
                    'restored_query': query,
                    'vietnamese_restoration_used': False,
                    'personalized': bool(session_id in self._user_context_cache),
                    'document_context_processed': True,
                    'token_info': {
                        'smart_tokens_used': True,
                        'method': 'document_context_processing',
                        'optimal_tokens': optimal_tokens
                    }
                }
            
            if instruction == 'process_external_api_data':
                response = self._generate_external_api_response(query, context, session_id)
                response_confidence = self.confidence_manager.calculate_response_confidence(
                    semantic_score=0.9,
                    keyword_score=0.0,
                    context_bonus=0.15,
                    method='external_api'
                )
                token_info = {
                    'smart_tokens_used': True,
                    'method': 'external_api_processing'
                }
                if session_id:
                    self.memory.add_interaction(session_id, original_query, response, intent_info, entities)

                return {
                    'response': response,
                    'method': 'external_api_processing',
                    'strategy': 'external_api',
                    'confidence': response_confidence,
                    'generation_time': time.time() - start_time,
                    'original_query': original_query,
                    'restored_query': query,
                    'vietnamese_restoration_used': False,
                    'personalized': bool(session_id in self._user_context_cache),
                    'external_api_processed': True,
                    'token_info': token_info
                }

            conversation_context = {}
            if session_id:
                conversation_context = self.memory.get_conversation_context(session_id)
                print(f"🧠 MEMORY DEBUG: History length = {len(conversation_context.get('history', []))}")
                print(f"📝 CONTEXT SUMMARY: {conversation_context.get('recent_conversation_summary', 'None')}")

            user_context = None
            if session_id and session_id in self._user_context_cache:
                user_context = self._user_context_cache[session_id]
                print(f"👤 USER CONTEXT: {user_context.get('faculty_code', 'Unknown')}")

            response_strategy = self._determine_lecturer_response_strategy(
                query, context, intent_info, conversation_context
            )
            
            raw_confidence = context.get('confidence', 0.5) if context else 0.5
            normalized_confidence = self.confidence_manager.normalize_confidence(raw_confidence, "input_context")
            
            if context:
                context['confidence'] = normalized_confidence
            
            if instruction == 'direct_answer_lecturer':
                response, token_info = self._generate_direct_lecturer_answer_smart(query, context, session_id)
                final_confidence = normalized_confidence
            elif instruction in ['enhance_answer_lecturer', 'enhance_answer_lecturer_boosted']:
                response, token_info = self._generate_enhanced_lecturer_answer_smart(query, context, intent_info, entities, session_id)
                final_confidence = self.confidence_manager.normalize_confidence(normalized_confidence + 0.05, "enhanced_method")
            elif instruction == 'clarification_needed':
                response, token_info = self._generate_clarification_request_smart(query, context, session_id)
                final_confidence = self.confidence_manager.normalize_confidence(0.3, "clarification")
            elif instruction == 'dont_know_lecturer':
                response, token_info = self._generate_dont_know_response_smart(query, context, session_id)
                final_confidence = self.confidence_manager.normalize_confidence(0.1, "dont_know")
            else:
                # Default case for normal RAG
                if not self._is_lecturer_education_related(query) and not context.get('force_education_response', False):
                    response = self._get_contextual_out_of_scope_response_lecturer(conversation_context, session_id)
                    token_info = {'smart_tokens_used': False, 'method': 'predefined_template'}
                    final_confidence = self.confidence_manager.normalize_confidence(0.9, "out_of_scope")
                    if session_id:
                        self.memory.add_interaction(session_id, original_query, response, intent_info, entities)
                    return {
                        'response': response,
                        'method': 'out_of_scope_lecturer',
                        'confidence': final_confidence,
                        'generation_time': time.time() - start_time,
                        'original_query': original_query,
                        'restored_query': query,
                        'personalized': session_id in self._user_context_cache,
                        'token_info': token_info
                    }
                response, token_info = self._generate_smart_response(query, context, session_id, response_strategy)
                semantic_score = context.get('semantic_score', 0.5) if context else 0.5
                keyword_score = context.get('keyword_score', 0.0) if context else 0.0
                
                final_confidence = self.confidence_manager.calculate_response_confidence(
                    semantic_score=semantic_score,
                    keyword_score=keyword_score,
                    context_bonus=0.05 if conversation_context.get('recent_conversation_summary') else 0.0,
                    method='two_stage_reranking' if context and context.get('two_stage_reranking_used') else 'hybrid'
                )
            
            final_response = response or self._get_smart_fallback_with_context_lecturer(query, intent_info, conversation_context, session_id)
            if not 'final_confidence' in locals():
                final_confidence = self.confidence_manager.normalize_confidence(normalized_confidence, "final_response")
            
            if session_id:
                print(f"🧠 MEMORY DEBUG: Saving interaction to memory...")
                self.memory.add_interaction(session_id, original_query, final_response, intent_info, entities)
            
            return {
                'response': final_response,
                'method': f'advanced_rag_lecturer_aware_gemini_{response_strategy}',
                'strategy': response_strategy,
                'conversation_context': conversation_context,
                'confidence': final_confidence,
                'generation_time': time.time() - start_time,
                'original_query': original_query,
                'restored_query': query,
                'vietnamese_restoration_used': False,
                'personalized': bool(user_context),
                'enhanced_generation': response_strategy == 'enhanced_generation',
                'token_info': token_info,
                'confidence_management': {
                    'raw_confidence': raw_confidence,
                    'normalized_confidence': normalized_confidence,
                    'final_confidence': final_confidence,
                    'confidence_capped': final_confidence == 1.0,
                    'confidence_source': 'advanced_calculation'
                }
            }
        except Exception as e:
            logger.error(f"Gemini API error: {str(e)}")
            fallback_response = self._get_smart_fallback_with_context_lecturer(query, intent_info, conversation_context, session_id)
            error_confidence = self.confidence_manager.normalize_confidence(0.1, "error_fallback")
            if session_id:
                self.memory.add_interaction(session_id, original_query, fallback_response, intent_info, entities)
            return {
                'response': fallback_response,
                'method': 'lecturer_context_aware_fallback',
                'error': str(e),
                'confidence': error_confidence,
                'generation_time': time.time() - start_time,
                'original_query': original_query,
                'restored_query': query,
                'personalized': session_id in self._user_context_cache,
                'token_info': {'smart_tokens_used': False, 'method': 'fallback'}
            }
            
    def _generate_smart_response(self, query: str, context=None, session_id=None, strategy='balanced'):        
        prompt = self._build_enhanced_prompt(query, context, None, None, session_id)
        optimal_tokens = self.token_manager.calculate_optimal_tokens(
            len(prompt), 
            complexity_hint=strategy
        )
        
        print(f"🧠 SMART TOKENS: {optimal_tokens} tokens")
        response = self._call_gemini_api_with_smart_tokens(prompt, strategy, optimal_tokens, session_id)
        
        if not response:
            return self._get_smart_fallback_with_context_lecturer(query, None, {}, session_id), {
                'smart_tokens_used': True, 'method': 'fallback_after_api_failure', 'tokens_attempted': optimal_tokens
            }
        completion_check = self.token_manager.is_response_incomplete(response)
        if completion_check['incomplete']:
            print(f"⚠️ INCOMPLETE RESPONSE detected: {completion_check['reason']}")
            completed_response = self._auto_complete_response(response, query, context, session_id, completion_check)
            
            if completed_response and completed_response != response:
                response = completed_response
                completion_check['auto_completed'] = True
                print(f"✅ AUTO-COMPLETION successful")
            else:
                print(f"⚠️ AUTO-COMPLETION failed, using original")
        response = self._post_process_with_lecturer_consistency(response, query, context, strategy, {}, session_id)
        
        token_info = {
            'smart_tokens_used': True,
            'method': 'smart_generation',
            'optimal_tokens': optimal_tokens,
            'completion_check': completion_check,
            'strategy': strategy
        }
        
        return response, token_info

    def _auto_complete_response(self, incomplete_response: str, original_query: str, context, session_id: str, completion_info: Dict) -> Optional[str]:        
        if completion_info['confidence'] < 0.6:
            return None
        completion_tokens = self.token_manager.estimate_completion_tokens(incomplete_response)
        completion_prompt = self._build_completion_prompt(incomplete_response, original_query, context, session_id, completion_info)
        print(f"🔧 AUTO-COMPLETION: Attempting with {completion_tokens} tokens")
        completion = self._call_gemini_api_with_smart_tokens(completion_prompt, 'completion', completion_tokens, session_id)
        if completion:
            if completion_info['reason'] == 'missing_proper_ending':
                personal_address = self._get_personal_address(session_id)
                return incomplete_response.rstrip() + f' {personal_address.title()} có cần em hỗ trợ thêm gì không ạ?'
            elif completion_info['reason'] == 'missing_proper_greeting':
                personal_address = self._get_personal_address(session_id)
                return f"Dạ {personal_address}, " + incomplete_response.lstrip()
            else:
                merged = self._merge_incomplete_and_completion(incomplete_response, completion)
                return merged
        
        return None
    def _build_completion_prompt(self, incomplete_response: str, original_query: str, context, session_id: str, completion_info: Dict) -> str:        
        system_prompt = self._get_personalized_system_prompt(session_id)
        personal_address = self._get_personal_address(session_id)
        
        if completion_info['reason'] == 'incomplete_pattern':
            completion_prompt = f"""
            {system_prompt}
            
            NHIỆM VỤ: HOÀN THIỆN câu trả lời bị cắt
            
            CÂU HỎI GỐC: {original_query}
            
            CÂU TRẢ LỜI BỊ CẮT:
            {incomplete_response}
            
            YÊU CẦU:
            - TIẾP TỤC viết để hoàn thiện câu trả lời
            - Đảm bảo kết thúc: "{personal_address.title()} có cần em hỗ trợ thêm gì không ạ?"
            - CHỈ VIẾT PHẦN TIẾP THEO, không lặp lại phần đã có
            
            Tiếp tục:"""
        else:
            completion_prompt = f"""
            {system_prompt}
            
            NHIỆM VỤ: SỬA LỖI và hoàn thiện câu trả lời
            
            CÂU HỎI GỐC: {original_query}
            
            CÂU TRẢ LỜI CÓ VẤN ĐỀ:
            {incomplete_response}
            
            VẤN ĐỀ PHÁT HIỆN: {completion_info['reason']}
            
            YÊU CẦU:
            - SỬA LỖI và viết lại câu trả lời HOÀN CHỈNH
            - Bắt đầu: "Dạ {personal_address},"
            - Kết thúc: "{personal_address.title()} có cần em hỗ trợ thêm gì không ạ?"
            
            Câu trả lời hoàn chỉnh:"""
        
        return completion_prompt

    def _merge_incomplete_and_completion(self, incomplete: str, completion: str) -> str:
        completion = completion.strip()
        completion = re.sub(r'^(dạ\s+(thầy|cô|giảng viên),?\s*)', '', completion, flags=re.IGNORECASE)
        incomplete_words = incomplete.split()
        if incomplete_words:
            last_word = incomplete_words[-1].lower()
            if last_word in ['và', 'với', 'để', 'khi', 'nếu', 'tại', 'về', 'cho', 'trong', 'của', 'từ']:
                incomplete = ' '.join(incomplete_words[:-1])
        
        merged = incomplete.rstrip() + ' ' + completion.lstrip()
        return merged

    def _get_personal_address(self, session_id: str) -> str:
        # Debug Visuals
        logger.info("\n" + "="*20 + " DEBUG: _get_personal_address " + "="*20)
        logger.info(f"🕵️‍♂️ [_get_personal_address] Đang lấy xưng hô cho session: {session_id}")
        
        # Lấy context từ cache
        user_context = self._user_context_cache.get(session_id, {}) if session_id else {}
        logger.info(f"🕵️‍♂️ [_get_personal_address] Context đọc từ cache: {user_context}")

        full_name = user_context.get('full_name', '')
        raw_gender = user_context.get('gender', 'other')

        # Chuẩn hóa giới tính (xử lý cả trường hợp số 0, 1 hoặc chuỗi)
        gender = 'other'
        if str(raw_gender).lower() in ['male', 'nam', '0']:
            gender = 'male'
        elif str(raw_gender).lower() in ['female', 'nữ', '1']:
            gender = 'female'

        logger.info(f"🕵️‍♂️ [_get_personal_address] Giới tính gốc: '{raw_gender}' -> Đã chuẩn hóa: '{gender}'")
        
        # Logic xác định xưng hô
        salutation = ''
        if gender == 'male':
            salutation = 'thầy'
        elif gender == 'female':
            salutation = 'cô'
        
        # Trường hợp KHÔNG xác định được giới tính (other)
        if not salutation:
            if full_name:
                logger.info(f"✅ [_get_personal_address] -> Trả về tên đầy đủ (không rõ giới tính): '{full_name}'")
                logger.info("="*60 + "\n")
                return full_name
            else:
                logger.info(f"✅ [_get_personal_address] -> Trả về fallback: 'giảng viên'")
                logger.info("="*60 + "\n")
                return 'giảng viên'

        # Trường hợp CÓ giới tính (male/female)
        if full_name:
            # Lấy tên cuối (VD: Dương Anh Tuấn -> Tuấn)
            name_suffix = full_name.strip().split()[-1]
            address = f"{salutation} {name_suffix}"
            logger.info(f"✅ [_get_personal_address] -> Trả về xưng hô: '{address}'")
            logger.info("="*60 + "\n")
            return address
        
        # Có giới tính nhưng không có tên
        logger.info(f"✅ [_get_personal_address] -> Trả về xưng hô: '{salutation}'")
        logger.info("="*60 + "\n")
        return salutation

    def _call_gemini_api_with_smart_tokens(self, prompt: str, strategy: str, max_tokens: int, session_id: str = None, retry_count=0) -> Optional[str]:
        api_key_to_use = self.key_manager.get_key()
        if not api_key_to_use:
            if retry_count == 0:
                logger.warning("All keys are limited. Waiting 5 seconds before one last retry...")
                time.sleep(5)
                return self._call_gemini_api_with_smart_tokens(prompt, strategy, max_tokens, session_id, retry_count=1)
            else:
                logger.error("CRITICAL: All Gemini API keys are rate-limited. Aborting call.")
                personal_address = self._get_personal_address(session_id)
                return f"Dạ {personal_address}, hiện tại hệ thống đang quá tải, tất cả các kết nối đều đang bận. Vui lòng thử lại sau khoảng 1 phút nữa ạ. 😥"

        try:
            headers = {'Content-Type': 'application/json'}
            
            strategy_temp_adjustments = {
                'quick_clarify': -0.2, 'direct_enhance': 0.0, 'enhanced_generation': +0.2,
                'completion': -0.3, 'balanced': 0.0, 'document_context': +0.1,
                'two_stage_reranking': +0.05
            }
            temp_adjustment = strategy_temp_adjustments.get(strategy, 0.0)
            final_temperature = max(0.1, min(1.0, self.default_generation_config["temperature"] + temp_adjustment))
            
            config = {
                "temperature": final_temperature, "maxOutputTokens": max_tokens,
                "topP": self.default_generation_config["topP"]
            }
            
            data = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": config,
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                ]
            }
            
            url = f"{self.base_url}?key={api_key_to_use}"
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates']:
                    candidate = result['candidates'][0]
                    if 'finishReason' in candidate and candidate['finishReason'] == 'SAFETY':
                        logger.warning("🚨 Gemini response blocked due to SAFETY reasons.")
                        personal_address = self._get_personal_address(session_id)
                        return f"Dạ {personal_address}, em không thể trả lời câu hỏi này vì lý do an toàn và chính sách nội dung."
                    
                    if 'content' in candidate and 'parts' in candidate['content']:
                        return candidate['content']['parts'][0]['text']
            
            elif response.status_code == 429:
                self.key_manager.report_failure(api_key_to_use)
                if retry_count == 0:
                    logger.warning(f"Rate limit on key. Retrying immediately with a new key...")
                    return self._call_gemini_api_with_smart_tokens(prompt, strategy, max_tokens, session_id, retry_count=1)
                else:
                    logger.error("Rate limit hit on retry attempt as well. Aborting call.")
                    personal_address = self._get_personal_address(session_id)
                    return f"Dạ {personal_address}, hiện tại hệ thống đang quá tải. Vui lòng thử lại sau ít phút ạ."
            
            else:
                logger.error(f"Gemini API Error {response.status_code} with key '{api_key_to_use[:4]}...': {response.text}")
            
            return None
        
        except requests.exceptions.Timeout:
            logger.error("Gemini API call timed out.")
            personal_address = self._get_personal_address(session_id)
            return f"Dạ {personal_address}, yêu cầu xử lý mất quá nhiều thời gian và đã bị ngắt. {personal_address.title()} có thể thử lại với câu hỏi ngắn gọn hơn không ạ?"
        except Exception as e:
            logger.error(f"Smart Gemini API call failed: {str(e)}")
            return None

    def _generate_direct_lecturer_answer_smart(self, query, context, session_id=None):
        personal_address = self._get_personal_address(session_id)
        
        system_prompt = self._get_personalized_system_prompt(session_id)
        db_answer = context.get('db_answer', context.get('response', ''))
        db_answer = (db_answer[:3500] + '...') if len(db_answer) > 3500 else db_answer

        conversation_context = self.memory.get_conversation_context(session_id) if session_id else {}
        recent_summary = conversation_context.get('recent_conversation_summary', '')
        
        context_section = ""
        if recent_summary:
            context_section = f"""
🗣️ NGỮ CẢNH HỘI THOẠI GẦN ĐÂY:
{recent_summary}

💡 LƯU Ý: Tham khảo ngữ cảnh trên để tránh lặp lại thông tin, tạo câu trả lời mạch lạc.
"""
        prompt = f"""{system_prompt}

---
BỐI CẢNH VÀ NHIỆM VỤ

1.  **Kiến thức nền (từ CSDL):**
    "{db_answer}"

2.  **Câu hỏi của giảng viên:**
    "{query}"

{context_section}

3.  **YÊU CẦU CUỐI CÙNG (QUAN TRỌNG):**
    Nhiệm vụ chính của bạn bây giờ là **nhập vai một trợ lý AI** với các đặc điểm và quy tắc được giảng viên định nghĩa trong phần "GHI NHỚ RIÊNG".
    Hãy sử dụng "Kiến thức nền" để trả lời "Câu hỏi của giảng viên" trong khi vẫn duy trì đúng vai trò đó.
    Nếu "GHI NHỚ RIÊNG" trống, hãy trả lời một cách chuyên nghiệp, rõ ràng theo quy tắc mặc định.
    Tạo câu trả lời mạch lạc, tự nhiên, tránh lặp lại thông tin đã thảo luận.
---
Trả lời:
"""

        optimal_tokens = self.token_manager.calculate_optimal_tokens(len(prompt), 'direct_enhance')
        response = self._call_gemini_api_with_smart_tokens(prompt, 'direct_enhance', optimal_tokens, session_id)
        
        fallback = f"Dạ {personal_address}, {db_answer} 🎓 {personal_address.title()} có cần hỗ trợ thêm gì không ạ?"
        
        token_info = {
            'smart_tokens_used': True, 
            'method': 'direct_answer_smart_v6_advanced_confidence', 
            'optimal_tokens': optimal_tokens,
            'personal_addressing': personal_address,
            'context_aware': bool(recent_summary),
            'confidence_managed': True
        }

        return response or fallback, token_info

    def _generate_enhanced_lecturer_answer_smart(self, query, context, intent_info, entities, session_id):
        personal_address = self._get_personal_address(session_id)
        system_prompt = self._get_personalized_system_prompt(session_id)
        db_answer = context.get('db_answer', context.get('response', ''))
        db_answer = (db_answer[:3500] + '...') if len(db_answer) > 3500 else db_answer

        conversation_context = self.memory.get_conversation_context(session_id) if session_id else {}
        recent_summary = conversation_context.get('recent_conversation_summary', '')
        
        context_section = ""
        if recent_summary:
            context_section = f"""
🗣️ NGỮ CẢNH HỘI THOẠI GẦN ĐÂY:
{recent_summary}

💡 LƯU Ý: Tham khảo ngữ cảnh trên để tránh lặp lại thông tin, tạo câu trả lời mạch lạc và tự nhiên.
"""

        prompt = f"""{system_prompt}

---
BỐI CẢNH VÀ NHIỆM VỤ

1.  **Kiến thức nền (từ CSDL):**
    "{db_answer}"

2.  **Câu hỏi của giảng viên:**
    "{query}"

{context_section}

3.  **YÊU CẦU CUỐI CÙNG (QUAN TRỌNG):**
    Nhiệm vụ chính của bạn bây giờ là **nhập vai một trợ lý AI** với các đặc điểm và quy tắc được giảng viên định nghĩa trong phần "GHI NHỚ RIÊNG".
    Hãy sử dụng "Kiến thức nền" để trả lời "Câu hỏi của giảng viên" trong khi vẫn duy trì đúng vai trò đó.
    Nếu "GHI NHỚ RIÊNG" trống, hãy trả lời một cách chuyên nghiệp, rõ ràng theo quy tắc mặc định.
    Tạo câu trả lời mạch lạc, tự nhiên, tránh lặp lại thông tin đã thảo luận.
    ĐẶC BIỆT: Tạo câu trả lời chi tiết và toàn diện hơn.
---
Trả lời:
"""

        complexity_hint = 'enhanced_generation' if context.get('generation_boosted', False) else 'two_stage_reranking'
        optimal_tokens = self.token_manager.calculate_optimal_tokens(len(prompt), complexity_hint)
        response = self._call_gemini_api_with_smart_tokens(prompt, complexity_hint, optimal_tokens, session_id)
        
        fallback = f"Dạ {personal_address}, {db_answer} 🎓 {personal_address.title()} có cần hỗ trợ thêm gì không ạ?"
        
        token_info = {
            'smart_tokens_used': True, 
            'method': 'enhanced_answer_smart_v6_advanced_confidence', 
            'optimal_tokens': optimal_tokens, 
            'generation_boosted': context.get('generation_boosted', False),
            'context_aware': bool(recent_summary),
            'confidence_managed': True,
            'two_stage_compatible': True
        }

        return response or fallback, token_info

    def _generate_clarification_request_smart(self, query, context, session_id=None):        
        personal_address = self._get_personal_address(session_id)
        
        clarification_templates = {
            'friendly': f"Dạ {personal_address}, để em có thể hỗ trợ {personal_address} tốt nhất, {personal_address} có thể chia sẻ thêm chi tiết về vấn đề này được không ạ? 😊 Em rất sẵn lòng giúp đỡ!",
            'brief': f"Dạ {personal_address}, cần thêm thông tin chi tiết ạ. 🎓",
            'technical': f"Dạ {personal_address}, để cung cấp hướng dẫn kỹ thuật chính xác, {personal_address} vui lòng cung cấp thêm thông số và yêu cầu cụ thể ạ.",
            'detailed': f"Dạ {personal_address}, để em có thể đưa ra câu trả lời toàn diện và chi tiết nhất, {personal_address} có thể bổ sung thêm về bối cảnh, mục đích sử dụng, và các yêu cầu cụ thể không ạ? Điều này sẽ giúp em hỗ trợ {personal_address} một cách hiệu quả nhất.",
            'professional': f"Dạ {personal_address}, để em hỗ trợ chính xác nhất, {personal_address} có thể nói rõ hơn về vấn đề cần hỗ trợ không ạ? 🎓"
        }
        
        response = clarification_templates.get('professional', clarification_templates['professional'])
        
        token_info = {
            'smart_tokens_used': False,
            'method': 'clarification_template_v2',
            'confidence_managed': True,
            'template_type': 'professional'
        }
        
        return response, token_info

    def _generate_dont_know_response_smart(self, query, context, session_id=None):        
        personal_address = self._get_personal_address(session_id)
        query_lower = query.lower()
        if any(word in query_lower for word in ['ngân hàng đề', 'đề thi', 'khảo thí']):
            dept = "Phòng Đảm bảo chất lượng và Khảo thí"
            contact = "ldkham@bdu.edu.vn"
        elif any(word in query_lower for word in ['kê khai', 'nhiệm vụ', 'giờ chuẩn']):
            dept = "Phòng Tổ chức - Cán bộ"
            contact = "tcccb@bdu.edu.vn"
        elif any(word in query_lower for word in ['tạp chí', 'nghiên cứu', 'khoa học']):
            dept = "Phòng Nghiên cứu - Hợp tác"
            contact = "nghiencuu@bdu.edu.vn"
        elif any(word in query_lower for word in ['khen thưởng', 'thi đua']):
            dept = "Phòng Tổ chức - Cán bộ"
            contact = "tcccb@bdu.edu.vn"
        else:
            dept = "phòng ban liên quan"
            contact = "info@bdu.edu.vn"
        response = f"Dạ {personal_address}, em chưa có thông tin về vấn đề này. {personal_address.title()} có thể liên hệ {dept} qua email {contact} để được hỗ trợ chi tiết ạ. 🎓"
        
        token_info = {
            'smart_tokens_used': False,
            'method': 'dont_know_template_v2',
            'suggested_department': dept,
            'personal_addressing': personal_address,
            'confidence_managed': True
        }
        
        return response, token_info

    def _determine_lecturer_response_strategy(self, query, context, intent_info, conversation_context):        
        has_real_history = bool(conversation_context.get('history') and len(conversation_context['history']) > 0)
        
        print(f"🔍 LECTURER STRATEGY DEBUG: has_real_history = {has_real_history}")
        
        if has_real_history:
            last_interaction = conversation_context['history'][-1]
            last_query = last_interaction['user_query'].lower()
            current_query = query.lower()
            
            lecturer_topics = {
                'ngân hàng đề thi': ['ngân hàng', 'đề thi', 'đề', 'khảo thí'],
                'kê khai nhiệm vụ': ['kê khai', 'nhiệm vụ', 'giờ chuẩn'],
                'tạp chí khoa học': ['tạp chí', 'bài viết', 'nghiên cứu'],
                'thi đua khen thưởng': ['thi đua', 'khen thưởng', 'danh hiệu'],
                'báo cáo': ['báo cáo', 'nộp', 'hạn cuối'],
                'lịch giảng dạy': ['lịch', 'giảng dạy', 'thời khóa biểu']
            }
            
            last_main_topic = None
            for topic, keywords in lecturer_topics.items():
                if any(kw in last_query for kw in keywords):
                    last_main_topic = topic
                    break
            
            current_main_topic = None
            for topic, keywords in lecturer_topics.items():
                if any(kw in current_query for kw in keywords):
                    current_main_topic = topic
                    break

            has_exact_same_topic = last_main_topic is not None and last_main_topic == current_main_topic
            strong_continuation_words = ['còn', 'thêm', 'nữa', 'khác', 'và', 'tiếp theo']
            has_strong_continuation = any(word in current_query.split() for word in strong_continuation_words)
            strong_clarification_words = ['cụ thể hơn', 'rõ hơn', 'chi tiết hơn', 'giải thích thêm']
            has_strong_clarification = any(phrase in current_query for phrase in strong_clarification_words)
            memory_test_words = ['nhớ không', 'hỏi gì', 'nói gì trước', 'vừa nói', 'tổng hợp']
            is_memory_test = any(word in current_query for word in memory_test_words)

            if has_strong_continuation and has_exact_same_topic:
                return 'follow_up_continuation'
            if has_strong_clarification and has_exact_same_topic:
                return 'follow_up_clarification'
            if is_memory_test:
                return 'memory_reference'
            if current_main_topic is not None and last_main_topic is not None and current_main_topic != last_main_topic:
                return 'topic_shift'
        
        raw_confidence = context.get('confidence', 0.5) if context else 0.5
        normalized_confidence = self.confidence_manager.normalize_confidence(raw_confidence, "strategy_decision")
        
        if normalized_confidence > 0.75:
            return 'direct_enhance'
        if normalized_confidence > 0.4:
            return 'enhanced_generation'
        if intent_info and intent_info.get('intent') in ['greeting', 'general'] and len(query.split()) <= 5:
            return 'quick_clarify'
        if any(word in query.lower() for word in ['khó khăn', 'cần gấp', 'hạn cuối', 'urgent']):
            return 'supportive_brief'
        return 'balanced'

    def _post_process_with_lecturer_consistency(self, response, query, context, strategy, conversation_context, session_id=None):
        if not response:
            return response
        personal_address = self._get_personal_address(session_id)
        prohibited_phrases = [
            'với tư cách là sinh viên', 'tôi là học sinh',
            'bạn', 'mình', 'anh', 'chị', 'em là sinh viên'
        ]
        for phrase in prohibited_phrases:
            if phrase.lower() in response.lower():
                response = response.replace(phrase, 'em là AI assistant của BDU')
        response = re.sub(r'\bbạn\b', personal_address, response, flags=re.IGNORECASE)
        response = re.sub(r'\bmình\b', 'em', response, flags=re.IGNORECASE)
        response = re.sub(r'\btôi\b', 'em', response, flags=re.IGNORECASE)
        response_stripped = response.strip()
        personalized_start = f"Dạ {personal_address},"
        if not response_stripped.lower().startswith(f'dạ {personal_address.lower()}'):
            if response_stripped.lower().startswith('dạ'):
                response = personalized_start + ' ' + response_stripped[3:].strip()
            else:
                response = personalized_start + ' ' + response_stripped
        proper_ending_pattern = r'(thầy|cô|giảng viên)\s+[^.!?]*có\s+cần.*?hỗ trợ.*?thêm.*?gì.*?không.*?ạ\?'
        
        if not re.search(proper_ending_pattern, response.lower()):
            response = re.sub(r'\s*🎓.*', '', response.strip())
            response = re.sub(r'\s*(có cần.*?không ạ\?|Cần.*?không\?|Có.*?không\?).*', '', response.strip())
            if not response.strip().endswith(('.', '!', '?')):
                response += '.'
            response += f' {personal_address.title()} có cần em hỗ trợ thêm gì không ạ? 🎓'
        response = re.sub(r'\*\*\d+\.\s*', '', response)
        response = re.sub(r'^\s*\d+\.\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'^\s*[•\-\*]\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'\*\*(.*?)\*\*', r'\1', response)
        duplicate_name_pattern = f'({re.escape(personal_address.title())}).*?\\1'
        response = re.sub(duplicate_name_pattern, r'\1', response)
        return response.strip()
    
    def _get_contextual_out_of_scope_response_lecturer(self, conversation_context, session_id=None):        
        personal_address = self._get_personal_address(session_id)
        user_context = self._user_context_cache.get(session_id, {}) if session_id else {}
        department_name = user_context.get('department_name', '')
        if conversation_context.get('context_summary'):
            if department_name:
                return f"Dạ {personal_address}, em chỉ hỗ trợ các vấn đề liên quan đến công việc giảng viên tại BDU thôi ạ! 🎓 {personal_address.title()} còn muốn hỏi gì về {conversation_context['context_summary'].lower()} cho ngành {department_name} không ạ?"
            else:
                return f"Dạ {personal_address}, em chỉ hỗ trợ các vấn đề liên quan đến công việc giảng viên tại BDU thôi ạ! 🎓 {personal_address.title()} còn muốn hỏi gì về {conversation_context['context_summary'].lower()} không ạ?"
        
        if department_name:
            return f"Dạ {personal_address}, em chỉ hỗ trợ các vấn đề liên quan đến công việc giảng viên tại BDU thôi ạ! 🎓 {personal_address.title()} có câu hỏi nào khác về ngành {department_name} không ạ?"
        else:
            return f"Dạ {personal_address}, em chỉ hỗ trợ các vấn đề liên quan đến công việc giảng viên tại BDU thôi ạ! 🎓 {personal_address.title()} có câu hỏi nào khác về trường không ạ?"
    
    def _get_smart_fallback_with_context_lecturer(self, query, intent_info, conversation_context, session_id=None):        
        personal_address = self._get_personal_address(session_id)
        user_context = self._user_context_cache.get(session_id, {}) if session_id else {}
        department_name = user_context.get('department_name', '')
        
        intent_name = intent_info.get('intent', 'general') if intent_info else 'general'
        
        if conversation_context.get('context_summary'):
            summary = conversation_context['context_summary']
            context_fallbacks = {
                'Đang hỏi về ngân hàng đề thi': f"Dạ {personal_address}, về ngân hàng đề thi, em có thể hỗ trợ thêm! 📋 {personal_address.title()} có cần hỗ trợ thêm gì không ạ?",
                'Đang hỏi về kê khai nhiệm vụ năm học': f"Dạ {personal_address}, về kê khai nhiệm vụ năm học, em có thể hỗ trợ thêm! 📊 {personal_address.title()} có cần hỗ trợ thêm gì không ạ?",
                'Đang hỏi về tạp chí khoa học': f"Dạ {personal_address}, về tạp chí khoa học, em có thể hỗ trợ thêm! 📚 {personal_address.title()} có cần hỗ trợ thêm gì không ạ?",
                'Đang hỏi về thi đua khen thưởng': f"Dạ {personal_address}, về thi đua khen thưởng, em có thể hỗ trợ thêm! 🏆 {personal_address.title()} có cần hỗ trợ thêm gì không ạ?"
            }
            if summary in context_fallbacks:
                return context_fallbacks[summary]
        
        smart_fallbacks = {
            'greeting': f"Dạ chào {personal_address}! 👋 Em có thể hỗ trợ gì cho {personal_address} về BDU ạ?",
            'general': f"Dạ {personal_address}, em sẵn sàng hỗ trợ các vấn đề liên quan đến BDU! 🎓 {personal_address.title()} có cần hỗ trợ thêm gì không ạ?"
        }
        
        if department_name and intent_name == 'general':
            smart_fallbacks['general'] = f"Dạ {personal_address}, em sẵn sàng hỗ trợ các vấn đề liên quan đến BDU và ngành {department_name}! 🎓 {personal_address.title()} có cần hỗ trợ thêm gì không ạ?"
        
        return smart_fallbacks.get(intent_name, smart_fallbacks['general'])
    
    def _is_lecturer_education_related(self, query):
        lecturer_education_keywords = [
            'trường', 'học', 'sinh viên', 'tuyển sinh', 'học phí', 'ngành', 
            'đại học', 'bdu', 'gv', 'giảng viên', 'dạy', 'quy định',
            'hội đồng', 'nghiên cứu', 'công tác', 'báo cáo', 'đánh giá',
            'thi đua', 'thành tích', 'khen thưởng', 'xét', 'xét thi đua',
            'nhiệm vụ', 'chức năng', 'tiêu chuẩn', 'tiêu chí', 'định mức',
            'kiểm tra', 'giám sát', 'quản lý', 'kết quả', 'hiệu quả',
            'phân công', 'giao nhiệm vụ', 'trách nhiệm', 'chuẩn đầu ra',
            'học kỳ', 'năm học', 'kỳ thi', 'bài giảng', 'giáo án',
            'lớp học', 'môn học', 'học phần', 'tín chỉ', 'cố vấn',
            'ngân hàng đề thi', 'file mềm', 'nộp', 'email', 'phòng ban',
            'kê khai', 'giờ chuẩn', 'thỉnh giảng', 'tạp chí', 'bài viết',
            'điểm', 'đạt', 'không đạt', 'học lại', 'nâng điểm', 'cải thiện điểm',
            'điểm trung bình', 'trung bình', 'tính điểm', 'tính',
            'chuyển đổi', 'công nhận', 'khối lượng', 'tối thiểu', 'chương trình', 
            'phần trăm', 'tối đa', 'giới hạn',
            'tốt nghiệp', 'lễ tốt nghiệp', 'tham dự', 'được phép', 'bằng cấp', 
            'văn bằng', 'cử nhân', 'cấp bằng', 'nhận bằng',
            'thường trực', 'kỷ luật', 'hội đồng thi đua', 'danh sách', 'thành phần',
            'theo quy định', 'quy định về', 'thể lệ', 'hướng dẫn', 'thủ tục',
            'điều kiện', 'yêu cầu',
            'như thế nào', 'bao nhiêu', 'là ai', 'ai là', 'làm gì', 'ở đâu', 
            'khi nào', 'có được',
            
            'truong', 'hoc', 'sinh vien', 'tuyen sinh', 'hoc phi', 'nganh',
            'dai hoc', 'giang vien', 'day', 'quy dinh', 'nghien cuu',
            'thi dua', 'thanh tich', 'khen thuong', 'nhiem vu', 'chuc nang',
            'tieu chuan', 'tieu chi', 'dinh muc', 'kiem tra', 'giam sat',
            'quan ly', 'ket qua', 'hieu qua', 'phan cong', 'giao nhiem vu',
            'hoc ky', 'nam hoc', 'ky thi', 'bai giang', 'giao an',
            'lop hoc', 'mon hoc', 'hoc phan', 'tin chi', 'co van',
            'ngan hang de thi', 'file mem', 'ke khai', 'gio chuan',
            'thinh giang', 'tap chi', 'bai viet'
            'diem', 'dat', 'khong dat', 'hoc lai', 'nang diem', 'cai thien diem',
            'diem trung binh', 'trung binh', 'tb', 'dtb', 'tinh diem', 'tinh',
            'chuyen doi', 'cong nhan', 'khoi luong', 'toi thieu', 'chuong trinh',
            'phan tram', 'toi da', 'gioi han',
            'tot nghiep', 'le tot nghiep', 'tham du', 'duoc phep', 'bang cap',
            'van bang', 'cu nhan', 'cap bang', 'nhan bang',
            'thuong truc', 'ky luat', 'hoi dong thi dua', 'danh sach', 'thanh phan',
            'ai phu trach', 'theo quy dinh', 'quy dinh ve', 'the le', 'huong dan', 'thu tuc',
            'dieu kien', 'yeu cau', 'nhu the nao', 'bao nhieu', 'la ai',
            'ai la', 'lam gi', 'o dau', 'khi nao', 'co duoc'
        ]
        
        if not query:
            return False        
        query_lower = query.lower()
        return any(kw in query_lower for kw in lecturer_education_keywords)

    def _build_enhanced_prompt(self, query: str, context=None, intent_info=None, entities=None, session_id=None):
        system_prompt = self._get_personalized_system_prompt(session_id)
        personal_address = self._get_personal_address(session_id)
        
        context_info = str(context.get('response', '')) if isinstance(context, dict) else str(context or '')
        
        conversation_context = self.memory.get_conversation_context(session_id) if session_id else {}
        recent_summary = conversation_context.get('recent_conversation_summary', '')
        
        context_section = ""
        if recent_summary:
            context_section = f"""
🗣️ NGỮ CẢNH HỘI THOẠI GẦN ĐÂY:
{recent_summary}

💡 LƯU Ý: Tham khảo ngữ cảnh trên để tránh lặp lại thông tin, tạo câu trả lời mạch lạc.
"""
        
        prompt = f"""{system_prompt}
        
CÂU HỎI: {query}
THÔNG TIN: {context_info}

{context_section}

YÊU CẦU:
- Bắt đầu: "Dạ {personal_address},"
- Kết thúc: "{personal_address.title()} có cần hỗ trợ thêm gì không ạ?"
- Tạo câu trả lời mạch lạc, tự nhiên, tránh lặp lại thông tin đã thảo luận

Trả lời:"""
        return prompt
    
    def validate_user_preferences(self, preferences):
        errors, warnings = [], []
        if 'user_memory_prompt' in preferences:
            memory = preferences['user_memory_prompt']
            if isinstance(memory, str):
                if len(memory) > 1500:
                    errors.append("user_memory_prompt too long (max 1500 characters)")
                elif len(memory) > 1400:
                    warnings.append("user_memory_prompt approaching limit")
            else:
                errors.append("user_memory_prompt must be string")
        if 'department_priority' in preferences:
            if not isinstance(preferences['department_priority'], bool):
                errors.append("department_priority must be boolean")
        
        return {'valid': len(errors) == 0, 'errors': errors, 'warnings': warnings}
    
    def get_user_context(self, session_id: str):
        return self._user_context_cache.get(session_id)    
    def clear_user_context(self, session_id=None):
        if session_id:
            if session_id in self._user_context_cache:
                del self._user_context_cache[session_id]
        else:
            self._user_context_cache.clear()
    def get_conversation_memory(self, session_id: str):
        return self.memory.get_conversation_context(session_id)
    def clear_conversation_memory(self, session_id: str = None):
        if session_id:
            if session_id in self.memory.conversations:
                del self.memory.conversations[session_id]
        else:
            self.memory.conversations.clear()
    def get_system_status(self) -> Dict[str, Any]:
        try:
            test_prompt = "Test ngắn cho giảng viên"
            response = self._call_gemini_api_with_smart_tokens(test_prompt, 'quick_clarify', 80, session_id="test")
            
            return {
                'gemini_api_available': response is not None,
                'api_key_configured': bool(self.key_manager.keys),
                'service_status': 'active' if response else 'error',
                'mode': 'advanced_rag_gemini_with_two_stage_reranking_integration_and_advanced_confidence_management',
                'memory_sessions': len(self.memory.conversations),
                'personalization_sessions': len(self._user_context_cache),
                'adaptive_token_range': self.token_manager.adaptive_token_range,
                'confidence_management': {
                    'max_confidence': self.confidence_manager.MAX_CONFIDENCE,
                    'decision_thresholds': self.confidence_manager.decision_thresholds,
                    'calibration_rules': self.confidence_manager.confidence_calibration_rules,
                    'overflow_protection_enabled': True,
                    'confidence_normalization_active': True
                },
                'features': [
                    'advanced_confidence_management',
                    'confidence_overflow_protection',
                    'confidence_normalization',
                    'two_stage_reranking_integration',
                    'advanced_rag_compatibility',
                    'smart_token_management',
                    'auto_response_completion',
                    'adaptive_token_allocation',
                    'incomplete_response_detection',
                    'lecturer_conversation_memory',
                    'lecturer_role_consistency',
                    'lecturer_context_aware_responses',
                    'lecturer_follow_up_detection',
                    'lecturer_topic_shift_handling',
                    'lecturer_clarification_requests',
                    'lecturer_department_suggestions',
                    'personalized_system_prompts',
                    'personalized_addressing',
                    'department_specific_responses',
                    'user_memory_prompt_support',
                    'flexible_personalization',
                    'external_api_data_processing',
                    'lecturer_schedule_formatting',
                    'personal_information_handling',
                    'gender_based_addressing',
                    'conversation_context_summary',
                    'mạch_lạc_response_generation',
                    'consistent_personalization_in_errors',
                    'session_id_propagation_in_api_calls',
                    'graceful_error_handling_with_personalization',
                    'document_context_processing',
                    'pdf_docx_text_extraction',
                    'document_based_question_answering',
                    'ocr_integration_support',
                    'fine_tuned_model_compatibility',
                    'cross_encoder_simulation_support',
                    'hybrid_retrieval_enhancement'
                ]
            }
        except Exception as e:
            return {
                'gemini_api_available': False,
                'service_status': 'error',
                'error': str(e),
                'consistent_personalization': True,
                'graceful_degradation': True,
                'document_context_support': True,
                'advanced_confidence_management': True,
                'confidence_overflow_protection': True
            }
            
class LocalQwenGenerator(GeminiResponseGenerator):
    def __init__(self):
        super().__init__()
        self.model_name = "qwen2.5:7b" 
        base_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
        
        # Xử lý để đảm bảo đường dẫn luôn đúng là .../api/chat
        if base_url.endswith("/api/chat"):
            self.api_url = base_url
        else:
            # Xóa dấu / ở cuối nếu có để tránh bị 2 dấu //
            base_url = base_url.rstrip("/")
            self.api_url = f"{base_url}/api/chat"
            
        logger.info(f"🚀 LocalQwenGenerator initialized using {self.model_name} via Ollama at {self.api_url}")

    def _call_gemini_api_with_smart_tokens(self, prompt: str, strategy: str, max_tokens: int, session_id: str = None, retry_count=0) -> Optional[str]:
        """
        Ghi đè hàm gọi API: Chuyển hướng sang Ollama Local
        """
        try:
            # Mapping tham số strategy sang temperature
            strategy_temp = {
                'quick_clarify': 0.1,      # Thấp để chính xác
                'direct_enhance': 0.2, 
                'enhanced_generation': 0.5, 
                'completion': 0.1, 
                'balanced': 0.3,
                'document_context': 0.1,
                'chat_only': 0.6,          # Cao hơn chút để tự nhiên
                'general_knowledge': 0.4
            }
            temperature = strategy_temp.get(strategy, 0.3)

            # 🛠️ SYSTEM PROMPT "THÉP": Chống tiếng Trung tuyệt đối
            system_instruction = """
            Bạn là ChatBDU, trợ lý ảo Tiếng Việt của Đại học Bình Dương.
            QUY TẮC BẤT DI BẤT DỊCH:
            1. NGÔN NGỮ: CHỈ trả lời bằng Tiếng Việt.
            2. CẤM: Tuyệt đối KHÔNG sử dụng tiếng Trung Quốc (Chinese/Mandarin) trong bất kỳ hoàn cảnh nào.
            3. DỊCH THUẬT: Nếu thông tin đầu vào là tiếng Anh hoặc tiếng Trung, hãy dịch mượt mà sang tiếng Việt.
            4. XƯNG HÔ: Xưng là 'em' và gọi người dùng là 'thầy/cô' hoặc 'bạn' tùy ngữ cảnh đã cung cấp.
            """

            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": system_instruction
                    },
                    {
                        "role": "user", 
                        # Nhắc lại một lần nữa ở cuối prompt để model nhớ kỹ
                        "content": f"{prompt}\n\n(Lưu ý: Hãy trả lời hoàn toàn bằng tiếng Việt)"
                    }
                ],
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": 0.9,
                    "repeat_penalty": 1.1, # Phạt lặp từ để tránh văn phong lặp lại
                    "num_ctx": 4096
                }
            }

            logger.info(f"🤖 Sending request to Local Ollama ({self.model_name}) | Strategy: {strategy}")
            
            # 👇 Dòng này giữ nguyên như Khang hỏi, nó sẽ dùng self.api_url đã setup ở trên
            response = requests.post(self.api_url, json=payload, timeout=120) 
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('message', {}).get('content', '')
                return content
            else:
                logger.error(f"❌ Ollama API Error {response.status_code}: {response.text}")
                return None

        except requests.exceptions.ConnectionError:
            # Sửa log một chút để biết nó đang gọi vào đâu
            logger.critical(f"❌ Could not connect to Ollama at {self.api_url}! Make sure 'ollama serve' is running.")
            return "Xin lỗi, hệ thống AI nội bộ đang mất kết nối. Vui lòng kiểm tra server Ollama."
        except Exception as e:
            logger.error(f"❌ Local LLM Error: {str(e)}")
            return None