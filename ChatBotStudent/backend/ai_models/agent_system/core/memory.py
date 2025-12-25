"""
Advanced Memory Management for BDU Student Agent
Hệ thống quản lý bộ nhớ đa cấp với Entity Memory và Conversation Summary
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import json

# LangChain imports
from langchain.memory import (
    ConversationBufferMemory,
    ConversationSummaryMemory,
    ConversationEntityMemory,
    CombinedMemory
)
from langchain.memory.chat_message_histories import ChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage
from langchain.schema import BaseMemory

logger = logging.getLogger(__name__)


class StudentContextMemory:
    """
    Memory đặc biệt cho context sinh viên
    Lưu trữ thông tin profile, lịch sử tương tác
    """
    
    def __init__(self):
        self.student_contexts: Dict[str, Dict[str, Any]] = {}
        logger.info("✅ StudentContextMemory initialized")
    
    def set_student_context(self, session_id: str, student_data: Dict[str, Any]):
        """
        Lưu context của sinh viên vào memory
        
        Args:
            session_id: ID của session
            student_data: Dict chứa profile sinh viên
        """
        self.student_contexts[session_id] = {
            "profile": student_data,
            "last_updated": datetime.now().isoformat(),
            "interaction_count": self.student_contexts.get(session_id, {}).get("interaction_count", 0) + 1
        }
        logger.info(f"💾 Student context saved for session: {session_id}")
    
    def get_student_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Lấy context của sinh viên"""
        return self.student_contexts.get(session_id)
    
    def clear_student_context(self, session_id: str):
        """Xóa context của sinh viên"""
        if session_id in self.student_contexts:
            del self.student_contexts[session_id]
            logger.info(f"🗑️ Student context cleared for session: {session_id}")


class EnhancedMemoryManager:
    """
    Memory Manager nâng cao với multi-level memory
    - Buffer Memory: Nhớ 10 câu gần nhất
    - Entity Memory: Nhớ người, địa điểm, môn học
    - Summary Memory: Tóm tắt cuộc hội thoại dài
    - Student Context: Context đặc biệt cho sinh viên
    """
    
    def __init__(self, config, llm):
        """
        Args:
            config: AgentConfig instance
            llm: LangChain LLM instance (Gemini)
        """
        self.config = config
        self.llm = llm
        
        # Memory cho từng session
        self.session_memories: Dict[str, BaseMemory] = {}
        
        # Student context memory
        self.student_memory = StudentContextMemory()
        
        # Entity cache (lưu các entity đã trích xuất)
        self.entity_cache: Dict[str, Dict[str, List[str]]] = {}
        
        logger.info("✅ EnhancedMemoryManager initialized")
    
    def create_memory_for_session(self, session_id: str) -> BaseMemory:
        """
        Tạo memory instance cho một session mới
        Sử dụng CombinedMemory để kết hợp nhiều loại memory
        """
        try:
            # 1. Buffer Memory - Nhớ câu hỏi/trả lời gần nhất
            buffer_memory = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True,
                input_key="input",  # ✅ FIXED: Thêm input_key
                output_key="output",  # ✅ FIXED: Thêm output_key
                human_prefix="Student",
                ai_prefix="ChatBDU"
            )
            
            memories = [buffer_memory]
            
            # 2. Entity Memory - Nhớ tên người, môn học, địa điểm
            if self.config.entity_memory_enabled:
                entity_memory = ConversationEntityMemory(
                    llm=self.llm,
                    input_key="input",  # ✅ FIXED: Thêm input_key
                    memory_key="entities",
                    return_messages=True,
                    human_prefix="Student",
                    ai_prefix="ChatBDU"
                )
                memories.append(entity_memory)
                logger.info(f"✅ Entity Memory enabled for session: {session_id}")
            
            # 3. Summary Memory - Tóm tắt khi hội thoại quá dài
            if self.config.summary_enabled:
                summary_memory = ConversationSummaryMemory(
                    llm=self.llm,
                    input_key="input",  # ✅ FIXED: Thêm input_key
                    memory_key="summary",
                    return_messages=True,
                    human_prefix="Student",
                    ai_prefix="ChatBDU"
                )
                memories.append(summary_memory)
                logger.info(f"✅ Summary Memory enabled for session: {session_id}")
            
            # Combine all memories
            if len(memories) > 1:
                combined_memory = CombinedMemory(memories=memories)
                self.session_memories[session_id] = combined_memory
                logger.info(f"✅ Combined Memory created for session: {session_id} with {len(memories)} memory types")
            else:
                self.session_memories[session_id] = buffer_memory
                logger.info(f"✅ Buffer Memory created for session: {session_id}")
            
            return self.session_memories[session_id]
            
        except Exception as e:
            logger.error(f"❌ Error creating memory for session {session_id}: {e}", exc_info=True)
            # Fallback to simple buffer memory
            buffer_memory = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True,
                input_key="input",  # ✅ FIXED: Thêm input_key
                output_key="output"  # ✅ FIXED: Thêm output_key
            )
            self.session_memories[session_id] = buffer_memory
            logger.warning(f"⚠️ Using fallback buffer memory for session: {session_id}")
            return buffer_memory
    
    def get_memory(self, session_id: str) -> BaseMemory:
        """
        Lấy memory instance cho session
        Tự động tạo nếu chưa có
        """
        if session_id not in self.session_memories:
            logger.info(f"🆕 Creating new memory for session: {session_id}")
            return self.create_memory_for_session(session_id)
        
        logger.debug(f"📖 Using existing memory for session: {session_id}")
        return self.session_memories[session_id]
    
    def add_user_message(self, session_id: str, message: str):
        """Thêm user message vào memory"""
        memory = self.get_memory(session_id)
        try:
            memory.chat_memory.add_user_message(message)
            logger.debug(f"💬 User message added to session {session_id}")
        except Exception as e:
            logger.error(f"❌ Error adding user message: {e}")
    
    def add_ai_message(self, session_id: str, message: str):
        """Thêm AI message vào memory"""
        memory = self.get_memory(session_id)
        try:
            memory.chat_memory.add_ai_message(message)
            logger.debug(f"🤖 AI message added to session {session_id}")
        except Exception as e:
            logger.error(f"❌ Error adding AI message: {e}")
    
    def get_conversation_context(self, session_id: str) -> Dict[str, Any]:
        """
        Lấy toàn bộ context của cuộc hội thoại
        Bao gồm: history, entities, summary, student_profile
        """
        memory = self.get_memory(session_id)
        context = {}
        
        try:
            # Get all memory variables
            memory_vars = memory.load_memory_variables({})
            context.update(memory_vars)
            
            # Add student context if available
            student_context = self.student_memory.get_student_context(session_id)
            if student_context:
                context["student_profile"] = student_context.get("profile", {})
            
            # Add entity cache if available
            if session_id in self.entity_cache:
                context["cached_entities"] = self.entity_cache[session_id]
            
            logger.debug(f"📋 Context loaded for session {session_id}: {list(context.keys())}")
            
        except Exception as e:
            logger.error(f"❌ Error loading context for session {session_id}: {e}")
        
        return context
    
    def extract_and_cache_entities(self, session_id: str, text: str) -> Dict[str, List[str]]:
        """
        Trích xuất và cache các entities từ text
        Entities bao gồm: tên người, môn học, địa điểm, thời gian
        """
        import re
        
        entities = {
            "person_names": [],
            "subjects": [],
            "locations": [],
            "dates": []
        }
        
        # Extract person names (Capitalized words)
        person_pattern = r'\b([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+(?:\s+[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+)*)\b'
        persons = re.findall(person_pattern, text)
        entities["person_names"] = list(set(persons))
        
        # Extract dates
        date_pattern = r'\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}-\d{1,2}-\d{2,4})\b'
        dates = re.findall(date_pattern, text)
        entities["dates"] = list(set(dates))
        
        # Cache entities
        if session_id not in self.entity_cache:
            self.entity_cache[session_id] = entities
        else:
            # Merge with existing cache
            for key in entities:
                existing = self.entity_cache[session_id].get(key, [])
                self.entity_cache[session_id][key] = list(set(existing + entities[key]))
        
        logger.debug(f"🔍 Entities extracted for session {session_id}: {entities}")
        return entities
    
    def set_student_context(self, session_id: str, student_data: Dict[str, Any]):
        """Set student profile context"""
        self.student_memory.set_student_context(session_id, student_data)
    
    def clear_session_memory(self, session_id: str):
        """Clear all memory for a session"""
        if session_id in self.session_memories:
            try:
                self.session_memories[session_id].clear()
                del self.session_memories[session_id]
            except Exception as e:
                logger.error(f"❌ Error clearing memory: {e}")
        
        if session_id in self.entity_cache:
            del self.entity_cache[session_id]
        
        self.student_memory.clear_student_context(session_id)
        
        logger.info(f"🗑️ All memory cleared for session: {session_id}")
    
    def get_memory_stats(self, session_id: str) -> Dict[str, Any]:
        """Get memory statistics for debugging"""
        stats = {
            "session_id": session_id,
            "has_memory": session_id in self.session_memories,
            "has_student_context": self.student_memory.get_student_context(session_id) is not None,
            "cached_entities": len(self.entity_cache.get(session_id, {})),
            "memory_type": type(self.session_memories.get(session_id)).__name__ if session_id in self.session_memories else None
        }
        
        if session_id in self.session_memories:
            try:
                memory_vars = self.session_memories[session_id].load_memory_variables({})
                if "chat_history" in memory_vars:
                    stats["message_count"] = len(memory_vars["chat_history"])
            except Exception as e:
                logger.error(f"❌ Error getting memory stats: {e}")
        
        return stats


class SimpleMemoryFallback:
    """
    Simple fallback memory khi LangChain memory gặp lỗi
    Chỉ lưu trữ đơn giản trong dict
    """
    
    def __init__(self, max_messages: int = 10):
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        self.max_messages = max_messages
        logger.info("✅ SimpleMemoryFallback initialized")
    
    def add_message(self, session_id: str, role: str, content: str):
        """Add message to conversation"""
        if session_id not in self.conversations:
            self.conversations[session_id] = []
        
        self.conversations[session_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        
        # Trim to max_messages
        if len(self.conversations[session_id]) > self.max_messages:
            self.conversations[session_id] = self.conversations[session_id][-self.max_messages:]
        
        logger.debug(f"💾 Fallback memory: Added {role} message to {session_id}")
    
    def get_conversation(self, session_id: str) -> List[Dict[str, str]]:
        """Get conversation history"""
        return self.conversations.get(session_id, [])
    
    def clear_conversation(self, session_id: str):
        """Clear conversation"""
        if session_id in self.conversations:
            del self.conversations[session_id]
            logger.info(f"🗑️ Fallback memory cleared for session: {session_id}")