"""
Base Tool Class for BDU Agent Tools
Tất cả tools đều kế thừa từ class này
"""
import logging
from typing import Dict, Any, Optional, Type
from abc import ABC, abstractmethod
import time

# LangChain imports
from langchain.tools import BaseTool
from langchain.pydantic_v1 import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolInputSchema(BaseModel):
    """Base schema for tool inputs - có thể customize cho từng tool"""
    pass


class BDUBaseTool(BaseTool, ABC):
    """
    Base class cho tất cả BDU Agent Tools
    Cung cấp các functionality chung: logging, error handling, timing
    """
    
    # Metadata
    category: str = "general"  # Category: rag, student_api, utility
    requires_auth: bool = False  # Tool có cần authentication không?
    timeout: int = 30  # Timeout in seconds
    
    # JWT token (được inject từ bên ngoài)
    jwt_token: Optional[str] = None
    
    # Student profile (được inject từ bên ngoài)
    student_profile: Optional[Dict[str, Any]] = None
    
    # Statistics
    call_count: int = 0
    total_time: float = 0.0
    error_count: int = 0
    
    class Config:
        """Pydantic config"""
        arbitrary_types_allowed = True
    
    def _run(self, *args, **kwargs) -> str:
        """
        Override LangChain's _run method
        Thêm logging, timing, và error handling
        """
        start_time = time.time()
        self.call_count += 1
        
        tool_name = self.__class__.__name__
        logger.info(f"🔧 [{tool_name}] Tool called with args: {args}, kwargs: {kwargs}")
        
        try:
            # Check authentication if required
            if self.requires_auth and not self.jwt_token:
                error_msg = f"Tool {tool_name} requires authentication but no JWT token provided"
                logger.error(f"❌ {error_msg}")
                return self._format_error_response(error_msg)
            
            # Call the actual implementation
            result = self.execute(*args, **kwargs)
            
            # Track timing
            elapsed = time.time() - start_time
            self.total_time += elapsed
            
            logger.info(f"✅ [{tool_name}] Completed in {elapsed:.2f}s")
            
            return self._format_success_response(result)
            
        except Exception as e:
            self.error_count += 1
            elapsed = time.time() - start_time
            
            logger.error(f"❌ [{tool_name}] Error after {elapsed:.2f}s: {str(e)}")
            
            return self._format_error_response(str(e))
    
    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """
        Implement tool logic here
        Must be overridden by subclasses
        """
        raise NotImplementedError("Subclasses must implement execute()")
    
    def _format_success_response(self, result: Any) -> str:
        """
        Format successful result as string
        LangChain tools must return strings
        """
        if isinstance(result, str):
            return result
        elif isinstance(result, dict):
            # Format dict nicely
            return self._dict_to_text(result)
        elif isinstance(result, list):
            return "\n".join(str(item) for item in result)
        else:
            return str(result)
    
    def _format_error_response(self, error: str) -> str:
        """Format error message"""
        return f"❌ Error: {error}"
    
    def _dict_to_text(self, data: Dict[str, Any]) -> str:
        """Convert dict to readable text"""
        lines = []
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for k, v in value.items():
                    lines.append(f"  - {k}: {v}")
            elif isinstance(value, list):
                lines.append(f"{key}: {', '.join(str(v) for v in value)}")
            else:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)
    
    def set_jwt_token(self, token: str):
        """Set JWT token for authenticated tools"""
        self.jwt_token = token
    
    def set_student_profile(self, profile: Dict[str, Any]):
        """Set student profile"""
        self.student_profile = profile
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tool statistics"""
        avg_time = self.total_time / self.call_count if self.call_count > 0 else 0
        
        return {
            "tool_name": self.name,
            "category": self.category,
            "call_count": self.call_count,
            "error_count": self.error_count,
            "total_time": round(self.total_time, 2),
            "average_time": round(avg_time, 2),
            "success_rate": round((self.call_count - self.error_count) / self.call_count * 100, 2) if self.call_count > 0 else 0
        }
    
    async def _arun(self, *args, **kwargs) -> str:
        """Async version - fallback to sync"""
        return self._run(*args, **kwargs)


class ToolValidator:
    """
    Utility class to validate tool inputs
    """
    
    @staticmethod
    def validate_required_fields(data: Dict[str, Any], required_fields: list) -> tuple[bool, Optional[str]]:
        """
        Validate that required fields are present
        
        Returns:
            (is_valid, error_message)
        """
        missing = [field for field in required_fields if field not in data or not data[field]]
        
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"
        
        return True, None
    
    @staticmethod
    def validate_mssv(mssv: str) -> tuple[bool, Optional[str]]:
        """Validate MSSV format"""
        if not mssv:
            return False, "MSSV is empty"
        
        if not isinstance(mssv, str):
            return False, "MSSV must be a string"
        
        if len(mssv) < 6 or len(mssv) > 12:
            return False, "MSSV must be between 6-12 characters"
        
        return True, None
    
    @staticmethod
    def validate_date_format(date_str: str) -> tuple[bool, Optional[str]]:
        """Validate date format (YYYY-MM-DD)"""
        import re
        pattern = r'^\d{4}-\d{2}-\d{2}$'
        
        if not re.match(pattern, date_str):
            return False, f"Invalid date format: {date_str}. Expected YYYY-MM-DD"
        
        return True, None


# ========================
# Decorator for easy tool creation
# ========================

def bdu_tool(
    name: str,
    description: str,
    category: str = "general",
    requires_auth: bool = False
):
    """
    Decorator để tạo tool dễ dàng hơn
    
    Usage:
        @bdu_tool(
            name="my_tool",
            description="This is my tool",
            category="utility"
        )
        def my_tool_function(query: str) -> str:
            return f"Processed: {query}"
    """
    def decorator(func):
        class DynamicTool(BDUBaseTool):
            name = name
            description = description
            category = category
            requires_auth = requires_auth
            
            def execute(self, *args, **kwargs):
                return func(*args, **kwargs)
        
        return DynamicTool
    
    return decorator
