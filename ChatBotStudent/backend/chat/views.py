import jwt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse
from knowledge.models import ChatHistory, UserFeedback
from authentication.models import Faculty
from typing import Optional

# ✅ SAFE IMPORTS - with fallbacks
try:
    from ai_models.chatbot_logic.chatbot_service import chatbot_ai
except ImportError:
    chatbot_ai = None

try:
    # Import Class thay vì instance
    from ai_models.speech_service import SpeechToTextService, TextToSpeechService
    speech_service = SpeechToTextService() # Khởi tạo tại đây
    tts_service = TextToSpeechService()
except ImportError:
    speech_service = None
    tts_service = None

try:
    from ai_models.ocr_service import ocr_service
except ImportError:
    ocr_service = None

# 🚀 NEW: Import training module with fallback
try:
    from ai_models.train_retriever import run_training, check_gpu_availability
    TRAINING_AVAILABLE = True
except ImportError:
    run_training = None
    check_gpu_availability = None
    TRAINING_AVAILABLE = False

import uuid
import time
import logging
import json
import tempfile
import os
import base64
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone
from django.db import models
import threading
from datetime import datetime

from rest_framework.permissions import IsAuthenticated, AllowAny

logger = logging.getLogger(__name__)

# 🚀 NEW: Global variable to track training status
TRAINING_STATUS = {
    'is_running': False,
    'started_at': None,
    'completed_at': None,
    'success': None,
    'error': None,
    'progress': 0,
    'output_dir': None,
    'training_examples': 0,
    'evaluation_results': None
}

def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

#
# --- XÓA TOÀN BỘ HÀM `_save_chat_history_sync` KHỎI FILE NÀY --- 
# (Vì chúng ta sẽ gọi hàm của chatbot_ai.save_chat_history() thay vì duplicate logic)
#

def extract_jwt_token(request):
    """
    Extract JWT token from request headers or data (robust)
    Returns: raw token string (no 'Bearer ' prefix) or None
    """
    try:
        # 1) DRF headers (case-insensitive)
        auth_header = ''
        try:
            auth_header = request.headers.get('Authorization', '')  # DRF provides this normalized mapping
            logger.info(f"🔍 DRF Authorization header: '{auth_header}'")
        except Exception:
            pass

        if not auth_header:
            # 2) WSGI META fallback
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            logger.info(f"🔍 META Authorization header: '{auth_header}'")

        if isinstance(auth_header, bytes):
            auth_header = auth_header.decode('utf-8', errors='ignore')
        auth_val = (auth_header or '').strip()

        # Normalize prefixes: Bearer / bearer / Token
        if auth_val:
            lower = auth_val.lower()
            if lower.startswith('bearer '):
                token = auth_val[7:].strip().strip('"').strip("'")
                logger.info(f"🔑 JWT token found in Authorization header (Bearer)")
                return token
            if lower.startswith('token '):
                token = auth_val[6:].strip().strip('"').strip("'")
                logger.info(f"🔑 JWT token found in Authorization header (Token)")
                return token

        # 3) Body: request.data
        if hasattr(request, 'data'):
            body_token = (request.data.get('token') or '').strip()
            if body_token:
                logger.info(f"🔑 JWT token found in request data")
                return body_token

        # 4) Body raw JSON
        if hasattr(request, 'body') and request.body:
            try:
                body_str = request.body.decode('utf-8') if isinstance(request.body, bytes) else str(request.body)
                body_json = json.loads(body_str)
                body_token = (body_json.get('token') or '').strip()
                if body_token:
                    logger.info(f"🔑 JWT token found in JSON body")
                    return body_token
            except Exception:
                pass

        # 5) Query string (testing only)
        qs_token = (request.GET.get('token') or '').strip()
        if qs_token:
            logger.info(f"🔑 JWT token found in query parameters")
            return qs_token

        logger.info("🔑 No JWT token found in request")
        return None
    except Exception as e:
        logger.error(f"❌ Error extracting JWT token (robust): {e}")
        return None

def validate_jwt_token_format(token):
    """
    Basic validation of JWT token format
    Returns: (is_valid, error_message)
    """
    if not token:
        return False, "Token is empty"
    
    if not isinstance(token, str):
        return False, "Token must be a string"
    
    # Remove Bearer prefix if present
    if token.startswith('Bearer '):
        token = token[7:]
    
    # JWT should have 3 parts separated by dots
    parts = token.split('.')
    if len(parts) != 3:
        return False, f"Invalid JWT format - expected 3 parts, got {len(parts)}"
    
    # Each part should be base64 encoded (basic check)
    try:
        import base64
        for i, part in enumerate(parts[:2]):  # Don't check signature part
            # Add padding if needed
            padded = part + '=' * (4 - len(part) % 4)
            base64.b64decode(padded)
    except Exception as e:
        return False, f"Invalid base64 encoding in JWT: {str(e)}"
    
    return True, "Valid JWT format"

def auto_setup_user_context_from_jwt(session_id: str, jwt_token: str):
    """
    🚀 AUTO-SETUP user context từ JWT token để đảm bảo personal addressing
    """
    try:
        # Import external_api_service
        from ai_models.external_api_service import external_api_service
        
        # Chỉ hỗ trợ sinh viên
        logger.info("ℹ️ JWT Auto-setup: Chỉ hỗ trợ sinh viên")
        return False
            
    except Exception as e:
        logger.error(f"❌ Error auto-setup user context from JWT: {str(e)}")
        return False

# 🚀 NEW: Training functions
def run_training_background(csv_path=None, output_dir='./fine_tuned_phobert'):
    """Run training in background thread"""
    global TRAINING_STATUS
    
    try:
        TRAINING_STATUS.update({
            'is_running': True,
            'started_at': datetime.now().isoformat(),
            'progress': 0,
            'error': None,
            'success': None
        })
        
        logger.info("🚀 Starting PhoBERT fine-tuning in background...")
        
        if not TRAINING_AVAILABLE or not run_training:
            raise Exception("Training module not available")
        
        # Run the actual training
        TRAINING_STATUS['progress'] = 25
        result = run_training(csv_path, output_dir)
        TRAINING_STATUS['progress'] = 90
        
        if result and result.get('success'):
            TRAINING_STATUS.update({
                'success': True,
                'completed_at': datetime.now().isoformat(),
                'progress': 100,
                'output_dir': result.get('output_dir'),
                'training_examples': result.get('training_examples', 0),
                'evaluation_results': result.get('evaluation_results')
            })
            
            # 🚀 CRITICAL: Reload the chatbot with new model
            if chatbot_ai and hasattr(chatbot_ai, 'reload_after_qa_update'):
                logger.info("🔄 Reloading chatbot with fine-tuned model...")
                chatbot_ai.reload_after_qa_update()
                logger.info("✅ Chatbot reloaded with fine-tuned model")
            
            logger.info("✅ Background training completed successfully!")
            
        else:
            error_msg = result.get('error', 'Unknown training error') if result else 'Training function returned None'
            raise Exception(error_msg)
            
    except Exception as e:
        logger.error(f"❌ Background training failed: {str(e)}")
        TRAINING_STATUS.update({
            'success': False,
            'error': str(e),
            'completed_at': datetime.now().isoformat(),
            'progress': 0,
            'is_running': False
        })
    finally:
        TRAINING_STATUS['is_running'] = False

# ✅ SAFE SYSTEM STATUS FUNCTIONS
def get_safe_system_status():
    """Get system status with safe fallbacks"""
    try:
        if chatbot_ai:
            return chatbot_ai.get_system_status()
    except Exception as e:
        logger.error(f"Error getting chatbot_ai status: {e}")
    
    return {
        'ai_service': {
            'available': False,
            'error': 'AI service not available'
        },
        'status': 'limited'
    }

def get_safe_speech_status():
    """Get speech status with safe fallbacks"""
    try:
        if speech_service:
            return speech_service.get_system_status()
    except Exception as e:
        logger.error(f"Error getting speech status: {e}")
    
    return {
        'available': False,
        'error': 'Speech service not available'
    }

def get_safe_tts_status():
    """Get TTS status with safe fallbacks"""
    try:
        if tts_service:
            return tts_service.get_system_status()
    except Exception as e:
        logger.error(f"Error getting TTS status: {e}")
    
    return {
        'available': False,
        'error': 'TTS service not available'
    }
class APIRootView(APIView):
    """API Root - Hiển thị danh sách endpoints"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        test_memory = request.GET.get('test_memory')
        if test_memory and chatbot_ai:
            try:
                memory = chatbot_ai.get_conversation_memory(test_memory)
                return Response({
                    'memory_test': True,
                    'session_id': test_memory,
                    'memory': memory,
                    'total_sessions': len(chatbot_ai.response_generator.memory.conversations) if hasattr(chatbot_ai, 'response_generator') else 0
                })
            except Exception as e:
                return Response({
                    'memory_test': True,
                    'error': str(e)
                })
        
        system_status = get_safe_system_status()
        speech_status = get_safe_speech_status()
        tts_status = get_safe_tts_status()
        
        # ✅ SAFE: External API status check
        external_api_status = {'external_api_service': {'available': False, 'error': 'Service not available'}}
        try:
            from ai_models.external_api_service import external_api_service
            external_api_status = external_api_service.get_system_status()
        except ImportError:
            pass
        except Exception as e:
            logger.error(f"Error getting external API status: {e}")

        # ✅ SAFE: Personalization status with fallbacks
        personalization_status = {
            'enabled': True,
            'active_personalized_sessions': 0,
            'user_memory_prompt_support': True,
            'flexible_personalization': True,
            'external_api_integration': external_api_status.get('external_api_service', {}).get('available', False),
            'jwt_token_support': True,
            'student_schedule_access': True
        }
        
        try:
            if chatbot_ai and hasattr(chatbot_ai, 'response_generator'):
                personalization_status['active_personalized_sessions'] = len(chatbot_ai.response_generator._user_context_cache)
        except Exception as e:
            logger.error(f"Error getting personalization stats: {e}")
        
        # 🚀 NEW: Training status
        training_status = {
            'training_available': TRAINING_AVAILABLE,
            'training_endpoint': '/api/train-retriever/',
            'current_training_status': dict(TRAINING_STATUS) if TRAINING_AVAILABLE else None
        }
        
        return Response({
            'message': 'Enhanced Chatbot API với Text-to-Speech và Fine-tuned Model Training - Đại học Bình Dương',
            'version': '6.2.0',  # 🚀 Updated version
            'status': 'active',
            'system_status': system_status,
            'speech_status': speech_status,
            'tts_status': tts_status,
            'personalization_status': personalization_status,
            'external_api_status': external_api_status,
            'training_status': training_status,  # 🚀 NEW
            'endpoints': {
                'chat': '/api/chat/',
                'health': '/api/health/',
                'history': '/api/history/',
                'feedback': '/api/feedback/',
                'speech_to_text': '/api/speech-to-text/',
                'speech_status': '/api/speech-status/',
                'personalized_context': '/api/personalized-context/',
                'personalized_status': '/api/personalized-status/',
                'train_retriever': '/api/train-retriever/',  # 🚀 NEW
            },
            'features': [
                'Natural Language Generation',
                'Intent Classification',
                'Conversation Memory',
                'Emotional Context',
                'UTF-8 Safe Encoding',
                'Speech-to-Text (Whisper)',
                'Text-to-Speech (gTTS)',
                'Voice Conversation Mode',
                'Enhanced Personalization',
                'User Memory Prompt Support',
                'Flexible Personalization',
                'Dynamic System Prompts',
                'Custom User Instructions',
                'User Memory Integration',
                'Department-Specific Responses',
                'JWT Token Authentication',
                'External API Integration',
                'Lecturer Schedule Access',
                'Personal Information Queries',
                'Fine-tuned Model Training',  # 🚀 NEW
                'Two-Stage Re-ranking',  # 🚀 NEW
                'Advanced RAG Architecture',  # 🚀 NEW
            ]
        })

class HealthCheckView(APIView):
    """
    ✅ SAFE Health check endpoint - Always works regardless of AI services
    """
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            # Basic health check that always works
            health_data = {
                'status': 'healthy',
                'message': 'BDU ChatBot API is running! 🚀',
                'timestamp': timezone.now().isoformat(),
                'database': 'connected',
                'encoding': 'utf-8',
                'version': '6.2.0'  # 🚀 Updated version
            }
            
            # ✅ SAFE: Add service status only if available
            try:
                health_data['system_status'] = get_safe_system_status()
                health_data['speech_status'] = get_safe_speech_status()
                health_data['tts_status'] = get_safe_tts_status()
                
                # Voice interaction capability
                speech_available = health_data['speech_status'].get('available', False)
                tts_available = health_data['tts_status'].get('available', False)
                
                health_data['voice_interaction'] = {
                    'stt_available': speech_available,
                    'tts_available': tts_available,
                    'full_voice_chat': speech_available and tts_available
                }
                
                health_data['personalization'] = 'enabled'
                
                # 🚀 NEW: Training capability
                health_data['training_capability'] = {
                    'available': TRAINING_AVAILABLE,
                    'current_status': TRAINING_STATUS['is_running'],
                    'fine_tuned_model_support': True
                }
                
            except Exception as e:
                logger.error(f"Error getting service status in health check: {e}")
                health_data['services_status'] = 'limited'
                health_data['services_error'] = str(e)
            
            return Response(health_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Health check failed: {str(e)}")
            return Response({
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Health check encountered an error',
                'timestamp': timezone.now().isoformat()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ChatView(APIView):
    """Enhanced Chat API with Natural Responses and TTS"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """GET method - API information with personalization and TTS"""
        try:
            system_status = get_safe_system_status()
            speech_status = get_safe_speech_status()
            tts_status = get_safe_tts_status()
            
            # ✅ SAFE: External API status
            external_api_status = {'external_api_service': {'available': False, 'error': 'Service not available'}}
            try:
                from ai_models.external_api_service import external_api_service
                external_api_status = external_api_service.get_system_status()
            except:
                pass
            
            # ✅ SAFE: User personalization
            user_personalization = None
            if request.user.is_authenticated:
                try:
                    user_personalization = {
                        'faculty_code': getattr(request.user, 'faculty_code', 'N/A'),
                        'full_name': getattr(request.user, 'full_name', 'N/A'),
                        'department': getattr(request.user, 'department', 'N/A'),
                        'position': getattr(request.user, 'position', 'N/A'),
                        'has_user_memory_prompt': bool(getattr(request.user, 'chatbot_preferences', {}).get('user_memory_prompt', '').strip()),
                        'memory_length': len(getattr(request.user, 'chatbot_preferences', {}).get('user_memory_prompt', '')),
                        'department_priority': getattr(request.user, 'chatbot_preferences', {}).get('department_priority', True),
                        'personalized_prompt_available': True
                    }
                except Exception as e:
                    logger.error(f"Error getting user personalization: {e}")
            
            return Response({
                'message': 'Enhanced Personalized Chat API với Text-to-Speech và Fine-tuned Training - Open Access',
                'authentication': 'Optional - Works with or without token',
                'jwt_token_support': 'Send JWT token for personal schedule/info access',
                'system_status': system_status,
                'speech_status': speech_status,
                'tts_status': tts_status,
                'external_api_status': external_api_status,
                'user_personalization': user_personalization,
                'method': 'POST để gửi tin nhắn với personalization, JWT token và TTS',
                'jwt_token_usage': {
                    'header': 'Authorization: Bearer <token>',
                    'body_field': 'token',
                    'query_param': 'token (for testing only)',
                    'purpose': 'Access personal schedule and student information'
                },
                'tts_usage': {
                    'mode_field': 'mode',
                    'voice_mode': 'voice - Tạo audio từ response text',
                    'text_mode': 'text - Chỉ trả về text (default)',
                    'audio_format': 'MP3 encoded as base64 string',
                    'supported_languages': tts_status.get('supported_languages', ['vi', 'en'])
                },
                'features': [
                    'PhoBERT Intent Classification',
                    'SBERT + FAISS Retrieval',
                    'Fine-tuned Model Support',  # 🚀 NEW
                    'Two-Stage Re-ranking',  # 🚀 NEW
                    'Advanced RAG Architecture',  # 🚀 NEW
                    'Conversation Memory',
                    'UTF-8 Safe Processing',
                    'Speech-to-Text Integration',
                    'Text-to-Speech Integration',
                    'Voice Conversation Mode',
                    'User Memory Prompt Support (with authentication)',
                    'Dynamic Personalized System Prompts (with authentication)',
                    'Flexible User Instructions (with authentication)',
                    'User Memory Integration (with authentication)',
                    'Anonymous Chat Support',
                    'JWT Token Authentication',
                    'External API Integration',
                    'Personal Schedule Access',
                    'Lecturer Information Queries',
                    'Model Training Capability'  # 🚀 NEW
                ]
            })
        except Exception as e:
            logger.error(f"Error in ChatView GET: {e}")
            return Response({
                'error': 'Chat API information not available',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        """POST method - Process chat with enhanced personalization support and TTS"""
        start_time = time.time()
        logger.info("=== /api/chat HIT ===")
        logger.info("Headers: %s", dict(request.headers))
        logger.info("Body: %s", request.body.decode("utf-8", errors="ignore"))
        
        try:
            # Get and validate input
            user_message = request.data.get('message', '').strip()
            session_id = request.data.get('session_id', str(uuid.uuid4()))
            request_mode = request.data.get('mode', 'text').lower()
            
            logger.info(f"🎯 Request mode: {request_mode}")
            
            # ✅ NEW: Xử lý file tài liệu đính kèm (OCR)
            document_text = None
            document_file = request.FILES.get('document') # Frontend sẽ gửi file với key là 'document'
            if document_file and ocr_service:
                logger.info(f"📄 Document file received: {document_file.name}")
                # Lưu file tạm thời để xử lý
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(document_file.name)[1]) as tmp_file:
                    for chunk in document_file.chunks():
                        tmp_file.write(chunk)
                    tmp_file_path = tmp_file.name
                
                try:
                    # Gọi OCR service để đọc file
                    pages_data = ocr_service.read_document(tmp_file_path)
                    if pages_data:
                        # Ghép nối text từ tất cả các trang
                        document_text = "\n\n".join([page['text'] for page in pages_data if page['text'].strip()])
                        logger.info(f"✅ OCR extracted {len(document_text)} characters.")
                    else:
                        logger.error("❌ OCR failed to extract text from document.")
                finally:
                    # Luôn xóa file tạm sau khi xử lý xong
                    os.unlink(tmp_file_path)
            elif document_file and not ocr_service:
                logger.error("❌ Document received, but OCR service is not available.")
            
            # Extract JWT token
            jwt_token = extract_jwt_token(request)
            logger.info(f"🔑 JWT Token extracted: {jwt_token[:20] if jwt_token else 'None'}...")
            
            # =============================================================================
            # ⛔️ ĐÃ XÓA TOÀN BỘ KHỐI "STUDENT SUPPORT" (từ if jwt_token: đến hết luồng fallback)
            # Lý do: Tránh short-circuit. Bây giờ JWT sẽ được pass vào process_query để routing đúng.
            # =============================================================================
            
            if jwt_token:
                is_valid_format, format_message = validate_jwt_token_format(jwt_token)
                logger.info(f"🔑 JWT Token received: format_valid={is_valid_format}, message='{format_message}'")
                
                # 🚀 CRITICAL FIX: Auto-setup user context từ JWT
                if is_valid_format:
                    logger.info("🔧 Setting up user context from JWT token...")
                    setup_success = auto_setup_user_context_from_jwt(session_id, jwt_token)
                    if setup_success:
                        logger.info("✅ JWT auto-setup completed successfully")
                    else:
                        logger.warning("⚠️ JWT auto-setup failed")
                else:
                    logger.warning(f"⚠️ Invalid JWT format: {format_message}")
            else:
                logger.info("🔑 No JWT token provided - using standard QA mode")
            
            # Get user context (existing logic - keep as backup)
            user_id = request.user.id if request.user.is_authenticated else None
            user_context = None
            personalization_info = {}
            
            if user_id and request.user.is_authenticated:
                try:
                    if hasattr(request.user, 'get_chatbot_context'):
                        user_context = request.user.get_chatbot_context()
                    
                    # Extract personalization info
                    personalization_info = {
                        'department_priority': getattr(request.user, 'chatbot_preferences', {}).get('department_priority', True),
                        'department': getattr(request.user, 'department', 'Unknown'),
                        'position': getattr(request.user, 'position', 'Unknown'),
                        'has_user_memory_prompt': bool(getattr(request.user, 'chatbot_preferences', {}).get('user_memory_prompt', '').strip()),
                        'memory_length': len(getattr(request.user, 'chatbot_preferences', {}).get('user_memory_prompt', '')),
                        'personalized_prompt_available': True
                    }
                    
                    logger.info(f"👤 USER CONTEXT: {user_context.get('role_description', 'Unknown') if user_context else 'None'}")
                    
                    # 🚀 ADDITIONAL: Set authenticated user context as backup
                    if user_context and chatbot_ai and hasattr(chatbot_ai, 'response_generator'):
                        chatbot_ai.response_generator.set_user_context(session_id, user_context)
                        logger.info("✅ Authenticated user context also set as backup")
                    
                except Exception as e:
                    logger.warning(f"Could not get enhanced user context: {e}")
                    personalization_info['error'] = str(e)
            
            # ✅ CRITICAL: Nếu có file upload nhưng không có tin nhắn, tạo tin nhắn mặc định
            if document_text and not user_message:
                user_message = f"Dựa vào nội dung tài liệu này ({document_file.name}), hãy tóm tắt ý chính."
                logger.info(f"📝 No user message, generated default query: '{user_message}'")
            
            if not user_message:
                return Response(
                    {'error': 'Tin nhắn không được để trống'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if len(user_message) > 1000:
                return Response(
                    {'error': 'Tin nhắn quá dài (tối đa 1000 ký tự)'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # ENSURE UTF-8 encoding
            try:
                user_message = user_message.encode('utf-8').decode('utf-8')
            except UnicodeError:
                user_message = user_message.encode('utf-8', errors='ignore').decode('utf-8')
            
            logger.info(f"💬 Processing message: {user_message[:50]}... (User: {user_context.get('faculty_code') if user_context else 'Anonymous'}, JWT: {bool(jwt_token)}, Mode: {request_mode})")

            # ✅ SAFE: Process with AI service if available (BÂY GIỜ LUÔN ĐƯỢC GỌI, KHÔNG BỊ BỎ QUA)
            ai_response = None
            if chatbot_ai:
                try:
                    # 🚀 ALWAYS call process_query with JWT token for auto-detection
                    # (Nó sẽ tự handle student routing, Agent/Legacy switch)
                    ai_response = chatbot_ai.process_query(user_message, session_id, jwt_token, document_text=document_text)
                    logger.info("✅ process_query called successfully - full pipeline executed")
                    
                except Exception as e:
                    logger.error(f"Error processing with AI service: {e}")
            
            # Fallback response if AI service fails
            if not ai_response:
                ai_response = {
                    'response': self._get_fallback_response(user_message, user_context, personalization_info, jwt_token, request_mode),
                    'confidence': 0.3,
                    'method': 'fallback',
                    'sources': [],
                    'reference_links': [],
                    'user_memory_prompt_used': False,
                    'external_api_used': False,
                    'decision_type': 'fallback'
                }
            
            # ENSURE UTF-8 safe response
            response_text = ai_response['response']
            try:
                response_text = response_text.encode('utf-8').decode('utf-8')
            except UnicodeError:
                response_text = response_text.encode('utf-8', errors='ignore').decode('utf-8')
            
            # Clean response text
            response_text = self._clean_response_text(response_text)
            
            # ✅ SAFE: TTS processing if requested and available
            audio_content_base64 = None
            tts_processing_time = 0
            tts_error = None
            
            if request_mode == 'voice' and response_text and tts_service:
                logger.info("🔊 Voice mode detected. Generating TTS response...")
                tts_start_time = time.time()
                
                try:
                    if hasattr(tts_service, 'text_to_audio_base64'):
                        audio_content_base64 = tts_service.text_to_audio_base64(response_text)
                        tts_processing_time = time.time() - tts_start_time
                        
                        if audio_content_base64:
                            logger.info(f"✅ TTS audio generated successfully in {tts_processing_time:.2f}s")
                        else:
                            logger.warning("⚠️ TTS audio generation failed - no audio returned")
                            tts_error = "TTS service returned no audio"
                    else:
                        tts_error = "TTS service method not available"
                        
                except Exception as e:
                    tts_processing_time = time.time() - tts_start_time
                    tts_error = str(e)
                    logger.error(f"❌ TTS audio generation failed: {e}")
            elif request_mode == 'voice' and not tts_service:
                logger.warning("⚠️ Voice mode requested but TTS service not available")
                tts_error = "TTS service not available"
            elif request_mode == 'voice':
                logger.warning("⚠️ Voice mode requested but no response text available")
                tts_error = "No response text available for TTS"
            else:
                logger.info(f"📝 Text mode - no TTS processing (mode: {request_mode})")
            
            processing_time = time.time() - start_time
            
            # --- XÓA BỎ LOGIC LƯU LỊCH SỬ Ở ĐÂY ---
            # (Vì `chatbot_service.py` đã tự động lưu lịch sử trong `process_query` rồi.
            #  Và `student_api` (Luồng 1) cũng đã được lưu ở trên với `chatbot_ai.save_chat_history()`)
            # ---
            
            # Debug headers if requested
            debug = request.query_params.get('debug') == '1'
            extra_debug = {}
            if debug:
                extra_debug = {
                    'received_headers': dict(request.headers),
                    'request_meta_keys': list(request.META.keys()),
                    'http_authorization': request.META.get('HTTP_AUTHORIZATION', 'NOT_FOUND'),
                    'token_preview': (jwt_token[:25] + '...') if jwt_token else None,
                    'token_full': jwt_token if jwt_token else None,
                }
            
            return Response({
                'session_id': session_id,
                'response': response_text,
                'confidence': ai_response['confidence'],
                'method': ai_response.get('method', 'hybrid'),
                'intent': ai_response.get('intent', {}).get('intent', 'general'),
                'sources': ai_response.get('sources', []),
                'response_time': processing_time,
                'status': 'success',
                'encoding': 'utf-8',
                'reference_links': ai_response.get('reference_links', []),  # ✅ PRESERVED
                
                # TTS fields
                'audio_content': audio_content_base64,
                'mode': request_mode,
                'tts_info': {
                    'enabled': request_mode == 'voice',
                    'processing_time': tts_processing_time,
                    'success': bool(audio_content_base64),
                    'error': tts_error,
                    'audio_format': 'mp3_base64' if audio_content_base64 else None
                },
                
                # 🚀 ENHANCED: Personalization info với JWT auto-setup
                'personalization': {
                    'enabled': bool(user_context) or bool(jwt_token and is_valid_format if 'is_valid_format' in locals() else False),
                    'jwt_auto_setup': jwt_token and (is_valid_format if 'is_valid_format' in locals() else False),  # 🚀 NEW
                    'user_info': {
                        'department': personalization_info.get('department'),
                        'position': personalization_info.get('position'),
                        'faculty_code': user_context.get('faculty_code') if user_context else None
                    } if user_context else None,
                    'user_memory_info': {
                        'has_user_memory_prompt': personalization_info.get('has_user_memory_prompt', False),
                        'memory_length': personalization_info.get('memory_length', 0),
                        'memory_applied': ai_response.get('user_memory_prompt_used', False)
                    } if user_context else None,
                    'department_priority_used': personalization_info.get('department_priority', False)
                },
                
                # External API information
                'external_api': {
                    'jwt_token_provided': bool(jwt_token),
                    'jwt_format_valid': is_valid_format if 'is_valid_format' in locals() and jwt_token else None,  # 🚀 NEW
                    'external_api_used': ai_response.get('external_api_used', False),
                    'decision_type': ai_response.get('decision_type', ''),
                    'method_used': ai_response.get('method', ''),
                    'personal_info_accessed': ai_response.get('external_api_used', False),
                    'token_valid_format': validate_jwt_token_format(jwt_token)[0] if jwt_token else None
                },
                
                # 🚀 NEW: Advanced RAG information
                'advanced_rag': {
                    'two_stage_reranking_used': ai_response.get('two_stage_reranking_used', False),
                    'fine_tuned_model_used': ai_response.get('fine_tuned_model_used', False),
                    'confidence_capped': ai_response.get('confidence_capped', False),
                    'reranking_stats': ai_response.get('reranking_stats', {}),
                    'enhanced_processing': True
                },
                
                # Debug information
                **extra_debug
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Chat error: {str(e)}")
            
            fallback_response = self._get_fallback_response(
                locals().get('user_message', ''),
                locals().get('user_context'),
                locals().get('personalization_info', {}),
                locals().get('jwt_token'),
                locals().get('request_mode', 'text')
            )
            
            return Response({
                'session_id': locals().get('session_id', str(uuid.uuid4())),
                'response': fallback_response,
                'confidence': 0.3,
                'method': 'fallback',
                'response_time': time.time() - start_time,
                'status': 'fallback',
                'audio_content': None,
                'mode': locals().get('request_mode', 'text'),
                'tts_info': {
                    'enabled': False,
                    'processing_time': 0,
                    'success': False,
                    'error': 'Fallback mode - TTS disabled',
                    'audio_format': None
                },
                'personalization': {
                    'enabled': bool(locals().get('user_context')),
                    'jwt_auto_setup': False,  # 🚀 NEW
                    'fallback_used': True,
                    'error': str(e)
                },
                'external_api': {
                    'jwt_token_provided': bool(locals().get('jwt_token')),
                    'jwt_format_valid': None,  # 🚀 NEW
                    'external_api_used': False,
                    'fallback_used': True,
                    'error': str(e)
                },
                'advanced_rag': {  # 🚀 NEW
                    'two_stage_reranking_used': False,
                    'fine_tuned_model_used': False,
                    'confidence_capped': False,
                    'fallback_used': True
                }
            }, status=status.HTTP_200_OK)
    
    def _get_fallback_response(self, user_message='', user_context=None, personalization_info={}, jwt_token=None, request_mode='text'):
        """Enhanced fallback response"""
        if user_context:
            full_name = user_context.get('full_name', '')
            faculty_code = user_context.get('faculty_code', '')
            name_suffix = full_name.split()[-1] if full_name else faculty_code
            personal_address = f"thầy/cô {name_suffix}"
            department_name = user_context.get('department_name', 'BDU')
            
            if jwt_token:
                base_message = f"""Dạ xin lỗi {personal_address}, hệ thống đang được nâng cấp để phục vụ {personal_address} tốt hơn.

Mặc dù em đã nhận được thông tin đăng nhập của {personal_address}, nhưng hiện tại có một số khó khăn kỹ thuật. 

{personal_address} có thể:
• Thử lại sau vài phút ⏰
• Truy cập trực tiếp hệ thống quản lý đào tạo của trường 🌐
• Liên hệ khoa {department_name} để được hỗ trợ trực tiếp 📞
• Gọi bộ phận IT: 0274.xxx.xxxx 📧

Em sẽ cố gắng khắc phục để phục vụ {personal_address} tốt hơn! 🎓✨"""
            else:
                has_user_memory = personalization_info.get('has_user_memory_prompt', False)
                
                if has_user_memory:
                    base_message = f"""Dạ xin lỗi {personal_address}, hệ thống đang được cải thiện để phục vụ {personal_address} tốt hơn theo những yêu cầu riêng mà {personal_address} đã thiết lập! 🧠

Để truy cập thông tin cá nhân như lịch giảng dạy, {personal_address} cần đăng nhập vào ứng dụng BDU trước ạ. 🔐

Trong thời gian này, {personal_address} có thể:
• Liên hệ trực tiếp khoa {department_name} 📞
• Gọi tổng đài: 0274.xxx.xxxx  
• Email: info@bdu.edu.vn 📧
• Website: www.bdu.edu.vn 🌐

Em sẽ cố gắng hỗ trợ {personal_address} tốt hơn theo những ghi nhớ mà {personal_address} đã cung cấp! 🎓✨"""
                else:
                    base_message = f"""Dạ xin lỗi {personal_address}, hệ thống đang được cải thiện để phục vụ {personal_address} tốt hơn.

Để truy cập thông tin cá nhân như lịch giảng dạy, {personal_address} cần đăng nhập vào ứng dụng BDU trước ạ. 🔐

Trong thời gian này, {personal_address} có thể:
• Liên hệ trực tiếp khoa {department_name}
• Gọi tổng đài: 0274.xxx.xxxx  
• Email: info@bdu.edu.vn
• Website: www.bdu.edu.vn

Cảm ơn {personal_address} đã kiên nhẫn! 🎓"""
            
            if request_mode == 'voice':
                base_message += f"\n\n🔊 Lưu ý: Chức năng chuyển văn bản thành giọng nói tạm thời không khả dụng. {personal_address} vẫn có thể đọc phản hồi này."
            
            return base_message
        
        # Fallback for non-authenticated users
        base_message = """Xin chào! Tôi đã nhận được thông tin đăng nhập, nhưng hiện tại gặp khó khăn kỹ thuật.

Bạn có thể thử lại sau hoặc liên hệ:
• Hotline: 0274.xxx.xxxx
• Email: info@bdu.edu.vn
• Website: www.bdu.edu.vn

Cảm ơn bạn đã kiên nhẫn! 🎓"""
        
        if request_mode == 'voice':
            base_message += "\n\n🔊 Lưu ý: Chức năng chuyển văn bản thành giọng nói tạm thời không khả dụng."
        
        return base_message if jwt_token else self._get_safe_fallback_response(user_message)
    
    def _clean_response_text(self, text):
        """Clean and ensure safe UTF-8 text"""
        import re
        
        # Remove control characters and invalid UTF-8
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]', '', text)
        
        # Fix common encoding issues
        encoding_fixes = {
            'â€™': "'",
            'â€œ': '"', 
            'â€': '"',
            'â€"': '-',
            'â€¦': '...',
            'Ã¡': 'á',
            'Ã ': 'à',
            'Ã¢': 'â',
            'Ã£': 'ã',
            'Ã¨': 'è',
            'Ã©': 'é',
            'Ãª': 'ê',
            'Ã¬': 'ì',
            'Ã­': 'í',
            'Ã²': 'ò',
            'Ã³': 'ó',
            'Ã´': 'ô',
            'Ã¹': 'ù',
            'Ãº': 'ú',
            'Ã½': 'ý',
            'Ä': 'đ',
            'Ä': 'Đ'
        }
        
        for wrong, correct in encoding_fixes.items():
            text = text.replace(wrong, correct)
        
        # Clean up spaces and newlines only
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()
    
    def _get_safe_fallback_response(self, user_message=''):
        """Safe fallback response with proper UTF-8"""
        return f"""Xin chào! Tôi đã nhận được câu hỏi của bạn. 

Hiện tại hệ thống đang được cải thiện để phục vụ bạn tốt hơn. Trong thời gian này, bạn có thể:

• Liên hệ trực tiếp: 0274.xxx.xxxx
• Email: info@bdu.edu.vn  
• Website: www.bdu.edu.vn

Cảm ơn bạn đã kiên nhẫn! 😊"""

# ✅ KEEP ALL EXISTING VIEWS UNCHANGED TO PRESERVE MIC/SPEECH FUNCTIONALITY

class SpeechToTextView(APIView):
    """Speech-to-Text API endpoint"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """GET method - Service information"""
        speech_status = get_safe_speech_status()
        return Response({
            'message': 'Speech-to-Text API',
            'method': 'POST để upload audio file',
            'speech_service': speech_status,
            'supported_formats': ['wav', 'mp3', 'webm', 'm4a'],
            'max_file_size_mb': 10,
            'usage': {
                'method': 'POST',
                'content_type': 'multipart/form-data',
                'fields': {
                    'audio': 'Audio file (required)',
                    'language': 'Language code (optional, default: vi)',
                    'beam_size': 'Beam size for better accuracy (optional, default: 5)'
                }
            }
        })
    
    def post(self, request):
        """POST method - Process audio file"""
        start_time = time.time()
        
        try:
            # Check if service is available
            if not speech_service:
                return Response({
                    'success': False,
                    'error': 'Speech-to-Text service not available. Service not loaded.',
                    'text': ''
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            if not hasattr(speech_service, 'is_available') or not speech_service.is_available():
                return Response({
                    'success': False,
                    'error': 'Speech-to-Text service not available. Please install faster-whisper.',
                    'text': '',
                    'status': get_safe_speech_status()
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # Check if file is in request
            if 'audio' not in request.FILES:
                return Response({
                    'success': False,
                    'error': 'No audio file provided. Please upload an audio file.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            audio_file = request.FILES['audio']
            
            # Validate file size (10MB max)
            max_size = 10 * 1024 * 1024
            if audio_file.size > max_size:
                return Response({
                    'success': False,
                    'error': f'File too large. Maximum size: 10MB'
                }, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            
            # Check minimum file size
            if audio_file.size < 1024:  # Less than 1KB
                return Response({
                    'success': False,
                    'error': 'Audio file too small. Please record longer audio.',
                    'text': ''
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get optional parameters
            language = request.data.get('language', 'vi')
            beam_size = int(request.data.get('beam_size', 5))
            
            # Save uploaded file to temporary location
            with tempfile.NamedTemporaryFile(
                delete=False, 
                suffix=os.path.splitext(audio_file.name)[1] or '.webm'
            ) as tmp_file:
                for chunk in audio_file.chunks():
                    tmp_file.write(chunk)
                tmp_file.flush()
                
                try:
                    # Process with speech service
                    if hasattr(speech_service, 'transcribe_audio'):
                        result = speech_service.transcribe_audio(
                            tmp_file.name,
                            language=language,
                            beam_size=beam_size
                        )
                    else:
                        result = {
                            'success': False,
                            'error': 'Speech service method not available',
                            'text': ''
                        }
                    
                    if result.get('success'):
                        transcribed_text = result.get('text', '').strip()
                        if not transcribed_text:
                            return Response({
                                'success': False,
                                'error': 'No speech detected in audio. Please speak louder or check microphone.',
                                'text': ''
                            }, status=status.HTTP_200_OK)
                    
                    # Add additional metadata
                    result['file_name'] = audio_file.name
                    result['file_size_mb'] = round(audio_file.size / (1024 * 1024), 2)
                    result['total_processing_time'] = time.time() - start_time
                    
                    return Response(result, status=status.HTTP_200_OK)
                    
                finally:
                    # Clean up temporary file
                    try:
                        if os.path.exists(tmp_file.name):
                            os.unlink(tmp_file.name)
                    except:
                        pass
        
        except Exception as e:
            logger.error(f"Speech-to-text error: {str(e)}")
            
            return Response({
                'success': False,
                'error': f'Server error: {str(e)}',
                'text': '',
                'processing_time': time.time() - start_time
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SpeechStatusView(APIView):
    """Get Speech service status"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            speech_status = get_safe_speech_status()
            tts_status = get_safe_tts_status()
            
            return Response({
                'status': 'ok',
                'message': 'Speech Services Status (STT + TTS)',
                'speech_service': speech_status,
                'tts_service': tts_status,
                'endpoints': {
                    'speech_to_text': '/api/speech-to-text/',
                    'speech_status': '/api/speech-status/'
                },
                'capabilities': {
                    'stt_languages': ['vi', 'en'],
                    'tts_languages': tts_status.get('supported_languages', ['vi', 'en']),
                    'supported_formats': ['wav', 'mp3', 'webm', 'm4a'],
                    'max_file_size_mb': 10,
                    'features': [
                        'Voice Activity Detection',
                        'Noise Suppression', 
                        'Automatic Language Detection',
                        'GPU Acceleration (if available)',
                        'Text-to-Speech (gTTS)',
                        'Voice Conversation Mode',
                        'Multi-language TTS Support'
                    ]
                },
                'voice_interaction': {
                    'full_duplex_available': speech_status.get('available', False) and tts_status.get('available', False),
                    'stt_available': speech_status.get('available', False),
                    'tts_available': tts_status.get('available', False),
                    'recommended_workflow': [
                        '1. User speaks (STT)',
                        '2. AI processes text',
                        '3. AI responds with text + audio (TTS)',
                        '4. User hears response'
                    ]
                }
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error getting speech status: {str(e)}")
            return Response({
                'status': 'error',
                'error': str(e),
                'speech_service': {
                    'available': False,
                    'error': 'Service status check failed'
                },
                'tts_service': {
                    'available': False,
                    'error': 'Service status check failed'
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class TextToSpeechTestView(APIView):
    """TTS test endpoint"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        tts_status = get_safe_tts_status()
        return Response({
            'message': 'Text-to-Speech Test API',
            'method': 'POST để test TTS conversion',
            'tts_service': tts_status,
            'usage': {
                'method': 'POST',
                'content_type': 'application/json',
                'fields': {
                    'text': 'Text to convert to speech (required)',
                    'language': 'Language code (optional, default: vi)',
                    'slow': 'Slow speech (optional, default: false)'
                }
            }
        })
    
    def post(self, request):
        try:
            if not tts_service:
                return Response({
                    'success': False,
                    'error': 'TTS service not available.',
                    'audio_content': None
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            text_to_convert = request.data.get('text', '').strip()
            if not text_to_convert:
                return Response({
                    'success': False,
                    'error': 'Text field is required.',
                    'audio_content': None
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Generate TTS audio
            if hasattr(tts_service, 'text_to_audio_base64'):
                audio_base64 = tts_service.text_to_audio_base64(text_to_convert)
                
                if audio_base64:
                    return Response({
                        'success': True,
                        'audio_content': audio_base64,
                        'text_processed': text_to_convert,
                        'audio_format': 'mp3_base64'
                    })
                else:
                    return Response({
                        'success': False,
                        'error': 'Failed to generate TTS audio.',
                        'audio_content': None
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                return Response({
                    'success': False,
                    'error': 'TTS service method not available.',
                    'audio_content': None
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': f'TTS test failed: {str(e)}',
                'audio_content': None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ KEEP ALL OTHER EXISTING VIEWS UNCHANGED

class ChatHistoryView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request, session_id=None):
        try:
            if session_id:
                history = ChatHistory.objects.filter(session_id=session_id).order_by('timestamp')
            else:
                history = ChatHistory.objects.all().order_by('-timestamp')[:50]
            
            data = [{
                'id': chat.id,
                'session_id': chat.session_id,
                'user_message': chat.user_message,
                'bot_response': chat.bot_response,
                'timestamp': chat.timestamp.isoformat(),
                'confidence': chat.confidence_score,
                'response_time': chat.response_time
            } for chat in history]
            
            return Response({
                'count': len(data),
                'results': data
            })
            
        except Exception as e:
            logger.error(f"Error getting chat history: {str(e)}")
            return Response(
                {'error': 'Không thể lấy lịch sử chat'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class StudentChatHistoryView(APIView):
    """
    API an toàn để sinh viên tải lịch sử chat CỦA CHÍNH MÌNH.
    Nó lọc theo MSSV lấy từ JWT Token VÀ session_id từ query params.
    """
    permission_classes = [AllowAny]  # Sử dụng AllowAny vì JWT sẽ được validate trong hàm
    
    def get(self, request):
        jwt_token = extract_jwt_token(request)
        if not jwt_token:
            return Response({"error": "Token không hợp lệ"}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            # Dùng hàm helper _get_user_and_mssv_from_token đã có trong chatbot_service
            if not chatbot_ai:
                return Response({"error": "Chatbot service không khả dụng"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 1. Lấy MSSV từ token (để bảo mật)
            _, mssv = chatbot_ai._get_user_and_mssv_from_token(jwt_token)
            
            if not mssv:
                return Response({"error": "Không thể xác định sinh viên từ token"}, status=status.HTTP_400_BAD_REQUEST)
            
            #
            # --- BƯỚC SỬA LỖI 1: LẤY SESSION ID TỪ URL ---
            #
            session_id = request.query_params.get('session_id')
            if not session_id:
                return Response({"error": "Thiếu tham số session_id"}, status=status.HTTP_400_BAD_REQUEST)
            
            logger.info(f"Đang tải lịch sử cho MSSV {mssv}, Session {session_id}")

            #
            # --- BƯỚC SỬA LỖI 2: LỌC THEO CẢ MSSV VÀ SESSION_ID ---
            #
            history_queryset = ChatHistory.objects.filter(
                mssv=mssv,
                session_id=session_id  # <--- SỬA LỖI QUAN TRỌNG
            ).order_by('-timestamp')  # Sắp xếp giảm dần (mới nhất trước)
            
            history_count = history_queryset.count()
            history = list(history_queryset[:50])  # Lấy 50 tin nhắn gần nhất CỦA SESSION NÀY
            
            logger.info(f"Tìm thấy {history_count} tin nhắn, trả về {len(history)}")
            
            messages_for_fe = []
            for msg in history:  # 'history' đang là [msg_MớiNhất, msg_CũHơn, ...]
                # Chỉ thêm nếu có cả user_message và bot_response
                if msg.user_message and msg.bot_response:
                    # Thêm AI message TRƯỚC (Vì nó mới hơn trong cặp Q&A)
                    messages_for_fe.append({
                        "id": f"ai_{msg.id}",
                        "text": str(msg.bot_response),
                        "sender": "ai"
                    })
                    # Thêm User message SAU
                    messages_for_fe.append({
                        "id": f"user_{msg.id}",
                        "text": str(msg.user_message),
                        "sender": "user"
                    })
            
            # Mảng kết quả: [ai_MớiNhất, user_MớiNhất, ai_CũHơn, user_CũHơn, ...]
            # FlatList (inverted) sẽ render ĐÚNG
            
            return Response({
                'success': True,
                'messages': messages_for_fe,
                'total': len(messages_for_fe),
                'session_id': session_id
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Lỗi khi tải lịch sử chat: {e}", exc_info=True)
            return Response({"error": "Lỗi máy chủ khi tải lịch sử"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StudentChatSessionsView(APIView):
    """
    API để lấy danh sách các chat sessions của student.
    Sử dụng JWT token để xác định MSSV và trả về tất cả sessions của student đó.
    """
    permission_classes = [AllowAny]  # Sử dụng AllowAny vì JWT sẽ được validate trong hàm
    
    def get(self, request):
        jwt_token = extract_jwt_token(request)
        if not jwt_token:
            return Response({"error": "Token không hợp lệ"}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            # Dùng hàm helper _get_user_and_mssv_from_token đã có trong chatbot_service
            if not chatbot_ai:
                return Response({"error": "Chatbot service không khả dụng"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 1. Lấy MSSV từ token (để bảo mật)
            _, mssv = chatbot_ai._get_user_and_mssv_from_token(jwt_token)
            
            if not mssv:
                return Response({"error": "Không thể xác định sinh viên từ token"}, status=status.HTTP_400_BAD_REQUEST)
            
            logger.info(f"Đang tải danh sách sessions cho MSSV {mssv}")
            
            # 2. Lấy tất cả sessions của student này, group by session_id
            sessions_queryset = ChatHistory.objects.filter(
                mssv=mssv
            ).values('session_id').annotate(
                last_message_time=models.Max('timestamp'),
                message_count=models.Count('id'),
                first_message=models.Min('timestamp')
            ).order_by('-last_message_time')[:50]  # Lấy 50 sessions gần nhất
            
            sessions_list = []
            for session_data in sessions_queryset:
                session_id = session_data['session_id']
                
                # Lấy tin nhắn đầu tiên (user message) để làm title/preview
                first_chat = ChatHistory.objects.filter(
                    mssv=mssv,
                    session_id=session_id
                ).order_by('timestamp').first()
                
                # Lấy tin nhắn cuối cùng để preview
                last_chat = ChatHistory.objects.filter(
                    mssv=mssv,
                    session_id=session_id
                ).order_by('-timestamp').first()
                
                # Tạo title từ tin nhắn đầu tiên (hoặc user message đầu tiên)
                title = "Đoạn chat mới"
                preview = ""
                if first_chat and first_chat.user_message:
                    title_text = first_chat.user_message.strip()
                    if len(title_text) > 50:
                        title = title_text[:50] + "..."
                    else:
                        title = title_text
                
                if last_chat and last_chat.user_message:
                    preview = last_chat.user_message[:100] + "..." if len(last_chat.user_message) > 100 else last_chat.user_message
                
                sessions_list.append({
                    'session_id': session_id,
                    'title': title,
                    'preview': preview,
                    'last_message_time': session_data['last_message_time'].isoformat() if session_data['last_message_time'] else None,
                    'message_count': session_data['message_count'],
                    'created_at': first_chat.timestamp.isoformat() if first_chat else None
                })
            
            logger.info(f"Tìm thấy {len(sessions_list)} sessions cho MSSV {mssv}")
            
            return Response({
                'success': True,
                'sessions': sessions_list,
                'total': len(sessions_list)
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Lỗi khi tải danh sách sessions: {e}", exc_info=True)
            return Response({"error": "Lỗi máy chủ khi tải danh sách sessions"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class FeedbackView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            chat_id = request.data.get('chat_id')
            feedback_type = request.data.get('feedback_type')
            comment = request.data.get('comment', '')
            
            if not chat_id or not feedback_type:
                return Response(
                    {'error': 'chat_id và feedback_type là bắt buộc'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                chat_history = ChatHistory.objects.get(id=chat_id)
            except ChatHistory.DoesNotExist:
                return Response(
                    {'error': 'Không tìm thấy cuộc trò chuyện'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            feedback = UserFeedback.objects.create(
                chat_history=chat_history,
                feedback_type=feedback_type,
                comment=comment
            )
            
            return Response({
                'message': 'Cảm ơn phản hồi của bạn!',
                'feedback_id': feedback.id
            })
            
        except Exception as e:
            logger.error(f"Error saving feedback: {str(e)}")
            return Response(
                {'error': 'Không thể lưu phản hồi'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class PersonalizedChatContextView(APIView):
    """Lấy context cá nhân hóa cho chat"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            if not request.user.is_authenticated:
                return Response({
                    'personalization_enabled': False,
                    'message': 'User not authenticated'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            user = request.user
            
            # Safe user context extraction
            user_context = {}
            try:
                if hasattr(user, 'get_chatbot_context'):
                    user_context = user.get_chatbot_context()
            except Exception as e:
                logger.error(f"Error getting user context: {e}")
            
            tts_status = get_safe_tts_status()
            
            context_info = {
                'personalization_enabled': True,
                'user_context': user_context,
                'personalized_greeting': f"Chào {getattr(user, 'position_name', 'sinh viên')} {getattr(user, 'full_name', 'N/A') }!",
                'department_focus': getattr(user, 'department', 'BDU'),
                'tts_capabilities': {
                    'available': tts_status.get('available', False),
                    'supported_languages': tts_status.get('supported_languages', []),
                    'default_language': tts_status.get('default_language', 'vi'),
                    'voice_mode_enabled': tts_status.get('available', False)
                },
                'current_settings': {
                    'department_priority': getattr(user, 'chatbot_preferences', {}).get('department_priority', True),
                    'has_user_memory_prompt': bool(getattr(user, 'chatbot_preferences', {}).get('user_memory_prompt', '').strip()),
                    'external_api_ready': True,
                    'tts_enabled': tts_status.get('available', False)
                }
            }
            
            return Response(context_info, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Personalized context error: {str(e)}")
            return Response({
                'personalization_enabled': False,
                'error': 'Could not load personalized context',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PersonalizedSystemStatusView(APIView):
    """System status với thông tin personalization"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            status_data = get_safe_system_status()
            speech_status = get_safe_speech_status()
            tts_status = get_safe_tts_status()
            
            personalization_status = {
                'personalization_enabled': True,
                'version': '6.2.0',  # 🚀 Updated version
                'features': {
                    'user_memory_prompt_support': True,
                    'flexible_personalization': True,
                    'dynamic_system_prompts': True,
                    'custom_user_instructions': True,
                    'department_priority': True,
                    'personalized_addressing': True,
                    'jwt_token_authentication': True,
                    'external_api_integration': True,
                    'personal_schedule_access': True,
                    'student_info_queries': True,
                    'text_to_speech_support': True,
                    'voice_conversation_mode': True,
                    'speech_to_text_support': True,
                    'full_voice_interaction': True,
                    'fine_tuned_model_training': TRAINING_AVAILABLE,  # 🚀 NEW
                    'two_stage_reranking': True,  # 🚀 NEW
                    'advanced_rag_architecture': True  # 🚀 NEW
                },
                'statistics': {
                    'total_faculty': 0,
                    'active_personalized_sessions': 0,
                    'departments_available': 0,
                    'positions_available': 0
                }
            }
            
            # Add current user info if authenticated
            if request.user.is_authenticated:
                personalization_status['current_user'] = {
                    'faculty_code': getattr(request.user, 'faculty_code', 'N/A'),
                    'department': getattr(request.user, 'department', 'N/A'),
                    'position': getattr(request.user, 'position', 'N/A'),
                    'has_user_memory_prompt': bool(getattr(request.user, 'chatbot_preferences', {}).get('user_memory_prompt', '').strip()),
                    'department_priority': getattr(request.user, 'chatbot_preferences', {}).get('department_priority', True),
                    'preferences_configured': bool(getattr(request.user, 'chatbot_preferences', {})),
                    'external_api_ready': True,
                    'tts_ready': tts_status.get('available', False)
                }
            
            # Merge with system status
            status_data.update({
                'personalization': personalization_status,
                'speech_status': speech_status,
                'tts_status': tts_status,
                'training_status': {  # 🚀 NEW
                    'training_available': TRAINING_AVAILABLE,
                    'current_training': dict(TRAINING_STATUS)
                }
            })
            
            return Response(status_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"System status error: {str(e)}")
            return Response({
                'error': 'Could not retrieve system status',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ChatSessionsView(APIView):
    """Quản lý chat sessions của user"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Lấy danh sách sessions của user"""
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, 
                          status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            sessions = ChatHistory.objects.filter(user=request.user) \
                .values('session_id', 'session_title') \
                .annotate(
                    last_message_time=models.Max('timestamp'),
                    message_count=models.Count('id')
                ) \
                .order_by('-last_message_time')[:20]
            
            sessions_list = []
            for session in sessions:
                last_chat = ChatHistory.objects.filter(
                    user=request.user,
                    session_id=session['session_id']
                ).order_by('-timestamp').first()
                
                sessions_list.append({
                    'session_id': session['session_id'],
                    'title': session['session_title'] or f"Chat {session['session_id'][-8:]}",
                    'last_message_time': session['last_message_time'],
                    'message_count': session['message_count'],
                    'preview': last_chat.user_message[:50] + '...' if last_chat and len(last_chat.user_message) > 50 else last_chat.user_message if last_chat else '',
                    'active': False
                })
            
            return Response({
                'success': True,
                'sessions': sessions_list,
                'total_sessions': len(sessions_list)
            })
            
        except Exception as e:
            logger.error(f"Error loading chat sessions: {str(e)}")
            return Response({
                'success': False,
                'error': 'Could not load chat sessions'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def post(self, request):
        """Tạo session mới"""
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, 
                          status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            session_title = request.data.get('title', '')
            new_session_id = f"session_{getattr(request.user, 'faculty_code', 'user')}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            
            return Response({
                'success': True,
                'session_id': new_session_id,
                'title': session_title or f"Chat mới - {timezone.now().strftime('%H:%M')}"
            })
            
        except Exception as e:
            logger.error(f"Error creating new session: {str(e)}")
            return Response({
                'success': False,
                'error': 'Could not create new session'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ChatSessionDetailView(APIView):
    """Chi tiết một chat session"""
    permission_classes = [AllowAny]
    
    def get(self, request, session_id):
        """Lấy toàn bộ chat history của session"""
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, 
                          status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            chat_history = ChatHistory.objects.filter(
                user=request.user,
                session_id=session_id
            ).order_by('timestamp')
            
            messages = []
            for chat in chat_history:
                # User message
                messages.append({
                    'type': 'user',
                    'content': chat.user_message,
                    'timestamp': chat.timestamp.isoformat()
                })
                
                bot_entities = {}
                if chat.entities:
                    try:
                        bot_entities = json.loads(chat.entities)
                    except json.JSONDecodeError:
                        bot_entities = {}
                        
                # Bot message
                messages.append({
                    'type': 'bot',
                    'content': chat.bot_response,
                    'timestamp': chat.timestamp.isoformat(),
                    'confidence': chat.confidence_score,
                    'response_time': chat.response_time,
                    'sources': bot_entities.get('sources', []),
                    'reference_links': bot_entities.get('reference_links', []),  # ✅ PRESERVED
                    'chat_id': chat.id,
                    'two_stage_reranking_used': bot_entities.get('two_stage_reranking_used', False),  # 🚀 NEW
                    'fine_tuned_model_used': bot_entities.get('fine_tuned_model_used', False)  # 🚀 NEW
                })
            
            return Response({
                'success': True,
                'session_id': session_id,
                'messages': messages,
                'total_messages': len(messages)
            })
            
        except Exception as e:
            logger.error(f"Error loading session detail: {str(e)}")
            return Response({
                'success': False,
                'error': 'Could not load session messages'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def patch(self, request, session_id):
        """Cập nhật thông tin session (rename)"""
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, 
                          status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            new_title = request.data.get('title', '').strip()
            
            if not new_title:
                return Response({
                    'success': False,
                    'error': 'Title không được để trống'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Cập nhật session_title
            updated_count = ChatHistory.objects.filter(
                user=request.user,
                session_id=session_id
            ).update(session_title=new_title)
            
            return Response({
                'success': True,
                'session_id': session_id,
                'new_title': new_title,
                'updated_records': updated_count,
                'message': 'Đã đổi tên đoạn chat thành công'
            })
            
        except Exception as e:
            logger.error(f"Error updating session title: {str(e)}")
            return Response({
                'success': False,
                'error': 'Không thể cập nhật tên session'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request, session_id):
        """Xóa session"""
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, 
                          status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            deleted_count = ChatHistory.objects.filter(
                user=request.user,
                session_id=session_id
            ).delete()[0]
            
            return Response({
                'success': True,
                'deleted_messages': deleted_count
            })
            
        except Exception as e:
            logger.error(f"Error deleting session: {str(e)}")
            return Response({
                'success': False,
                'error': 'Could not delete session'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ FUNCTION-BASED VIEWS FOR COMPATIBILITY (Google Drive endpoints)
def health_check(request):
    """Health check function-based view"""
    return JsonResponse({
        'status': 'healthy',
        'message': 'BDU ChatBot API is running!',
        'version': '6.2.0',
        'advanced_rag': True,
        'training_available': TRAINING_AVAILABLE
    })

def speech_status(request):
    """Speech status function-based view"""
    try:
        speech_status = get_safe_speech_status()
        tts_status = get_safe_tts_status()
        
        return JsonResponse({
            'speech_service': speech_status,
            'tts_service': tts_status,
            'voice_interaction_available': speech_status.get('available', False) and tts_status.get('available', False)
        })
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'speech_service': {'available': False},
            'tts_service': {'available': False}
        })

def speech_to_text(request):
    """Speech to text function-based view"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method allowed'}, status=405)
    
    # Redirect to class-based view
    view = SpeechToTextView()
    return view.post(request)

def force_refresh_drive_data(request):
    """Force refresh Google Drive data"""
    try:
        from qa_management.services import drive_service
        result = drive_service.force_refresh()
        
        # Reload chatbot after data refresh
        if result.get('success') and chatbot_ai:
            chatbot_ai.reload_after_qa_update()
        
        return JsonResponse(result)
    except ImportError:
        return JsonResponse({
            'success': False,
            'error': 'QA Management service not available'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def google_drive_status(request):
    """Get Google Drive sync status"""
    try:
        from qa_management.services import drive_service
        status = drive_service.get_system_status()
        return JsonResponse(status)
    except ImportError:
        return JsonResponse({
            'available': False,
            'error': 'QA Management service not available'
        })
    except Exception as e:
        return JsonResponse({
            'available': False,
            'error': str(e)
        })