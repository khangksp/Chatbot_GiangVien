"""
Tool Registry - Central management for all agent tools
Quản lý tất cả tools và cung cấp tools cho Agent
✅ UPDATED: Đã thêm StudentTuitionTool, StudentCreditsTool, StudentNewsTool
"""
import logging
from typing import List, Dict, Any, Optional

from .base_tool import BDUBaseTool
from .rag_tool import RAGSearchTool, RAGContextSearchTool
from .student_tools import (
    StudentProfileTool,
    StudentScheduleTool,
    StudentGradesTool,
    StudentTuitionTool,      # ✅ MỚI - Học phí
    StudentCreditsTool,      # ✅ MỚI - Tín chỉ tích lũy
    StudentNewsTool,         # ✅ MỚI - Tin tức
)
# Logger: khai báo trước khi dùng trong các try/except import
logger = logging.getLogger(__name__)

# ✅ IMPORT AN TOÀN - Nếu exam_rl_tools chưa có thì các tool khác vẫn hoạt động
try:
    from .exam_rl_tools import (
        StudentExamScheduleTool,
        StudentRLGradesTool,
    )
    EXAM_RL_TOOLS_AVAILABLE = True
    logger.info("✅ exam_rl_tools imported successfully")
except ImportError as e:
    EXAM_RL_TOOLS_AVAILABLE = False
    logger.warning(f"⚠️ exam_rl_tools not available: {e}")
    logger.warning("⚠️ Exam schedule and RL grades tools will not be registered")
except Exception as e:
    EXAM_RL_TOOLS_AVAILABLE = False
    logger.error(f"❌ Error importing exam_rl_tools: {e}")
    logger.error("❌ Exam schedule and RL grades tools will not be registered")

# ✅ IMPORT AN TOÀN - Union & GPA tools
try:
    from .union_gpa_tools import (
        StudentUnionInfoTool,
        StudentSemesterGPATool,
        StudentScoreListTool,
        StudentCurriculumTool,  # <--- 1. THÊM DÒNG NÀY
    )
    UNION_GPA_TOOLS_AVAILABLE = True
    logger.info("✅ union_gpa_tools imported successfully")
except ImportError as e:
    UNION_GPA_TOOLS_AVAILABLE = False
    logger.warning(f"⚠️ union_gpa_tools not available: {e}")
    logger.warning("⚠️ Union info, semester GPA, and score list tools will not be registered")
except Exception as e:
    UNION_GPA_TOOLS_AVAILABLE = False
    logger.error(f"❌ Error importing union_gpa_tools: {e}")
    logger.error("❌ Union info, semester GPA, and score list tools will not be registered")
logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registry để quản lý tất cả tools
    Cung cấp tools phù hợp dựa trên context
    """
    
    def __init__(self):
        """Initialize tool registry"""
        self.tools: Dict[str, BDUBaseTool] = {}
        self._register_default_tools()
        logger.info("🔧 ToolRegistry initialized")
    
    def _register_default_tools(self):
        """Register default tools"""
        # ================================
        # RAG Tools (Knowledge Base)
        # ================================
        self.register_tool("rag_search", RAGSearchTool())
        self.register_tool("rag_context_search", RAGContextSearchTool())
        
        # ================================
        # Student API Tools
        # ================================
        self.register_tool("student_profile", StudentProfileTool())
        self.register_tool("student_schedule", StudentScheduleTool())
        self.register_tool("student_grades", StudentGradesTool())
        
        # ✅ THÊM 3 TOOLS MỚI
        self.register_tool("student_tuition", StudentTuitionTool())    # Học phí
        self.register_tool("student_credits", StudentCreditsTool())    # Tín chỉ
        self.register_tool("student_news", StudentNewsTool())          # Tin tức
        
        # ✅ THÊM 2 TOOLS MỚI - Chỉ register nếu import thành công
        if EXAM_RL_TOOLS_AVAILABLE:
            self.register_tool("student_exam_schedule", StudentExamScheduleTool())  # Lịch thi
            self.register_tool("student_rl_grades", StudentRLGradesTool())          # Điểm RL
            logger.info("✅ Exam & RL tools registered")
        else:
            logger.warning("⚠️ Exam & RL tools NOT registered (import failed)")
        
        # ✅ THÊM 3 TOOLS MỚI - Union & GPA
        if UNION_GPA_TOOLS_AVAILABLE:
            self.register_tool("student_union_info", StudentUnionInfoTool())        # Thông tin đoàn viên
            self.register_tool("student_semester_gpa", StudentSemesterGPATool())    # Điểm TB học kỳ
            self.register_tool("student_score_list", StudentScoreListTool())        # Bảng điểm
            self.register_tool("student_curriculum", StudentCurriculumTool())   # <--- 2. THÊM DÒNG NÀY
            logger.info("✅ Union & GPA tools registered")
        else:
            logger.warning("⚠️ Union & GPA tools NOT registered (import failed)")
        
        logger.info(f"✅ Registered {len(self.tools)} default tools")
    
    def register_tool(self, tool_id: str, tool: BDUBaseTool):
        """
        Register a new tool
        
        Args:
            tool_id: Unique identifier for the tool
            tool: Tool instance
        """
        if tool_id in self.tools:
            logger.warning(f"⚠️ Tool {tool_id} already registered, overwriting...")
        
        self.tools[tool_id] = tool
        logger.debug(f"🔧 Registered tool: {tool_id} ({tool.name})")
    
    def unregister_tool(self, tool_id: str):
        """Unregister a tool"""
        if tool_id in self.tools:
            del self.tools[tool_id]
            logger.debug(f"🗑️ Unregistered tool: {tool_id}")
    
    def get_tool(self, tool_id: str) -> Optional[BDUBaseTool]:
        """Get a specific tool by ID"""
        return self.tools.get(tool_id)
    
    def get_all_tools(self) -> List[BDUBaseTool]:
        """Get all registered tools"""
        return list(self.tools.values())
    
    def get_tools_for_session(
        self,
        jwt_token: Optional[str] = None,
        student_profile: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[BDUBaseTool]:
        """
        Get appropriate tools for a specific session
        
        Args:
            jwt_token: JWT token for authenticated tools
            student_profile: Student profile data
            **kwargs: Additional context
        
        Returns:
            List of tools appropriate for this session
        """
        selected_tools = []
        
        # ================================
        # 1. RAG Tools (Always available)
        # ================================
        rag_tool = self.get_tool("rag_search")
        if rag_tool:
            has_retriever = hasattr(rag_tool, 'retriever') and rag_tool.retriever is not None
            logger.info(f"🔍 RAG Search Tool: retriever={'✅ Initialized' if has_retriever else '❌ NOT initialized'}")
            selected_tools.append(rag_tool)
        
        rag_context_tool = self.get_tool("rag_context_search")
        if rag_context_tool:
            has_retriever = hasattr(rag_context_tool, 'retriever') and rag_context_tool.retriever is not None
            logger.info(f"🔍 RAG Context Tool: retriever={'✅ Initialized' if has_retriever else '❌ NOT initialized'}")
            selected_tools.append(rag_context_tool)
        
        # ================================
        # 2. Student API Tools (Authenticated)
        # ================================
        if jwt_token:
            # ✅ Danh sách các tools cần authentication
            authenticated_tool_ids = [
                "student_profile",
                "student_schedule",
                "student_grades",
                "student_tuition",   # ✅ MỚI - Học phí
                "student_credits",   # ✅ MỚI - Tín chỉ
            ]
            
            # ✅ Thêm exam & RL tools nếu available
            if EXAM_RL_TOOLS_AVAILABLE:
                authenticated_tool_ids.extend([
                    "student_exam_schedule",  # ✅ MỚI - Lịch thi
                    "student_rl_grades",      # ✅ MỚI - Điểm RL
                ])
            
            # ✅ Thêm union & GPA tools nếu available
            if UNION_GPA_TOOLS_AVAILABLE:
                authenticated_tool_ids.extend([
                    "student_union_info",     # ✅ MỚI - Thông tin đoàn viên
                    "student_semester_gpa",   # ✅ MỚI - Điểm TB học kỳ
                    "student_score_list",     # ✅ MỚI - Bảng điểm
                    "student_curriculum",     # <--- 3. THÊM DÒNG NÀY
                ])
            
            for tool_id in authenticated_tool_ids:
                tool = self.get_tool(tool_id)
                if tool:
                    tool.set_jwt_token(jwt_token)
                    if student_profile:
                        tool.set_student_profile(student_profile)
                    selected_tools.append(tool)
                    logger.debug(f"✅ {tool_id.replace('_', ' ').title()} Tool added (authenticated)")
            
            logger.info(f"✅ Session with authentication: {len(selected_tools)} tools available")
        else:
            logger.info(f"ℹ️ Session without authentication: {len(selected_tools)} tools available (RAG only)")
        
        # ================================
        # 3. Public Tools (No auth needed)
        # ================================
        # Student News không cần auth (public)
        news_tool = self.get_tool("student_news")
        if news_tool:
            selected_tools.append(news_tool)
            logger.debug(f"✅ Student News Tool added (public)")
        
        return selected_tools
    
    def inject_dependencies(
        self,
        retriever=None,
        reranker=None,
        api_service=None,
        **kwargs
    ):
        """
        Inject external dependencies vào các tools
        
        Args:
            retriever: SBERT retriever instance
            reranker: Semantic reranker instance
            api_service: External API service instance
            **kwargs: Additional services
        """
        logger.info("💉 Injecting dependencies into tools...")
        
        injection_count = 0
        
        # ================================
        # Inject vào RAG tools
        # ================================
        if retriever:
            for tool_id in ["rag_search", "rag_context_search"]:
                tool = self.get_tool(tool_id)
                if tool:
                    tool.set_retriever(retriever)
                    logger.debug(f"✅ Retriever injected into {tool_id}")
                    injection_count += 1
        else:
            logger.warning("⚠️ No retriever provided for injection")
        
        if reranker:
            for tool_id in ["rag_search", "rag_context_search"]:
                tool = self.get_tool(tool_id)
                if tool:
                    tool.set_reranker(reranker)
                    logger.debug(f"✅ Reranker injected into {tool_id}")
                    injection_count += 1
        else:
            logger.warning("⚠️ No reranker provided for injection")
        
        # ================================
        # Inject vào Student API tools
        # ================================
        if api_service:
            # ✅ Danh sách đầy đủ các student tools
            student_tool_ids = [
                "student_profile",
                "student_schedule",
                "student_grades",
                "student_tuition",   # ✅ MỚI
                "student_credits",   # ✅ MỚI
                "student_news",      # ✅ MỚI
            ]
            
            # ✅ Thêm exam & RL tools nếu available
            if EXAM_RL_TOOLS_AVAILABLE:
                student_tool_ids.extend([
                    "student_exam_schedule",  # ✅ MỚI - Lịch thi
                    "student_rl_grades",      # ✅ MỚI - Điểm RL
                ])
            
            # ✅ Thêm union & GPA tools nếu available
            if UNION_GPA_TOOLS_AVAILABLE:
                student_tool_ids.extend([
                    "student_union_info",     # ✅ MỚI - Thông tin đoàn viên
                    "student_semester_gpa",   # ✅ MỚI - Điểm TB học kỳ
                    "student_score_list",     # ✅ MỚI - Bảng điểm
                    "student_curriculum",     # <--- 4. THÊM DÒNG NÀY
                ])
            
            for tool_id in student_tool_ids:
                tool = self.get_tool(tool_id)
                if tool:
                    tool.set_api_service(api_service)
                    logger.debug(f"✅ API service injected into {tool_id}")
                    injection_count += 1
        else:
            logger.warning("⚠️ No API service provided for injection")
        
        logger.info(f"✅ All dependencies injected ({injection_count} injections completed)")
    
    def verify_dependencies(self) -> Dict[str, bool]:
        """
        Verify that all critical dependencies are injected
        
        Returns:
            Dict with verification results
        """
        results = {
            "rag_search_ready": False,
            "rag_context_search_ready": False,
            "student_api_ready": False
        }
        
        # Check RAG tools
        rag_tool = self.get_tool("rag_search")
        if rag_tool and hasattr(rag_tool, 'retriever') and rag_tool.retriever is not None:
            results["rag_search_ready"] = True
        
        rag_context_tool = self.get_tool("rag_context_search")
        if rag_context_tool and hasattr(rag_context_tool, 'retriever') and rag_context_tool.retriever is not None:
            results["rag_context_search_ready"] = True
        
        # Check Student API tools
        profile_tool = self.get_tool("student_profile")
        if profile_tool and hasattr(profile_tool, 'api_service') and profile_tool.api_service is not None:
            results["student_api_ready"] = True
        
        # Log results
        all_ready = all(results.values())
        if all_ready:
            logger.info("✅ All tool dependencies verified and ready")
        else:
            logger.warning(f"⚠️ Some dependencies not ready: {results}")
        
        return results
    
    def get_tool_stats(self) -> Dict[str, Any]:
        """Get statistics for all tools"""
        stats = {
            "total_tools": len(self.tools),
            "tools_by_category": {},
            "tool_details": []
        }
        
        for tool_id, tool in self.tools.items():
            category = tool.category
            if category not in stats["tools_by_category"]:
                stats["tools_by_category"][category] = 0
            stats["tools_by_category"][category] += 1
            
            stats["tool_details"].append({
                "id": tool_id,
                "name": tool.name,
                "category": category,
                "requires_auth": tool.requires_auth,
                "stats": tool.get_stats()
            })
        
        return stats
    
    def reset_tool_stats(self):
        """Reset statistics for all tools"""
        for tool in self.tools.values():
            tool.call_count = 0
            tool.total_time = 0.0
            tool.error_count = 0
        logger.info("🔄 All tool stats reset")
    
    def get_tool_count(self) -> int:
        """Get total number of registered tools"""
        return len(self.tools)
    
    def list_tools(self) -> List[Dict[str, str]]:
        """List all tools with basic info"""
        return [
            {
                "id": tool_id,
                "name": tool.name,
                "description": tool.description[:100] + "..." if len(tool.description) > 100 else tool.description,
                "category": tool.category,
                "requires_auth": tool.requires_auth
            }
            for tool_id, tool in self.tools.items()
        ]