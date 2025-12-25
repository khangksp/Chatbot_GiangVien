"""
Student API Tools - COMPLETE VERSION
Tools để gọi các API liên quan đến thông tin sinh viên
Đã được update để match với external_api_service.py
"""
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from .base_tool import BDUBaseTool, ToolValidator

logger = logging.getLogger(__name__)


# ================================
# 1. STUDENT PROFILE TOOL
# ================================
class StudentProfileTool(BDUBaseTool):
    """Tool to get student profile information"""
    
    name: str = "get_student_profile"
    description: str = """Lấy thông tin cá nhân của sinh viên.
    
    Sử dụng khi sinh viên hỏi:
    - "Tôi là ai?"
    - "Thông tin của tôi"
    - "MSSV của tôi là gì?"
    - "Lớp của tôi"
    - "Khoa của tôi"
    
    Input: Không cần input (tự động lấy từ JWT token)
    Output: Thông tin sinh viên (họ tên, MSSV, lớp, khoa)
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: Optional[str] = None) -> str:
        """Get student profile"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Không có thông tin xác thực. Vui lòng đăng nhập."
        
        try:
            logger.info("👤 Fetching student profile...")
            
            # ✅ API returns StudentProfile object or None
            profile = self.api_service.get_student_profile(self.jwt_token)
            
            if profile is None:
                logger.error("❌ Profile is None")
                return "❌ Không thể lấy thông tin sinh viên. Vui lòng thử lại sau."
            
            # ✅ Access dataclass attributes
            name = getattr(profile, 'ho_ten', None) or "N/A"
            mssv = getattr(profile, 'mssv', None) or "N/A"
            lop = getattr(profile, 'lop', None) or "N/A"
            khoa = getattr(profile, 'khoa', None) or "N/A"
            
            response = f"""📋 Thông tin sinh viên:

👤 Họ và tên: {name}
🎓 MSSV: {mssv}
📚 Lớp: {lop}
🏛️ Khoa: {khoa}
"""
            logger.info(f"✅ Profile fetched: {mssv}")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Đã xảy ra lỗi: {str(e)}"
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 2. STUDENT SCHEDULE TOOL
# ================================
class StudentScheduleTool(BDUBaseTool):
    """Tool to get student schedule"""
    
    name: str = "get_student_schedule"
    description: str = """Lấy lịch học của sinh viên.
    
    Sử dụng khi hỏi về:
    - "Lịch học của tôi"
    - "Hôm nay tôi học gì?"
    - "Lịch tuần này"
    - "Lịch tuần sau"
    - "Ngày mai tôi có học không?"
    
    Input: Câu hỏi (chứa thời gian)
    Output: Lịch học chi tiết
    """
    
    name: str = "get_student_schedule"
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get schedule"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem lịch học."
        
        try:
            logger.info(f"📅 Fetching schedule for: '{query}'")
            
            # API tự parse time từ query
            result = self.api_service.get_student_schedule(
                jwt_token=self.jwt_token,
                query=query
            )
            
            if not result or not result.get("ok"):
                reason = result.get("reason", "Unknown") if result else "No response"
                return f"❌ Không thể lấy lịch học. Lý do: {reason}"
            
            schedule = result.get("data", [])
            
            if not schedule:
                return "📅 Bạn không có lịch học nào trong khoảng thời gian này."
            
            response = self._format_schedule(schedule)
            logger.info(f"✅ Schedule fetched: {len(schedule)} sessions")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def _format_schedule(self, schedule: list) -> str:
        """Format schedule"""
        response = "📅 Lịch học của bạn:\n\n"
        
        by_date = {}
        for session in schedule:
            date = session.get('ngay_hoc', 'N/A')
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(session)
        
        for date in sorted(by_date.keys()):
            sessions = by_date[date]
            
            try:
                date_obj = datetime.strptime(date, '%Y-%m-%d')
                weekdays = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'CN']
                weekday = weekdays[date_obj.weekday()]
                date_str = f"{date_obj.strftime('%d/%m/%Y')} ({weekday})"
            except:
                date_str = date
            
            response += f"📆 {date_str}\n"
            
            for session in sessions:
                mon = session.get('ten_mon_hoc', 'N/A')
                tiet = session.get('tiet_bat_dau', 'N/A')
                so_tiet = session.get('so_tiet', 'N/A')
                phong = session.get('ma_phong', 'N/A')
                gv = session.get('ten_giang_vien', 'N/A')
                
                response += f"  📖 {mon}\n"
                response += f"     ⏰ Tiết {tiet} ({so_tiet} tiết)\n"
                response += f"     🏫 Phòng {phong}\n"
                response += f"     👨‍🏫 GV: {gv}\n\n"
        
        return response
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 3. STUDENT GRADES TOOL (FIXED)
# ================================
class StudentGradesTool(BDUBaseTool):
    """Tool to get student grades"""
    
    name: str = "get_student_grades"
    description: str = """Lấy điểm số và GPA của sinh viên.
    
    Sử dụng khi hỏi:
    - "Điểm của tôi"
    - "Điểm trung bình"
    - "GPA của tôi"
    - "Xem bảng điểm"
    - "Điểm học kỳ này"
    
    Input: Câu hỏi (có thể chứa học kỳ)
    Output: Bảng điểm hoặc GPA
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get grades"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem điểm."
        
        try:
            logger.info(f"📊 Fetching grades for: '{query}'")
            
            # API call
            result = self.api_service.get_student_grades(
                jwt_token=self.jwt_token,
                nkhk=None  # Auto-determine
            )
            
            if not result or not result.get("ok"):
                reason = result.get("reason", "Unknown") if result else "No response"
                return f"❌ Không thể lấy điểm. {reason}"
            
            data = result.get("data", {})
            
            if not data:
                return "📊 Chưa có điểm nào được công bố."
            
            # ✅ FIX: API response format
            # Actual API returns: {"avg_diem_hp": 7.86, "avg_diem_hp_4": 3.24}
            response = self._format_grades(data)
            logger.info(f"✅ Grades fetched")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def _format_grades(self, data: Any) -> str:
        """Format grades - FIXED to match API response"""
        
        # ✅ Handle dict response (GPA summary)
        if isinstance(data, dict):
            # Map API field names to display names
            gpa_10 = data.get("avg_diem_hp", data.get("diem_trung_binh_he_10", "N/A"))
            gpa_4 = data.get("avg_diem_hp_4", data.get("diem_trung_binh_he_4", "N/A"))
            tong_tc = data.get("tong_tin_chi", "N/A")
            xep_loai = data.get("xep_loai", "N/A")
            
            response = f"""📊 Điểm trung bình của bạn:

📈 GPA (Hệ 10): {gpa_10}
📈 GPA (Hệ 4): {gpa_4}
"""
            if tong_tc != "N/A":
                response += f"📚 Tổng tín chỉ: {tong_tc}\n"
            if xep_loai != "N/A":
                response += f"🏆 Xếp loại: {xep_loai}\n"
            
            return response
        
        # ✅ Handle list response (subject grades)
        elif isinstance(data, list):
            response = "📊 Bảng điểm của bạn:\n\n"
            
            for i, grade in enumerate(data, 1):
                mon = grade.get('ten_mon_hoc', 'N/A')
                tc = grade.get('so_tin_chi', 'N/A')
                diem_chu = grade.get('diem_chu', 'N/A')
                diem_10 = grade.get('diem_he_10', 'N/A')
                diem_4 = grade.get('diem_he_4', 'N/A')
                
                response += f"{i}. 📖 {mon} ({tc} TC)\n"
                response += f"   Điểm: {diem_chu} | {diem_10}/10 | {diem_4}/4\n\n"
            
            return response
        
        else:
            return "📊 Dữ liệu điểm không hợp lệ."
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 4. STUDENT TUITION TOOL (NEW!)
# ================================
class StudentTuitionTool(BDUBaseTool):
    """Tool to get student tuition/fees"""
    
    name: str = "get_student_tuition"
    description: str = """Lấy thông tin học phí của sinh viên.
    
    Sử dụng khi hỏi về:
    - "Học phí của tôi"
    - "Học phí là bao nhiêu?"
    - "Tôi phải đóng bao nhiêu tiền?"
    - "Chi phí học tập"
    - "Còn nợ học phí không?"
    
    Input: Câu hỏi (có thể chứa học kỳ)
    Output: Thông tin học phí chi tiết
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get tuition info"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem học phí."
        
        try:
            logger.info(f"💰 Fetching tuition for: '{query}'")
            
            # API call
            result = self.api_service.get_student_tuition(
                jwt_token=self.jwt_token,
                nkhk=None  # Auto-determine
            )
            
            if not result or not result.get("ok"):
                reason = result.get("reason", "Unknown") if result else "No response"
                return f"❌ Không thể lấy thông tin học phí. {reason}"
            
            data = result.get("data", [])
            
            if not data:
                return "💰 Chưa có thông tin học phí."
            
            response = self._format_tuition(data)
            logger.info(f"✅ Tuition fetched")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def _format_tuition(self, data: Any) -> str:
        """Format tuition data - FIXED to match API response"""
        
        if isinstance(data, list):
            response = "💰 Thông tin học phí:\n\n"
            
            total_amount_hp = 0
            total_paid_hp = 0
            total_debt_hp = 0
            
            total_debt_other = 0

            # Helper để định dạng mã NKHK (ví dụ: 25261)
            def format_nkhk(nkhk_code):
                try:
                    nkhk_str = str(nkhk_code)
                    year1 = nkhk_str[0:2]
                    year2 = nkhk_str[2:4]
                    term = nkhk_str[4]
                    
                    term_display = f"Kỳ {term}"
                    # Logic này có thể cần điều chỉnh tùy theo quy ước của trường
                    if term == '1': term_display = "Kỳ 1" 
                    elif term == '2': term_display = "Kỳ 2"
                    elif term == '3': term_display = "Kỳ 3"
                    elif term == '5': term_display = "Kỳ Hè" # Giả định
                    
                    return f"{term_display} (Năm {2000+int(year1)}-{2000+int(year2)})"
                except Exception:
                    return f"NKHK {nkhk_code}" # Fallback

            # Helper để định dạng loại thanh toán
            def format_type(type_code):
                if type_code == "hoc_phi": return "Học phí"
                if type_code == "bhyt": return "BHYT"
                return str(type_code).replace("_", " ").title()

            for item in data:
                # ✅ SỬ DỤNG CÁC KEY CHÍNH XÁC TỪ JSON
                nkhk_code = item.get('nkhk', 'N/A')
                loai_tt = item.get('loai_thanh_toan', 'Khác')
                so_tien = item.get('tong_tien_phai_thu', 0)
                da_dong = item.get('tong_tien_da_thu', 0)
                con_no = item.get('tong_tien_con_lai', 0)
                status = item.get('status', 'N/A')

                # Định dạng tiêu đề
                hoc_ky_formatted = format_nkhk(nkhk_code)
                type_formatted = format_type(loai_tt)
                
                response += f"📚 {hoc_ky_formatted} - ({type_formatted})\n"
                response += f"   Trạng thái: {status.title()}\n"
                response += f"   💵 Tổng: {so_tien:,} VNĐ\n"
                response += f"   ✅ Đã đóng: {da_dong:,} VNĐ\n"
                
                if con_no > 0:
                    response += f"   ⚠️ Còn nợ: {con_no:,} VNĐ\n"
                
                response += "\n"
                
                # Tách riêng logic tính tổng
                if loai_tt == 'hoc_phi':
                    total_amount_hp += so_tien
                    total_paid_hp += da_dong
                    total_debt_hp += con_no
                elif con_no > 0: # Các khoản nợ khác (BHYT, v.v.)
                    total_debt_other += con_no
            
            response += f"📊 TỔNG KẾT:\n"
            response += f"   💵 Tổng học phí đã tính: {total_amount_hp:,} VNĐ\n"
            response += f"   ✅ Đã đóng học phí: {total_paid_hp:,} VNĐ\n"
            
            if total_debt_hp > 0:
                response += f"   ⚠️ NỢ HỌC PHÍ: {total_debt_hp:,} VNĐ\n"
            else:
                response += f"   ✅ Đã hoàn thành học phí!\n"
                
            if total_debt_other > 0:
                response += f"   ⚠️ NỢ KHÁC (BHYT,...): {total_debt_other:,} VNĐ\n"
            
            return response
        
        elif isinstance(data, dict):
            # Xử lý trường hợp API chỉ trả về 1 object (ít khả năng)
            so_tien = data.get('tong_tien_phai_thu', 0)
            da_dong = data.get('tong_tien_da_thu', 0)
            con_no = data.get('tong_tien_con_lai', 0)
            
            response = f"""💰 Thông tin học phí:
💵 Tổng: {so_tien:,} VNĐ
✅ Đã đóng: {da_dong:,} VNĐ
"""
            if con_no > 0:
                response += f"⚠️ Còn nợ: {con_no:,} VNĐ\n"
            else:
                response += "✅ Đã hoàn thành!\n"
            
            return response
        
        else:
            return "💰 Dữ liệu học phí không hợp lệ."
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 5. STUDENT CREDITS TOOL (BONUS)
# ================================
class StudentCreditsTool(BDUBaseTool):
    """Tool to get accumulated credits"""
    
    name: str = "get_student_credits"
    description: str = """Lấy thông tin tích lũy tín chỉ.
    
    Sử dụng khi hỏi:
    - "Tín chỉ tích lũy"
    - "Tôi đã học được bao nhiêu tín chỉ?"
    - "Số tín chỉ hiện tại"
    
    Input: Câu hỏi
    Output: Thông tin tín chỉ tích lũy
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get credits"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập."
        
        try:
            logger.info(f"📊 Fetching credits for: '{query}'")
            
            result = self.api_service.get_student_credits(
                jwt_token=self.jwt_token,
                query=query
            )
            
            if not result or not result.get("ok"):
                return "❌ Không thể lấy thông tin tín chỉ."
            
            data = result.get("data", {})
            
            if not data:
                return "📊 Chưa có thông tin tín chỉ."
            
            # === SỬA LỖI KEY TẠI ĐÂY ===
            
            # Key cũ (SAI): 'tong_tc_tich_luy'
            tc_tich_luy = data.get('total_credit', 'N/A')
            
            # Key cũ (SAI): 'tc_bat_buoc'
            tc_yeu_cau = data.get('required_credit', 'N/A')
            
            # API không trả về 'tc_tu_chon', nên chúng ta bỏ qua
            
            response = f"""📊 Tín chỉ của bạn:

📚 Tổng tín chỉ đã tích lũy: {tc_tich_luy}
📖 Tổng tín chỉ yêu cầu (toàn khóa): {tc_yeu_cau}
"""
            # === KẾT THÚC SỬA LỖI ===
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 6. STUDENT NEWS TOOL (BONUS)
# ================================
class StudentNewsTool(BDUBaseTool):
    """Tool to get student news"""
    
    name: str = "get_student_news"
    description: str = """Lấy tin tức dành cho sinh viên.
    
    Sử dụng khi hỏi:
    - "Tin tức mới nhất"
    - "Có thông báo gì không?"
    - "Tin tức trường"
    
    Input: Câu hỏi
    Output: Danh sách tin tức
    """
    
    category: str = "student_api"
    requires_auth: bool = False
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get news"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        try:
            logger.info(f"📰 Fetching news")
            
            result = self.api_service.get_student_news(
                jwt_token=self.jwt_token,
                limit=5
            )
            
            if not result or not result.get("ok"):
                return "❌ Không thể lấy tin tức."
            
            news_list = result.get("data", [])
            
            if not news_list:
                return "📰 Chưa có tin tức mới."
            
            response = "📰 Tin tức mới nhất:\n\n"
            
            for i, news in enumerate(news_list[:5], 1):
                title = news.get('tieu_de', 'N/A')
                date = news.get('ngay_dang', 'N/A')
                
                response += f"{i}. {title}\n"
                response += f"   📅 {date}\n\n"
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def set_api_service(self, service):
        self.api_service = service