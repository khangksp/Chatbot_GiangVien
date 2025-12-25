"""
Agent System Configuration
Cấu hình tập trung cho toàn bộ hệ thống Agent
"""
import os
from typing import Dict, Any
from dataclasses import dataclass, field

@dataclass
class AgentConfig:
    """Cấu hình cho BDU Student Agent"""
    
    # ========================
    # LLM Configuration
    # ========================
    model_name: str = "gemini-2.5-flash"  # ✅ FIXED: Đổi từ gemini-1.5-pro-latest
    temperature: float = 0.3  # Thấp để có câu trả lời ổn định
    max_tokens: int = 2048
    top_p: float = 0.95
    top_k: int = 40
    
    # ========================
    # Memory Configuration
    # ========================
    memory_type: str = "buffer"  # Options: buffer, summary, entity
    max_memory_messages: int = 10  # Giữ 10 câu gần nhất
    memory_key: str = "chat_history"
    
    # Entity Memory (Nhớ tên người, địa điểm, môn học)
    entity_memory_enabled: bool = True
    entity_store_type: str = "dict"  # Options: dict, redis, mongodb
    
    # Conversation Summary (Cho cuộc hội thoại dài)
    summary_enabled: bool = True
    summary_threshold: int = 20  # Tóm tắt sau 20 tin nhắn
    
    # ========================
    # Agent Configuration
    # ========================
    agent_type: str = "chat-conversational-react-description"
    max_iterations: int = 5  # Tối đa 5 bước reasoning
    early_stopping_method: str = "force"  # ✅ FIXED: Đổi từ "generate"
    handle_parsing_errors: bool = True
    
    # Verbose mode (cho debugging)
    verbose: bool = True  # Set False trong production
    
    # ========================
    # Tool Configuration
    # ========================
    tool_timeout: int = 30  # Timeout cho mỗi tool (seconds)
    max_tool_calls: int = 10  # Tối đa số lần gọi tool trong 1 query
    
    # RAG Tool settings
    rag_top_k: int = 5
    rag_min_confidence: float = 0.6
    
    # Student API settings
    api_timeout: int = 15
    api_retry_attempts: int = 2
    
    # ========================
    # System Prompts
    # ========================
    system_prompt_template: str = """Bạn là ChatBDU, trợ lý AI thông minh của Đại học Bình Dương.

🎯 VAI TRÒ CỦA BẠN:
- Hỗ trợ sinh viên về mọi vấn đề liên quan đến học tập, lịch học, điểm số, học phí
- Trả lời câu hỏi về thông tin trường, quy định, thủ tục
- Tư vấn và định hướng sinh viên

💡 NGUYÊN TẮC HOẠT ĐỘNG:
1. Sử dụng tools để tìm thông tin chính xác nhất
2. Luôn ưu tiên dữ liệu từ API sinh viên cho thông tin cá nhân
3. Dùng RAG tool cho kiến thức chung về trường
4. Nếu không chắc chắn, hãy hỏi lại thay vì đoán
5. Trả lời ngắn gọn, súc tích, thân thiện

📋 CÁC TOOLS AVAILABLE:
{tools}

🔧 FORMAT SỬ DỤNG TOOLS:
{{
    "action": "tên_tool",
    "action_input": "input cho tool"
}}

Hãy suy luận từng bước và chọn tool phù hợp nhất!
"""

    # Tool description template
    tool_description_template: str = """Tool: {name}
Description: {description}
Args: {args}
"""
    
    # ========================
    # Vietnamese Settings
    # ========================
    language: str = "vi"
    tone: str = "friendly"  # Options: formal, friendly, casual
    
    # Personal pronouns (xưng hô)
    user_pronouns: list = field(default_factory=lambda: ["bạn", "cậu", "{first_name}"])
    bot_pronouns: list = field(default_factory=lambda: ["mình", "tớ"])
    
    # ========================
    # Error Handling
    # ========================
    error_max_retries: int = 2
    error_fallback_enabled: bool = True
    error_messages: Dict[str, str] = field(default_factory=lambda: {
        "timeout": "Xin lỗi bạn, hệ thống đang phản hồi chậm. Vui lòng thử lại sau!",
        "api_error": "Mình gặp khó khăn khi truy xuất thông tin. Bạn có thể thử lại không?",
        "parsing_error": "Mình chưa hiểu rõ câu hỏi của bạn. Bạn có thể diễn đạt lại được không?",
        "tool_error": "Công cụ tìm kiếm gặp vấn đề. Mình sẽ thử cách khác!",
        "unknown": "Đã có lỗi xảy ra. Vui lòng liên hệ bộ phận kỹ thuật nếu vấn đề vẫn tiếp diễn."
    })
    
    # ========================
    # Logging & Monitoring
    # ========================
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    log_conversations: bool = True
    log_tool_calls: bool = True
    
    # LangSmith (optional - cho production monitoring)
    langsmith_enabled: bool = False
    langsmith_api_key: str = os.getenv("LANGSMITH_API_KEY", "")
    langsmith_project: str = "bdu-chatbot"
    
    # ========================
    # Rate Limiting
    # ========================
    rate_limit_enabled: bool = True
    max_requests_per_minute: int = 60
    max_requests_per_hour: int = 1000
    
    # ========================
    # Caching
    # ========================
    cache_enabled: bool = True
    cache_ttl: int = 3600  # 1 hour
    cache_backend: str = "memory"  # Options: memory, redis
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "memory_type": self.memory_type,
            "agent_type": self.agent_type,
            "verbose": self.verbose
        }
    
    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Load configuration from environment variables"""
        return cls(
            model_name=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.3")),
            verbose=os.getenv("AGENT_VERBOSE", "true").lower() == "true",
            langsmith_enabled=os.getenv("LANGSMITH_ENABLED", "false").lower() == "true"
        )


# ========================
# Default Configuration Instance
# ========================
default_config = AgentConfig()


# ========================
# Development vs Production Configs
# ========================
class DevelopmentConfig(AgentConfig):
    """Configuration for development environment"""
    verbose: bool = True
    log_level: str = "DEBUG"
    cache_enabled: bool = False
    

class ProductionConfig(AgentConfig):
    """Configuration for production environment"""
    verbose: bool = False
    log_level: str = "WARNING"
    cache_enabled: bool = True
    rate_limit_enabled: bool = True
    langsmith_enabled: bool = True


def get_config(environment: str = "development") -> AgentConfig:
    """
    Get configuration based on environment
    
    Args:
        environment: "development" or "production"
    
    Returns:
        AgentConfig instance
    """
    if environment == "production":
        return ProductionConfig()
    else:
        return DevelopmentConfig()