import logging
import time
import os
from typing import Optional, Tuple

from .rag_pipeline import PureSemanticChatbotAI
from ..gemini_service import GeminiResponseGenerator
from ..query_response_cache import query_response_cache
# XÓA BỎ CÁC IMPORT GÂY XUNG ĐỘT
# from ..external_api_service import external_api_service  # <--- XÓA
# from .student_api_handler import handle_external_api_student  # <--- XÓA

from knowledge.models import ChatHistory
from authentication.models import Faculty

logger = logging.getLogger(__name__)

class BDUChatbotService:
    def __init__(self):
        print("--- CHECKPOINT 1: BDUChatbotService __init__ started ---")
        self.response_generator = GeminiResponseGenerator()
        self.query_cache = query_response_cache        
        self.semantic_chatbot = PureSemanticChatbotAI(shared_response_generator=self.response_generator)
        # --- XÓA BỎ self.personal_info_keywords ---
        
        # 🆕 NEW: Initialize Agent Integration
        self.agent_integration = None
        self._initialize_agent_integration()
        
        logger.info("🎯 ENHANCED BDUChatbotService initialized")
    
    def _initialize_agent_integration(self):
        """Initialize agent integration service"""
        try:
            # Lấy Gemini API key từ environment
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            
            if not gemini_api_key:
                logger.warning("⚠️ GEMINI_API_KEY not found, agent mode disabled")
                return
            
            # ✅ FORCE ENABLE AGENT
            enable_agent_mode = True  # Force enable for testing
            
            logger.info(f"🚀 Initializing Agent Integration (enable_agent={enable_agent_mode})")
            
            # Import integration service
            from ..agent_integration import initialize_integration
            from ..external_api_service import external_api_service
            
            # Initialize integration
            self.agent_integration = initialize_integration(
                retriever=self.semantic_chatbot.sbert_retriever,
                reranker=self.semantic_chatbot.semantic_reranker,
                api_service=external_api_service,
                enable_agent=enable_agent_mode,  # ✅ Use the forced value
                gemini_api_key=os.getenv("GEMINI_API_KEY"),
                environment="development"
            )
            
            # ✅ VERIFY AGENT IS ENABLED
            if self.agent_integration:
                logger.info(f"✅ Agent Integration initialized: enable_agent={self.agent_integration.enable_agent}")
                logger.info(f"✅ Agent instance exists: {self.agent_integration.agent is not None}")
                
                # ✅ VERIFY DEPENDENCIES
                if hasattr(self.agent_integration, 'tool_registry'):
                    deps = self.agent_integration.tool_registry.verify_dependencies()
                    logger.info(f"✅ Tool dependencies: {deps}")
            else:
                logger.error("❌ Agent integration is None after initialization!")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize agent integration: {e}", exc_info=True)
            self.agent_integration = None

    #
    # --- SỬA ĐỔI HÀM HELPER NÀY ---
    #
    def _get_user_and_mssv_from_token(self, jwt_token: str) -> Tuple[Optional[Faculty], Optional[str]]:
        """
        Helper để lấy Faculty object (nếu là GV) VÀ MSSV string (nếu là SV).
        Trả về: (Faculty_obj, mssv_str)
        """
        if not jwt_token:
            return None, None
        
        try:
            # --- PHẢI IMPORT TRỰC TIẾP Ở ĐÂY ĐỂ TRÁNH CIRCULAR IMPORT ---
            from ..external_api_service import external_api_service
            decoded_token = external_api_service.decode_jwt_token(jwt_token)
            if not decoded_token:
                return None, None

            # 1. Lấy MSSV (luôn luôn thử lấy)
            mssv = None
            # Thử các key phổ biến trong JWT claims
            for key in ("mssv", "student_id", "user_id", "sub"):
                val = decoded_token.get(key)
                if isinstance(val, str) and val.strip():
                    mssv = val.strip()
                    break
                if isinstance(val, int):
                    mssv = str(val)
                    break
            
            # Thử trong nested object sinh_vien/student
            if not mssv:
                sv = decoded_token.get("sinh_vien") or decoded_token.get("student") or {}
                for key in ("mssv", "student_id"):
                    val = sv.get(key)
                    if isinstance(val, str) and val.strip():
                        mssv = val.strip()
                        break
            
            # Thử từ user.name (có thể là MSSV)
            if not mssv:
                user_info = decoded_token.get('user', {})
                if user_info.get('name'):
                    mssv = str(user_info['name'])

            # 2. Kiểm tra Role
            role = decoded_token.get('role') or decoded_token.get('roles', '')
            if isinstance(role, list):
                role = ','.join(role).lower()
            else:
                role = str(role).lower()
            
            # 3. Lấy Faculty object (CHỈ KHI LÀ GIẢNG VIÊN)
            if 'sinhvien' in role or 'student' in role:
                logger.debug(f"Token là của Sinh viên (MSSV: {mssv}). Sẽ lưu mssv.")
                return None, mssv  # Trả về (None, "22050090")
            
            # Nếu không phải sinh viên, thử lấy Giảng viên
            user_info = decoded_token.get('user', {})
            user_id = user_info.get('id') or decoded_token.get('user_id')
            
            if user_id:
                try:
                    faculty_obj = Faculty.objects.get(id=user_id)
                    logger.debug(f"Token là của Giảng viên (ID: {user_id}). Sẽ lưu user.")
                    return faculty_obj, None  # Trả về (Faculty_obj, None)
                except Faculty.DoesNotExist:
                    logger.warning(f"[ChatHistory] User (Faculty) ID {user_id} không tồn tại.")
                except Faculty.MultipleObjectsReturned:
                    logger.warning(f"[ChatHistory] Nhiều Faculty với ID {user_id} được tìm thấy.")
                    faculty_obj = Faculty.objects.filter(id=user_id).first()
                    return faculty_obj, None
            
            # Trường hợp không rõ role nhưng có mssv
            if mssv:
                return None, mssv
                
            return None, None
        except Exception as e:
            # Import ở đây để tránh lỗi circular import
            from ..external_api_service import external_api_service
            logger.error(f"[ChatHistory] Lỗi khi decode token: {e}")
            return None, None

    def save_chat_history(self, jwt_token: str, session_id: str, query: str, result: dict):
        """
        Ghi lịch sử chat vào DB (Đồng bộ) - Đã cập nhật để lưu cả MSSV.
        """
        try:
            # --- SỬA ĐỔI CÁCH GỌI HÀM HELPER ---
            user_obj, mssv_str = self._get_user_and_mssv_from_token(jwt_token)
            
            processing_time = result.get('processing_time', 0.0)

            # Đảm bảo session_id tồn tại
            if not session_id:
                session_id = f"anonymous_{int(time.time())}"

            ChatHistory.objects.create(
                user=user_obj,           # Sẽ là Faculty obj hoặc None
                mssv=mssv_str,           # --- LƯU MSSV VÀO ĐÂY ---
                session_id=session_id,
                user_message=query,
                bot_response=result.get('response', ''),
                confidence_score=result.get('confidence', 0.0),
                response_time=processing_time,
                intent=result.get('intent', None),
                method=result.get('method', None),
                strategy=result.get('strategy', None),
                entities=result.get('entities', None)
            )
            
            user_info = f"user={user_obj.faculty_code}" if user_obj else f"mssv={mssv_str}" if mssv_str else "user=Anonymous"
            logger.info(f"[SyncSave] 💾 Đã lưu lịch sử chat cho session: {session_id} ({user_info})")
            
        except Exception as e:
            logger.error(f"[SyncSave] ❌ LỖI NGHIÊM TRỌNG khi lưu lịch sử chat: {e}", exc_info=True)

    # --- KẾT THÚC HÀM HELPER ---

    #
    # --- XÓA BỎ CÁC HÀM GÂY LỖI KIẾN TRÚC ---
    #
    # def _needs_external_api(self, query: str) -> bool: # <-- XÓA HÀM NÀY
    #
    # def _handle_external_api_call(self, query: str, ...): # <-- XÓA HÀM NÀY
    #
    # --- KẾT THÚC XÓA BỎ ---

    def process_query(self, query: str, session_id: str = None, jwt_token: str = None, document_text: str = None) -> dict:
        """
        Process query với Agent hoặc Legacy mode
        """
        start_time = time.time()
        logger.info(f"🎯 Processing: '{query}' (session: {session_id})")
        
        # Validate input
        if not query or len(query.strip()) < 2:
            try:
                if hasattr(self.response_generator, '_get_personal_address') and session_id:
                    personal_address = self.response_generator._get_personal_address(session_id)
                    response_text = f"Dạ chào {personal_address}! mình có thể hỗ trợ gì cho {personal_address} về công việc tại BDU ạ?"
                else:
                    response_text = "Dạ chào bạn! mình có thể hỗ trợ gì cho bạn về công việc tại BDU ạ?"
            except:
                response_text = "Dạ chào bạn! mình có thể hỗ trợ gì cho bạn về công việc tại BDU ạ?"
            return {
                'response': response_text, 'confidence': 0.9, 'method': 'empty_query',
                'processing_time': time.time() - start_time, 'enhanced_semantic_rag': True, 'cache_hit': False
            }
        
        try:
            # ✅ ENHANCED: Better agent detection
            use_agent = (
                self.agent_integration is not None and 
                hasattr(self.agent_integration, 'enable_agent') and 
                self.agent_integration.enable_agent and 
                self.agent_integration.agent is not None
            )
            
            # ✅ DEBUG LOG
            logger.info(f"🔍 Agent check: integration={self.agent_integration is not None}, "
                        f"enable={getattr(self.agent_integration, 'enable_agent', False)}, "
                        f"agent_exists={getattr(self.agent_integration, 'agent', None) is not None}")
            
            if use_agent:
                logger.info("🤖 Using AGENT MODE")
                
                # Get student profile if JWT token available
                student_profile = None
                if jwt_token:
                    try:
                        from ..external_api_service import external_api_service
                        profile_result = external_api_service.get_student_profile(jwt_token)
                        if profile_result:
                            student_profile = profile_result
                    except Exception as e:
                        logger.warning(f"⚠️ Could not fetch student profile: {e}")
                
                # Process với Agent
                result = self.agent_integration.process_query(
                    query=query,
                    session_id=session_id or f"session_{int(time.time())}",
                    jwt_token=jwt_token,
                    student_profile=student_profile,
                    document_text=document_text,
                    legacy_handler=self.semantic_chatbot  # Fallback
                )
                
                # Save history
                if session_id and jwt_token:
                    self.save_chat_history(jwt_token, session_id, query, result)
                
                return result
            
            else:
                logger.info("🔧 Using LEGACY MODE")
                logger.warning("⚠️ Agent mode not available, falling back to legacy")
                
                # 2. Kiểm tra Cache
                cached_response = self.query_cache.get(query)
                if cached_response:
                    cached_response['processing_time'] = time.time() - start_time
                    logger.info(f"⚡ [RAG] CACHE HIT: Response served in {cached_response['processing_time']:.3f}s")
                    # KHÔNG LƯU LỊCH SỬ KHI CACHE HIT
                    return cached_response
                
                logger.info("💨 [RAG] CACHE MISS: Proceeding with semantic processing")
                
                # 3. Gọi đến luồng xử lý RAG (đã bao gồm xử lý tài liệu)
                logger.info("📚 [RAG] Calling semantic_chatbot.process_query...")
                result = self.semantic_chatbot.process_query(query, session_id, jwt_token, document_text)
                
                result['processing_time'] = time.time() - start_time
                
                # 4. Lưu kết quả vào Cache
                result['cache_hit'] = False
                if result and result.get('confidence', 0) > 0.1:
                    cache_stored = self.query_cache.set(query, result)
                    result['cache_stored'] = cache_stored
                
                # 5. LƯU LỊCH SỬ CHO RAG RESULT
                if result.get('method') not in ['empty_query', 'service_error']:
                    # Dùng jwt_token được truyền vào
                    self.save_chat_history(jwt_token, session_id, query, result)
                
                return result
                
        except Exception as e:
            logger.error(f"❌ Error in process_query: {str(e)}", exc_info=True)
            return {
                'response': 'Lỗi hệ thống', 
                'confidence': 0.0, 
                'method': 'error',
                'processing_time': time.time() - start_time, 
                'error': str(e)
            }
            
    #
    # --- XÓA BỎ CÁC HÀM GÂY LỖI KIẾN TRÚC ---
    # (Đã được xóa: _needs_external_api, _handle_external_api_call, _handle_authentication_required, 
    #  _get_api_fallback, _get_api_error_response)
    # --- KẾT THÚC XÓA BỎ ---

    def get_system_status(self):
        semantic_status = self.semantic_chatbot.get_system_status()
        # Import ở đây để tránh circular import
        try:
            from ..external_api_service import external_api_service
            api_status = external_api_service.get_system_status()
        except Exception as e:
            logger.warning(f"Could not get external API status: {e}")
            api_status = {'available': False, 'error': str(e)}
        cache_stats = self.query_cache.get_cache_stats()        
        return {
            'service_name': 'BDUChatbotService',
            'architecture': 'rag_only_mode',
            'chatbot_service': semantic_status,
            'external_api_service': api_status,
            'cache_performance': cache_stats
        }
    def test_context_functionality(self, session_id="test_session"):
        """🆕 Test context-aware functionality"""
        logger.info("🧪 Testing context-aware functionality...")
        
        test_results = {
            'entity_extraction': False,
            'context_memory': False, 
            'dual_search': False,
            'context_enhancement': False,
            'conversation_continuity': False
        }        
        try:
            if hasattr(self.response_generator, 'memory') and hasattr(self.response_generator.memory, 'entity_extractor'):
                entities = self.response_generator.memory.entity_extractor.extract_entities(
                    "Hiệu trưởng là Cao Việt Hiếu", 
                    "hiệu trưởng là ai"
                )
                test_results['entity_extraction'] = bool(entities)
                logger.info(f"✅ Entity extraction test: {entities}")
            if hasattr(self.response_generator, 'memory'):
                self.response_generator.memory.add_interaction(
                    session_id, 
                    "hiệu trưởng là ai?", 
                    "Cao Việt Hiếu", 
                    intent_info={'intent': 'test'}, 
                    entities={}
                )
                context_info = self.response_generator.memory.get_context_for_query(
                    session_id, 
                    "vậy Cao Việt Hiếu là ai?"
                )
                test_results['context_memory'] = context_info.get('should_use_context', False)
                logger.info(f"✅ Context memory test: {context_info}")
            if hasattr(self.sbert_retriever, 'dual_semantic_search'):
                candidates, method = self.sbert_retriever.dual_semantic_search(
                    "test query", 
                    ["test keyword"], 
                    top_k=5
                )
                test_results['dual_search'] = method in ['normal', 'context', 'fallback']
                logger.info(f"✅ Dual search test: method={method}, candidates={len(candidates)}")
            try:
                result = self.process_query("ai là hiệu trưởng?", session_id=session_id)
                test_results['context_enhancement'] = 'context_info' in result
                logger.info(f"✅ Context enhancement test: {result.get('context_info', {})}")
                
                # Follow-up query để test continuity  
                result2 = self.process_query("vậy người đó làm gì?", session_id=session_id)
                test_results['conversation_continuity'] = result2.get('context_info', {}).get('context_used', False)
                logger.info(f"✅ Conversation continuity test: {result2.get('context_info', {})}")
            except Exception as e:
                logger.error(f"❌ Context enhancement test failed: {str(e)}")
        except Exception as e:
            logger.error(f"❌ Context functionality test failed: {str(e)}")
        if session_id and hasattr(self.response_generator, 'memory'):
            if session_id in self.response_generator.memory.conversations:
                del self.response_generator.memory.conversations[session_id]
        passed_tests = sum(test_results.values())
        total_tests = len(test_results)
        logger.info(f"🧪 Context functionality test completed: {passed_tests}/{total_tests} tests passed")
        logger.info(f"📊 Test results: {test_results}")
        return {
            'test_results': test_results,
            'passed': passed_tests,
            'total': total_tests,
            'success_rate': passed_tests / total_tests if total_tests > 0 else 0,
            'fully_functional': passed_tests == total_tests
        }
    def get_conversation_memory(self, session_id):
        return self.semantic_chatbot.get_conversation_memory(session_id)
    def clear_conversation_memory(self, session_id=None):
        return self.semantic_chatbot.clear_conversation_memory(session_id)
    def reload_after_qa_update(self):
        return self.semantic_chatbot.reload_after_qa_update()
    @property
    def model(self):
        return self.semantic_chatbot.model
    @property
    def index(self):
        return self.semantic_chatbot.index
    @property
    def knowledge_data(self):
        return self.semantic_chatbot.knowledge_data
    def get_cache_stats(self):
        return self.query_cache.get_cache_stats()
    def clear_cache(self):
        return self.query_cache.clear_cache()
    def update_cache_ttl(self, new_ttl: int):
        self.query_cache.update_ttl(new_ttl)
        logger.info(f"🔄 Cache TTL updated to {new_ttl} seconds")
    
    def generate_with_context(self, query: str, student_context: dict, session_id: str = None) -> dict:
        """
        Generate response với student context cho chế độ gia sư
        """
        try:
            logger.info(f"🎓 BDUChatbotService.generate_with_context called: query='{query}', session_id={session_id}")
            
            # Gọi Gemini với context
            gemini_response = self.response_generator.generate_response(
                query=query,
                context={
                    "instruction": "tutor_mode",
                    "confidence": 0.7,
                    "student_data": student_context,
                    "profile": student_context.get("profile", {})
                },
                intent_info={"role": "student", "mode": "tutor"},
                entities=None,
                session_id=session_id or f"tutor_{int(time.time())}"
            )
            
            if gemini_response and gemini_response.get("response"):
                logger.info(f"🎓 Tutor response generated successfully")
                return {
                    "status": "success",
                    "response": gemini_response.get("response"),
                    "method": "gemini_tutor_with_context",
                    "confidence": 0.85,
                    "student_data": student_context
                }
            else:
                logger.warning("⚠️ Gemini tutor response empty")
                return {
                    "status": "error",
                    "response": "Xin lỗi, mình không thể tư vấn lúc này. Thử lại sau nhé!",
                    "method": "tutor_fallback",
                    "confidence": 0.5
                }
                
        except Exception as e:
            logger.error(f"❌ Error in generate_with_context: {str(e)}")
            return {
                "status": "error", 
                "response": "Đã xảy ra lỗi khi tư vấn. Thử lại sau nhé!",
                "method": "tutor_error",
                "confidence": 0.3
            }
            
chatbot_ai = BDUChatbotService()