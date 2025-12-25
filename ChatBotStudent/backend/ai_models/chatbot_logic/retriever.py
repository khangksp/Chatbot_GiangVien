import numpy as np
import faiss
import os
import re
import pandas as pd
import io
import logging
from django.conf import settings
from knowledge.models import KnowledgeBase
from qa_management.services import drive_service
from qa_management.models import QAEntry
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

class ChatbotAI:
    def __init__(self, shared_response_generator):
        print("--- CHECKPOINT 3: ChatbotAI (Retriever) __init__ started ---")
        self.model = None
        self.index = None
        self.knowledge_data = []
        self.vietnamese_restorer = shared_response_generator.vietnamese_restorer
        self.link_mapping = {}
        self.cached_data = None
        self.cache_timestamp = 0
        self.load_models()
    def load_models(self):
        try:
            from sentence_transformers import SentenceTransformer
            fine_tuned_path = os.path.join(settings.BASE_DIR, 'fine_tuned_phobert')
            if os.path.exists(fine_tuned_path):
                self.model = SentenceTransformer(fine_tuned_path)
                logger.info("✅ Fine-tuned SBERT loaded from: fine_tuned_phobert")
            else:
                self.model = SentenceTransformer('keepitreal/vietnamese-sbert')
                logger.info("✅ Base Vietnamese SBERT loaded")
            self.load_knowledge_base()
        except Exception as e:
            logger.error(f"Error loading models: {str(e)}")
            self.model = None
    def load_link_mapping(self):
        try:
            link_csv_content = drive_service.get_specific_csv_content('link.csv')
            if link_csv_content:
                df_links = pd.read_csv(io.StringIO(link_csv_content), encoding='utf-8')
                logger.info(f"✅ Loaded link mapping from GOOGLE DRIVE")
            else:
                raise ValueError("No content from Drive, attempting fallback")
        except Exception as e:
            logger.warning(f"⚠️ Could not load link.csv from Google Drive (Reason: {e}). Attempting local fallback...")
            try:
                fallback_path = os.path.join(settings.BASE_DIR, 'data', 'link.csv')
                if os.path.exists(fallback_path):
                    df_links = pd.read_csv(fallback_path, encoding='utf-8')
                    logger.info(f"✅ Fallback: Loaded link mapping from local file (data/link.csv)")
                else:
                    logger.error("❌ CRITICAL: Could not load link.csv from Google Drive or local fallback. Link mapping will be empty.")
                    self.link_mapping = {}
                    return
            except Exception as fallback_e:
                logger.error(f"❌ CRITICAL: Error reading local fallback link.csv file: {fallback_e}")
                self.link_mapping = {}
                return
        self.link_mapping = {}
        for index, row in df_links.iterrows():
            stt = str(row.get('STT', '')).strip()
            link = str(row.get('Link', '')).strip()
            if stt and link and stt != 'nan' and link != 'nan':
                self.link_mapping[stt] = link
        
        logger.info(f"✅ Successfully processed {len(self.link_mapping)} reference links.")
    def get_reference_links(self, qa_item):
        reference_links = []
        stt_value = qa_item.get('STT', '')
        if not stt_value:
            return reference_links
        stt_list = []
        if isinstance(stt_value, str):
            stt_parts = re.split(r'[,;\s]+', stt_value.strip())
            stt_list = [part.strip() for part in stt_parts if part.strip()]
        else:
            stt_list = [str(stt_value).strip()]
        for stt in stt_list:
            if stt in self.link_mapping:
                link_url = self.link_mapping[stt]
                reference_links.append({
                    'stt': stt,
                    'url': link_url,
                    'title': f"Tài liệu tham khảo {stt}"
                })        
        return reference_links
    def load_knowledge_base(self):
        print("--- CHECKPOINT 4: Loading Knowledge Base... ---")
        try:
            self.load_link_mapping()
            
            # Khởi tạo danh sách trống để đảm bảo dữ liệu sạch mỗi lần tải lại
            all_entries = []
            # Dùng set để kiểm tra trùng lặp câu hỏi
            unique_questions = set()

            # 1. Tải từ QA Management Django App
            try:
                from qa_management.models import QAEntry
                qa_entries = QAEntry.objects.filter(is_active=True).order_by('stt')
                
                count = 0
                for entry in qa_entries:
                    if entry.question not in unique_questions:
                        all_entries.append({
                            'question': entry.question,
                            'answer': entry.answer,
                            'category': entry.category or 'sinh viên',
                            'STT': entry.stt
                        })
                        unique_questions.add(entry.question)
                        count += 1
                if count > 0:
                    logger.info(f"✅ Loaded {count} unique entries from QA Management database")
            except Exception as e:
                logger.warning(f"⚠️ QA Management not available or failed: {str(e)}")

            # 2. Tải từ Google Drive
            try:
                drive_data = drive_service.get_csv_data()
                if drive_data:
                    count = 0
                    for item in drive_data:
                        question = item.get('question')
                        if question and question not in unique_questions:
                            all_entries.append(item)
                            unique_questions.add(question)
                            count += 1
                    if count > 0:
                        logger.info(f"✅ Loaded {count} unique records from Google Drive")
            except Exception as e:
                logger.error(f"❌ Failed to load from Google Drive: {str(e)}")

            # 3. Tải từ CSDL KnowledgeBase (nếu có)
            try:
                db_knowledge = list(KnowledgeBase.objects.filter(is_active=True).values(
                    'question', 'answer', 'category'
                ))
                count = 0
                for item in db_knowledge:
                    question = item.get('question')
                    if question and question not in unique_questions:
                        all_entries.append(item)
                        unique_questions.add(question)
                        count += 1
                if count > 0:
                    logger.info(f"✅ Loaded {count} unique entries from KnowledgeBase model")
            except Exception as e:
                logger.warning(f"⚠️ KnowledgeBase model not available or failed: {str(e)}")


            # 4. Fallback: Tải từ file CSV local nếu tất cả các nguồn trên đều trống
            if not all_entries:
                csv_path = os.path.join(settings.BASE_DIR, 'data', 'QA.csv')
                logger.warning(f"No data from primary sources. Attempting local fallback: {csv_path}")
                if os.path.exists(csv_path):
                    try:
                        df = pd.read_csv(csv_path, encoding='utf-8')
                        # Xử lý an toàn hơn: Bỏ các dòng có question hoặc answer rỗng
                        df.dropna(subset=['question', 'answer'], inplace=True)
                        
                        count = 0
                        for index, row in df.iterrows():
                            question = str(row['question'])
                            if question not in unique_questions:
                                all_entries.append({
                                    'question': question,
                                    'answer': str(row['answer']),
                                    'category': str(row.get('category', 'Chung')),
                                    'STT': str(row.get('STT', ''))
                                })
                                unique_questions.add(question)
                                count += 1
                        if count > 0:
                            logger.info(f"✅ Fallback: Loaded {count} unique records from local CSV")
                    except Exception as e:
                        logger.error(f"❌ Fallback CSV loading failed: {str(e)}")
                else:
                    logger.error(f"❌ CRITICAL: Fallback file data/QA.csv not found!")

            # Gán dữ liệu cuối cùng và xây dựng index
            self.knowledge_data = all_entries
            
            if self.knowledge_data:
                logger.info(f"✅ Total unique knowledge base entries loaded: {len(self.knowledge_data)}")
                if self.model:
                    self.build_faiss_index() # Gọi hàm đã sửa lỗi
                else:
                    logger.error("❌ Cannot build FAISS index because SBERT model is not loaded.")
            else:
                logger.error("❌ CRITICAL: Knowledge base is EMPTY. Chatbot will not be able to answer questions from QA data.")

        except Exception as e:
            logger.error(f"A critical error occurred in load_knowledge_base: {str(e)}")
            self.knowledge_data = []
            self.index = None
    def build_faiss_index(self):
        try:
            # Lọc ra những item hợp lệ (là dict và có key 'question')
            valid_items = [item for item in self.knowledge_data if isinstance(item, dict) and 'question' in item]
            if not valid_items:
                logger.warning("⚠️ No valid questions found in knowledge_data to build FAISS index.")
                self.index = None
                return

            # SỬA LỖI: dùng 'item' thay vì 'itmình'
            questions = [item['question'] for item in valid_items]
            embeddings = self.model.encode(questions)
            
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dimension)            
            faiss.normalize_L2(embeddings)
            self.index.add(embeddings.astype('float32'))            
            logger.info(f"✅ FAISS index built with {len(questions)} entries")            
        except Exception as e:
            logger.error(f"Error building FAISS index: {str(e)}")
            self.index = None
    def semantic_search_top_k(self, query, top_k=20):
        try:
            if not self.model or not self.index:
                logger.warning("⚠️ Model or index not available")
                return []
            
            if self.vietnamese_restorer and not self.vietnamese_restorer.has_vietnamese_accents(query):
                restored_query = self.vietnamese_restorer.restore_vietnamese_tone(query)
                if restored_query != query:
                    logger.info(f"🎯 Using restored query: '{query}' -> '{restored_query}'")
                    query = restored_query
            
            query_embedding = self.model.encode([query])
            faiss.normalize_L2(query_embedding)            
            scores, indices = self.index.search(query_embedding.astype('float32'), min(top_k, len(self.knowledge_data)))            
            candidates = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < len(self.knowledge_data) and score > 0.1:
                    candidate = self.knowledge_data[idx].copy()
                    candidate['semantic_score'] = float(score)
                    candidate['similarity'] = float(score)
                    candidate['reference_links'] = self.get_reference_links(candidate)
                    candidates.append(candidate)
            
            logger.info(f"🔍 Semantic search found {len(candidates)} candidates")
            return candidates
            
        except Exception as e:
            logger.error(f"Semantic search error: {str(e)}")
            return []
    
    def semantic_search_with_context(self, query, context_keywords=None, top_k=20):
        """🆕 THÊM MỚI: Semantic search với context enhancement"""
        try:
            if not self.model or not self.index:
                logger.warning("⚠️ Model or index not available for context search")
                return []
            
            original_query = query
            if self.vietnamese_restorer and not self.vietnamese_restorer.has_vietnamese_accents(query):
                restored_query = self.vietnamese_restorer.restore_vietnamese_tone(query)
                if restored_query != query:
                    logger.info(f"🎯 Using restored query for context search: '{query}' -> '{restored_query}'")
                    query = restored_query
            
            enhanced_query = query
            if context_keywords and len(context_keywords) > 0:
                context_str = " ".join(context_keywords[:3])  # Chỉ dùng 3 keywords đầu
                enhanced_query = f"{query} {context_str}"
                logger.info(f"🔍 Enhanced query với context: '{query}' -> '{enhanced_query}'")
            
            query_embedding = self.model.encode([enhanced_query])
            faiss.normalize_L2(query_embedding)
            
            scores, indices = self.index.search(
                query_embedding.astype('float32'), 
                min(top_k, len(self.knowledge_data))
            )
            candidates = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < len(self.knowledge_data) and score > 0.1:
                    candidate = self.knowledge_data[idx].copy()
                    candidate['semantic_score'] = float(score)
                    candidate['similarity'] = float(score)
                    candidate['reference_links'] = self.get_reference_links(candidate)
                    candidate['context_enhanced'] = bool(context_keywords)
                    candidate['context_keywords_used'] = context_keywords or []
                    candidates.append(candidate)
            
            logger.info(f"🔍 Context-enhanced search found {len(candidates)} candidates")
            return candidates
        except Exception as e:
            logger.error(f"Context-enhanced search error: {str(e)}")
            return self.semantic_search_top_k(query, top_k)

    def dual_semantic_search(self, query, context_keywords=None, top_k=20):
        try:
            logger.info(f"🔄 STABLE Dual semantic search for: '{query}' with context: {context_keywords}")
            
            normal_candidates = self.semantic_search_top_k(query, top_k)
            logger.info(f"🔍 Normal search: {len(normal_candidates)} candidates, top_score={normal_candidates[0].get('semantic_score', 0):.3f if normal_candidates else 0}")
            context_candidates = []
            if context_keywords and len(context_keywords) > 0:
                context_candidates = self.semantic_search_with_context(query, context_keywords, top_k)
                logger.info(f"🔍 Context search: {len(context_candidates)} candidates, top_score={context_candidates[0].get('semantic_score', 0):.3f if context_candidates else 0}")
            if not context_candidates or len(context_candidates) == 0:
                logger.info("🔍 Using normal search (no context results)")
                return normal_candidates, 'normal'
            if not normal_candidates or len(normal_candidates) == 0:
                logger.info("🔍 Using context search (no normal results)")  
                return context_candidates, 'context'
            normal_top_score = normal_candidates[0].get('semantic_score', 0)
            context_top_score = context_candidates[0].get('semantic_score', 0)
            score_diff = context_top_score - normal_top_score
            if score_diff > 0.2:
                logger.info(f"🔍 Context significantly better (+{score_diff:.3f}) - using context")
                return context_candidates, 'context'
            elif score_diff < -0.05:
                logger.info(f"🔍 Normal clearly better ({score_diff:.3f}) - using normal")
                return normal_candidates, 'normal'
            else:
                query_lower = query.lower()
                if any(pronoun in query_lower for pronoun in ['ông ấy', 'bà ấy', 'người đó', 'thầy ấy', 'cô ấy']):
                    logger.info(f"🔍 Query has pronoun - preferring context (score_diff: {score_diff:.3f})")
                    return context_candidates, 'context'
                has_proper_name = any(word[0].isupper() for word in query.split() if len(word) > 1)
                if has_proper_name:
                    logger.info(f"🔍 Query has proper names - preferring normal for stability (score_diff: {score_diff:.3f})")
                    return normal_candidates, 'normal'
                logger.info(f"🔍 Ambiguous case - preferring normal for stability (score_diff: {score_diff:.3f})")
                return normal_candidates, 'normal'
            
        except Exception as e:
            logger.error(f"Dual search error: {str(e)}")
            return self.semantic_search_top_k(query, top_k), 'fallback'