# ai_models/ocr_service.py
import os
import logging
from typing import List, Dict, Optional
from django.conf import settings
import pytesseract
from pdf2image import convert_from_path
import docx
import re

# 🆕 NEW: Import PIL for image processing
try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Warning: PIL (Pillow) not installed. Image processing will not be available.")

logger = logging.getLogger(__name__)

class OCRService:
    """
    Hỗ trợ trích xuất văn bản từ file PDF, DOCX và các định dạng ảnh
    (JPG, PNG, JPEG, BMP, TIFF, WEBP) sử dụng Tesseract OCR
    và các thư viện xử lý văn bản khác.
    """
    
    def __init__(self):
        """Khởi tạo OCR Service với cấu hình từ Django settings"""
        self.tesseract_cmd_path = None
        self.poppler_path = None
        self.is_configured = False
        
        # 🆕 NEW: Supported image formats
        self.supported_image_formats = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp']
        
        self._configure_paths()
        self._validate_configuration()
        
        logger.info("✅ Enhanced OCRService initialized successfully" if self.is_configured else "⚠️ OCRService initialized with configuration issues")
    
    def _configure_paths(self):
        """Cấu hình đường dẫn Tesseract và Poppler từ Django settings"""
        try:
            # Lấy cấu hình từ Django settings
            self.tesseract_cmd_path = getattr(settings, 'TESSERACT_CMD_PATH', None)
            self.poppler_path = getattr(settings, 'POPPLER_PATH_BIN', None)
            
            # Fallback: nếu không có trong settings, thử lấy từ environment variables
            if not self.tesseract_cmd_path:
                tesseract_relative = os.getenv("TESSERACT_PATH_RELATIVE")
                if tesseract_relative:
                    project_root = getattr(settings, 'BASE_DIR', '').parent
                    self.tesseract_cmd_path = os.path.join(project_root, tesseract_relative)
            
            if not self.poppler_path:
                poppler_relative = os.getenv("POPPLER_PATH_RELATIVE")
                if poppler_relative:
                    project_root = getattr(settings, 'BASE_DIR', '').parent
                    self.poppler_path = os.path.join(project_root, poppler_relative)
            
            logger.info(f"🔧 OCR Paths configured: Tesseract='{self.tesseract_cmd_path}', Poppler='{self.poppler_path}'")
            
        except Exception as e:
            logger.error(f"❌ Error configuring OCR paths: {str(e)}")
            self.tesseract_cmd_path = None
            self.poppler_path = None
    
    def _validate_configuration(self):
        """Kiểm tra và xác thực cấu hình OCR"""
        try:
            # Kiểm tra Tesseract
            if self.tesseract_cmd_path and os.path.exists(self.tesseract_cmd_path):
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd_path
                logger.info(f"✅ Tesseract configured at: {self.tesseract_cmd_path}")
            else:
                logger.warning(f"⚠️ Tesseract not found at: {self.tesseract_cmd_path}")
                return
          
            # Kiểm tra Poppler
            if self.poppler_path and os.path.exists(self.poppler_path):
                logger.info(f"✅ Poppler configured at: {self.poppler_path}")
            else:
                logger.warning(f"⚠️ Poppler not found at: {self.poppler_path}")
                return
            
            # 🆕 NEW: Check PIL availability
            if not PIL_AVAILABLE:
                logger.warning("⚠️ PIL (Pillow) not available - image processing will be limited")
            else:
                logger.info("✅ PIL (Pillow) available for image processing")
            
            # Test cơ bản với Tesseract
            try:
                pytesseract.get_tesseract_version()
                self.is_configured = True
                logger.info("✅ OCR Service validation successful")
            except Exception as e:
                logger.error(f"❌ Tesseract validation failed: {str(e)}")
                
        except Exception as e:
            logger.error(f"❌ OCR configuration validation error: {str(e)}")
    
    def extract_text_from_pdf(self, pdf_path: str) -> Optional[List[Dict]]:
        if not self.is_configured:
            logger.error("❌ OCR Service not properly configured")
            return None
        
        if not os.path.exists(pdf_path):
            logger.error(f"❌ PDF file not found: {pdf_path}")
            return None
        
        try:
            logger.info(f"📄 Starting PDF OCR extraction: {os.path.basename(pdf_path)}")
            
            # Chuyển đổi PDF thành hình ảnh
            pages_as_images = convert_from_path(pdf_path, poppler_path=self.poppler_path)
            extracted_data = []
            
            for i, page_image in enumerate(pages_as_images):
                page_num = i + 1
                logger.info(f"  -> OCR processing page {page_num}/{len(pages_as_images)}")
                
                # Thực hiện OCR với tiếng Việt
                text = pytesseract.image_to_string(page_image, lang='vie')
                
                # Làm sạch văn bản
                cleaned_text = self._clean_extracted_text(text)
                
                extracted_data.append({
                    "page": page_num,
                    "text": cleaned_text
                })
            
            logger.info(f"✅ PDF OCR completed: {len(extracted_data)} pages processed")
            return extracted_data
            
        except Exception as e:
            logger.error(f"❌ Error extracting text from PDF: {str(e)}")
            return None
    
    def extract_text_from_docx(self, docx_path: str) -> Optional[List[Dict]]:
        if not os.path.exists(docx_path):
            logger.error(f"❌ DOCX file not found: {docx_path}")
            return None
        
        try:
            logger.info(f"📄 Starting DOCX text extraction: {os.path.basename(docx_path)}")
            
            # Đọc file DOCX
            doc = docx.Document(docx_path)
            
            # Trích xuất tất cả paragraph
            paragraphs = []
            for para in doc.paragraphs:
                if para.text.strip():
                    paragraphs.append(para.text.strip())
            
            # Kết hợp thành văn bản hoàn chỉnh
            full_text = "\n".join(paragraphs)
            cleaned_text = self._clean_extracted_text(full_text)
            
            logger.info(f"✅ DOCX extraction completed: {len(paragraphs)} paragraphs processed")
            
            return [{"page": 1, "text": cleaned_text}]
            
        except Exception as e:
            logger.error(f"❌ Error extracting text from DOCX: {str(e)}")
            return None
    
    def extract_text_from_image(self, image_path: str) -> Optional[List[Dict]]:
        if not self.is_configured:
            logger.error("❌ OCR Service not properly configured")
            return None
        
        if not PIL_AVAILABLE:
            logger.error("❌ PIL (Pillow) not available for image processing")
            return None
        
        if not os.path.exists(image_path):
            logger.error(f"❌ Image file not found: {image_path}")
            return None
        
        try:
            logger.info(f"🖼️ Starting Image OCR extraction: {os.path.basename(image_path)}")
            
            # Đọc và xử lý ảnh
            image = Image.open(image_path)
            
            # 🆕 NEW: Image preprocessing for better OCR
            processed_image = self._preprocess_image_for_ocr(image)
            
            # Thực hiện OCR với tiếng Việt
            text = pytesseract.image_to_string(processed_image, lang='vie')
            
            # Làm sạch văn bản
            cleaned_text = self._clean_extracted_text(text)
            
            logger.info(f"✅ Image OCR completed: {len(cleaned_text)} characters extracted")
            
            return [{"page": 1, "text": cleaned_text}]
            
        except Exception as e:
            logger.error(f"❌ Error extracting text from image: {str(e)}")
            return None
    
    def _preprocess_image_for_ocr(self, image: Image.Image) -> Image.Image:
        try:
            # Chuyển về RGB nếu cần
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Tăng độ tương phản
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.5)
            
            # Tăng độ sắc nét
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(1.2)
            
            # Chuyển về grayscale để OCR tốt hơn
            image = image.convert('L')
            
            # Resize nếu ảnh quá nhỏ (OCR hoạt động tốt hơn với ảnh lớn)
            width, height = image.size
            min_size = 1000
            if width < min_size or height < min_size:
                scale_factor = max(min_size / width, min_size / height)
                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                logger.debug(f"🔍 Image resized from {width}x{height} to {new_width}x{new_height}")
            
            return image
            
        except Exception as e:
            logger.warning(f"⚠️ Image preprocessing failed: {str(e)}, using original image")
            return image
    
    def read_document(self, file_path: str) -> Optional[List[Dict]]:
        if not file_path or not os.path.exists(file_path):
            logger.error(f"❌ File not found: {file_path}")
            return None
        
        # Xác định định dạng file
        _, file_extension = os.path.splitext(file_path)
        file_extension = file_extension.lower()
        
        logger.info(f"🚀 Processing document: {os.path.basename(file_path)} ({file_extension})")
        
        # Điều phối xử lý theo định dạng
        if file_extension == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_extension == '.docx':
            return self.extract_text_from_docx(file_path)
        elif file_extension in self.supported_image_formats:
            # 🆕 NEW: Handle image files
            return self.extract_text_from_image(file_path)
        else:
            logger.error(f"❌ Unsupported file format: {file_extension}")
            logger.info(f"📋 Supported formats: PDF, DOCX, {', '.join(self.supported_image_formats)}")
            return None
    
    def find_precise_quote(self, pages_data: List[Dict], search_phrase: str) -> Optional[Dict]:
        if not pages_data or not search_phrase:
            return None
        
        logger.info(f"🔍 Searching for precise quote: '{search_phrase}'")
        
        for page_info in pages_data:
            lines = page_info["text"].split('\n')
            
            for line in lines:
                line = line.strip()
                if len(line) > 3 and search_phrase.lower() in line.lower():
                    logger.info(f"  -> ✅ Quote found on page {page_info['page']}")
                    return {
                        "quote": line,
                        "location_text": f"Trang {page_info['page']}"
                    }
        
        logger.info("  -> ❌ No precise quote found")
        return None
    
    def _clean_extracted_text(self, text: str) -> str:
        if not text:
            return ""
        
        # Bước 1: Làm sạch cơ bản
        # Loại bỏ các dòng trống liên tiếp
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        # Loại bỏ khoảng trắng thừa
        text = re.sub(r'[ \t]+', ' ', text)
        
        # Loại bỏ khoảng trắng đầu và cuối mỗi dòng
        lines = []
        for line in text.split('\n'):
            line = line.strip()
            if line:
                lines.append(line)
        
        # Bước 2: ⭐ NHIỆM VỤ 2 - Xử lý các dòng có khả năng là hàng trong bảng
        processed_lines = []
        
        for line in lines:
            # Tìm các dòng bắt đầu bằng số thứ tự (có thể là hàng trong bảng)
            # Pattern: bắt đầu bằng 1-2 chữ số, sau đó có khoảng trắng
            table_row_pattern = r'^(\d{1,2})\s+(.+)$'
            match = re.match(table_row_pattern, line)
            
            if match:
                row_number = match.group(1)
                rest_of_line = match.group(2)
                
                # Cố gắng phân tích và tái cấu trúc nội dung hàng bảng
                formatted_line = self._format_table_row(row_number, rest_of_line)
                processed_lines.append(formatted_line)
                
                logger.debug(f"🔧 Table row processed: '{line}' -> '{formatted_line}'")
            else:
                # Giữ nguyên các dòng không phải bảng
                processed_lines.append(line)
        
        return '\n'.join(processed_lines)
    
    def _format_table_row(self, row_number: str, content: str) -> str:
        try:
            # Các pattern phổ biến để nhận diện cấu trúc bảng
            # Pattern 1: Họ tên + Chức vụ + Nhiệm vụ (thường gặp trong danh sách thành viên)
            name_position_task_pattern = r'^([A-ZÄ][a-záắằẳẵặăâầấẩẫậàáảãạêềếểễệèéẻẽẹôốồổỗộơớờởỡợòóỏõọưứừửữựùúủũụìíỉĩịỳýỷỹỵđ\s]+?)(\s+[A-ZÄ][a-záắằẳẵặăâầấẩẫậàáảãạêềếểễệèéẻẽẹôốồổỗộơớờởỡợòóỏõọưứừửữựùúủũụìíỉĩịỳýỷỹỵđ\s,;]+?)(\s+[A-ZÄ][a-záắằẳẵặăâầấẩẫậàáảãạêềếểễệèéẻẽẹôốồổỗộơớờởỡợòóỏõọưứừửữựùúủũụìíỉĩịỳýỷỹỵđ\s]+)$'
            
            # Thử pattern Họ tên + Chức vụ + Nhiệm vụ
            match = re.match(name_position_task_pattern, content)
            if match and len(match.groups()) >= 2:
                name = match.group(1).strip()
                # Kết hợp phần còn lại làm chức vụ và nhiệm vụ
                remaining = content[len(name):].strip()
                
                # Cố gắng tách chức vụ và nhiệm vụ bằng cách tìm từ khóa
                position_keywords = ['Hiệu trưởng', 'Phó Hiệu trưởng', 'Trưởng', 'Phó Trưởng', 'Giảng viên', 'Thư ký', 'Ủy viên', 'Chủ tịch']
                task_keywords = ['Chủ tịch', 'Phó Chủ tịch', 'Ủy viên', 'Thư ký', 'Thành viên']
                
                position = ""
                task = ""
                
                # Tìm từ khóa chức vụ
                for keyword in position_keywords:
                    if keyword in remaining:
                        # Tách phần chứa keyword làm chức vụ
                        parts = remaining.split(keyword)
                        if len(parts) >= 2:
                            position = (parts[0] + keyword).strip()
                            remaining_after_position = parts[1].strip()
                            
                            # Phần còn lại có thể là nhiệm vụ
                            for task_keyword in task_keywords:
                                if task_keyword in remaining_after_position:
                                    task = remaining_after_position.strip()
                                    break
                            
                            if not task:
                                task = remaining_after_position.strip()
                            break
                
                # Nếu không tách được, sử dụng heuristic đơn giản
                if not position and not task:
                    words = remaining.split()
                    if len(words) > 3:
                        # Giả sử 2/3 đầu là chức vụ, 1/3 cuối là nhiệm vụ
                        split_point = len(words) * 2 // 3
                        position = ' '.join(words[:split_point])
                        task = ' '.join(words[split_point:])
                    else:
                        position = remaining
                        task = "Thành viên"
                
                # Định dạng lại với nhãn rõ ràng
                formatted = f"Thành viên {row_number}: {name}"
                if position:
                    formatted += f", Chức vụ: {position}"
                if task:
                    formatted += f", Nhiệm vụ: {task}"
                
                return formatted
            
            # Pattern 2: Nếu không match pattern trên, thử format đơn giản
            # Giả sử cấu trúc: số + tên + thông tin khác
            parts = content.split(None, 2)  # Tách thành tối đa 3 phần
            if len(parts) >= 2:
                name = parts[0]
                if len(parts) >= 3:
                    additional_info = ' '.join(parts[1:])
                    return f"Thành viên {row_number}: {name}, Thông tin: {additional_info}"
                else:
                    return f"Thành viên {row_number}: {name}"
            
            # Fallback: nếu không thể phân tích, chỉ thêm nhãn
            return f"Mục {row_number}: {content}"
            
        except Exception as e:
            logger.debug(f"⚠️ Error formatting table row: {e}")
            # Fallback an toàn
            return f"Mục {row_number}: {content}"
    
    def get_document_summary(self, pages_data: List[Dict]) -> str:
        if not pages_data:
            return "Không có dữ liệu tài liệu"
        
        total_pages = len(pages_data)
        total_chars = sum(len(page["text"]) for page in pages_data)
        
        # Lấy một vài dòng đầu tiên làm preview
        preview_lines = []
        for page in pages_data[:2]:  # Chỉ lấy 2 trang đầu
            lines = page["text"].split('\n')[:3]  # 3 dòng đầu mỗi trang
            preview_lines.extend(lines)
        
        preview = '\n'.join(preview_lines[:5])  # Tổng cộng 5 dòng
        
        return f"""📄 Tóm tắt tài liệu:
- Số trang: {total_pages}
- Độ dài văn bản: {total_chars} ký tự
- Nội dung đầu tiên:
{preview}"""
    
    def is_service_available(self) -> bool:
        """
        Kiểm tra xem OCR service có sẵn sàng không
        
        Returns:
            bool: True nếu service sẵn sàng
        """
        return self.is_configured
    
    def get_service_status(self) -> Dict:
        """
        Lấy trạng thái chi tiết của OCR service
        
        Returns:
            Dict: Thông tin trạng thái service
        """
        return {
            'is_configured': self.is_configured,
            'tesseract_path': self.tesseract_cmd_path,
            'poppler_path': self.poppler_path,
            'tesseract_available': bool(self.tesseract_cmd_path and os.path.exists(self.tesseract_cmd_path)),
            'poppler_available': bool(self.poppler_path and os.path.exists(self.poppler_path)),
            'pil_available': PIL_AVAILABLE,  # 🆕 NEW: PIL availability status
            'supported_formats': ['.pdf', '.docx'] + self.supported_image_formats,  # 🆕 UPDATED: Include image formats
            'image_formats_supported': self.supported_image_formats,  # 🆕 NEW: Separate image format list
            'features': [
                'PDF OCR extraction',
                'DOCX text extraction', 
                'Image OCR extraction',  # 🆕 NEW: Image OCR feature
                'Image preprocessing for better OCR',  # 🆕 NEW: Image enhancement feature
                'Multiple image format support',  # 🆕 NEW: Multiple formats
                'Precise quote finding',
                'Vietnamese language support',
                'Document summarization',
                'Table structure processing',  # 🚀 NEW: Thêm tính năng xử lý bảng
                'Smart text formatting'  # 🚀 NEW: Thêm tính năng định dạng thông minh
            ]
        }

ocr_service = OCRService()