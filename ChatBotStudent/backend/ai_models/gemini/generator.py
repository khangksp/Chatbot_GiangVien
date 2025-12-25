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
from .memory import ConversationMemory
from .restorer import SimpleVietnameseRestorer
from .token_manager import SmartTokenManager
from .confidence import AdvancedConfidenceManager
from . import prompts

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
            "temperature": 0.55,
            "topP": 0.85
        }
        
        self.role_consistency_rules = {
            'identity': 'AI assistant của Đại học Bình Dương (BDU) hỗ trợ sinh viên',
            'personality': 'lịch sự, chuyên nghiệp, tôn trọng',
            'knowledge_scope': 'chuyên về thông tin BDU và hỗ trợ sinh viên',
            'addressing': 'xưng hô theo pronoun_style đã cấu hình (ví dụ người dùng="bạn", bot="tôi"/"tớ"/"mình")',
            'prohibited_roles': [
                'sinh viên', 'học sinh', 'phụ huynh', 'người ngoài trường'
            ]
        }
    def _get_dynamic_pronouns(self, session_id: str) -> Dict[str, str]:
        user_context = self._user_context_cache.get(session_id, {})
        preferences = user_context.get('preferences', {})
        pronoun_style = preferences.get('pronoun_style', 'default')
        style = prompts.PERSONAL_PRONOUNS.get(pronoun_style, prompts.PERSONAL_PRONOUNS['default'])
        user_options = style['user']
        bot_options = style['bot']
        bot_pronoun = random.choice(bot_options)
        user_pronoun = "bạn"
        first_name = None
        full_name = user_context.get('full_name')
        if full_name and isinstance(full_name, str):
            name_parts = full_name.split()
            first_name = name_parts[-1] if name_parts else full_name
        available_user_options = []
        for option in user_options:
            if option == '{first_name}':
                if first_name:
                    available_user_options.extend([first_name, first_name]) 
            else:
                available_user_options.append(option)
                
        if not available_user_options:
            available_user_options = ['bạn', 'cậu']

        user_pronoun = random.choice(available_user_options)

        return {'user': user_pronoun, 'bot': bot_pronoun}
        
    def _should_strip_greeting(self, session_id: str) -> bool:
        try:
            hist = self.memory.conversations.get(session_id, {}).get('history', [])
            return len(hist) >= 1
        except Exception:
            return False
    def _strip_greeting_and_closing(self, text: str, personal_address: str) -> str:
        if not text:
            return text
        s = text.strip()
        greet_pat = rf'^(Dạ[\s,]+)?((Xin\s+)?[Cc]hào\s+[^,!:]{{0,50}}[,!:]\s*)'
        s = re.sub(greet_pat, '', s)
        pa = re.escape(personal_address)
        s = re.sub(rf'^(Dạ[\s,]+)?{pa}\s*[,!:]\s*', '', s)
        pa_title = re.escape(personal_address.title())
        closing_variants = [
            r'có\s+thể\s+em\s+hỗ\s*trợ\s+thêm\s+gì\s+không\s+ạ\??',
            rf'{pa_title}\s+có\s+cần\s+em\s+hỗ\s*trợ\s+thêm\s+gì\s+không\s+ạ\??',
            r'em\s+có\s+thể\s+giúp\s+gì\s+thêm\s+không\s+ạ\??'
        ]
        s = re.sub('|'.join(closing_variants), '', s, flags=re.IGNORECASE).strip()
        s = re.sub(r'\s*([,;:])\s*$', '', s).strip()
        return s

    def _generate_external_api_response(self, query, context, session_id=None):
        api_data = context.get('api_data', None) # Lấy api_data (có thể là dict hoặc list hoặc None)
        profile_data = context.get('profile', {}) # Lấy profile (luôn là dict)
        data_type = context.get('data_type', 'general') # Lấy data_type
        
        logger.debug(f"--- DEBUG: _generate_external_api_response ---")
        logger.debug(f"Data type: {data_type}")
        logger.debug(f"api_data type: {type(api_data)}")
        logger.debug(f"profile_data: {json.dumps(profile_data, ensure_ascii=False)}")
        student_name = profile_data.get('name', profile_data.get('full_name', 'bạn'))
        display_name = student_name.split()[-1] if student_name and student_name != 'bạn' else 'bạn' # Lấy tên riêng
        mssv = profile_data.get('mssv', 'N/A')
        class_name = profile_data.get('class', profile_data.get('class_name', 'N/A'))
        faculty = profile_data.get('faculty', 'N/A')
        system_prompt_header = f"""Bạn là ChatBDU, trợ lý AI thân thiện của Đại học Bình Dương, đang nói chuyện với sinh viên tên là {display_name}.

👤 THÔNG TIN CỦA SINH VIÊN (BẠN):
- Tên: {student_name}
- MSSV: {mssv}
- Lớp: {class_name}
- Khoa: {faculty}

❓ CÂU HỎI CỦA SINH VIÊN: "{query}"

📝 DỮ LIỆU TỪ HỆ THỐNG:
"""
        data_section = ""
        instruction_section = ""
        if api_data is None:
             logger.warning(f"⚠️ api_data is None for data_type '{data_type}'. Cannot build data section.")
             data_section = "(Không có dữ liệu từ hệ thống)"
             instruction_section = f"""
HƯỚNG DẪN (Không có dữ liệu):
- Thông báo cho {display_name} rằng không tìm thấy dữ liệu liên quan đến câu hỏi.
- Có thể gợi ý hỏi lại hoặc kiểm tra thông tin khác.
- Xưng "mình" và gọi sinh viên là "{display_name}" hoặc "bạn".
"""
        elif data_type == "profile":
            _student_info_data = {}
            if isinstance(api_data, dict):
                 _student_info_data = api_data.get('student_info', api_data)
            else:
                 _student_info_data = profile_data
                 logger.warning(f"⚠️ Expected dict for profile api_data, got {type(api_data)}. Using profile_data instead.")

            data_section = f"""```json
{json.dumps(_student_info_data, ensure_ascii=False, indent=2)}
```"""
            instruction_section = f"""
HƯỚNG DẪN (Profile):
- Phân tích câu hỏi để xác định thông tin sinh viên đang hỏi về CHÍNH HỌ dựa trên dữ liệu trên.
- Chỉ trả lời phần thông tin được hỏi, ngắn gọn, tự nhiên.
- Xưng "mình" và gọi sinh viên là "{display_name}" hoặc "bạn".
- TUYỆT ĐỐI KHÔNG nói "Mình học lớp..." mà phải nói "Bạn học lớp...".
"""
        elif data_type == "schedule" and isinstance(api_data, list):
            date_range_info = profile_data.get("date_range", {}) # Lấy từ profile context
            start_date = date_range_info.get("start_date")
            end_date = date_range_info.get("end_date")
            date_context = ""
            if start_date and end_date:
                date_context = f"cho khoảng thời gian từ {start_date} đến {end_date}"
                if start_date == end_date:
                    date_context = f"cho ngày {start_date}"

            data_section = f"""(Lịch học {date_context})
```json
{json.dumps(api_data, ensure_ascii=False, indent=2)}
```"""
            instruction_section = f"""
HƯỚNG DẪN (Lịch học):
- Dựa vào danh sách các buổi học {date_context}, hãy tóm tắt lịch học cho {display_name}.
- Trình bày rõ ràng theo ngày, môn học, thời gian (tiết), phòng học, giảng viên.
- Nếu không có lịch học trong danh sách, hãy báo rõ là không có cho khoảng thời gian đó.
- Xưng "mình" và gọi sinh viên là "{display_name}" hoặc "bạn".
- Nếu dữ liệu là của "2 tuần tới" (theo date_context), hãy dùng đúng cụm từ đó.
"""
        elif data_type == "tuition" and isinstance(api_data, list):
            data_section = f"""(Danh sách các khoản thu học phí và BHYT)
```json
{json.dumps(api_data, ensure_ascii=False, indent=2)}
```"""
            instruction_section = f"""
HƯỚNG DẪN (Học phí):
- Dựa vào danh sách các khoản thu (bao gồm trường `tong_tien_phai_thu`, `tong_tien_da_thu`, `tong_tien_con_lai`, `status`, `nkhk`), hãy phân tích và trả lời câu hỏi của {display_name}.
- Tính toán tổng số tiền còn lại nếu được hỏi "còn bao nhiêu" hoặc "chưa đóng".
- Liệt kê chi tiết các khoản theo học kỳ hoặc năm học (`nkhk`) nếu được hỏi "các kỳ" hoặc "năm X".
- Trả lời về trạng thái ("đã đóng", "chưa đóng") nếu được hỏi.
- Nếu hỏi "tổng học phí các kỳ", hãy tính tổng cộng phải đóng, đã đóng, còn lại của TẤT CẢ các khoản trong danh sách.
- Xưng "mình" và gọi sinh viên là "{display_name}" hoặc "bạn".
"""

        # *** KHỐI LOGIC MỚI CHO CURRICULUM ***
        elif data_type == "curriculum" and isinstance(api_data, dict):
            curriculum_tree = api_data.get("curriculum_tree", [])
            credit_summary = api_data.get("credit_summary", {})
            
            data_section = f"""1. DỮ LIỆU TÍN CHỈ TỔNG QUAN:
```json
{json.dumps(credit_summary, ensure_ascii=False, indent=2)}
```"""
            instruction_section = f"""
HƯỚNG DẪN (Chung):
- Dựa vào dữ liệu trên, cố gắng trả lời câu hỏi của {display_name} một cách chính xác và tự nhiên nhất có thể.
- Xưng "mình" và gọi sinh viên là "{display_name}" hoặc "bạn".
"""
        prompt = system_prompt_header + data_section + instruction_section + "\nTrả lời:"
        optimal_tokens = self.token_manager.calculate_optimal_tokens(
            len(prompt),
            'external_api_processing'
        )
        
        # *** TĂNG TOKEN CHO CURRICULUM ***
        if data_type == "curriculum":
            optimal_tokens = max(optimal_tokens, 4096) # Đảm bảo đủ token để phân tích JSON
            logger.info(f"🌐 Processing external API data ({data_type}) with BOOSTED {optimal_tokens} tokens")
        else:
            logger.info(f"🌐 Processing external API data ({data_type}) with {optimal_tokens} tokens")

        response = self._call_gemini_api_with_smart_tokens(
            prompt, 'external_api_processing', optimal_tokens, session_id
        )
        if response:
             response = response.strip()
        if not response:
            logger.warning(f"⚠️ Gemini failed or returned empty for external API ({data_type}). Using basic fallback.")
            if data_type == "profile":
                 s_name = profile_data.get('name', student_name)
                 s_mssv = profile_data.get('mssv', mssv)
                 s_class = profile_data.get('class', class_name)
                 s_faculty = profile_data.get('faculty', faculty)
                 response = f"Thông tin của bạn: Tên {s_name}, MSSV {s_mssv}, Lớp {s_class}, Khoa {s_faculty}."
            elif data_type == "schedule" and isinstance(api_data, list):
                 if not api_data:
                     response = f"Chào {display_name}, bạn không có lịch học nào trong khoảng thời gian được yêu cầu."
                 else:
                     response = f"Đây là lịch học của bạn, {display_name}:\n"
                     for session in api_data[:2]:
                         response += f"- {session.get('ten_mon_hoc', 'N/A')} vào ngày {session.get('ngay_hoc', '?')}\n"
                     if len(api_data) > 2: response += "... (và các môn khác)"
            elif data_type == "tuition" and isinstance(api_data, list):
                 try:
                     from ..chatbot_logic.student_api_handler import _format_tuition_response # Import nếu cần
                     response = _format_tuition_response(api_data, "overview", query)
                 except ImportError:
                     logger.error("Fallback function _format_tuition_response not found.")
                     response = f"Mình gặp khó khăn khi xử lý thông tin học phí của {display_name}."
                 except Exception as fmt_err:
                     logger.error(f"Error in fallback _format_tuition_response: {fmt_err}")
                     response = f"Mình gặp khó khăn khi tóm tắt học phí của {display_name}."
            
            # *** FALLBACK CHO CURRICULUM ***
            elif data_type == "curriculum":
                 response = f"Chào {display_name}, mình đã tải được chương trình đào tạo của cậu nhưng gặp lỗi khi phân tích chi tiết. Cậu có thể kiểm tra trực tiếp trên cổng thông tin sinh viên nhé."
            
            else:
                 response = f"Mình đã nhận được dữ liệu nhưng gặp khó khăn khi diễn giải cho {display_name}. Bạn có thể hỏi cụ thể hơn không?"
        logger.debug(f"--- DEBUG END: _generate_external_api_response ---")
        return response
    
    def _generate_student_profile_response(self, query, student_info, session_id=None):
        try:
            student_name = student_info.get('student_name', '')
            mssv = student_info.get('mssv', '')
            class_name = student_info.get('class', '')
            faculty = student_info.get('faculty', '')
            display_name = student_name.split()[-1] if student_name else 'bạn'
            prompt = f"""Bạn là ChatBDU, trợ lý AI thân thiện của Đại học Bình Dương, đang nói chuyện với một sinh viên.

👤 THÔNG TIN CỦA SINH VIÊN (BẠN):
- Tên: {student_name}
- MSSV: {mssv}
- Lớp: {class_name}
- Khoa: {faculty}

❓ CÂU HỎI CỦA SINH VIÊN: {query}

HƯỚNG DẪN:
- Phân tích câu hỏi để xác định thông tin sinh viên đang hỏi về CHÍNH HỌ.
- Chỉ trả lời phần thông tin được hỏi, ngắn gọn, tự nhiên.
- Ví dụ:
  - "tôi là ai" → Trả đầy đủ tên + MSSV + lớp + khoa
  - "mssv" → Chỉ trả MSSV
  - "lớp của tôi" → Chỉ trả lớp
  - "khoa" → Chỉ trả khoa
  - "tên tôi" → Chỉ trả tên
- **QUAN TRỌNG VỀ XƯNG HÔ:** Luôn xưng "mình" (hoặc "tớ") và gọi sinh viên là "bạn" (hoặc tên {display_name}).
- **TUYỆT ĐỐI KHÔNG:** Không bao giờ nói "Mình học lớp..." (I am in class...). Phải nói "Bạn học lớp..." (You are in class...) hoặc "Lớp của bạn là...".
- Hãy trả lời trực tiếp vào thông tin, không cần chào "Chào bạn..." nếu không cần thiết.

Trả lời:"""
            
            optimal_tokens = self.token_manager.calculate_optimal_tokens(
                len(prompt), 
                'student_profile_processing'
            )
            logger.info(f"🎓 Processing student profile with {optimal_tokens} tokens")
            
            response = self._call_gemini_api_with_smart_tokens(
                prompt, 'student_profile_processing', optimal_tokens, session_id
            )
            
            if not response:
                return f"Thông tin của bạn: Tên {student_name}, MSSV {mssv}, Lớp {class_name}, Khoa {faculty}."
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Error generating student profile response: {e}")
            return f"Thông tin của bạn: Tên {student_info.get('student_name', 'N/A')}, MSSV {student_info.get('mssv', 'N/A')}, Lớp {student_info.get('class', 'N/A')}, Khoa {student_info.get('faculty', 'N/A')}."
    
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
    
    def _get_personalized_system_prompt_for_external_api(self, student_info):        
        base_prompt = """Bạn là AI assistant của Đại học Bình Dương (BDU), chuyên hỗ trợ sinh viên.

🎯 QUY TẮC QUAN TRỌNG (external API):
- Giữ cách xưng hô theo pronoun_style hiện tại (ví dụ: gọi người dùng là "bạn", tự xưng "tôi"/"tớ"/"mình").
- Trả lời chính xác theo dữ liệu từ hệ thống; không bịa.
- Trình bày tự nhiên, dễ đọc; không ép mẫu "Dạ ...", không ép câu kết thúc khuôn mẫu.
"""
        return base_prompt
    def _get_personal_address_from_api_data(self, student_info, session_id): return 'bạn'
    def _post_process_external_api_response(self, response, student_info, query, session_id):
        if not response:
            return response
        response = re.sub(r'\*\*\d+\.\s*', '', response)
        response = re.sub(r'^\s*\d+\.\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'^\s*[•\-\*]\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'\*\*(.*?)\*\*', r'\1', response)
        return response.strip()
    def _get_external_api_fallback_response(self, api_data, personal_address):
        student_info = api_data.get('student_info', {})
        ten_sinh_vien = student_info.get('student_name', personal_address)
        return f"""Chào {personal_address}, mình tìm thấy thông tin từ hệ thống của trường:
👤 Thông tin của {ten_sinh_vien}:
- MSSV: {student_info.get('mssv', 'Không xác định')}
- Lớp: {student_info.get('class', 'Không xác định')}
- Khoa: {student_info.get('faculty', 'Không xác định')}

Tuy nhiên, mình gặp khó khăn khi xử lý câu hỏi cụ thể của bạn. Bạn có thể hỏi lại một cách khác không?"""
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

    def _get_personalized_system_prompt(self, session_id: str = None, context: Optional[Dict] = None):
        try:
            user_context = self._user_context_cache.get(session_id, {})
            user_memory_prompt = user_context.get('preferences', {}).get('user_memory_prompt', '')
            profile = None
            if context and isinstance(context, dict):
                profile = context.get('profile')
            if session_id:
                pronouns = self._get_dynamic_pronouns(session_id)
                user_address = pronouns['user']
                bot_pronoun = pronouns['bot']
            else:
                style = prompts.PERSONAL_PRONOUNS['default']
                user_address = random.choice(style['user']).replace('{first_name}', 'bạn')
                bot_pronoun = random.choice(style['bot'])
            return prompts.build_personalized_system_prompt(
                user_memory_prompt, 
                user_address=[user_address], # Truyền vào dưới dạng list
                bot_pronoun=[bot_pronoun],   # Truyền vào dưới dạng list
                profile=profile              # Truyền profile nếu có
            )
        except Exception as e:
            logger.error(f"Error getting personalized prompt: {e}")
            return prompts.build_personalized_system_prompt() # Fallback
        
    def generate_response(self, query: str, context: Optional[Dict] = None, 
                      intent_info: Optional[Dict] = None, entities: Optional[Dict] = None,
                      session_id: str = None) -> Dict[str, Any]:
        start_time = time.time()
        print(f"\n--- 🚀 ADVANCED RAG GENERATION REQUEST (Session: {session_id}) ---")
        print(f"🧠 MEMORY DEBUG: Total active sessions = {len(self.memory.conversations)}")
        try:
            original_query = query
            # Bỏ comment dòng dưới để bật chức năng phục hồi dấu tiếng Việt
            # if not self.vietnamese_restorer.has_vietnamese_accents(query):
            #     restored_query = self.vietnamese_restorer.restore_vietnamese_tone(query)
            #     if restored_query != query:
            #         logger.info(f"🎯 Query restored: '{query}' -> '{restored_query}'")
            #         query = restored_query
            
            instruction = context.get('instruction', '') if context else ''
            
            if instruction == 'summarize_news':
                logger.info("📰 NEWS SUMMARY: Processing news summary request")
                prompt = self._build_news_summary_prompt(query, context, session_id)
                optimal_tokens = self.token_manager.calculate_optimal_tokens(
                    len(prompt), 
                    'balanced' # Sửa hint thành 'balanced' để phù hợp với tóm tắt tổng quan
                )
                optimal_tokens = max(optimal_tokens, 600)
                response = self._call_gemini_api_with_smart_tokens(
                    prompt, 'balanced', optimal_tokens, session_id
                )
                if not response:
                    response = "Mình gặp chút khó khăn khi tóm tắt tin tức, bạn thử lại sau nhé."
                return {
                    'response': response,
                    'method': 'gemini_news_summary',
                    'strategy': 'summarize_news',
                    'confidence': 0.9,
                    'generation_time': time.time() - start_time,
                }
            
            if instruction == 'answer_from_document':
                logger.info("📄 DOCUMENT CONTEXT: Processing document-based query")
                document_text = context.get('document_text', '')
                if not document_text or not document_text.strip():
                    logger.warning("⚠️ Empty document text provided")
                    personal_address = self._get_personal_address(session_id)
                    response_confidence = self.confidence_manager.normalize_confidence(0.1, "document_error")
                    return {
                        'response': f"Chào cậu, tớ không nhận được nội dung tài liệu để trả lời câu hỏi. Cậu có thể gửi lại tài liệu được không? 🎓",
                        'method': 'document_context_empty',
                        'strategy': 'document_error',
                        'confidence': response_confidence,  # 🛡️ CAPPED
                        'generation_time': time.time() - start_time,
                        'original_query': original_query,
                        'restored_query': query,
                        'vietnamese_restoration_used': query != original_query,
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
                    response = f"Chào cậu, tớ gặp khó khăn kỹ thuật khi phân tích tài liệu. Cậu có thể thử lại hoặc đặt câu hỏi cụ thể hơn được không?"
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
                    'vietnamese_restoration_used': query != original_query,
                    'personalized': bool(session_id in self._user_context_cache),
                    'document_context_processed': True,
                    'token_info': {
                        'smart_tokens_used': True,
                        'method': 'document_context_processing',
                        'optimal_tokens': optimal_tokens
                    }
                }
            if instruction == 'process_external_api_data':
                logger.debug(f"--- DEBUG START: generate_response (process_external_api_data) ---")
                logger.debug(f"Received context: {json.dumps(context, ensure_ascii=False, indent=2)}")
                
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
                logger.debug(f"--- DEBUG END: generate_response (process_external_api_data) ---")
                return {
                    'response': response,
                    'method': 'external_api_processing',
                    'strategy': 'external_api',
                    'confidence': response_confidence,
                    'generation_time': time.time() - start_time,
                    'original_query': original_query,
                    'restored_query': query,
                    'vietnamese_restoration_used': query != original_query,
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
            response_strategy = 'enhanced_generation'
            raw_confidence = context.get('confidence', 0.5) if context else 0.5
            normalized_confidence = self.confidence_manager.normalize_confidence(raw_confidence, "input_context")
            if context:
                context['confidence'] = normalized_confidence
            instruction = context.get('instruction', '') if context else ''
            if instruction == 'direct_answer_student':
                response, token_info = self._generate_direct_answer_smart(query, context, session_id)
                final_confidence = normalized_confidence
            elif instruction in ['enhance_answer', 'enhance_answer_boosted']:
                response_strategy = 'enhanced_generation' 
                response, token_info = self._generate_smart_response(query, context, session_id, response_strategy) 
                final_confidence = self.confidence_manager.normalize_confidence(normalized_confidence + 0.05, "enhanced_method")
            elif instruction == 'clarification_needed':
                response, token_info = self._generate_clarification_request_smart(query, context, session_id)
                final_confidence = self.confidence_manager.normalize_confidence(0.3, "clarification")
            elif instruction == 'dont_know':
                response, token_info = self._generate_dont_know_response_smart(query, context, session_id)
                final_confidence = self.confidence_manager.normalize_confidence(0.1, "dont_know")
            else:
                response, token_info = self._generate_smart_response(query, context, session_id, response_strategy)
                semantic_score = context.get('semantic_score', 0.5) if context else 0.5
                keyword_score = context.get('keyword_score', 0.0) if context else 0.0
                if context and context.get('emergency_education', False):
                    print(f"🚨 GEMINI: Emergency education mode activated")
                    pass
                if not self._is_education_related(query) and not context.get('force_education_response', False):
                    response = self._get_contextual_out_of_scope_response(conversation_context, session_id)
                    token_info = {'smart_tokens_used': False, 'method': 'predefined_template'}
                    final_confidence = self.confidence_manager.normalize_confidence(0.9, "out_of_scope")
                    if session_id:
                        self.memory.add_interaction(session_id, original_query, response, intent_info, entities)
                    return {
                        'response': response,
                        'method': 'out_of_scope',
                        'confidence': final_confidence,
                        'generation_time': time.time() - start_time,
                        'original_query': original_query,
                        'restored_query': query,
                        'personalized': session_id in self._user_context_cache,
                        'token_info': token_info
                    }
                
                final_confidence = self.confidence_manager.calculate_response_confidence(
                    semantic_score=semantic_score,
                    keyword_score=keyword_score,
                    context_bonus=0.05 if conversation_context.get('recent_conversation_summary') else 0.0,
                    method='two_stage_reranking' if context and context.get('two_stage_reranking_used') else 'hybrid'
                )
            final_response = response or self._get_smart_fallback_with_context(query, intent_info, conversation_context, session_id)
            if not 'final_confidence' in locals():
                final_confidence = self.confidence_manager.normalize_confidence(normalized_confidence, "final_response")
            if session_id:
                print(f"🧠 MEMORY DEBUG: Saving interaction to memory...")
                self.memory.add_interaction(session_id, original_query, final_response, intent_info, entities)
            return {
                'response': final_response,
                'method': f'advanced_rag_student_aware_gemini_{response_strategy}',
                'strategy': response_strategy,
                'conversation_context': conversation_context,
                'confidence': final_confidence,
                'generation_time': time.time() - start_time,
                'original_query': original_query,
                'restored_query': query,
                'vietnamese_restoration_used': query != original_query,
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
            fallback_response = self._get_smart_fallback_with_context(query, intent_info, conversation_context, session_id)
            error_confidence = self.confidence_manager.normalize_confidence(0.1, "error_fallback")
            if session_id:
                self.memory.add_interaction(session_id, original_query, fallback_response, intent_info, entities)
            return {
                'response': fallback_response,
                'method': 'student_context_aware_fallback',
                'error': str(e),
                'confidence': error_confidence,
                'generation_time': time.time() - start_time,
                'original_query': original_query,
                'restored_query': query,
                'personalized': session_id in self._user_context_cache,
                'token_info': {'smart_tokens_used': False, 'method': 'fallback'}
            }
    
    def _build_document_context_prompt(self, query: str, document_text: str, session_id: str = None) -> str:
        system_prompt = self._get_personalized_system_prompt(session_id)
        personal_address = self._get_personal_address(session_id)
        
        conversation_context = self.memory.get_conversation_context(session_id) if session_id else {}
        recent_summary = conversation_context.get('recent_conversation_summary', '')
        
        context_section = ""
        if recent_summary:
            context_section = f"""
    🗣️ NGỮ CẢNH HỘI THOẠI GẦN ĐÂY (để tham khảo):
    {recent_summary}
    """
        task_instruction = "Trả lời câu hỏi của sinh viên một cách chi tiết và chính xác dựa trên tài liệu." # Nhiệm vụ mặc định
        query_lower = query.lower()
        counting_keywords = ['bao nhiêu', 'có mấy', 'đếm', 'số lượng', 'liệt kê']
        
        if any(keyword in query_lower for keyword in counting_keywords):
            logger.info("📄 Detected a counting/listing query. Building a specialized prompt.")
            task_instruction = """
    Thực hiện nhiệm vụ ĐẾM hoặc LIỆT KÊ. Hãy đọc kỹ TOÀN BỘ tài liệu và tìm tất cả các mục được đánh số thứ tự (ví dụ: 1., 2., 3., ...) hoặc các đề mục, đề tài riêng biệt. Sau đó, đếm tổng số lượng các mục đó và trả lời thẳng vào câu hỏi của sinh viên.
    """

        max_doc_length = 10000
        if len(document_text) > max_doc_length:
            document_text = document_text[:max_doc_length] + "\n\n[...tài liệu còn tiếp...]"

        prompt = f"""{system_prompt}

    🎯 **NHIỆM VỤ CỤ THỂ:** {task_instruction}

    ---
    📄 **NỘI DUNG TÀI LIỆU ĐỂ PHÂN TÍCH:**
    {document_text}
    ---

    {context_section}

    ❓ **CÂU HỎI TỪ SINH VIÊN:** "{query}"

    📝 **YÊU CẦU BẮT BUỘC KHI TRẢ LỜI:**
    1.  **Tập trung vào Nhiệm Vụ:** Luôn tuân thủ "NHIỆM VỤ CỤ THỂ" đã nêu ở trên.
    2.  **Nguồn Duy Nhất:** CHỈ được phép sử dụng "NỘI DUNG TÀI LIỆU" để trả lời. Nghiêm cấm bịa đặt hoặc dùng kiến thức ngoài.
    3.  **Trả Lời Thẳng:** Đi thẳng vào câu trả lời, không cần chào hỏi lại.
    4.  **Trường Hợp Bất Khả Kháng:** Nếu sau khi đã đọc kỹ mà tài liệu thực sự không chứa thông tin để hoàn thành nhiệm vụ, hãy nói rõ: "Trong tài liệu được cung cấp, mình không tìm thấy thông tin để trả lời câu hỏi này."

    **Câu trả lời của bạn:**"""
        return prompt
        
    def _build_news_summary_prompt(self, query: str, context: Dict, session_id: str) -> str:
        profile = context.get('profile') if isinstance(context, dict) else None
        student_name = profile.get('full_name', 'bạn').split()[-1] if profile and profile.get('full_name') else 'bạn'  # Lấy tên cuối
        news_articles = context.get("news_data", [])
        logger.info(f"📰 DEBUG: Gemini received {len(news_articles)} news articles")
        if news_articles:
            logger.info(f"📰 DEBUG: First article in Gemini: {news_articles[0]}")
            gemini_titles = [article.get('tieu_de', article.get('title', 'NO_TITLE')) for article in news_articles[:5]]
            logger.info(f"📰 DEBUG: First 5 titles in Gemini: {gemini_titles}")
        if not news_articles:
            return f"Chào {student_name}, hiện tại mình chưa tìm thấy thông báo nào mới cả."
        titles = [(n.get("title") or "").strip() for n in news_articles]
        valid_titles = [t for t in titles if t]
        if not valid_titles:
            return f"Chào {student_name}, không có tin tức hợp lệ để tóm tắt."

        news_titles = [f"- {article.get('title', 'Không có tiêu đề')}" for article in news_articles]
        news_titles_str = "\n".join(news_titles)
        prompt = f"""🎯 NHIỆM VỤ: TÓM TẮT CHỦ ĐỀ CHÍNH TỪ TIÊU ĐỀ TIN TỨC.

        DANH SÁCH TIÊU ĐỀ CẦN XEM XÉT:
        {news_titles_str}

        📝 YÊU CẦU:
        1.  **Đọc kỹ các tiêu đề** để xác định các nhóm chủ đề chính (ví dụ: thi cử, đăng ký học phần, thông báo chung).
        2.  **Viết một đoạn tóm tắt ngắn gọn (khoảng 2-3 câu)** nêu bật các nhóm chủ đề này. Bắt đầu bằng cách chào tên sinh viên (ví dụ: "Chào {student_name}, mình thấy có...").
        3.  **Tuyệt đối không đi vào chi tiết** của bất kỳ tin tức nào.
        4.  **Kết thúc bằng một câu hỏi mở** để gợi ý sinh viên hỏi thêm. Ví dụ: "Bạn muốn xem chi tiết về phần nào không?".
        5.  **Quan trọng:** Chỉ tập trung vào việc tóm tắt các chủ đề từ danh sách tiêu đề được cung cấp.

        Câu trả lời của bạn:
        """
        return prompt

    def _build_detailed_news_prompt(self, query: str, context: Dict, session_id: str) -> str:
        profile = context.get('profile') if isinstance(context, dict) else None
        student_name = profile.get('full_name', 'bạn').split()[-1] if profile and profile.get('full_name') else 'bạn'
        news_articles_from_memory = context.get("news_data_from_memory", [])
        if not news_articles_from_memory and session_id:
            conversation_context = self.memory.get_conversation_context(session_id)
            recent_history = conversation_context.get('history', [])
            if recent_history:
                last_interaction = recent_history[-1]
                intent_info = last_interaction.get('intent_info', {})
                news_articles_from_memory = intent_info.get('news_context', [])
        
        news_content_section = json.dumps(news_articles_from_memory, ensure_ascii=False, indent=2)
        prompt = f"""🎯 NHIỆM VỤ: TÌM VÀ TRẢ LỜI CHI TIẾT VỀ TIN TỨC CỤ THỂ.

    TOÀN BỘ DỮ LIỆU TIN TỨC ĐỂ TRA CỨU:
    {news_content_section}

    ❓ CÂU HỎI CỤ THỂ CỦA SINH VIÊN: "{query}"

    📝 YÊU CẦU:
    1. **Xác định chủ đề:** Đọc câu hỏi của sinh viên để hiểu họ muốn biết về tin tức nào (ví dụ: "lịch thi", "GDQP", "khảo sát").
    2. **Tìm kiếm chính xác:** Duyệt qua "TOÀN BỘ DỮ LIỆU TIN TỨC" để tìm (các) bài viết phù hợp nhất với chủ đề đó.
    3. **Tóm tắt chi tiết:** Trích xuất và trình bày lại những thông tin quan trọng nhất từ bài viết đã tìm thấy, đặc biệt là các mốc thời gian, địa điểm, và hướng dẫn.
    4. **Nếu không tìm thấy:** Trả lời một cách lịch sự, ví dụ: "Trong các thông báo gần đây, mình không thấy có tin nào nói về [chủ đề] cả. Bạn có muốn hỏi về cái khác không?".

    Câu trả lời chi tiết của bạn:
    """
        return prompt

    def _build_completion_prompt(self, incomplete_response: str, original_query: str, context, session_id: str, completion_info: Dict) -> str:        
        system_prompt = self._get_personalized_system_prompt(session_id, context)
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
            - Giữ giọng điệu tự nhiên, lịch sự; không ép mẫu chào/kết thúc
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
            - Giữ xưng hô theo pronoun_style hiện tại (người dùng="bạn", bot="tôi"/"tớ"/"mình")
            - Không ép mẫu chào "Dạ ..." hay câu kết thúc khuôn mẫu
            
            Câu trả lời hoàn chỉnh:"""
        return completion_prompt

    def _build_api_data_prompt(self, api_data: dict, query: str, data_type: str = "general", profile: Optional[Dict] = None) -> str:
        logger.debug(f"--- DEBUG START: _build_api_data_prompt ---")
        logger.debug(f"Data Type: {data_type}")
        logger.debug(f"Profile received: {json.dumps(profile, ensure_ascii=False, indent=2)}")

        if not api_data:
            logger.debug(f"API data is empty. Returning empty prompt section.")
            logger.debug(f"--- DEBUG END: _build_api_data_prompt ---")
            return ""
        
        student_name = "bạn"
        student_mssv = "chưa rõ"
        student_class = "chưa rõ"
        student_faculty = "chưa rõ"
        if profile:
            student_name = profile.get('full_name') or profile.get('name') or student_name
            student_mssv = profile.get('mssv') or student_mssv
            student_class = profile.get('class_name') or profile.get('class') or student_class
            student_faculty = profile.get('faculty') or student_faculty

        student_info_header = f"""
    ---
    👤 THÔNG TIN SINH VIÊN ĐANG HỎI (Sử dụng thông tin này, không hỏi lại):
    - Tên: {student_name}
    - MSSV: {student_mssv}
    - Lớp: {student_class}
    - Khoa: {student_faculty}
    ---
    """     
        if data_type == "grades":
            prompt_section = f"""
    📊 DỮ LIỆU ĐIỂM SỐ SINH VIÊN:
    - Điểm trung bình hệ 4: {api_data.get('avg_diem_hp_4', 'N/A')}
    - Điểm trung bình hệ 10: {api_data.get('avg_diem_hp', 'N/A')}
    - Xếp loại học lực: {api_data.get('xep_loai', 'N/A')}
    - Số tín chỉ đã tích lũy: {api_data.get('so_tin_chi_da_tich_luy', 'N/A')}

    Dựa vào dữ liệu điểm số trên, hãy trả lời câu hỏi của sinh viên một cách tự nhiên và tích cực: "{query}"
    """
        elif data_type == "schedule":
            prompt_section = f"""
    📅 DỮ LIỆU LỊCH HỌC:
    {json.dumps(api_data, ensure_ascii=False, indent=2)}

    Dựa vào lịch học trên, hãy trả lời câu hỏi của sinh viên: "{query}"
    """
        elif data_type == "tuition":
            prompt_section = f"""
    💰 DỮ LIỆU HỌC PHÍ:
    {json.dumps(api_data, ensure_ascii=False, indent=2)}

    Dựa vào thông tin học phí trên, hãy trả lời câu hỏi của sinh viên: "{query}"
    """     
        elif data_type == "curriculum":
            curriculum_tree = api_data.get("curriculum_tree", [])
            credit_summary = api_data.get("credit_summary", {})
            tree_summary = []
            for khoi in curriculum_tree[:2]: # Chỉ lấy 2 khối đầu
                khoi_summary = {
                    "khoi_kien_thuc": khoi.get("khoi_kien_thuc"),
                    "so_nhom_hoc": len(khoi.get("nhom_hoc", [])),
                    "nhom_hoc_sample": []
                }
                for nhom in khoi.get("nhom_hoc", [])[:2]: # Chỉ lấy 2 nhóm đầu
                    nhom_summary = {
                        "nhom_mon_hoc": nhom.get("nhom_mon_hoc"),
                        "tin_chi_yeu_cau": nhom.get("tin_chi_yeu_cau"),
                        "so_mon_hoc": len(nhom.get("danh_sach_mon_hoc", [])),
                        "mon_hoc_dat_sample": [
                            s.get("ten_mon_hoc") for s in nhom.get("danh_sach_mon_hoc", [])
                            if s.get("trang_thai") == "Đạt"
                        ][:2], # Lấy 2 môn đã đạt
                        "mon_hoc_dang_hoc_sample": [
                            s.get("ten_mon_hoc") for s in nhom.get("danh_sach_mon_hoc", [])
                            if s.get("trang_thai") == "Đang học"
                        ][:2] # Lấy 2 môn đang học
                    }
                    khoi_summary["nhom_hoc_sample"].append(nhom_summary)
                tree_summary.append(khoi_summary)
            prompt_section = student_info_header + f"""
    📈 DỮ LIỆU TIẾN ĐỘ HỌC TẬP (CURRICULUM) CỦA SINH VIÊN NÀY (Tên: {student_name}):

    1.  **DỮ LIỆU TÍN CHỈ TỔNG QUAN:**
    ```json
    {json.dumps(credit_summary, ensure_ascii=False, indent=2)}
    ```

    2.  **DỮ LIỆU CÂY CHƯƠNG TRÌNH ĐÀO TẠO ĐẦY ĐỦ (JSON):**
    ```json
    {json.dumps(curriculum_tree, ensure_ascii=False, indent=2)}
    ```
    *Lưu ý cấu trúc JSON:* Dữ liệu là một list các Khối kiến thức. Mỗi khối chứa list các Nhóm học. Mỗi nhóm học chứa list các Môn học (với các trường ten_mon_hoc, so_tin_chi, trang_thai).

    ---
    **NHIỆM VỤ:** Phân tích dữ liệu trên để trả lời câu hỏi của sinh viên `{student_name}` (MSSV: {student_mssv}).
    **CÂU HỎI:** "{query}"

    **HƯỚNG DẪN PHÂN TÍCH VÀ TRẢ LỜI (TUYỆT ĐỐI KHÔNG HỎI LẠI THÔNG TIN SV):**

    * **XÁC ĐỊNH YÊU CẦU:** Đọc kỹ câu hỏi `{query}` để biết sinh viên muốn biết thông tin gì:
    * **Loại 1 (Tổng quan):** Hỏi về tiến độ chung, tổng tín chỉ ("tiến độ học tập", "học được bao nhiêu", "còn bao nhiêu tín chỉ").
    * **Loại 2 (Chi tiết - Môn học):** Hỏi về các môn cụ thể ("còn thiếu môn nào", "cần học môn gì", "liệt kê môn chưa học", "đang học môn nào").

    * **CÁCH TRẢ LỜI TÙY THEO YÊU CẦU:**

    * **Nếu là Loại 1 (Tổng quan):**
        1.  Chào `{student_name}`.
        2.  Dùng **DỮ LIỆU TÍN CHỈ TỔNG QUAN (Mục 1)** để trả lời chính. Ví dụ: "Chào Khang, cậu đã đạt `{credit_summary.get('total_credit')}` / `{credit_summary.get('required_credit')}` tín chỉ yêu cầu."
        3.  *Không cần* liệt kê chi tiết các môn học. Có thể tóm tắt 1-2 khối kiến thức chính nếu muốn.

    * **Nếu là Loại 2 (Chi tiết - Môn học):**
        1.  Chào `{student_name}`.
        2.  **QUAN TRỌNG:** Duyệt qua **TOÀN BỘ DỮ LIỆU CÂY CTĐT ĐẦY ĐỦ (Mục 2)** theo cấu trúc: `khoi_kien_thuc` -> `nhom_hoc` -> `danh_sach_mon_hoc`.
        3.  **LỌC MÔN HỌC:**
            * Nếu hỏi "môn còn thiếu"/"môn chưa học": Tìm tất cả `mon_hoc` có `"trang_thai": "Chưa học"`.
            * Nếu hỏi "môn đang học": Tìm tất cả `mon_hoc` có `"trang_thai": "Đang học"`.
        4.  **TRÌNH BÀY KẾT QUẢ:**
            * Liệt kê rõ ràng danh sách các môn học đã lọc được (dùng `ten_mon_hoc`). Có thể nhóm theo `khoi_kien_thuc` hoặc `nhom_mon_hoc` cho dễ nhìn.
            * Ví dụ: "Chào Khang, mình thấy cậu còn **chưa học** các môn sau:\n- Khối kiến thức ABC:\n  - Môn X (3 TC)\n  - Môn Y (2 TC)\n- Khối kiến thức XYZ:\n  - Môn Z (3 TC)..."
            * Nếu không tìm thấy môn nào theo tiêu chí lọc, hãy nói rõ: "Mình không tìm thấy môn nào [chưa học/đang học] trong chương trình của cậu."
        5.  *Không cần* lặp lại thông tin tổng tín chỉ nếu không được hỏi trực tiếp.

    ---
    **TRẢ LỜI (Bắt đầu bằng cách chào `{student_name}`):**
    """
        else: # data_type general
            prompt_section = student_info_header + f"""
    📋 DỮ LIỆU TỪ HỆ THỐNG:
    {json.dumps(api_data, ensure_ascii=False, indent=2)}

    Dựa vào dữ liệu trên VÀ thông tin sinh viên ở đầu, hãy trả lời câu hỏi của sinh viên một cách tự nhiên: "{query}"
    (Nhớ chào tên sinh viên!)
    """     
        logger.debug(f"Generated prompt_section (first 300 chars): {prompt_section[:300]}...")
        logger.debug(f"--- DEBUG END: _build_api_data_prompt ---")
        return prompt_section

    def _build_enhanced_prompt(self, query: str, context=None, intent_info=None, entities=None, session_id=None):
        logger.debug(f"--- DEBUG START: _build_enhanced_prompt (Session: {session_id}) ---")
        system_prompt = self._get_personalized_system_prompt(session_id, context)
        
        # ✅ FIX #2.1: GET PROFILE FROM CONTEXT
        profile = context.get('profile') if isinstance(context, dict) else None
        if profile:
            logger.debug(f"Profile found in context: {json.dumps(profile, ensure_ascii=False)}")
            logger.info(f"👤 Profile WILL BE USED in prompt for session {session_id}")
        else:
            logger.debug(f"No profile found in context.")
        
        personal_address = self._get_personal_address(session_id)
        context_info = str(context.get('response', '')) if isinstance(context, dict) else str(context or '')
        
        # ✅ FIX #2.2: GET MEMORY CONTEXT
        memory_context = self.memory.get_conversation_context(session_id) if session_id else {}
        recent_summary = memory_context.get('recent_conversation_summary', '')
        
        # ✅ FIX #2.3: BUILD MEMORY SECTION FROM HISTORY
        memory_section = ""
        if memory_context and memory_context.get('history'):
            history = memory_context['history']
            # Lấy 3 câu gần nhất
            recent_messages = history[-3:] if len(history) >= 3 else history
            
            if recent_messages:
                history_text = ""
                for msg in recent_messages:
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')
                    if role == 'user':
                        history_text += f"- Sinh viên: {content[:150]}...\n"
                    else:
                        history_text += f"- ChatBDU: {content[:150]}...\n"
                
                memory_section = f"""
    🗣️ NGỮ CẢNH HỘI THOẠI (3 câu gần nhất):
    {history_text}
    
    💡 LƯU Ý: Sinh viên đang hỏi tiếp theo dựa trên ngữ cảnh trên. Hãy trả lời mạch lạc, tự nhiên, không lặp lại thông tin đã nói.
    """
                logger.info(f"✅ Memory section built with {len(recent_messages)} messages")
        
        # Context section từ summary (legacy support)
        context_section = ""
        if recent_summary and not memory_section:
            context_section = f"""
    🗣️ NGỮ CẢNH HỘI THOẠI GẦN ĐÂY:
    {recent_summary}

    💡 LƯU Ý: Dựa vào ngữ cảnh cuộc hội thoại trên, hãy trả lời câu hỏi tiếp theo của sinh viên một cách tự nhiên và mạch lạc. Tránh lặp lại thông tin đã thảo luận, nhưng có thể tham khảo để tạo câu trả lời liền mạch.
    """
        
        # ✅ FIX #2.4: BUILD PROFILE SECTION
        profile_section = ""
        if profile:
            full_name = profile.get('full_name', '')
            mssv = profile.get('mssv', '')
            class_name = profile.get('class_name', '')
            faculty = profile.get('faculty', '')
            
            profile_section = f"""
    👤 THÔNG TIN SINH VIÊN:
    - Tên: {full_name}
    - MSSV: {mssv}
    - Lớp: {class_name}
    - Khoa: {faculty}
    
    💡 LƯU Ý: Đây là thông tin của sinh viên đang hỏi. Hãy sử dụng để trả lời cá nhân hóa (gọi tên, đề cập lớp/khoa nếu phù hợp).
    """
        
        profile_prompt = f"\n👤 Profile thêm: {json.dumps(profile, ensure_ascii=False)}" if profile and not profile_section else ""

        api_data_section = ""
        if isinstance(context, dict) and 'api_data' in context:
            api_data = context['api_data']
            data_type = context.get('data_type', 'general')
            api_data_section = self._build_api_data_prompt(api_data, query, data_type, profile=profile)
        tutor_prompt = ""
        if isinstance(context, dict) and context.get("instruction") == "tutor_mode":
            student_data = context.get("student_data", {})
            gpa_4 = student_data.get("grades", {}).get("gpa_4", 0)
            gpa_10 = student_data.get("grades", {}).get("gpa_10", 0)
            credits_completed = student_data.get("credits", {}).get("completed_credits", 0)
            total_credits = student_data.get("credits", {}).get("total_credits", 0)
            rl_xep_loai = student_data.get("rl_grades", {}).get("xep_loai", "Chưa có")
            analysis = []
            if isinstance(gpa_4, (int, float)) and gpa_4 < 3.0:
                analysis.append(f"- GPA {gpa_4} (hệ 4) dưới 3.0: Tập trung cải thiện bằng cách phân tích môn yếu (kiểm tra bảng điểm chi tiết nếu có). Lập lịch ôn 2-3 giờ/ngày cho từng môn, ưu tiên công thức toán/lập trình nếu khoa CNTT.")
                analysis.append("- Tài liệu: Sử dụng Khan Academy cho toán cơ bản, hoặc Coursera 'Learning How to Learn' miễn phí. Theo dõi tiến độ hàng tuần qua app như Notion.")
            elif isinstance(gpa_4, (int, float)) and gpa_4 < 2.5:
                analysis.append(f"- GPA {gpa_4} thấp hơn 2.5: Cần hỗ trợ ngay - gặp cố vấn học tập khoa {student_data.get('profile', {}).get('faculty', 'BDU')} để đăng ký tutor hoặc khóa bổ sung.")
                analysis.append("- Hành động: Giảm tải môn học kỳ sau, tập trung 1-2 môn chính. Theo dõi sức khỏe để tránh kiệt sức.")
            
            if total_credits > 0 and credits_completed / total_credits < 0.7:
                analysis.append(f"- Tín chỉ hoàn thành {credits_completed}/{total_credits} ({credits_completed/total_credits*100:.1f}%): Ưu tiên đăng ký môn dễ đạt trước, tránh overload >18 tín chỉ/kỳ.")
            
            if rl_xep_loai != "Tốt" and rl_xep_loai != "Xuất sắc":
                analysis.append(f"- Điểm rèn luyện {rl_xep_loai}: Tham gia 1-2 hoạt động ngoại khóa/tháng (câu lạc bộ khoa CNTT) để tăng điểm chuyên cần và xã hội.")
            
            tutor_prompt = f"""
    💡 CHẾ ĐỘ GIA SƯ: Phân tích data sinh viên để tư vấn cải thiện cụ thể. Dựa data real: GPA {gpa_4} (hệ 4), {gpa_10} (hệ 10); Tín chỉ: {credits_completed}/{total_credits}; Rèn luyện: {rl_xep_loai}.

    📊 PHÂN TÍCH VÀ HƯỚNG DẪN CẢI THIỆN:
    {chr(10).join(analysis)}

    🎯 LỜI KHUYÊN CHUNG:
    - Theo dõi tiến độ: Dùng Google Sheets ghi điểm từng bài kiểm tra hàng tuần.
    - Nếu cần hỗ trợ: Liên hệ phòng Đào tạo BDU hoặc group lớp {student_data.get('profile', {}).get('class', '24TH01')} trên Zalo.
    - Không bịa data, giữ trung thực: Nếu data thiếu, gợi ý kiểm tra API lại.

    Trả lời ngắn gọn, khả thi, kết thúc bằng câu hỏi cụ thể như "Bạn muốn kế hoạch ôn môn nào trước?".
    """
        
        prompt = f"""{system_prompt}
        
    CÂU HỎI: {query}
    THÔNG TIN: {context_info}{profile_prompt}

    {profile_section}

    {memory_section}

    {context_section}

    {api_data_section}

    {tutor_prompt}

    YÊU CẦU:
    - Dùng profile để trả lời cá nhân hóa (tên, lớp, khoa).
    - Dùng memory để trả lời follow-up questions.
    - Không lặp 'AI assistant của BDU', giữ tự nhiên.
    - Không bịa data.
    - Giữ cách xưng hô thân thiện (bạn-mình, cậu-tớ).
    - Tạo câu trả lời mạch lạc, tự nhiên, tránh lặp lại thông tin đã thảo luận.
    - Nếu cần, có thể kết thúc bằng một câu hỏi mở như "Bạn có cần mình giúp gì thêm không?".

    Trả lời:"""

        logger.debug(f"Final prompt built (first 500 chars): {prompt[:500]}...")
        logger.debug(f"Final prompt built (last 300 chars): ...{prompt[-300:]}")
        logger.debug(f"--- DEBUG END: _build_enhanced_prompt ---")

        return prompt

    def _build_external_api_prompt(self, query, api_data, personal_address, recent_summary=""):        
        student_info = api_data.get('student_info', {})
        ten_sinh_vien = student_info.get('student_name', personal_address)
        mssv = student_info.get('mssv', '')
        lop = student_info.get('class', '')
        khoa = student_info.get('faculty', '')
        
        system_prompt = f"""Bạn là trợ lý AI thông minh của trường đại học, chuyên hỗ trợ sinh viên.

    THÔNG TIN SINH VIÊN:
    - Tên: {ten_sinh_vien}
    - MSSV: {mssv}
    - Lớp: {lop}
    - Khoa: {khoa}

    Hãy trả lời câu hỏi của sinh viên một cách thân thiện, chính xác và hữu ích."""

        context_section = ""
        if recent_summary:
            context_section = f"""
    🗣️ NGỮ CẢNH HỘI THOẠI GẦN ĐÂY:
    {recent_summary}
    """

        prompt = f"""{system_prompt}

    {context_section}

    📝 CÂU HỎI CỦA SINH VIÊN:
    {query}

    Hãy trả lời câu hỏi một cách tự nhiên và hữu ích."""

        return prompt
    
    def _generate_direct_answer_smart(self, query, context, session_id):
        text = context.get('db_answer') or context.get('response') or context.get('fallback_response') or ''
        return text, {'smart_tokens_used': False, 'method': 'direct_passthrough'}

    def _generate_smart_response(self, query: str, context=None, session_id=None, strategy='balanced'):        
        prompt = self._build_enhanced_prompt(query, context, None, None, session_id)
        data_type = context.get('data_type', 'general') if isinstance(context, dict) else 'general'
        
        optimal_tokens = self.token_manager.calculate_optimal_tokens(
            len(prompt), 
            complexity_hint=strategy
        )
        if data_type == "curriculum":
            optimal_tokens = max(optimal_tokens, 3000) # Tăng lên 3000 tokens
            print(f"🧠 SMART TOKENS (CURRICULUM): {optimal_tokens} tokens")
        else:
            print(f"🧠 SMART TOKENS: {optimal_tokens} tokens")
        response = self._call_gemini_api_with_smart_tokens(prompt, strategy, optimal_tokens, session_id)
        if not response:
            return self._get_smart_fallback_with_context(query, None, {}, session_id), {
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
        response = self._post_process_response(response, query, context, strategy, {}, session_id)
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
            merged = self._merge_incomplete_and_completion(incomplete_response, completion)
            return merged
        return None
    
    def _merge_incomplete_and_completion(self, incomplete: str, completion: str) -> str:
        completion = completion.strip()
        completion = re.sub(r'^(dạ\s+(thầy|cô|sinh viên),?\s*)', '', completion, flags=re.IGNORECASE)
        incomplete_words = incomplete.split()
        if incomplete_words:
            last_word = incomplete_words[-1].lower()
            if last_word in ['và', 'với', 'để', 'khi', 'nếu', 'tại', 'về', 'cho', 'trong', 'của', 'từ']:
                incomplete = ' '.join(incomplete_words[:-1])
        merged = incomplete.rstrip() + ' ' + completion.lstrip()
        return merged
    def _get_personal_address(self, session_id: str) -> str:        
        user_context = self._user_context_cache.get(session_id, {}) if session_id else {}
        preferences = user_context.get('preferences', {}) if isinstance(user_context, dict) else {}
        pronoun_style = (preferences or {}).get('pronoun_style', 'default')
        return 'bạn'
    
    def _call_gemini_api_with_smart_tokens(self, prompt: str, strategy: str, max_tokens: int, session_id: str = None) -> Optional[str]:
        max_retries = len(self.key_manager.keys) if self.key_manager.keys else 1 # Thử tối đa bằng số key, ít nhất 1 lần
        attempt = 0
        logger.debug(f"--- DEBUG START: _call_gemini_api_with_smart_tokens ---")
        logger.debug(f"Strategy: {strategy}, Max Tokens: {max_tokens}, Session: {session_id}")
        logger.debug(f"Prompt to send (first 500 chars): {prompt[:500]}...")
        logger.debug(f"Prompt to send (last 300 chars): ...{prompt[-300:]}")
        while attempt < max_retries:
            api_key_to_use = self.key_manager.get_key()
            if not api_key_to_use:
                logger.error("CRITICAL: All Gemini API keys are currently marked as rate-limited. Aborting call.")
                personal_address = self._get_personal_address(session_id)
                logger.debug(f"--- DEBUG END: _call_gemini_api_with_smart_tokens (All keys rate-limited) ---")
                # Trả về thông báo lỗi cụ thể hơn
                return f"Chào cậu, hiện tại tất cả các kết nối đến trợ lý AI đều đang tạm thời bị giới hạn do quá nhiều yêu cầu. Vui lòng thử lại sau khoảng 1 phút nữa nhé. 😥"
            logger.info(f"Attempt {attempt + 1}/{max_retries} using Key: ...{api_key_to_use[-4:]}")

            try:
                headers = {'Content-Type': 'application/json'}
                strategy_temp_adjustments = {
                    'quick_clarify': -0.2, 'direct_enhance': 0.0, 'enhanced_generation': +0.2,
                    'completion': -0.3, 'balanced': 0.0, 'document_context': +0.1,
                    'two_stage_reranking': +0.05,
                    'external_api_processing': 0.0, # Giữ nguyên temperature cho API data
                    'student_profile_processing': -0.1 # Giảm nhẹ temperature cho profile để chính xác hơn
                }
                temp_adjustment = strategy_temp_adjustments.get(strategy, 0.0)
                base_temp = self.default_generation_config.get("temperature", 0.55)
                final_temperature = max(0.1, min(1.0, base_temp + temp_adjustment))
                base_top_p = self.default_generation_config.get("topP", 0.85)

                config = {
                    "temperature": final_temperature,
                    "maxOutputTokens": max_tokens,
                    "topP": base_top_p
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
                response = requests.post(url, headers=headers, json=data, timeout=30) # Timeout 30 giây
                if response.status_code == 200:
                    result = response.json()
                    if 'candidates' in result and result['candidates']:
                        candidate = result['candidates'][0]
                        if 'finishReason' in candidate and candidate['finishReason'] == 'SAFETY':
                            logger.warning(f"🚨 Gemini response blocked due to SAFETY reasons (Key: ...{api_key_to_use[-4:]}). Attempt {attempt + 1}/{max_retries}. Trying next key...")
                            attempt += 1
                            time.sleep(0.1)
                            continue # Thử key tiếp theo
                        if 'content' in candidate and 'parts' in candidate['content']:
                            response_text = candidate['content']['parts'][0]['text']
                            logger.debug(f"✅ Gemini API Success (Key: ...{api_key_to_use[-4:]})")
                            logger.debug(f"Response received (first 300 chars): {response_text[:300]}...")
                            logger.debug(f"--- DEBUG END: _call_gemini_api_with_smart_tokens (Success) ---")
                            return response_text
                        else:
                            logger.warning(f"⚠️ Gemini API returned 200 but no valid content (Key: ...{api_key_to_use[-4:]}). Attempt {attempt + 1}/{max_retries}. Trying next key...")
                            attempt += 1
                            time.sleep(0.2)
                            continue # Thử key tiếp theo
                    else:
                        logger.warning(f"⚠️ Gemini API returned 200 but no candidates (Key: ...{api_key_to_use[-4:]}). Attempt {attempt + 1}/{max_retries}. Trying next key...")
                        attempt += 1
                        time.sleep(0.2)
                        continue # Thử key tiếp theo
                elif response.status_code == 429: # Rate Limit
                    self.key_manager.report_failure(api_key_to_use) # Đánh dấu key bị rate limit
                    logger.warning(f"Rate limit (429) on key ...{api_key_to_use[-4:]}. Attempt {attempt + 1}/{max_retries}. Trying next key...")
                    attempt += 1
                    time.sleep(0.5) # Chờ lâu hơn chút sau 429
                    continue # Thử key tiếp theo
                else:
                    logger.error(f"Gemini API Error {response.status_code} with key ...{api_key_to_use[-4:]}: {response.text}")
                    logger.warning(f"API Error {response.status_code}. Attempt {attempt + 1}/{max_retries}. Trying next key...")
                    attempt += 1
                    time.sleep(0.3) # Độ trễ nhỏ trước khi thử key khác
                    continue # Thử key tiếp theo
            except requests.exceptions.Timeout:
                logger.error(f"Gemini API call timed out with key ...{api_key_to_use[-4:]}. Attempt {attempt + 1}/{max_retries}. Trying next key...")
                attempt += 1
                time.sleep(0.8) # Chờ lâu hơn sau timeout
                continue # Thử key tiếp theo
            except Exception as e:
                logger.error(f"Unexpected error during API call with key ...{api_key_to_use[-4:]}: {str(e)}. Attempt {attempt + 1}/{max_retries}. Trying next key...")
                attempt += 1
                time.sleep(0.5)
                continue # Thử key tiếp theo

        logger.error(f"All {max_retries} retry attempts failed (due to errors like 429, 503, timeout, safety blocks, etc.).")
        personal_address = self._get_personal_address(session_id)
        logger.debug(f"--- DEBUG END: _call_gemini_api_with_smart_tokens (All retries failed) ---")
        return f"Chào cậu, hiện tại trợ lý AI đang gặp sự cố kết nối hoặc quá tải sau khi thử {max_retries} lần. {personal_address.title()} vui lòng thử lại sau ít phút nhé."
    
    def _generate_clarification_request_smart(self, query, context, session_id=None):        
        personal_address = self._get_personal_address(session_id)
        clarification_templates = {
            'friendly': f"Để mình có thể hỗ trợ tốt nhất, {personal_address} có thể chia sẻ thêm chi tiết được không? Mình luôn sẵn lòng giúp!",
            'brief': f"Chào cậu, cần thêm thông tin chi tiết ạ. 🎓",
            'technical': f"Chào cậu, để cung cấp hướng dẫn kỹ thuật chính xác, {personal_address} vui lòng cung cấp thêm thông số và yêu cầu cụ thể ạ.",
            'detailed': f"Chào cậu, để tớ có thể đưa ra câu trả lời toàn diện và chi tiết nhất, {personal_address} có thể bổ sung thêm về bối cảnh, mục đích sử dụng, và các yêu cầu cụ thể không? Điều này sẽ giúp tớ hỗ trợ {personal_address} một cách hiệu quả nhất.",
            'professional': f"Chào cậu, để tớ hỗ trợ chính xác nhất, {personal_address} có thể nói rõ hơn về vấn đề cần hỗ trợ không? 🎓"
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
        response = f"Xin lỗi {personal_address}, mình chưa có thông tin về vấn đề này. Bạn có thể liên hệ {dept} qua email {contact} để được hỗ trợ nhé."
        token_info = {
            'smart_tokens_used': False,
            'method': 'dont_know_template_v2',
            'suggested_department': dept,
            'personal_addressing': personal_address,
            'confidence_managed': True
        }
        return response, token_info
    
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
            test_prompt = "Test ngắn cho sinh viên"
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
                }
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
    def _post_process_response(self, response, query, context, strategy, conversation_context, session_id=None):
        if not response:
            return response
        personal_address = self._get_personal_address(session_id)
        response = re.sub(r'\*\*\d+\.\s*', '', response)
        response = re.sub(r'^\s*\d+\.\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'^\s*[•\-\*]\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'\*\*(.*?)\*\*', r'\1', response)
        if session_id and self._should_strip_greeting(session_id):
            response = self._strip_greeting_and_closing(response, personal_address)
        return response.strip()
    def _get_smart_fallback_with_context(self, query, intent_info, conversation_context, session_id=None):        
        personal_address = self._get_personal_address(session_id)
        user_context = self._user_context_cache.get(session_id, {}) if session_id else {}
        department_name = user_context.get('department_name', '')
        intent_name = intent_info.get('intent', 'general') if intent_info else 'general'
        if conversation_context.get('context_summary'):
            summary = conversation_context['context_summary']
            context_fallbacks = {
                'Đang hỏi về thông tin sinh viên': f"Chào cậu, về thông tin sinh viên, tớ có thể hỗ trợ thêm! 📋 {personal_address.title()} có cần hỗ trợ thêm gì không?",
                'Đang hỏi về lịch học': f"Chào cậu, về lịch học, tớ có thể hỗ trợ thêm! 📊 {personal_address.title()} có cần hỗ trợ thêm gì không?",
                'Đang hỏi về điểm số': f"Chào cậu, về điểm số, tớ có thể hỗ trợ thêm! 📚 {personal_address.title()} có cần hỗ trợ thêm gì không?",
                'Đang hỏi về học phí': f"Chào cậu, về học phí, tớ có thể hỗ trợ thêm! 🏆 {personal_address.title()} có cần hỗ trợ thêm gì không?"
            }
            if summary in context_fallbacks:
                return context_fallbacks[summary]
        smart_fallbacks = {
            'greeting': f"Chào {personal_address}! 👋 Mình có thể giúp gì cho bạn về BDU không?",
            'general': f"Chào cậu, tớ sẵn sàng hỗ trợ các vấn đề liên quan đến BDU! 🎓 {personal_address.title()} có cần hỗ trợ thêm gì không?"
        }
        if department_name and intent_name == 'general':
            smart_fallbacks['general'] = f"Chào cậu, tớ sẵn sàng hỗ trợ các vấn đề liên quan đến BDU và ngành {department_name}! 🎓 {personal_address.title()} có cần hỗ trợ thêm gì không?"
        return smart_fallbacks.get(intent_name, smart_fallbacks['general'])
    def _get_contextual_out_of_scope_response(self, conversation_context, session_id=None):        
        personal_address = self._get_personal_address(session_id)
        user_context = self._user_context_cache.get(session_id, {}) if session_id else {}
        department_name = user_context.get('department_name', '')
        if conversation_context.get('context_summary'):
            if department_name:
                return f"Mình chỉ hỗ trợ các vấn đề liên quan đến học tập tại BDU thôi. Bạn có câu hỏi nào khác về trường không?"
            else:
                return f"Mình chỉ hỗ trợ các vấn đề liên quan đến học tập tại BDU thôi. Bạn có câu hỏi nào khác về trường không?"
        if department_name:
            return f"Mình chỉ hỗ trợ các vấn đề liên quan đến học tập tại BDU thôi. Bạn có câu hỏi nào khác về ngành {department_name} không?"
        else:
            return f"Mình chỉ hỗ trợ các vấn đề liên quan đến học tập tại BDU thôi. Bạn có câu hỏi nào khác về ngành {department_name} không?"

    def _is_education_related(self, query):
        education_keywords = [
            'trường', 'học', 'sinh viên', 'tuyển sinh', 'học phí', 'ngành',
            'đại học', 'bdu', 'đăng ký', 'môn học', 'tín chỉ', 
            'lịch thi', 'kỳ thi', 'điểm', 'điểm danh', 'vắng',
            'thời khóa biểu', 'lịch học', 'phòng học', 'tiết học',
            'học lại', 'cải thiện điểm', 'thi lại', 'nâng điểm',
            'điểm trung bình', 'trung bình', 'tính điểm', 'điểm quá trình',
            'điểm thi', 'điểm cuối kỳ', 'điểm giữa kỳ',
            'khối lượng', 'tối thiểu', 'chương trình', 'học kỳ', 'năm học',
            'tốt nghiệp', 'lễ tốt nghiệp', 'xét tốt nghiệp', 'bằng cấp',
            'văn bằng', 'cử nhân', 'cấp bằng', 'nhận bằng',
            'kỷ luật', 'danh sách', 'theo quy định', 'quy định về', 
            'thủ tục', 'điều kiện', 'yêu cầu', 'mở lớp',
            'như thế nào', 'bao nhiêu', 'là ai', 'ai là', 'làm gì', 'ở đâu',
            'khi nào', 'có được', 'cần gì', 'phải làm'
        ]
        if not query:
            return False        
        query_lower = query.lower()
        return any(kw in query_lower for kw in education_keywords)