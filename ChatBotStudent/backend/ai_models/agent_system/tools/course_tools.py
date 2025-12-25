"""
Course Tools - Student Course & Attendance API Tools
Tools để xử lý các API liên quan đến môn học và điểm danh
Bao gồm: Danh sách môn học, Tiến độ điểm danh, Chi tiết môn học
"""
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from .base_tool import BDUBaseTool

logger = logging.getLogger(__name__)

# ========================
# CONSTANTS & THRESHOLDS
# ========================
MIN_SCORE_THRESHOLD = 5.0  # Điểm tối thiểu để accept match
MAX_SEMESTERS_TO_SEARCH = 4  # ✅ TĂNG từ 3 → 4 học kỳ để tìm tốt hơn


class StudentCourseListTool(BDUBaseTool):
    """
    Tool để lấy danh sách môn học trong học kỳ
    API: /odp/nhom-hoc?nkhk=${nkhk}
    """
    
    name: str = "get_student_courses"
    description: str = """Lấy danh sách các môn học của sinh viên trong một học kỳ cụ thể.
    
    Sử dụng tool này khi sinh viên hỏi:
    - "Tôi học những môn nào?"
    - "Danh sách môn học của tôi"
    - "Môn học học kỳ này"
    - "Học kỳ [X] tôi học gì?"
    - "Có bao nhiêu môn?"
    - "Môn nào đã hoàn thành?"
    - "Môn nào đang học?"
    
    Tool này sẽ:
    - Hiển thị danh sách môn học với mã môn, tên môn, nhóm
    - Hiển thị tổng số buổi học của mỗi môn
    - Hiển thị trạng thái (đang học/hoàn thành)
    - Hiển thị tiến độ học (số buổi đã học)
    - Tự động phát hiện học kỳ từ câu hỏi hoặc dùng học kỳ hiện tại
    
    Input: Câu hỏi (có thể chứa học kỳ hoặc không)
    Output: Danh sách môn học với thông tin chi tiết
    
    Ví dụ:
    - "Môn học của tôi" → Hiển thị môn học kỳ hiện tại
    - "Học kỳ 1 năm 2024-2025" → Hiển thị môn học kỳ 1/2024-2025
    - "Tôi có mấy môn đang học?" → Đếm số môn status = "in_progress"
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    
    # Injected dependencies
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """
        Execute course list fetching
        
        Args:
            query: User's question (có thể chứa học kỳ)
            
        Returns:
            Formatted course list
        """
        if not self.api_service:
            return "❌ API service chưa được khởi tạo"
        
        if not self.jwt_token:
            return "❌ Cần đăng nhập để xem danh sách môn học"
        
        try:
            logger.info(f"📚 Fetching course list (query: '{query}')")
            
            # Xác định học kỳ từ query hoặc dùng hiện tại
            nkhk = self._extract_nkhk_from_query(query)
            
            if not nkhk:
                logger.warning("⚠️ Could not determine NKHK, using current semester")
                nkhk = self.api_service.get_latest_nkhk(self.jwt_token)
            
            if not nkhk:
                return "❌ Không thể xác định học kỳ. Vui lòng thử lại."
            
            logger.info(f"📅 Using NKHK: {nkhk}")
            
            # Gọi API - Sử dụng method có sẵn hoặc tạo mới
            result = self._call_course_list_api(nkhk)
            
            if not result or not result.get("ok"):
                reason = result.get("error", "Unknown") if result else "No response"
                logger.error(f"❌ Course list API failed: {reason}")
                return f"❌ Không thể lấy danh sách môn học. Lý do: {reason}"
            
            courses = result.get("data", [])
            
            if not courses:
                return f"📚 Bạn chưa có môn học nào trong học kỳ này (NKHK: {nkhk})."
            
            logger.info(f"✅ Fetched {len(courses)} courses")
            
            # Format response
            response = self._format_course_list(courses, nkhk, query)
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Course List Tool error: {str(e)}", exc_info=True)
            return f"❌ Đã xảy ra lỗi khi lấy danh sách môn học: {str(e)}"
    
    def _extract_nkhk_from_query(self, query: str) -> Optional[str]:
        """
        Trích xuất mã NKHK từ câu hỏi
        Sử dụng logic tương tự external_api_service._extract_semester_from_query
        ✅ BỔ SUNG: Xử lý "kỳ trước", "học kỳ trước"
        """
        if not query:
            return None
        
        query_lower = query.lower().strip()
        
        # ✅ FIX 2: Xử lý "kỳ trước" / "học kỳ trước"
        previous_semester_phrases = [
            "kỳ trước", "ky truoc", 
            "học kỳ trước", "hoc ky truoc",
            "học kì trước", "hoc ki truoc",
            "kì trước", "ki truoc"
        ]
        
        if any(phrase in query_lower for phrase in previous_semester_phrases):
            logger.info("🔍 Detected 'kỳ trước' in query - calling get_previous_nkhk()")
            try:
                previous_nkhk = self.api_service.get_previous_nkhk(self.jwt_token)
                if previous_nkhk:
                    logger.info(f"✅ Using previous NKHK: {previous_nkhk}")
                    return previous_nkhk
                else:
                    logger.warning("⚠️ Could not get previous NKHK, fallback to current")
                    return None
            except Exception as e:
                logger.error(f"❌ Error getting previous NKHK: {e}")
                return None
        
        # Pattern: (học kỳ|kỳ) + (1|2|3) + (năm) + (YYYY-YYYY | YY-YY | YYYY)
        pattern = r"(?:hoc ky|học kỳ|ky|kỳ)\s*([123])\s*(?:nam|năm)?\s*(\d{2,4})(?:[-\s](\d{2,4}))?"
        
        match = re.search(pattern, query_lower)
        
        if match:
            hk_num = match.group(1)
            year1_str = match.group(2)
            year2_str = match.group(3)
            
            try:
                # Xử lý năm bắt đầu
                if len(year1_str) == 4:
                    year1_short = year1_str[-2:]
                elif len(year1_str) == 2:
                    year1_short = year1_str
                else:
                    return None
                
                # Xử lý năm kết thúc
                if year2_str:
                    if len(year2_str) == 4:
                        year2_short = year2_str[-2:]
                    elif len(year2_str) == 2:
                        year2_short = year2_str
                    else:
                        return None
                else:
                    year2_short = str(int(year1_short) + 1).zfill(2)
                
                # Map học kỳ
                hk_map = {'1': '1', '2': '2', '3': '3'}
                if hk_num in hk_map:
                    nkhk_suffix = hk_map[hk_num]
                    generated_nkhk = f"{year1_short}{year2_short}{nkhk_suffix}"
                    logger.info(f"🔍 Extracted NKHK from query: {generated_nkhk}")
                    return generated_nkhk
                
            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Error parsing semester from query: {e}")
                return None
        
        return None
    
    def _call_course_list_api(self, nkhk: str) -> Dict[str, Any]:
        """
        Gọi API lấy danh sách môn học
        API: /odp/nhom-hoc?nkhk={nkhk}
        """
        try:
            endpoint = f"{self.api_service.student_base}/odp/nhom-hoc"
            headers = {
                "Authorization": f"Bearer {self.jwt_token}" if not self.jwt_token.startswith("Bearer") else self.jwt_token
            }
            params = {"nkhk": nkhk}
            
            logger.info(f"🌐 Calling API: {endpoint} with nkhk={nkhk}")
            
            import requests
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ API success: Got {len(data) if isinstance(data, list) else 'N/A'} courses")
                return {"ok": True, "data": data}
            else:
                logger.error(f"❌ API failed: {response.status_code} - {response.text}")
                return {"ok": False, "error": f"API returned {response.status_code}"}
                
        except Exception as e:
            logger.error(f"❌ API call error: {e}")
            return {"ok": False, "error": str(e)}
    
    def _format_course_list(self, courses: List[Dict], nkhk: str, query: str = "") -> str:
        """
        Format danh sách môn học để hiển thị
        """
        # Phân loại môn theo trạng thái
        in_progress = [c for c in courses if c.get('status') == 'in_progress']
        done = [c for c in courses if c.get('status') == 'done']
        
        semester_name = self._format_semester_name(nkhk)
        
        response = f"📚 **Danh sách môn học - {semester_name}**\n\n"
        
        # Môn đang học
        if in_progress:
            response += f"🔵 **Môn đang học ({len(in_progress)} môn):**\n"
            for idx, course in enumerate(in_progress, 1):
                response += self._format_single_course(course, idx)
                response += "\n"
        
        # Môn đã hoàn thành
        if done:
            response += f"\n✅ **Môn đã hoàn thành ({len(done)} môn):**\n"
            for idx, course in enumerate(done, 1):
                response += self._format_single_course(course, idx)
                response += "\n"
        
        # Thống kê
        total = len(courses)
        response += f"\n📊 **Tổng kết:**\n"
        response += f"   • Tổng số môn: {total}\n"
        response += f"   • Đang học: {len(in_progress)}\n"
        response += f"   • Đã hoàn thành: {len(done)}\n"
        
        return response
    
    def _format_single_course(self, course: Dict, index: int) -> str:
        """Format thông tin một môn học"""
        ma_mon = course.get('ma_mon', 'N/A')
        ten_mon = course.get('ten_mon_hoc', 'Không có tên')
        ma_nhom = course.get('ma_nhom', 'N/A')
        tong_buoi = course.get('tong_buoi', 0)
        progress = course.get('progress', 0)
        status = course.get('status', 'unknown')
        
        # Icon theo trạng thái
        status_icon = "🔵" if status == "in_progress" else "✅"
        
        # Progress bar
        progress_percent = int(progress * 100) if isinstance(progress, float) else progress
        progress_bar = self._create_progress_bar(progress_percent)
        
        result = f"{status_icon} **{index}. [{ma_mon}] {ten_mon}**\n"
        result += f"   • Nhóm: {ma_nhom}\n"
        result += f"   • Tổng số buổi: {tong_buoi}\n"
        result += f"   • Tiến độ: {progress_bar} {progress_percent}%\n"
        
        return result
    
    def _create_progress_bar(self, percent: int, length: int = 10) -> str:
        """Tạo progress bar text"""
        filled = int(percent / 100 * length)
        bar = "█" * filled + "░" * (length - filled)
        return f"[{bar}]"
    
    def _format_semester_name(self, nkhk: str) -> str:
        """
        Format NKHK thành tên học kỳ đẹp
        Ví dụ: "24251" → "Học kỳ 1 năm 2024-2025"
        """
        if not nkhk or len(nkhk) != 5:
            return f"Học kỳ {nkhk}"
        
        try:
            year1 = "20" + nkhk[:2]
            year2 = "20" + nkhk[2:4]
            semester_code = nkhk[4]
            
            semester_map = {'1': '1', '2': '2', '3': '3'}
            semester_name = semester_map.get(semester_code, semester_code)
            
            return f"Học kỳ {semester_name} năm {year1}-{year2}"
        except:
            return f"Học kỳ {nkhk}"
    
    def set_api_service(self, service):
        """Set API service instance"""
        self.api_service = service


class StudentCourseProgressTool(BDUBaseTool):
    """
    Tool để xem tiến độ điểm danh các môn học
    API: /odp/nhom-hoc/progress?nkhk=${nkhk}
    """
    
    name: str = "get_course_attendance_progress"
    description: str = """Xem tiến độ điểm danh và tình trạng vắng học của các môn học.
    
    Sử dụng tool này khi sinh viên hỏi:
    - "Điểm danh của tôi thế nào?"
    - "Tôi vắng bao nhiêu buổi?"
    - "Môn nào tôi vắng nhiều?"
    - "Tình trạng điểm danh"
    - "Có nguy cơ cấm thi không?"
    - "Môn nào bị cảnh báo?"
    - "Tiến độ học"
    
    Tool này sẽ:
    - Hiển thị số buổi đi học / vắng của từng môn
    - Tính tỷ lệ % điểm danh
    - Cảnh báo môn có nguy cơ cấm thi (vắng 1-2 buổi)
    - Báo rõ môn đã bị cấm thi (vắng >= 2 buổi)
    - Phân loại trạng thái: Good (tốt), Warning (cảnh báo), Banned (cấm thi)
    
    LƯU Ý QUAN TRỌNG:
    - Vắng 1 buổi → Cảnh báo ⚠️
    - Vắng 2 buổi → Cấm thi ❌
    
    Input: Câu hỏi (có thể chứa học kỳ hoặc tên môn)
    Output: Bảng tiến độ điểm danh chi tiết với cảnh báo
    
    Ví dụ:
    - "Điểm danh của tôi" → Hiển thị tất cả môn
    - "Môn nào tôi vắng nhiều?" → Sắp xếp theo số buổi vắng giảm dần
    - "Tôi có bị cấm thi không?" → Hiển thị môn có status = "banned"
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """
        Execute attendance progress fetching
        """
        if not self.api_service:
            return "❌ API service chưa được khởi tạo"
        
        if not self.jwt_token:
            return "❌ Cần đăng nhập để xem tiến độ điểm danh"
        
        try:
            logger.info(f"📊 Fetching attendance progress (query: '{query}')")
            
            # Xác định học kỳ
            nkhk = self._extract_nkhk_from_query(query)
            
            if not nkhk:
                logger.warning("⚠️ Could not determine NKHK, using current semester")
                nkhk = self.api_service.get_latest_nkhk(self.jwt_token)
            
            if not nkhk:
                return "❌ Không thể xác định học kỳ. Vui lòng thử lại."
            
            logger.info(f"📅 Using NKHK: {nkhk}")
            
            # Gọi API
            result = self._call_progress_api(nkhk)
            
            if not result or not result.get("ok"):
                reason = result.get("error", "Unknown") if result else "No response"
                logger.error(f"❌ Progress API failed: {reason}")
                return f"❌ Không thể lấy tiến độ điểm danh. Lý do: {reason}"
            
            progress_data = result.get("data", [])
            
            if not progress_data:
                return f"📊 Chưa có dữ liệu điểm danh trong học kỳ này (NKHK: {nkhk})."
            
            logger.info(f"✅ Fetched progress for {len(progress_data)} courses")
            
            # Format response
            response = self._format_progress(progress_data, nkhk, query)
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Attendance Progress Tool error: {str(e)}", exc_info=True)
            return f"❌ Đã xảy ra lỗi khi lấy tiến độ điểm danh: {str(e)}"
    
    def _extract_nkhk_from_query(self, query: str) -> Optional[str]:
        """Trích xuất NKHK từ query (giống StudentCourseListTool)"""
        if not query:
            return None
        
        query_lower = query.lower().strip()
        pattern = r"(?:hoc ky|học kỳ|ky|kỳ)\s*([123])\s*(?:nam|năm)?\s*(\d{2,4})(?:[-\s](\d{2,4}))?"
        
        match = re.search(pattern, query_lower)
        
        if match:
            hk_num = match.group(1)
            year1_str = match.group(2)
            year2_str = match.group(3)
            
            try:
                if len(year1_str) == 4:
                    year1_short = year1_str[-2:]
                elif len(year1_str) == 2:
                    year1_short = year1_str
                else:
                    return None
                
                if year2_str:
                    if len(year2_str) == 4:
                        year2_short = year2_str[-2:]
                    elif len(year2_str) == 2:
                        year2_short = year2_str
                    else:
                        return None
                else:
                    year2_short = str(int(year1_short) + 1).zfill(2)
                
                hk_map = {'1': '1', '2': '2', '3': '3'}
                if hk_num in hk_map:
                    nkhk_suffix = hk_map[hk_num]
                    generated_nkhk = f"{year1_short}{year2_short}{nkhk_suffix}"
                    logger.info(f"🔍 Extracted NKHK from query: {generated_nkhk}")
                    return generated_nkhk
                
            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Error parsing semester: {e}")
                return None
        
        return None
    
    def _call_progress_api(self, nkhk: str) -> Dict[str, Any]:
        """
        Gọi API tiến độ điểm danh
        API: /odp/nhom-hoc/progress?nkhk={nkhk}
        """
        try:
            endpoint = f"{self.api_service.student_base}/odp/nhom-hoc/progress"
            headers = {
                "Authorization": f"Bearer {self.jwt_token}" if not self.jwt_token.startswith("Bearer") else self.jwt_token
            }
            params = {"nkhk": nkhk}
            
            logger.info(f"🌐 Calling API: {endpoint} with nkhk={nkhk}")
            
            import requests
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ API success: Got {len(data) if isinstance(data, list) else 'N/A'} records")
                return {"ok": True, "data": data}
            else:
                logger.error(f"❌ API failed: {response.status_code} - {response.text}")
                return {"ok": False, "error": f"API returned {response.status_code}"}
                
        except Exception as e:
            logger.error(f"❌ API call error: {e}")
            return {"ok": False, "error": str(e)}
    
    def _format_progress(self, progress_data: List[Dict], nkhk: str, query: str = "") -> str:
        """Format tiến độ điểm danh"""
        semester_name = self._format_semester_name(nkhk)
        
        response = f"📊 **Tiến độ điểm danh - {semester_name}**\n\n"
        
        # Phân loại theo status
        good = [p for p in progress_data if p.get('status') == 'good']
        warning = [p for p in progress_data if p.get('status') == 'warning']
        banned = [p for p in progress_data if p.get('status') == 'banned']
        
        # Cảnh báo nếu có môn bị cấm thi
        if banned:
            response += "🚨 **CẢNH BÁO NGHIÊM TRỌNG** 🚨\n"
            response += f"Bạn có {len(banned)} môn BỊ CẤM THI do vắng quá nhiều!\n\n"
        
        # Hiển thị môn bị cấm thi trước
        if banned:
            response += f"❌ **MÔN BỊ CẤM THI ({len(banned)} môn):**\n"
            for idx, progress in enumerate(banned, 1):
                response += self._format_single_progress(progress, idx, highlight=True)
                response += "\n"
        
        # Môn cảnh báo
        if warning:
            response += f"\n⚠️ **MÔN CẢNH BÁO ({len(warning)} môn):**\n"
            for idx, progress in enumerate(warning, 1):
                response += self._format_single_progress(progress, idx, highlight=True)
                response += "\n"
        
        # Môn tốt
        if good:
            response += f"\n✅ **MÔN TỐT ({len(good)} môn):**\n"
            for idx, progress in enumerate(good, 1):
                response += self._format_single_progress(progress, idx)
                response += "\n"
        
        # Thống kê tổng quan
        total = len(progress_data)
        total_attended = sum(int(p.get('tong_buoi_di_hoc', 0)) for p in progress_data)
        total_absent = sum(int(p.get('tong_buoi_vang', 0)) for p in progress_data)
        
        response += f"\n📈 **Tổng quan:**\n"
        response += f"   • Tổng số môn: {total}\n"
        response += f"   • Tốt: {len(good)} | Cảnh báo: {len(warning)} | Cấm thi: {len(banned)}\n"
        response += f"   • Tổng buổi đi học: {total_attended}\n"
        response += f"   • Tổng buổi vắng: {total_absent}\n"
        
        # Lưu ý quan trọng
        response += f"\n💡 **Lưu ý:**\n"
        response += f"   • Vắng 1 buổi = Cảnh báo ⚠️\n"
        response += f"   • Vắng 2 buổi = Cấm thi ❌\n"
        response += f"   • Hãy đảm bảo đi học đầy đủ!\n"
        
        return response
    
    def _format_single_progress(self, progress: Dict, index: int, highlight: bool = False) -> str:
        """Format thông tin tiến độ một môn"""
        ma_nhom = progress.get('ma_nhom', 'N/A')
        ten_mon = progress.get('ten_mon_hoc', 'Không có tên')
        tong_di_hoc = int(progress.get('tong_buoi_di_hoc', 0))
        tong_vang = int(progress.get('tong_buoi_vang', 0))
        progress_val = float(progress.get('progress', 0))
        status = progress.get('status', 'unknown')
        
        # Icon theo status
        if status == 'good':
            status_icon = "✅"
            status_text = "Tốt"
        elif status == 'warning':
            status_icon = "⚠️"
            status_text = "Cảnh báo"
        elif status == 'banned':
            status_icon = "❌"
            status_text = "Cấm thi"
        else:
            status_icon = "❓"
            status_text = "Không rõ"
        
        # Progress percentage
        progress_percent = int(progress_val * 100)
        
        result = f"{status_icon} **{index}. {ten_mon}**\n"
        result += f"   • Mã nhóm: {ma_nhom}\n"
        result += f"   • Đi học: {tong_di_hoc} buổi | Vắng: {tong_vang} buổi\n"
        result += f"   • Tỷ lệ điểm danh: {progress_percent}%\n"
        result += f"   • Trạng thái: {status_text}\n"
        
        # Thêm cảnh báo nếu highlight
        if highlight:
            if status == 'banned':
                result += f"   🚨 **BỊ CẤM THI** - Vắng quá nhiều!\n"
            elif status == 'warning':
                result += f"   ⚠️ **CẢNH BÁO** - Vắng thêm 1 buổi nữa sẽ bị cấm thi!\n"
        
        return result
    
    def _format_semester_name(self, nkhk: str) -> str:
        """Format tên học kỳ"""
        if not nkhk or len(nkhk) != 5:
            return f"Học kỳ {nkhk}"
        
        try:
            year1 = "20" + nkhk[:2]
            year2 = "20" + nkhk[2:4]
            semester_code = nkhk[4]
            
            semester_map = {'1': '1', '2': '2', '3': '3'}
            semester_name = semester_map.get(semester_code, semester_code)
            
            return f"Học kỳ {semester_name} năm {year1}-{year2}"
        except:
            return f"Học kỳ {nkhk}"
    
    def set_api_service(self, service):
        """Set API service instance"""
        self.api_service = service


class StudentCourseDetailTool(BDUBaseTool):
    """
    Tool để xem chi tiết điểm danh từng buổi của một môn học
    API: /odp/nhom-hoc/detail?ma_nhom=${ma_nhom}
    """
    
    name: str = "get_course_detail_attendance"
    description: str = """Xem chi tiết điểm danh từng buổi học của một môn học cụ thể.
    
    Sử dụng tool này khi sinh viên hỏi:
    - "Chi tiết điểm danh môn [tên môn]"
    - "Tôi vắng buổi nào môn [X]?"
    - "Lịch sử điểm danh môn [Y]"
    - "Xem điểm danh chi tiết [tên môn]"
    - "Môn [Z] thầy/cô ai dạy?"
    - "Giảng viên môn [tên môn]"
    - "Tỷ lệ đúng giờ môn [tên môn]"
    - "Điểm danh [tên môn] học kỳ [X]"
    
    Tool này sẽ:
    - TỰ ĐỘNG tìm môn học chỉ cần có TÊN MÔN (không cần mã phức tạp)
    - Hỗ trợ tìm trong nhiều học kỳ (hiện tại, trước đó, hoặc chỉ định)
    - Hiển thị thông tin môn học: mã môn, tên môn, giảng viên, phòng học
    - Hiển thị danh sách điểm danh từng buổi với ngày và trạng thái
    - Tính tỷ lệ đi học đúng giờ
    - Đếm số buổi đi học / vắng / đi muộn
    - Hiển thị giờ có mặt (nếu có)
    - Hiển thị link ảnh điểm danh (nếu có)
    
    TRẠNG THÁI ĐIỂM DANH:
    - "Có" / "Sớm" → Đi học ✅
    - "Trễ" → Đi muộn ⏰
    - "Vắng" → Vắng học ❌
    - "Phép" → Nghỉ có phép 📝
    
    Input: Câu hỏi (CHỈ CẦN TÊN MÔN, không cần mã phức tạp)
    Output: Chi tiết điểm danh từng buổi với timeline
    
    Ví dụ:
    - "Chi tiết điểm danh Quản trị dự án" → Tìm môn theo tên
    - "Xem điểm danh Điện toán đám mây" → Tự động tìm mã
    - "Điểm danh môn Phân tích dữ liệu học kỳ 1" → Tìm học kỳ cụ thể
    - "Tôi vắng buổi nào môn CNTT?" → Tìm môn có từ khóa CNTT
    
    QUAN TRỌNG: Tool này TỰ ĐỘNG tìm mã môn, user CHỈ CẦN nhập tên môn!
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """
        Execute course detail fetching
        """
        if not self.api_service:
            return "❌ API service chưa được khởi tạo"
        
        if not self.jwt_token:
            return "❌ Cần đăng nhập để xem chi tiết môn học"
        
        try:
            logger.info(f"🔍 Fetching course detail (query: '{query}')")
            
            # Trích xuất mã nhóm từ query
            ma_nhom = self._extract_ma_nhom_from_query(query)
            
            if not ma_nhom:
                # Nếu không có mã nhóm, tìm từ tên môn
                logger.info("🔍 No ma_nhom found, searching by course name...")
                ma_nhom = self._find_ma_nhom_by_course_name(query)
            
            if not ma_nhom:
                # Không tìm thấy môn học - gợi ý các môn có sẵn
                suggestion = self._get_course_suggestions(query)
                return (f"❌ Không tìm thấy môn học phù hợp với: '{query}'\n\n"
                       f"{suggestion}\n\n"
                       f"💡 **Gợi ý:**\n"
                       f"   • Hãy nhập tên môn chính xác hơn\n"
                       f"   • VD: 'Quản trị dự án', 'Điện toán đám mây', 'Phân tích dữ liệu'\n"
                       f"   • Hoặc dùng tool 'get_student_courses' để xem danh sách tất cả môn học")
            
            logger.info(f"📚 Using ma_nhom: {ma_nhom}")
            
            # Gọi API
            result = self._call_detail_api(ma_nhom)
            
            if not result or not result.get("ok"):
                reason = result.get("error", "Unknown") if result else "No response"
                logger.error(f"❌ Detail API failed: {reason}")
                return f"❌ Không thể lấy chi tiết môn học. Lý do: {reason}"
            
            detail_data = result.get("data", {})
            
            if not detail_data:
                return f"❌ Không tìm thấy dữ liệu cho mã nhóm: {ma_nhom}"
            
            logger.info(f"✅ Fetched detail for course: {detail_data.get('ten_mon_hoc', 'N/A')}")
            
            # Format response
            response = self._format_detail(detail_data, query)
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Course Detail Tool error: {str(e)}", exc_info=True)
            return f"❌ Đã xảy ra lỗi khi lấy chi tiết môn học: {str(e)}"
    
    def _get_course_suggestions(self, query: str) -> str:
        """
        Lấy gợi ý các môn học có sẵn khi không tìm thấy
        CẢI TIẾN: Show TẤT CẢ môn học (không limit 5)
        """
        try:
            # Lấy danh sách môn học kỳ hiện tại
            nkhk = self.api_service.get_latest_nkhk(self.jwt_token)
            if not nkhk:
                return "ℹ️ Không thể lấy danh sách môn học để gợi ý."
            
            courses = self._get_courses_for_semester(nkhk)
            
            if not courses:
                # Thử HK trước nếu HK hiện tại rỗng
                previous_nkhk = self.api_service.get_previous_nkhk(self.jwt_token)
                if previous_nkhk:
                    courses = self._get_courses_for_semester(previous_nkhk)
                    nkhk = previous_nkhk
            
            if not courses:
                return "ℹ️ Không có môn học nào trong học kỳ này."
            
            # Format semester name
            semester_name = self._format_semester_name(nkhk)
            
            # Lấy TẤT CẢ môn học (không limit)
            suggestion = f"📚 **Các môn học có sẵn ({semester_name}):**\n"
            for idx, course in enumerate(courses, 1):
                ten_mon = course.get('ten_mon_hoc', 'N/A')
                ma_mon = course.get('ma_mon', '')
                suggestion += f"   {idx}. {ten_mon} ({ma_mon})\n"
            
            return suggestion
            
        except Exception as e:
            logger.error(f"⚠️ Error getting suggestions: {e}")
            return "ℹ️ Vui lòng thử lại với tên môn chính xác hơn."
    
    def _format_semester_name(self, nkhk: str) -> str:
        """
        Format NKHK thành tên học kỳ đẹp
        Ví dụ: "24251" → "Học kỳ 1 năm 2024-2025"
        """
        if not nkhk or len(nkhk) != 5:
            return f"Học kỳ {nkhk}"
        
        try:
            year1 = "20" + nkhk[:2]
            year2 = "20" + nkhk[2:4]
            semester_code = nkhk[4]
            
            semester_map = {'1': '1', '2': '2', '3': '3'}
            semester_name = semester_map.get(semester_code, semester_code)
            
            return f"Học kỳ {semester_name} năm {year1}-{year2}"
        except:
            return f"Học kỳ {nkhk}"
    
    def _extract_ma_nhom_from_query(self, query: str) -> Optional[str]:
        """
        Trích xuất mã nhóm từ query
        Format: XXX####_#####_##
        Ví dụ: INF1313_24251_02
        """
        if not query:
            return None
        
        # Pattern: [A-Z]{3}\d{4}_\d{5}_\d{2}
        pattern = r'[A-Z]{3}\d{4}_\d{5}_\d{2}'
        match = re.search(pattern, query.upper())
        
        if match:
            ma_nhom = match.group(0)
            logger.info(f"✅ Extracted ma_nhom: {ma_nhom}")
            return ma_nhom
        
        return None
    
    def _extract_nkhk_from_query(self, query: str) -> Optional[str]:
        """
        Trích xuất mã NKHK từ câu hỏi
        Sử dụng logic tương tự external_api_service._extract_semester_from_query
        ✅ BỔ SUNG: Xử lý "kỳ trước", "học kỳ trước"
        """
        if not query:
            return None
        
        query_lower = query.lower().strip()
        
        # ✅ FIX 2: Xử lý "kỳ trước" / "học kỳ trước"
        previous_semester_phrases = [
            "kỳ trước", "ky truoc", 
            "học kỳ trước", "hoc ky truoc",
            "học kì trước", "hoc ki truoc",
            "kì trước", "ki truoc"
        ]
        
        if any(phrase in query_lower for phrase in previous_semester_phrases):
            logger.info("🔍 Detected 'kỳ trước' in query - calling get_previous_nkhk()")
            try:
                previous_nkhk = self.api_service.get_previous_nkhk(self.jwt_token)
                if previous_nkhk:
                    logger.info(f"✅ Using previous NKHK: {previous_nkhk}")
                    return previous_nkhk
                else:
                    logger.warning("⚠️ Could not get previous NKHK, fallback to current")
                    return None
            except Exception as e:
                logger.error(f"❌ Error getting previous NKHK: {e}")
                return None
        
        # Pattern: (học kỳ|kỳ) + (1|2|3) + (năm) + (YYYY-YYYY | YY-YY | YYYY)
        pattern = r"(?:hoc ky|học kỳ|ky|kỳ)\s*([123])\s*(?:nam|năm)?\s*(\d{2,4})(?:[-\s](\d{2,4}))?"
        
        match = re.search(pattern, query_lower)
        
        if match:
            hk_num = match.group(1)
            year1_str = match.group(2)
            year2_str = match.group(3)
            
            try:
                # Xử lý năm bắt đầu
                if len(year1_str) == 4:
                    year1_short = year1_str[-2:]
                elif len(year1_str) == 2:
                    year1_short = year1_str
                else:
                    return None
                
                # Xử lý năm kết thúc
                if year2_str:
                    if len(year2_str) == 4:
                        year2_short = year2_str[-2:]
                    elif len(year2_str) == 2:
                        year2_short = year2_str
                    else:
                        return None
                else:
                    year2_short = str(int(year1_short) + 1).zfill(2)
                
                # Map học kỳ
                hk_map = {'1': '1', '2': '2', '3': '3'}
                if hk_num in hk_map:
                    nkhk_suffix = hk_map[hk_num]
                    generated_nkhk = f"{year1_short}{year2_short}{nkhk_suffix}"
                    logger.info(f"🔍 Extracted NKHK from query: {generated_nkhk}")
                    return generated_nkhk
                
            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Error parsing semester from query: {e}")
                return None
        
        return None
    
    def _find_ma_nhom_by_course_name(self, query: str) -> Optional[str]:
        """
        Tìm mã nhóm bằng cách match tên môn học
        CẢI TIẾN: Tìm trong nhiều học kỳ, fuzzy matching thông minh
        """
        try:
            # Trích xuất học kỳ từ query (nếu có)
            specified_nkhk = self._extract_nkhk_from_query(query)
            
            # Danh sách học kỳ cần tìm
            nkhk_list = []
            
            if specified_nkhk:
                # Nếu user chỉ định học kỳ cụ thể
                nkhk_list = [specified_nkhk]
                logger.info(f"🔍 Searching in specified semester: {specified_nkhk}")
            else:
                # Tìm trong học kỳ hiện tại và trước đó
                current_nkhk = self.api_service.get_latest_nkhk(self.jwt_token)
                previous_nkhk = self.api_service.get_previous_nkhk(self.jwt_token)
                
                if current_nkhk:
                    nkhk_list.append(current_nkhk)
                if previous_nkhk:
                    nkhk_list.append(previous_nkhk)
                
                logger.info(f"🔍 Searching in semesters: {nkhk_list}")
            
            if not nkhk_list:
                logger.warning("⚠️ No semesters available for search")
                return None
            
            # Extract keywords từ query
            keywords = self._extract_course_keywords(query)
            logger.info(f"🔍 Extracted keywords: {keywords}")
            
            # Tìm trong tất cả các học kỳ
            all_matches = []
            
            for nkhk in nkhk_list:
                courses = self._get_courses_for_semester(nkhk)
                
                for course in courses:
                    ten_mon = course.get('ten_mon_hoc', '')
                    ma_nhom = course.get('ma_nhom', '')
                    
                    # Calculate matching score
                    score = self._calculate_match_score(keywords, ten_mon, query)
                    
                    if score > 0:
                        all_matches.append({
                            'ma_nhom': ma_nhom,
                            'ten_mon': ten_mon,
                            'nkhk': nkhk,
                            'score': score
                        })
                        logger.debug(f"  Match: {ten_mon} (score: {score:.2f})")
            
            # Sắp xếp theo score và chọn match tốt nhất
            if all_matches:
                all_matches.sort(key=lambda x: x['score'], reverse=True)
                best_match = all_matches[0]
                
                # ✅ CHECK SCORE THRESHOLD
                if best_match['score'] < MIN_SCORE_THRESHOLD:
                    logger.warning(f"⚠️ Best match score ({best_match['score']:.2f}) below threshold ({MIN_SCORE_THRESHOLD})")
                    logger.warning(f"   Query: '{query}'")
                    logger.warning(f"   Best match: '{best_match['ten_mon']}'")
                    logger.warning(f"   → REJECTING match (score too low)")
                    return None
                
                logger.info(f"✅ Best match: {best_match['ten_mon']} (score: {best_match['score']:.2f}, semester: {best_match['nkhk']})")
                return best_match['ma_nhom']
            
            logger.warning(f"⚠️ No course found matching '{query}'")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error finding ma_nhom by name: {e}", exc_info=True)
            return None
    
    def _get_courses_for_semester(self, nkhk: str) -> List[Dict]:
        """Lấy danh sách môn học của một học kỳ"""
        try:
            endpoint = f"{self.api_service.student_base}/odp/nhom-hoc/progress"
            headers = {
                "Authorization": f"Bearer {self.jwt_token}" if not self.jwt_token.startswith("Bearer") else self.jwt_token
            }
            params = {"nkhk": nkhk}
            
            import requests
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"⚠️ Failed to get courses for semester {nkhk}")
                return []
        except Exception as e:
            logger.error(f"❌ Error getting courses for {nkhk}: {e}")
            return []
    
    def _extract_course_keywords(self, query: str) -> List[str]:
        """
        Trích xuất từ khóa quan trọng từ query
        Bỏ qua stop words và các từ không liên quan
        """
        # Stop words tiếng Việt
        stop_words = {
            'môn', 'mon', 'của', 'cua', 'tôi', 'toi', 'mình', 'minh', 'em',
            'chi', 'tiết', 'tiet', 'xem', 'điểm', 'diem', 'danh', 'học', 'hoc',
            'thầy', 'thay', 'cô', 'co', 'giảng', 'giang', 'viên', 'vien',
            'là', 'la', 'ai', 'nào', 'nao', 'gì', 'gi', 'thế', 'the', 'nào',
            'vắng', 'vang', 'buổi', 'buoi', 'lịch', 'lich', 'sử', 'su',
            'trong', 'học', 'hoc', 'kỳ', 'ky', 'năm', 'nam', 'của', 'cua'
        }
        
        # Normalize và split
        query_normalized = self._normalize_vietnamese(query.lower())
        words = query_normalized.split()
        
        # Lọc stop words và từ quá ngắn
        keywords = []
        for word in words:
            word_clean = re.sub(r'[^a-z0-9]', '', word)
            if len(word_clean) >= 3 and word_clean not in stop_words:
                keywords.append(word_clean)
        
        return keywords
    
    def _calculate_match_score(self, keywords: List[str], ten_mon: str, original_query: str) -> float:
        """
        Tính điểm match giữa keywords và tên môn
        Score càng cao = match càng tốt
        
        CẢI TIẾN v2.1:
        - Tăng bonus cho exact substring match
        - Tăng bonus cho consecutive keywords
        - Giảm penalty cho tên dài
        """
        if not keywords or not ten_mon:
            return 0.0
        
        ten_mon_normalized = self._normalize_vietnamese(ten_mon.lower())
        original_query_normalized = self._normalize_vietnamese(original_query.lower())
        
        score = 0.0
        
        # 1. Exact substring match (điểm cao nhất)
        if original_query_normalized in ten_mon_normalized:
            # ✅ TĂNG từ 10 → 15 điểm
            score += 15.0
            logger.debug(f"      + Exact substring match: +15.0")
        
        # 2. Đếm số keywords xuất hiện
        matched_keywords = 0
        for keyword in keywords:
            if keyword in ten_mon_normalized:
                matched_keywords += 1
        
        # Tính tỷ lệ keywords match
        if keywords:
            keyword_ratio = matched_keywords / len(keywords)
            keyword_score = keyword_ratio * 8.0  # ✅ TĂNG từ 5 → 8 điểm
            score += keyword_score
            logger.debug(f"      + Keyword ratio ({matched_keywords}/{len(keywords)}): +{keyword_score:.1f}")
        
        # 3. Thưởng điểm nếu match nhiều keywords liên tiếp
        ten_mon_words = ten_mon_normalized.split()
        consecutive_matches = 0
        max_consecutive = 0
        
        for word in ten_mon_words:
            if any(keyword in word or word in keyword for keyword in keywords):
                consecutive_matches += 1
                max_consecutive = max(max_consecutive, consecutive_matches)
            else:
                consecutive_matches = 0
        
        consecutive_score = max_consecutive * 1.0  # ✅ TĂNG từ 0.5 → 1.0
        score += consecutive_score
        logger.debug(f"      + Consecutive keywords ({max_consecutive}): +{consecutive_score:.1f}")
        
        # ✅ FIX 3.4: Penalty nếu có keyword không match
        unmatched_keywords = 0
        for keyword in keywords:
            if not any(keyword in word or word in keyword for word in ten_mon_words):
                unmatched_keywords += 1
        
        if unmatched_keywords > 0:
            unmatch_penalty = unmatched_keywords * 1.5
            score -= unmatch_penalty
            logger.debug(f"      - Unmatched keywords ({unmatched_keywords}): -{unmatch_penalty:.1f}")
        
        # 4. Penalty cho tên môn quá dài (ưu tiên match chính xác hơn)
        length_penalty = len(ten_mon_normalized) / 150.0  # ✅ GIẢM từ /100 → /150
        score -= length_penalty
        logger.debug(f"      - Length penalty: -{length_penalty:.1f}")
        
        final_score = max(0.0, score)
        logger.debug(f"      = TOTAL SCORE: {final_score:.2f}")
        
        return final_score
    
    def _normalize_vietnamese(self, text: str) -> str:
        """
        Normalize Vietnamese text để so sánh
        CẢI TIẾN: Chuyển có dấu → không dấu ĐÚNG
        """
        if not text:
            return ""
        
        # Bảng chuyển đổi tiếng Việt có dấu → không dấu
        vietnamese_map = {
            'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
            'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
            'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
            'đ': 'd',
            'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
            'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
            'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
            'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
            'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
            'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
            'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
            'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
            'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
        }
        
        # Chuyển thành lowercase
        text = text.lower()
        
        # Thay thế từng ký tự
        result = []
        for char in text:
            result.append(vietnamese_map.get(char, char))
        
        text = ''.join(result)
        
        # Remove special chars (giữ chữ số, chữ cái)
        text = re.sub(r'[^a-z0-9\s]', '', text)
        
        # Remove extra spaces
        text = ' '.join(text.split())
        
        return text.strip()
    
    def _call_detail_api(self, ma_nhom: str) -> Dict[str, Any]:
        """
        Gọi API chi tiết môn học
        API: /odp/nhom-hoc/detail?ma_nhom={ma_nhom}
        """
        try:
            endpoint = f"{self.api_service.student_base}/odp/nhom-hoc/detail"
            headers = {
                "Authorization": f"Bearer {self.jwt_token}" if not self.jwt_token.startswith("Bearer") else self.jwt_token
            }
            params = {"ma_nhom": ma_nhom}
            
            logger.info(f"🌐 Calling API: {endpoint} with ma_nhom={ma_nhom}")
            
            import requests
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ API success: Got detail data")
                return {"ok": True, "data": data}
            else:
                logger.error(f"❌ API failed: {response.status_code} - {response.text}")
                return {"ok": False, "error": f"API returned {response.status_code}"}
                
        except Exception as e:
            logger.error(f"❌ API call error: {e}")
            return {"ok": False, "error": str(e)}
    
    def _format_detail(self, detail: Dict, query: str = "") -> str:
        """Format chi tiết môn học và điểm danh"""
        # Thông tin cơ bản
        ma_mon = detail.get('ma_mon', 'N/A')
        ten_mon = detail.get('ten_mon_hoc', 'Không có tên')
        ten_gv = detail.get('ten_giang_vien', 'Chưa cập nhật')
        phong_hoc = detail.get('phong_hoc', 'Chưa cập nhật')
        ma_nhom = detail.get('ma_nhom', 'N/A')
        
        tong_buoi = detail.get('tong_so_buoi', 0)
        so_di_hoc = detail.get('so_buoi_di_hoc', 0)
        so_vang = detail.get('so_buoi_vang', 0)
        ti_le_dung_gio = detail.get('ti_le_dung_gio', 0)
        
        ds_diem_danh = detail.get('ds_diem_danh', [])
        
        # Header
        response = f"📚 **Chi tiết môn học**\n\n"
        response += f"**[{ma_mon}] {ten_mon}**\n"
        response += f"👨‍🏫 Giảng viên: {ten_gv}\n"
        response += f"🏫 Phòng học: {phong_hoc}\n"
        response += f"🔢 Nhóm: {ma_nhom}\n"
        response += f"\n"
        
        # Thống kê
        response += f"📊 **Thống kê điểm danh:**\n"
        response += f"   • Tổng số buổi: {tong_buoi}\n"
        response += f"   • Đã đi học: {so_di_hoc} buổi ({so_di_hoc/tong_buoi*100:.1f}%)\n" if tong_buoi > 0 else f"   • Đã đi học: {so_di_hoc} buổi\n"
        response += f"   • Vắng: {so_vang} buổi\n"
        response += f"   • Tỷ lệ đúng giờ: {ti_le_dung_gio*100:.1f}%\n"
        
        # Cảnh báo nếu vắng nhiều
        if so_vang >= 2:
            response += f"\n🚨 **CẢNH BÁO: BỊ CẤM THI do vắng {so_vang} buổi!**\n"
        elif so_vang == 1:
            response += f"\n⚠️ **CẢNH BÁO: Đã vắng {so_vang} buổi. Vắng thêm 1 buổi nữa sẽ bị cấm thi!**\n"
        else:
            response += f"\n✅ **Tình trạng tốt** - Chưa vắng buổi nào\n"
        
        # Danh sách điểm danh chi tiết
        if ds_diem_danh:
            response += f"\n📋 **Lịch sử điểm danh ({len(ds_diem_danh)} buổi):**\n\n"
            
            # Sắp xếp theo buổi
            sorted_danh_sach = sorted(ds_diem_danh, key=lambda x: int(x.get('buoi', 0)))
            
            for item in sorted_danh_sach:
                response += self._format_single_attendance(item)
                response += "\n"
        else:
            response += f"\n📋 Chưa có dữ liệu điểm danh chi tiết.\n"
        
        return response
    
    def _format_single_attendance(self, item: Dict) -> str:
        """Format thông tin điểm danh một buổi"""
        buoi = item.get('buoi', '?')
        ngay = item.get('ngay', 'N/A')
        trang_thai = item.get('diem_danh', 'Chưa điểm danh')
        gio_co_mat = item.get('gio_co_mat', None)
        image_link = item.get('image_link', None)
        
        # Icon theo trạng thái
        if trang_thai in ['Có', 'Sớm']:
            icon = "✅"
        elif trang_thai == 'Trễ':
            icon = "⏰"
        elif trang_thai == 'Vắng':
            icon = "❌"
        elif trang_thai == 'Phép':
            icon = "📝"
        else:
            icon = "❓"
        
        # Format ngày
        date_formatted = self._format_date(ngay)
        
        result = f"{icon} **Buổi {buoi}** - {date_formatted}\n"
        result += f"   • Trạng thái: {trang_thai}\n"
        
        if gio_co_mat:
            result += f"   • Giờ có mặt: {gio_co_mat}\n"
        
        if image_link:
            result += f"   • 📷 [Xem ảnh điểm danh]({image_link})\n"
        
        return result
    
    def _format_date(self, date_str: str) -> str:
        """
        Format date to Vietnamese
        Input: YYYY-MM-DD
        Output: Thứ X, DD/MM/YYYY
        """
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            
            weekdays = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật']
            weekday = weekdays[date_obj.weekday()]
            
            return f"{weekday}, {date_obj.strftime('%d/%m/%Y')}"
        except:
            return date_str
    
    def set_api_service(self, service):
        """Set API service instance"""
        self.api_service = service