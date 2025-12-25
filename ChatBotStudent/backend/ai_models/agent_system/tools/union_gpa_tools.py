"""
Union & GPA Tools - Thông tin đoàn viên và điểm số chi tiết
Tools để lấy thông tin đoàn viên, điểm TB học kỳ, bảng điểm
VÀ CHƯƠNG TRÌNH ĐÀO TẠO
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from .base_tool import BDUBaseTool

logger = logging.getLogger(__name__)


# ================================
# 1. STUDENT UNION INFO TOOL
# ================================
class StudentUnionInfoTool(BDUBaseTool):
    """Tool to get student union/youth organization information"""
    
    name: str = "get_student_union_info"
    description: str = """Lấy thông tin đoàn viên, hội sinh viên của sinh viên.
    
    Sử dụng khi sinh viên hỏi:
    - "Thông tin đoàn viên của tôi"
    - "Tôi có phải là đoàn viên không?"
    - "Ngày vào đoàn của tôi"
    - "Thẻ đoàn của tôi"
    - "Chức vụ đoàn hội"
    - "Tôi thuộc chi đoàn nào?"
    
    Input: Câu hỏi (tùy chọn)
    Output: Thông tin đoàn viên đầy đủ
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get union info"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem thông tin đoàn viên."
        
        try:
            logger.info(f"✊ Fetching union info for: '{query}'")
            
            result = self.api_service.get_student_union_info(
                jwt_token=self.jwt_token
            )
            
            if not result or not result.get("ok"):
                reason = result.get("reason", "Unknown") if result else "No response"
                return f"❌ Không thể lấy thông tin đoàn viên. Lý do: {reason}"
            
            union_data = result.get("data", {})
            
            if not union_data:
                return "✊ Chưa có thông tin đoàn viên được cập nhật."
            
            response = self._format_union_info(union_data)
            logger.info(f"✅ Union info fetched successfully")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def _format_union_info(self, data: Dict[str, Any]) -> str:
        """
        Format union info from API response
        """
        if not data:
            return "✊ Chưa có thông tin đoàn viên."
        
        response = "✊ **THÔNG TIN ĐOÀN VIÊN - HỘI SINH VIÊN**\n\n"
        
        # Thông tin cơ bản
        so_the = data.get('so_the_doan', 'N/A')
        ngay_vao_doan = data.get('ngay_vao_doan', 'N/A')
        chuc_vu = data.get('chuc_vu_chi_doan', 'N/A')
        
        # Format ngày vào đoàn
        if ngay_vao_doan and ngay_vao_doan != 'N/A':
            try:
                date_obj = datetime.strptime(ngay_vao_doan, '%Y-%m-%d')
                ngay_display = date_obj.strftime('%d/%m/%Y')
            except:
                ngay_display = ngay_vao_doan
        else:
            ngay_display = 'N/A'
        
        response += f"🎫 **Số thẻ đoàn:** {so_the}\n"
        response += f"📅 **Ngày vào đoàn:** {ngay_display}\n"
        response += f"👤 **Chức vụ:** {chuc_vu}\n\n"
        
        # Đơn vị
        don_vi = data.get('don_vi', '')
        if don_vi:
            response += f"🏢 **Đơn vị:**\n{don_vi}\n\n"
        
        # Hội
        hoi = data.get('hoi', 'N/A')
        response += f"🤝 **Hội:** {hoi}\n\n"
        
        # Trạng thái hoạt động
        response += "📊 **TRẠNG THÁI HOẠT ĐỘNG:**\n"
        
        doi_tuong = data.get('doi_tuong_doan_vien', 'N/A')
        ren_luyen = data.get('ren_luyen_doan_vien', 'N/A')
        danh_gia = data.get('danh_gia_xep_loai', 'N/A')
        
        response += f"   • Đối tượng: {doi_tuong}\n"
        response += f"   • Rèn luyện: {ren_luyen}\n"
        response += f"   • Đánh giá: {danh_gia}\n\n"
        
        # Khen thưởng & Kỷ luật
        khen_thuong = data.get('khen_thuong', 'Không')
        ky_luat = data.get('ky_luat', 'Không')
        
        if khen_thuong != 'Không' or ky_luat != 'Không':
            response += "🏆 **KHEN THƯỞNG & KỶ LUẬT:**\n"
            if khen_thuong != 'Không':
                response += f"   ✅ Khen thưởng: {khen_thuong}\n"
            if ky_luat != 'Không':
                response += f"   ⚠️ Kỷ luật: {ky_luat}\n"
            response += "\n"
        
        # Trình độ
        response += "📚 **TRÌNH ĐỘ:**\n"
        
        van_hoa = data.get('trinh_do_van_hoa', 'N/A')
        chuyen_mon = data.get('trinh_do_chuyen_mon', 'Chưa có')
        ly_luan = data.get('trinh_do_ly_luan_chinh_tri', 'Chưa có')
        tin_hoc = data.get('tin_hoc', 'Chưa có')
        ngoai_ngu = data.get('ngoai_ngu', 'Chưa có')
        
        response += f"   • Văn hóa: {van_hoa}\n"
        response += f"   • Chuyên môn: {chuyen_mon}\n"
        response += f"   • Lý luận chính trị: {ly_luan}\n"
        response += f"   • Tin học: {tin_hoc}\n"
        if ngoai_ngu and ngoai_ngu != 'Chưa có':
            response += f"   • Ngoại ngữ: {ngoai_ngu}\n"
        
        # Ngày vào đảng (nếu có)
        ngay_vao_dang = data.get('ngay_vao_dang')
        if ngay_vao_dang:
            try:
                date_obj = datetime.strptime(ngay_vao_dang, '%Y-%m-%d')
                dang_display = date_obj.strftime('%d/%m/%Y')
                response += f"\n🎉 **Ngày vào Đảng:** {dang_display}\n"
            except:
                pass
        
        return response
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 2. STUDENT SEMESTER GPA TOOL
# ================================
class StudentSemesterGPATool(BDUBaseTool):
    """Tool to get GPA for specific semester"""
    
    name: str = "get_student_semester_gpa"
    description: str = """Lấy điểm trung bình của sinh viên theo học kỳ cụ thể.
    
    Sử dụng khi sinh viên hỏi:
    - "Điểm trung bình học kỳ này"
    - "GPA học kỳ 1"
    - "Xếp loại học kỳ 2"
    - "Điểm TB học kỳ 2024-2025"
    
    Input: Câu hỏi (có thể chứa học kỳ)
    Output: Điểm TB, xếp loại, tổng tín chỉ của học kỳ
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get semester GPA"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem điểm."
        
        try:
            logger.info(f"📊 Fetching semester GPA for: '{query}'")
            
            # API tự động xử lý nkhk từ query hoặc lấy học kỳ hiện tại
            result = self.api_service.get_student_semester_gpa(
                jwt_token=self.jwt_token,
                query=query,
                nkhk=None  # Auto-determine
            )
            
            if not result or not result.get("ok"):
                reason = result.get("reason", "Unknown") if result else "No response"
                return f"❌ Không thể lấy điểm trung bình. Lý do: {reason}"
            
            gpa_data = result.get("data", {})
            
            if not gpa_data:
                return "📊 Chưa có điểm trung bình được công bố cho học kỳ này."
            
            response = self._format_semester_gpa(gpa_data)
            logger.info(f"✅ Semester GPA fetched successfully")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def _format_semester_gpa(self, data: Dict[str, Any]) -> str:
        """
        Format semester GPA from API response
        """
        if not data:
            return "📊 Chưa có điểm trung bình."
        
        tin_chi = data.get('tong_tin_chi', 0)
        diem_10 = data.get('diem_trung_binh_he_10', 0)
        diem_4 = data.get('diem_trung_binh_he_4', 0)
        xep_loai = data.get('xep_loai', 'N/A')
        
        response = f"""📊 **ĐIỂM TRUNG BÌNH HỌC KỲ**

📚 Tổng tín chỉ: **{tin_chi} TC**

📈 Điểm trung bình:
   • Hệ 10: **{diem_10:.2f}**
   • Hệ 4: **{diem_4:.2f}**

🏅 Xếp loại: **{xep_loai}**
"""
        
        # Thêm đánh giá
        if diem_10 >= 9.0:
            response += "\n✨ Xuất sắc! Hãy tiếp tục phát huy!"
        elif diem_10 >= 8.0:
            response += "\n👍 Giỏi! Kết quả rất tốt!"
        elif diem_10 >= 7.0:
            response += "\n📈 Khá! Tiếp tục cố gắng!"
        elif diem_10 >= 6.5:
            response += "\n✅ Đạt! Hãy cải thiện thêm!"
        elif diem_10 >= 5.0:
            response += "\n⚠️ Trung bình! Cần nỗ lực hơn nữa!"
        else:
            response += "\n🔔 Cần cố gắng nhiều hơn trong học kỳ tới!"
        
        return response
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 3. STUDENT SCORE LIST TOOL
# ================================
class StudentScoreListTool(BDUBaseTool):
    """Tool to get list of scores for all subjects in a semester"""
    
    name: str = "get_student_score_list"
    description: str = """Lấy danh sách điểm các môn học trong học kỳ.
    
    Sử dụng khi sinh viên hỏi:
    - "Bảng điểm của tôi"
    - "Điểm các môn học kỳ này"
    - "Xem điểm tất cả các môn"
    - "Danh sách điểm học kỳ 1"
    
    Input: Câu hỏi (có thể chứa học kỳ)
    Output: Danh sách điểm từng môn với điểm xếp hạng
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """Get score list"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem bảng điểm."
        
        try:
            logger.info(f"📋 Fetching score list for: '{query}'")
            
            # Lấy nkhk từ query hoặc dùng học kỳ hiện tại
            from ai_models.external_api_service import external_api_service
            
            # Extract nkhk nếu có trong query
            nkhk = None
            # TODO: Parse nkhk from query if needed
            
            if not nkhk:
                # Lấy học kỳ hiện tại
                nkhk = external_api_service.get_latest_nkhk(self.jwt_token)
            
            if not nkhk:
                return "❌ Không thể xác định học kỳ. Vui lòng chỉ rõ học kỳ."
            
            result = external_api_service.get_score_list(
                jwt_token=self.jwt_token,
                nkhk=nkhk
            )
            
            if not result or not result.get("ok"):
                reason = result.get("reason", "Unknown") if result else "No response"
                return f"❌ Không thể lấy bảng điểm. Lý do: {reason}"
            
            score_list = result.get("data", [])
            
            if not score_list:
                return "📋 Chưa có điểm nào được công bố cho học kỳ này."
            
            response = self._format_score_list(score_list)
            logger.info(f"✅ Score list fetched: {len(score_list)} subjects")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def _format_score_list(self, score_list: list) -> str:
        """
        Format score list from API response
        """
        if not score_list:
            return "📋 Chưa có bảng điểm."
        
        response = "📋 **BẢNG ĐIỂM CÁC MÔN HỌC**\n\n"
        
        # Tính tổng tín chỉ
        total_tc = sum(subject.get('tin_chi', 0) for subject in score_list)
        
        # Đếm số môn theo điểm
        grade_count = {}
        for subject in score_list:
            grade = subject.get('diem_xep_hang', 'N/A')
            grade_count[grade] = grade_count.get(grade, 0) + 1
        
        # Hiển thị từng môn
        for i, subject in enumerate(score_list, 1):
            ma_mon = subject.get('ma_mon_hoc', 'N/A')
            ten_mon = subject.get('ten_mon_hoc', 'N/A')
            tin_chi = subject.get('tin_chi', 0)
            diem = subject.get('diem_xep_hang', 'N/A')
            
            # Icon theo điểm
            if diem in ['A+', 'A']:
                icon = "🌟"
            elif diem in ['B+', 'B']:
                icon = "✅"
            elif diem in ['C+', 'C']:
                icon = "📊"
            elif diem == 'P':
                icon = "✔️"
            else:
                icon = "📝"
            
            response += f"{icon} **{ten_mon}** ({ma_mon})\n"
            response += f"   Tín chỉ: {tin_chi} TC | Điểm: **{diem}**\n\n"
        
        # Tổng kết
        response += f"📊 **TỔNG KẾT:**\n"
        response += f"   • Tổng số môn: {len(score_list)}\n"
        response += f"   • Tổng tín chỉ: {total_tc} TC\n\n"
        
        # Phân bố điểm
        response += "📈 **Phân bố điểm:**\n"
        for grade in sorted(grade_count.keys(), reverse=True):
            if grade != 'N/A':
                response += f"   • Điểm {grade}: {grade_count[grade]} môn\n"
        
        return response
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 4. STUDENT CURRICULUM TOOL (NEW!)
# ================================
class StudentCurriculumTool(BDUBaseTool):
    """Tool to get student's curriculum/study program"""
    
    name: str = "get_student_curriculum"
    description: str = """Lấy chương trình đào tạo của sinh viên.
    
    Sử dụng khi sinh viên hỏi:
    - "Chương trình đào tạo của tôi"
    - "Tôi cần học những môn gì?"
    - "Các môn bắt buộc"
    - "Các môn tự chọn"
    - "Lộ trình học"
    
    Input: Câu hỏi (tùy chọn)
    Output: Phân tích chi tiết chương trình đào tạo, các môn đã học,
            chưa học, và đề xuất lộ trình cho học kỳ tới.
    """
    
    category: str = "student_api"
    requires_auth: bool = True
    api_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True

    def _format_credits_overview(self, credits_data: Dict) -> str:
        """Helper: Format phần tổng quan tín chỉ"""
        try:
            total_credit = int(credits_data.get('total_credit', 0))
            required_credit = int(credits_data.get('required_credit', 0))
            
            if required_credit == 0: # Tránh chia cho 0
                percentage = 0.0
                missing_credits = 0
            else:
                percentage = (total_credit / required_credit) * 100
                missing_credits = required_credit - total_credit
            
            response = "📊 **Tổng quan:**\n"
            response += f"   ✅ Đã tích lũy: **{total_credit} / {required_credit}** tín chỉ ({percentage:.1f}%)\n"
            if missing_credits > 0:
                response += f"   ⚠️ Còn thiếu: **{missing_credits}** tín chỉ\n"
            else:
                response += "   🎉 Chúc mừng! Bạn đã hoàn thành đủ tín chỉ!\n"
            response += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            return response
            
        except Exception as e:
            logger.warning(f"⚠️ Could not format credits overview: {e}")
            return ""

    def _format_subject_group(self, group: Dict) -> tuple[str, List[Dict]]:
        """
        Helper: Format 1 nhóm môn học và trả về đề xuất môn
        Returns: (response_string, suggestion_list)
        """
        group_response = ""
        suggestions = []
        
        try:
            group_name = group.get('nhom_mon_hoc', 'N/A')
            status = group.get('trang_thai', 'N/A')
            yeu_cau_raw = group.get('tin_chi_yeu_cau') # Có thể là null hoặc số
            dat_duoc = int(group.get('tin_chi_dat_duoc', 0))
            all_subjects = group.get('danh_sach_mon_hoc', [])
            
            group_response += f"▫️ **{group_name}**\n"

            # Case 1: Nhóm Bắt buộc (phải học hết)
            if yeu_cau_raw is None:
                unlearned_subjects = [s for s in all_subjects if s.get('trang_thai') == 'Chưa học']
                
                if status == "Chưa hoàn thành":
                    group_response += f"   ⚠️ **Chưa hoàn thành** (Đã đạt: {dat_duoc} TC)\n"
                    group_response += "   📌 Phải học HẾT TẤT CẢ các môn bắt buộc trong nhóm này.\n"
                    
                    if unlearned_subjects:
                        group_response += "\n   ❌ **Các môn bắt buộc chưa học:**\n"
                        for s in unlearned_subjects:
                            ten_mon = s.get('ten_mon_hoc', 'N/A')
                            ma_mon = s.get('ma_mon', 'N/A')
                            so_tc = s.get('so_tin_chi', 0)
                            group_response += f"      • {ma_mon} - {ten_mon} ({so_tc} TC)\n"
                            
                            # Thêm vào đề xuất (cho lộ trình)
                            s['is_mandatory'] = True
                            suggestions.append(s)
                    else:
                         group_response += "   ✅ Đã đăng ký/học tất cả môn, chờ hoàn thành.\n"
                else:
                    group_response += f"   ✅ **Hoàn thành** (Đã đạt: {dat_duoc} TC)\n"
            
            # Case 2: Nhóm Tự chọn (đạt đủ số TC)
            else:
                yeu_cau = int(yeu_cau_raw)
                if status == "Chưa hoàn thành":
                    missing_credits = yeu_cau - dat_duoc
                    group_response += f"   ⚠️ **Chưa hoàn thành** (Đã đạt: {dat_duoc} / {yeu_cau} TC)\n"
                    group_response += f"   📌 **Còn thiếu: {missing_credits} tín chỉ**\n"
                    
                    # Tìm môn có thể học
                    available_subjects = [s for s in all_subjects if s.get('trang_thai') == 'Chưa học']
                    
                    if available_subjects:
                        group_response += "\n   💡 **Gợi ý các môn có thể học:**\n"
                        
                        # Logic đề xuất (ưu tiên môn >= số TC thiếu)
                        exact_matches = [s for s in available_subjects if s.get('so_tin_chi') == missing_credits]
                        over_matches = sorted([s for s in available_subjects if s.get('so_tin_chi', 0) > missing_credits], key=lambda x: x.get('so_tin_chi', 0))
                        under_matches = sorted([s for s in available_subjects if s.get('so_tin_chi', 0) < missing_credits], key=lambda x: x.get('so_tin_chi', 0), reverse=True)
                        
                        # Lấy tối đa 3 đề xuất
                        recommendations = (exact_matches + over_matches + under_matches)[:3]
                        
                        for s in recommendations:
                            ten_mon = s.get('ten_mon_hoc', 'N/A')
                            ma_mon = s.get('ma_mon', 'N/A')
                            so_tc = s.get('so_tin_chi', 0)
                            group_response += f"      • {ma_mon} - {ten_mon} ({so_tc} TC)\n"

                        # Thêm 1 môn vào đề xuất tổng (cho lộ trình)
                        if recommendations:
                            rec = recommendations[0].copy() # Dùng copy để tránh thay đổi
                            rec['is_mandatory'] = False
                            suggestions.append(rec)
                    else:
                        group_response += "   (Không còn môn 'Chưa học' nào trong nhóm này)\n"
                else:
                     group_response += f"   ✅ **Hoàn thành** (Đã đạt: {dat_duoc} / {yeu_cau} TC)\n"

            group_response += "\n" # Thêm khoảng trắng
            return group_response, suggestions

        except Exception as e:
            logger.error(f"❌ Error formatting subject group '{group.get('nhom_mon_hoc')}': {e}")
            return f"▫️ Lỗi xử lý nhóm {group.get('nhom_mon_hoc')}\n", []

    def _format_next_semester_plan(self, suggestions: List[Dict]) -> str:
        """Helper: Format lộ trình đề xuất"""
        plan_response = "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        plan_response += "🎯 **Đề xuất môn học cho học kỳ tới**\n\n"
        
        if not suggestions:
            plan_response += "✅ Bạn không còn môn 'Chưa học' nào trong các nhóm chưa hoàn thành.\n"
            return plan_response

        final_plan = []
        seen_codes = set()
        total_credits = 0
        
        # Ưu tiên môn Bắt buộc
        mandatory = [s for s in suggestions if s.get('is_mandatory')]
        elective = [s for s in suggestions if not s.get('is_mandatory')]
        
        # Giới hạn 5 môn hoặc 15 TC
        for s in (mandatory + elective):
            ma_mon = s.get('ma_mon')
            so_tc = int(s.get('so_tin_chi', 0))
            
            if ma_mon not in seen_codes and len(final_plan) < 5 and (total_credits + so_tc) <= 15:
                final_plan.append(s)
                seen_codes.add(ma_mon)
                total_credits += so_tc

        if not final_plan:
             plan_response += "✅ Không có đề xuất môn học nào (có thể các môn đều 'Đang học').\n"
             return plan_response

        for i, s in enumerate(final_plan, 1):
            tag = "Bắt buộc" if s.get('is_mandatory') else "Tự chọn"
            plan_response += f"{i}. {s.get('ma_mon')} - {s.get('ten_mon_hoc')} ({s.get('so_tin_chi')} TC)\n"
            plan_response += f"   (Nhóm: [{tag}])\n"

        plan_response += f"\n📌 **Tổng cộng (gợi ý): {total_credits} tín chỉ**"
        plan_response += "\n(Đây là gợi ý, bạn nên đăng ký theo kế hoạch và điều kiện cá nhân.)"
        
        return plan_response

    def execute(self, query: str = "") -> str:
        """Get curriculum"""
        if not self.api_service:
            return "❌ API service not initialized"
        
        if not self.jwt_token:
            return "❌ Vui lòng đăng nhập để xem chương trình đào tạo."
        
        try:
            logger.info(f"🎓 Fetching curriculum for: '{query}'")
            
            # === 1. Gọi API Tín chỉ (Tổng quan) ===
            credits_result = self.api_service.get_student_credits(
                jwt_token=self.jwt_token,
                query=query
            )
            if not credits_result or not credits_result.get("ok"):
                logger.warning("⚠️ Could not fetch credits overview")
                credits_data = {}
            else:
                credits_data = credits_result.get("data", {})

            # === 2. Gọi API Chương trình đào tạo (Chi tiết) ===
            curriculum_result = self.api_service.get_student_curriculum(
                jwt_token=self.jwt_token
            )
            
            if not curriculum_result or not curriculum_result.get("ok"):
                reason = curriculum_result.get("reason", "Unknown") if curriculum_result else "No response"
                return f"❌ Không thể lấy chương trình đào tạo. Lý do: {reason}"
            
            curriculum_data = curriculum_result.get("data", [])
            
            if not curriculum_data:
                return "🎓 Bạn chưa có chương trình đào tạo nào."

            # === 3. Xử lý và Format Data ===
            response = "📚 **CHƯƠNG TRÌNH ĐÀO TẠO CỦA BẠN**\n\n"
            next_semester_suggestions = []

            # Thêm phần tổng quan tín chỉ
            response += self._format_credits_overview(credits_data)
            
            # Duyệt qua từng khối kiến thức
            for block in curriculum_data:
                response += f"📖 **{block.get('khoi_kien_thuc', 'N/A')}**\n\n"
                
                # Duyệt qua từng nhóm môn trong khối
                for group in block.get('nhom_hoc', []):
                    group_response, group_suggestions = self._format_subject_group(group)
                    response += group_response
                    next_semester_suggestions.extend(group_suggestions)
                
                response += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # === 4. Thêm lộ trình đề xuất ===
            response += self._format_next_semester_plan(next_semester_suggestions)
            
            logger.info(f"✅ Curriculum processed successfully")
            return response
            
        except Exception as e:
            logger.error(f"❌ Curriculum Tool Error: {str(e)}", exc_info=True)
            return f"Lỗi: {str(e)}"
    
    def set_api_service(self, service):
        self.api_service = service


# ================================
# 5. STUDENT SCORE DETAIL TOOL (PLACEHOLDER)
# ================================
# TODO: Chờ data từ API /odp/bang-diem?ma_nhom={ma_nhom}
# class StudentScoreDetailTool(BDUBaseTool):
#     """Tool to get detailed score breakdown for a subject"""
#     
#     name: str = "get_student_score_detail"
#     description: str = """Lấy chi tiết điểm thành phần của môn học.
#     
#     Sử dụng khi sinh viên hỏi:
#     - "Chi tiết điểm môn X"
#     - "Điểm chuyên cần, giữa kỳ, cuối kỳ môn Y"
#     - "Điểm thành phần môn Z"
#     """
#     
#     # TODO: Implement khi có data


# ================================
# 6. STUDENT CURRICULUM TOOL (OLD PLACEHOLDER - NAY ĐÃ CÓ)
# ================================
# (Đã implement ở trên)