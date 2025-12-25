"""
BDU Agent System
LangChain-based Agent System for BDU Chatbot
"""
from .core import (
    AgentConfig,
    get_config,
    BDUStudentAgent,
    create_agent,
    get_agent,
    EnhancedMemoryManager
)
from .tools import (
    ToolRegistry,
    RAGSearchTool,
    StudentProfileTool,
    StudentScheduleTool,
    StudentGradesTool
)

__version__ = "1.0.0"

__all__ = [
    # Core
    "AgentConfig",
    "get_config",
    "BDUStudentAgent",
    "create_agent",
    "get_agent",
    "EnhancedMemoryManager",
    
    # Tools
    "ToolRegistry",
    "RAGSearchTool",
    "StudentProfileTool",
    "StudentScheduleTool",
    "StudentGradesTool"
]
