"""
Agent Integration Wrapper
Wrapper để tích hợp Agent System với code hiện tại
Đảm bảo backward compatibility
"""
import logging
import os
from typing import Dict, Any, Optional
import time

# ✅ SỬA LỖI: Import hàm tạo agent từ file agent.py
from .agent_system.core.agent import create_agent 

logger = logging.getLogger(__name__)


class AgentIntegrationService:
    """
    Service để tích hợp Agent System vào chatbot hiện tại
    Có thể chuyển đổi giữa legacy mode và agent mode
    """
    
    def __init__(
        self,
        enable_agent: bool = True,
        gemini_api_key: Optional[str] = None,
        environment: str = "development"
    ):
        """
        Initialize integration service
        
        Args:
            enable_agent: Enable agent mode (True) or use legacy mode (False)
            gemini_api_key: Gemini API key
            environment: "development" or "production"
        """
        self.enable_agent = enable_agent
        self.environment = environment
        self.agent = None
        self.tool_registry = None
        
        # Statistics
        self.stats = {
            "agent_calls": 0,
            "legacy_calls": 0,
            "agent_errors": 0,
            "legacy_fallbacks": 0
        }
        
        if enable_agent:
            try:  
                # Dòng này sẽ gọi hàm _initialize_agent (đã được thêm ở dưới)
                self._initialize_agent(gemini_api_key) 
                logger.info("✅ Agent mode enabled")
            except Exception as e:
                logger.error(f"❌ Failed to initialize agent: {e}", exc_info=True) # Thêm exc_info
                logger.warning("⚠️ Falling back to legacy mode")
                self.enable_agent = False # Tắt agent nếu khởi tạo lỗi
        else:
             logger.info("🔧 Agent mode is manually disabled")

    # ✅ SỬA LỖI: THÊM LẠI HÀM BỊ MẤT
    def _initialize_agent(self, gemini_api_key: str):
        """
        Khởi tạo Agent thực sự bằng cách gọi hàm create_agent từ agent.py
        """
        logger.info("🚀 Initializing Core Agent System via create_agent...")
        
        try:
            # Gọi hàm create_agent từ file agent.py
            agent_instance = create_agent(
                gemini_api_key=gemini_api_key,
                environment=self.environment
            )
            
            if not agent_instance:
                raise Exception("create_agent() returned None")
            
            # Gán agent và tool_registry để các hàm khác có thể dùng
            self.agent = agent_instance
            self.tool_registry = agent_instance.tool_registry #
            
            if self.agent and self.tool_registry:
                 logger.info("✅ Core Agent and Tool Registry initialized successfully.")
            else:
                raise Exception("Agent or Tool Registry is None after creation")
                
        except Exception as e:
            logger.error(f"❌ Critical Agent Initialization Error in _initialize_agent: {e}")
            raise # Ném lỗi ra ngoài để __init__ bắt được và tắt agent mode

    
    def inject_dependencies(
        self,
        retriever,
        reranker,
        api_service,
        **kwargs
    ):
        """
        Inject dependencies vào tools
        """
        # HÀM NÀY SẼ HẾT LỖI 'NoneType'
        # VÌ self.tool_registry ĐÃ ĐƯỢC GÁN TRONG _initialize_agent
        if not self.tool_registry:
            logger.warning("⚠️ Tool registry not initialized, skipping dependency injection")
            return
        
        try:
            # (Giả định ToolRegistry có hàm inject_dependencies)
            self.tool_registry.inject_dependencies(
                retriever=retriever,
                reranker=reranker,
                api_service=api_service,
                **kwargs
            )
            logger.info("✅ Dependencies injected into tools")
        except AttributeError:
             logger.warning(f"⚠️ 'ToolRegistry' object has no attribute 'inject_dependencies'. Skipping.")
        except Exception as e:
            logger.error(f"❌ Failed to inject dependencies: {e}")
    
    def process_query(
        self,
        query: str,
        session_id: str,
        jwt_token: Optional[str] = None,
        student_profile: Optional[Dict[str, Any]] = None,
        document_text: Optional[str] = None,
        legacy_handler=None
    ) -> Dict[str, Any]:
        """
        Process query với Agent hoặc fallback to legacy
        """
        start_time = time.time()
        
        # Quyết định mode (Bây giờ self.agent sẽ không còn là None)
        use_agent = self.enable_agent and self.agent is not None
        
        if use_agent:
            try:
                logger.info(f"🤖 Using AGENT mode for query: '{query}'")
                self.stats["agent_calls"] += 1
                
                # ... (Phần logic student_profile) ...
                if jwt_token and not student_profile:
                    try:
                        # ✅ SỬA LỖI IMPORT: Dùng . (dấu chấm)
                        from .external_api_service import external_api_service 
                        profile_result = external_api_service.get_student_profile(jwt_token)
                        if profile_result:
                            student_profile = {
                                "full_name": getattr(profile_result, "full_name", ""),
                                "mssv": getattr(profile_result, "mssv", ""),
                                "class_name": getattr(profile_result, "class_name", ""),
                                "faculty": getattr(profile_result, "faculty", ""),
                                "major": getattr(profile_result, "major", ""),
                                "email": getattr(profile_result, "email", ""),
                            }
                            logger.info(
                                "✅ Student profile converted to dict: %s (%s)",
                                student_profile.get("full_name"),
                                student_profile.get("mssv"),
                            )
                    except Exception as profile_error:
                        logger.warning(f"⚠️ Could not fetch student profile: {profile_error}")
                
                # Process với agent (self.agent giờ đã tồn tại)
                result = self.agent.process_query(
                    query=query,
                    session_id=session_id,
                    jwt_token=jwt_token,
                    student_profile=student_profile,
                    document_text=document_text
                )
                
                # ... (Phần còn lại của logic) ...
                result["integration_mode"] = "agent"
                result["agent_enabled"] = True
                result["processing_time"] = time.time() - start_time
                
                return result
                
            except Exception as e:
                logger.error(f"❌ Agent error: {e}, falling back to legacy", exc_info=True)
                self.stats["agent_errors"] += 1
                self.stats["legacy_fallbacks"] += 1
                
                if legacy_handler:
                    return self._call_legacy(
                        legacy_handler, query, session_id, jwt_token, document_text, error=e
                    )
                else:
                    return self._get_error_response(e, query, session_id, start_time)
        
        else:
            # Legacy mode
            logger.info(f"🔧 Using LEGACY mode for query: '{query}'")
            self.stats["legacy_calls"] += 1
            
            if legacy_handler:
                return self._call_legacy(
                    legacy_handler, query, session_id, jwt_token, document_text
                )
            else:
                return {
                    "status": "error",
                    "response": "No handler available",
                    "integration_mode": "none"
                }
    
    def _call_legacy(
        self,
        legacy_handler,
        query: str,
        session_id: str,
        jwt_token: Optional[str],
        document_text: Optional[str],
        error: Optional[Exception] = None
    ) -> Dict[str, Any]:
        """Call legacy chatbot service"""
        try:
            result = legacy_handler.process_query(
                query=query,
                session_id=session_id,
                jwt_token=jwt_token,
                document_text=document_text
            )
            
            result["integration_mode"] = "legacy"
            result["agent_enabled"] = False
            
            if error:
                result["agent_error"] = str(error)
                result["fallback_reason"] = "agent_error"
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Legacy handler also failed: {e}")
            return {
                "status": "error",
                "response": "Hệ thống gặp sự cố. Vui lòng thử lại sau.",
                "integration_mode": "error",
                "agent_error": str(error) if error else None,
                "legacy_error": str(e)
            }
    
    def _get_error_response(
        self,
        error: Exception,
        query: str,
        session_id: str,
        start_time: float
    ) -> Dict[str, Any]:
        """Generate error response"""
        return {
            "status": "error",
            "response": f"Đã xảy ra lỗi: {str(error)}",
            "session_id": session_id,
            "processing_time": time.time() - start_time,
            "integration_mode": "agent_error",
            "error": str(error)
        }
    
    def switch_mode(self, enable_agent: bool):
        """
        Switch between agent and legacy mode
        """
        if enable_agent and not self.agent:
            logger.warning("⚠️ Cannot enable agent mode: agent not initialized")
            return False
        
        self.enable_agent = enable_agent
        mode = "agent" if enable_agent else "legacy"
        logger.info(f"🔄 Switched to {mode} mode")
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get integration statistics"""
        total_calls = self.stats["agent_calls"] + self.stats["legacy_calls"]
        
        agent_stats = None
        tool_stats = None
        
        try:
            if self.agent and hasattr(self.agent, 'get_system_stats'):
                agent_stats = self.agent.get_system_stats()
        except Exception as e:
            logger.warning(f"Could not get agent stats: {e}")
        
        try:
            # SỬA LỖI: Kiểm tra self.tool_registry, không phải self.agent
            if self.tool_registry and hasattr(self.tool_registry, 'get_tool_stats'):
                tool_stats = self.tool_registry.get_tool_stats()
        except Exception as e:
            logger.warning(f"Could not get tool stats: {e}")
        
        return {
            "mode": "agent" if self.enable_agent else "legacy",
            "agent_initialized": self.agent is not None,
            "total_calls": total_calls,
            "agent_calls": self.stats["agent_calls"],
            "legacy_calls": self.stats["legacy_calls"],
            "agent_errors": self.stats["agent_errors"],
            "legacy_fallbacks": self.stats["legacy_fallbacks"],
            "agent_success_rate": round(
                (self.stats["agent_calls"] - self.stats["agent_errors"]) / 
                self.stats["agent_calls"] * 100, 2
            ) if self.stats["agent_calls"] > 0 else 0,
            "agent_stats": agent_stats,
            "tool_stats": tool_stats
        }
    
    def clear_session(self, session_id: str):
        """Clear session data"""
        if self.agent:
            try:
                if hasattr(self.agent, 'clear_session'):
                    self.agent.clear_session(session_id)
                logger.info(f"🗑️ Session cleared: {session_id}")
            except Exception as e:
                logger.error(f"❌ Error clearing session: {e}")


# ========================
# Global Integration Service (Singleton)
# ========================
_global_integration: Optional[AgentIntegrationService] = None


def get_integration_service(
    enable_agent: bool = True,
    gemini_api_key: Optional[str] = None,
    environment: str = "development"
) -> AgentIntegrationService:
    """
    Get global integration service (create if not exists)
    """
    global _global_integration
    
    if _global_integration is None:
        _global_integration = AgentIntegrationService(
            enable_agent=enable_agent,
            gemini_api_key=gemini_api_key,
            environment=environment
        )
    
    return _global_integration


def initialize_integration(
    retriever,
    reranker,
    api_service,
    enable_agent: bool = True,
    gemini_api_key: Optional[str] = None,
    environment: str = "development"
) -> "AgentIntegrationService":
    """
    Initialize integration service với tất cả dependencies
    """
    service = get_integration_service(
        enable_agent=enable_agent,
        gemini_api_key=gemini_api_key,
        environment=environment
    )
    
    # Inject dependencies
    service.inject_dependencies(
        retriever=retriever,
        reranker=reranker,
        api_service=api_service
    )
    
    logger.info("✅ Integration service fully initialized")
    return service