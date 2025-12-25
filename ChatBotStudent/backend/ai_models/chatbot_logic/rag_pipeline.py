import time
import re
import random
import logging
logger = logging.getLogger(__name__)

import jwt # Thêm import này

# Import các module vừa tách
from .retriever import ChatbotAI
from .reranker import SemanticReRanker
from .decision_engine import PureSemanticDecisionEngine

# Import các service khác
from ..phobert_service import retriever_service # Sử dụng .. để đi ra khỏi thư mục chatbot_logic
from ..interaction_logger_service import interaction_logger
from qa_management.services import drive_service          # <--- Đường dẫn đúng cho drive_service
from ..external_api_service import external_api_service # <--- Đường dẫn này vẫn đúng cho external_api_service

class PureSemanticChatbotAI:
    def __init__(self, shared_response_generator):
        print("--- CHECKPOINT 2: PureSemanticChatbotAI __init__ started ---")
        from ..phobert_service import retriever_service        
        self.sbert_retriever = ChatbotAI(shared_response_generator=shared_response_generator)
        self.retriever_service = retriever_service
        self.response_generator = shared_response_generator
        self.decision_engine = PureSemanticDecisionEngine()        
        self.semantic_reranker = SemanticReRanker(retriever_service=self.retriever_service)        
        self.conversation_memory = {}        
        logger.info("🎯 ENHANCED PureSemanticChatbotAI initialized")
        logger.info("   🛡️ Smart penalty systmình enabled")
        logger.info("   🧠 Confidence-aware decision making")
        logger.info("   🎯 High-quality answer preservation")
        logger.info("   🔬 Top-5 smart candidate selection")
    
    def _check_direct_entity_query(self, query: str, session_id: str):
        """🔧 IMPROVED: Better detection of entity queries"""
        session_memory = self.get_conversation_context(session_id)
        if not session_memory or len(session_memory) == 0:
            return False, None, None

        query_lower = query.lower().strip()
        
        # 🆕 EXPANDED: More patterns to catch entity questions
        direct_patterns = [
            r'\b(vậy|thế)\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)\s+là\s+(ai|gì)\b',  # "vậy X là ai"
            r'\b(vậy|thế)\s+(thầy|cô|ông|bà|anh|chị)\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)\b',  # "vậy thầy X"
            r'\b(còn|và)\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)\s+(thì sao|như thế nào|là ai)\b',  # "còn X thì sao"
            r'\b([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)\s+là\s+(ai|gì)\b',  # "X là ai"
            r'\b(?:ông|bà|thầy|cô|anh|chị)\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)\s*$'  # "ông X", "bà Y"
        ]
        
        # Traditional direct references
        direct_pronouns = ['ông ấy', 'bà ấy', 'người đó', 'thầy ấy', 'cô ấy', 'anh ấy', 'chị ấy']
        has_direct_pronoun = any(pronoun in query_lower for pronoun in direct_pronouns)
        
        # Check for name patterns
        extracted_name = None
        has_direct_pattern = False
        
        for pattern in direct_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                has_direct_pattern = True
                # Extract name from different groups based on pattern
                groups = match.groups()
                for group in groups:
                    if group and len(group.split()) >= 1 and group[0].isupper():
                        # Handle single name or full name
                        if len(group.split()) == 1:
                            # Single word - check if it could be part of a longer name
                            extracted_name = group
                        else:
                            # Multiple words - likely full name
                            extracted_name = group
                        break
                if extracted_name:
                    break
        
        # ONLY proceed if there's a clear direct reference
        if not (has_direct_pronoun or has_direct_pattern):
            return False, None, None

        # Check last 3 interactions instead of just 1
        recent_interactions = session_memory[-3:] if len(session_memory) >= 3 else session_memory
        
        for interaction in reversed(recent_interactions):
            last_entities_info = interaction.get('semantic_info', {}).get('extracted_entities', {})
            last_person_entities = last_entities_info.get('person_name', [])
            
            if not last_person_entities:
                continue
            
            # If we extracted a specific name, try to match it
            if extracted_name:
                for entity in last_person_entities:
                    if self._names_match_flexible(extracted_name, entity):
                        logger.info(f"🎯 Direct entity match: '{extracted_name}' → '{entity}'")
                        return True, entity, interaction
            
            # For pronouns, use the most recent entity
            if has_direct_pronoun:
                main_entity = last_person_entities[0]
                logger.info(f"🎯 Direct pronoun reference: '{main_entity}'")
                return True, main_entity, interaction
        
        return False, None, None

    def _names_match_flexible(self, name1: str, name2: str) -> bool:
        """🆕 NEW: Flexible name matching"""
        if not name1 or not name2:
            return False
        
        # Normalize both names
        norm1 = name1.lower().strip()
        norm2 = name2.lower().strip()
        
        # Remove Vietnamese particles
        particles = ['dạ', 'ạ', 'ơi', 'nhé', 'vậy', 'thì', 'là', 'của', 'và', 'với']
        for particle in particles:
            norm1 = norm1.replace(particle, ' ')
            norm2 = norm2.replace(particle, ' ')
        
        # Clean up spaces
        norm1 = ' '.join(norm1.split())
        norm2 = ' '.join(norm2.split())
        
        # Direct match
        if norm1 == norm2:
            return True
        
        # Word-level matching
        words1 = set(norm1.split())
        words2 = set(norm2.split())
        
        # If both have multiple words, check overlap
        if len(words1) >= 2 and len(words2) >= 2:
            overlap = len(words1.intersection(words2))
            total_words = min(len(words1), len(words2))  # Use smaller set as denominator
            overlap_ratio = overlap / total_words if total_words > 0 else 0
            
            # 60% overlap is good enough for names
            return overlap_ratio >= 0.6
        
        # Single word vs multi-word (e.g., "cường" vs "lê văn cường")
        if len(words1) == 1 and len(words2) >= 2:
            single_word = list(words1)[0]
            return single_word in words2 and len(single_word) > 2
        elif len(words2) == 1 and len(words1) >= 2:
            single_word = list(words2)[0]
            return single_word in words1 and len(single_word) > 2
        
        # Single word matching with partial
        if len(words1) == 1 and len(words2) == 1:
            word1, word2 = list(words1)[0], list(words2)[0]
            if len(word1) >= 3 and len(word2) >= 3:
                # Check if one contains the other
                return word1 in word2 or word2 in word1
        
        return False

    def _create_response_from_memory(self, query, entity_name, last_interaction, session_id):
        """Create response using information from memory"""
        last_response = last_interaction.get('response', '')
        last_query = last_interaction.get('query', '')
        
        logger.info(f"📝 Creating response from memory about: '{entity_name}'")
        logger.info(f"   Previous query: '{last_query}'")
        
        # Use generator to create natural response
        context = {
            'response': last_response,
            'entity_name': entity_name,
            'previous_query': last_query,
            'memory_based': True
        }
        
        response = self.response_generator.generate_response(
            query=query,
            context=context,
            intent_info=None,
            entities={'person_name': [entity_name]},
            session_id=session_id
        )
        
        response_text = response.get('response', '') if response else ''
        
        if not response_text or len(response_text.strip()) < 10:
            # Fallback to simple response
            response_text = f"Chào bạn, về {entity_name}, như mình đã thảo luận trước đó: {last_response[:200]}..."
        
        return {
            'response': response_text,
            'confidence': 0.85,
            'method': 'memory_direct_hit',
            'decision_type': 'memory_context',
            'entity_referenced': entity_name,
            'processing_time': 0.1,
            'context_aware_rag': True
        }

    def _smart_entity_fallback_search(self, query, session_id):
        """Smart fallback for entity queries when main search fails"""
        if not session_id:
            return []
        
        session_memory = self.get_conversation_context(session_id)
        if not session_memory:
            return []
        
        # Get recent entities from memory
        recent_entities = []
        for interaction in reversed(session_memory[-5:]):  # Check last 5 interactions
            entities_info = interaction.get('semantic_info', {}).get('extracted_entities', {})
            if 'person_name' in entities_info:
                recent_entities.extend(entities_info['person_name'])
        
        if not recent_entities:
            return []
        
        # Build enhanced query with entity context
        recent_entities = list(set(recent_entities))[:3]  # Top 3 unique entities
        entity_context = " ".join(recent_entities)
        enhanced_query = f"{query} {entity_context}"
        
        logger.info(f"🔍 Smart fallback: Enhanced query with entities: {recent_entities}")
        
        # Search with enhanced query
        candidates = self.sbert_retriever.semantic_search_top_k(
            enhanced_query,
            top_k=self.semantic_reranker.config['stage1_top_k']
        )
        
        return candidates

    def _calculate_semantic_relevance(self, query, document_text):
        """Calculate semantic relevance between query and document"""
        try:
            from sentence_transformers import util
            
            # Get embeddings
            query_embedding = self.sbert_retriever.model.encode(query, convert_to_tensor=True)
            doc_embedding = self.sbert_retriever.model.encode(document_text[:500], convert_to_tensor=True)
            
            # Calculate cosine similarity
            similarity = util.cos_sim(query_embedding, doc_embedding).item()
            
            return similarity
            
        except Exception as e:
            logger.error(f"❌ Error calculating semantic relevance: {str(e)}")
            return 0.5  # Default to medium relevance
    
    def process_query(self, query, session_id=None, jwt_token=None, document_text=None):
        start_time = time.time()
        logger.info(f"🎯 IMPROVED Context-Aware Semantic RAG Processing: '{query}' (session: {session_id})")
        
        # ✅ FIX #1: LOAD PROFILE FROM JWT_TOKEN
        student_profile = None
        if jwt_token:
            try:
                logger.info(f"🔑 Loading student profile from JWT token...")
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
                    logger.info(f"✅ Profile loaded: {student_profile.get('full_name')} ({student_profile.get('mssv')}), lớp {student_profile.get('class_name')}")
                    
                    # ✅ SET PROFILE INTO GENERATOR CONTEXT
                    if self.response_generator and hasattr(self.response_generator, '_user_context_cache'):
                        if session_id:
                            self.response_generator._user_context_cache[session_id] = student_profile
                            logger.info(f"✅ Profile set into generator context for session: {session_id}")
                else:
                    logger.warning("⚠️ get_student_profile returned None")
            except Exception as e:
                logger.warning(f"⚠️ Could not load student profile from JWT: {e}")
        else:
            logger.debug("ℹ️ No JWT token provided, skipping profile load")
        
        try:
            normalized_query = query.lower().strip()
        
            ACKNOWLEDGEMENT_PHRASES = [
                'đúng rồi', 'chính xác', 'chính xác rồi đó', 'cậu nói đúng rồi', 'cậu nói đúng',
                'ok bạn', 'cảm ơn cậu', 'cảm ơn', 'cảm ơn bạn', 'cảm ơn nhé', 'cảm ơn nha',
                'oke', 'okela', 'okee', 'ok', 'ukm', 'ừm', 'uhm', 'uh', 'ừ'
            ]
            if normalized_query in ACKNOWLEDGEMENT_PHRASES:
                ACKNOWLEDGEMENT_RESPONSES = [
                    "Dạ, mình đây. Cậu cần mình hỗ trợ thêm gì không?", "Okie, nếu cậu cần gì cứ hỏi nhé!",
                    "Không có gì đâu cậu. Cần gì cứ nói mình nha.", "Mình hiểu rồi. Cậu có câu hỏi nào khác không?",
                    "Rất vui vì đã giúp được cậu!"
                ]
                response_text = random.choice(ACKNOWLEDGEMENT_RESPONSES)
                logger.info(f"💬 Conversational filter triggered for '{query}'. Responding naturally.")
                
                return {
                    'response': response_text, 'confidence': 0.98, 'method': 'conversational_filter',
                    'decision_type': 'acknowledgement', 'processing_time': time.time() - start_time, 'context_aware_rag': True,
                }
            
            query = self._clean_query(query)
            if not query:
                return self._get_empty_query_response()

            session_memory = self.get_conversation_context(session_id) if session_id else []
            logger.info(f"🧠 Session memory: {len(session_memory)} interactions")

            is_document_context_active = False
            final_document_text = document_text # Ưu tiên tài liệu mới tải lên

            if not final_document_text and session_memory:
                previous_document = None
                # Tìm kiếm ngược từ cuối lịch sử hội thoại
                for interaction in reversed(session_memory):
                    doc_in_memory = interaction.get('document_text')
                    if doc_in_memory and doc_in_memory.strip():
                        # Tìm thấy tài liệu gần nhất, lấy nó và dừng tìm kiếm
                        previous_document = doc_in_memory
                        break
                
                if previous_document:
                    # Tầng 1: Tính toán độ tương đồng ngữ nghĩa (logic này giữ nguyên)
                    relevance_score = self._calculate_semantic_relevance(query, previous_document)
                    logger.info(f"📊 Semantic relevance to previous document: {relevance_score:.2f}")

                    # Tầng 2: Ra quyết định cho các trường hợp rõ ràng
                    if relevance_score > 0.7: # Ngưỡng Rất Cao
                        logger.info("✔️ Relevance check: PASSED (High similarity). Reusing document.")
                        final_document_text = previous_document
                    elif relevance_score < 0.4: # Ngưỡng Rất Thấp
                        logger.info("❌ Relevance check: FAILED (Low similarity). Topic shift.")
                        final_document_text = None
                    else:
                        # Tầng 3: Trường hợp nhập nhằng -> Hiện tại, để đơn giản, chúng ta sẽ coi là liên quan
                        # (Trong tương lai, có thể thêm 1 lệnh gọi LLM ở đây để xác nhận)
                        logger.info("⚠️ Relevance check: AMBIGUOUS. Assuming continuation for better user experience.")
                        final_document_text = previous_document
            
            if final_document_text and final_document_text.strip():
                is_document_context_active = True

            if is_document_context_active:
                logger.info(f"📄 Document context is ACTIVE with {len(final_document_text.strip())} chars. Prioritizing document processing.")
                decision_type, context, should_respond = self.decision_engine.make_decision(
                    query, [], session_memory, jwt_token, final_document_text
                )
                
                # ✅ ADD PROFILE TO CONTEXT
                if student_profile:
                    context['profile'] = student_profile
                
                if should_respond and decision_type == 'use_document_context':
                    response_text = self._execute_fixed_semantic_decision(
                        decision_type, query, context, session_id
                    )
                    final_score = context.get('confidence', 0.95)
                    
                    if session_id:
                        self._update_semantic_memory(
                            session_id, query, final_score, decision_type, 
                            True, context, final_document_text
                        )

                    return {
                        'response': response_text, 'confidence': final_score, 'method': 'document_context_priority',
                        'decision_type': decision_type, 'semantic_info': context, 'sources': [],
                        'processing_time': time.time() - start_time, 'document_context_used': True,
                        'document_context_priority': True, 'context_aware_rag': True,
                    }
            
            logger.info("📚 No active document context. Proceeding with standard RAG pipeline.")
            
            is_direct_hit, entity_name, last_interaction = self._check_direct_entity_query(query, session_id)
            if is_direct_hit:
                response_data = self._create_response_from_memory(query, entity_name, last_interaction, session_id)
                if session_id:
                    self._update_semantic_memory(
                        session_id, query, response_data['confidence'], response_data['decision_type'], 
                        True, response_data, None
                    )
                return response_data
            
            candidates = []
            search_method = 'normal'
            context_info = {}
            if session_id and hasattr(self.response_generator, 'memory'):
                context_info = self.response_generator.memory.get_context_for_query(session_id, query)
                logger.info(f"🔍 Context analysis: should_use={context_info.get('should_use_context', False)}, strength={context_info.get('context_strength', 0)}")
            
            should_try_context = (
                context_info.get('should_use_context', False) and 
                context_info.get('related_entities') and
                context_info.get('context_strength', 0) >= 1.5
            )
            is_entity_query = any(pattern in query.lower() for pattern in [
                'là ai', 'ai là', 'ông ', 'bà ', 'thầy ', 'cô ',
                'vậy ', 'thế ', 'còn ', 'và ', 'gs.ts', 'tiến sĩ'
            ])

            if should_try_context:
                logger.info("🔄 Trying DUAL search (context + normal) for comparison")
                context_keywords = context_info.get('context_keywords', [])
                candidates, search_method = self.sbert_retriever.dual_semantic_search(
                    query, 
                    context_keywords, 
                    top_k=self.semantic_reranker.config['stage1_top_k']
                )
                logger.info(f"🔄 Dual search result: method={search_method}, candidates={len(candidates)}")
            elif is_entity_query:
                logger.info("🔍 Entity query detected - trying smart fallback search first")
                fallback_candidates = self._smart_entity_fallback_search(query, session_id)
                
                if fallback_candidates:
                    logger.info(f"✅ Smart fallback found {len(fallback_candidates)} candidates")
                    candidates = fallback_candidates
                    search_method = 'entity_fallback'
                else:
                    logger.info("⚠️ Smart fallback found no candidates, using normal search")
                    candidates = self.sbert_retriever.semantic_search_top_k(
                        query, 
                        top_k=self.semantic_reranker.config['stage1_top_k']
                    )
                    search_method = 'normal'
            else:
                logger.info("🔍 Using NORMAL search (non-entity query)")
                candidates = self.sbert_retriever.semantic_search_top_k(
                    query, 
                    top_k=self.semantic_reranker.config['stage1_top_k']
                )
                search_method = 'normal'

            if not candidates or len(candidates) == 0:
                logger.warning("⚠️ No candidates found in semantic search")
                return self._get_no_match_response()
            
            reranked_candidates = self.semantic_reranker.rerank(
                query=query, 
                candidates=candidates, 
                context_keywords=context_info.get('context_keywords', [])  # Nếu cần, thay vì context_info
            )
            
            if not reranked_candidates:
                logger.warning("⚠️ No candidates after re-ranking")
                return self._get_no_match_response()
            
            logger.info(f"📊 Top candidate analysis:")
            top = reranked_candidates[0]
            context_quality = self._analyze_context_quality(query, top, session_memory)
            logger.info(f"   Score: {top.get('final_score', 0):.3f} | Context quality: {context_quality:.3f}")
            logger.info(f"   Method: {search_method}")
            
            decision_type, context, should_respond = self.decision_engine.make_decision(
                query, reranked_candidates, session_memory, jwt_token, None
            )
            
            # ✅ ADD PROFILE TO CONTEXT
            if student_profile:
                context['profile'] = student_profile
                logger.info(f"✅ Added profile to context: {student_profile.get('full_name')}")
            
            if not should_respond:
                logger.info(f"🚫 Decision engine says NO RESPOND for type: {decision_type}")
                return self._get_no_match_response()
            
            was_education = self._is_education_related(query)
            user_type = 'student'
            
            response_text = self._execute_fixed_semantic_decision(
                decision_type, query, context, session_id
            )
            
            final_score = context.get('confidence', 0.5)
            
            if session_id:
                self._update_semantic_memory(
                    session_id, query, final_score, decision_type, 
                    was_education, context, None
                )
            
            return {
                'response': response_text,
                'confidence': final_score,
                'method': f'semantic_rag_{search_method}',
                'decision_type': decision_type,
                'semantic_info': context,
                'sources': self._format_sources(reranked_candidates[:3]),
                'processing_time': time.time() - start_time,
                'was_education_related': was_education,
                'user_type': user_type,
                'context_aware_rag': True,
                'context_quality': context_quality
            }
            
        except Exception as e:
            logger.error(f"❌ Error in process_query: {str(e)}", exc_info=True)
            return {
                'response': self._get_error_response(session_id),
                'confidence': 0.0,
                'method': 'error',
                'error': str(e),
                'processing_time': time.time() - start_time
            }
    
    def _analyze_context_quality(self, query, top_candidate, session_memory):
        """Analyze the quality of context from memory"""
        try:
            quality_score = 0.0
            
            # Base score from candidate
            if top_candidate:
                quality_score += min(0.3, top_candidate.get('final_score', 0))
            
            # Boost from memory
            if session_memory and len(session_memory) > 0:
                quality_score += 0.2
            
            # Boost from entity continuity
            query_lower = query.lower()
            if any(kw in query_lower for kw in ['ông ấy', 'bà ấy', 'thầy ấy', 'cô ấy', 'vậy', 'thế', 'còn']):
                quality_score += 0.3
            
            # Boost from clear question patterns
            if any(kw in query_lower for kw in ['là ai', 'ai là', 'làm gì', 'ở đâu', 'như thế nào']):
                quality_score += 0.2
            
            return min(1.0, quality_score)
            
        except Exception as e:
            logger.error(f"❌ Error analyzing context quality: {str(e)}")
            return 0.0
        
    def _execute_fixed_semantic_decision(self, decision_type, query, context, session_id):
        logger.info(f"🎯 Executing FIXED semantic decision: {decision_type}")
        gemini_available = self._check_gemini_availability()
        if not gemini_available:
            logger.warning("⚠️ Gemini API not available - using FIXED graceful degradation")
            return self._create_fixed_semantic_fallback_response(decision_type, query, context, session_id)        
        try:
            if decision_type == 'use_document_context':
                response = self.response_generator.generate_response(
                    query=query, context=context, intent_info=None, entities={}, session_id=session_id
                )
                response_text = response.get('response', '') if response else ''                
                if not response_text or len(response_text.strip()) < 10:
                    logger.warning("⚠️ Empty/invalid response from Gemini - using fallback")
                    return self._get_document_fallback(session_id)
                
                return response_text
            elif decision_type == 'use_external_api':
                return self._handle_external_api_decision(query, context, session_id)            
            elif decision_type == 'require_authentication':
                return self._handle_authentication_required(session_id)            
            elif decision_type in ['use_db_direct', 'enhance_db_answer']:
                response = self.response_generator.generate_response(
                    query=query, context=context, intent_info=None, entities={}, session_id=session_id
                )
                response_text = response.get('response', '') if response else ''                
                if not response_text or len(response_text.strip()) < 10:
                    logger.warning("⚠️ Empty/invalid response from Gemini - using FIXED semantic fallback")
                    return self._create_fixed_semantic_fallback_response(decision_type, query, context, session_id)                
                return response_text
            
            elif decision_type == 'ask_clarification':
                if context and context.get('smart_clarification', False):
                    logger.info("🤔 Creating FIXED smart clarification response")
                    mismatch_issues = context.get('mismatch_issues', [])
                    return self.decision_engine._create_smart_clarification_response(
                        query, mismatch_issues, session_id
                    )
                else:
                    response = self.response_generator.generate_response(
                        query=query, context=context, intent_info=None, entities={}, session_id=session_id
                    )
                    response_text = response.get('response', '') if response else ''                    
                    if not response_text or len(response_text.strip()) < 10:
                        return self._get_clarification_fallback(session_id)                    
                    return response_text
            elif decision_type == 'say_dont_know':
                response = self.response_generator.generate_response(
                    query=query, context=context, intent_info=None, entities={}, session_id=session_id
                )
                response_text = response.get('response', '') if response else ''                
                if not response_text or len(response_text.strip()) < 10:
                    return self._get_dont_know_fallback(session_id)                
                return response_text            
            else:
                return self._get_out_of_scope_response(session_id)
                
        except Exception as e:
            logger.error(f"❌ Error in _execute_fixed_semantic_decision: {str(e)}")
            return self._create_fixed_semantic_fallback_response(decision_type, query, context, session_id)
    
    def _create_fixed_semantic_fallback_response(self, decision_type, query, context, session_id):
        logger.info(f"🛡️ Creating FIXED semantic fallback for decision: {decision_type}")
        personal_address = self._get_personal_address(session_id)
        raw_answer = context.get('response', '') if context else ''
        mismatch_issues = context.get('mismatch_issues', []) if context else []
        confidence_preserved = context.get('confidence_preserved', False) if context else False        
        if mismatch_issues and decision_type in ['use_db_direct', 'enhance_db_answer', 'ask_clarification']:
            logger.info("🤔 FIXED fallback: Using smart clarification due to detected mismatches")
            return self.decision_engine._create_smart_clarification_response(
                query, mismatch_issues, session_id
            )
        if decision_type in ['use_db_direct', 'enhance_db_answer']:
            if raw_answer and raw_answer.strip():
                logger.info(f"🔍 DEBUG - Raw database answer: '{raw_answer[:300]}...'")                
                clean_answer = raw_answer.strip()                
                clean_answer = re.sub(r'^(dạ\s+(thầy|cô|sinh viên)[^,]*,?\s*)', '', clean_answer, flags=re.IGNORECASE)
                clean_answer = re.sub(r'^(xin chào|chào)[^.!?]*[.!?]\s*', '', clean_answer, flags=re.IGNORECASE)                
                if clean_answer and not clean_answer[0].isupper():
                    clean_answer = clean_answer[0].upper() + clean_answer[1:]                
                personalized_response = f"Chào cậu, {clean_answer}"                
                if not personalized_response.strip().endswith(('?', '!', '.')):
                    personalized_response += '.'                
                if confidence_preserved:
                    personalized_response += f' {personal_address.title()} có cần tớ hỗ trợ thêm gì không ạ?'
                else:
                    personalized_response += f' {personal_address.title()} cần tớ làm rõ thêm gì không ạ?'                
                logger.info(f"🛡️ FIXED SEMANTIC FALLBACK: Formatted raw answer for {personal_address}")
                return personalized_response
            else:
                return f"Chào cậu, tớ chưa có thông tin về vấn đề này. {personal_address.title()} có thể liên hệ phòng ban liên quan để được hỗ trợ chi tiết."
        return f"Chào cậu, tớ sẵn sàng hỗ trợ {personal_address} về các vấn đề liên quan đến BDU. {personal_address.title()} có thể chia sẻ cụ thể hơn về điều cần hỗ trợ không ạ?"
    def _check_gemini_availability(self):
        try:
            if not self.response_generator:
                return False            
            if not hasattr(self.response_generator, 'key_manager') or not self.response_generator.key_manager.keys:
                return False            
            test_key = self.response_generator.key_manager.get_key()
            if not test_key:
                return False            
            return True            
        except Exception as e:
            logger.error(f"❌ Error checking Gemini availability: {str(e)}")
            return False
    def _validate_answer_relevance(self, query, answer):
        try:
            query_lower = query.lower()
            answer_lower = answer.lower()            
            concept_patterns = {
                'báo cáo khối lượng': ['báo cáo', 'khối lượng', 'công việc'],
                'kê khai nhiệm vụ': ['kê khai', 'nhiệm vụ'],
                'tốt nghiệp': ['tốt nghiệp', 'graduation'],
                'tạp chí': ['tạp chí', 'journal', 'bài viết'],
                'lịch giảng': ['lịch', 'giảng dạy', 'schedule'],
                'hạn nộp': ['hạn', 'deadline', 'chậm nhất']
            }            
            main_concept = None
            for concept, keywords in concept_patterns.items():
                if any(kw in query_lower for kw in keywords):
                    main_concept = concept
                    break            
            if not main_concept:
                return True
            concept_keywords = concept_patterns[main_concept]
            answer_has_concept = any(kw in answer_lower for kw in concept_keywords)            
            relevance_issues = []
            if 'báo cáo khối lượng' in query_lower and 'khối lượng học tập' in answer_lower:
                relevance_issues.append("Query về 'báo cáo khối lượng công việc' nhưng answer về 'khối lượng học tập sinh viên'")
            if 'kê khai nhiệm vụ' in query_lower and 'kê khai' not in answer_lower:
                relevance_issues.append("Query về 'kê khai nhiệm vụ' nhưng answer không chứa 'kê khai'")
            if relevance_issues:
                logger.warning(f"🔍 ANSWER RELEVANCE WARNING:")
                for issue in relevance_issues:
                    logger.warning(f"   ⚠️ {issue}")
                return False            
            return answer_has_concept            
        except Exception as e:
            logger.error(f"❌ Error in answer relevance validation: {str(e)}")
            return True
    def _clean_query(self, query):
        if not query:
            return ""
        query = re.sub(r'\s+', ' ', query.strip())
        query = re.sub(r'[?]{2,}', '?', query)
        query = re.sub(r'[!]{2,}', '!', query)
        return query
    
    def _update_semantic_memory(self, session_id, query, confidence, decision_type, was_education, semantic_info_context, document_text=None):
        if session_id not in self.conversation_memory:
            self.conversation_memory[session_id] = []
        
        user_type = 'student'
        
        interaction = {
            'query': query,
            'response': semantic_info_context.get('response', '') if isinstance(semantic_info_context, dict) else '',
            'confidence': confidence,
            'semantic_info': {
                'method': semantic_info_context.get('method', 'unknown') if isinstance(semantic_info_context, dict) else 'unknown',
                'top_score': semantic_info_context.get('final_score', confidence) if isinstance(semantic_info_context, dict) else confidence,
                'extracted_entities': semantic_info_context.get('extracted_entities', {}) if isinstance(semantic_info_context, dict) else {},
                'confidence_preserved': semantic_info_context.get('confidence_preserved', False),
                'smart_penalty': semantic_info_context.get('smart_penalty', 0),
                'mismatch_issues': semantic_info_context.get('mismatch_issues', []),
                'semantic_decision': True
            },
            'timestamp': time.time(),
            
            # SỬ DỤNG GIÁ TRỊ ĐÚNG
            'user_type': user_type,
            
            'decision_type': decision_type,
            'was_education_related': was_education,
            'fixed_semantic_processed': True,
            'document_text': document_text,
            'document_context_priority': decision_type == 'use_document_context',
            'external_api_used': decision_type == 'use_external_api',
            'query_length': len(query.split()),
            'architecture': 'fixed_semantic_rag'
        }
        self.conversation_memory[session_id].append(interaction)
        
        self.conversation_memory[session_id] = self.conversation_memory[session_id][-30:]
        
        logger.info(f"🧠 FIXED semantic memory updated for session {session_id} (user_type: {user_type}): {len(self.conversation_memory[session_id])} interactions")
        
    def _get_personal_address(self, session_id):
        try:
            if hasattr(self.response_generator, '_get_personal_address'):
                return self.response_generator._get_personal_address(session_id)
            return "bạn"
        except Exception as e:
            logger.error(f"❌ Error getting personal address: {str(e)}")
            return "bạn"
    def _get_empty_query_response(self):
        return {
            'response': "Chào bạn! Mình có thể hỗ trợ gì cho bạn về các vấn đề tại BDU không?",
            'confidence': 0.9,
            'method': 'empty_query',
            'processing_time': 0.01,
            'fixed_semantic_rag': True
        }
    def _get_no_match_response(self):
        return {
            'response': "Mình chưa có thông tin về vấn đề này. Bạn có thể liên hệ phòng ban liên quan để được hỗ trợ chi tiết nhé.",
            'confidence': 0.1,
            'method': 'no_match_semantic',
            'decision_type': 'say_dont_know',
            'processing_time': 0.01,
            'fixed_semantic_rag': True
        }
    def _get_out_of_scope_response(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào cậu, tớ chỉ hỗ trợ các vấn đề liên quan đến công việc sinh viên tại BDU thôi ạ!"
    def _get_error_response(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào cậu, tớ gặp khó khăn kỹ thuật. {personal_address.title()} có thể liên hệ bộ phận IT qua email it@bdu.edu.vn để được hỗ trợ."
    def _get_clarification_fallback(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào bạn, để tớ hỗ trợ chính xác nhất, {personal_address} có thể nói rõ hơn về vấn đề cần hỗ trợ không ạ?"
    def _get_dont_know_fallback(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào bạn, tớ chưa có thông tin về vấn đề này. {personal_address.title()} có thể liên hệ phòng ban liên quan để được hỗ trợ chi tiết."
    def _get_document_fallback(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào bạn, tớ đã xét tài liệu nhưng gặp khó khăn trong việc trả lời. {personal_address.title()} có thể đặt câu hỏi cụ thể hơn không ạ?"
    def _handle_external_api_decision(self, query, context, session_id):
        """
        Quyết định gọi external API và tạo câu trả lời tự nhiên.
        Hỗ trợ sinh viên. Có fallback khi LLM hoặc API thiếu dữ liệu.
        """
        from .student_api_handler import handle_external_api_student
        from ..external_api_service import ExternalAPIService  # tránh import vòng
        import jwt

        svc = ExternalAPIService()
        jwt_token = (context or {}).get('jwt_token') or ''
        role_hint = (context or {}).get('role')  # nếu upstream có truyền
        lower_q = (query or '').lower()

        # 1) Xác định vai trò từ JWT (ưu tiên) hoặc hint
        role = None
        try:
            # PyJWT decode không cần verify khi chỉ đọc claim, SSO nội bộ thì verify ở middleware rồi
            payload = jwt.decode(jwt_token, options={"verify_signature": False})
            role = payload.get('role') or payload.get('roles') or role_hint
        except Exception:
            role = role_hint

        # 2) Router: student only
        is_student = (role == 'sinhvien' or 'sinh viên' in str(role or '').lower())

        try:
            if is_student:
                # Sử dụng function handle_external_api_student mới
                result = handle_external_api_student(jwt_token, query)
                if result.get("status") == "success":
                    return result.get("response", "Đã xử lý yêu cầu thành công.")
                else:
                    return self._get_api_error_response(result, session_id)

            else:
                # Chỉ hỗ trợ sinh viên
                return "Xin lỗi, hệ thống hiện tại chỉ hỗ trợ sinh viên. Vui lòng liên hệ phòng đào tạo để được hỗ trợ."

        except Exception as e:
            logger.error(f"❌ Error handling external API: {str(e)}")
            return self._get_api_error_fallback(session_id)
    def _handle_authentication_required(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào bạn, để tớ có thể cung cấp thông tin cá nhân như lịch học, {personal_address} cần đăng nhập vào ứng dụng trước . 🔐"
    def _get_api_fallback(self, api_result, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào bạn, tớ đã tìm thấy thông tin lịch học nhưng gặp khó khăn trong việc trình bày chi tiết. {personal_address.title()} có thể truy cập hệ thống quản lý đào tạo để xem thông tin đầy đủ."
    def _get_api_error_response(self, api_result, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào bạn, tớ gặp khó khăn khi truy xuất thông tin cá nhân. {personal_address.title()} có thể thử lại sau hoặc liên hệ bộ phận IT để được hỗ trợ."
    def _get_api_error_fallback(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Chào bạn, mình gặp khó khăn kỹ thuật khi truy xuất thông tin cá nhân. {personal_address.title()} có thể thử lại sau."
    def _format_sources(self, results):
        sources = []
        for result in results:
            if result and result.get('final_score', 0) > 0.2:
                sources.append({
                    'question': result['question'],
                    'category': result.get('category', 'sinh viên'),
                    'final_score': result.get('final_score', 0),
                    'original_semantic_score': result.get('semantic_score', 0),
                    'smart_penalty': result.get('smart_penalty', 0),
                    'stage1_score': result.get('stage1_score', 0),
                    'stage2_score': result.get('stage2_score', 0),
                    'mismatch_issues': result.get('mismatch_issues', []),
                    'fixed_semantic_reranking': result.get('fixed_semantic_reranking', False)
                })
        return sources

    def get_conversation_context(self, session_id):
        return self.conversation_memory.get(session_id, [])
    def get_conversation_memory(self, session_id):
        return self.response_generator.get_conversation_memory(session_id)
    def clear_conversation_memory(self, session_id=None):
        if session_id:
            self.response_generator.clear_conversation_memory(session_id)
            if session_id in self.conversation_memory:
                del self.conversation_memory[session_id]
        else:
            self.response_generator.clear_conversation_memory()
            self.conversation_memory.clear()
    def reload_after_qa_update(self):
        logger.info("🔄 Reloading FIXED semantic knowledge base...")
        if hasattr(self.sbert_retriever, 'cached_data'):
            self.sbert_retriever.cached_data = None
            self.sbert_retriever.cache_timestamp = 0
        self.sbert_retriever.load_knowledge_base()
        if self.sbert_retriever.model and self.sbert_retriever.knowledge_data:
            self.sbert_retriever.build_faiss_index()
    def _is_education_related(self, query):
        education_keywords = [
            'trường', 'học', 'sinh viên', 'tuyển sinh', 'học phí', 'ngành',
            'đại học', 'bdu', 'đăng ký', 'môn học', 'tín chỉ', 
            'lịch thi', 'kỳ thi', 'điểm', 'điểm danh', 'vắng',
            'thời khóa biểu', 'lịch học', 'phòng học', 'tiết học',
            'học lại', 'cải thiện điểm', 'thi lại', 'nâng điểm',
            'điểm trung bình', 'trung bình', 'tính điểm', 'điểm quá trình',
            'điểm thi', 'điểm cuối kỳ', 'điểm giữa kỳ',
            'khối lượng', 'tối thiểu', 'chương trình', 'học kỳ', 'năm học',
            'tốt nghiệp', 'lễ tốt nghiệp', 'xét tốt nghiệp', 'bằng cấp',
            'văn bằng', 'cử nhân', 'cấp bằng', 'nhận bằng',
            'kỷ luật', 'danh sách', 'theo quy định', 'quy định về', 
            'thủ tục', 'điều kiện', 'yêu cầu', 'mở lớp',
            'như thế nào', 'bao nhiêu', 'là ai', 'ai là', 'làm gì', 'ở đâu',
            'khi nào', 'có được', 'cần gì', 'phải làm'
        ]
        if not query:
            return False        
        query_lower = query.lower()
        return any(kw in query_lower for kw in education_keywords)