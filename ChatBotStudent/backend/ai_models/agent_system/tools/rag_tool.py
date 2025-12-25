"""
RAG Tool - Search Knowledge Base
Tool để tìm kiếm thông tin từ knowledge base (QA database)
"""
import logging
from typing import Dict, Any, Optional, List
from langchain.pydantic_v1 import Field

from .base_tool import BDUBaseTool

logger = logging.getLogger(__name__)


class RAGSearchTool(BDUBaseTool):
    """
    Tool to search knowledge base using semantic search
    Sử dụng SBERT + FAISS retriever hiện có
    """
    
    name: str = "search_knowledge_base"
    description: str = """Tìm kiếm thông tin trong knowledge base của trường BDU.
    
    Sử dụng tool này khi:
    - Sinh viên hỏi về quy định, thủ tục của trường
    - Câu hỏi về thông tin chung (không phải thông tin cá nhân)
    - Câu hỏi về giảng viên, khoa, phòng ban
    - Hướng dẫn các thủ tục hành chính
    
    Input: Câu hỏi cần tìm (string)
    Output: Câu trả lời từ knowledge base
    
    Ví dụ:
    - "Thầy Hiệp dạy môn gì?" → search_knowledge_base("Thầy Hiệp dạy môn gì?")
    - "Làm thế nào để đăng ký môn học?" → search_knowledge_base("đăng ký môn học")
    """
    
    category: str = "rag"
    requires_auth: bool = False
    
    # Injected dependencies (được set từ bên ngoài)
    retriever: Optional[Any] = None  # ChatbotAI instance
    reranker: Optional[Any] = None  # SemanticReRanker instance
    
    # Configuration
    top_k: int = 5
    min_confidence: float = 0.6
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str) -> str:
        """
        Execute RAG search
        
        Args:
            query: User's question
            
        Returns:
            Answer from knowledge base
        """
        if not self.retriever:
            return "❌ RAG retriever not initialized"
        
        try:
            logger.info(f"🔍 RAG Search for: '{query}'")
            
            # Step 1: Semantic search
            candidates = self.retriever.semantic_search_top_k(
                query=query,
                top_k=self.top_k * 2  # Get more for reranking
            )
            
            if not candidates:
                return "Xin lỗi, mình không tìm thấy thông tin về vấn đề này trong knowledge base."
            
            logger.info(f"📋 Found {len(candidates)} candidates")
            
            # Step 2: Rerank if reranker available
            if self.reranker:
                try:
                    reranked = self.reranker.rerank_with_context(
                        query=query,
                        candidates=candidates,
                        session_context={}
                    )
                    if reranked:
                        candidates = reranked[:self.top_k]
                        logger.info(f"✅ Reranked to top {len(candidates)} results")
                except Exception as e:
                    logger.warning(f"⚠️ Reranking failed: {e}, using original results")
            
            # Step 3: Get best answer
            best_candidate = candidates[0] if candidates else None
            
            if not best_candidate:
                return "Xin lỗi, mình không tìm thấy thông tin phù hợp."
            
            confidence = best_candidate.get('final_score', best_candidate.get('semantic_score', 0))
            
            if confidence < self.min_confidence:
                return f"Mình tìm được thông tin nhưng độ chắc chắn không cao (confidence: {confidence:.2f}). Bạn có thể hỏi cụ thể hơn không?"
            
            # Get answer
            answer = best_candidate.get('answer', '')
            question = best_candidate.get('question', '')
            category = best_candidate.get('category', '')
            
            # Format response
            response = f"{answer}"
            
            # Add reference info if available
            reference_links = best_candidate.get('reference_links', [])
            if reference_links:
                response += "\n\n📎 Tài liệu tham khảo:"
                for link in reference_links[:2]:  # Max 2 links
                    response += f"\n- {link.get('title', 'Tài liệu')}: {link.get('url', '')}"
            
            # Add metadata for debugging (nếu verbose)
            if logger.level <= logging.DEBUG:
                response += f"\n\n[Debug: confidence={confidence:.3f}, matched_question='{question}', category='{category}']"
            
            logger.info(f"✅ RAG Search successful (confidence: {confidence:.3f})")
            
            return response
            
        except Exception as e:
            logger.error(f"❌ RAG Search error: {str(e)}")
            return f"Đã xảy ra lỗi khi tìm kiếm: {str(e)}"
    
    def set_retriever(self, retriever):
        """Set retriever instance"""
        self.retriever = retriever
    
    def set_reranker(self, reranker):
        """Set reranker instance"""
        self.reranker = reranker


class RAGContextSearchTool(BDUBaseTool):
    """
    Advanced RAG tool with conversation context
    Sử dụng khi cần tìm kiếm với context từ câu hỏi trước
    """
    
    name: str = "search_with_context"
    description: str = """Tìm kiếm thông tin với context từ cuộc hội thoại trước.
    
    Sử dụng khi:
    - Câu hỏi follow-up có đại từ (ông ấy, bà ấy, người đó)
    - Câu hỏi liên quan đến câu trước
    
    Input: JSON string với format: {"query": "câu hỏi", "context": ["keyword1", "keyword2"]}
    """
    
    category: str = "rag"
    requires_auth: bool = False
    
    retriever: Optional[Any] = None
    reranker: Optional[Any] = None
    top_k: int = 5
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str, context: Optional[List[str]] = None) -> str:
        """
        Execute context-aware RAG search
        
        Args:
            query: User's question
            context: List of context keywords from previous conversation
        """
        if not self.retriever:
            return "❌ RAG retriever not initialized"
        
        try:
            logger.info(f"🔍 Context RAG Search: '{query}' with context: {context}")
            
            # Use dual semantic search (context-aware)
            candidates, method = self.retriever.dual_semantic_search(
                query=query,
                context_keywords=context,
                top_k=self.top_k * 2
            )
            
            if not candidates:
                return "Xin lỗi, mình không tìm thấy thông tin phù hợp với context này."
            
            logger.info(f"📋 Found {len(candidates)} candidates using method: {method}")
            
            # Rerank
            if self.reranker and len(candidates) > 1:
                try:
                    reranked = self.reranker.rerank_with_context(
                        query=query,
                        candidates=candidates,
                        session_context={"context_keywords": context or []}
                    )
                    if reranked:
                        candidates = reranked[:self.top_k]
                except Exception as e:
                    logger.warning(f"⚠️ Reranking failed: {e}")
            
            # Format answer similar to RAGSearchTool
            best = candidates[0]
            answer = best.get('answer', '')
            confidence = best.get('final_score', best.get('semantic_score', 0))
            
            response = f"{answer}"
            
            if confidence < 0.6:
                response = f"Dựa vào context, mình tìm được: {answer}\n\n(Lưu ý: Độ chắc chắn không cao, bạn có thể hỏi rõ hơn)"
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Context RAG error: {str(e)}")
            return f"Lỗi tìm kiếm với context: {str(e)}"
    
    def set_retriever(self, retriever):
        self.retriever = retriever
    
    def set_reranker(self, reranker):
        self.reranker = reranker
