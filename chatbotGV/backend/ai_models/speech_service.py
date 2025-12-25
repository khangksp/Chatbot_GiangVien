import os
import logging
import time
import base64
import tempfile
import gc
from pathlib import Path
from typing import Optional, Dict, Any

# Logger
logger = logging.getLogger(__name__)

# TTS Imports (Giữ nguyên)
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# -------------------------------------------------------------------------
# STT Imports: Sử dụng Hugging Face Transformers thay vì faster-whisper
# -------------------------------------------------------------------------
try:
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logger.warning("⚠️ 'transformers' or 'torch' not installed. Speech-to-text disabled.")

# -------------------------------------------------------------------------
class SpeechToTextService:
    def __init__(self):
        self.pipe = None
        self.model_id = "openai/whisper-large-v3" # Model chuẩn từ OpenAI
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        
        self.supported_formats = ['.wav', '.mp3', '.m4a', '.ogg', '.flac']
        self.max_file_size_mb = 50

    def _ensure_model_loaded(self):
        """Lazy loading model"""
        if self.pipe is None and TRANSFORMERS_AVAILABLE:
            self._load_pipeline()

    def _load_pipeline(self):
        try:
            logger.info(f"🚀 Loading Whisper '{self.model_id}' via Transformers on {self.device.upper()}...")
            
            # 1. Load Model
            model = AutoModelForSpeechSeq2Seq.from_pretrained(
                self.model_id, 
                torch_dtype=self.torch_dtype, 
                low_cpu_mem_usage=True, 
                use_safetensors=True
            )
            model.to(self.device)

            # 2. Load Processor
            processor = AutoProcessor.from_pretrained(self.model_id)

            # 3. Create Pipeline
            # chunk_length_s=30: Cắt nhỏ audio để xử lý file dài không bị OOM
            self.pipe = pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                max_new_tokens=128,
                chunk_length_s=30, 
                batch_size=16, 
                return_timestamps=False, # Tắt timestamp để return text thuần
                torch_dtype=self.torch_dtype,
                device=self.device,
            )
            
            logger.info("✅ HuggingFace Whisper Pipeline loaded successfully!")

        except Exception as e:
            logger.error(f"❌ Failed to load Transformers Pipeline: {e}")
            self.pipe = None

    def is_available(self) -> bool:
        return TRANSFORMERS_AVAILABLE
    
    def validate_audio_file(self, file_path: str) -> Dict[str, Any]:
        try:
            path = Path(file_path)
            if not path.exists():
                return {"valid": False, "error": "File not found"}
            if path.suffix.lower() not in self.supported_formats:
                return {"valid": False, "error": "Unsupported format"}
            return {"valid": True}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def transcribe_audio(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """Core function compatible with existing views"""
        start_time = time.time()

        # 1. Check & Load
        if not self.is_available():
            return {"success": False, "error": "Transformers library missing", "text": ""}
        
        if self.pipe is None:
            self._ensure_model_loaded()
            if self.pipe is None:
                return {"success": False, "error": "Model failed to load", "text": ""}

        # 2. Validate
        val = self.validate_audio_file(file_path)
        if not val["valid"]:
            return {"success": False, "error": val["error"], "text": ""}

        # 3. Transcribe
        try:
            logger.info(f"🎤 Transcribing file: {file_path}")
            
            # generate_kwargs force tiếng Việt
            result = self.pipe(
                str(file_path), 
                generate_kwargs={"language": "vietnamese", "task": "transcribe"}
            )
            
            final_text = result["text"].strip() if result else ""

            if not final_text:
                return {"success": False, "error": "No speech detected", "text": ""}

            duration = time.time() - start_time
            logger.info(f"✅ Transcribed in {duration:.2f}s: {final_text[:50]}...")

            return {
                "success": True,
                "text": final_text,
                "processing_time": duration,
                "method": "transformers_pipeline"
            }

        except Exception as e:
            logger.error(f"❌ Transcription Error: {e}")
            # Nếu OOM (tràn VRAM), thử clear cache
            if "CUDA out of memory" in str(e):
                torch.cuda.empty_cache()
                gc.collect()
            return {"success": False, "error": str(e), "text": ""}

    def transcribe_audio_data(self, audio_data: bytes, format: str = "wav") -> Dict[str, Any]:
        """Helper for in-memory files (used by views.py)"""
        with tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name
        try:
            return self.transcribe_audio(tmp_path)
        finally:
            try: os.unlink(tmp_path)
            except: pass

    def get_system_status(self) -> Dict[str, Any]:
        return {
            "available": self.is_available(),
            "model_loaded": self.pipe is not None,
            "engine": "HuggingFace Transformers",
            "device": self.device
        }

# -------------------------------------------------------------------------
# TTS Service (Giữ nguyên vì đã ổn định)
# -------------------------------------------------------------------------
class TextToSpeechService:
    def __init__(self):
        self.is_available = GTTS_AVAILABLE
        self.speed_control = PYDUB_AVAILABLE
        self.lang = "vi"
        self.speed = 1.2
    
    def text_to_audio_base64(self, text: str, language: str = None, speed_multiplier: float = None) -> Optional[str]:
        if not self.is_available or not text: return None
        try:
            tts = gTTS(text=text, lang=language or self.lang, slow=False)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                fname = tmp.name
            tts.save(fname)
            
            if self.speed_control and (speed_multiplier or self.speed) != 1.0:
                try:
                    sound = AudioSegment.from_mp3(fname)
                    sound = sound.speedup(playback_speed=speed_multiplier or self.speed)
                    sound.export(fname, format="mp3")
                except: pass
                
            with open(fname, 'rb') as f:
                data = base64.b64encode(f.read()).decode('utf-8')
            return data
        except Exception as e:
            logger.error(f"TTS Error: {e}")
            return None
        finally:
            if 'fname' in locals():
                try: os.unlink(fname) 
                except: pass

    def get_system_status(self) -> Dict[str, Any]:
        return {"available": self.is_available}