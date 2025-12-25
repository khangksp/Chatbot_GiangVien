"""
Score Tools - Công cụ xem điểm số và bảng điểm
Tools để lấy danh sách điểm và chi tiết điểm thành phần các môn học

🎯 QUAN TRỌNG: Tools này dành riêng cho ĐIỂM SỐ (BẢNG ĐIỂM)
   KHÔNG dùng cho điểm danh/tiến độ học tập (dùng StudentCourseDetailTool)

📊 2 API chính:
   1. GET /odp/nhom-hoc/progress?nkhk={nkhk} - Lấy danh sách môn & ma_nhom
   2. GET /odp/bang-diem?ma_nhom={ma_nhom} - Chi tiết điểm 1 môn (TV, B1, K1, T1)
"""
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

# ✅ Import hàm xử lý semester từ external_api_service
from ai_models.external_api_service import _extract_semester_from_query

from .base_tool import BDUBaseTool

logger = logging.getLogger(__name__)


# ================================
# HELPER FUNCTIONS
# ================================

def extract_course_name_from_query(query: str) -> Optional[str]:
    """
    Extract tên môn từ query
    
    Examples:
        "điểm chi tiết môn Cấu trúc dữ liệu" -> "Cấu trúc dữ liệu"
        "xem điểm môn CTDL kỳ trước" -> "CTDL"
        "điểm thành phần môn toán" -> "toán"
    """
    if not query:
        return None
    
    query_lower = query.lower().strip()
    
    # Pattern matching để extract tên môn
    patterns = [
        r'điểm.*?môn\s+(.+?)(?:\s+kỳ|\s+học\s+kỳ|$)',          # "điểm chi tiết môn X kỳ trước"
        r'chi\s*tiết.*?môn\s+(.+?)(?:\s+kỳ|\s+học\s+kỳ|$)',    # "chi tiết điểm môn X"
        r'thành\s*phần.*?môn\s+(.+?)(?:\s+kỳ|\s+học\s+kỳ|$)',  # "điểm thành phần môn X"
        r'xem.*?môn\s+(.+?)(?:\s+kỳ|\s+học\s+kỳ|$)',           # "xem điểm môn X"
        r'môn\s+(.+?)(?:\s+kỳ|\s+học\s+kỳ|\s+có|\s+được|$)',   # "môn X kỳ trước"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, query_lower)
        if match:
            course_name = match.group(1).strip()
            # Loại bỏ các từ khóa thừa
            course_name = re.sub(r'\b(học|hoc|nào|nao|bao nhiêu|bao nhieu)\b', '', course_name).strip()
            if len(course_name) > 2:  # Tên môn ít nhất 3 ký tự
                logger.info(f"✅ Extracted course name: '{course_name}' from query: '{query}'")
                return course_name
    
    # Fallback: loại bỏ keywords
    remove_keywords = [
        'điểm', 'diem', 'chi tiết', 'chi tiet', 'xem', 'thành phần', 'thanh phan',
        'môn', 'mon', 'học', 'hoc', 'k1', 't1', 'tv', 'b1', 'kỳ trước', 'ky truoc',
        'kỳ này', 'ky nay', 'giữa kỳ', 'giua ky', 'cuối kỳ', 'cuoi ky',
        'thư viện', 'thu vien', 'của', 'cua', 'tôi', 'toi', 'em'
    ]
    
    remaining = query_lower
    for keyword in remove_keywords:
        remaining = remaining.replace(keyword, ' ')
    
    remaining = ' '.join(remaining.split()).strip()
    
    if len(remaining) > 2:  # Tên môn ít nhất 3 ký tự
        logger.info(f"✅ Extracted course name (fallback): '{remaining}' from query: '{query}'")
        return remaining
    
    return None


def find_ma_nhom_from_progress(
    jwt_token: str,
    course_name: str, 
    nkhk: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    🎯 Tìm ma_nhom từ API PROGRESS (Dùng chung cho cả Điểm danh và Điểm thi)
    URL: /odp/nhom-hoc/progress?nkhk={nkhk}
    
    ⚠️ API này trả về ma_nhom FULL format: {ma_mon}_{nkhk}_{ma_nhom}
    VD: "INF1463_24253_02"
    
    Args:
        jwt_token: JWT token
        course_name: Tên môn học cần tìm
        nkhk: Mã học kỳ (optional, nếu không có sẽ tìm trong 3 kỳ gần nhất)
    
    Returns:
        Dict chứa {ma_nhom, ten_mon, nkhk, raw_data} hoặc None
    """
    if not course_name:
        return None
    
    try:
        from ai_models.external_api_service import external_api_service
        import requests
        
        # Xác định danh sách NKHK cần tìm
        if nkhk:
            nkhk_list = [nkhk]
            logger.info(f"🔍 Searching in specific semester: {nkhk}")
        else:
            # ✅ Tìm trong 3 kỳ gần nhất (current + 2 previous)
            current = external_api_service.get_latest_nkhk(jwt_token)
            previous = external_api_service.get_previous_nkhk(jwt_token)
            
            nkhk_list = [current]
            if previous:
                nkhk_list.append(previous)
            
            # Thêm kỳ cũ hơn nữa (nếu có)
            if previous:
                try:
                    # Tính kỳ trước kỳ previous
                    prev_int = int(previous)
                    # Giảm suffix xuống (3->2, 2->1, 1->3 của năm trước)
                    suffix = prev_int % 10
                    if suffix > 1:
                        # Cùng năm học, kỳ trước
                        even_older = str(prev_int - 1)
                    else:
                        # Kỳ 3 của năm trước
                        year_part = prev_int // 10
                        # Giảm năm xuống 1
                        year1 = (year_part // 100) - 1
                        year2 = (year_part % 100) - 1
                        even_older = f"{year1:02d}{year2:02d}3"
                    
                    nkhk_list.append(even_older)
                except:
                    pass
            
            logger.info(f"🔍 Searching in {len(nkhk_list)} semesters: {nkhk_list}")
        
        best_match_overall = None
        best_score_overall = 0
        
        # Normalize tên môn để so sánh
        def normalize(text: str) -> str:
            import unicodedata
            if not text:
                return ""
            # Loại bỏ dấu tiếng Việt
            text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode('utf-8')
            return ' '.join(text.lower().split())
        
        course_name_normalized = normalize(course_name)
        course_name_lower = course_name.lower().strip()
        
        # Tìm kiếm trong từng học kỳ
        for search_nkhk in nkhk_list:
            if not search_nkhk:
                continue
            
            logger.info(f"🔍 Searching in semester {search_nkhk}...")
            
            # Gọi API lấy danh sách PROGRESS
            try:
                api_url = "https://cds.bdu.edu.vn/student/api/v1/odp/nhom-hoc/progress"
                headers = {"Authorization": f"Bearer {jwt_token}"}
                params = {"nkhk": search_nkhk}
                
                res = requests.get(api_url, headers=headers, params=params, timeout=10)
                
                if res.status_code != 200:
                    logger.warning(f"⚠️ API failed for semester {search_nkhk}: {res.status_code}")
                    continue
                
                courses = res.json()
                
                if not courses:
                    logger.info(f"ℹ️ No courses found in semester {search_nkhk}")
                    continue
                
                logger.info(f"✅ Found {len(courses)} courses in semester {search_nkhk}")
                
            except Exception as e:
                logger.error(f"❌ Error fetching progress for {search_nkhk}: {e}")
                continue
            
            # Fuzzy matching với từng môn
            for course in courses:
                ten_mon = course.get('ten_mon_hoc', '')
                ma_nhom = course.get('ma_nhom', '')  # ✅ Đây là FULL ma_nhom
                
                if not ten_mon or not ma_nhom:
                    continue
                
                ten_mon_normalized = normalize(ten_mon)
                ten_mon_lower = ten_mon.lower()
                
                # Tính điểm matching
                score = 0
                
                # 1. Exact match (100 điểm)
                if course_name_normalized == ten_mon_normalized:
                    score = 100
                    logger.info(f"🎯 Exact match: '{course_name}' == '{ten_mon}'")
                
                # 2. Contains (85 điểm)
                elif course_name_normalized in ten_mon_normalized:
                    score = 85
                    logger.info(f"✅ Contains match: '{course_name}' in '{ten_mon}'")
                
                # 3. Reverse contains (75 điểm)
                elif ten_mon_normalized in course_name_normalized:
                    score = 75
                    logger.info(f"✅ Reverse contains: '{ten_mon}' in '{course_name}'")
                
                # 4. Case-insensitive contains (65 điểm)
                elif course_name_lower in ten_mon_lower:
                    score = 65
                    logger.info(f"✅ Case-insensitive match: '{course_name}' ~ '{ten_mon}'")
                
                # 5. Acronym matching (50 điểm)
                else:
                    # Lấy chữ cái đầu của mỗi từ trong tên môn
                    words = ten_mon_normalized.split()
                    if len(words) > 1:
                        acronym = ''.join([w[0] for w in words if w])
                        if course_name_normalized.replace(' ', '') == acronym:
                            score = 50
                            logger.info(f"✅ Acronym match: '{course_name}' ~ '{acronym}' from '{ten_mon}'")
                
                # Cập nhật best match
                if score > best_score_overall:
                    best_score_overall = score
                    best_match_overall = {
                        'ma_nhom': ma_nhom,  # FULL ma_nhom từ API
                        'ten_mon': ten_mon,
                        'nkhk': search_nkhk,
                        'raw_data': course
                    }
            
            # Nếu tìm thấy exact match, dừng tìm kiếm
            if best_score_overall >= 85:
                logger.info(f"🎯 Found good match, stopping search")
                break
        
        # Trả về kết quả
        if best_match_overall and best_score_overall >= 50:
            logger.info(
                f"✅ Found match: '{best_match_overall['ten_mon']}' "
                f"(ma_nhom: {best_match_overall['ma_nhom']}, "
                f"semester: {best_match_overall['nkhk']}, "
                f"score: {best_score_overall})"
            )
            return best_match_overall
        
        logger.warning(f"❌ No match found for course: '{course_name}'")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error in find_ma_nhom_from_progress: {e}", exc_info=True)
        return None


# ================================
# 1. STUDENT SCORE LIST TOOL
# ================================
class StudentScoreListTool(BDUBaseTool):
    """
    Tool lấy DANH SÁCH ĐIỂM các môn trong học kỳ (BẢNG ĐIỂM)
    
    🎯 Sử dụng API: GET /odp/nhom-hoc/progress?nkhk={nkhk}
    
    ⚠️ LƯU Ý: Tool này hiển thị tổng quan các môn
       Để xem chi tiết điểm thành phần (TV, K1, T1), dùng get_student_score_detail
    """
    
    name: str = "get_student_score_list"
    description: str = """Lấy DANH SÁCH các môn học trong học kỳ với thông tin tổng quan.

🎯 Sử dụng khi hỏi:
- "Xem danh sách môn học kỳ này"
- "Các môn tôi đang học"
- "Môn nào kỳ trước"
- "Danh sách môn học kỳ 3"

📊 Trả về: Danh sách các môn với tiến độ học tập

⚠️ KHÔNG dùng cho:
- Điểm danh chi tiết (dùng get_student_course_detail)
- Điểm thi chi tiết TV/K1/T1 (dùng get_student_score_detail)
"""
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "", nkhk: Optional[str] = None) -> str:
        """
        Execute tool to get course list
        
        Args:
            query: User query (để parse semester)
            nkhk: Mã học kỳ (optional)
        
        Returns:
            Formatted course list
        """
        if not self.api_service or not self.jwt_token:
            return "❌ Lỗi: Chưa đăng nhập."
        
        try:
            # 1. Xác định NKHK
            if nkhk:
                final_nkhk = nkhk
                logger.info(f"📅 Using provided NKHK: {final_nkhk}")
            else:
                # Parse từ query
                extracted_nkhk = _extract_semester_from_query(query.lower()) if query else None
                
                if extracted_nkhk:
                    final_nkhk = extracted_nkhk
                    logger.info(f"📅 Extracted NKHK from query: {final_nkhk}")
                else:
                    # Detect từ keywords
                    query_lower = query.lower()
                    
                    if any(kw in query_lower for kw in ['kỳ trước', 'ky truoc', 'học kỳ trước', 'hoc ky truoc']):
                        final_nkhk = self.api_service.get_previous_nkhk(self.jwt_token)
                        logger.info(f"📅 Using previous semester: {final_nkhk}")
                    else:
                        # Default: kỳ hiện tại
                        final_nkhk = self.api_service.get_latest_nkhk(self.jwt_token)
                        logger.info(f"📅 Using current semester: {final_nkhk}")
            
            if not final_nkhk:
                return "❌ Lỗi: Không xác định được học kỳ."
            
            # 2. Gọi API Progress
            import requests
            api_url = "https://cds.bdu.edu.vn/student/api/v1/odp/nhom-hoc/progress"
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            params = {"nkhk": final_nkhk}
            
            res = requests.get(api_url, headers=headers, params=params, timeout=10)
            
            if res.status_code != 200:
                return f"❌ Lỗi API: {res.status_code}"
            
            courses = res.json()
            
            # 3. Format response
            return self._format_course_list(courses, final_nkhk)
            
        except Exception as e:
            logger.error(f"❌ StudentScoreListTool Error: {str(e)}", exc_info=True)
            return f"❌ Lỗi: {str(e)}"
    
    def _format_course_list(self, data: List[Dict[str, Any]], nkhk: str) -> str:
        """Format course list response"""
        if not data:
            return f"📚 Chưa có môn học nào trong học kỳ {nkhk}."
        
        response = "📚 **DANH SÁCH MÔN HỌC**\n\n"
        response += f"📅 Học kỳ: **{nkhk}**\n"
        response += f"📊 Số môn: **{len(data)}** môn\n\n"
        
        response += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for idx, course in enumerate(data, 1):
            ten_mon = course.get('ten_mon_hoc', 'N/A')
            ma_nhom = course.get('ma_nhom', 'N/A')
            progress = course.get('progress', 0)
            status = course.get('status', 'unknown')
            tong_buoi_di = course.get('tong_buoi_di_hoc', 0)
            tong_buoi_vang = course.get('tong_buoi_vang', 0)
            
            # Icon theo status
            if status == 'good':
                icon = "✅"
                status_text = "Tốt"
            elif status == 'done':
                icon = "🎯"
                status_text = "Hoàn thành"
            elif status == 'in_progress':
                icon = "📝"
                status_text = "Đang học"
            elif status == 'warning':
                icon = "⚠️"
                status_text = "Cảnh báo"
            else:
                icon = "📚"
                status_text = "N/A"
            
            response += f"{icon} **{idx}. {ten_mon}**\n"
            response += f"   • Mã nhóm: {ma_nhom}\n"
            response += f"   • Trạng thái: {status_text}\n"
            response += f"   • Tiến độ: {progress*100:.0f}%\n"
            
            if tong_buoi_di or tong_buoi_vang:
                response += f"   • Đi học: {tong_buoi_di} buổi | Vắng: {tong_buoi_vang} buổi\n"
            
            response += "\n"
        
        response += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        response += "💡 **Gợi ý:**\n"
        response += "   • Xem điểm chi tiết: 'điểm chi tiết môn [tên môn]'\n"
        response += "   • Xem điểm danh: 'điểm danh môn [tên môn]'\n"
        
        return response
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 2. STUDENT SCORE DETAIL TOOL
# ================================
class StudentScoreDetailTool(BDUBaseTool):
    """
    Tool lấy CHI TIẾT ĐIỂM thành phần của 1 môn học (TV, B1, K1, T1)
    
    🎯 Sử dụng API: 
       - GET /odp/nhom-hoc/progress (tìm ma_nhom)
       - GET /odp/bang-diem?ma_nhom={ma_nhom} (lấy điểm)
    
    ⚠️ LƯU Ý: Tool này dành cho ĐIỂM THI (điểm thành phần)
       KHÔNG phải điểm danh hay tiến độ học tập!
    """
    
    name: str = "get_student_score_detail"
    description: str = """Lấy điểm THI CHI TIẾT thành phần (Thư viện, Bài tập, Giữa kỳ, Cuối kỳ) của 1 môn.

🎯 Sử dụng khi hỏi:
- "Điểm chi tiết môn X"
- "Điểm thành phần môn Y"
- "Điểm TV, K1, T1 môn Z"
- "Xem điểm thi môn ABC"

📊 Trả về: Điểm TV (thư viện), B1 (bài tập), K1 (giữa kỳ), T1 (cuối kỳ), điểm tổng kết

✅ Tự động tìm môn từ tên (không cần ma_nhom)
✅ Tìm cả trong kỳ trước nếu kỳ này không có

⚠️ KHÔNG dùng cho:
- Điểm danh/vắng (dùng get_student_course_detail)
- Danh sách môn (dùng get_student_score_list)
"""
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "", ma_nhom: Optional[str] = None) -> str:
        """
        Execute tool to get score detail
        
        Args:
            query: User query (để parse tên môn và semester)
            ma_nhom: Mã nhóm (optional, sẽ auto-detect nếu không có)
        
        Returns:
            Formatted score detail
        """
        if not self.api_service or not self.jwt_token:
            return "❌ Lỗi: Chưa đăng nhập."
        
        try:
            # 1. Auto-detect ma_nhom nếu thiếu
            if not ma_nhom:
                course_name = extract_course_name_from_query(query)
                
                if not course_name:
                    return "❌ Không hiểu tên môn học. Vui lòng nói rõ hơn (VD: 'điểm chi tiết môn Toán')"
                
                logger.info(f"🔍 Searching for course: '{course_name}'")
                
                # Parse NKHK từ query (nếu có)
                extracted_nkhk = _extract_semester_from_query(query.lower()) if query else None
                
                # 🎯 Tìm ma_nhom từ API PROGRESS
                match = find_ma_nhom_from_progress(
                    jwt_token=self.jwt_token,
                    course_name=course_name,
                    nkhk=extracted_nkhk
                )
                
                if not match:
                    return (
                        f"❌ Không tìm thấy môn '{course_name}'.\n\n"
                        f"💡 Có thể:\n"
                        f"   • Tên môn không chính xác\n"
                        f"   • Môn này không có trong kỳ học\n"
                        f"   • Thử hỏi: 'danh sách môn học' để xem các môn"
                    )
                
                ma_nhom = match['ma_nhom']
                ten_mon = match['ten_mon']
                semester = match['nkhk']
                
                logger.info(f"✅ Found course: {ten_mon} (ma_nhom: {ma_nhom}, semester: {semester})")
            
            # 2. Gọi API lấy chi tiết điểm
            import requests
            api_url = "https://cds.bdu.edu.vn/student/api/v1/odp/bang-diem"
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            params = {"ma_nhom": ma_nhom}
            
            res = requests.get(api_url, headers=headers, params=params, timeout=10)
            
            if res.status_code != 200:
                return f"❌ Lỗi API: {res.status_code}"
            
            detail_data = res.json()
            
            # Thêm thông tin từ match (nếu có)
            if 'match' in locals() and match:
                detail_data['_search_info'] = {
                    'found_name': match['ten_mon'],
                    'semester': match['nkhk']
                }
            
            # 3. Format response
            return self._format_score_detail(detail_data, ma_nhom)
            
        except Exception as e:
            logger.error(f"❌ StudentScoreDetailTool Error: {str(e)}", exc_info=True)
            return f"❌ Lỗi: {str(e)}"
    
    def _format_score_detail(self, data: Dict[str, Any], ma_nhom: str) -> str:
        """Format score detail response"""
        if not data:
            return f"📊 Không có dữ liệu chi tiết điểm cho môn {ma_nhom}."
        
        response = "📊 **CHI TIẾT ĐIỂM THI**\n\n"
        
        # Thông tin môn học
        response += f"📋 **Mã nhóm:** {ma_nhom}\n"
        
        # Hiển thị semester nếu có từ search
        if '_search_info' in data:
            ten_mon = data['_search_info'].get('found_name', 'N/A')
            semester = data['_search_info'].get('semester')
            response += f"📚 **Môn học:** {ten_mon}\n"
            if semester:
                response += f"📅 **Học kỳ:** {semester}\n"
        
        response += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # Điểm thành phần
        tv = data.get('tv', 'N/A')
        b1 = data.get('b1', 'N/A')
        k1 = data.get('k1', 'N/A')
        k1pt = data.get('k1pt', 'N/A')
        t1 = data.get('t1', 'N/A')
        t1pt = data.get('t1pt', 'N/A')
        
        response += "📝 **ĐIỂM THÀNH PHẦN:**\n\n"
        response += f"   📚 **Thư viện (TV):** {tv}\n"
        response += f"   📖 **Bài tập (B1):** {b1}\n"
        response += f"   📊 **Giữa kỳ (K1):** {k1} ({k1pt}%)\n"
        response += f"   📝 **Cuối kỳ (T1):** {t1} ({t1pt}%)\n\n"
        
        response += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # Điểm tổng kết
        diem_hp = data.get('diem_hp', 'N/A')
        diem_hp_4 = data.get('diem_hp_4', 'N/A')
        diem_chu = data.get('diem_chu_hp', 'N/A')
        dat_hp = data.get('dat_hp', 0)
        tin_chi = data.get('tin_chi', 'N/A')
        
        response += "🎯 **ĐIỂM TỔNG KẾT:**\n\n"
        response += f"   • Điểm hệ 10: **{diem_hp}**\n"
        response += f"   • Điểm hệ 4: **{diem_hp_4}**\n"
        response += f"   • Điểm chữ: **{diem_chu}**\n"
        response += f"   • Tín chỉ: **{tin_chi}**\n"
        
        if dat_hp == 1:
            response += f"   • Kết quả: ✅ **ĐẠT**\n"
        else:
            response += f"   • Kết quả: ❌ **KHÔNG ĐẠT**\n"
        
        response += "\n"
        
        # Phân tích
        try:
            diem_num = float(diem_hp) if diem_hp != 'N/A' else 0
            
            response += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            response += "💡 **PHÂN TÍCH:**\n\n"
            
            if diem_num >= 9.0:
                response += "   🌟 **Xuất sắc!** Kết quả rất tốt!\n"
            elif diem_num >= 8.0:
                response += "   ✨ **Giỏi!** Học tập tốt!\n"
            elif diem_num >= 7.0:
                response += "   ✅ **Khá!** Kết quả khá tốt!\n"
            elif diem_num >= 5.5:
                response += "   📊 **Trung bình khá.** Cần cố gắng thêm!\n"
            elif diem_num >= 4.0:
                response += "   ⚠️ **Trung bình.** Cần học tốt hơn!\n"
            else:
                response += "   ❌ **Yếu.** Cần ôn tập lại!\n"
            
            # Phân tích điểm thành phần
            if tv != 'N/A' and k1 != 'N/A' and t1 != 'N/A':
                try:
                    tv_num = float(tv)
                    k1_num = float(k1)
                    t1_num = float(t1)
                    
                    response += "\n   📊 **Phân tích chi tiết:**\n"
                    
                    # Điểm TV
                    if tv_num >= 8.0:
                        response += "   • Thư viện: Rất tốt! ✅\n"
                    elif tv_num >= 5.0:
                        response += "   • Thư viện: Ổn định 📚\n"
                    else:
                        response += "   • Thư viện: Cần cải thiện ⚠️\n"
                    
                    # Điểm K1
                    if k1_num >= 8.0:
                        response += "   • Giữa kỳ: Xuất sắc! 🌟\n"
                    elif k1_num >= 6.0:
                        response += "   • Giữa kỳ: Khá tốt 📖\n"
                    else:
                        response += "   • Giữa kỳ: Cần ôn tập ⚠️\n"
                    
                    # Điểm T1
                    if t1_num >= 8.0:
                        response += "   • Cuối kỳ: Rất tốt! ✨\n"
                    elif t1_num >= 6.0:
                        response += "   • Cuối kỳ: Ổn định 📝\n"
                    else:
                        response += "   • Cuối kỳ: Cần cố gắng ⚠️\n"
                    
                    # So sánh xu hướng
                    if t1_num > k1_num:
                        response += "\n   📈 **Xu hướng:** Tiến bộ tốt! (Cuối kỳ cao hơn Giữa kỳ)\n"
                    elif t1_num < k1_num:
                        response += "\n   📉 **Xu hướng:** Cần ôn tập tốt hơn (Cuối kỳ thấp hơn Giữa kỳ)\n"
                    else:
                        response += "\n   📊 **Xu hướng:** Ổn định\n"
                        
                except ValueError:
                    pass
        except:
            pass
        
        return response
    
    def set_api_service(self, service):
        self.api_service = service