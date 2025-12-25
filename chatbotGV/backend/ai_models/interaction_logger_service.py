import os
import csv
import threading
from datetime import datetime
from typing import Optional
from django.conf import settings

class InteractionLoggerService:
    """
    ✍️ Ghi lại các tương tác không thành công hoặc có độ tin cậy thấp để phân tích.
    Dữ liệu sẽ được lưu vào file CSV để dễ dàng xử lý cho việc training sau này.
    """
    def __init__(self):
        # Đảm bảo thư mục logs tồn tại
        self.log_dir = os.path.join(settings.BASE_DIR, 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Đường dẫn tới file log CSV
        self.log_file_path = os.path.join(self.log_dir, 'failed_interactions.csv')
        
        # Header cho file CSV
        self.csv_header = [
            'timestamp', 
            'user_query', 
            'bot_response', 
            'confidence_score', 
            'method',
            'reason_for_logging'
        ]
        
        # 🔒 Sử dụng Lock để tránh xung đột khi ghi file từ nhiều request cùng lúc
        self._lock = threading.Lock()
        
        # Khởi tạo file nếu chưa tồn tại
        self._initialize_log_file()

    def _initialize_log_file(self):
        """Kiểm tra và tạo file log với header nếu nó chưa tồn tại."""
        with self._lock:
            if not os.path.exists(self.log_file_path):
                with open(self.log_file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.csv_header)

    def log_interaction(self, query: str, response: str, confidence: float, method: str, reason: str):
        """
        Ghi lại một tương tác vào file CSV.

        Args:
            query (str): Câu hỏi của người dùng.
            response (str): Câu trả lời (chưa đạt yêu cầu) của bot.
            confidence (float): Điểm tin cậy của câu trả lời.
            method (str): Phương thức mà bot đã sử dụng (ví dụ: 'fallback', 'no_match').
            reason (str): Lý do tại sao tương tác này được ghi lại.
        """
        try:
            with self._lock:
                timestamp = datetime.now().isoformat()
                
                log_entry = {
                    'timestamp': timestamp,
                    'user_query': query,
                    'bot_response': response,
                    'confidence_score': round(confidence, 4),
                    'method': method,
                    'reason_for_logging': reason
                }
                
                with open(self.log_file_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=self.csv_header)
                    writer.writerow(log_entry)
                    
                # print(f"✍️ Logged failed interaction: {query[:50]}... Reason: {reason}")

        except Exception as e:
            # Dùng logger của Django để báo lỗi nếu việc ghi log thất bại
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"❌ Could not write to interaction log file: {e}")

interaction_logger = InteractionLoggerService()