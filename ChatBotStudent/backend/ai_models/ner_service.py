import re
import logging
import time

logger = logging.getLogger(__name__)

class SimpleEntityExtractor:
    """
    Trích xuất thực thể đơn giản (NER) bằng Regex có mục tiêu (Targeted Regex).
    Chỉ trích xuất các thực thể rõ ràng để tránh làm ô nhiễm context memory.
    """
    
    def __init__(self):
        # --- SỬA LỖI: Định nghĩa lại hoàn toàn các pattern ---
        self.entity_patterns = {
            'person_name': [
                # Chỉ bắt tên (1-3 từ) SAU KHI có các chức danh
                r'(?:thầy|cô|ông|bà|GS\.TS\.|TS\.|GS\.|tiến sĩ|giáo sư)\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){0,2})\b',
                # Bắt tên đầy đủ (2-4 từ) viết hoa
                r'\b([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})\b'
            ],
            'position': [
                r'\b(hiệu trưởng|phó hiệu trưởng|trưởng phòng|phó trưởng phòng|trưởng khoa|phó trưởng khoa)\b'
            ],
            'department': [
                r'\b(khoa [A-ZÀ-Ỹ][A-Za-zà-ỹ\s]+|phòng [A-ZÀ-Ỹ][A-Za-zà-ỹ\s]+|ban [A-ZÀ-Ỹ][A-Za-zà-ỹ\s]+)\b'
            ],
            'dates': [
                r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                r'(học kỳ \d+|năm học \d{4}-\d{4})'
            ]
        }
        
        # ✅ FIX #3.1: EXPANDED BLACKLIST - Loại bỏ các từ bị nhận nhầm là TÊN
        self.person_name_blacklist = {
            # Ngày trong tuần
            'thứ hai', 'thứ ba', 'thứ tư', 'thứ năm', 'thứ sáu', 'thứ bảy', 'chủ nhật',
            'thứ 2', 'thứ 3', 'thứ 4', 'thứ 5', 'thứ 6', 'thứ 7', 'thứ 8',
            'hôm nay', 'hôm qua', 'ngày mai', 'tuần này', 'tuần sau',
            
            # Greeting phrases
            'chào bạn', 'xin chào', 'chúc bạn', 'kính chào', 'chào mừng',
            'chào tài', 'chào hiệp', 'chào mọi người',
            
            # Common phrases
            'chúc bạn học tốt', 'bạn vui lòng cho', 'mình biết tuần này', 
            'ví dụ', 'hỏi nào khác', 'vui lòng cho',
            
            # Academic terms
            'công nghệ thông tin', 'đại học bình dương', 'lập trình web',
            'thời khóa biểu', 'liệu thời khóa biểu', 'học phí', 'học kỳ', 
            'năm học', 'tín chỉ', 'môn học', 'lớp học', 'khóa học',
            
            # Organizational terms
            'trân trọng', 'kính gửi', 'thân gửi', 'trung tâm', 
            'phòng đào tạo', 'khoa', 'bộ môn', 'ban', 'phòng ban',
            
            # Questions/Requests
            'cho biết', 'cho tôi', 'giúp tôi', 'vui lòng',
        }
        
        # ✅ FIX #3.2: QUESTION WORDS để filter department/position
        self.question_words = {
            'gì', 'nào', 'đâu', 'sao', 'thế nào', 'như thế nào', 
            'nhé', 'ạ', 'hả', 'à', 'hả', 'không'
        }
        
        # ✅ FIX #3.3: TIME INDICATORS để tránh extract ngày làm entity
        self.time_indicators = {
            'thứ', 'hôm', 'ngày', 'tháng', 'năm', 'tuần', 'tối', 'sáng', 'chiều', 'trưa'
        }
        
        logger.info("✅ Targeted SimpleEntityExtractor initialized with expanded filters.")

    def extract_entities(self, text, query_context=""):
        if not text:
            return {}
            
        entities = {}
        text_cleaned = re.sub(r'\s+', ' ', text.strip())
        
        for entity_type, patterns in self.entity_patterns.items():
            found_entities = []
            for pattern in patterns:
                # Dùng re.IGNORECASE cho các chức danh (position, department)
                flags = re.IGNORECASE if entity_type != 'person_name' else 0
                matches = re.finditer(pattern, text_cleaned, flags)
                
                for match in matches:
                    # Luôn lấy group(1) nếu có, vì group(0) sẽ chứa cả chức danh
                    entity_value = match.group(1) if match.groups() else match.group(0)
                    entity_value = entity_value.strip().rstrip('.,')
                    
                    if self._is_valid_entity(entity_value, entity_type, text_cleaned):
                        normalized_value = self._normalize_entity(entity_value, entity_type)
                        if normalized_value not in found_entities:
                            found_entities.append(normalized_value)
            
            if found_entities:
                entities[entity_type] = found_entities
        
        logger.debug(f"🔍 Entity extraction result: {entities}")
        return entities

    def _is_valid_entity(self, entity_value, entity_type, full_text=""):
        """
        ✅ FIX #3.4: ENHANCED VALIDATION với nhiều check hơn
        """
        if not entity_value or len(entity_value.strip()) < 3:
            return False
            
        entity_lower = entity_value.lower().strip()
        
        # ✅ CHECK 1: Blacklist cho person_name
        if entity_type == 'person_name':
            if entity_lower in self.person_name_blacklist:
                logger.debug(f"🚫 Rejected by person blacklist: '{entity_value}'")
                return False
            
            # Check xem có phải câu hoàn chỉnh không
            sentence_starters = ['chúc', 'hỏi', 'ví dụ', 'liệu', 'bạn', 'mình', 'cho', 'giúp', 'vui lòng']
            if entity_lower.startswith(tuple(sentence_starters)):
                logger.debug(f"🚫 Rejected sentence-like entity: '{entity_value}'")
                return False
            
            # ✅ CHECK 2: Time indicators (tránh "Thứ Ba", "Hôm Nay")
            words = entity_lower.split()
            if any(word in self.time_indicators for word in words):
                logger.debug(f"🚫 Rejected time indicator in name: '{entity_value}'")
                return False

        # ✅ CHECK 3: Question words cho department/position
        if entity_type in ['department', 'position']:
            words = entity_lower.split()
            if any(word in self.question_words for word in words):
                logger.debug(f"🚫 Rejected question word in {entity_type}: '{entity_value}'")
                return False
            
            # Tránh pattern "khoa gì", "phòng nào", etc.
            if re.search(r'(khoa|phòng|ban)\s+(gì|nào|đâu|nhé|ạ)', entity_lower):
                logger.debug(f"🚫 Rejected question pattern in {entity_type}: '{entity_value}'")
                return False

        # ✅ CHECK 4: Các từ rác chung
        noise_words = {'là', 'của', 'và', 'để', 'trong', 'có', 'không', 'được', 'thì', 'này', 'đó'}
        entity_words = set(entity_lower.split())
        if len(entity_words.intersection(noise_words)) > 0:
            logger.debug(f"🚫 Rejected noise word in entity: '{entity_value}'")
            return False

        # ✅ CHECK 5: Too short sau khi remove prefix
        clean_words = [w for w in entity_lower.split() if w not in {'khoa', 'phòng', 'ban'}]
        if entity_type in ['department', 'position'] and len(' '.join(clean_words)) < 3:
            logger.debug(f"🚫 Rejected too short {entity_type}: '{entity_value}'")
            return False

        logger.debug(f"✅ Valid entity: '{entity_value}' (type: {entity_type})")
        return True

    def _normalize_entity(self, name, entity_type):
        """Chuẩn hóa entity"""
        if entity_type == 'person_name':
            # Viết hoa chữ cái đầu mỗi từ
            words = name.lower().split()
            normalized_words = [word[0].upper() + word[1:] for word in words if word]
            return ' '.join(normalized_words)
        
        return name.lower() # Giữ nguyên case cho các loại khác nếu cần, hoặc lower()

    def build_entity_relationships(self, query, answer, entities):
        """Build relationships between entities"""
        relationships = []
        if 'person_name' in entities and 'position' in entities:
            for person in entities['person_name']:
                for position in entities['position']:
                    relationships.append({
                        'type': 'person_position',
                        'entity1': person,
                        'entity2': position,
                        'relation': 'has_position',
                        'confidence': 0.8,
                        'source': 'context'
                    })
        return relationships

    def get_context_keywords(self, entities, relationships):
        """Get context keywords from entities"""
        context_keywords = []
        if 'person_name' in entities:
            context_keywords.extend(entities['person_name'][:2])
        if 'position' in entities:
            context_keywords.extend(entities['position'][:1])
        context_keywords = list(set(context_keywords))
        return [kw for kw in context_keywords if len(kw.strip()) > 2][:3]