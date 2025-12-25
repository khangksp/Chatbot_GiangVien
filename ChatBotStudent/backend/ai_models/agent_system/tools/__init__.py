"""
Tools Package
Tất cả tools cho BDU Agent
"""
# --- Import cơ bản ---
from .base_tool import BDUBaseTool, ToolValidator, bdu_tool
from .tool_registry import ToolRegistry  # ✅ CHỈ IMPORT 1 LẦN TỪ ĐÂY

# --- Import các tool cụ thể ---
from .rag_tool import RAGSearchTool, RAGContextSearchTool
from .student_tools import (
    StudentProfileTool,
    StudentScheduleTool,
    StudentGradesTool,
    StudentTuitionTool,      # ✅ TÊN ĐÚNG TỪ FILE ĐÚNG
    StudentCreditsTool,      # ✅ TÊN ĐÚNG TỪ FILE ĐÚNG
    StudentNewsTool          # ✅ TÊN ĐÚNG TỪ FILE ĐÚNG
)

# ❌ XÓA HOÀN TOÀN DÒNG NÀY:
# from .tool_registry import ToolRegistry, FeesTool, NewsTool


# --- Định nghĩa __all__ để export ---
__all__ = [
    # Base
    "BDUBaseTool",
    "ToolValidator",
    "bdu_tool",
    
    # RAG Tools
    "RAGSearchTool",
    "RAGContextSearchTool",
    
    # Student API Tools
    "StudentProfileTool",
    "StudentScheduleTool",
    "StudentGradesTool",
    "StudentTuitionTool",      # ✅ CẬP NHẬT TÊN TRONG NÀY
    "StudentCreditsTool",      # ✅ CẬP NHẬT TÊN TRONG NÀY
    "StudentNewsTool",         # ✅ CẬP NHẬT TÊN TRONG NÀY
    
    # Registry
    "ToolRegistry"
]