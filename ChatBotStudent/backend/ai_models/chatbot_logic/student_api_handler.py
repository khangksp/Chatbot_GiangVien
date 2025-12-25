import logging
from typing import Dict, Any, Optional, Tuple, List
from ..external_api_service import external_api_service
from ..gemini_service import GeminiResponseGenerator
import re
import unicodedata
from collections import defaultdict

logger = logging.getLogger(__name__)

def _normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ascii")
    return s.lower()

#
# --- THÊM HÀM HELPER MỚI NÀY ---
#
def _extract_teacher_name(query: str) -> str:
    """
    Trích xuất tên giảng viên từ câu hỏi (ví dụ: 'thầy hiệp', 'cô lan').
    """
    q = query.lower()
    # Tìm các cụm từ "thầy/cô/gv [Tên]"
    match = re.search(r'(?:thầy|cô|giảng viên|gv)\s+([a-zà-ỹ\s]+)', q)
    if match:
        name = match.group(1).strip()
        # Loại bỏ các từ rác phía sau tên
        name = re.sub(r'\s*(dạy|học|môn|gì|trong|tuần|này|á|ạ|vậy|\?|ko).*', '', name, flags=re.IGNORECASE).strip()
        
        if name == "cô": # Xử lý trường hợp "thầy cô" (không có tên)
            return ""
            
        logger.info(f"🔍 Trích xuất tên Giảng viên: '{name}'")
        return name
    return ""
# --- KẾT THÚC HÀM MỚI ---
def _needs_student_news(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    news_keywords = [
        "tin tức", "tin tuc", "thông báo", "thong bao", "có gì mới", 
        "co gi moi", "tin mới", "tin moi", "thông tin mới", "thong tin moi",
        "tin tức hôm nay", "tin tuc hom nay", "thông báo mới", "thong bao moi",
    ]
    return any(keyword in q for keyword in news_keywords)

def _needs_student_news_detail(query: str) -> bool:
    if not query: 
        return False
    q = query.lower()
    return any(kw in q for kw in [
        "chi tiết tin", "xem chi tiết", "chi tiet tin",
        "bài số", "bai so", "tin số", "tin so",
        "mục số", "muc so", "thông báo số", "thong bao so",
        "xem thông báo số", "xem thong bao so"
    ])

def _extract_news_index(query: str) -> Optional[int]:
    q = query.lower()
    m = re.search(r'(?:bài|bai|tin|mục|muc|thông\s*báo|thong\s*bao|tb|#)\s*(?:số|so)?\s*#?\s*(\d{1,2})', q)
    if not m:
        m = re.search(r'\b(?:số|so)\s*(\d{1,2})\b', q)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 50 else None
    return None

def _pick_news_by_title(items: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
    q = query.lower()
    scored = []
    for it in items:
        title = (it.get("title") or "").lower()
        if not title:
            continue
        # điểm dựa vào tỉ lệ từ chung
        q_words = [w for w in re.split(r'\W+', q) if len(w) > 2]
        t_words = [w for w in re.split(r'\W+', title) if len(w) > 2]
        overlap = len(set(q_words) & set(t_words))
        scored.append((overlap, len(t_words), it))
    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][2]
    return None

def _format_news_detail(it: Dict[str, Any]) -> str:
    title = (it.get("title") or "").strip()
    cat = (it.get("category") or "").strip()
    date = (it.get("date") or "").strip()
    time = (it.get("time") or "").strip()
    plain = (it.get("plain") or it.get("html") or "").strip()

    sents = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', plain) if s.strip()]
    bullets = sents[:5] if sents else [title or ""]

    header = f"**{title}**\n"
    meta = []
    if cat: meta.append(cat)
    if date: meta.append(date)
    if time: meta.append(time)
    if meta: header += "_{}_\n".format(" • ".join(meta))

    body = "\n".join(f"- {b}" for b in bullets)
    note = "\n\n_(Mở \"Xem toàn văn\" để đọc đầy đủ. Các hình ảnh/biểu mẫu giữ nguyên trong phần HTML.)_"
    return header + body + note

def _extract_nkhk_from_query(query: str) -> Optional[str]:
    if not query:
        return None
    
    match = re.search(r'(?:nkhk|hoc ky|học kỳ)\s*(\d{5})', query.lower())
    if match:
        nkhk = match.group(1)
        logger.info(f"🔍 Extracted NKHK from query: {nkhk}")
        return nkhk
    
    from ..external_api_service import _extract_semester_from_query
    mapped_nkhk = _extract_semester_from_query(query)
    if mapped_nkhk:
        logger.info(f"🔍 Mapped semester to NKHK: {mapped_nkhk}")
        return mapped_nkhk
    
    return None

def _needs_student_schedule(query: str) -> bool:
    if not query:
        return False
    
    q = query.lower()
    schedule_keywords = [
        "lịch học", "tkb", "thời khóa biểu", "tiết học", "môn học hôm nay",
        "tuần này học", "ngày mai học", "lịch của tôi", "học tuyến",
        "lịch sinh viên", "thời khóa biểu sinh viên", "lịch học sinh viên",
        "hôm nay học gì", "ngày mai học gì", "tuần này học gì",
        "học những môn nào", "môn nào", "học gì", "tuần sau học", "tuần sau tôi",
        "sẽ học", "có học", "học môn gì", "lịch tuần sau", "lịch tuần tới"
    ]
    time_patterns = ["tuần sau", "tuần tới", "tuần này", "ngày mai", "hôm nay", "next week"]
    has_time = any(pattern in q for pattern in time_patterns)
    has_study = any(word in q for word in ["học", "môn", "học gì", "học những", "môn nào"])
    
    return any(keyword in q for keyword in schedule_keywords) or (has_time and has_study)

def _needs_student_profile(query: str) -> bool:
    if not query:
        return False
    q = query.lower().strip()
    
    # Chỉ trigger khi hỏi RÕ RÀNG về bản thân hoặc chào hỏi
    profile_keywords = [
        "tôi là ai", "toi la ai", "tôi tên gì", "toi ten gi",
        "mssv của tôi", "mssv cua toi", "mã sinh viên của tôi",
        "thông tin cá nhân", "thong tin ca nhan", "profile của tôi",
        "xin chào", "hello", "hi", "chào bạn", "chao ban", "chào"
    ]
    
    # Phải là câu chào duy nhất
    if q in ["xin chào", "hello", "hi", "chào", "chào bạn"]:
        return True
    
    if any(kw in q for kw in profile_keywords):
        logger.info(f"🎯 Detected profile intent (explicit) for query: '{query}'")
        return True
    
    return False

def _needs_student_grades(query: str) -> bool:
    if not query:
        return False
    
    nq = _normalize_text(query)
    
    keywords = [
        "gpa", "cgpa", "grade point average",
        "diem trung binh", "diem tb", "dtb",
        "diem tich luy", "diem trung binh tich luy",
        "gpa cua toi", "gpa cua minh",
        "diem tong ket", "diem tong ket cua toi"
    ]
    
    if any(kw in nq for kw in keywords):
        if ("tin chi" in nq) and not any(x in nq for x in ["gpa", "diem", "tb"]):
            return False
        return True

    query_lower = query.lower()
    return "điểm trung bình" in query_lower or "điểm tổng kết" in query_lower

def _needs_student_tuition(query: str) -> bool:
    if not query:
        return False
    
    q = query.lower()
    tuition_keywords = [
        "học phí", "hoc phi", "thanh toán", "tiền học", "con lai",
        "bao nhiêu tiền", "đã đóng", "chưa đóng", "bảo hiểm", "bhyt",
        "học phí của tôi", "hoc phi cua toi", "số tiền học", "so tien hoc",
        "tình trạng học phí", "tinh trang hoc phi",
        "học phí các kì", "hoc phi cac ki", "học phí kì", "hoc phi ki",
        "học phí năm", "hoc phi nam",
    ]
    return any(keyword in q for keyword in tuition_keywords)

def _parse_nkhk_to_year(nkhk: int) -> str:
    nkhk_str = str(nkhk)
    if len(nkhk_str) >= 4:
        year_start = nkhk_str[:2]
        year_end = nkhk_str[2:4]
        if year_start.isdigit() and year_end.isdigit():
             return f"{year_start}-{year_end}"
    return ""

def _parse_curriculum_data(curriculum_data: List[Dict], query: str, total_credits_achieved: int = 0, total_credits_required: int = 0) -> str:
    q_lower = query.lower()
    relevant_subjects = []
    for khoi in curriculum_data:
        khoi_name = khoi.get("khoi_kien_thuc", "")
        for nhom in khoi.get("nhom_hoc", []):
            nhom_name = nhom.get("nhom_mon_hoc", "")
            trang_thai = nhom.get("trang_thai", "")
            tin_chi_yeu_cau = nhom.get("tin_chi_yeu_cau")
            tin_chi_dat = nhom.get("tin_chi_dat_duoc", 0)
            
            needs_completion = False
            
            if trang_thai == "Chưa hoàn thành":
                if tin_chi_yeu_cau is None:
                    needs_completion = True
                elif tin_chi_dat < tin_chi_yeu_cau:
                    needs_completion = True
                else:
                    needs_completion = False
            
            if needs_completion:
                for mon in nhom.get("danh_sach_mon_hoc", []):
                    relevant_subjects.append({
                        "khoi": khoi_name,
                        "nhom": nhom_name,
                        "nhom_trang_thai": trang_thai,
                        "tin_chi_yeu_cau": tin_chi_yeu_cau,
                        "tin_chi_dat": tin_chi_dat,
                        "ma_mon": mon.get("ma_mon", ""),
                        "ten_mon": mon.get("ten_mon_hoc", ""),
                        "so_tc": mon.get("so_tin_chi", 0),
                        "trang_thai": mon.get("trang_thai", "")
                    })
    
    asking_not_learned = any(kw in q_lower for kw in ["chưa học", "chua hoc", "thiếu", "thieu", "còn thiếu", "con thieu", "cần học", "can hoc"])
    asking_current = any(kw in q_lower for kw in ["đang học", "dang hoc", "học hiện tại", "hoc hien tai"])
    asking_major = any(kw in q_lower for kw in ["chuyên ngành", "chuyen nganh"])
    asking_foundation = any(kw in q_lower for kw in ["cơ sở", "co so", "cơ bản", "co ban"])
    
    if asking_not_learned:
        filtered = [s for s in relevant_subjects if s["trang_thai"] == "Chưa học"]
    elif asking_current:
        filtered = [s for s in relevant_subjects if s["trang_thai"] == "Đang học"]
    elif asking_major:
        filtered = [s for s in relevant_subjects if "chuyên ngành" in s["khoi"].lower() and s["trang_thai"] == "Chưa học"]
    elif asking_foundation:
        filtered = [s for s in relevant_subjects if "cơ sở" in s["khoi"].lower() and s["trang_thai"] == "Chưa học"]
    else:
        filtered = [s for s in relevant_subjects if s["trang_thai"] == "Chưa học"]
    
    if len(filtered) == 0:
        if asking_not_learned:
            return "🎉 Bạn đã hoàn thành tất cả các môn học rồi!"
        elif asking_current:
            return "Hiện tại bạn không có môn nào đang học."
        else:
            return "Không tìm thấy môn học phù hợp."

    by_nhom = defaultdict(lambda: {"subjects": [], "info": {}})
    
    for item in filtered:
        nhom = item["nhom"]
        by_nhom[nhom]["subjects"].append(item)
        if not by_nhom[nhom]["info"]:
            by_nhom[nhom]["info"] = {
                "khoi": item["khoi"],
                "tin_chi_yeu_cau": item["tin_chi_yeu_cau"],
                "tin_chi_dat": item["tin_chi_dat"]
            }
    
    results = []
    status_text = "chưa học cần học" if asking_not_learned else "đang học"
    
    total_subjects = len(filtered)
    results.append(f"📚 Các môn {status_text} ({total_subjects} môn):\n")
    
    for nhom_name, data in by_nhom.items():
        subjects = data["subjects"]
        info = data["info"]
        
        header = f"\n📦 {nhom_name}"
        if info["tin_chi_yeu_cau"] is not None:
            required = info["tin_chi_yeu_cau"]
            achieved = info["tin_chi_dat"]
            remaining = max(0, required - achieved)
            header += f" ({achieved}/{required} TC, còn thiếu {remaining} TC)"
        else:
            header += " (Phải học đầy đủ)"
        
        results.append(header)
        results.append(f"({info['khoi']})")
        
        for item in subjects[:8]:
            results.append(f"  • {item['ten_mon']} ({item['so_tc']} TC)")
        
        if len(subjects) > 8:
            results.append(f"  ... và {len(subjects) - 8} môn nữa")
        
        results.append("")
    
    return "\n".join(results)

def _format_tuition_response(data: List[Dict], query_type: str, query: str) -> str:
    q_lower = query.lower()

    is_asking_total = any(kw in q_lower for kw in ["tổng", "tong", "bao nhiêu", "bao nhieu", "là bao nhiêu"])
    is_asking_remaining = any(kw in q_lower for kw in ["còn", "con", "chưa đóng", "chua dong", "nợ"])
    is_asking_status = any(kw in q_lower for kw in ["đã đóng", "da dong", "tình trạng", "tinh trang", "trạng thái", "trang thai"])
    is_asking_all_terms = any(kw in q_lower for kw in ["các kì", "cac ki", "tất cả kỳ", "tat ca ky", "toàn bộ kỳ", "toan bo ky"])
    year_pattern_match = re.search(r'\b(năm|nam)\s*(\d{4}|\d{2}-\d{2}|\d{2}\s*\d{2})\b', q_lower) or \
                         re.search(r'\b(\d{2}-\d{2})\b', q_lower)
    is_asking_by_year = bool(year_pattern_match)
    is_asking_grand_total = (is_asking_total and is_asking_all_terms) or \
                            any(kw in q_lower for kw in ["tổng cộng", "tong cong", "tổng hết", "tong het", "tất cả học phí", "tat ca hoc phi"])
    if not data:
        return "Hiện tại bạn chưa có dữ liệu học phí nào."
    unpaid_items = []
    total_unpaid = 0
    total_paid = 0
    grand_total_phai_thu = 0

    for item in data:
        if not isinstance(item, dict):
             logger.warning(f"Skipping invalid item in tuition data: {item}")
             continue

        loai = "Học phí" if item.get("loai_thanh_toan") == "hoc_phi" else "BHYT"
        tong_tien = item.get("tong_tien_phai_thu", 0)
        da_thu = item.get("tong_tien_da_thu", 0)
        con_lai = item.get("tong_tien_con_lai", 0)
        status = item.get("status", "")
        nkhk = item.get("nkhk", "")

        grand_total_phai_thu += tong_tien
        total_paid += da_thu
        total_unpaid += con_lai

        if con_lai > 0:
            unpaid_items.append({
                "loai": loai,
                "con_lai": con_lai,
                "tong_tien": tong_tien,
                "status": status,
                "nkhk": nkhk
            })

    if is_asking_grand_total:
         return (
             f"Tổng cộng học phí và các khoản thu của bạn qua các kỳ:\n"
             f"- **Tổng phải đóng:** {grand_total_phai_thu:,} VNĐ\n"
             f"- **Tổng đã đóng:** {total_paid:,} VNĐ\n"
             f"- **Tổng còn lại:** {total_unpaid:,} VNĐ"
         )

    elif is_asking_all_terms:
        by_nkhk = defaultdict(lambda: {"hoc_phi": 0, "bhyt": 0, "total": 0, "paid": 0, "year": ""})

        for item in data:
            if not isinstance(item, dict): continue
            nkhk = item.get("nkhk", "")
            loai = item.get("loai_thanh_toan", "")
            tong_tien = item.get("tong_tien_phai_thu", 0)
            da_thu = item.get("tong_tien_da_thu", 0)

            if not nkhk: continue

            by_nkhk[nkhk]["total"] += tong_tien
            by_nkhk[nkhk]["paid"] += da_thu
            if not by_nkhk[nkhk]["year"]:
                 try:
                     if len(str(nkhk)) >= 4:
                         by_nkhk[nkhk]["year"] = _parse_nkhk_to_year(int(nkhk))
                     else:
                         by_nkhk[nkhk]["year"] = ""
                 except (ValueError, TypeError):
                     by_nkhk[nkhk]["year"] = ""

            if loai == "hoc_phi":
                by_nkhk[nkhk]["hoc_phi"] += tong_tien
            elif loai == "bhyt":
                by_nkhk[nkhk]["bhyt"] += tong_tien

        results = []
        for nkhk in sorted(by_nkhk.keys(), reverse=True):
            info = by_nkhk[nkhk]
            year_str = f" (Năm học {info['year']})" if info['year'] else ""
            remaining = info['total'] - info['paid']
            status_str = f", còn lại: {remaining:,}" if remaining > 0 else ""
            results.append(f"- **Học kỳ {nkhk}{year_str}:** {info['total']:,} VNĐ (Đã đóng: {info['paid']:,}{status_str})")

        return "Chi tiết học phí các kỳ của bạn:\n" + "\n".join(results)
    elif is_asking_by_year:
        target_year = ""
        for kw in ["25-26", "24-25", "23-24", "22-23"]: # Giữ lại list này để ưu tiên format YY-YY
            if kw in q_lower:
                target_year = kw
                break
        if not target_year:
            if year_pattern_match:
                year_input_group = year_pattern_match.group(2) if len(year_pattern_match.groups()) > 1 else year_pattern_match.group(1) # Lấy group chứa năm
                year_input = year_input_group.replace(" ", "").replace("-","") # "25-26"->"2526", "25 26"->"2526", "2025"->"2025"

                if len(year_input) == 4 and year_input.isdigit():
                    try:
                        start_yr_str = year_input[2:]
                        start_yr = int(start_yr_str)
                        end_yr = start_yr + 1
                        target_year = f"{start_yr}-{end_yr}"
                    except ValueError: pass
                elif len(year_input) == 2 and year_input.isdigit(): # "năm 26"
                     try:
                         start_yr = int(year_input)
                         end_yr = start_yr + 1
                         target_year = f"{start_yr}-{end_yr}"
                     except ValueError: pass
                elif len(year_input) == 4 and not year_input.isdigit() and '-' in year_input_group: # "25-26" (từ group 1 của regex thứ 2)
                    target_year = year_input_group # Giữ nguyên format YY-YY

        if target_year:
            filtered_data = []
            for item in data:
                 if not isinstance(item, dict): continue
                 nkhk_str = str(item.get("nkhk", ""))
                 if nkhk_str:
                     try:
                         if len(nkhk_str) >= 4:
                            item_year = _parse_nkhk_to_year(int(nkhk_str))
                            if item_year == target_year:
                                filtered_data.append(item)
                     except (ValueError, TypeError): continue

            if filtered_data:
                year_total_phai_thu = sum(item.get("tong_tien_phai_thu", 0) for item in filtered_data)
                year_total_paid = sum(item.get("tong_tien_da_thu", 0) for item in filtered_data)
                year_total_remaining = sum(item.get("tong_tien_con_lai", 0) for item in filtered_data)

                items_by_nkhk = defaultdict(list)
                for item in filtered_data:
                    items_by_nkhk[item.get("nkhk", "")].append(item)

                details = []
                for nkhk in sorted(items_by_nkhk.keys()):
                    nkhk_total = sum(i.get("tong_tien_phai_thu", 0) for i in items_by_nkhk[nkhk])
                    nkhk_paid = sum(i.get("tong_tien_da_thu", 0) for i in items_by_nkhk[nkhk])
                    details.append(f"  - Học kỳ {nkhk}: {nkhk_total:,} VNĐ (Đã đóng: {nkhk_paid:,})")

                return (
                    f"Tổng hợp học phí **Năm học {target_year}**:\n" +
                    "\n".join(details) +
                    f"\n\n**Tổng cộng năm học:**\n" +
                    f"- Phải đóng: {year_total_phai_thu:,} VNĐ\n" +
                    f"- Đã đóng: {year_total_paid:,} VNĐ\n" +
                    f"- Còn lại: {year_total_remaining:,} VNĐ"
                 )
            else:
                return f"Không tìm thấy dữ liệu học phí cho năm học {target_year}."
        else:
            logger.warning("Asked about year but couldn't detect which one, showing overview.")
            if total_unpaid > 0:
                items = []
                for item in unpaid_items:
                     items.append(f"- {item['loai']} (HK {item.get('nkhk','?')}) : {item['con_lai']:,} VNĐ ({item['status']})")
                return f"Bạn còn **{total_unpaid:,} VNĐ** chưa đóng:\n" + "\n".join(items)
            else:
                return "Tất cả các khoản học phí và BHYT của bạn đã được đóng đầy đủ. ✅"

    elif is_asking_remaining:
        if len(unpaid_items) > 0:
            items_details = []
            unpaid_by_nkhk = defaultdict(list)
            for item in unpaid_items:
                 unpaid_by_nkhk[item.get("nkhk", "Chưa rõ HK")].append(item)

            for nkhk in sorted(unpaid_by_nkhk.keys()):
                 nkhk_remaining = sum(i["con_lai"] for i in unpaid_by_nkhk[nkhk])
                 items_details.append(f"- Học kỳ {nkhk}: {nkhk_remaining:,} VNĐ")

            if total_unpaid > 0:
                items_details.append(f"\n**Tổng cộng còn lại:** {total_unpaid:,} VNĐ")
                return f"Các khoản bạn còn phải đóng:\n" + "\n".join(items_details)
            else:
                 return "Bạn đã đóng hết học phí và các khoản thu rồi! 🎉"
        else:
            return "Bạn đã đóng hết tất cả các khoản học phí và BHYT rồi! 🎉"

    elif is_asking_status:
        # (Giữ nguyên logic is_asking_status)
        if total_unpaid > 0:
            return f"Bạn còn {len(unpaid_items)} khoản chưa đóng với tổng số tiền {total_unpaid:,} VNĐ."
        else:
            return "Tất cả các khoản học phí và BHYT của bạn đã được đóng đầy đủ. ✅"

    elif is_asking_total:
         return (
             f"Tổng hợp học phí của bạn:\n"
             f"- Tổng phải đóng: {grand_total_phai_thu:,} VNĐ\n"
             f"- Tổng đã đóng: {total_paid:,} VNĐ\n"
             f"- Tổng còn lại: {total_unpaid:,} VNĐ"
         )

    else:
        if total_unpaid > 0:
            items = []
            for item in unpaid_items:
                 items.append(f"- {item['loai']} (HK {item.get('nkhk','?')}) : {item['con_lai']:,} VNĐ ({item['status']})")
            return f"Bạn còn **{total_unpaid:,} VNĐ** chưa đóng:\n" + "\n".join(items)
        else:
            return "Tất cả các khoản học phí và BHYT của bạn đã được đóng đầy đủ. ✅"

def _needs_student_credits(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    credits_keywords = [
        "tín chỉ", "tin chi", "tong tin chi", "total credit", "required credit", 
        "hoan thanh", "progress", "điểm tín chỉ", "diem tin chi",
        "tích lũy", "tich luy", "đã đạt", "da dat", "bao nhiêu tín chỉ", "bao nhieu tin chi",
        "số tín chỉ", "so tin chi", "tín chỉ của tôi", "tin chi cua toi",
        "cần để tốt nghiệp", "can de tot nghiep", "tốt nghiệp cần", "tot nghiep can"
    ]
    return any(keyword in q for keyword in credits_keywords)

def _needs_student_semester_gpa(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    if any(k in q for k in ["danh sach", "danh sách", "bang diem", "bảng điểm"]):
        return False
    
    semester_keywords = [
        "điểm trung bình học kỳ", "diem trung binh hoc ky",
        "gpa học kỳ", "gpa hoc ky", "avg semester",
        "điểm tổng kết học kỳ", "diem tong ket hoc ky",
        "trung bình học kỳ", "trung binh hoc ky"
    ]
    return any(keyword in q for keyword in semester_keywords)

def _needs_student_rl_grades(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    rl_keywords = ["điểm rèn luyện", "diem ren luyen", "rèn luyện", "ren luyen", "xep loai ren luyen"]
    return any(keyword in q for keyword in rl_keywords)

def _needs_student_exam_schedule(query: str) -> bool:
    """Check if query is asking for exam schedule."""
    if not query:
        return False
    q = query.lower()
    exam_keywords = [
        "lịch thi", "lich thi", "thi cử", "thi cuoi ky", "thi cuối kỳ", 
        "lịch thi của tôi", "xem lịch thi"
    ]
    if "lịch học" in q or "thời khóa biểu" in q or "tkb" in q:
        return False
    return any(keyword in q for keyword in exam_keywords)

def _needs_student_union_info(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    union_keywords = [
        "đoàn viên", "doan vien", "thông tin đoàn", "thong tin doan",
        "sinh hoạt đoàn", "chức vụ trong đoàn", "thẻ đoàn", "so the doan"
    ]
    return any(keyword in q for keyword in union_keywords)

def _needs_score_list(query: str) -> bool:
    """Check if query is asking for score list"""
    if not query:
        return False
    # Chuẩn hóa query về không dấu, lowercase (ví dụ: "điểm" -> "iem")
    q = _normalize_text(query)
    
    # === SỬA LỖI: KEYWORDS PHẢI KHỚP VỚI KẾT QUẢ CỦA _normalize_text ===
    keywords = [
        "danh sach mon",    # "danh sách môn"
        "iem mon",          # "điểm môn"
        "mon hoc hoc ky",   # "môn học học kỳ"
        "list mon",         # "list môn"
        "bang iem mon",     # "bảng điểm môn"
        "bang iem",         # "bảng điểm"
        "danh sach iem",    # "danh sách điểm"
        "iem hoc ky",       # "điểm học kỳ"
        "cac mon hoc",      # "các môn học"
        "xem bang iem",     # "xem bảng điểm"
        "bang iem hoc ky",  # "bảng điểm học kỳ"
        "liet ke iem",      # "liệt kê điểm"
        "iem cac mon",      # "điểm các môn"
        "mon a hoc",        # "môn đã học"
        "iem hoc ky nay",   # "điểm học kỳ này"
        "iem ky roi",       # "điểm kỳ rồi"
        "hoc ky roi"        # "học kỳ rồi"
    ]
    # === KẾT THÚC SỬA LỖI ===
    
    match_found = any(k in q for k in keywords)
    
    if match_found:
        logger.info(f"✅ _needs_score_list: Match found for query '{q}'")
            
    return match_found

def _needs_score_detail(query: str) -> bool:
    if not query:
        return False
    q = _normalize_text(query)
    patterns = [
        r"\bma[_\s-]?nhom\s*[:=]?\s*([A-Za-z0-9\-_.]+)",
        r"\bnhom\s*([A-Za-z0-9\-_.]+)",
        r"\bchi tiet mon\b",
        r"\bchi tiet diem\b"
    ]
    return any(re.search(p, q) for p in patterns)

def _needs_student_curriculum(query: str) -> bool:
    if not query:
        return False
    
    q = query.lower()
    
    # --- BƯỚC 1: KIỂM TRA LOẠI TRỪ (FIREWALL) ---
    # (Hàm này đã có trong code của bạn và đang chạy tốt)
    if _needs_student_schedule(q):
        return False
    if _needs_student_exam_schedule(q):
        return False
    if _needs_student_tuition(q):
        return False
    # --- KẾT THÚC FIREWALL ---
    
    # BƯỚC 2: KIỂM TRA TỪ KHÓA (BỔ SUNG ĐẦY ĐỦ)
    curriculum_keywords = [
        # (Từ khóa cũ)
        "chương trình đào tạo", "chuong trinh dao tao", "ctdt",
        "tiến độ học tập", "tien do hoc tap", "lộ trình học", "lo trinh hoc",
        "khung đào tạo", "khung dao tao", "còn thiếu môn nào", "con thieu mon nao",
        "cần học môn gì", "can hoc mon gi", "học thêm môn gì", "hoc them mon gi",
        "môn chưa học", "mon chua hoc", "môn còn thiếu", "mon con thieu",
        "môn đang học", "mon dang hoc", "khối kiến thức", "khoi kien thuc",
        "chuyên ngành", "chuyen nganh",
        "thiếu môn", "thieu mon", "còn thiếu", "con thieu",
        
        # --- BỔ SUNG CÁC TỪ KHÓA BỊ LỌT ---
        "cơ sở ngành", "co so nganh",  # Test "Liệt kê môn cơ sở ngành"
        "nên học môn nào", "nen hoc mon nao",
        "nên đăng ký môn nào", "nen dang ky mon nao",
        "học môn gì", "hoc mon gi", 
        "khối nào", "khoi nao", 
        "yếu nhất", "yeu nhat", 
        "thấp nhất", "thap nhat",
        "tiến độ", "tien do",
        "đề xuất", "de xuat", 
        "nên học", "nen hoc",
        "liệt kê các môn", "liet ke cac mon", 
        "liệt kê môn", "liet ke mon",
        
        # Bắt các câu hỏi trực tiếp về nhóm (Test "Nhóm II.2")
        "nhóm i.1", "nhom i.1",
        "nhóm i.2", "nhom i.2",
        "nhóm i.3", "nhom i.3",
        "nhóm ii.1", "nhom ii.1",
        "nhóm ii.2", "nhom ii.2",
        "nhóm ii.3", "nhom ii.3",
        "nhóm ii.4", "nhom ii.4",
        "nhóm ii.5", "nhom ii.5",
        "nhóm ii.6", "nhom ii.6",
        "nhóm iii.1", "nhom iii.1",
        "nhóm iii.2", "nhom iii.2",
        "nhóm iii.3", "nhom iii.3",
        "ii.2", "i.2", "i.1",  # Bắt các câu hỏi rất ngắn
        "công dân số", "cong dan so"  # Bắt tên môn học
    ]
    
    return any(keyword in q for keyword in curriculum_keywords)

def _extract_ma_nhom(query: str) -> Optional[str]:
    """Extract ma_nhom from query"""
    if not query:
        return None
    q = _normalize_text(query)
    for p in [r"\bma[_\s-]?nhom\s*[:=]?\s*([A-Za-z0-9\-_.]+)", r"\bnhom\s*([A-Za-z0-9\-_.]+)"]:
        m = re.search(p, q)
        if m:
            return m.group(1)
    return None

def _extract_date_range(query: str) -> Tuple[Optional[str], Optional[str]]:
    # TODO: Implement more sophisticated date extraction
    # For now, return None to use default current week
    return None, None

def handle_external_api_student(jwt_token: str, query: str) -> Dict[str, Any]:
    try:
        # 1) Get student profile
        profile = external_api_service.get_student_profile(jwt_token)
        if not profile or not profile.mssv:
            return {
                "status": "error",
                "message": "Không lấy được hồ sơ sinh viên từ token. Vui lòng đăng nhập lại.",
                "error_type": "profile_failed"
            }
        logger.info(f"🎓 Profile loaded: {profile.ho_ten} ({profile.mssv}), lớp {profile.lop}, khoa {profile.khoa}")

        gemini_temp = GeminiResponseGenerator()
        session_id_temp = f"student_{profile.mssv}_news_overview"
        conversation_context = gemini_temp.memory.get_conversation_context(session_id_temp)
        recent_history = conversation_context.get('history', [])
        
        query_lower = query.lower()
        generic_followup_keywords = [
            "chi tiết hơn", "chi tiet hon", "nói chi tiết hơn", "noi chi tiet hon",
            "chi tiết", "chi tiet", "rõ hơn", "ro hon", "cụ thể hơn", "cu the hon",
            "đầy đủ hơn", "day du hon", "giải thích rõ", "giai thich ro"
        ]
        is_generic_followup = any(kw in query_lower for kw in generic_followup_keywords)
        if is_generic_followup and recent_history:
            logger.info("🔄 Detected generic follow-up - checking for news context...")
            has_news_context = any(
                'news_context' in interaction.get('intent_info', {}) or
                'news_overview' in interaction.get('method', '') or
                any(word in str(interaction.get('bot_response', '')).lower() 
                    for word in ['thông báo', 'thong bao', 'tin tức', 'tin tuc', 'bạn muốn xem chi tiết'])
                for interaction in recent_history[-3:]  # Check last 3 interactions
            )
            
            if has_news_context:
                logger.info("📰 News context found - routing to news handler with specific topic")
                last_interaction = recent_history[-1] if recent_history else None
                previous_query = last_interaction.get('user_query', '') if last_interaction else ''
                if previous_query and 'tin tức về' in previous_query.lower():
                    topic = previous_query.lower().replace('tin tức về', '').replace('tin tuc ve', '').strip()
                    query = f"tin tức về {topic}"  # Update query to include topic
                    logger.info(f"📰 Extracted topic: '{topic}'")
        if _needs_student_news_detail(query):
            logger.info("📰 News DETAIL intent detected")
            news_res = external_api_service.get_student_news(jwt_token, page=1, page_size=10)
            if not (news_res and news_res.get("ok")):
                return {"status": "error", "mode": "text", "message": "Không lấy được tin tức để xem chi tiết."}

            items = news_res.get("data", [])
            if not items:
                return {"status": "success", "mode": "text", "response": "Không có tin nào để xem chi tiết."}

            idx = _extract_news_index(query)
            picked = items[idx-1] if (idx and 1 <= idx <= len(items)) else None
            if not picked:
                picked = _pick_news_by_title(items, query) or items[0]

            detail_text = _format_news_detail(picked)

            return {
                "status": "success",
                "mode": "text",
                "method": "student_news_detail",
                "response": detail_text,
                "news_detail": {
                    "id": picked.get("id"),
                    "title": picked.get("title"),
                    "category": picked.get("category"),
                    "date": picked.get("date"),
                    "time": picked.get("time"),
                    "author": picked.get("author"),
                    "html": picked.get("html"),    # FE mở WebView nếu cần
                    "plain": picked.get("plain")
                }
            }
        elif _needs_student_profile(query):
            try:
                logger.info("🎯 Profile intent detected. Using Gemini for a natural response.")
                
                # Tạo context để gửi cho Gemini
                gemini_context = {
                    "instruction": "process_external_api_data",
                    "api_data": {
                        "student_info": { 
                            "student_name": profile.ho_ten,
                            "mssv": profile.mssv,
                            "class": profile.lop,
                            "faculty": profile.khoa
                        }
                    },
                    "profile": { # Thêm profile để cá nhân hóa xưng hô
                        "full_name": profile.ho_ten,
                        "mssv": profile.mssv,
                        "class_name": profile.lop,
                        "faculty": profile.khoa
                    },
                    "original_query": query
                }

                gemini = GeminiResponseGenerator()
                session_id = f"student_{profile.mssv}_profile"
                
                gemini.set_user_context(session_id, {
                    "full_name": profile.ho_ten,
                    "mssv": profile.mssv,
                    "class_name": profile.lop,
                    "faculty": profile.khoa
                })

                gemini_response = gemini.generate_response(
                    query=query,
                    context=gemini_context,
                    session_id=session_id
                )

                response_text = gemini_response.get("response")
                if not response_text:
                     raise ValueError("Gemini returned an empty response.")

                return {
                    "status": "success", "mode": "text", "response": response_text,
                    "method": "gemini_student_profile", "confidence": gemini_response.get('confidence', 0.9),
                    "mssv": profile.mssv, "student_name": profile.ho_ten,
                    "class": profile.lop, "faculty": profile.khoa,
                }

            except Exception as e:
                logger.error(f"❌ Gemini generation for profile failed: {e}. Falling back to template.")
                # Fallback: Nếu Gemini lỗi, trả về câu trả lời cũ để đảm bảo hệ thống không chết
                response_text = f"Thông tin của bạn: Tên {profile.ho_ten}, MSSV {profile.mssv}, Lớp {profile.lop}, Khoa {profile.khoa}."
                return {
                    "status": "success", "mode": "text", "response": response_text,
                    "method": "student_profile_fallback", "confidence": 1.0,
                    "mssv": profile.mssv, "student_name": profile.ho_ten,
                    "class": profile.lop, "faculty": profile.khoa,
                }
        elif _needs_student_grades(query):
            logger.info("🎯 Grades intent detected")
            nkhk = _extract_nkhk_from_query(query)
            if not nkhk:
                query_lower = query.lower()
                recent_semester_keywords = [
                    "vừa rồi", "vua roi", "gần đây", "gan day", 
                    "gần nhất", "gan nhat", "hiện tại", "hien tai",
                    "học kỳ vừa", "hoc ky vua", "học kì vừa", "hoc ki vua",
                    "kỳ vừa rồi", "ky vua roi", "kì vừa", "ki vua"
                ]
                is_asking_recent_semester = any(kw in query_lower for kw in recent_semester_keywords)
                
                if is_asking_recent_semester:
                    logger.info("🔄 Detected request for recent semester - fetching latest NKHK")
                    nkhk = external_api_service.get_latest_nkhk(jwt_token)
                    if nkhk:
                        logger.info(f"📍 Using latest NKHK: {nkhk}")
                    else:
                        logger.warning("⚠️ Could not get latest NKHK, falling back to overall GPA")
            
            if nkhk:
                logger.info(f"📍 Detected semester NKHK {nkhk} in query - routing to semester GPA")
                ov = external_api_service.get_semester_overview(jwt_token, nkhk)
                if not (ov and ov.get("ok")):
                    return {"status": "error", "mode": "text", "message": f"Không lấy được tổng quan học kỳ {nkhk}."}
                d = ov["data"] or {}
                def fmt(x, dec=2):
                    try: 
                        return f"{float(x):.{dec}f}"
                    except Exception:
                        return "Chưa có"
                text = (
                    f"Điểm tổng kết học kỳ {nkhk} của bạn: "
                    f"Điểm trung bình hệ 10: {fmt(d.get('diem_trung_binh_he_10'))}, "
                    f"Điểm trung bình hệ 4: {fmt(d.get('diem_trung_binh_he_4'))}, "
                    f"Tổng tín chỉ: {d.get('tong_tin_chi') if d.get('tong_tin_chi') is not None else 'Chưa có'}, "
                    f"Xếp loại: {d.get('xep_loai') or 'Chưa có'}."
                )
                try:
                    gemini = GeminiResponseGenerator()
                    session_id = f"student_{profile.mssv}_semester_gpa"
                    
                    gemini.set_user_context(session_id, {
                        "full_name": profile.ho_ten,
                        "mssv": profile.mssv,
                        "class_name": profile.lop,
                        "faculty": profile.khoa
                    })
                    
                    gemini_context = {
                        "instruction": "process_external_api_data",
                        "api_data": d,
                        "data_type": "semester_gpa",
                        "profile": {
                            "name": profile.ho_ten,
                            "mssv": profile.mssv,
                            "class": profile.lop,
                            "faculty": profile.khoa
                        },
                        "nkhk": nkhk,
                        "original_query": query
                    }
                    
                    gemini_response = gemini.generate_response(
                        query=query,
                        context=gemini_context,
                        session_id=session_id
                    )
                    
                    response_text = (gemini_response or {}).get("response", "").strip()
                    
                    if not response_text or "mình chỉ hỗ trợ" in response_text.lower():
                        response_text = text
                    
                    return {
                        "status": "success",
                        "mode": "text",
                        "response": response_text,
                        "method": "student_semester_gpa_tutor",
                        "confidence": gemini_response.get("confidence", 0.9) if gemini_response else 1.0,
                        "mssv": profile.mssv,
                        "student_name": profile.ho_ten,
                        "class": profile.lop,
                        "faculty": profile.khoa,
                        "nkhk": nkhk,
                        "overview": d
                    }
                except Exception as e:
                    logger.error(f"❌ Error during Gemini semester GPA processing: {e}")
                    return {
                        "status": "success",
                        "mode": "text",
                        "method": "semester_overview",
                        "response": text,
                        "nkhk": nkhk,
                        "overview": d
                    }
            
            logger.info("🎯 Calling API and then Gemini for overall GPA")
            res = external_api_service.get_student_grades(jwt_token)
            
            if not (res and res.get("ok")):
                return {"status": "error", "message": "Không lấy được điểm số từ API."}

            credits_res = external_api_service.get_student_credits(jwt_token, query)
            rl_res = external_api_service.get_student_rl_grades(jwt_token, query)

            student_full_context = {
                "profile": {
                    "name": profile.ho_ten, "mssv": profile.mssv,
                    "class": profile.lop, "faculty": profile.khoa
                },
                "grades": res.get("data", {}),
                "credits": credits_res.get("data", {}) if credits_res.get("ok") else {},
                "rl_grades": rl_res.get("data", {}) if rl_res.get("ok") else {}
            }

            try:
                gemini = GeminiResponseGenerator()
                session_id = f"student_{profile.mssv}_grades_tutor"
                
                gemini.set_user_context(session_id, {
                    "full_name": profile.ho_ten,
                    "mssv": profile.mssv,
                    "class_name": profile.lop,
                    "faculty": profile.khoa
                })

                gemini_context = {
                    "instruction": "tutor_mode",
                    "api_data": res.get("data", {}),
                    "data_type": "grades",
                    "student_data": student_full_context,
                    "profile": student_full_context["profile"]
                }

                gemini_response = gemini.generate_response(
                    query=query,
                    context=gemini_context,
                    session_id=session_id
                )

                response_text = (gemini_response or {}).get("response", "").strip()
                
                grades = res.get("data", {}) if res else {}
                gpa4 = grades.get("gpa4") or grades.get("avg4") or grades.get("avg_he_4") or grades.get("avg_diem_hp_4") or grades.get("diem_trung_binh_he_4") or grades.get("gpa_he_4")
                gpa10 = grades.get("gpa10") or grades.get("avg10") or grades.get("avg_he_10") or grades.get("avg_diem_hp") or grades.get("diem_trung_binh_he_10") or grades.get("gpa_he_10")
                
                if not response_text or "mình chỉ hỗ trợ" in response_text.lower():
                    response_text = f"GPA hiện tại của bạn: {gpa4} (hệ 4) • {gpa10} (hệ 10)."

                return {
                    "status": "success",
                    "mode": "text",
                    "response": response_text,
                    "method": "student_grades_tutor",
                    "confidence": gemini_response.get("confidence", 0.9) if gemini_response else 1.0,
                    "mssv": profile.mssv, 
                    "student_name": profile.ho_ten,
                    "class": profile.lop, 
                    "faculty": profile.khoa,
                }
            except Exception as e:
                logger.error(f"❌ Error during Gemini grades processing: {e}")
                
                data = res.get("data", {}) if isinstance(res, dict) else {}
                gpa_4 = (
                    data.get("avg_diem_hp_4")
                    or data.get("diem_trung_binh_he_4")
                    or data.get("gpa_he_4")
                    or "N/A"
                )
                gpa_10 = (
                    data.get("avg_diem_hp")
                    or data.get("diem_trung_binh_he_10")
                    or data.get("gpa_he_10")
                    or "N/A"
                )
                
                return {
                    "status": "success",
                    "mode": "text",
                    "method": "student_grades",
                    "response": f"Điểm trung bình hiện tại: {gpa_4} (hệ 4) • {gpa_10} (hệ 10).",
                    "grades": data
                }
        elif _needs_student_tuition(query):
            logger.info("💰 Tuition intent detected, calling API and then Gemini")
            conversation_context = {}
            res = external_api_service.get_student_tuition(jwt_token)
            
            if not (res and res.get("ok")):
                return {"status": "error", "message": "Không lấy được thông tin học phí từ API."}

            try:
                gemini = GeminiResponseGenerator()
                session_id = f"student_{profile.mssv}_tuition"
                
                gemini.set_user_context(session_id, {
                    "full_name": profile.ho_ten,
                    "mssv": profile.mssv,
                    "class_name": profile.lop,
                    "faculty": profile.khoa
                })

                gemini_context = {
                    "instruction": "process_external_api_data",
                    "api_data": res.get("data", []),
                    "data_type": "tuition",
                    "profile": {
                        "name": profile.ho_ten,
                        "mssv": profile.mssv,
                        "class": profile.lop,
                        "faculty": profile.khoa
                    }
                }

                # Gọi Gemini để tạo câu trả lời tự nhiên
                gemini_response = gemini.generate_response(
                    query=query,
                    context=gemini_context,
                    session_id=session_id
                )

                response_text = gemini_response.get("response")
                if not response_text:
                    raise ValueError("Gemini returned an empty response.")

                return {
                    "status": "success",
                    "mode": "text",
                    "response": response_text,
                    "method": "gemini_tuition_with_api_data",
                    "confidence": gemini_response.get('confidence', 0.9),
                    "mssv": profile.mssv,
                    "student_name": profile.ho_ten,
                    "class": profile.lop,
                    "faculty": profile.khoa,
                }
            except Exception as e:
                logger.error(f"❌ Error during Gemini tuition processing: {e}")
                q_lower = query.lower()
                query_type = "remaining" if any(kw in q_lower for kw in ["còn", "con", "chưa đóng", "chua dong"]) else "overview"
                data = res.get("data", [])
                if isinstance(data, list) and len(data) > 0:
                    fallback_response = _format_tuition_response(data, query_type, query)
                elif isinstance(data, list) and len(data) == 0:
                    fallback_response = "Bạn hiện chưa có khoản học phí nào."
                else:
                    fallback_response = "Không thể tải thông tin học phí lúc này."
                
                return {
                    "status": "success",
                    "mode": "text",
                    "response": fallback_response,
                    "method": "tuition_api_fallback",
                    "confidence": 0.8,
                    "mssv": profile.mssv,
                    "student_name": profile.ho_ten,
                    "class": profile.lop,
                    "faculty": profile.khoa,
                }
        elif _needs_student_credits(query):
            logger.info("🎯 Credits intent detected, calling API and then Gemini")
            res = external_api_service.get_student_credits(jwt_token, query)
            
            if not (res and res.get("ok")):
                return {"status": "error", "message": "Không lấy được thông tin tín chỉ từ API."}

            data = res.get("data", {})
            logger.info(f"📊 Credits API response: {data}")
            try:
                completed_credits = int(data.get("total_credit", 0))
                required_credits = int(data.get("required_credit", 0))
                
                if required_credits == 0:
                    response_text = "Không thể tải thông tin tín chỉ lúc này."
                else:
                    remaining_credits = max(0, required_credits - completed_credits)
                    progress = int((completed_credits / required_credits) * 100) if required_credits > 0 else 0
                    response_text = f"📊 Bạn đã tích lũy được {completed_credits}/{required_credits} tín chỉ\n"
                    if remaining_credits > 0:
                        response_text += f"📝 Còn lại: {remaining_credits} tín chỉ để tốt nghiệp\n"
                    response_text += f"📈 Tiến độ: {progress}%"
                
                return {
                    "status": "success",
                    "mode": "text",
                    "response": response_text,
                    "method": "credits_direct",
                    "confidence": 0.95,
                    "student_data": {
                        "mssv": profile.mssv,
                        "student_name": profile.ho_ten,
                        "class": profile.lop,
                        "faculty": profile.khoa,
                        "credits_info": {
                            "total_credit": completed_credits,
                            "required_credit": required_credits,
                            "remaining_credits": remaining_credits,
                            "progress": progress
                        }
                    },
                }
            except Exception as e:
                logger.error(f"❌ Error processing credits data: {e}")
                return {"status": "error", "message": f"Không thể xử lý dữ liệu tín chỉ: {str(e)}"}
        
        elif _needs_student_curriculum(query):
            logger.info("🎓 Curriculum/Progress intent detected, calling APIs")
            curriculum_res = external_api_service.get_student_curriculum(jwt_token)
            credit_res = external_api_service.get_student_credits(jwt_token, query)
            
            if not (curriculum_res and curriculum_res.get("ok")):
                return {"status": "error", "message": "Không lấy được dữ liệu chương trình đào tạo từ API."}
            
            curriculum_data = curriculum_res.get("data", [])
            logger.info(f"📚 Curriculum data received: {len(curriculum_data)} khối kiến thức")
            credit_data = credit_res.get("data", {}) if (credit_res and credit_res.get("ok")) else {}
            total_credits_achieved = int(credit_data.get("total_credit", 0))
            total_credits_required = int(credit_data.get("required_credit", 0))

            # --- BẮT ĐẦU THAY THẾ TỪ ĐÂY ---

            try:
                # --- ƯU TIÊN 1: GỌI GEMINI (LOGIC AI THÔNG MINH) ---
                # Logic này sẽ dùng _build_api_data_prompt (gemini_service.py)
                # để đọc JSON động và trả lời đúng câu hỏi
                
                logger.info(f"🎓 Calling Gemini (AI Logic) as PRIORITY for curriculum...")
                gemini = GeminiResponseGenerator()
                session_id = f"student_{profile.mssv}_curriculum"
                
                gemini.set_user_context(session_id, {
                    "full_name": profile.ho_ten,
                    "mssv": profile.mssv,
                    "class_name": profile.lop,
                    "faculty": profile.khoa
                })

                # Đóng gói TOÀN BỘ data động từ API cho Gemini
                gemini_context = {
                    "instruction": "enhance_answer_boosted",
                    "api_data": {
                        "curriculum_tree": curriculum_data, # Gửi CÂY JSON
                        "credit_summary": credit_data # Gửi TÓM TẮT TÍN CHỈ
                    },
                    "data_type": "curriculum", # Key quan trọng nhất
                    "profile": { # Gửi profile để Gemini biết tên
                        "name": profile.ho_ten, "mssv": profile.mssv,
                        "class": profile.lop, "faculty": profile.khoa
                    }
                }

                # Gemini sẽ tự động gọi _build_api_data_prompt
                gemini_response = gemini.generate_response(
                    query=query,
                    context=gemini_context,
                    session_id=session_id
                ) #

                response_text = gemini_response.get("response")
                if not response_text:
                    raise ValueError("Gemini returned an empty response.") # Kích hoạt fallback

                return {
                    "status": "success",
                    "mode": "text",
                    "response": response_text,
                    "method": "gemini_curriculum_priority", # Đổi tên method
                    "confidence": gemini_response.get('confidence', 0.9),
                    "student_data": {
                        "mssv": profile.mssv,
                        "student_name": profile.ho_ten,
                    },
                }
                
            except Exception as gemini_error:
                # --- ƯU TIÊN 2: FALLBACK (LOGIC XÉT CỨNG) ---
                # Chỉ chạy nếu Gemini API lỗi (429, 500, timeout...)
                logger.error(f"❌ Gemini curriculum processing failed: {gemini_error}. Falling back to hard-coded logic.")
                try:
                    # Gọi hàm "xét cứng" (logic cũ) làm dự phòng
                    response_text = _parse_curriculum_data(curriculum_data, query, total_credits_achieved, total_credits_required) #
                    return {
                        "status": "success",
                        "mode": "text",
                        "response": response_text,
                        "method": "curriculum_direct_fallback", # Đổi tên method
                        "confidence": 0.85, 
                        "student_data": {
                            "mssv": profile.mssv,
                            "student_name": profile.ho_ten,
                        },
                    }
                except Exception as fallback_error:
                     logger.error(f"❌ Hard-coded fallback logic ALSO failed: {fallback_error}")
                     return {"status": "error", "message": f"Không thể xử lý dữ liệu chương trình đào tạo: {str(fallback_error)}"}

            # --- KẾT THÚC THAY THẾ ---
        
        elif _needs_student_semester_gpa(query) or "avg semester" in _normalize_text(query):
            nkhk = _extract_nkhk_from_query(query)
            if not nkhk:
                nkhk = external_api_service.get_latest_nkhk(jwt_token)
            
            if not nkhk:
                return {"status": "error", "mode": "text", "message": "Không lấy được mã học kỳ. Vui lòng chỉ định học kỳ cụ thể, ví dụ: 'điểm trung bình học kỳ 24253'."}
            
            ov = external_api_service.get_semester_overview(jwt_token, nkhk)
            if not (ov and ov.get("ok")):
                return {"status": "error", "mode": "text", "message": f"Không lấy được tổng quan học kỳ {nkhk}."}
            d = ov["data"] or {}
            def fmt(x, dec=2):
                try: 
                    return f"{float(x):.{dec}f}"
                except Exception:
                    return "Chưa có"
            text = (
                f"Tổng quan học kỳ {nkhk}: "
                f"GPA hệ 10: {fmt(d.get('diem_trung_binh_he_10'))}, "
                f"hệ 4: {fmt(d.get('diem_trung_binh_he_4'))}, "
                f"tổng tín chỉ: {d.get('tong_tin_chi') if d.get('tong_tin_chi') is not None else 'Chưa có'}, "
                f"xếp loại: {d.get('xep_loai') or 'Chưa có'}."
            )
            return {"status": "success", "mode": "text", "method": "semester_overview", "response": text, "nkhk": nkhk, "overview": d}

        elif _needs_score_list(query):
            q_norm = _normalize_text(query)
            
            needs_latest = any(k in q_norm for k in ["hoc ky nay", "ky nay"])
            needs_previous = any(k in q_norm for k in ["hoc ky roi", "ky roi", "mon a hoc ky roi", "iem ky roi"]) # Thêm check "kỳ rồi"

            nkhk = None
            if needs_latest:
                nkhk = external_api_service.get_latest_nkhk(jwt_token)
                logger.info(f"📅 Query mentions 'this semester', using latest NKHK: {nkhk}")
            
            elif needs_previous: # <--- KHỐI LOGIC MỚI
                logger.info(f"📅 Query mentions 'last semester', attempting to find previous NKHK...")
                nkhk = external_api_service.get_previous_nkhk(jwt_token) 
                if nkhk:
                    logger.info(f"📅 Found previous NKHK: {nkhk}")
                else:
                    logger.warning(f"⚠️ Could not determine previous NKHK, falling back to latest.")
                    nkhk = external_api_service.get_latest_nkhk(jwt_token)
            
            else:
                nkhk = _extract_nkhk_from_query(query) or external_api_service.get_latest_nkhk(jwt_token)
            if not nkhk:
                return {"status": "error", "mode": "text", "message": "Không lấy được mã học kỳ. Vui lòng chỉ định học kỳ cụ thể, ví dụ: 'danh sách điểm học kỳ 24253'."}
            
            ls = external_api_service.get_score_list(jwt_token, nkhk)
            
            if not (ls and ls.get("ok")):
                return {"status": "error", "mode": "text", "message": f"Không lấy được danh sách môn học kỳ {nkhk}."}
            
            items = ls.get("data", [])
            
            if not items:
                return {"status": "success", "mode": "text", "method": "score_list", "response": f"Học kỳ {nkhk} chưa có dữ liệu điểm."}
            
            lines = []
            for i, it in enumerate(items[:20], 1):
                ten = it.get("ten_mon_hoc") or it.get("ten_mon") or "(Không tên)"
                nhom = it.get("ma_nhom_hoc") or it.get("ma_nhom") or "?"
                dxh = it.get("diem_xep_hang") if it.get("diem_xep_hang") is not None else "Chưa có"
                lines.append(f"{i:02d}. {ten} — nhóm {nhom} — xếp hạng: {dxh}")
            
            text = f"Danh sách môn học kỳ {nkhk}:\n" + "\n".join(lines)
            
            return {"status": "success", "mode": "text", "method": "score_list", "response": text, "nkhk": nkhk, "list": items}

        elif any(k in _normalize_text(query) for k in ["bao nhieu mon", "may mon", "co may mon"]):
            nkhk = _extract_nkhk_from_query(query) or external_api_service.get_latest_nkhk(jwt_token)
            if not nkhk:
                return {"status": "error", "mode": "text", "message": "Thiếu mã học kỳ (nkhk). Ví dụ: 'có bao nhiêu môn học kỳ 24253'."}
            ls = external_api_service.get_score_list(jwt_token, nkhk)
            if not (ls and ls.get("ok")):
                return {"status": "error", "mode": "text", "message": f"Không lấy được danh sách môn học kỳ {nkhk}."}
            items = ls.get("data") or []
            return {
                "status": "success",
                "mode": "text",
                "method": "score_count",
                "response": f"Học kỳ {nkhk} bạn có {len(items)} môn.",
                "nkhk": nkhk,
                "count": len(items)
            }

        elif _needs_score_detail(query):
            nkhk = _extract_nkhk_from_query(query) or external_api_service.get_latest_nkhk(jwt_token)
            if not nkhk:
                return {"status": "error", "mode": "text", "message": "Thiếu mã học kỳ (nkhk). Ví dụ: 'chi tiết môn học kỳ 24253'."}
            ls = external_api_service.get_score_list(jwt_token, nkhk)
            if not (ls and ls.get("ok")):
                return {"status": "error", "mode": "text", "message": f"Không lấy được danh sách môn học kỳ {nkhk}."}
            items = ls.get("data") or []
            ma_nhom = _extract_ma_nhom(query)
            picked = None
            if ma_nhom:
                picked = next((x for x in items if _normalize_text(x.get("ma_nhom_hoc","")) == _normalize_text(ma_nhom)), None)
            if not picked:
                m = re.search(r"(?:mon|môn)\s*(?:so|số)?\s*(\d{1,2})", _normalize_text(query))
                if m:
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(items):
                        picked = items[idx]

            if not picked:
                q_words = set(w for w in re.split(r"\W+", _normalize_text(query)) if len(w) > 2)
                def score_item(it):
                    name = _normalize_text(it.get("ten_mon_hoc",""))
                    words = set(re.split(r"\W+", name))
                    return len(q_words & words)
                items_scored = sorted(items, key=score_item, reverse=True)
                if items_scored and score_item(items_scored[0]) > 0:
                    picked = items_scored[0]

            if not picked:
                return {"status":"success","mode":"text","method":"score_detail","response":"Không tìm thấy môn trùng khớp để xem chi tiết."}

            ma_nhom_pick = picked.get("ma_nhom_hoc")
            detail = external_api_service.get_score_detail(jwt_token, ma_nhom_pick)
            if not (detail and detail.get("ok")):
                return {"status":"error","mode":"text","message":f"Không lấy được chi tiết môn {picked.get('ten_mon_hoc','')} ({ma_nhom_pick})."}

            d = detail.get("data") or {}
            txt = (
                f"Chi tiết môn {d.get('ten_mon') or picked.get('ten_mon_hoc','')}: "
                f"giữa kỳ {d.get('k1','Chưa có')}, cuối kỳ {d.get('t1','Chưa có')}, thư viện {d.get('tv','Chưa có')}. "
                f"Điểm HP hệ 10: {d.get('diem_hp','Chưa có')}, hệ 4: {d.get('diem_hp_4','Chưa có')}, "
                f"xếp hạng: {d.get('diem_xep_hang','Chưa có')}, trạng thái: {'Đạt' if d.get('dat_hp')==1 else 'Không đạt' if d.get('dat_hp')==0 else 'Chưa rõ'}."
            )
            return {"status":"success","mode":"text","method":"score_detail","response":txt,"nkhk":nkhk,"detail":d}
        
        elif _needs_student_rl_grades(query):
            logger.info("🎯 RL grades intent detected, calling API")
            
            nkhk = _extract_nkhk_from_query(query)
            res = external_api_service.get_student_rl_grades(jwt_token, query, nkhk)
            
            if res and res.get("ok"):
                data = res.get("data", {})

                tong_diem = data.get("diem_ren_luyen", data.get("tong_diem", "Chưa có"))
                xep_loai = data.get("xep_loai", "Chưa có")
                response_text = f"Điểm rèn luyện của bạn: Tổng điểm {tong_diem}, xếp loại: {xep_loai}."
                confidence = 0.95
                method = "student_rl_grades_api"
            else:
                response_text = "Không lấy được điểm rèn luyện từ API lúc này."
                confidence = 0.7
                method = "student_rl_grades_error"
            
            logger.info(f"📊 RL grades response: {response_text[:50]}...")
            return {
                "status": "success",
                "mode": "text",
                "response": response_text,
                "method": method,
                "confidence": confidence,
                "mssv": profile.mssv,
            }
        
        elif _needs_student_exam_schedule(query):
            logger.info("📅 Exam schedule intent detected, calling API")
            
            nkhk = _extract_nkhk_from_query(query)
            res = external_api_service.get_student_exam_schedule(jwt_token, query, nkhk)
            
            if res and res.get("ok"):
                exam_data = res.get("data", [])
                q_lower = query.lower()
            
                target_subject_name = ""
                match = re.search(r'môn\s+(.+)', q_lower) # VD: "lịch thi môn [abc]"
                if not match:
                    match = re.search(r'khi\s+nào\s+thi\s+(?:môn\s+)?(.+)', q_lower) 
                
                if match:
                    target_subject_name = match.group(1).strip()
                    target_subject_name = re.sub(r'\s*(không|ko|ạ|à|vậy)\??$', '', target_subject_name, flags=re.IGNORECASE).strip()

                exam_data_to_format = [] # Đây là danh sách sẽ dùng để hiển thị

                if target_subject_name and exam_data:
                    logger.info(f"📅 Filtering exam schedule for subject: '{target_subject_name}'")
                    norm_target = _normalize_text(target_subject_name) # Dùng hàm _normalize_text có sẵn
                    
                    for exam in exam_data:
                        exam_name = exam.get('ten_mon_hoc', 'N/A')
                        norm_exam_name = _normalize_text(exam_name)
                        
                        if norm_target in norm_exam_name:
                            exam_data_to_format.append(exam)
                else:
                    exam_data_to_format = exam_data
                if not exam_data_to_format:
                    if target_subject_name: # Nếu có lọc nhưng không thấy
                        response_text = f"Chào {profile.ho_ten}, mình không tìm thấy lịch thi nào cho môn '{target_subject_name}' trong học kỳ này."
                    else: # Nếu không có lịch thi chung
                        response_text = f"Chào {profile.ho_ten}, bạn không có lịch thi nào được ghi nhận trong học kỳ này."
                else:
                    if target_subject_name: # Header cho môn cụ thể
                         response_text = f"Đây là lịch thi môn '{target_subject_name}' của bạn, {profile.ho_ten}:\n"
                    else: # Header chung
                         response_text = f"Đây là lịch thi của bạn, {profile.ho_ten}:\n"
                    for exam in exam_data_to_format: 
                        ten_mon_hoc = exam.get('ten_mon_hoc', 'N/A')
                        ma_mon_hoc = exam.get('ma_mon_hoc', '')
                        hinh_thuc = exam.get('hinh_thuc', 'Chưa cập nhật')
                        # Sử dụng 'or' để hiển thị "(Chưa có)" nếu dữ liệu là null
                        ngay_thi = exam.get('ngay') or "Chưa có"
                        gio_thi = exam.get('gio_bd') or "Chưa có"
                        phong_thi = exam.get('phong') or "Chưa có"
                        
                        response_text += (
                            f"\n- **{ten_mon_hoc} ({ma_mon_hoc})**\n"
                            f"  - Hình thức: {hinh_thuc}\n"
                            f"  - Ngày thi: {ngay_thi}\n"
                            f"  - Giờ thi: {gio_thi}\n"
                            f"  - Phòng thi: {phong_thi}\n"
                        )
                return {
                    "status": "success",
                    "mode": "text",
                    "response": response_text,
                    "method": "student_exam_schedule_api",
                    "confidence": 0.98,
                    "mssv": profile.mssv,
                    "student_name": profile.ho_ten,
                    "exam_data": exam_data_to_format 
                }
            else:
                response_text = "Mình gặp chút khó khăn khi tra cứu lịch thi của bạn lúc này. Vui lòng thử lại sau nhé."
                return {
                    "status": "error",
                    "response": response_text,
                    "method": "student_exam_schedule_error",
                    "confidence": 0.7,
                    "mssv": profile.mssv
                }
        
        elif _needs_student_union_info(query):
            logger.info("✊ Union member intent detected, calling API")
            res = external_api_service.get_student_union_info(jwt_token)
            if res and res.get("ok"):
                data = res.get("data", {})
                if not data:
                    response_text = f"Chào {profile.ho_ten}, mình không tìm thấy thông tin Đoàn viên của bạn trong hệ thống."
                else:
                    ngay_vao_doan = data.get('ngay_vao_doan') or "chưa có thông tin"
                    ngay_vao_dang = data.get('ngay_vao_dang') or "chưa có thông tin"
                    khen_thuong = "Không có" if data.get('khen_thuong') == "Không" else data.get('khen_thuong', 'Không có')
                    ky_luat = "Không có" if data.get('ky_luat') == "Không" else data.get('ky_luat', 'Không có')
                    
                    ma_dinh_danh = data.get('ma_dinh_danh_doan_vien') or "chưa có thông tin"
                    so_the_doan = data.get('so_the_doan') or "chưa có thông tin"

                    response_text = (
                        f"Chào {profile.ho_ten}, mình đã tra cứu được thông tin Đoàn viên của bạn:\n"
                        f"\n- **Mã định danh:** {ma_dinh_danh}"
                        f"\n- **Số thẻ Đoàn:** {so_the_doan}"
                        f"\n- **Đơn vị sinh hoạt:** {data.get('don_vi', 'Chưa có')}"
                        f"\n- **Chức vụ:** {data.get('chuc_vu_chi_doan', 'Chưa có')}"
                        f"\n- **Ngày vào Đoàn:** {ngay_vao_doan}"
                        f"\n- **Đối tượng:** {data.get('doi_tuong_doan_vien', 'Chưa có')}"
                        f"\n\n**Về trình độ:**"
                        f"\n  - **Văn hóa:** {data.get('trinh_do_van_hoa', 'Chưa có')}"
                        f"\n  - **Chuyên môn:** {data.get('trinh_do_chuyen_mon', 'Chưa có')}"
                        f"\n  - **Lý luận chính trị:** {data.get('trinh_do_ly_luan_chinh_tri', 'Chưa có')}"
                        f"\n  - **Tin học:** {data.get('tin_hoc', 'Chưa có')}"
                        f"\n  - **Ngoại ngữ:** {data.get('ngoai_ngu', 'Chưa có')}"
                        f"\n\n**Về quá trình rèn luyện:**"
                        f"\n  - **Đánh giá/Xếp loại:** {data.get('danh_gia_xep_loai', 'Chưa có')}"
                        f"\n  - **Khen thưởng:** {khen_thuong}"
                        f"\n  - **Kỷ luật:** {ky_luat}"
                        f"\n\nNếu có thông tin nào chưa chính xác, bạn vui lòng liên hệ với văn phòng Đoàn trường để được hỗ trợ cập nhật nhé. ✊"
                    )

                return {
                    "status": "success",
                    "mode": "text",
                    "response": response_text,
                    "method": "student_union_info_api",
                    "confidence": 0.98,
                    "mssv": profile.mssv,
                    "student_name": profile.ho_ten,
                    "union_data": data
                }
            else:
                return {
                    "status": "error",
                    "response": "Mình gặp sự cố khi tra cứu thông tin Đoàn viên của bạn. Vui lòng thử lại sau.",
                    "method": "student_union_info_error",
                    "confidence": 0.7,
                    "mssv": profile.mssv
                }
        
        elif _needs_student_schedule(query):
            logger.info("📅 Schedule intent detected, calling API and THEN filtering")
            res = external_api_service.get_student_schedule(jwt_token, query)
            params_used = res.get("params_used", {}) 
            
            if not res.get("ok"):
                return {
                    "status": "error",
                    "message": f"Không lấy được thời khóa biểu: {res.get('reason')}",
                    "error_type": "schedule_failed"
                }
            
            schedule_entries = res.get("data", [])
            
            #
            # --- LOGIC FILTER MỚI (ĐÂY LÀ PHẦN SỬA LỖI "THẦY HIỆP") ---
            #
            target_teacher = _extract_teacher_name(query)
            filtered_schedule = schedule_entries
            
            if target_teacher and schedule_entries:
                logger.info(f"🔍 Filtering schedule cho giảng viên: '{target_teacher}'")
                norm_target_teacher = _normalize_text(target_teacher) # 'hiep'
                
                temp_filtered = []
                for entry in schedule_entries:
                    gv_name = entry.get('ten_giang_vien', '')
                    norm_gv_name = _normalize_text(gv_name) # 'le van hiep'
                    
                    # Kiểm tra xem 'hiep' có trong 'le van hiep' không
                    if norm_target_teacher in norm_gv_name:
                        temp_filtered.append(entry)
                
                filtered_schedule = temp_filtered # Ghi đè danh sách
                
                if not filtered_schedule:
                    logger.warning(f"⚠️ Không tìm thấy lớp nào của GV '{target_teacher}' trong lịch học của SV.")
                    # Tạo câu trả lời trực tiếp (Không cần Gemini)
                    response_text = f"Chào {profile.ho_ten.split()[-1]}, theo lịch học của bạn, **{target_teacher.title()}** không dạy bạn môn nào trong khoảng thời gian này."
                    return {
                        "status": "success", "mode": "text", "response": response_text,
                        "method": "student_schedule_filtered_empty",
                        "confidence": 0.99, "mssv": profile.mssv, "student_name": profile.ho_ten,
                        "class": profile.lop, "faculty": profile.khoa,
                        "schedule_data": [], "total_entries": 0
                    }
            #
            # --- KẾT THÚC LOGIC FILTER ---
            #
            
            try:
                # Gọi Gemini với danh sách schedule ĐÃ LỌC
                gemini = GeminiResponseGenerator()
                session_id = f"student_{profile.mssv}_schedule"
                
                gemini.set_user_context(session_id, {
                    "full_name": profile.ho_ten,
                    "mssv": profile.mssv,
                    "class_name": profile.lop,
                    "faculty": profile.khoa
                })

                gemini_context = {
                    "instruction": "enhance_answer_boosted",
                    "api_data": filtered_schedule, # <-- QUAN TRỌNG: Gửi danh sách ĐÃ LỌC
                    "data_type": "schedule",
                    "date_range": params_used,
                    "profile": {
                        "name": profile.ho_ten,
                        "mssv": profile.mssv,
                        "class": profile.lop,
                        "faculty": profile.khoa,
                        "date_range": params_used
                    }
                }
                gemini_response = gemini.generate_response(
                    query=query,
                    context=gemini_context,
                    session_id=session_id
                )

                response_text = gemini_response.get("response")
                if not response_text:
                    raise ValueError("Gemini returned an empty response.")

                return {
                    "status": "success",
                    "mode": "text",
                    "response": response_text,
                    "method": "gemini_schedule_filtered" if target_teacher else "gemini_schedule_full",
                    "confidence": gemini_response.get('confidence', 0.9),
                    "mssv": profile.mssv,
                    "student_name": profile.ho_ten,
                    "class": profile.lop,
                    "faculty": profile.khoa,
                    "schedule_data": filtered_schedule, # Trả về data đã lọc
                    "total_entries": len(filtered_schedule)
                }
            except Exception as e:
                logger.error(f"❌ Error during Gemini schedule processing: {e}")
                student_name = profile.ho_ten.split()[-1] if profile.ho_ten else "bạn"

                if not filtered_schedule:  # <-- SỬA: dùng filtered_schedule thay vì schedule_entries
                    fallback_response = f"Chào {student_name}, bạn không có lịch học nào trong khoảng thời gian được yêu cầu."
                else:
                    fallback_response = f"Đây là lịch học của bạn, {student_name}:\n"
                    schedule_by_day = defaultdict(list)
                    for entry in filtered_schedule:  # <-- SỬA: dùng filtered_schedule
                        schedule_by_day[entry['ngay_hoc']].append(entry)
                    
                    for day, sessions in sorted(schedule_by_day.items()):
                        try:
                            from datetime import datetime
                            date_obj = datetime.strptime(day, '%Y-%m-%d')
                            day_str = f"{['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật'][date_obj.weekday()]}, ngày {date_obj.strftime('%d/%m/%Y')}"
                        except:
                            day_str = day
                        fallback_response += f"\n🗓️ **{day_str}:**\n"
                        for session in sessions:
                            tiet_bd = session.get('tiet_bat_dau', '?')
                            so_tiet = session.get('so_tiet', '?')
                            fallback_response += (
                                f"  - **{session.get('ten_mon_hoc', 'N/A')}**\n"
                                f"    (Tiết {tiet_bd} - {so_tiet} tiết, Phòng: {session.get('ma_phong', 'N/A')}, GV: {session.get('ten_giang_vien', 'N/A')})\n"
                            )
                
                return {
                    "status": "success",
                    "mode": "text",
                    "response": fallback_response,
                    "method": "schedule_api_fallback",
                    "confidence": 0.8,
                    "mssv": profile.mssv,
                    "student_name": profile.ho_ten,
                    "class": profile.lop,
                    "faculty": profile.khoa,
                    "schedule_data": filtered_schedule,  # <-- SỬA: dùng filtered_schedule
                    "total_entries": len(filtered_schedule)  # <-- SỬA: dùng filtered_schedule
                }

        elif _needs_student_news(query):
            logger.info("🎯 News intent detected, calling service for OVERVIEW...")
            res = external_api_service.get_student_news(jwt_token, page=1, page_size=10)

            if not res.get("ok"):
                return {"status": "error", "message": "Không thể tải tin tức lúc này."}

            news_articles = res.get("data", [])
            logger.info(f"📰 DEBUG: API returned {len(news_articles)} news articles")
            if news_articles:
                logger.info(f"📰 DEBUG: First article keys: {list(news_articles[0].keys())}")
                logger.info(f"📰 DEBUG: First article sample: {news_articles[0]}")
                titles = [article.get('title', article.get('tieu_de', 'NO_TITLE')) for article in news_articles[:5]]
                logger.info(f"📰 DEBUG: First 5 titles: {titles}")
            else:
                logger.warning("📰 DEBUG: No news articles returned from API")
            news_for_llm = [{
                "title": it["title"],
                "category": it.get("category"),
                "date": it.get("date"),
                "time": it.get("time"),
                "is_pinned": it.get("is_pinned", False),
                "author": it.get("author"),
                "excerpt": it.get("plain")  # dùng plain text 500 ký tự
            } for it in news_articles]
            
            if not news_articles:
                return {
                    "status": "success", "mode": "text", "confidence": 0.9,
                    "response": f"Chào {profile.ho_ten}, hiện tại chưa có tin tức hay thông báo nào mới trong học kỳ này cả nhé."
                }
            
            try:
                gemini = GeminiResponseGenerator() 
                session_id = f"student_{profile.mssv}_news_overview"
                conversation_context = gemini.memory.get_conversation_context(session_id)
                recent_history = conversation_context.get('history', [])

                detected_topic = None
                is_specific_query = False
                
                query_lower = query.lower()
                general_questions = ["có tin tức gì", "tin tức mới", "thông báo mới", "có gì mới"]
                is_general_query = any(gq in query_lower for gq in general_questions)
                if not is_general_query and ('về' in query_lower or any(word in query_lower for word in ['về vấn đề', 've van de'])):
                    is_specific_query = True
                    detected_topic = query
                    logger.info(f"🔍 Detected specific topic from query: '{detected_topic}'")
                elif recent_history:
                    last_interaction = recent_history[-1]
                    last_response = last_interaction.get('bot_response', '').lower()
                    last_query = last_interaction.get('user_query', '').lower()
                    if any(word in last_response for word in ['thông báo', 'thong bao', 'tin tức', 'tin tuc', 'chủ đề']):
                        if not is_general_query:
                            is_specific_query = True
                            detected_topic = query  # Pass full query to Gemini for topic extraction
                            logger.info(f"🔍 Detected specific topic query from follow-up: '{detected_topic}'")
                filtered_news = news_for_llm
                if is_specific_query and detected_topic:
                    logger.info(f"🔍 Filtering news for topic: '{detected_topic}'")
                    filtered_news = []
                    for article in news_for_llm:
                        title = article.get('title', '').lower()
                        excerpt = article.get('excerpt', '').lower()
                        category = article.get('category', '').lower()
                        full_text = f"{title} {excerpt} {category}"
                        query_keywords = detected_topic.lower().split()
                        matches = sum(1 for kw in query_keywords if len(kw) > 2 and kw in full_text)
                        if matches >= max(1, len(query_keywords) // 2):
                            filtered_news.append(article)
                    logger.info(f"📰 Semantic filtered: {len(filtered_news)} articles matching '{detected_topic}'")
                    if not filtered_news:
                        logger.info("📰 No specific match, Gemini will find relevant articles from all")
                        filtered_news = news_for_llm
                else:
                    filtered_news = news_for_llm
                if is_specific_query:
                    logger.info(f"📰 NEWS DETAIL: Processing detailed request - topic: '{detected_topic}'")
                    gemini_context = {
                        "instruction": "summarize_news",
                        "news_data": filtered_news,
                        "user_query": query,  # Pass user's original query to Gemini
                        "is_specific_topic": is_specific_query,
                        "profile": {
                            "full_name": profile.ho_ten,
                            "mssv": profile.mssv
                        }
                    }
                else:
                    logger.info("📰 NEWS OVERVIEW: Processing news overview request")
                    gemini_context = {
                        "instruction": "summarize_news",
                        "news_data": news_for_llm,  # dùng data sạch
                        "profile": {
                            "full_name": profile.ho_ten,
                            "mssv": profile.mssv
                        }
                    }
                
                gemini.set_user_context(session_id, {"full_name": profile.ho_ten})
                gemini_response = gemini.generate_response(
                    query=query,
                    context=gemini_context,
                    session_id=session_id
                )
                
                final_response = gemini_response.get("response")
                if not final_response:
                    raise ValueError("Gemini returned an empty response.")
                if not is_specific_query:
                    gemini.memory.add_interaction(
                        session_id, 
                        query, 
                        final_response,
                        intent_info={"news_context": news_articles}  # Lưu dữ liệu tin tức
                    )
                if is_specific_query:
                    method = "student_news_gemini_topic"
                else:
                    method = "student_news_gemini_overview"
                return {
                    "status": "success", 
                    "mode": "text", 
                    "response": final_response,
                    "method": method, 
                    "confidence": 0.95
                }
            except Exception as e:
                logger.error(f"❌ Error during Gemini news processing: {e}")
                return {"status": "error", "message": "Lỗi trong quá trình xử lý tin tức."}
            
        logger.info("ℹ️ Không có intent API sinh viên nào khớp. Chuyển sang RAG.")
        return {
            "status": "fallback_to_rag",
            "mode": "text",
            "message": "Không phải câu hỏi API, chuyển sang RAG.",
            "method": "student_intent_miss"
        }
        
    except Exception as e:
        logger.error(f"❌ Error in handle_external_api_student: {str(e)}")
        return {
            "status": "error",
            "message": "Đã xảy ra lỗi khi xử lý yêu cầu của sinh viên",
            "error_type": "unexpected_error"
        }

def decide_and_route_with_student_support(query: str, jwt_token: Optional[str]) -> Dict[str, Any]:
    if not jwt_token:
        return {"status": "unauthorized", "message": "Thiếu token. Vui lòng đăng nhập."}
    if external_api_service.is_student_token(jwt_token):
        logger.info("🎓 Student token detected, routing to student handler")
        return handle_external_api_student(jwt_token, query)
    return {"status": "skip_student", "message": "Not a student token"}