import jwt
import requests
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any, Optional, List, Tuple
import json
import re
from django.conf import settings
import os
from dataclasses import dataclass
from html import unescape

logger = logging.getLogger(__name__)

# HTML sanitization helpers
TAG_RE = re.compile(r"<[^>]+>")
FILE_IMG_RE = re.compile(r'<img[^>]+src=["\']file://[^"\']+["\'][^>]*>', re.I)
TABLE_TAG_RE = re.compile(r'</?(table|tbody|thead|tr|td|th|figure)[^>]*>', re.I)
WS_RE = re.compile(r'\s+')

def _html_to_text(html: str, limit: int = 500) -> str:
    if not html:
        return ""
    s = html
    s = FILE_IMG_RE.sub('', s)                 # bỏ ảnh nội bộ file://
    s = TABLE_TAG_RE.sub(' ', s)               # bỏ bảng rác MS Word
    s = unescape(s)
    s = TAG_RE.sub(' ', s)                     # gỡ tất cả tag còn lại
    s = WS_RE.sub(' ', s).strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s

def _extract_semester_from_query(query_lower: str) -> Optional[str]:
    """Extract semester info (HK + Year) from query and generate nkhk code."""
    if not query_lower:
        return None
    
    # === SỬA LẠI REGEX VÀ LOGIC ===
    # Pattern: (học kỳ|kỳ) + (1|2|3) + (năm) + (YYYY-YYYY | YY-YY | YYYY)
    # Group 1: Số học kỳ (1, 2, 3)
    # Group 2: Năm bắt đầu (YYYY hoặc YY)
    # Group 3: Năm kết thúc (YYYY hoặc YY, tùy chọn)
    pattern = r"(?:hoc ky|học kỳ|ky|kỳ)\s*([123])\s*(?:nam|năm)?\s*(\d{2,4})(?:[-\s](\d{2,4}))?"
    
    match = re.search(pattern, query_lower)
    
    if match:
        hk_num = match.group(1)
        year1_str = match.group(2)
        year2_str = match.group(3) # Có thể là None

        year1_short = ""
        year2_short = ""

        try:
            # Xử lý năm bắt đầu
            if len(year1_str) == 4: # YYYY
                year1_short = year1_str[-2:]
            elif len(year1_str) == 2: # YY
                year1_short = year1_str
            else:
                return None # Định dạng năm không hợp lệ

            # Xử lý năm kết thúc (nếu có)
            if year2_str:
                if len(year2_str) == 4: # YYYY
                    year2_short = year2_str[-2:]
                elif len(year2_str) == 2: # YY
                    year2_short = year2_str
                else:
                    return None # Định dạng năm không hợp lệ
                
                # Kiểm tra năm kết thúc phải lớn hơn năm bắt đầu 1 đơn vị
                if int(year2_short) != (int(year1_short) + 1) % 100:
                    logger.warning(f"Invalid year range detected: {year1_short}-{year2_short}")
                    return None
            else:
                # Nếu chỉ có năm bắt đầu -> tự suy ra năm kết thúc
                year2_short = str(int(year1_short) + 1).zfill(2)

            # Map số học kỳ sang mã (1->1, 2->3, 3->5)
            # Map số học kỳ sang mã (1->1, 2->2, 3->3)
            hk_map = {'1': '1', '2': '2', '3': '3'}
            if hk_num in hk_map:
                nkhk_suffix = hk_map[hk_num]
                # Tạo mã NKHK theo format YY1YY2SUFFIX (ví dụ: 24253)
                generated_nkhk = f"{year1_short}{year2_short}{nkhk_suffix}"
                logger.info(f"🔍 Generated NKHK from semester/year: HK {hk_num} Năm {year1_short}-{year2_short} -> {generated_nkhk}")
                return generated_nkhk
            else:
                logger.warning(f"Invalid semester number: {hk_num}")
                return None
        except ValueError:
            logger.warning(f"Error parsing year strings: {year1_str}, {year2_str}")
            return None

    logger.debug(f"ℹ️ No semester pattern (HK + Year) found in query.")
    return None

def extract_date_range_from_query(query: str) -> Tuple[Optional[str], Optional[str]]:
    if not query:
        return (None, None)
    
    query_lower = query.lower().strip()
    today = datetime.now()
    
    logger.info(f"🔍 Phân tích thời gian từ câu: '{query}'")
    complex_patterns = {
        'tuần sau nữa': lambda: _calculate_week_range(today, weeks_ahead=2),
        'tuan sau nua': lambda: _calculate_week_range(today, weeks_ahead=2),
        '2 tuần tới': lambda: _calculate_week_range(today, weeks_ahead=2),
        '2 tuan toi': lambda: _calculate_week_range(today, weeks_ahead=2),
        'hai tuần tới': lambda: _calculate_week_range(today, weeks_ahead=2),
        'hai tuan toi': lambda: _calculate_week_range(today, weeks_ahead=2),
        
        'cuối tuần này': lambda: _calculate_weekend_range(today, current_week=True),
        'cuoi tuan nay': lambda: _calculate_weekend_range(today, current_week=True),
        'cuối tuần': lambda: _calculate_weekend_range(today, current_week=True),
        'cuoi tuan': lambda: _calculate_weekend_range(today, current_week=True),
        'cuối tuần sau': lambda: _calculate_weekend_range(today, current_week=False),
        'cuoi tuan sau': lambda: _calculate_weekend_range(today, current_week=False),
        
        'đầu tuần này': lambda: _calculate_early_week_range(today, weeks_ahead=0),
        'dau tuan nay': lambda: _calculate_early_week_range(today, weeks_ahead=0),
        'đầu tuần sau': lambda: _calculate_early_week_range(today, weeks_ahead=1),
        'dau tuan sau': lambda: _calculate_early_week_range(today, weeks_ahead=1),
        
        'tháng này': lambda: _calculate_month_range(today, months_ahead=0),
        'thang nay': lambda: _calculate_month_range(today, months_ahead=0),
        'tháng sau': lambda: _calculate_month_range(today, months_ahead=1),
        'thang sau': lambda: _calculate_month_range(today, months_ahead=1),
    }
    
    for pattern, date_func in complex_patterns.items():
        if pattern in query_lower:
            start_date, end_date = date_func()
            logger.info(f"✅ Khớp mẫu phức tạp: '{pattern}' -> {start_date} đến {end_date}")
            return (start_date, end_date)

    weekday_patterns = {
        'thứ 2': 0, 'thu 2': 0, 'thứ hai': 0, 'thu hai': 0, 'monday': 0,
        'thứ 3': 1, 'thu 3': 1, 'thứ ba': 1, 'thu ba': 1, 'tuesday': 1,
        'thứ 4': 2, 'thu 4': 2, 'thứ tư': 2, 'thu tu': 2, 'wednesday': 2,
        'thứ 5': 3, 'thu 5': 3, 'thứ năm': 3, 'thu nam': 3, 'thursday': 3,
        'thứ 6': 4, 'thu 6': 4, 'thứ sáu': 4, 'thu sau': 4, 'friday': 4,
        'thứ 7': 5, 'thu 7': 5, 'thứ bảy': 5, 'thu bay': 5, 'saturday': 5,
        'chủ nhật': 6, 'chu nhat': 6, 'sunday': 6
    }
    
    for weekday_name, target_weekday in weekday_patterns.items():
        pattern = r'\b' + re.escape(weekday_name) + r'\b'
        
        if re.search(pattern, query_lower):
            has_schedule_context = any(kw in query_lower for kw in [
                'lịch', 'lich', 'tkb', 'thời khóa biểu', 'thoi khoa bieu',
                'học', 'hoc', 'có học', 'co hoc'
            ])
            
            has_time_modifier = any(mod in query_lower for mod in [
                'tuần này', 'tuan nay', 'tuần sau', 'tuan sau', 'này', 'nay', 'tới', 'toi'
            ])
            
            is_ordinal_context = any(kw in query_lower for kw in [
                'lần', 'lan', 'vi phạm', 'vi pham', 'hạng', 'hang', 'điều', 'dieu'
            ])
            
            if (has_schedule_context or has_time_modifier) and not is_ordinal_context:
                is_next_week = any(mod in query_lower for mod in ['tuần sau', 'tuan sau', 'tuần tới', 'tuan toi', 'next week'])
                is_this_week = any(mod in query_lower for mod in ['tuần này', 'tuan nay', 'this week', 'nay'])
                target_date = _get_weekday_date_relative(today, target_weekday, is_next_week, is_this_week)
                date_str = target_date.strftime(ISO_DATE)
                logger.info(f"✅ Khớp thứ trong tuần: '{weekday_name}' (NextWeek={is_next_week}, ThisWeek={is_this_week}) -> {date_str}")
                return (date_str, date_str)

    week_pattern = re.search(r'\b(\d+)\s*tuần\s*(tới|sau|tiếp theo|tiep theo)', query_lower)
    if week_pattern:
        num_weeks = int(week_pattern.group(1))
        start_date, end_date = _calculate_week_range(today, weeks_ahead=num_weeks)
        logger.info(f"✅ Khớp mẫu số: {num_weeks} tuần -> {start_date} đến {end_date}")
        return (start_date, end_date)
    
    day_pattern = re.search(r'(\d+)\s*ngày\s*(tới|sau|tiếp theo|tiep theo)', query_lower)
    if day_pattern:
        num_days = int(day_pattern.group(1))
        start_date = today.strftime(ISO_DATE)
        end_date = (today + timedelta(days=num_days)).strftime(ISO_DATE)
        logger.info(f"✅ Khớp mẫu số: {num_days} ngày -> {start_date} đến {end_date}")
        return (start_date, end_date)

    basic_time_patterns = {
        # Hôm nay
        'hôm nay': lambda: (today.strftime(ISO_DATE), today.strftime(ISO_DATE)),
        'hom nay': lambda: (today.strftime(ISO_DATE), today.strftime(ISO_DATE)),
        'today': lambda: (today.strftime(ISO_DATE), today.strftime(ISO_DATE)),
        
        'ngày mai': lambda: _calculate_single_day(today, days_ahead=1),
        'ngay mai': lambda: _calculate_single_day(today, days_ahead=1),
        'tomorrow': lambda: _calculate_single_day(today, days_ahead=1),
        'mai': lambda: _calculate_single_day(today, days_ahead=1),
        
        'ngày kia': lambda: _calculate_single_day(today, days_ahead=2),
        'ngay kia': lambda: _calculate_single_day(today, days_ahead=2),
        
        'tuần này': lambda: _calculate_week_range(today, weeks_ahead=0),
        'tuan nay': lambda: _calculate_week_range(today, weeks_ahead=0),
        'this week': lambda: _calculate_week_range(today, weeks_ahead=0),
        
        'tuần sau': lambda: _calculate_week_range(today, weeks_ahead=1),
        'tuan sau': lambda: _calculate_week_range(today, weeks_ahead=1),
        'tuần tới': lambda: _calculate_week_range(today, weeks_ahead=1),
        'tuan toi': lambda: _calculate_week_range(today, weeks_ahead=1),
        'next week': lambda: _calculate_week_range(today, weeks_ahead=1),
    }
    
    for pattern, date_func in basic_time_patterns.items():
        if pattern in query_lower:
            start_date, end_date = date_func()
            logger.info(f"✅ Khớp từ khóa cơ bản: '{pattern}' -> {start_date} đến {end_date}")
            return (start_date, end_date)

    date_pattern = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?', query_lower)
    if date_pattern:
        day = int(date_pattern.group(1))
        month = int(date_pattern.group(2))
        year = int(date_pattern.group(3)) if date_pattern.group(3) else today.year
        
        if year < 100:
            year = 2000 + year
        
        try:
            specific_date = datetime(year, month, day)
            date_str = specific_date.strftime(ISO_DATE)
            logger.info(f"✅ Khớp ngày cụ thể: {day}/{month}/{year} -> {date_str}")
            return (date_str, date_str)
        except ValueError:
            logger.warning(f"⚠️ Ngày không hợp lệ: {day}/{month}/{year}")
    logger.info(f"ℹ️ Không tìm thấy từ khóa thời gian trong câu: '{query}'")
    return (None, None)
def _calculate_single_day(today: datetime, days_ahead: int) -> Tuple[str, str]:
    """Tính một ngày cụ thể"""
    target_date = today + timedelta(days=days_ahead)
    date_str = target_date.strftime(ISO_DATE)
    return (date_str, date_str)

def _calculate_week_range(today: datetime, weeks_ahead: int) -> Tuple[str, str]:
    if weeks_ahead == 0:
        start_of_week = today - timedelta(days=today.weekday())
    else:
        start_of_week = today + timedelta(days=(7 * weeks_ahead - today.weekday()))
    
    end_of_week = start_of_week + timedelta(days=6)  # Chủ nhật
    
    return (start_of_week.strftime(ISO_DATE), end_of_week.strftime(ISO_DATE))


def _calculate_weekend_range(today: datetime, current_week: bool = True) -> Tuple[str, str]:
    if current_week:
        days_until_saturday = (5 - today.weekday()) % 7
        if days_until_saturday == 0 and today.weekday() == 5:
            saturday = today
        else:
            saturday = today + timedelta(days=days_until_saturday)
    else:
        saturday = today + timedelta(days=(12 - today.weekday()))
    sunday = saturday + timedelta(days=1)
    return (saturday.strftime(ISO_DATE), sunday.strftime(ISO_DATE))


def _calculate_early_week_range(today: datetime, weeks_ahead: int) -> Tuple[str, str]:
    start_of_target_week = today + timedelta(days=(7 * weeks_ahead - today.weekday()))
    end_of_early_week = start_of_target_week + timedelta(days=2)  # Thứ 4
    return (start_of_target_week.strftime(ISO_DATE), end_of_early_week.strftime(ISO_DATE))


def _calculate_month_range(today: datetime, months_ahead: int) -> Tuple[str, str]:
    target_month = today.month + months_ahead
    target_year = today.year
    while target_month > 12:
        target_month -= 12
        target_year += 1
    start_of_month = datetime(target_year, target_month, 1)
    if target_month == 12:
        end_of_month = datetime(target_year + 1, 1, 1) - timedelta(days=1)
    else:
        end_of_month = datetime(target_year, target_month + 1, 1) - timedelta(days=1)
    return (start_of_month.strftime(ISO_DATE), end_of_month.strftime(ISO_DATE))

def _get_weekday_date_relative(today: datetime, target_weekday: int, is_next_week: bool, is_this_week: bool) -> datetime:
    current_weekday = today.weekday()
    days_ahead = target_weekday - current_weekday
    
    if is_next_week:
        start_of_next_week = today - timedelta(days=current_weekday) + timedelta(days=7)
        target_date = start_of_next_week + timedelta(days=target_weekday)
        return target_date

    elif is_this_week:
        return today + timedelta(days=days_ahead)
        
    else:
        if days_ahead <= 0:  # Đã qua hoặc là hôm nay
            days_ahead += 7
        return today + timedelta(days=days_ahead)

ISO_DATE = "%Y-%m-%d"

def _to_date(d: str) -> Optional[datetime]:
    if not d:
        return None
    d = d.strip()
    for fmt in (ISO_DATE, "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(d, fmt)
        except Exception:
            pass
    return None

@dataclass
class StudentProfile:
    mssv: str
    ho_ten: Optional[str] = None
    lop: Optional[str] = None
    khoa: Optional[str] = None

class ExternalAPIService:
    def __init__(self):
        self.base_url = getattr(settings, 'SCHOOL_API_BASE_URL', 'https://cds.bdu.edu.vn')
        self.student_base = os.getenv('EXPO_PUBLIC_API_URL', 'https://cds.bdu.edu.vn/student/api/v1').rstrip('/')
        self.student_profile_ep = f"{self.student_base}/odp/sinh-vien/profile"
        self.student_tkb_ep = f"{self.student_base}/odp/thoi-khoa-bieu"
        self.student_diem_ep = f"{self.student_base}/odp/diem-ren-luyen"
        self.student_hocphi_ep = f"{self.student_base}/odp/hoc-phi/tuition-all-by-student"
        self.nkhk_endpoint = f"{self.base_url}/app_cbgv/odp/nkhk"
        self.student_curriculum_ep = f"{self.student_base}/odp/chuong-trinh-dao-tao"
        self.student_lichthi_ep = f"{self.student_base}/odp/lich-thi/get-exam-schedule-semester"
        self.news_endpoint = f"{self.student_base}/odp/tin-tuc"
        self.student_doanvien_ep = f"{self.student_base}/odp/doan-vien"
        self.timeout = int(os.getenv('SCHOOL_TIMEOUT', '15'))
        self.jwt_verify = os.getenv('JWT_VERIFY', '0') == '1'
        self.jwt_pubkey = os.getenv('JWT_PUBLIC_KEY', None)
        self.jwt_secret = getattr(settings, 'JWT_SECRET_KEY', None)
        self.jwt_algorithm = getattr(settings, 'JWT_ALGORITHM', 'HS256')
        self.cache = {}
        self.cache_duration = 300  # 5 minutes
        logger.info("✅ ExternalAPIService initialized with Student support")
        logger.info(f"🎓 Student API Base: {self.student_base}")
        logger.info(f"🔐 JWT Verify: {self.jwt_verify}")
    
    def decode_jwt_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            if token.startswith('Bearer '):
                token = token[7:]  # Remove 'Bearer ' prefix
            
            # Nếu không có secret key, thử decode without verification (for testing)
            if not self.jwt_secret:
                logger.warning("⚠️ JWT_SECRET_KEY not configured, decoding without verification")
                decoded = jwt.decode(token, options={"verify_signature": False})
            else:
                decoded = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            
            logger.info(f"✅ JWT decoded successfully for user: {decoded.get('user', {}).get('name', 'Unknown')}")
            return decoded
            
        except jwt.ExpiredSignatureError:
            logger.error("❌ JWT token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.error(f"❌ Invalid JWT token: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"❌ Error decoding JWT: {str(e)}")
            return None

    def _decode_jwt_soft(self, token: str) -> Dict[str, Any]:
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            
            if self.jwt_verify and self.jwt_pubkey:
                return jwt.decode(token, self.jwt_pubkey, algorithms=["RS256", "HS256"], options={"verify_aud": False})
            # Dev mode: no-verify
            return jwt.decode(token, options={"verify_signature": False})
        except Exception as e:
            logger.error(f"❌ Error decoding student JWT: {str(e)}")
            return {}

    def _infer_nkhk_from_date(self, target_date: datetime.date) -> str:
        cache_key = 'nkhk_list'
        current_year = target_date.year
        yy = str(current_year)[2:]  # Lấy 2 số cuối của năm
        month = target_date.month
        if 1 <= month <= 4:
            fallback_nkhk = f"{yy}02{yy}1"  # HK1 (ví dụ: 25251)
        elif 5 <= month <= 8:
            fallback_nkhk = f"{yy}02{yy}3"  # HK2 (ví dụ: 25253)
        else:
            fallback_nkhk = f"{yy}03{yy}5"  # HK3 (ví dụ: 25255)

        nkhk_data = self.cache.get(cache_key)
        if nkhk_data and (datetime.now() - nkhk_data['timestamp']) < timedelta(hours=1): # Cache trong 1 giờ
            logger.info("🧠 Using cached NKHK list.")
            nkhk_list = nkhk_data['data']
        else:
            logger.info(f"🧠 Calling NKHK API endpoint: {self.nkhk_endpoint}")
            try:
                response = requests.get(self.nkhk_endpoint, timeout=self.timeout)
                response.raise_for_status() # Kiểm tra lỗi HTTP (bao gồm 404)

                json_response = response.json()
                if json_response.get("status") == "success" and "data" in json_response and isinstance(json_response["data"], list):
                    nkhk_list = json_response["data"]
                    # Lưu vào cache
                    self.cache[cache_key] = {'timestamp': datetime.now(), 'data': nkhk_list}
                    logger.info(f"✅ Successfully fetched and cached {len(nkhk_list)} NKHK entries.")
                else:
                    logger.error(f"❌ Invalid JSON structure received from NKHK API: {json_response}")
                    nkhk_list = []

            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Exception while fetching NKHK list: {e}")
                nkhk_list = []
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to decode JSON from NKHK API response: {e}")
                nkhk_list = []

        if not nkhk_list:
            logger.warning(f"⚠️ NKHK list is empty or API failed. Falling back to default '{fallback_nkhk}'.")
            return fallback_nkhk

        matched_nkhk = None
        for semester in nkhk_list:
            if not isinstance(semester, dict): continue

            try:
                start_str = semester.get('ngay_bat_dau')
                end_str = semester.get('ngay_ket_thuc')
                ma_nkhk_val = semester.get('ma_nkhk')

                if start_str and end_str and ma_nkhk_val is not None:
                    start_date = datetime.strptime(start_str, '%d-%m-%Y').date()
                    end_date = datetime.strptime(end_str, '%d-%m-%Y').date()

                    if start_date <= target_date <= end_date:
                        matched_nkhk = str(ma_nkhk_val) # Chuyển sang string
                        logger.info(f"✅ Found matching NKHK: {matched_nkhk} for date {target_date.strftime('%Y-%m-%d')}")
                        return matched_nkhk # Trả về ngay khi tìm thấy

            except (ValueError, KeyError, TypeError) as e:
                logger.warning(f"⚠️ Could not parse semester data: {semester}. Error: {e}")
                continue

        default_nkhk = None
        for semester in nkhk_list:
             if not isinstance(semester, dict): continue
             if semester.get('is_default') == 'True' and semester.get('ma_nkhk') is not None:
                default_nkhk = str(semester.get('ma_nkhk'))
                logger.warning(f"⚠️ No date range matched. Falling back to default NKHK: {default_nkhk}")
                return default_nkhk
        logger.error(f"❌ CRITICAL: No matching or default NKHK found. Using hardcoded fallback '{fallback_nkhk}'.")
        return fallback_nkhk
    
    def get_student_news(
        self,
        jwt_token: str,
        page: int = 1,
        page_size: int = 10,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        if not jwt_token:
            return {"ok": False, "error": "jwt_required"}

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        params = {
            "page": page,
            "pageSize": page_size,
            "token": jwt_token
        }
        if category:
            params["category"] = category

        try:
            logger.info(f"📰 Calling news API: {self.news_endpoint} params={params}")
            r = requests.get(self.news_endpoint, headers=headers, params=params, timeout=self.timeout)
            r.raise_for_status()
            raw = r.json()
            if not isinstance(raw, list):
                logger.error(f"[News] Invalid response type: {type(raw)}")
                return {"ok": False, "error": "invalid_response"}

            items = []
            for it in raw:
                date_str = it.get("ngay")
                time_str = it.get("gio") or "00:00"
                dt = None
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                except Exception:
                    pass

                plain = _html_to_text(it.get("noi_dung_html") or "", limit=500)
                title = (it.get("tieu_de") or "").strip()
                
                if not title and plain:
                    title = (plain[:80].rstrip() + "…")

                items.append({
                    "id": it.get("id"),
                    "title": title,
                    "html": it.get("noi_dung_html") or "",
                    "plain": plain,
                    "category": it.get("danh_muc") or "",
                    "date": date_str,
                    "time": time_str,
                    "datetime": dt or datetime.min,
                    "is_pinned": bool(it.get("is_pinned")),
                    "author": it.get("author") or ""
                })

            items.sort(key=lambda x: (0 if x["is_pinned"] else 1, x["datetime"]), reverse=False)

            logger.info(f"📰 DEBUG: Processed {len(items)} items after normalization")
            if items:
                logger.info(f"📰 DEBUG: First processed item: {items[0]}")
                logger.info(f"📰 DEBUG: First 5 processed titles: {[i.get('title') or 'NO_TITLE' for i in items[:5]]}")

            return {
                "ok": True,
                "data": items,
                "pagination": {"page": page, "pageSize": page_size, "returned": len(items)}
            }

        except requests.HTTPError as e:
            logger.error(f"[News] HTTP {e.response.status_code} when calling /odp/tin-tuc: {e}")
            return {"ok": False, "error": f"HTTP_{e.response.status_code}"}
        except Exception as e:
            logger.exception(f"[News] Unexpected error: {e}")
            return {"ok": False, "error": "unexpected_error"}
    
    def get_student_exam_schedule(self, jwt_token: str, query: str, nkhk: Optional[str] = None) -> Dict[str, Any]:
        if not jwt_token:
            return {"ok": False, "reason": "JWT token required"}

        headers = {"Authorization": f"Bearer {jwt_token}"}
        params = {}
        endpoint = self.student_lichthi_ep  # <-- Sử dụng endpoint đã định nghĩa (dòng 318)

        if nkhk:
            final_nkhk = nkhk
        else:
            # ✅ FIX: Parse query để extract NKHK trước
            extracted_nkhk = _extract_semester_from_query(query.lower()) if query else None
            
            if extracted_nkhk:
                final_nkhk = extracted_nkhk
                logger.info(f"✅ Extracted NKHK from query '{query}': {extracted_nkhk}")
            else:
                # Fallback về current semester nếu không parse được
                target_date = datetime.now().date()
                final_nkhk = self._infer_nkhk_from_date(target_date)
                logger.info(f"ℹ️ Using current semester NKHK: {final_nkhk}")
        
        params['nkhk'] = final_nkhk
        
        # === BỔ SUNG PHẦN BỊ THIẾU ===
        try:
            logger.info(f"📝 Calling exam schedule API: {endpoint} with params: {params}")
            r = requests.get(endpoint, headers=headers, params=params, timeout=self.timeout)
            
            if r.status_code == 200:
                data = r.json()
                logger.info(f"✅ Exam schedule API success: {len(data) if isinstance(data, list) else 'object'}")
                return {"ok": True, "data": data}
            else:
                logger.error(f"❌ Exam schedule API failed: {r.status_code} - {r.text}")
                return {"ok": False, "reason": f"API returned {r.status_code}"}
        except Exception as e:
            logger.error(f"❌ Exam schedule API error: {e}")
            return {"ok": False, "reason": str(e)}
    
    def get_student_union_info(self, jwt_token: str) -> Dict[str, Any]:
        if not jwt_token:
            return {"ok": False, "reason": "JWT token required"}

        headers = {"Authorization": f"Bearer {jwt_token}"}
        endpoint = self.student_doanvien_ep

        try:
            logger.info(f"✊ Calling student union info API: {endpoint}")
            r = requests.get(endpoint, headers=headers, timeout=self.timeout)

            if r.status_code == 200:
                logger.info(f"✅ Union info API success")
                return {"ok": True, "data": r.json()}
            else:
                logger.error(f"❌ Union info API failed: {r.status_code} - {r.text}")
                return {"ok": False, "reason": f"API returned {r.status_code}"}
        except Exception as e:
            logger.error(f"❌ Union info API error: {e}")
            return {"ok": False, "reason": str(e)}
    
    def _guess_student_from_claims(self, claims: Dict[str, Any]) -> Optional[str]:
        for key in ("mssv", "student_id", "user_id", "sub"):
            val = claims.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, int):
                return str(val)
        
        sv = claims.get("sinh_vien") or claims.get("student") or {}
        for key in ("mssv", "student_id"):
            val = sv.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    def is_student_token(self, jwt_token: str) -> bool:
        """Check if token belongs to a student"""
        claims = self._decode_jwt_soft(jwt_token)
        role = (claims.get("role") or claims.get("roles") or "").lower()
        if isinstance(role, list):
            role = ",".join(role).lower()
        return "sinhvien" in role or "student" in role or bool(self._guess_student_from_claims(claims))

    def get_student_profile(self, jwt_token: str) -> Optional[StudentProfile]:
        """Get student profile from API"""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        try:
            r = requests.get(self.student_profile_ep, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json() or {}
            else:
                logger.warning(f"⚠️ Primary profile endpoint failed ({r.status_code}), trying fallback...")
                fallback_ep = f"{self.student_base}/odp/profile/me"
                r = requests.get(fallback_ep, headers=headers, timeout=self.timeout)
                if r.status_code != 200:
                    logger.error(f"❌ Student profile API failed: {r.status_code}")
                    return None
                data = r.json() or {}
            mssv = data.get("mssv") or data.get("student_id")
            
            if not mssv:
                claims = self._decode_jwt_soft(jwt_token)
                mssv = self._guess_student_from_claims(claims)
            
            if not mssv:
                logger.error("❌ Could not extract MSSV from profile or token")
                return None
            
            profile = StudentProfile(
                mssv=str(mssv),
                ho_ten=data.get("ho_ten") or data.get("full_name") or data.get("ten_day_du") or f"{data.get('ho_sv', '')} {data.get('ten_sv', '')}".strip(),
                lop=data.get("lop") or data.get("class") or data.get("ten_lop") or data.get("ma_lop"),
                khoa=data.get("khoa") or data.get("faculty") or data.get("ten_khoa") or data.get("ma_khoa"),
            )
            
            logger.info(f"✅ Student profile loaded: {profile.mssv} - {profile.ho_ten}")
            return profile
            
        except Exception as e:
            logger.error(f"❌ Error getting student profile: {str(e)}")
            return None

    def _infer_nkhk(self, jwt_token: str) -> Optional[str]:
        # TODO: Implement if your system has NKHK endpoint
        return None

    def get_student_schedule(
        self,
        jwt_token: str,
        query: str,
        nkhk: Optional[str] = None # Vẫn giữ để có thể override nếu cần
    ) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {jwt_token}"}
        params = {}
        
        start_date_str, end_date_str = extract_date_range_from_query(query)
        
        target_date_for_nkhk = datetime.now().date()
        if start_date_str:
            try:
                target_date_for_nkhk = datetime.strptime(start_date_str, ISO_DATE).date()
            except ValueError:
                logger.warning(f"Could not parse start_date '{start_date_str}', using today for NKHK inference.")

        if nkhk:
            final_nkhk = nkhk
            logger.info(f"✅ Using provided NKHK: {final_nkhk}")
        else:
            final_nkhk = self._infer_nkhk_from_date(target_date_for_nkhk)
        
        params["nkhk"] = final_nkhk
        
        if start_date_str and end_date_str:
            params["start_date"] = start_date_str
            params["end_date"] = end_date_str
        else:
            today = datetime.now().date()
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)
            params["start_date"] = monday.strftime(ISO_DATE)
            params["end_date"] = sunday.strftime(ISO_DATE)

        try:
            logger.info(f"📞 Calling student schedule API with params: {params}")
            r = requests.get(self.student_tkb_ep, headers=headers, params=params, timeout=self.timeout)
            
            if r.status_code != 200:
                logger.error(f"❌ Student schedule API failed: {r.status_code} - {r.text}")
                return {"ok": False, "reason": f"student_tkb_http_{r.status_code}", "data": None, "params_used": params}

            raw_data = r.json()
            flattened_schedule = self._flatten_schedule_data(raw_data)
            logger.info(f"✅ Student schedule loaded and flattened: {len(flattened_schedule)} individual sessions")
            return {"ok": True, "reason": "ok", "data": flattened_schedule, "params_used": params}
            
        except Exception as e:
            logger.error(f"❌ Error getting student schedule: {str(e)}")
            return {"ok": False, "reason": f"api_error: {str(e)}", "data": None, "params_used": params}
    
    def _flatten_schedule_data(self, raw_schedule_data: List[Dict]) -> List[Dict]:
        if not isinstance(raw_schedule_data, list):
            return []
            
        flattened_list = []
        for course_group in raw_schedule_data:
            buoi_hoc_list = course_group.get("buoi_hoc", [])
            if not isinstance(buoi_hoc_list, list):
                continue

            for session in buoi_hoc_list:
                flat_session = {
                    "ngay_hoc": session.get("ngay_hoc"),
                    "buoi_thu": session.get("buoi_thu"),
                    "ma_mon_hoc": course_group.get("ma_mon_hoc"),
                    "ten_mon_hoc": course_group.get("ten_mon_hoc"),
                    "tiet_bat_dau": course_group.get("tiet_bat_dau"),
                    "so_tiet": course_group.get("so_tiet"),
                    "ma_phong": course_group.get("ma_phong"),
                    "ten_giang_vien": course_group.get("ten_giang_vien"),
                    "ma_nhom": course_group.get("ma_nhom"),
                }
                flattened_list.append(flat_session)
        flattened_list.sort(key=lambda x: (x.get('ngay_hoc', ''), x.get('tiet_bat_dau', 0)))
        
        return flattened_list
    
    def get_student_schedule_today(self, jwt_token: str) -> Dict[str, Any]:
        from datetime import datetime, date
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        result = self.get_student_schedule(
            jwt_token=jwt_token,
            start_date=today_str,
            end_date=today_str
        )
        
        if result.get("ok"):
            data = result.get("data", {})
            schedule_data = data.get("data", [])
            today_schedule = []
            for item in schedule_data:
                item_date = item.get("ngay_hoc")
                if item_date == today_str:
                    today_schedule.append(item)
            
            return {
                "success": True,
                "today": today_schedule,
                "date": today_str,
                "total_slots": len(today_schedule)
            }
        else:
            return {
                "success": False,
                "error": result.get("reason", "Unknown error"),
                "today": [],
                "date": today_str,
                "total_slots": 0
            }
    
    def get_student_curriculum(self, jwt_token: str) -> Dict[str, Any]:
        if not jwt_token:
            return {"ok": False, "reason": "JWT token required"}

        headers = {"Authorization": f"Bearer {jwt_token}"}
        endpoint = self.student_curriculum_ep

        try:
            logger.info(f"🎓 Calling student curriculum API: {endpoint}")
            r = requests.get(endpoint, headers=headers, timeout=self.timeout)

            if r.status_code == 200:
                data = r.json()
                logger.info(f"✅ Curriculum API success (Returned {len(data)} blocks)")
                return {"ok": True, "data": data}
            else:
                logger.error(f"❌ Curriculum API failed: {r.status_code} - {r.text}")
                return {"ok": False, "reason": f"API returned {r.status_code}"}
        except Exception as e:
            logger.error(f"❌ Curriculum API error: {e}")
            return {"ok": False, "reason": str(e)}
    
    def get_system_status(self) -> Dict[str, Any]:
        return {
            'external_api_service': {
                'available': True,
                'base_url': self.base_url,
                'endpoints': {
                    'student_profile': self.student_profile_ep,
                    'student_schedule': self.student_tkb_ep,
                    'student_grades': self.student_diem_ep,
                    'student_tuition': self.student_hocphi_ep
                },
                'jwt_configured': bool(self.jwt_secret),
                'jwt_verify_enabled': self.jwt_verify,
                'cache_entries': len(self.cache),
                'cache_duration_seconds': self.cache_duration,
                'timeout_seconds': self.timeout,
                'features': [
                    'jwt_token_decoding',
                    'student_profile_retrieval',
                    'student_schedule_retrieval',
                    'student_grades_retrieval',
                    'student_tuition_retrieval',
                    'enhanced_query_context_filtering',
                    'response_caching',
                    'error_handling',
                    'complex_time_pattern_processing',
                    'priority_based_time_filtering',
                    'flexible_jwt_verification',
                    'iso_date_standardization'
                ]
            }
        }

    def get_student_grades(self, jwt_token: str, nkhk: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not jwt_token:
            logger.error("❌ JWT token required for grades API")
            return {"ok": False, "reason": "JWT token required"}
        
        headers = {"Authorization": f"Bearer {jwt_token}"}
        endpoint = f"{self.student_base}/odp/bang-diem/avg"
        if nkhk:
            endpoint += f"?nkhk={nkhk}"
        
        try:
            logger.info(f"📊 Calling grades API: {endpoint}")
            r = requests.get(endpoint, headers=headers, timeout=self.timeout)
            
            if r.status_code == 200:
                data = r.json()
                logger.info(f"🔍 Raw grades JSON: {json.dumps(data, ensure_ascii=False, indent=2)}")  # Log raw để debug
                logger.info(f"✅ Grades API success: {len(data) if isinstance(data, list) else 'object'}")
                return {"ok": True, "data": data}
            else:
                logger.error(f"❌ Grades API failed: {r.status_code} - {r.text}")
                return {"ok": False, "reason": f"API returned {r.status_code}"}
        except Exception as e:
            logger.error(f"❌ Grades API error: {e}")
            return {"ok": False, "reason": str(e)}

    def get_student_tuition(self, jwt_token: str, nkhk: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not jwt_token:
            logger.error("❌ JWT token required for tuition API")
            return {"ok": False, "reason": "JWT token required"}
        
        headers = {"Authorization": f"Bearer {jwt_token}"}
        endpoint = f"{self.student_base}/odp/hoc-phi/tuition-all-by-student"
        if nkhk:
            endpoint += f"?nkhk={nkhk}"
        
        try:
            logger.info(f"💰 Calling tuition API: {endpoint}")
            r = requests.get(endpoint, headers=headers, timeout=self.timeout)
            
            if r.status_code == 200:
                data = r.json()
                logger.info(f"✅ Tuition API success: {len(data) if isinstance(data, list) else 'object'}")
                return {"ok": True, "data": data}
            else:
                logger.error(f"❌ Tuition API failed: {r.status_code} - {r.text}")
                return {"ok": False, "reason": f"API returned {r.status_code}"}
        except Exception as e:
            logger.error(f"❌ Tuition API error: {e}")
            return {"ok": False, "reason": str(e)}

    def get_student_credits(self, jwt_token: str, query: str) -> Optional[Dict[str, Any]]:
        if not jwt_token:
            logger.error("❌ JWT token required for credits API")
            return {"ok": False, "reason": "JWT token required"}
        
        headers = {"Authorization": f"Bearer {jwt_token}"}
        endpoint = f"{self.student_base}/odp/bang-diem/credit"
        
        try:
            logger.info(f"📊 Calling credits API: {endpoint}")
            r = requests.get(endpoint, headers=headers, timeout=self.timeout)
            
            if r.status_code == 200:
                data = r.json()
                logger.info(f"🔍 Raw credits JSON: {json.dumps(data, ensure_ascii=False, indent=2)}")  # Log raw để debug
                logger.info(f"✅ Credits API success: {len(data) if isinstance(data, list) else 'object'}")
                return {"ok": True, "data": data}
            else:
                logger.error(f"❌ Credits API failed: {r.status_code} - {r.text}")
                return {"ok": False, "reason": f"API returned {r.status_code}"}
        except Exception as e:
            logger.error(f"❌ Credits API error: {e}")
            return {"ok": False, "reason": str(e)}

    def get_student_semester_gpa(self, jwt_token: str, query: str, nkhk: Optional[str] = None) -> Dict[str, Any]:
        if not jwt_token: return {"ok": False, "reason": "JWT token required"}
        
        headers = {"Authorization": f"Bearer {jwt_token}"}
        params = {}

        if nkhk:
            final_nkhk = nkhk
        else:
            # ✅ FIX: Parse query để extract NKHK trước
            extracted_nkhk = _extract_semester_from_query(query.lower()) if query else None
            
            if extracted_nkhk:
                final_nkhk = extracted_nkhk
                logger.info(f"✅ Extracted NKHK from query '{query}': {extracted_nkhk}")
            else:
                # Fallback về current semester nếu không parse được
                target_date = datetime.now().date()
                final_nkhk = self._infer_nkhk_from_date(target_date)
                logger.info(f"ℹ️ Using current semester NKHK: {final_nkhk}")
        
        params['nkhk'] = final_nkhk

    def get_student_rl_grades(self, jwt_token: str, query: str, nkhk: Optional[str] = None) -> Dict[str, Any]:
            if not jwt_token: return {"ok": False, "reason": "JWT token required"}
            
            headers = {"Authorization": f"Bearer {jwt_token}"}
            params = {}

            # === THÊM DÒNG NÀY VÀO ===
            # Định nghĩa endpoint TRƯỚC khi sử dụng nó
            endpoint = self.student_diem_ep
            # ==========================

            if nkhk:
                final_nkhk = nkhk
            else:
                # ✅ FIX: Parse query để extract NKHK trước
                extracted_nkhk = _extract_semester_from_query(query.lower()) if query else None
                
                if extracted_nkhk:
                    final_nkhk = extracted_nkhk
                    logger.info(f"✅ Extracted NKHK from query '{query}': {extracted_nkhk}")
                else:
                    # Fallback về current semester nếu không parse được
                    target_date = datetime.now().date()
                    final_nkhk = self._infer_nkhk_from_date(target_date)
                    logger.info(f"ℹ️ Using current semester NKHK: {final_nkhk}")
            
            params['nkhk'] = final_nkhk
            
            # === BỔ SUNG PHẦN BỊ THIẾU ===
            try:
                # Bây giờ biến 'endpoint' đã tồn tại
                logger.info(f"💪 Calling RL grades API: {endpoint} with params: {params}")
                r = requests.get(endpoint, headers=headers, params=params, timeout=self.timeout)
                
                if r.status_code == 200:
                    data = r.json()
                    logger.info(f"✅ RL grades API success: {len(data) if isinstance(data, list) else 'object'}")
                    return {"ok": True, "data": data}
                else:
                    logger.error(f"❌ RL grades API failed: {r.status_code} - {r.text}")
                    return {"ok": False, "reason": f"API returned {r.status_code}"}
            except Exception as e:
                logger.error(f"❌ RL grades API error: {e}")
                return {"ok": False, "reason": str(e)}

    def get_semester_overview(self, jwt_token: str, nkhk: str) -> Dict[str, Any]:
        url = f"{self.student_base}/odp/bang-diem/avg-semester"
        params = {"nkhk": nkhk}
        headers = {"Authorization": jwt_token if jwt_token.startswith("Bearer ") else f"Bearer {jwt_token}"}
        r = requests.get(url, headers=headers, params=params, timeout=self.timeout)
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "error": r.text}
        data = r.json() if r.text else {}
        # Chuẩn hóa key và null
        return {
            "ok": True,
            "data": {
                "tong_tin_chi": data.get("tong_tin_chi"),
                "diem_trung_binh_he_10": data.get("diem_trung_binh_he_10"),
                "diem_trung_binh_he_4": data.get("diem_trung_binh_he_4"),
                "xep_loai": data.get("xep_loai"),
            }
        }

    def get_score_list(self, jwt_token: str, nkhk: str) -> Dict[str, Any]:
        url = f"{self.student_base}/odp/bang-diem/list"
        params = {"nkhk": nkhk}
        headers = {"Authorization": jwt_token if jwt_token.startswith("Bearer ") else f"Bearer {jwt_token}"}
        r = requests.get(url, headers=headers, params=params, timeout=self.timeout)
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "error": r.text}
        items = r.json() if r.text else []
        # Không assume shape, chỉ lọc object
        valid = [it for it in items if isinstance(it, dict)]
        return {"ok": True, "data": valid}

    def get_score_detail(self, jwt_token: str, ma_nhom: str) -> Dict[str, Any]:
        url = f"{self.student_base}/odp/bang-diem"
        params = {"ma_nhom": ma_nhom}
        headers = {"Authorization": jwt_token if jwt_token.startswith("Bearer ") else f"Bearer {jwt_token}"}
        r = requests.get(url, headers=headers, params=params, timeout=self.timeout)
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "error": r.text}
        raw = r.json() if r.text else {}
        return {"ok": True, "data": raw}

    def get_latest_nkhk(self, jwt_token: str) -> Optional[str]:
        try:
            current_date = date.today()
            nkhk = self._infer_nkhk_from_date(current_date)
            logger.info(f"📅 Latest NKHK for today ({current_date}): {nkhk}")
            return nkhk
        except Exception as e:
            logger.error(f"❌ Error getting latest NKHK: {e}")
            return None

    def get_previous_nkhk(self, jwt_token: str) -> Optional[str]:
        """Lấy học kỳ TRƯỚC HỌC KỲ HIỆN TẠI."""
        try:
            current_nkhk_str = self.get_latest_nkhk(jwt_token)
            if not current_nkhk_str:
                logger.warning("get_previous_nkhk: Could not determine current NKHK.")
                return None

            # Lấy danh sách NKHK (từ cache hoặc API)
            # _infer_nkhk_from_date sẽ tự động gọi API và cache nếu cần
            # Chúng ta chỉ cần truy cập cache mà nó tạo ra
            cache_key = 'nkhk_list'
            nkhk_data = self.cache.get(cache_key)
            
            if not nkhk_data or not nkhk_data.get('data'):
                # Nếu cache rỗng, gọi _infer để điền cache
                logger.info("get_previous_nkhk: NKHK list not in cache, fetching...")
                self._infer_nkhk_from_date(date.today())
                nkhk_data = self.cache.get(cache_key) # Thử lấy lại

            if not nkhk_data or not nkhk_data.get('data'):
                 logger.error("get_previous_nkhk: Failed to get NKHK list from API/cache.")
                 return None

            nkhk_list_of_dicts = nkhk_data['data']
            
            # Sắp xếp danh sách theo ma_nkhk giảm dần (mới nhất -> cũ nhất)
            # Cần đảm bảo ma_nkhk là số để so sánh
            valid_semesters = []
            for sem in nkhk_list_of_dicts:
                if isinstance(sem, dict) and sem.get('ma_nkhk'):
                    try:
                        # Thêm 'ma_nkhk' gốc để trả về
                        sem['ma_nkhk_int'] = int(sem['ma_nkhk'])
                        valid_semesters.append(sem)
                    except (ValueError, TypeError):
                        continue
            
            if not valid_semesters:
                logger.error("get_previous_nkhk: No valid semesters found in list.")
                return None

            valid_semesters.sort(key=lambda x: x['ma_nkhk_int'], reverse=True)
            
            # Tìm index của học kỳ hiện tại
            current_nkhk_int = int(current_nkhk_str)
            current_index = -1
            for i, sem in enumerate(valid_semesters):
                if sem['ma_nkhk_int'] == current_nkhk_int:
                    current_index = i
                    break
            
            if current_index == -1:
                logger.warning(f"get_previous_nkhk: Current NKHK {current_nkhk_str} not found in sorted list.")
                # Fallback: Nếu không tìm thấy, trả về cái cũ thứ 2 trong danh sách
                if len(valid_semesters) > 1:
                    return str(valid_semesters[1]['ma_nkhk'])
                return None
            
            # Lấy học kỳ trước đó (index + 1 vì đã sắp xếp giảm dần)
            previous_index = current_index + 1
            if 0 <= previous_index < len(valid_semesters):
                previous_nkhk = str(valid_semesters[previous_index]['ma_nkhk'])
                logger.info(f"📅 Found previous NKHK: {previous_nkhk} (current was {current_nkhk_str})")
                return previous_nkhk
            else:
                logger.warning(f"get_previous_nkhk: No previous semester found (current is the oldest).")
                return None # Không có học kỳ cũ hơn

        except Exception as e:
            logger.error(f"❌ Error in get_previous_nkhk: {e}")
            return None
    
external_api_service = ExternalAPIService()