"""
BDU Student Agent - Core Agent Implementation
Agent thông minh với Gemini + LangChain cho sinh viên BDU

✅ FIXED VERSION - JWT Token Cache Invalidation
"""
import logging
import time
from typing import Dict, List, Any, Optional, Tuple
import os

# LangChain imports
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import AgentAction, AgentFinish
from langchain.callbacks.base import BaseCallbackHandler

# Internal imports
from .config import AgentConfig, get_config
from .memory import EnhancedMemoryManager, SimpleMemoryFallback
from ..tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentCallbackHandler(BaseCallbackHandler):
    """
    Custom callback handler để track agent actions
    Hữu ích cho debugging và monitoring
    """
    
    def __init__(self):
        self.actions: List[Dict[str, Any]] = []
        self.start_time = None
    
    def on_agent_action(self, action: AgentAction, **kwargs):
        """Called when agent takes an action (calls a tool)"""
        logger.info(f"🔧 Agent Action: {action.tool} with input: {action.tool_input}")
        self.actions.append({
            "tool": action.tool,
            "input": action.tool_input,
            "timestamp": time.time()
        })
    
    def on_agent_finish(self, finish: AgentFinish, **kwargs):
        """Called when agent finishes"""
        logger.info(f"✅ Agent Finished with output")
        
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs):
        """Called when a tool starts"""
        tool_name = serialized.get("name", "unknown")
        logger.debug(f"🛠️ Tool Start: {tool_name}")
    
    def on_tool_end(self, output: str, **kwargs):
        """Called when a tool ends"""
        logger.debug(f"✅ Tool End: Output length = {len(str(output))}")
    
    def on_tool_error(self, error: Exception, **kwargs):
        """Called when a tool errors"""
        logger.error(f"❌ Tool Error: {str(error)}")
    
    def get_action_summary(self) -> Dict[str, Any]:
        """Get summary of all actions taken"""
        return {
            "total_actions": len(self.actions),
            "actions": self.actions,
            "total_time": time.time() - self.start_time if self.start_time else 0
        }


class BDUStudentAgent:
    """
    Main Agent class cho BDU Chatbot
    Sử dụng Gemini + LangChain với tools và memory
    """
    
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        gemini_api_key: Optional[str] = None
    ):
        """
        Initialize BDU Student Agent
        
        Args:
            config: Agent configuration (optional)
            gemini_api_key: Gemini API key (optional, can be from env)
        """
        # Load configuration
        self.config = config or get_config("development")
        logger.info("🚀 Initializing BDU Student Agent...")
        
        # Setup Gemini LLM
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not self.gemini_api_key:
            raise ValueError("❌ GEMINI_API_KEY not found! Please set it in environment or pass as argument.")
        
        self.llm = self._setup_llm()
        
        # Setup Memory Manager
        self.memory_manager = EnhancedMemoryManager(
            config=self.config,
            llm=self.llm
        )
        
        # Setup Tool Registry
        self.tool_registry = ToolRegistry()
        
        # Agent executor (will be created per session)
        self.agent_executors: Dict[str, AgentExecutor] = {}
        
        # ✅ FIX: Track JWT tokens per session để detect thay đổi
        self.session_jwt_tokens: Dict[str, Optional[str]] = {}
        
        # Fallback memory (nếu LangChain memory fail)
        self.fallback_memory = SimpleMemoryFallback()
        
        # Statistics
        self.stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "total_tool_calls": 0,
            "average_response_time": 0.0,
            "executor_cache_hits": 0,  # ✅ Thêm metric
            "executor_cache_invalidations": 0  # ✅ Thêm metric
        }
        
        logger.info("✅ BDU Student Agent initialized successfully!")
    
    @staticmethod
    def _safe_get_profile_field(profile, field_name: str, default: str = "") -> str:
        """
        Safely get field from profile (dict or object)
        """
        if profile is None:
            return default
        
        if isinstance(profile, dict):
            return profile.get(field_name, default)
        
        return getattr(profile, field_name, default)
    
    def _setup_llm(self) -> ChatGoogleGenerativeAI:
        """Setup Gemini LLM với LangChain"""
        try:
            llm = ChatGoogleGenerativeAI(
                model=self.config.model_name,
                google_api_key=self.gemini_api_key,
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_tokens,
                top_p=self.config.top_p,
                top_k=self.config.top_k,
                convert_system_message_to_human=True  # Important for Gemini
            )
            logger.info(f"✅ Gemini LLM initialized: {self.config.model_name}")
            return llm
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini LLM: {e}")
            raise
    
    def _create_agent_prompt(self, student_profile: Optional[Dict[str, Any]] = None) -> PromptTemplate:
        """
        Tạo system prompt cho Agent
        Có thể customize dựa trên student profile
        """
        # Base system instructions
        system_instructions = """Bạn là ChatBDU, trợ lý AI thông minh của Đại học Bình Dương.

🎯 VAI TRÒ:
Hỗ trợ sinh viên về học tập, lịch học, điểm số, học phí, thông tin trường, quy định và thủ tục.

💡 NGUYÊN TẮC:
1. Sử dụng tools để tìm thông tin chính xác
2. Ưu tiên API sinh viên cho thông tin cá nhân
3. Dùng RAG tool cho kiến thức chung
4. Hỏi lại nếu không chắc chắn
5. Trả lời ngắn gọn, thân thiện

🔧 SỬ DỤNG TOOLS:
- Luôn suy luận xem tool nào phù hợp nhất
- Có thể gọi nhiều tools liên tiếp nếu cần
- Format: Action: [tool_name]
         Action Input: [input_string]

"""
        
        # Add student context if available
        if student_profile:
            name = self._safe_get_profile_field(student_profile, "full_name")
            mssv = self._safe_get_profile_field(student_profile, "mssv")
            class_name = self._safe_get_profile_field(student_profile, "class_name")
            
            system_instructions += f"""
👤 THÔNG TIN SINH VIÊN HIỆN TẠI:
- Tên: {name}
- MSSV: {mssv}
- Lớp: {class_name}

Khi sinh viên hỏi về "tôi", "mình", dùng thông tin này.
"""
        
        # ReAct prompt template
        template = system_instructions + """

TOOLS:
------
Bạn có các tools sau:

{tools}

TOOL NAMES: {tool_names}

FORMAT:
------
Hãy sử dụng format sau:

Question: câu hỏi đầu vào bạn cần trả lời
Thought: bạn nên suy nghĩ về cần làm gì
Action: tool cần sử dụng, phải là một trong [{tool_names}]
Action Input: input cho tool
Observation: kết quả từ tool
... (có thể lặp lại Thought/Action/Observation nhiều lần)
Thought: Tôi đã có đủ thông tin để trả lời
Final Answer: câu trả lời cuối cùng cho sinh viên

BEGIN!

Previous conversation history:
{chat_history}

Question: {input}
Thought: {agent_scratchpad}
"""
        
        return PromptTemplate(
            input_variables=["input", "chat_history", "agent_scratchpad", "tools", "tool_names"],
            template=template
        )
    
    def get_or_create_agent_executor(
        self,
        session_id: str,
        student_profile: Optional[Dict[str, Any]] = None,
        jwt_token: Optional[str] = None
    ) -> AgentExecutor:
        """
        Lấy hoặc tạo AgentExecutor cho session
        Mỗi session có agent riêng với memory riêng
        
        ✅ FIX: Invalidate cache nếu JWT token thay đổi
        """
        # ✅ FIX: Kiểm tra xem JWT token có thay đổi không
        cached_token = self.session_jwt_tokens.get(session_id)
        token_changed = (cached_token != jwt_token)
        
        # ✅ DEBUG: Log chi tiết
        logger.info(f"🔍 Cache check for session: {session_id}")
        logger.info(f"   - Cached token exists: {cached_token is not None}")
        logger.info(f"   - New token exists: {jwt_token is not None}")
        logger.info(f"   - Token changed: {token_changed}")
        logger.info(f"   - Executor in cache: {session_id in self.agent_executors}")
        
        # Nếu có executor được cache VÀ token không đổi → dùng lại
        if session_id in self.agent_executors and not token_changed:
            logger.info(f"♻️ Using cached agent executor for session: {session_id}")
            self.stats["executor_cache_hits"] += 1
            return self.agent_executors[session_id]
        
        # Nếu token thay đổi → xóa executor cũ
        if token_changed and session_id in self.agent_executors:
            logger.warning(f"🔄 JWT token changed for session {session_id}, invalidating cached executor")
            logger.warning(f"   - Old token: {cached_token[:20] if cached_token else 'None'}...")
            logger.warning(f"   - New token: {jwt_token[:20] if jwt_token else 'None'}...")
            del self.agent_executors[session_id]
            self.stats["executor_cache_invalidations"] += 1
        
        try:
            # Get tools for this session với JWT token MỚI
            logger.info(f"🔧 Creating NEW agent executor for session: {session_id}")
            logger.info(f"   - JWT token: {'✅ Present (' + str(jwt_token[:30]) + '...)' if jwt_token else '❌ None'}")
            logger.info(f"   - Student profile: {'✅ Present' if student_profile else '❌ None'}")
            
            tools = self.tool_registry.get_tools_for_session(
                jwt_token=jwt_token,
                student_profile=student_profile
            )
            
            logger.info(f"✅ Got {len(tools)} tools with JWT token properly injected")
            
            # Get memory for this session
            memory = self.memory_manager.get_memory(session_id)
            
            # Set student context if available
            if student_profile:
                self.memory_manager.set_student_context(session_id, student_profile)
            
            # Create prompt
            prompt = self._create_agent_prompt(student_profile)
            
            # Create ReAct agent
            agent = create_react_agent(
                llm=self.llm,
                tools=tools,
                prompt=prompt
            )
            
            # Create callback handler
            callback = AgentCallbackHandler()
            callback.start_time = time.time()
            
            # Create agent executor
            agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                memory=memory,
                verbose=self.config.verbose,
                max_iterations=self.config.max_iterations,
                early_stopping_method=self.config.early_stopping_method,
                handle_parsing_errors=self.config.handle_parsing_errors,
                callbacks=[callback]
            )
            
            # Cache the executor
            self.agent_executors[session_id] = agent_executor
            
            # ✅ FIX: Lưu JWT token hiện tại để track thay đổi
            self.session_jwt_tokens[session_id] = jwt_token
            
            logger.info(f"✅ Agent executor created and cached for session: {session_id}")
            return agent_executor
            
        except Exception as e:
            logger.error(f"❌ Failed to create agent executor for session {session_id}: {e}", exc_info=True)
            raise
    
    def process_query(
        self,
        query: str,
        session_id: str,
        jwt_token: Optional[str] = None,
        student_profile: Optional[Dict[str, Any]] = None,
        document_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process user query với Agent
        
        Args:
            query: User's question
            session_id: Session ID
            jwt_token: JWT token (for student API calls)
            student_profile: Student profile data
            document_text: Optional document context
        
        Returns:
            Dict with response and metadata
        """
        start_time = time.time()
        self.stats["total_queries"] += 1
        
        logger.info(f"🎯 Processing query: '{query}' (session: {session_id})")
        
        try:
            # Get or create agent executor
            agent_executor = self.get_or_create_agent_executor(
                session_id=session_id,
                student_profile=student_profile,
                jwt_token=jwt_token
            )
            
            # Prepare input
            agent_input = {
                "input": query
            }
            
            # Add document context if provided
            if document_text:
                agent_input["document_context"] = document_text
            
            # Run agent
            try:
                result = agent_executor.invoke(agent_input)
                response_text = result.get("output", "")
                
                # Extract intermediate steps for debugging
                intermediate_steps = result.get("intermediate_steps", [])
                
                processing_time = time.time() - start_time
                self.stats["successful_queries"] += 1
                self.stats["total_tool_calls"] += len(intermediate_steps)
                
                # Update average response time
                total = self.stats["total_queries"]
                avg = self.stats["average_response_time"]
                self.stats["average_response_time"] = (avg * (total - 1) + processing_time) / total
                
                logger.info(f"✅ Query processed successfully in {processing_time:.2f}s")
                
                return {
                    "status": "success",
                    "response": response_text,
                    "session_id": session_id,
                    "processing_time": processing_time,
                    "method": "langchain_agent",
                    "tools_used": [step[0].tool for step in intermediate_steps] if intermediate_steps else [],
                    "confidence": 0.9,  # High confidence when agent completes
                    "metadata": {
                        "intermediate_steps": len(intermediate_steps),
                        "model": self.config.model_name
                    }
                }
                
            except Exception as e:
                logger.error(f"❌ Agent execution error: {e}", exc_info=True)
                self.stats["failed_queries"] += 1
                
                # Fallback response
                return self._get_error_response(
                    error=e,
                    query=query,
                    session_id=session_id,
                    processing_time=time.time() - start_time
                )
        
        except Exception as e:
            logger.error(f"❌ Critical error in process_query: {e}", exc_info=True)
            self.stats["failed_queries"] += 1
            
            return {
                "status": "error",
                "response": self.config.error_messages["unknown"],
                "session_id": session_id,
                "processing_time": time.time() - start_time,
                "method": "error_fallback",
                "confidence": 0.0,
                "error": str(e)
            }
    
    def _get_error_response(
        self,
        error: Exception,
        query: str,
        session_id: str,
        processing_time: float
    ) -> Dict[str, Any]:
        """Generate appropriate error response"""
        error_str = str(error).lower()
        
        # Determine error type
        if "timeout" in error_str:
            message = self.config.error_messages["timeout"]
        elif "parsing" in error_str:
            message = self.config.error_messages["parsing_error"]
        elif "tool" in error_str:
            message = self.config.error_messages["tool_error"]
        elif "api" in error_str:
            message = self.config.error_messages["api_error"]
        else:
            message = self.config.error_messages["unknown"]
        
        return {
            "status": "error",
            "response": message,
            "session_id": session_id,
            "processing_time": processing_time,
            "method": "error_handler",
            "confidence": 0.3,
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
    
    def clear_session(self, session_id: str):
        """Clear all data for a session"""
        # Clear memory
        self.memory_manager.clear_session_memory(session_id)
        
        # Remove agent executor
        if session_id in self.agent_executors:
            del self.agent_executors[session_id]
            logger.info(f"🗑️ Cleared executor for session: {session_id}")
        
        # ✅ FIX: Xóa tracked JWT token
        if session_id in self.session_jwt_tokens:
            del self.session_jwt_tokens[session_id]
            logger.info(f"🗑️ Cleared tracked token for session: {session_id}")
        
        logger.info(f"✅ Session fully cleared: {session_id}")
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get statistics for a session"""
        memory_stats = self.memory_manager.get_memory_stats(session_id)
        
        return {
            "session_id": session_id,
            "has_agent": session_id in self.agent_executors,
            "has_jwt_token": session_id in self.session_jwt_tokens,
            "memory": memory_stats
        }
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get overall system statistics"""
        return {
            "agent_config": self.config.to_dict(),
            "statistics": self.stats,
            "active_sessions": len(self.agent_executors),
            "registered_tools": self.tool_registry.get_tool_count(),
            "memory_type": self.config.memory_type,
            "model": self.config.model_name
        }


# ========================
# Convenience Functions
# ========================

def create_agent(
    gemini_api_key: Optional[str] = None,
    environment: str = "development"
) -> BDUStudentAgent:
    """
    Convenience function to create agent
    
    Args:
        gemini_api_key: Gemini API key (optional)
        environment: "development" or "production"
    
    Returns:
        BDUStudentAgent instance
    """
    config = get_config(environment)
    return BDUStudentAgent(config=config, gemini_api_key=gemini_api_key)


# ========================
# Global Agent Instance (Singleton pattern)
# ========================
_global_agent: Optional[BDUStudentAgent] = None

def get_agent() -> BDUStudentAgent:
    """Get global agent instance (create if not exists)"""
    global _global_agent
    if _global_agent is None:
        _global_agent = create_agent()
    return _global_agent