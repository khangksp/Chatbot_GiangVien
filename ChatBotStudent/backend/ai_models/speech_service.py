import os
import logging
import torch
from django.conf import settings

# Setup logger
logger = logging.getLogger(__name__)

# Kiểm tra thư viện faster_whisper
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("⚠️ Warning: faster_whisper not installed. Speech-to-text will not be available.")

# Kiểm tra gTTS
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

# Kiểm tra pydub (để xử lý audio speed nếu cần)
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

class SpeechToTextService:
    def __init__(self):
        """
        Khởi tạo dịch vụ STT nhưng KHÔNG load model ngay (Lazy Loading).
        Điều này giúp server khởi động nhanh và tránh crash do thiếu VRAM/Cuda context ban đầu.
        """
        # Kiểm tra GPU
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        # Cấu hình compute type: float16 cho GPU, int8 cho CPU
        self.compute_type = "float16" if self.device == 'cuda' else "int8"
        
        # ⚠️ CẤU HÌNH MODEL: LARGE-V3 (Theo yêu cầu của Khang)
        # Lưu ý: Model này yêu cầu khoảng 3GB-4GB VRAM. 
        self.model_size = "large-v3" 
        
        # Biến chứa model (Khởi tạo là None)
        self.model = None 
        
        logger.info(f"✅ SpeechToTextService initialized (Lazy Loading). Device: {self.device}, Model: {self.model_size}")

    def _load_model(self):
        """
        Hàm nội bộ: Chỉ load model khi thực sự cần dùng (khi có request convert voice).
        """
        if self.model is not None:
            return

        if not WHISPER_AVAILABLE:
            raise ImportError("faster_whisper not available")
        
        logger.info(f"🚀 Lazy Loading Whisper model '{self.model_size}' on {self.device}...")
        
        # 1. Tính toán số worker tối ưu dựa trên CPU
        cpu_count = os.cpu_count() or 4
        num_workers = max(1, cpu_count // 2)
        cpu_threads = max(1, cpu_count // 2)
        
        # 2. ✅ KHẮC PHỤC LỖI SYMLINK WINDOWS & QUYỀN ADMIN:
        # Tạo thư mục 'models_cache' ngay trong project thay vì dùng cache hệ thống.
        cache_dir = os.path.join(settings.BASE_DIR, 'models_cache', 'whisper')
        
        if not os.path.exists(cache_dir):
            try:
                os.makedirs(cache_dir, exist_ok=True)
                logger.info(f"📁 Created local model cache: {cache_dir}")
            except Exception as e:
                logger.error(f"❌ Could not create cache dir {cache_dir}: {e}")
                # Fallback: nếu không tạo được thư mục local, để thư viện tự quyết định (có thể lỗi)
                cache_dir = None

        try:
            # Load model với download_root trỏ về thư mục local
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                num_workers=num_workers,
                cpu_threads=cpu_threads,
                download_root=cache_dir, # 👈 Quan trọng: Tránh lỗi Symlink
                local_files_only=False 
            )
            logger.info(f"✅ Whisper model '{self.model_size}' loaded successfully.")
            
        except OSError as e:
            logger.error(f"❌ OS Error loading Whisper (Possible Symlink/Permission issue): {e}")
            logger.warning("⚠️ Hãy thử chạy lại server với quyền Administrator hoặc kiểm tra dung lượng ổ cứng.")
            raise e
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            raise e

    def transcribe_audio(self, audio_file_path, language='vi', beam_size=5):
        """
        Chuyển đổi file âm thanh thành văn bản.
        """
        if not WHISPER_AVAILABLE:
            return {"success": False, "text": "", "error": "Library 'faster_whisper' not installed"}

        try:
            # ✅ GỌI HÀM LOAD MODEL (Nếu chưa load thì giờ mới load)
            self._load_model()
            
            # Bắt đầu transcribe
            # beam_size=5 giúp tăng độ chính xác nhưng chậm hơn một chút
            segments, info = self.model.transcribe(
                audio_file_path, 
                beam_size=beam_size, 
                language=language
            )
            
            # Gộp các đoạn text lại
            text_segments = []
            for segment in segments:
                text_segments.append(segment.text)
            
            full_text = " ".join(text_segments).strip()
            
            return {
                "success": True,
                "text": full_text,
                "language": info.language,
                "language_probability": info.language_probability
            }
            
        except Exception as e:
            logger.error(f"Error transcribing audio: {str(e)}")
            # Nếu lỗi OOM (Out Of Memory), gợi ý hạ model
            if "CUDA out of memory" in str(e):
                logger.critical("❌ GPU VRAM OOM! Hãy thử hạ model_size xuống 'medium' hoặc 'small'.")
            return {"success": False, "text": "", "error": str(e)}
            
    def get_system_status(self):
        """Trả về trạng thái hiện tại của service"""
        return {
            'available': WHISPER_AVAILABLE,
            'model_loaded': self.model is not None,
            'device': self.device,
            'model_size': self.model_size,
            'compute_type': self.compute_type
        }

class TextToSpeechService:
    def __init__(self):
        self.available = GTTS_AVAILABLE
        if self.available:
            logger.info("✅ Text-to-Speech service (gTTS) initialized")
        else:
            logger.warning("⚠️ gTTS not installed. Text-to-Speech disabled.")
    
    def text_to_audio_base64(self, text, lang='vi', slow=False):
        """
        Chuyển text sang audio và trả về base64 (để play trên frontend)
        """
        if not self.available:
            return None
            
        try:
            import io
            import base64
            
            # Tạo file audio trong bộ nhớ
            mp3_fp = io.BytesIO()
            tts = gTTS(text=text, lang=lang, slow=slow)
            tts.write_to_fp(mp3_fp)
            
            # Chuyển sang base64
            mp3_fp.seek(0)
            audio_base64 = base64.b64encode(mp3_fp.read()).decode('utf-8')
            return audio_base64
            
        except Exception as e:
            logger.error(f"Error in TTS: {e}")
            return None
    
    def get_system_status(self):
        return {
            'available': self.available,
            'supported_languages': ['vi', 'en']
        }