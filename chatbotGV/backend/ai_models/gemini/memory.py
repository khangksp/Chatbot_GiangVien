import time
import re
from typing import Dict, Any
import logging
try:
    from ..ner_service import SimpleEntityExtractor
except ImportError:
    # Fallback xử lý đường dẫn nếu chạy script lẻ
    import sys
    import os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
    from ner_service import SimpleEntityExtractor

logger = logging.getLogger(__name__)

class ConversationMemory:    
    def __init__(self, max_history=30):
        self.conversations = {}
        self.max_history = max_history
        try:
            self.entity_extractor = SimpleEntityExtractor()
            logger.info("✅ SimpleEntityExtractor initialized successfully in ConversationMemory")
        except Exception as e:
            logger.error(f"❌ Failed to initialize SimpleEntityExtractor: {str(e)}")
            self.entity_extractor = None
        
    def add_interaction(self, session_id: str, user_query: str, bot_response: str, 
                       intent_info: dict = None, entities: dict = None):
        
        logger.info(f"🔍 DEBUG add_interaction: session={session_id}")
        logger.info(f"🔍 DEBUG query: '{user_query}'")
        logger.info(f"🔍 DEBUG response preview: '{bot_response[:100]}...'")
        
        if not hasattr(self, 'entity_extractor') or self.entity_extractor is None:
            logger.error("❌ CRITICAL: entity_extractor is None!")
            return

        qa_text = f"{user_query} {bot_response}"
        extracted_entities = self.entity_extractor.extract_entities(qa_text, user_query)
        
        logger.info(f"🔍 DEBUG extracted entities: {extracted_entities}")
        
        """Thêm interaction vào memory với entity extraction"""
        if session_id not in self.conversations:
            self.conversations[session_id] = {
                'history': [],
                'context_summary': "",
                'user_interests': set(),
                'conversation_type': 'lecturer',
                'entity_memory': {},
                'entity_relationships': [],
                'context_keywords': []
            }

        qa_text = f"{user_query} {bot_response}"
        extracted_entities = self.entity_extractor.extract_entities(qa_text, user_query)

        relationships = self.entity_extractor.build_entity_relationships(
            user_query, bot_response, extracted_entities
        )

        self._update_entity_memory(session_id, extracted_entities, relationships, user_query, bot_response)

        if entities:
            if 'major' in entities:
                self.conversations[session_id]['user_interests'].add(entities['major'])

        interaction = {
            'timestamp': time.time(),
            'user_query': user_query,
            'bot_response': bot_response,
            'intent': intent_info.get('intent', 'unknown') if intent_info else 'unknown',
            'entities': entities or {},
            'extracted_entities': extracted_entities,
            'entity_relationships': relationships
        }
        
        self.conversations[session_id]['history'].append(interaction)
        if len(self.conversations[session_id]['history']) > self.max_history:
            self.conversations[session_id]['history'] = self.conversations[session_id]['history'][-self.max_history:]
        self._update_context_summary(session_id)
        self._update_context_keywords(session_id)
    
    def _update_entity_memory(self, session_id: str, extracted_entities: dict, relationships: list, query: str, response: str):
        """Cập nhật entity memory với thông tin mới"""
        conv = self.conversations[session_id]
        for entity_type, entity_list in extracted_entities.items():
            for entity in entity_list:
                entity_key = entity.lower().strip()
                if entity_key not in conv['entity_memory']:
                    conv['entity_memory'][entity_key] = {
                        'original_form': entity,
                        'type': entity_type,
                        'contexts': [],
                        'related_entities': set(),
                        'confidence': 0.5,
                        'first_seen': time.time(),
                        'last_used': time.time()
                    }
                context_snippet = f"Q: {query[:100]}... A: {response[:100]}..."
                conv['entity_memory'][entity_key]['contexts'].append({
                    'snippet': context_snippet,
                    'timestamp': time.time(),
                    'query': query,
                    'response_preview': response[:200]
                })
                if len(conv['entity_memory'][entity_key]['contexts']) > 3:
                    conv['entity_memory'][entity_key]['contexts'] = conv['entity_memory'][entity_key]['contexts'][-3:]
                
                conv['entity_memory'][entity_key]['last_used'] = time.time()
        for rel in relationships:
            entity1_key = rel['entity1'].lower().strip()
            entity2_key = rel['entity2'].lower().strip()
            if entity1_key in conv['entity_memory']:
                conv['entity_memory'][entity1_key]['related_entities'].add(entity2_key)
                conv['entity_memory'][entity1_key]['confidence'] = min(0.9, conv['entity_memory'][entity1_key]['confidence'] + 0.1)
            
            if entity2_key in conv['entity_memory']:
                conv['entity_memory'][entity2_key]['related_entities'].add(entity1_key)
                conv['entity_memory'][entity2_key]['confidence'] = min(0.9, conv['entity_memory'][entity2_key]['confidence'] + 0.1)
        conv['entity_relationships'].extend(relationships)
        if len(conv['entity_relationships']) > 20:
            conv['entity_relationships'] = conv['entity_relationships'][-20:]
    
    def _update_context_keywords(self, session_id: str):
        """Cập nhật context keywords từ entity memory"""
        conv = self.conversations[session_id]
        recent_entities = []
        current_time = time.time()
        
        for entity_key, entity_data in conv['entity_memory'].items():
            time_since_last_use = current_time - entity_data['last_used']
            if time_since_last_use < 300:
                if entity_data['confidence'] > 0.6:
                    recent_entities.append({
                        'entity': entity_data['original_form'],
                        'type': entity_data['type'],
                        'confidence': entity_data['confidence'],
                        'recency': time_since_last_use
                    })
        recent_entities.sort(key=lambda x: (x['confidence'], -x['recency']), reverse=True)
        context_keywords = []
        for entity_info in recent_entities[:5]:
            entity = entity_info['entity']
            if len(entity.strip()) > 2:
                context_keywords.append(entity)
        conv['context_keywords'] = context_keywords
        logger.debug(f"📝 Updated context keywords for session {session_id}: {context_keywords}")

    def get_conversation_context(self, session_id: str) -> dict:
        if session_id not in self.conversations:
            return {
                'history': [], 
                'context_summary': '', 
                'user_interests': [], 
                'recent_conversation_summary': '',
                'context_keywords': [],
                'entity_memory': {},
                'active_entities': []
            }
        
        conv = self.conversations[session_id]
        recent_summary = self._create_recent_conversation_summary(session_id)
        active_entities = self._get_active_entities(session_id)
        return {
            'history': conv['history'][-25:],
            'context_summary': conv['context_summary'],
            'user_interests': list(conv['user_interests']),
            'conversation_type': conv['conversation_type'],
            'recent_conversation_summary': recent_summary,
            'context_keywords': conv.get('context_keywords', []),
            'entity_memory': conv.get('entity_memory', {}),
            'active_entities': active_entities,
            'entity_relationships': conv.get('entity_relationships', [])[-10:]
        }
    
    def _get_active_entities(self, session_id: str) -> list:
        """Lấy danh sách entities đang active (confidence cao, dùng gần đây)"""
        if session_id not in self.conversations:
            return []
        
        conv = self.conversations[session_id]
        active_entities = []
        current_time = time.time()
        
        for entity_key, entity_data in conv['entity_memory'].items():
            time_since_last_use = current_time - entity_data['last_used']
            
            if entity_data['confidence'] > 0.6 and time_since_last_use < 600:
                active_entities.append({
                    'entity': entity_data['original_form'],
                    'type': entity_data['type'], 
                    'confidence': entity_data['confidence'],
                    'related_entities': list(entity_data['related_entities'])[:3],  # Top 3 related
                    'last_context': entity_data['contexts'][-1]['snippet'] if entity_data['contexts'] else ""
                })
        
        active_entities.sort(key=lambda x: x['confidence'], reverse=True)
        return active_entities[:5]
    
    def get_context_for_query(self, session_id: str, current_query: str) -> dict:
        """🔧 IMPROVED: Enhanced context detection with fallback mechanisms"""
        
        logger.info(f"🔍 DEBUG get_context_for_query called: session={session_id}, query='{current_query}'")
        
        if session_id not in self.conversations:
            logger.info(f"🔍 DEBUG: No conversations found for session {session_id}")
            return {
                'context_keywords': [], 
                'related_entities': [], 
                'should_use_context': False,
                'context_strength': 0
            }
        
        conv = self.conversations[session_id]
        logger.info(f"🔍 DEBUG: Found conversation with {len(conv.get('entity_memory', {}))} entities")
        current_query_normalized = self._normalize_for_matching(current_query)
        logger.info(f"🔍 DEBUG: Normalized query: '{current_query_normalized}'")
        recent_interactions = conv['history'][-3:] if len(conv['history']) >= 3 else conv['history']
        relevant_entities = []
        extracted_names = []
        memory_reference_patterns = [
            r'\b(còn|vẫn)\s+(nhớ|biết)\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)',
            r'\b(thế|vậy)\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)\s+là\s+(ai|gì)',
            r'\b([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)\s+là\s+(ai|gì)',
            r'\bai\s+là\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*)',
        ]

        for pattern in memory_reference_patterns:
            matches = re.findall(pattern, current_query, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    for group in match:
                        if group and len(group.strip()) > 2:
                            if any(c.isupper() for c in group):
                                extracted_names.append(group.strip())
                else:
                    if len(match.strip()) > 2 and any(c.isupper() for c in match):
                        extracted_names.append(match.strip())
        
        logger.info(f"🔍 DEBUG: Extracted names from patterns: {extracted_names}")
        if extracted_names:
            logger.info(f"🔍 Memory/Direct reference detected: {extracted_names}")
            for extracted_name in extracted_names:
                for entity_key, entity_data in conv.get('entity_memory', {}).items():
                    original_form = entity_data.get('original_form', entity_key)
                    if self._names_match_flexible(extracted_name, original_form):
                        relevant_entities.append({
                            'entity': original_form,
                            'type': entity_data.get('type', 'unknown'),
                            'related': list(entity_data.get('related_entities', set()))[:2],
                            'confidence': 0.8
                        })
                        logger.info(f"🎯 Memory reference matched: {extracted_name} → {original_form}")
        for entity_key, entity_data in conv.get('entity_memory', {}).items():
            original_form = entity_data.get('original_form', entity_key)

            if any(ent['entity'] == original_form for ent in relevant_entities):
                continue

            is_relevant = self._is_entity_relevant_to_query_strict(
                current_query_normalized, 
                entity_key, 
                original_form
            )
            
            if is_relevant:
                relevant_entities.append({
                    'entity': original_form,
                    'type': entity_data.get('type', 'unknown'),
                    'related': list(entity_data.get('related_entities', set()))[:2],
                    'confidence': entity_data.get('confidence', 0.5)
                })
                logger.info(f"🎯 Found relevant entity: {original_form} (key: {entity_key})")

        if not relevant_entities and extracted_names:
            logger.info(f"🔍 No entity memory found, creating fallback context for: {extracted_names}")
            for name in extracted_names:
                if len(name.split()) >= 2:
                    relevant_entities.append({
                        'entity': name,
                        'type': 'person_name', 
                        'related': [],
                        'confidence': 0.6
                    })
                    logger.info(f"🎯 Fallback entity created: {name}")

        context_strength = len(relevant_entities)

        should_use_context = (
            len(relevant_entities) > 0 and 
            any(entity['confidence'] > 0.3 for entity in relevant_entities)
        )

        entity_query_indicators = [
            'là ai', 'ai là', 'còn nhớ', 'vậy ', 'thế ', 
            'ông ', 'bà ', 'thầy ', 'cô ', 'anh ', 'chị '
        ]
        
        if not should_use_context:
            has_entity_pattern = any(indicator in current_query.lower() for indicator in entity_query_indicators)
            if has_entity_pattern and (relevant_entities or extracted_names):
                should_use_context = True
                logger.info(f"🎯 Force context enabled for entity query pattern")

        context_keywords = []
        if should_use_context:
            for name in extracted_names[:2]:
                if name not in context_keywords:
                    context_keywords.append(name)
            
            for entity_info in relevant_entities[:3]:  # Max 3 total
                if len(context_keywords) < 3 and entity_info['entity'] not in context_keywords:
                    context_keywords.append(entity_info['entity'])
        
        logger.info(f"🔍 DEBUG: should_use_context={should_use_context}, relevant_entities={len(relevant_entities)}")
        logger.info(f"🔍 DEBUG: context_keywords={context_keywords}")
        logger.info(f"🔍 DEBUG: context_strength={context_strength}")
        
        final_confidence = max([e['confidence'] for e in relevant_entities], default=0.0)
        if extracted_names and not relevant_entities:
            final_confidence = 0.6  # Fallback confidence
        
        return {
            'context_keywords': context_keywords,
            'related_entities': relevant_entities,
            'should_use_context': should_use_context,
            'context_strength': context_strength,
            'context_confidence': final_confidence,
            'extracted_names': extracted_names,  # For debugging
            'memory_reference_detected': bool(extracted_names),
            'fallback_used': not relevant_entities and bool(extracted_names)
        }
    
    def _names_match_flexible(self, name1: str, name2: str) -> bool:
        """🆕 NEW: Flexible name matching"""
        if not name1 or not name2:
            return False

        norm1 = self._normalize_for_matching(name1.lower())
        norm2 = self._normalize_for_matching(name2.lower())
        if norm1 == norm2:
            return True

        words1 = set(norm1.split())
        words2 = set(norm2.split())

        if len(words1) >= 2 and len(words2) >= 2:
            overlap = len(words1.intersection(words2))
            total_unique = len(words1.union(words2))
            overlap_ratio = overlap / total_unique if total_unique > 0 else 0

            return overlap_ratio >= 0.5

        if len(words1) == 1 and len(words2) == 1:
            word1, word2 = list(words1)[0], list(words2)[0]
            if len(word1) >= 3 and len(word2) >= 3:
                return word1 in word2 or word2 in word1
        
        return False
    
    def _is_entity_relevant_to_query_strict(self, normalized_query, entity_key, original_form):
        """🔧 IMPROVED: Flexible entity matching để tránh miss các variations"""
        entity_key_normalized = self._normalize_for_matching(entity_key)
        original_form_normalized = self._normalize_for_matching(original_form)
        
        if entity_key_normalized in normalized_query or original_form_normalized in normalized_query:
            logger.debug(f"🎯 Exact match found for '{original_form}'")
            return True
        
        entity_words = set(original_form_normalized.split())
        query_words = set(normalized_query.split())
        
        if len(entity_words) >= 2:
            overlap = len(entity_words.intersection(query_words))
            overlap_ratio = overlap / len(entity_words)
            
            if overlap_ratio >= 0.6:  
                logger.debug(f"🎯 Name parts match: {overlap}/{len(entity_words)} = {overlap_ratio:.2f}")
                return True
        
        if len(entity_words) >= 2:
            first_name = list(entity_words)[0]
            last_name = list(entity_words)[-1]
            
            if first_name in query_words and last_name in query_words:
                logger.debug(f"🎯 First + Last name match: '{first_name}' + '{last_name}'")
                return True
            
            if len(entity_words) >= 3:
                middle_name = list(entity_words)[1]
                if last_name in query_words and middle_name in query_words:
                    logger.debug(f"🎯 Middle + Last name match: '{middle_name}' + '{last_name}'")
                    return True
        
        titles = ['gs.ts', 'ts', 'gs', 'thầy', 'cô', 'giáo sư', 'tiến sĩ', 'ông', 'bà']
        query_has_title = any(title in normalized_query for title in titles)
        
        if query_has_title and len(entity_words) >= 2:
            last_name = list(entity_words)[-1]
            if last_name in query_words and len(last_name) > 2:
                logger.debug(f"🎯 Title + Last name match: '{last_name}'")
                return True
        
        return False
    
    def _normalize_for_matching(self, text):
        """🚀 FIX: Normalize text for better entity matching"""
        if not text:
            return ""
        normalized = text.lower().strip()
        normalized = re.sub(r'\b(dạ|ạ|à|ơi|nhé|vậy|thì|là|ai|gì|như|thế|nào)\b', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized

    def _is_entity_relevant_to_query(self, normalized_query, entity_key, original_form):
        entity_key_normalized = self._normalize_for_matching(entity_key)
        original_form_normalized = self._normalize_for_matching(original_form)
        
        if entity_key_normalized in normalized_query or entity_key in normalized_query.lower():
            logger.debug(f"📝 Match strategy 1: entity_key '{entity_key_normalized}' in query")
            return True
            
        if original_form_normalized in normalized_query or original_form.lower() in normalized_query.lower():
            logger.debug(f"📝 Match strategy 2: original_form '{original_form_normalized}' in query")
            return True
        
        entity_words = set(original_form_normalized.split())
        query_words = set(normalized_query.split())
        
        if len(entity_words) > 1:
            overlap = len(entity_words.intersection(query_words))
            overlap_ratio = overlap / len(entity_words)
            
            if overlap_ratio >= 0.7:
                logger.debug(f"📝 Match strategy 3: word overlap {overlap}/{len(entity_words)} = {overlap_ratio:.2f}")
                return True
        
        if len(entity_words) >= 2:
            last_word = list(entity_words)[-1]
            if len(last_word) > 2 and last_word in query_words:
                logger.debug(f"📝 Match strategy 4: last name '{last_word}' found")
                return True
        
        return False
    
    def _create_recent_conversation_summary(self, session_id: str) -> str:
        if session_id not in self.conversations:
            return ""
        
        history = self.conversations[session_id]['history']
        if len(history) < 2:
            return ""
        
        recent_interactions = history[-20:]
        
        summary_parts = []
        for interaction in recent_interactions:
            user_query = interaction['user_query'][:100]
            bot_response = interaction['bot_response'][:150]
            summary_parts.append(f"Hỏi: {user_query}... → Trả lời: {bot_response}...")
        
        return " | ".join(summary_parts)
    
    def _update_context_summary(self, session_id: str):
        conv = self.conversations[session_id]
        recent_queries = [h['user_query'] for h in conv['history'][-3:]]
        
        query_text = ' '.join(recent_queries).lower()
        
        if any(word in query_text for word in ['ngân hàng đề', 'đề thi', 'khảo thí']):
            conv['context_summary'] = 'Đang hỏi về ngân hàng đề thi'
        elif any(word in query_text for word in ['kê khai', 'nhiệm vụ', 'giờ chuẩn']):
            conv['context_summary'] = 'Đang hỏi về kê khai nhiệm vụ năm học'
        elif any(word in query_text for word in ['tạp chí', 'nghiên cứu', 'bài viết']):
            conv['context_summary'] = 'Đang hỏi về tạp chí khoa học'
        elif any(word in query_text for word in ['thi đua', 'khen thưởng', 'danh hiệu']):
            conv['context_summary'] = 'Đang hỏi về thi đua khen thưởng'
        elif any(word in query_text for word in ['báo cáo', 'nộp', 'hạn cuối']):
            conv['context_summary'] = 'Đang hỏi về báo cáo và thủ tục'
        elif any(word in query_text for word in ['lịch', 'thời khóa biểu', 'giảng dạy']):
            conv['context_summary'] = 'Đang hỏi về lịch giảng dạy'
        elif any(word in query_text for word in ['học phí', 'tiền', 'chi phí']):
            conv['context_summary'] = 'Đang quan tâm học phí'
        elif any(word in query_text for word in ['tuyển sinh', 'điểm', 'xét tuyển']):
            conv['context_summary'] = 'Đang hỏi về tuyển sinh'
        elif any(word in query_text for word in ['ngành', 'chuyên ngành', 'đào tạo']):
            conv['context_summary'] = 'Đang tìm hiểu về ngành học'
        elif any(word in query_text for word in ['cơ sở', 'phòng', 'trang thiết bị']):
            conv['context_summary'] = 'Đang hỏi về cơ sở vật chất'
        else:
            conv['context_summary'] = 'Hỏi đáp chung về BDU'
