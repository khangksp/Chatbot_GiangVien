"""
Exam & RL Tools - Lịch thi và Điểm rèn luyện
Tools để lấy thông tin lịch thi và điểm rèn luyện của sinh viên
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .base_tool import BDUBaseTool

logger = logging.getLogger(__name__)


# ================================
# 1. STUDENT EXAM SCHEDULE TOOL
# ================================
class StudentExamScheduleTool(BDUBaseTool):
    """Tool to get student exam schedule"""
    
    name: str = "get_student_exam_schedule"
    description: str = """Lấy lịch thi của sinh viên.
    
    Sử dụng khi sinh viên hỏi:
    - "Lịch thi của tôi"
    - "Khi nào thi môn X?"
    - "Lịch thi học kỳ này"
    - "Lịch thi cuối kỳ"
    - "Tôi thi môn gì?"
    
    Input: Câu hỏi (có thể chứa tên môn hoặc học kỳ)
    Output: Lịch thi chi tiết theo từng môn
    
    Lưu ý: Nếu ngày/giờ thi là null thì là thi theo lịch riêng của khoa
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get exam schedule"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem lịch thi."
        
        try:
            logger.info(f"📝 Fetching exam schedule for: '{query}'")
            
            # API tự động xử lý nkhk từ query hoặc lấy học kỳ hiện tại
            result = self.api_service.get_student_exam_schedule(
                jwt_token=self.jwt_token,
                query=query,
                nkhk=None  # Auto-determine
            )
            
            if not result or not result.get("ok"):
                reason = result.get("reason", "Unknown") if result else "No response"
                return f"❌ Không thể lấy lịch thi. Lý do: {reason}"
            
            exam_list = result.get("data", [])
            
            if not exam_list:
                return "📝 Bạn chưa có lịch thi nào được công bố."
            
            response = self._format_exam_schedule(exam_list, query)
            logger.info(f"✅ Exam schedule fetched: {len(exam_list)} exams")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def _format_exam_schedule(self, exam_list: list, query: str = "") -> str:
        """
        Format exam schedule from API response
        
        API Response Format:
        [
            {
                "ma_mon_hoc": "INF0103",
                "ten_mon_hoc": "Nhập môn Trí tuệ nhân tạo",
                "nhom_thi": "02",
                "to_thi": "001-25TH01",
                "nkhk": 24252,
                "ngay": null,
                "gio_bd": null,
                "so_phut": "0",
                "phong": null,
                "hinh_thuc": "Nộp bài tiểu luận"
            }
        ]
        """
        if not exam_list:
            return "📝 Chưa có lịch thi."
        
        # Kiểm tra xem có hỏi về môn cụ thể không
        query_lower = query.lower() if query else ""
        specific_subject = None
        
        # Tìm môn học được hỏi trong query
        for exam in exam_list:
            subject_name = exam.get('ten_mon_hoc', '').lower()
            subject_code = exam.get('ma_mon_hoc', '').lower()
            
            if subject_name and subject_name in query_lower:
                specific_subject = exam.get('ma_mon_hoc')
                break
            elif subject_code and subject_code in query_lower:
                specific_subject = subject_code
                break
        
        # Nếu hỏi môn cụ thể, chỉ hiển thị môn đó
        if specific_subject:
            exam_list = [e for e in exam_list if e.get('ma_mon_hoc') == specific_subject]
        
        response = "📝 Lịch thi của bạn:\n\n"
        
        # Phân loại theo hình thức thi
        scheduled_exams = []  # Thi có lịch cụ thể
        flexible_exams = []   # Thi theo lịch khoa/nộp bài
        
        for exam in exam_list:
            ngay = exam.get('ngay')
            gio_bd = exam.get('gio_bd')
            
            # Nếu có ngày và giờ cụ thể
            if ngay and gio_bd:
                scheduled_exams.append(exam)
            else:
                flexible_exams.append(exam)
        
        # Hiển thị thi có lịch cụ thể trước (sắp xếp theo ngày)
        if scheduled_exams:
            response += "📅 **Lịch thi theo thời gian biểu:**\n\n"
            
            # Sort by date
            scheduled_exams.sort(key=lambda x: x.get('ngay', ''))
            
            for exam in scheduled_exams:
                mon = exam.get('ten_mon_hoc', 'N/A')
                ma_mon = exam.get('ma_mon_hoc', '')
                ngay = exam.get('ngay', 'N/A')
                gio = exam.get('gio_bd', 'N/A')
                phong = exam.get('phong', 'N/A')
                hinh_thuc = exam.get('hinh_thuc', 'N/A')
                so_phut = exam.get('so_phut', '0')
                
                # Format date
                try:
                    if ngay and ngay != 'N/A':
                        date_obj = datetime.strptime(ngay, '%Y-%m-%d')
                        weekdays = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'CN']
                        weekday = weekdays[date_obj.weekday()]
                        ngay_display = f"{date_obj.strftime('%d/%m/%Y')} ({weekday})"
                    else:
                        ngay_display = ngay
                except:
                    ngay_display = ngay
                
                response += f"📖 **{mon}** ({ma_mon})\n"
                response += f"   📅 Ngày: {ngay_display}\n"
                response += f"   ⏰ Giờ: {gio}"
                
                if so_phut and so_phut != '0':
                    response += f" ({so_phut} phút)"
                response += "\n"
                
                if phong and phong != 'N/A':
                    response += f"   🏫 Phòng: {phong}\n"
                response += f"   📋 Hình thức: {hinh_thuc}\n\n"
        
        # Hiển thị thi linh hoạt (không có lịch cụ thể)
        if flexible_exams:
            response += "📌 **Thi theo lịch riêng/nộp bài:**\n\n"
            
            for exam in flexible_exams:
                mon = exam.get('ten_mon_hoc', 'N/A')
                ma_mon = exam.get('ma_mon_hoc', '')
                hinh_thuc = exam.get('hinh_thuc', 'N/A')
                
                response += f"📖 **{mon}** ({ma_mon})\n"
                response += f"   📋 Hình thức: {hinh_thuc}\n"
                
                # Gợi ý dựa vào hình thức
                if 'tiểu luận' in hinh_thuc.lower():
                    response += f"   💡 Lưu ý: Nộp bài theo hướng dẫn giảng viên\n"
                elif 'vấn đáp' in hinh_thuc.lower() or 'khoa' in hinh_thuc.lower():
                    response += f"   💡 Lưu ý: Theo lịch do khoa thông báo riêng\n"
                elif 'thực hành' in hinh_thuc.lower():
                    response += f"   💡 Lưu ý: Thi trong giờ học thực hành\n"
                
                response += "\n"
        
        # Thống kê tổng số môn thi
        total = len(exam_list)
        response += f"\n📊 **Tổng cộng: {total} môn thi**"
        
        if scheduled_exams:
            response += f" ({len(scheduled_exams)} môn có lịch cụ thể)"
        
        return response
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 2. STUDENT RL GRADES TOOL
# ================================
class StudentRLGradesTool(BDUBaseTool):
    """Tool to get student RL (rèn luyện) grades"""
    
    name: str = "get_student_rl_grades"
    description: str = """Lấy điểm rèn luyện của sinh viên.
    
    Sử dụng khi sinh viên hỏi:
    - "Điểm rèn luyện của tôi"
    - "Điểm RL"
    - "Xếp loại rèn luyện"
    - "Điểm rèn luyện học kỳ này"
    - "Tôi được bao nhiêu điểm RL?"
    
    Input: Câu hỏi (có thể chứa học kỳ)
    Output: Điểm rèn luyện và xếp loại
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get RL grades"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem điểm rèn luyện."
        
        try:
            logger.info(f"🏆 Fetching RL grades for: '{query}'")
            
            # API tự động xử lý nkhk từ query hoặc lấy học kỳ hiện tại
            result = self.api_service.get_student_rl_grades(
                jwt_token=self.jwt_token,
                query=query,
                nkhk=None  # Auto-determine
            )
            
            if not result or not result.get("ok"):
                reason = result.get("reason", "Unknown") if result else "No response"
                return f"❌ Không thể lấy điểm rèn luyện. Lý do: {reason}"
            
            rl_data = result.get("data", {})
            
            if not rl_data:
                return "🏆 Chưa có điểm rèn luyện được công bố."
            
            response = self._format_rl_grades(rl_data)
            logger.info(f"✅ RL grades fetched successfully")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def _format_rl_grades(self, rl_data: Dict[str, Any]) -> str:
        """
        Format RL grades from API response
        
        API Response Format:
        {
            "diem_ren_luyen": "91",
            "xep_loai": "Xuất sắc"
        }
        """
        if not rl_data:
            return "🏆 Chưa có điểm rèn luyện."
        
        # Lấy điểm và xếp loại từ API
        diem = rl_data.get('diem_ren_luyen', 'N/A')
        xep_loai = rl_data.get('xep_loai', 'N/A')
        
        # Convert điểm sang số để đánh giá
        try:
            diem_num = int(diem) if diem != 'N/A' else 0
        except:
            diem_num = 0
        
        response = f"""🏆 Điểm rèn luyện của bạn:

📊 Điểm: {diem}/100
🏅 Xếp loại: {xep_loai}
"""
        
        # Thêm đánh giá và gợi ý
        if diem_num >= 90:
            response += "\n✨ Xuất sắc! Bạn đang thực hiện rất tốt!"
        elif diem_num >= 80:
            response += "\n👍 Tốt! Hãy duy trì phong độ!"
        elif diem_num >= 70:
            response += "\n📈 Khá! Có thể cải thiện thêm!"
        elif diem_num >= 50:
            response += "\n⚠️ Trung bình. Bạn nên tham gia thêm các hoạt động!"
        elif diem_num > 0:
            response += "\n🔔 Cần cố gắng hơn! Hãy tham gia nhiều hoạt động tập thể!"
        
        # Thêm thông tin về tiêu chí đánh giá (nếu cần)
        response += "\n\n📋 Các hoạt động ảnh hưởng đến điểm RL:"
        response += "\n  • Tham gia hoạt động đoàn, hội"
        response += "\n  • Tham gia các cuộc thi, sự kiện"
        response += "\n  • Tham gia công tác xã hội, tình nguyện"
        response += "\n  • Kỷ luật học tập và sinh hoạt"
        
        return response
    
    def set_api_service(self, service):
        self.api_service = service