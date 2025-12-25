# 1. TẠO FILE MỚI: vietnamese_normalizer.py (trong ai_models/)

import re
import unicodedata
import logging

logger = logging.getLogger(__name__)

class VietnameseNormalizer:
    def __init__(self):
        # Vietnamese diacritics mapping
        self.vietnamese_map = {
            # a variations
            'á': 'a', 'à': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
            'ă': 'a', 'ắ': 'a', 'ằ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
            'â': 'a', 'ấ': 'a', 'ầ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
            
            # e variations
            'é': 'e', 'è': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
            'ê': 'e', 'ế': 'e', 'ề': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
            
            # i variations
            'í': 'i', 'ì': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
            
            # o variations
            'ó': 'o', 'ò': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
            'ô': 'o', 'ố': 'o', 'ồ': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
            'ơ': 'o', 'ớ': 'o', 'ờ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
            
            # u variations
            'ú': 'u', 'ù': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
            'ư': 'u', 'ứ': 'u', 'ừ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
            
            # y variations
            'ý': 'y', 'ỳ': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
            
            # d variations
            'đ': 'd'
        }
        
        # Common abbreviations and variations
        self.abbreviation_map = {
            # Teaching related
            'gv': ['giảng viên', 'giang vien'],
            'sv': ['sinh viên', 'sinh vien'], 
            'hs': ['học sinh', 'hoc sinh'],
            'qv': ['quy định', 'quy dinh'],
            'hp': ['học phí', 'hoc phi'],
            'ts': ['tuyển sinh', 'tuyen sinh'],
            'dh': ['đại học', 'dai hoc'],
            'bdu': ['bình dương', 'binh duong', 'đại học bình dương'],
            
            # Common words
            'k': ['không', 'khong'],
            'ko': ['không', 'khong'],
            'dc': ['được', 'duoc'],
            'duoc': ['được'],
            'khong': ['không'],
            'gi': ['gì'],
            'lam': ['làm'],
            'bao nhieu': ['bao nhiêu'],
            'the nao': ['thế nào', 'thế nào'],
            'ra sao': ['ra sao'],
            
            # Numbers
            'gio': ['giờ'],
            'tiet': ['tiết'],
            'nam': ['năm'],
            'thang': ['tháng'],
            
            # Common verbs
            'day': ['dạy'],
            'hoc': ['học'],
            'lam': ['làm'],
            'di': ['đi'],
            'den': ['đến'],
            'duoi': ['dưới'],
            'tren': ['trên'],
            'trong': ['trong'],
            'ngoai': ['ngoài']
        }
        
        # Context-aware phrase mapping
        self.phrase_map = {
            'day bang tieng anh': 'dạy bằng tiếng anh',
            'hoc phi bao nhieu': 'học phí bao nhiêu',
            'tuyen sinh ra sao': 'tuyển sinh ra sao',
            'lam gi': 'làm gì',
            'the nao': 'thế nào',
            'bao gio': 'bao giờ',
            'o dau': 'ở đâu',
            'tai sao': 'tại sao',
            'co duoc khong': 'có được không',
            'can lien he': 'cần liên hệ',
            'lien he voi ai': 'liên hệ với ai',
            'ben nao': 'bên nào'
        }
        
        # Education-specific terms
        self.education_terms = {
            'giang vien': 'giảng viên',
            'sinh vien': 'sinh viên', 
            'hoc phi': 'học phí',
            'tuyen sinh': 'tuyển sinh',
            'dai hoc': 'đại học',
            'chuong trinh': 'chương trình',
            'nganh hoc': 'ngành học',
            'hoc bong': 'học bổng',
            'co so vat chat': 'cơ sở vật chất',
            'ky tuc xa': 'ký túc xá',
            'thu vien': 'thư viện',
            'phong thi nghiem': 'phòng thí nghiệm'
        }
        
        logger.info("✅ Vietnamese Normalizer initialized")
    
    def normalize_query(self, query):
        """Comprehensive query normalization"""
        if not query:
            return ""
        
        # Step 1: Basic cleaning
        normalized = query.lower().strip()
        
        # Step 2: Remove excessive punctuation
        normalized = re.sub(r'[?]{2,}', '?', normalized)
        normalized = re.sub(r'[!]{2,}', '!', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Step 3: Handle common typos and variations
        normalized = self._fix_common_typos(normalized)
        
        # Step 4: Expand abbreviations
        normalized = self._expand_abbreviations(normalized)
        
        # Step 5: Add diacritics back
        normalized = self._add_diacritics(normalized)
        
        # Step 6: Context-aware phrase replacement
        normalized = self._replace_phrases(normalized)
        
        return normalized.strip()
    
    def _fix_common_typos(self, text):
        """Fix common typing errors"""
        typo_fixes = {
            # Common typing errors
            'khoogn': 'khong',
            'ducoi': 'duoc',
            'tinhg': 'tinh',
            'themm': 'them',
            'gioo': 'gio',
            'dayy': 'day',
            'laaam': 'lam',
            'hocc': 'hoc',
            
            # Missing spaces
            'khongduoc': 'khong duoc',
            'baonhieu': 'bao nhieu',
            'thenao': 'the nao',
            'rasao': 'ra sao',
            'lienhe': 'lien he',
            'giaovien': 'giao vien',
            'sinhvien': 'sinh vien',
            'hocphi': 'hoc phi',
            'tuyensinh': 'tuyen sinh',
            'daihoc': 'dai hoc',
            
            # Extra spaces  
            'k h o n g': 'khong',
            'g i': 'gi',
            'l a m': 'lam',
            'd a y': 'day'
        }
        
        for typo, fix in typo_fixes.items():
            text = text.replace(typo, fix)
        
        return text
    
    def _expand_abbreviations(self, text):
        """Expand abbreviations to full words"""
        words = text.split()
        expanded_words = []
        
        for word in words:
            # Check if word is an abbreviation
            if word in self.abbreviation_map:
                # Use the first (most common) expansion
                expanded_words.append(self.abbreviation_map[word][0])
            else:
                expanded_words.append(word)
        
        return ' '.join(expanded_words)
    
    def _add_diacritics(self, text):
        """Add back Vietnamese diacritics using context"""
        # For education terms, replace with proper diacritics
        for no_accent, with_accent in self.education_terms.items():
            text = text.replace(no_accent, with_accent)
        
        return text
    
    def _replace_phrases(self, text):
        """Replace common phrases with standard forms"""
        for phrase, replacement in self.phrase_map.items():
            text = text.replace(phrase, replacement)
        
        return text
    
    def remove_diacritics(self, text):
        """Remove diacritics for matching purposes"""
        if not text:
            return ""
        
        # Method 1: Use mapping
        result = ""
        for char in text.lower():
            result += self.vietnamese_map.get(char, char)
        
        return result
    
    def create_search_variants(self, query):
        """Create multiple search variants of a query"""
        variants = [query]  # Original query
        
        # Add normalized version
        normalized = self.normalize_query(query)
        if normalized != query:
            variants.append(normalized)
        
        # Add no-diacritics version
        no_diacritics = self.remove_diacritics(query)
        if no_diacritics != query.lower():
            variants.append(no_diacritics)
        
        # Add keyword-based version
        keywords = self._extract_keywords(normalized)
        if keywords:
            variants.append(' '.join(keywords))
        
        return list(set(variants))  # Remove duplicates
    
    def _extract_keywords(self, text):
        """Extract important keywords from text"""
        # Remove stop words
        stop_words = {'là', 'của', 'và', 'có', 'được', 'này', 'đó', 'một', 'các', 'cho', 'với', 'từ', 'đã', 'sẽ', 'bị', 'về'}
        
        words = text.split()
        keywords = [word for word in words if word not in stop_words and len(word) > 1]
        
        return keywords

# 2. CẬP NHẬT phobert_service.py - THÊM NORMALIZE

class PhoBERTIntentClassifier:
    def __init__(self):
        # ... existing code ...
        
        # ADD: Initialize normalizer
        from .vietnamese_normalizer import VietnameseNormalizer
        self.normalizer = VietnameseNormalizer()
        
        # ... rest of existing init code ...
    
    def classify_intent(self, query):
        """Enhanced intent classification with normalization"""
        if not query or not query.strip():
            return {
                'intent': 'general',
                'confidence': 0.3,
                'description': 'Câu hỏi chung',
                'response_style': 'neutral'
            }
        
        # NORMALIZE QUERY FIRST
        normalized_query = self.normalizer.normalize_query(query)
        query_variants = self.normalizer.create_search_variants(query)
        
        print(f"🔍 NORMALIZE DEBUG: Original = '{query}'")
        print(f"🔍 NORMALIZE DEBUG: Normalized = '{normalized_query}'")
        print(f"🔍 NORMALIZE DEBUG: Variants = {query_variants}")
        
        intent_scores = {}
        
        # Method 1: Enhanced keyword matching with variants
        for variant in query_variants:
            variant_lower = variant.lower().strip()
            
            for intent, config in self.intent_categories.items():
                score = 0
                keyword_matches = 0
                
                for keyword in config['keywords']:
                    if keyword in variant_lower:
                        # Boost score for exact matches
                        if keyword == variant_lower:
                            score += 2
                        elif variant_lower.startswith(keyword) or variant_lower.endswith(keyword):
                            score += 1.5
                        else:
                            score += 1
                        keyword_matches += 1
                
                # Normalize and boost for multiple keyword matches
                if len(config['keywords']) > 0:
                    base_score = score / len(config['keywords'])
                    # Bonus for multiple keyword matches
                    if keyword_matches > 1:
                        base_score *= (1 + (keyword_matches - 1) * 0.2)
                    
                    # Update intent score with max from all variants
                    intent_scores[intent] = max(intent_scores.get(intent, 0), min(base_score, 1.0))
        
        # Method 2: Context-based boosting with normalized query
        self._boost_contextual_intents(normalized_query.lower(), intent_scores)
        
        # Method 3: PhoBERT similarity (if available)
        if not self.fallback_mode and self.model and self.tokenizer:
            try:
                # Use normalized query for semantic similarity
                self._add_semantic_similarity(normalized_query, intent_scores)
            except Exception as e:
                logger.warning(f"Semantic similarity failed, using fallback: {str(e)}")
        
        # Find best intent
        if intent_scores:
            best_intent = max(intent_scores.items(), key=lambda x: x[1])
            intent_name, confidence = best_intent
            
            # Dynamic threshold based on query complexity
            base_threshold = self.intent_categories[intent_name]['confidence_threshold']
            if self.fallback_mode:
                threshold = base_threshold * 0.6  # Lower threshold for fallback with normalization
            else:
                threshold = base_threshold * 0.8  # Slightly lower with normalization
            
            if confidence >= threshold:
                return {
                    'intent': intent_name,
                    'confidence': confidence,
                    'description': self.intent_categories[intent_name]['description'],
                    'response_style': self.intent_categories[intent_name]['response_style'],
                    'normalized_query': normalized_query  # Add for debugging
                }
        
        return {
            'intent': 'general',
            'confidence': 0.3,
            'description': 'Câu hỏi chung',
            'response_style': 'neutral',
            'normalized_query': normalized_query
        }

# 3. CẬP NHẬT services.py - ENHANCED EDUCATION DETECTION

def _is_education_related_query(self, query):
    """Enhanced education detection with normalization"""
    
    # Normalize query first
    normalized_query = self.intent_classifier.normalizer.normalize_query(query)
    query_variants = self.intent_classifier.normalizer.create_search_variants(query)
    
    print(f"🎓 EDUCATION DEBUG: Checking variants = {query_variants}")
    
    # Enhanced education keywords (including no-diacritics versions)
    education_keywords = [
        # With diacritics
        'trường', 'học', 'sinh viên', 'tuyển sinh', 'học phí', 'ngành', 
        'đại học', 'giáo dục', 'đào tạo', 'chương trình', 'điểm', 'xét tuyển',
        'bình dương', 'bdu', 'giảng viên', 'giảng dạy', 'giờ chuẩn', 'nghiên cứu',
        'dạy', 'thầy', 'cô', 'học bổng', 'học vị', 'học hàm',
        
        # Without diacritics (common user input)
        'truong', 'hoc', 'sinh vien', 'tuyen sinh', 'hoc phi', 'nganh',
        'dai hoc', 'giao duc', 'dao tao', 'chuong trinh', 'diem', 'xet tuyen',
        'binh duong', 'giang vien', 'giang day', 'gio chuan', 'nghien cuu',
        'day', 'thay', 'co', 'hoc bong', 'hoc vi', 'hoc ham',
        
        # Abbreviations
        'sv', 'hs', 'gv', 'qv', 'đh', 'hp', 'ts',
        
        # Common teaching terms
        'làm', 'công việc', 'nhiệm vụ', 'hoạt động', 'quy định', 'chế độ',
        'lam', 'cong viec', 'nhiem vu', 'hoat dong', 'quy dinh', 'che do',
        
        # Course-related
        'tiết', 'môn', 'lớp', 'khóa', 'kỳ', 'năm học',
        'tiet', 'mon', 'lop', 'khoa', 'ky', 'nam hoc'
    ]
    
    # Context indicators
    context_indicators = [
        'trường', 'đại học', 'bình dương', 'bdu', 'mình', 'chúng ta', 'ở đây',
        'trong trường', 'tại trường', 'trường này',
        'truong', 'dai hoc', 'binh duong', 'minh', 'chung ta', 'o day',
        'trong truong', 'tai truong', 'truong nay'
    ]
    
    # Check all variants
    for variant in query_variants:
        variant_lower = variant.lower()
        
        # Count keywords and context
        keyword_count = sum(1 for kw in education_keywords if kw in variant_lower)
        context_count = sum(1 for ctx in context_indicators if ctx in variant_lower)
        
        print(f"🎓 EDUCATION DEBUG: Variant '{variant}' - Keywords: {keyword_count}, Context: {context_count}")
        
        # Enhanced logic
        if context_count > 0:
            # Has context → lower threshold
            if keyword_count >= 1:
                print(f"🎓 EDUCATION DEBUG: MATCH - Context + Keywords")
                return True
        else:
            # No context → need more keywords
            if keyword_count >= 2:
                print(f"🎓 EDUCATION DEBUG: MATCH - Multiple Keywords")
                return True
            elif keyword_count == 1:
                # Check for strong education keywords
                strong_keywords = ['gv', 'giảng viên', 'giang vien', 'dạy', 'day', 'sinh viên', 'sinh vien', 'học phí', 'hoc phi']
                if any(strong_kw in variant_lower for strong_kw in strong_keywords):
                    print(f"🎓 EDUCATION DEBUG: MATCH - Strong Keyword")
                    return True
        
        # Special patterns for teaching-related queries
        teaching_patterns = [
            'dạy bằng', 'day bang', 'giờ chuẩn', 'gio chuan', 'định mức', 'dinh muc',
            'gv', 'giảng viên', 'giang vien', 'giảng dạy', 'giang day'
        ]
        
        if any(pattern in variant_lower for pattern in teaching_patterns):
            print(f"🎓 EDUCATION DEBUG: MATCH - Teaching Pattern")
            return True
    
    print(f"🎓 EDUCATION DEBUG: NO MATCH")
    return False

# 4. CẬP NHẬT ChatbotAI retrieval với multiple variants

def semantic_search(self, query, top_k=3):
    """Enhanced semantic search with query variants"""
    try:
        if not self.model or not self.index:
            return self.keyword_search(query)
        
        # Create multiple search variants
        from ai_models.vietnamese_normalizer import VietnameseNormalizer
        normalizer = VietnameseNormalizer()
        query_variants = normalizer.create_search_variants(query)
        
        print(f"🔍 SEARCH DEBUG: Searching with variants = {query_variants}")
        
        all_results = []
        
        # Search with each variant
        for variant in query_variants:
            variant_embedding = self.model.encode([variant])
            faiss.normalize_L2(variant_embedding)
            
            scores, indices = self.index.search(variant_embedding.astype('float32'), top_k)
            
            for score, idx in zip(scores[0], indices[0]):
                if idx < len(self.knowledge_data):
                    result = self.knowledge_data[idx].copy()
                    result['similarity'] = float(score)
                    result['search_variant'] = variant
                    all_results.append(result)
        
        # Remove duplicates and sort by similarity
        seen_indices = set()
        unique_results = []
        
        for result in sorted(all_results, key=lambda x: x['similarity'], reverse=True):
            # Use question as unique identifier
            question_key = result['question'].lower()
            if question_key not in seen_indices:
                seen_indices.add(question_key)
                unique_results.append(result)
        
        best_result = unique_results[0] if unique_results else None
        return best_result, unique_results[:top_k]
        
    except Exception as e:
        logger.error(f"Enhanced semantic search error: {str(e)}")
        return self.keyword_search(query)