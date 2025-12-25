import numpy as np
import faiss
import time
import os
import re
from django.conf import settings
from knowledge.models import KnowledgeBase
import logging
from .gemini.core import GeminiResponseGenerator, LocalQwenGenerator, SimpleVietnameseRestorer
import pandas as pd
import io
import re

from .external_api_service import external_api_service
from qa_management.services import drive_service
from .interaction_logger_service import interaction_logger
from .query_response_cache import query_response_cache

logger = logging.getLogger(__name__)

class SemanticReRanker:
    def __init__(self, retriever_service):
        self.retriever_service = retriever_service
        self.config = {
            'stage1_top_k': 20,      # Get more candidates for re-ranking
            'stage2_top_n': 8,       # 🔬 ENHANCED: 3 → 5 to catch more correct answers
            'cross_encoder_enabled': True,
            'semantic_weight': 0.6,   # Weight for original semantic score
            'cross_encoder_weight': 0.4,  # Weight for cross-encoder score
            'min_score_threshold': 0.1,    # Minimum score to consider
            'smart_penalty_enabled': True,  # FIXED: Smart penalty system
            'confidence_preservation': True,  # FIXED: Preserve high confidence
            'adaptive_penalty_rates': {    # FIXED: Adaptive penalty rates
                'very_high': 0.05,  # Very light penalty for very high confidence
                'high': 0.1,        # Light penalty for high confidence
                'medium': 0.15,     # Moderate penalty for medium confidence
                'low': 0.25         # Heavy penalty for low confidence
            }
        }
        
        logger.info("🎯 ENHANCED SemanticReRanker initialized with smart penalty + top-5 selection")
        logger.info(f"   📊 Stage 1: Top-{self.config['stage1_top_k']} semantic retrieval")
        logger.info(f"   🔄 Stage 2: Top-{self.config['stage2_top_n']} cross-encoder re-ranking")
        logger.info(f"   🧠 Smart penalty: {self.config['smart_penalty_enabled']}")
        logger.info(f"   🛡️ Confidence preservation: {self.config['confidence_preservation']}")
        logger.info(f"   🔬 Top-5 candidate selection enabled")

    def calculate_semantic_boost(self, candidate, query):
        boost = 0.0
        answer_length = len(candidate.get('answer', ''))
        if 100 <= answer_length <= 500:  # Optimal length range
            boost += 0.05
        elif answer_length > 1000:  # Penalty for very long answers
            boost -= 0.05
        
        question = candidate.get('question', '')
        answer = candidate.get('answer', '')        
        query_words = set(query.lower().split())
        question_words = set(question.lower().split())
        answer_words = set(answer.lower().split())        
        question_overlap = len(query_words.intersection(question_words)) / max(len(query_words), 1)
        if question_overlap > 0.3:
            boost += 0.1        
        return min(0.2, boost)

    def _detect_mismatch_severity(self, candidate, query):
        query_lower = query.lower()
        question_lower = candidate.get('question', '').lower()
        answer_lower = candidate.get('answer', '').lower()        
        mismatch_analysis = {
            'concept_severity': 0.0,
            'topic_severity': 0.0, 
            'context_severity': 0.0,
            'issues': []
        }        
        concept_conflicts = [
            {
                'query_concepts': ['báo cáo khối lượng công việc', 'báo cáo nhiệm vụ giảng viên'],
                'wrong_concepts': ['khối lượng học tập sinh viên', 'tín chỉ sinh viên'],
                'severity': 0.8,  # High severity
                'description': 'Work reporting vs Student credit hours'
            },
            {
                'query_concepts': ['tài khoản đóng học phí', 'số tài khoản ngân hàng'],
                'wrong_concepts': ['tài khoản đăng nhập', 'tài khoản khảo sát'],
                'severity': 0.7,  # High severity
                'description': 'Bank account vs Login account'
            },
            {
                'query_concepts': ['kê khai nhiệm vụ giảng viên'],
                'wrong_concepts': ['đăng ký môn học sinh viên'],
                'severity': 0.5,  # Medium severity
                'description': 'Faculty duty vs Student registration'
            },
            {
                'query_concepts': ['lịch giảng dạy giảng viên'],
                'wrong_concepts': ['lịch học sinh viên'],
                'severity': 0.4,  # Medium-low severity
                'description': 'Teaching vs Learning schedule'
            }
        ]
        
        for conflict in concept_conflicts:
            query_has = any(concept in query_lower for concept in conflict['query_concepts'])
            answer_has_wrong = any(concept in answer_lower for concept in conflict['wrong_concepts'])            
            if query_has and answer_has_wrong:
                mismatch_analysis['concept_severity'] = max(
                    mismatch_analysis['concept_severity'], 
                    conflict['severity']
                )
                mismatch_analysis['issues'].append(f"Concept: {conflict['description']}")        
        topic_irrelevance = [
            {
                'query_topics': ['học phí', 'lệ phí'],
                'irrelevant_topics': ['cuộc thi', 'moswc', 'viettel', 'robot'],
                'severity': 0.9,  # Very high - completely different domain
                'description': 'Education fees vs Competition'
            },
            {
                'query_topics': ['báo cáo'],
                'irrelevant_topics': ['sinh viên tham gia cuộc thi'],
                'severity': 0.6,  # Medium-high
                'description': 'Reporting vs Student activities'
            },
            {
                'query_topics': ['tài khoản ngân hàng'],
                'irrelevant_topics': ['khảo sát đánh giá'],
                'severity': 0.7,  # High
                'description': 'Banking vs Survey system'
            }
        ]        
        for irrelevance in topic_irrelevance:
            query_has_topic = any(topic in query_lower for topic in irrelevance['query_topics'])
            answer_has_irrelevant = any(topic in answer_lower for topic in irrelevance['irrelevant_topics'])            
            if query_has_topic and answer_has_irrelevant:
                mismatch_analysis['topic_severity'] = max(
                    mismatch_analysis['topic_severity'],
                    irrelevance['severity']
                )
                mismatch_analysis['issues'].append(f"Topic: {irrelevance['description']}")
        
        context_checks = [
            {
                'query_pattern': ['giảng viên', 'cán bộ'],
                'answer_wrong': ['sinh viên chỉ', 'dành riêng sinh viên'],
                'severity': 0.3,  # Light penalty for context mismatch
                'description': 'Faculty vs Student role'
            }
        ]
        
        for check in context_checks:
            query_has_pattern = any(pattern in query_lower for pattern in check['query_pattern'])
            answer_has_wrong = any(wrong in answer_lower for wrong in check['answer_wrong'])            
            if query_has_pattern and answer_has_wrong:
                mismatch_analysis['context_severity'] = max(
                    mismatch_analysis['context_severity'],
                    check['severity']
                )
                mismatch_analysis['issues'].append(f"Context: {check['description']}")        
        return mismatch_analysis

    def _calculate_smart_penalty(self, candidate, query, base_semantic_score):
        if not self.config['smart_penalty_enabled']:
            return 0.0, []            
        mismatch_analysis = self._detect_mismatch_severity(candidate, query)        
        if not mismatch_analysis['issues']:
            return 0.0, []  # No mismatch detected        
        if base_semantic_score >= 0.8:
            confidence_tier = 'very_high'
        elif base_semantic_score >= 0.65:
            confidence_tier = 'high'
        elif base_semantic_score >= 0.45:
            confidence_tier = 'medium'
        else:
            confidence_tier = 'low'        
        max_penalty_rate = self.config['adaptive_penalty_rates'][confidence_tier]        
        concept_penalty = mismatch_analysis['concept_severity'] * max_penalty_rate * 0.6  # 60% weight
        topic_penalty = mismatch_analysis['topic_severity'] * max_penalty_rate * 0.3     # 30% weight  
        context_penalty = mismatch_analysis['context_severity'] * max_penalty_rate * 0.1 # 10% weight        
        total_penalty = concept_penalty + topic_penalty + context_penalty        
        if confidence_tier == 'very_high' and self.config['confidence_preservation']:
            total_penalty = min(total_penalty, 0.08)  # Cap at 8% penalty for very high confidence
            logger.debug(f"🛡️ Confidence preservation applied: penalty capped at {total_penalty:.3f}")
        elif confidence_tier == 'high' and self.config['confidence_preservation']:
            total_penalty = min(total_penalty, 0.12)  # Cap at 12% penalty for high confidence
            logger.debug(f"🛡️ Confidence preservation applied: penalty capped at {total_penalty:.3f}")        
        if total_penalty > 0:
            logger.debug(f"🔍 Smart penalty calculated:")
            logger.debug(f"   📊 Base score: {base_semantic_score:.3f}")
            logger.debug(f"   🎯 Confidence tier: {confidence_tier}")
            logger.debug(f"   📉 Concept penalty: {concept_penalty:.3f}")
            logger.debug(f"   📉 Topic penalty: {topic_penalty:.3f}")
            logger.debug(f"   📉 Context penalty: {context_penalty:.3f}")
            logger.debug(f"   📉 Total penalty: {total_penalty:.3f}")            
        return total_penalty, mismatch_analysis['issues']

    def calculate_context_boost(self, candidate, context_keywords):
        """🚀 NEW: Tính điểm thưởng cho candidates chứa context entities"""
        if not context_keywords:
            return 0.0
            
        question = candidate.get('question', '').lower()
        answer = candidate.get('answer', '').lower()
        candidate_text = f"{question} {answer}"
        
        boost = 0.0
        matched_keywords = 0
        
        for keyword in context_keywords:
            keyword_lower = keyword.lower()
            
            # Exact match bonus
            if keyword_lower in candidate_text:
                matched_keywords += 1
                boost += 0.15  # Base boost per keyword
                
                # Extra boost for person names in answer
                if len(keyword.split()) >= 2:  # Multi-word (likely person name)
                    if keyword_lower in answer:
                        boost += 0.1  # Extra bonus for names in answer
                        
        # Diminishing returns for multiple keywords
        if matched_keywords > 0:
            keyword_ratio = matched_keywords / len(context_keywords)
            boost = boost * (0.5 + 0.5 * keyword_ratio)  # Scale by match ratio
            
        return min(0.3, boost)    
    
    def stage1_semantic_scoring(self, candidates, query, context_keywords=None):
        """🚀 UPDATED: Stage 1 với context boosting"""
        if not candidates:
            return []        
        enhanced_candidates = []        
        for candidate in candidates:
            if not candidate:
                continue
            semantic_score = candidate.get('similarity', candidate.get('semantic_score', 0.0))            
            semantic_boost = self.calculate_semantic_boost(candidate, query)            
            concept_penalty, mismatch_issues = self._calculate_smart_penalty(candidate, query, semantic_score)
            
            # 🚀 NEW: Context boost
            context_boost = self.calculate_context_boost(candidate, context_keywords) if context_keywords else 0.0
            
            # Final stage 1 score: semantic + boost - penalty + context_boost
            stage1_score = semantic_score + semantic_boost - concept_penalty + context_boost
            stage1_score = max(0.0, min(1.0, stage1_score))  # Clamp to [0,1]
            
            # Create enhanced candidate
            enhanced_candidate = candidate.copy()
            enhanced_candidate.update({
                'semantic_score': semantic_score,
                'semantic_boost': semantic_boost,
                'smart_penalty': concept_penalty,
                'context_boost': context_boost,  # 🚀 NEW
                'mismatch_issues': mismatch_issues,
                'stage1_score': stage1_score,
                'ranking_method': 'stage1_with_context_boost'  # 🚀 UPDATED
            })
            
            enhanced_candidates.append(enhanced_candidate)
            
            if context_boost > 0:
                logger.debug(f"🎯 Context boost: semantic={semantic_score:.3f}, context_boost={context_boost:.3f}, final={stage1_score:.3f}")
        
        enhanced_candidates.sort(key=lambda x: x['stage1_score'], reverse=True)
        stage1_candidates = enhanced_candidates[:self.config['stage1_top_k']]        
        logger.info(f"🎯 Context-boosted Stage 1: {len(stage1_candidates)} candidates selected")        
        return stage1_candidates

    def stage2_cross_encoder_simulation(self, candidates, query):
        if not candidates:
            logger.info("🔄 Stage 2 skipped: No candidates available")
            return []        
        logger.info(f"🔄 Stage 2: Cross-encoder re-ranking {len(candidates)} candidates")        
        try:
            cross_encoder_scores = self._simulate_cross_encoder_semantic(query, candidates)
            final_candidates = []
            for i, candidate in enumerate(candidates):
                stage1_score = candidate.get('stage1_score', 0.0)
                stage2_score = cross_encoder_scores[i] if i < len(cross_encoder_scores) else 0.0                
                final_score = (
                    self.config['semantic_weight'] * stage1_score + 
                    self.config['cross_encoder_weight'] * stage2_score
                )                
                final_score = min(1.0, final_score)                
                final_candidate = candidate.copy()
                final_candidate.update({
                    'stage2_score': stage2_score,
                    'final_score': final_score,
                    'ranking_method': 'stage2_fixed_smart_semantic',
                    'fixed_semantic_reranking': True
                })                
                final_candidates.append(final_candidate)                
                logger.debug(f"🔄 Stage 2: s1={stage1_score:.3f}, s2={stage2_score:.3f}, final={final_score:.3f}")            
            final_candidates.sort(key=lambda x: x['final_score'], reverse=True)            
            logger.info(f"✅ Stage 2 Complete: Top-{self.config['stage2_top_n']} candidates selected")            
            return final_candidates[:self.config['stage2_top_n']]            
        except Exception as e:
            logger.error(f"❌ Stage 2 cross-encoder failed: {str(e)}, falling back to Stage 1 results")
            return candidates[:self.config['stage2_top_n']]

    def _simulate_cross_encoder_semantic(self, query, candidates):
        scores = []
        query_words = set(query.lower().split())
        for candidate in candidates:
            question = candidate.get('question', '').lower()
            answer = candidate.get('answer', '').lower()

            # Factor 1: Query-Question semantic overlap (increased weight)
            question_words = set(question.split())
            question_overlap = len(query_words.intersection(question_words)) / max(len(query_words), 1)

            # Factor 2: Answer completeness and relevance
            answer_words = set(answer.split())
            answer_coverage = len(query_words.intersection(answer_words)) / max(len(query_words), 1)
            
            # Factor 3: Question-Answer semantic coherence
            qa_shared_words = len(question_words.intersection(answer_words))
            qa_coherence = qa_shared_words / max(len(question_words.union(answer_words)), 1)

            # Factor 4: Answer length optimization (not too short, not too long)
            answer_length = len(answer)
            if 100 <= answer_length <= 800:
                length_score = 1.0
            elif answer_length < 100:
                length_score = answer_length / 100.0
            else:
                length_score = max(0.5, 1000.0 / answer_length)
            cross_encoder_score = (
                0.4 * question_overlap +      # Primary: query-question match
                0.3 * answer_coverage +       # Secondary: answer relevance  
                0.2 * qa_coherence +          # Coherence between Q&A
                0.1 * length_score            # Length optimization
            )

            cross_encoder_score = min(1.0, cross_encoder_score)
            scores.append(cross_encoder_score)

        return scores

    def apply_exact_name_priority(self, candidates, context_keywords):
        """🎯 CRITICAL: Ưu tiên tuyệt đối candidates có exact name match"""
        if not context_keywords:
            return candidates
            
        person_names = []
        for keyword in context_keywords:
            # Check if keyword is likely a person name (2+ words, proper case)
            if len(keyword.split()) >= 2 and keyword[0].isupper():
                person_names.append(keyword.lower())
        
        if not person_names:
            return candidates
            
        exact_matches = []
        partial_matches = []
        no_matches = []
        
        logger.info(f"🎯 Applying exact name priority for: {person_names}")
        
        for candidate in candidates:
            question = candidate.get('question', '').lower()
            answer = candidate.get('answer', '').lower()
            candidate_text = f"{question} {answer}"
            
            has_exact_match = False
            has_partial_match = False
            
            for person_name in person_names:
                # Exact name match
                if person_name in candidate_text:
                    has_exact_match = True
                    logger.debug(f"🎯 Exact match found: '{person_name}' in candidate")
                    break
                    
                # Partial match (last name only)
                name_parts = person_name.split()
                if len(name_parts) >= 2:
                    last_name = name_parts[-1]
                    if len(last_name) > 2 and last_name in candidate_text:
                        has_partial_match = True
                        logger.debug(f"🎯 Partial match found: '{last_name}' in candidate")
            
            # Categorize candidates
            if has_exact_match:
                # Boost exact matches significantly
                candidate = candidate.copy()
                original_score = candidate.get('final_score', candidate.get('stage1_score', candidate.get('semantic_score', 0)))
                candidate['name_match_boost'] = 0.4  # Huge boost
                candidate['boosted_score'] = min(1.0, original_score + 0.4)
                exact_matches.append(candidate)
            elif has_partial_match:
                candidate = candidate.copy()
                original_score = candidate.get('final_score', candidate.get('stage1_score', candidate.get('semantic_score', 0)))
                candidate['name_match_boost'] = 0.2  # Medium boost
                candidate['boosted_score'] = min(1.0, original_score + 0.2)
                partial_matches.append(candidate)
            else:
                candidate = candidate.copy()
                candidate['name_match_boost'] = 0.0
                candidate['boosted_score'] = candidate.get('final_score', candidate.get('stage1_score', candidate.get('semantic_score', 0)))
                no_matches.append(candidate)
        
        # Sort each group by their boosted scores
        exact_matches.sort(key=lambda x: x['boosted_score'], reverse=True)
        partial_matches.sort(key=lambda x: x['boosted_score'], reverse=True)
        no_matches.sort(key=lambda x: x['boosted_score'], reverse=True)
        
        # Combine: exact matches first, then partial, then others
        prioritized_candidates = exact_matches + partial_matches + no_matches
        
        logger.info(f"🎯 Name priority applied: {len(exact_matches)} exact, {len(partial_matches)} partial, {len(no_matches)} no match")
        
        return prioritized_candidates

    def rerank(self, candidates, query="", context_keywords=None):
        """🚀 UPDATED: Re-ranking với exact name priority"""
        if not candidates:
            return []        
        logger.info(f"🎯 Starting context-aware semantic re-ranking for {len(candidates)} candidates")
        if context_keywords:
            logger.info(f"🔍 Using context keywords: {context_keywords}")
        
        # STAGE 1: Context-aware semantic scoring  
        stage1_candidates = self.stage1_semantic_scoring(candidates, query, context_keywords)        
        if not stage1_candidates:
            logger.warning("⚠️ No candidates after context-aware Stage 1")
            return []
        
        # STAGE 2: Cross-encoder re-ranking
        stage2_candidates = self.stage2_cross_encoder_simulation(stage1_candidates, query)
        
        # 🎯 STAGE 3: Apply exact name priority (CRITICAL for person names)
        if context_keywords:
            stage2_candidates = self.apply_exact_name_priority(stage2_candidates, context_keywords)
            
            # Update final_score with boosted_score
            for candidate in stage2_candidates:
                candidate['final_score'] = candidate.get('boosted_score', candidate.get('final_score', 0))
        
        final_candidates = stage2_candidates[:self.config['stage2_top_n']]
        
        logger.info(f"✅ Context-aware + name-priority re-ranking complete: {len(final_candidates)} final candidates")        
        return final_candidates
    
class PureSemanticDecisionEngine:
    def __init__(self):
        self.semantic_confidence_thresholds = {
            'very_high': 0.75,   # Lowered from 0.8
            'high': 0.55,        # Lowered from 0.65 
            'medium': 0.35,      # Lowered from 0.45
            'low': 0.20,         # Lowered from 0.25
            'very_low': 0.1      # Kept original
        }
        
        self.decision_factors = {
            'preserve_high_confidence': True,     # Don't over-penalize good answers
            'mismatch_tolerance': {               # Tolerance levels by confidence
                'very_high': 0.8,  # High tolerance for high confidence
                'high': 0.6,       # Medium tolerance for good confidence
                'medium': 0.4,     # Low tolerance for medium confidence
                'low': 0.2         # Very low tolerance for poor confidence
            },
            'smart_clarification_threshold': 0.3  # When to use smart vs generic clarification
        }
        
        self.personal_info_keywords = [
            'lịch của tôi', 'lich cua toi', 'thời khóa biểu của tôi', 'tkb của tôi',
            'lịch giảng của tôi', 'lich giang cua toi', 'lịch dạy của tôi', 'lich day cua toi',
            'tôi giảng', 'toi giang', 'tôi dạy', 'toi day', 'môn của tôi', 'mon cua toi',
            'tôi là ai', 'toi la ai', 'thông tin của tôi', 'thong tin cua toi',
            'hôm nay', 'hom nay', 'ngày mai', 'ngay mai', 'tuần này', 'tuan nay'
        ]
        
        self.education_keywords = [
            'học', 'trường', 'sinh viên', 'giảng viên', 'dạy', 'bdu', 'đại học',
            'ngân hàng đề thi', 'báo cáo', 'kê khai', 'tạp chí', 'nghiên cứu'
        ]
        
        logger.info("✅ FIXED PureSemanticDecisionEngine initialized")
        logger.info("   🎯 FIXED decision making với smart confidence preservation")
        logger.info("   🛡️ High confidence answer protection")
        logger.info("   🧠 Adaptive mismatch tolerance")

    def categorize_semantic_confidence(self, final_score):
        if final_score >= self.semantic_confidence_thresholds['very_high']:
            return 'very_high'
        elif final_score >= self.semantic_confidence_thresholds['high']:
            return 'high'
        elif final_score >= self.semantic_confidence_thresholds['medium']:
            return 'medium'
        elif final_score >= self.semantic_confidence_thresholds['low']:
            return 'low'
        else:
            return 'very_low'

    def is_education_related(self, query):
        if not query:
            return False        
        query_lower = query.lower()        
        education_found = any(kw in query_lower for kw in self.education_keywords)
        
        if not education_found:
            education_patterns = [
                r'(?:bdu|đại học|trường)',
                r'(?:giảng viên|thầy|cô)',
                r'(?:sinh viên|học sinh)',
                r'(?:báo cáo|kê khai)',
                r'(?:đề thi|tạp chí)'
            ]
            
            for pattern in education_patterns:
                if re.search(pattern, query_lower):
                    education_found = True
                    break        
        logger.debug(f"🎓 Education check: '{query}' -> {education_found}")
        return education_found

    def needs_external_api(self, query, final_score=0.0):
        if not query:
            return False        
        query_lower = query.lower()        
        needs_api = any(keyword in query_lower for keyword in self.personal_info_keywords)        
        logger.debug(f"🌐 API check: '{query}' -> {needs_api}")
        return needs_api

    def _assess_mismatch_impact(self, best_candidate, original_score):
        if not best_candidate:
            return False, []        
        mismatch_issues = best_candidate.get('mismatch_issues', [])
        smart_penalty = best_candidate.get('smart_penalty', 0.0)        
        if not mismatch_issues:
            return False, []  # No mismatch issues
        
        confidence_tier = self.categorize_semantic_confidence(original_score)        
        tolerance = self.decision_factors['mismatch_tolerance'].get(confidence_tier, 0.5)        
        severity_score = smart_penalty / 0.3  # Normalize to 0-1 scale (max penalty is ~0.3)        
        should_impact_decision = severity_score > tolerance
        
        logger.debug(f"🧠 Mismatch impact assessment:")
        logger.debug(f"   📊 Original score: {original_score:.3f}")
        logger.debug(f"   🎯 Confidence tier: {confidence_tier}")
        logger.debug(f"   📉 Smart penalty: {smart_penalty:.3f}")
        logger.debug(f"   🔍 Severity score: {severity_score:.3f}")
        logger.debug(f"   🛡️ Tolerance: {tolerance:.3f}")
        logger.debug(f"   💡 Should impact decision: {should_impact_decision}")        
        return should_impact_decision, mismatch_issues

    def _create_smart_clarification_response(self, query, mismatch_issues, session_id):
        try:
            personal_address = "giảng viên"  # Default fallback
        except:
            personal_address = "giảng viên"
        
        if any('Work reporting vs Student' in issue for issue in mismatch_issues):
            return f"""Dạ {personal_address}, em thấy câu hỏi về "báo cáo khối lượng công việc" của giảng viên, nhưng thông tin em tìm được lại về khối lượng học tập của sinh viên.

{personal_address.title()} có thể làm rõ hơn:
- {personal_address.title()} cần thông tin về báo cáo khối lượng giờ giảng của giảng viên?
- Hay về thời gian nộp báo cáo nhiệm vụ giảng dạy?
- Hoặc về quy trình báo cáo công tác của khoa/bộ môn?

Em sẽ tìm thông tin chính xác hơn khi {personal_address} làm rõ! 🎯"""

        elif any('Bank account vs Login' in issue for issue in mismatch_issues):
            return f"""Dạ {personal_address}, em hiểu {personal_address} hỏi về "số tài khoản để đóng học phí", nhưng thông tin em tìm được lại về tài khoản đăng nhập hệ thống.

{personal_address.title()} có thể xác nhận:
- {personal_address.title()} cần số tài khoản ngân hàng để chuyển tiền học phí?
- Hay cần thông tin về cách đóng học phí online?
- Hoặc về thủ tục thanh toán học phí tại trường?

Em sẽ tìm đúng thông tin {personal_address} cần! 💳"""

        elif any('Education fees vs Competition' in issue for issue in mismatch_issues):
            return f"""Dạ {personal_address}, em tìm thấy thông tin nhưng có vẻ không đúng chủ đề {personal_address} quan tâm (thông tin về cuộc thi thay vì học phí).

{personal_address.title()} có thể nói rõ hơn về:
- Loại học phí cụ thể {personal_address} cần biết?
- Phòng ban hoặc thủ tục liên quan?
- Đối tượng áp dụng?

Em sẽ tìm thông tin chính xác hơn! 🔍"""
        
        else:
            return f"""Dạ {personal_address}, để em có thể hỗ trợ chính xác nhất, {personal_address} có thể làm rõ hơn về vấn đề cần hỗ trợ không ạ?

Em sẽ tìm thông tin phù hợp nhất cho {personal_address}! 🎯"""

    def make_decision(self, query, candidates_list, session_memory=None, jwt_token=None, document_text=None):
        if document_text and document_text.strip():
            logger.info("📄 DOCUMENT CONTEXT PRIORITY: Document text provided")
            return 'use_document_context', {
                'instruction': 'answer_from_document',
                'query': query,
                'document_text': document_text,
                'confidence': 0.95,
                'message': 'Answering based on document content',
                'semantic_decision': True
            }, True
        
        is_education = self.is_education_related(query)
        if not is_education and session_memory and len(session_memory) == 0:
            logger.info("📚 SCOPE: Rejecting non-education query")
            return 'reject_non_education', None, False
        
        if self.needs_external_api(query, 0.0):
            if jwt_token and jwt_token.strip():
                return 'use_external_api', {
                    'instruction': 'external_api_lecturer',
                    'query': query,
                    'jwt_token': jwt_token,
                    'fallback_qa_answer': candidates_list[0].get('answer', '') if candidates_list else '',
                    'confidence': candidates_list[0].get('final_score', 0) if candidates_list else 0,
                    'message': 'Using external API for personal information',
                    'semantic_decision': True
                }, True
            else:
                return 'require_authentication', {
                    'instruction': 'authentication_required',
                    'query': query,
                    'confidence': candidates_list[0].get('final_score', 0) if candidates_list else 0,
                    'message': 'Personal information requires authentication',
                    'semantic_decision': True
                }, True
        
        if not candidates_list:
            logger.warning("⚠️ No candidates provided for decision making")
            return 'say_dont_know', {
                'instruction': 'dont_know_lecturer',
                'confidence': 0.0,
                'message': 'No candidates available',
                'semantic_decision': True
            }, True
        
        best_candidate = None
        best_suitability = -1
        selection_info = []
        
        if len(candidates_list) > 1:
            logger.info(f"🔬 SMART SELECTION: Analyzing {len(candidates_list)} candidates")
            
            for i, candidate in enumerate(candidates_list[:5]):
                score = candidate.get('final_score', 0)
                mismatch_count = len(candidate.get('mismatch_issues', []))
                semantic_score = candidate.get('semantic_score', 0)
                
                position_bonus = (5 - i) * 0.01
                suitability = semantic_score - (mismatch_count * 0.1) + position_bonus
                
                selection_info.append({
                    'position': i + 1,
                    'score': score,
                    'semantic_score': semantic_score,
                    'mismatch_count': mismatch_count,
                    'suitability': suitability
                })
                
                if suitability > best_suitability:
                    best_suitability = suitability
                    best_candidate = candidate
                    
                logger.debug(f"🔬 Candidate #{i+1}: score={score:.3f}, semantic={semantic_score:.3f}, mismatches={mismatch_count}, suitability={suitability:.3f}")
            
            if best_candidate:
                original_pos = None
                for info in selection_info:
                    if info['suitability'] == best_suitability:
                        original_pos = info['position']
                        break
                logger.info(f"🔬 SMART SELECTION: Chose candidate #{original_pos} (suitability: {best_suitability:.3f})")
        else:
            best_candidate = candidates_list[0]
            logger.info("🔬 SINGLE CANDIDATE: Using the only available candidate")
        
        final_score = best_candidate.get('final_score', 0.0)
        original_score = best_candidate.get('semantic_score', final_score)        
        should_impact, mismatch_issues = self._assess_mismatch_impact(best_candidate, original_score)        
        confidence_level = self.categorize_semantic_confidence(final_score)
        
        logger.info(f"🎯 ENHANCED Semantic Decision Analysis:")
        logger.info(f"   📊 Selected candidate position: {original_pos if 'original_pos' in locals() else 1}")
        logger.info(f"   📊 Original semantic score: {original_score:.3f}")
        logger.info(f"   📊 Final score: {final_score:.3f}")
        logger.info(f"   🎯 Confidence level: {confidence_level}")
        logger.info(f"   🧠 Mismatch should impact: {should_impact}")
        logger.info(f"   🔍 Mismatch issues: {len(mismatch_issues)}")
                
        if confidence_level == 'very_high':
            decision = 'use_db_direct'
            context = {
                'instruction': 'direct_answer_lecturer',
                'db_answer': best_candidate.get('answer', ''),
                'confidence': final_score,
                'message': f'Very high confidence - direct answer (preserved)',
                'semantic_decision': True,
                'confidence_level': confidence_level,
                'mismatch_issues': mismatch_issues,
                'confidence_preserved': True,
                'selected_position': original_pos if 'original_pos' in locals() else 1
            }
            logger.info(f"✅ ENHANCED Decision: {decision} (very high confidence preserved)")            
        elif confidence_level == 'high':
            if should_impact and mismatch_issues:
                decision = 'ask_clarification'
                context = {
                    'instruction': 'smart_clarification_needed',
                    'db_answer': best_candidate.get('answer', ''),
                    'confidence': final_score,
                    'message': f'High confidence but serious mismatch → smart clarification',
                    'semantic_decision': True,
                    'confidence_level': confidence_level,
                    'mismatch_issues': mismatch_issues,
                    'smart_clarification': True,
                    'selected_position': original_pos if 'original_pos' in locals() else 1
                }
                logger.info(f"🤔 ENHANCED Decision: {decision} (high confidence + serious mismatch)")
            else:
                decision = 'use_db_direct'
                context = {
                    'instruction': 'direct_answer_lecturer',
                    'db_answer': best_candidate.get('answer', ''),
                    'confidence': final_score,
                    'message': f'High confidence - direct answer',
                    'semantic_decision': True,
                    'confidence_level': confidence_level,
                    'mismatch_issues': mismatch_issues,
                    'selected_position': original_pos if 'original_pos' in locals() else 1
                }
                logger.info(f"✅ ENHANCED Decision: {decision} (high confidence)")                
        elif confidence_level == 'medium':
            if should_impact and mismatch_issues:
                decision = 'ask_clarification'
                context = {
                    'instruction': 'smart_clarification_needed',
                    'db_answer': best_candidate.get('answer', ''),
                    'confidence': final_score,
                    'message': f'Medium confidence + mismatch → smart clarification',
                    'semantic_decision': True,
                    'confidence_level': confidence_level,
                    'mismatch_issues': mismatch_issues,
                    'smart_clarification': True,
                    'selected_position': original_pos if 'original_pos' in locals() else 1
                }
                logger.info(f"🤔 ENHANCED Decision: {decision} (medium confidence + mismatch)")
            else:
                decision = 'enhance_db_answer'
                context = {
                    'instruction': 'enhance_answer_lecturer',
                    'db_answer': best_candidate.get('answer', ''),
                    'confidence': final_score,
                    'message': 'Medium confidence - enhanced answer',
                    'semantic_decision': True,
                    'confidence_level': confidence_level,
                    'selected_position': original_pos if 'original_pos' in locals() else 1
                }
                logger.info(f"✅ ENHANCED Decision: {decision} (medium confidence)")                
        elif confidence_level == 'low':
            smart_clarification = bool(mismatch_issues)
            decision = 'ask_clarification'
            context = {
                'instruction': 'smart_clarification_needed' if smart_clarification else 'clarification_needed',
                'db_answer': best_candidate.get('answer', ''),
                'confidence': final_score,
                'message': f'Low confidence - need clarification',
                'semantic_decision': True,
                'confidence_level': confidence_level,
                'mismatch_issues': mismatch_issues,
                'smart_clarification': smart_clarification,
                'selected_position': original_pos if 'original_pos' in locals() else 1
            }
            logger.info(f"🤔 ENHANCED Decision: {decision} (low confidence)")            
        else:  # very_low
            decision = 'say_dont_know'
            context = {
                'instruction': 'dont_know_lecturer',
                'confidence': final_score,
                'message': f'Very low confidence - no relevant information',
                'semantic_decision': True,
                'confidence_level': confidence_level,
                'mismatch_issues': mismatch_issues,
                'selected_position': original_pos if 'original_pos' in locals() else 1
            }
            logger.info(f"❌ ENHANCED Decision: {decision} (very low confidence)")        
        return decision, context, True
class PureSemanticChatbotAI:
    def __init__(self, shared_response_generator):
        from .phobert_service import retriever_service        
        self.sbert_retriever = ChatbotAI(shared_response_generator=shared_response_generator)
        self.retriever_service = retriever_service
        self.response_generator = shared_response_generator
        self.decision_engine = PureSemanticDecisionEngine()        
        self.semantic_reranker = SemanticReRanker(retriever_service=self.retriever_service)        
        self.conversation_memory = {}        
        logger.info("🎯 ENHANCED PureSemanticChatbotAI initialized")
        logger.info("   🛡️ Smart penalty system enabled")
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
                return word1 in word2 or word2 in word1
        
        return False
    
    def _smart_entity_fallback_search(self, query: str, session_id: str = None):
        """🆕 NEW: Smart fallback khi context không match"""
        try:
            query_lower = query.lower()
            
            # Extract potential entity names from query
            potential_names = self._extract_names_from_query(query)
            
            if not potential_names:
                return []
            
            logger.info(f"🔍 Smart entity fallback: searching for {potential_names}")
            
            # Search for each potential name in knowledge base
            best_candidates = []
            
            for name in potential_names:
                # Try different query variations
                search_queries = [
                    f"{name} là ai",
                    f"ai là {name}",
                    f"thông tin {name}",
                    f"chức vụ {name}",
                    name  # Just the name itself
                ]
                
                for search_query in search_queries:
                    candidates = self.sbert_retriever.semantic_search_top_k(
                        search_query, top_k=5
                    )
                    
                    if candidates and candidates[0].get('semantic_score', 0) > 0.5:  # Lowered from 0.6
                        # Add fallback context info
                        candidates[0]['fallback_search_query'] = search_query
                        candidates[0]['extracted_name'] = name
                        candidates[0]['search_method'] = 'smart_entity_fallback'
                        best_candidates.append(candidates[0])
                        logger.info(f"Found entity info via fallback: {name} -> score={candidates[0].get('semantic_score', 0):.3f}")
                        break  # Found good match, no need to try other variations
            
            # Sort by semantic score and return best ones
            best_candidates.sort(key=lambda x: x.get('semantic_score', 0), reverse=True)
            return best_candidates[:3]  # Top 3
            
        except Exception as e:
            logger.error(f"Error in smart entity fallback search: {str(e)}")
            return []
    
    def _extract_names_from_query(self, query: str) -> list:
        """🆕 NEW: Extract potential person names from query"""
        potential_names = []
        
        # Pattern 1: "vậy X là ai", "X là ai", "ai là X" 
        patterns = [
            r'(?:vậy|thế)\s+([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+(?:\s+[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+)*)\s+là\s+ai',
            r'([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+(?:\s+[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+)*)\s+là\s+ai',
            r'ai\s+là\s+([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+(?:\s+[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+)*)',
            r'(?:ông|bà|thầy|cô|anh|chị)\s+([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+(?:\s+[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+)*)'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, query, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    name = match[0] if match[0] else (match[1] if len(match) > 1 else "")
                else:
                    name = match
                
                if name and len(name.strip()) > 2:
                    clean_name = name.strip()
                    # Validate it looks like a Vietnamese name
                    if self._is_likely_vietnamese_name(clean_name):
                        potential_names.append(clean_name)
        
        # Also extract capitalized words that could be names
        words = query.split()
        current_name = []
        for word in words:
            if word and word[0].isupper() and len(word) > 2:
                # Check if it's not a common word
                if word.lower() not in ['Dạ', 'Vậy', 'Thế', 'Còn', 'Và', 'Hay', 'Nhưng']:
                    current_name.append(word)
            else:
                if len(current_name) >= 2:  # At least 2 words for a name
                    full_name = ' '.join(current_name)
                    if self._is_likely_vietnamese_name(full_name):
                        potential_names.append(full_name)
                current_name = []
        
        # Check remaining name at end
        if len(current_name) >= 2:
            full_name = ' '.join(current_name)
            if self._is_likely_vietnamese_name(full_name):
                potential_names.append(full_name)
        
        # Remove duplicates and return
        return list(set(potential_names))
    
    def _is_likely_vietnamese_name(self, name: str) -> bool:
        """Check if text looks like a Vietnamese person name"""
        if not name or len(name.split()) < 1:
            return False
        
        words = name.lower().split()
        
        # Common Vietnamese surnames
        common_surnames = {
            'nguyễn', 'trần', 'lê', 'phạm', 'hoàng', 'huỳnh', 'phan', 'vũ', 'võ', 'đặng', 
            'bùi', 'đỗ', 'hồ', 'ngô', 'dương', 'lý', 'cao', 'đậu', 'lưu', 'tô',
            'nguyen', 'tran', 'le', 'pham', 'hoang', 'huynh', 'phan', 'vu', 'vo', 'dang',
            'bui', 'do', 'ho', 'ngo', 'duong', 'ly', 'cao', 'dau', 'luu', 'to'
        }
        
        # If first word is common surname, likely a name
        if words[0] in common_surnames:
            return True
        
        # Check for Vietnamese name characteristics
        vietnamese_chars = 'ăâêôơưàáạảãầấậẩẫằắặẳẵèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹđ'
        vietnamese_char_count = sum(1 for char in name.lower() if char in vietnamese_chars)
        
        # Must have reasonable length and structure
        total_chars = len(''.join(words))
        if len(words) >= 2 and 4 <= total_chars <= 20:
            # If has Vietnamese chars, likely a name
            if vietnamese_char_count >= 1:
                return True
            # Even without accents, if structure looks right, could be name
            elif len(words) <= 4 and all(len(w) >= 2 for w in words):
                return True
        
        return False
    
    def _normalize_for_matching(self, text):
        """🚀 IMPROVED: Better normalization for Vietnamese text"""
        if not text:
            return ""
        
        # Convert to lowercase first
        normalized = text.lower().strip()
        
        # Remove punctuation but keep Vietnamese characters and spaces
        normalized = re.sub(r'[^\w\sàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', ' ', normalized)
        
        # Remove particles but keep meaningful words  
        particles = ['dạ', 'ạ', 'ơi', 'nhé', 'vậy', 'thì', 'là', 'của', 'và', 'với', 'ai', 'gì', 'nào']
        words = normalized.split()
        filtered_words = [w for w in words if w not in particles and len(w) > 1]
        
        normalized = ' '.join(filtered_words)
        
        # Remove extra spaces
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _create_response_from_memory(self, query: str, entity_name: str, last_interaction: dict, session_id: str):
        """
        Tạo câu trả lời trực tiếp từ bộ nhớ (NÂNG CẤP)
        """
        personal_address = self._get_personal_address(session_id)
        last_bot_response = last_interaction.get('response', '')
        last_qa_info = last_interaction.get('sources', [{}])[0] if last_interaction.get('sources') else {}
        original_question = last_qa_info.get('question', '')
        original_answer = last_qa_info.get('answer', last_bot_response)

        # Cố gắng tìm chức vụ đã được xác định ở lượt trước
        position = "vai trò đã được đề cập" # Fallback
        last_entities = last_interaction.get('semantic_info', {}).get('extracted_entities', {})
        if 'position' in last_entities and last_entities['position']:
            position = last_entities['position'][0]

        # Xây dựng câu trả lời dựa trên thông tin đã có
        response_text = (
            f"Dạ {personal_address}, khi đề cập đến \"{entity_name}\", "
            f"em đang hiểu là {personal_address} hỏi về thông tin từ lượt trao đổi trước. "
            f"Theo đó, {entity_name} giữ chức vụ là {position} ạ. "
            f"{personal_address.title()} có cần em cung cấp thêm chi tiết nào từ thông tin gốc không ạ?"
        )

        final_score = 0.98

        return {
            'response': response_text,
            'confidence': final_score,
            'method': 'conversation_memory_direct_answer_v2',
            'decision_type': 'use_memory_direct',
            'semantic_info': {
                'final_score': final_score,
                'confidence_level': 'very_high',
                'semantic_decision': True,
                'selected_position': 0,
                'original_context': {
                    'question': original_question,
                    'answer': original_answer
                }
            },
            'context_info': {
                'search_method': 'skipped_retrieval',
                'context_used': True,
                'context_keywords': [entity_name],
            },
            'sources': last_interaction.get('sources', []),
            'processing_time': 0.1,
            'context_aware_rag': True,
            'architecture': 'context_aware_semantic_rag',
        }
    
    def _ensure_context_functionality(self):
        """🆕 CRITICAL: Đảm bảo context functionality hoạt động"""
        try:
            # Kiểm tra entity extractor
            if not hasattr(self.response_generator, 'memory'):
                logger.error("❌ CRITICAL: response_generator.memory not found")
                return False
                
            if not hasattr(self.response_generator.memory, 'entity_extractor'):
                logger.error("❌ CRITICAL: entity_extractor not found in memory")
                return False
                
            if not hasattr(self.response_generator.memory, 'get_context_for_query'):
                logger.error("❌ CRITICAL: get_context_for_query method not found")
                return False
                
            # Test basic functionality
            test_entities = self.response_generator.memory.entity_extractor.extract_entities(
                "test text", "test query"
            )
            
            logger.info("✅ Context functionality check passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Context functionality check failed: {str(e)}")
            return False
    
    @property
    def model(self):
        return self.sbert_retriever.model    
    @property
    def index(self):
        return self.sbert_retriever.index    
    @property
    def knowledge_data(self):
        return self.sbert_retriever.knowledge_data    
    def get_system_status(self):
        gemini_status = self.response_generator.get_system_status()
        drive_status = drive_service.get_system_status()
        external_api_status = external_api_service.get_system_status()
        retriever_status = self.retriever_service.get_system_status()
        
        # 🆕 THÊM: Context-aware features status
        context_features_status = {
            'entity_extractor_available': hasattr(self.response_generator, 'memory') and hasattr(self.response_generator.memory, 'entity_extractor'),
            'dual_search_available': hasattr(self.sbert_retriever, 'dual_semantic_search'),
            'context_memory_available': hasattr(self.response_generator, 'memory'),
            'context_keywords_supported': True,
            'entity_relationships_supported': True
        }
        
        return {
            'sbert_model': bool(self.sbert_retriever.model),
            'faiss_index': bool(self.sbert_retriever.index),
            'retriever_service_available': self.retriever_service.is_available(),
            'fine_tuned_model_available': retriever_status.get('fine_tuned_model_loaded', False),
            'gemini_available': gemini_status.get('gemini_api_available', False),
            'knowledge_entries': len(self.sbert_retriever.knowledge_data),
            'mode': 'context_aware_semantic_rag',  # 🆕 UPDATED
            'architecture': 'context_aware_semantic_rag',
            'semantic_reranking': {
                'enabled': True,
                'smart_penalty_system': True,
                'confidence_preservation': True,
                'adaptive_penalty_rates': True,
                'stage1_candidates': self.semantic_reranker.config['stage1_top_k'],
                'stage2_final': self.semantic_reranker.config['stage2_top_n']
            },
            'decision_engine': {
                'type': 'context_aware_semantic',  # 🆕 UPDATED
                'confidence_thresholds': self.decision_engine.semantic_confidence_thresholds,
                'smart_mismatch_handling': True,
                'high_confidence_preservation': True,
                'adaptive_tolerance': True
            },
            # 🆕 THÊM: Context-aware features
            'context_aware_features': [
                'entity_extraction_from_qa',
                'entity_relationship_building', 
                'context_keyword_generation',
                'dual_semantic_search',
                'context_enhanced_queries',
                'smart_fallback_mechanism',
                'context_quality_analysis',
                'conversation_continuity',
                'multi_turn_understanding',
                'entity_memory_decay'
            ],
            'context_features_status': context_features_status,
            'enhanced_semantic_features': [
                'smart_penalty_system',
                'confidence_preservation', 
                'adaptive_mismatch_tolerance',
                'tiered_decision_logic',
                'targeted_clarification',
                'high_quality_answer_protection',
                'context_aware_retrieval',  # 🆕 NEW
                'entity_based_context',     # 🆕 NEW
                'conversation_memory'       # 🆕 NEW
            ],
            'retriever_service_status': retriever_status,
            'external_api_status': external_api_status,
            'gemini_status': gemini_status
        }

    def _is_social_query(self, query: str) -> bool:
        """Kiểm tra xem câu hỏi có phải là chào hỏi xã giao không"""
        social_patterns = [
            r'^(xin )?chào( bạn| mọi người| ad| admin)?\.?$',
            r'^hi( there| guy)?\.?$',
            r'^hello\.?$',
            r'^alo( alo)?\.?$',
            r'^có ai (ở đây|không).*\??$',
            r'^bạn là ai\??$',
            r'^giới thiệu về bạn\??$',
            r'^test\.?$'
        ]
        query_lower = query.strip().lower()
        return any(re.match(p, query_lower) for p in social_patterns)
    
    def process_query(self, query, session_id=None, jwt_token=None, document_text=None):
        start_time = time.time()
        
        logger.info(f"🎯 IMPROVED Context-Aware Semantic RAG Processing: '{query}' (session: {session_id})")
        
        try:
            # STEP 1: VALIDATE INPUT
            query = self._clean_query(query)
            if not query:
                return self._get_empty_query_response()

            # 🔥 NEW: STEP 1.1 CHECK SOCIAL QUERY (CHIT-CHAT)
            # Nếu là câu xã giao, trả lời ngay, không cần tìm kiếm tài liệu
            if hasattr(self, '_is_social_query') and self._is_social_query(query):
                logger.info(f"👋 Detected social query: '{query}'")
                response_data = self.response_generator.generate_response(
                    query=query,
                    context={'mode': 'chat_only'}, # Chế độ chỉ chat
                    session_id=session_id
                )
                return {
                    'response': response_data['response'],
                    'confidence': 1.0,
                    'method': 'social_chat',
                    'processing_time': time.time() - start_time,
                    'is_education': False
                }
            
            # STEP 2: GET SESSION MEMORY
            session_memory = self.get_conversation_context(session_id) if session_id else []
            logger.info(f"🧠 Session memory: {len(session_memory)} interactions")
            
            # STEP 2.1: CHECK DIRECT ENTITY QUERY
            is_direct_hit, entity_name, last_interaction = self._check_direct_entity_query(query, session_id)
            if is_direct_hit:
                response_data = self._create_response_from_memory(query, entity_name, last_interaction, session_id)
                if session_id:
                     self._update_semantic_memory(
                        session_id, query, response_data['confidence'], response_data['decision_type'], 
                        True, response_data, None
                    )
                return response_data
            
            # STEP 3: DOCUMENT CONTEXT CHECK
            if document_text:
                doc_length = len(document_text.strip())
                logger.info(f"📄 Document context: {doc_length} characters")
            
            # STEP 4: IMPROVED CONTEXT-AWARE RETRIEVAL
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
                    query, context_keywords, top_k=self.semantic_reranker.config['stage1_top_k']
                )
                logger.info(f"🔄 Dual search result: method={search_method}, candidates={len(candidates)}")
                
            elif is_entity_query:
                logger.info("🔍 Entity query detected - trying smart fallback search first")
                fallback_candidates = self._smart_entity_fallback_search(query, session_id)
                
                if fallback_candidates and fallback_candidates[0].get('semantic_score', 0) > 0.6:
                    logger.info("Smart entity fallback found good results, using them")
                    candidates = fallback_candidates
                    search_method = 'smart_entity_fallback'
                else:
                    logger.info("Smart fallback insufficient - using normal search")
                    candidates = self.sbert_retriever.semantic_search_top_k(
                        query, top_k=self.semantic_reranker.config['stage1_top_k']
                    )
                    search_method = 'normal'
            else:
                logger.info("🔍 Using NORMAL search (non-entity query)")
                candidates = self.sbert_retriever.semantic_search_top_k(
                    query, top_k=self.semantic_reranker.config['stage1_top_k']
                )
                search_method = 'normal'
                
            logger.info(f"🔍 Search completed: method={search_method}, candidates={len(candidates)}")
            
            # STEP 5: CONTEXT-AWARE SEMANTIC RE-RANKING
            context_keywords = context_info.get('context_keywords', []) if should_try_context else []
            reranked_candidates = self.semantic_reranker.rerank(candidates, query, context_keywords)
            
            # 🔥 NEW: LOW CONFIDENCE CHECK & FALLBACK (Kiểm tra điểm số thấp)
            top_score = reranked_candidates[0].get('final_score', 0) if reranked_candidates else 0
            
            if not reranked_candidates or top_score < 0.45:
                logger.warning(f"⚠️ Low confidence ({top_score:.3f}) -> Switching to General Knowledge Mode")
                
                # Gọi LLM với chế độ kiến thức chung (không dùng RAG context)
                response_data = self.response_generator.generate_response(
                    query=query,
                    context={'mode': 'general_knowledge'}, # Chế độ kiến thức chung
                    session_id=session_id
                )
                
                return {
                    'response': response_data['response'],
                    'confidence': 0.5, # Tự tin trung bình
                    'method': 'general_knowledge_fallback',
                    'processing_time': time.time() - start_time,
                    'is_education': False,
                    'original_score': top_score
                }

            # STEP 5.1: CONTEXT QUALITY ANALYSIS (Nếu điểm cao thì tiếp tục logic RAG)
            context_quality_score = self._analyze_context_quality(
                query, reranked_candidates[0], context_info, search_method
            )
            
            logger.info(f"📊 Top candidate analysis:")
            best_candidate = reranked_candidates[0]
            final_score = best_candidate.get('final_score', 0)
            logger.info(f"   Score: {final_score:.3f} | Context quality: {context_quality_score:.3f}")
            logger.info(f"   Method: {search_method}")
            
            # STEP 6: ADD CONTEXT INFO TO CANDIDATE
            best_candidate['context_method'] = search_method
            best_candidate['context_quality'] = context_quality_score
            best_candidate['context_keywords_used'] = context_info.get('context_keywords', [])
            
            # STEP 7: DECISION MAKING
            decision_type, context, should_respond = self.decision_engine.make_decision(
                query, reranked_candidates, session_memory, jwt_token, document_text
            )
            
            # STEP 8: EXECUTE DECISION
            if not should_respond:
                response_text = self._get_out_of_scope_response(session_id)
                method = 'rejected_non_education'
            else:
                if context:
                    context['context_method'] = search_method
                    context['context_quality'] = context_quality_score
                    context['context_keywords_used'] = context_info.get('context_keywords', [])
                
                response_text = self._execute_fixed_semantic_decision(
                    decision_type, query, context, session_id
                )
                method = f"{decision_type}_{search_method}"
            
            # STEP 9: UPDATE MEMORY
            if session_id and should_respond:
                self._update_semantic_memory(
                    session_id, query, final_score, decision_type, 
                    should_respond, context, document_text
                )
                
                if hasattr(self.response_generator, 'memory'):
                    self.response_generator.memory.add_interaction(
                        session_id, query, response_text, 
                        intent_info={'intent': decision_type}, 
                        entities={}
                    )
            
            processing_time = time.time() - start_time
            
            return {
                'response': response_text,
                'confidence': final_score,
                'method': method,
                'decision_type': decision_type,
                'semantic_info': {
                    'final_score': final_score,
                    'original_semantic_score': best_candidate.get('semantic_score', final_score),
                    'smart_penalty': best_candidate.get('smart_penalty', 0),
                    'mismatch_issues': best_candidate.get('mismatch_issues', []),
                    'confidence_level': context.get('confidence_level', 'unknown') if context else 'unknown',
                    'confidence_preserved': context.get('confidence_preserved', False) if context else False,
                    'selected_position': context.get('selected_position', 1) if context else 1,
                    'semantic_decision': True
                },
                'context_info': {
                    'search_method': search_method,
                    'context_used': should_try_context,
                    'context_keywords': context_info.get('context_keywords', []),
                    'context_strength': context_info.get('context_strength', 0),
                    'context_quality': context_quality_score,
                    'related_entities': context_info.get('related_entities', []),
                    'context_threshold_met': should_try_context
                },
                'sources': self._format_sources(reranked_candidates[:2]),
                'processing_time': processing_time,
                'is_education': context is not None,
                'context_aware_rag': True,
                'reference_links': best_candidate.get('reference_links', []),
                'external_api_used': decision_type == 'use_external_api',
                'semantic_reranking_used': best_candidate.get('fixed_semantic_reranking', False),
                'session_memory_used': bool(session_memory),
                'document_context_used': bool(document_text),
                'document_context_priority': decision_type == 'use_document_context',
                'architecture': 'improved_context_aware_semantic_rag',
                'enhanced_features': [
                    'smart_penalty', 'confidence_preservation', 'adaptive_tolerance', 
                    'top5_selection', 'smart_candidate_selection',
                    'improved_context_detection', 'dual_search_with_fallback', 'selective_entity_memory',
                    'context_quality_analysis', 'smart_context_threshold', 'chat_fallback'
                ]
            }
            
        except Exception as e:
            logger.error(f"⛔ Context-aware semantic processing error: {str(e)}")
            return {
                'response': self._get_error_response(session_id),
                'confidence': 0.0,
                'method': 'error_fallback',
                'processing_time': time.time() - start_time,
                'error': str(e),
                'context_aware_rag': True,
                'graceful_degradation_used': True
            }

    def _analyze_context_quality(self, query, best_candidate, context_info, search_method):
        """🆕 THÊM MỚI: Phân tích chất lượng context được sử dụng"""
        try:
            if search_method == 'normal' or not context_info.get('should_use_context', False):
                return 0.0
            
            context_keywords = context_info.get('context_keywords', [])
            if not context_keywords:
                return 0.0
            
            # Kiểm tra context keywords có xuất hiện trong candidate không
            question = best_candidate.get('question', '').lower()
            answer = best_candidate.get('answer', '').lower()
            candidate_text = f"{question} {answer}"
            
            keywords_found = 0
            for keyword in context_keywords:
                if keyword.lower() in candidate_text:
                    keywords_found += 1
            
            # Tính quality score
            keyword_ratio = keywords_found / len(context_keywords) if context_keywords else 0
            semantic_score = best_candidate.get('semantic_score', 0)
            context_strength = context_info.get('context_strength', 0)
            
            quality_score = (
                0.4 * keyword_ratio +           # 40% từ keyword match
                0.4 * semantic_score +          # 40% từ semantic score  
                0.2 * min(1.0, context_strength / 3.0)  # 20% từ context strength
            )
            
            logger.debug(f"📊 Context quality: keywords_found={keywords_found}/{len(context_keywords)}, "
                        f"semantic={semantic_score:.3f}, strength={context_strength}, quality={quality_score:.3f}")
            
            return min(1.0, quality_score)
            
        except Exception as e:
            logger.error(f"❌ Error analyzing context quality: {str(e)}")
            return 0.0
    
    def _execute_fixed_semantic_decision(self, decision_type, query, context, session_id):
        logger.info(f"🎯 Executing FIXED semantic decision: {decision_type}")
        
        gemini_available = self._check_gemini_availability()
        
        # KIỂM TRA TỔNG HỢP: API không có sẵn HOẶC tất cả key đều đang quá tải
        if not gemini_available:
            # Thêm log để bạn biết chính xác lý do fallback
            if self.response_generator.key_manager.keys and all(
                status.get('is_rate_limited', False) 
                for status in self.response_generator.key_manager.key_status.values()
            ):
                logger.warning("⚠️ All Gemini keys are rate-limited. Using FIXED graceful degradation (raw answer).")
            else:
                logger.warning("⚠️ Gemini API not available (no keys configured). Using FIXED graceful degradation (raw answer).")
            
            # Cả hai trường hợp đều dẫn đến fallback trả lời thô
            return self._create_fixed_semantic_fallback_response(decision_type, query, context, session_id)        
        
        # Nếu kiểm tra qua, nghĩa là API đang sẵn sàng, tiếp tục xử lý bình thường
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
                logger.warning(f"⚠️ Unknown decision type: {decision_type}")
                return self._create_fixed_semantic_fallback_response(decision_type, query, context, session_id)                
        except Exception as e:
            logger.error(f"❌ Error executing FIXED semantic decision: {str(e)}")
            return self._create_fixed_semantic_fallback_response(decision_type, query, context, session_id)
        
    def _create_fixed_semantic_fallback_response(self, decision_type, query, context, session_id):
        personal_address = self._get_personal_address(session_id)        
        raw_answer = context.get('db_answer', '') if context else ''
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
                clean_answer = re.sub(r'^(dạ\s+(thầy|cô|giảng viên)[^,]*,?\s*)', '', clean_answer, flags=re.IGNORECASE)
                clean_answer = re.sub(r'^(xin chào|chào)[^.!?]*[.!?]\s*', '', clean_answer, flags=re.IGNORECASE)                
                if clean_answer and not clean_answer[0].isupper():
                    clean_answer = clean_answer[0].upper() + clean_answer[1:]                
                personalized_response = f"Dạ {personal_address}, {clean_answer}"                
                if not personalized_response.strip().endswith(('?', '!', '.')):
                    personalized_response += '.'                
                if confidence_preserved:
                    personalized_response += f' {personal_address.title()} có cần em hỗ trợ thêm gì không ạ? 🎯'
                else:
                    personalized_response += f' {personal_address.title()} cần em làm rõ thêm gì không ạ? 🎯'                
                logger.info(f"🛡️ FIXED SEMANTIC FALLBACK: Formatted raw answer for {personal_address}")
                return personalized_response
            else:
                return f"Dạ {personal_address}, em chưa có thông tin về vấn đề này. {personal_address.title()} có thể liên hệ phòng ban liên quan để được hỗ trợ chi tiết ạ. 🎯"
        
        return f"Dạ {personal_address}, em sẵn sàng hỗ trợ {personal_address} về các vấn đề liên quan đến BDU. {personal_address.title()} có thể chia sẻ cụ thể hơn về điều cần hỗ trợ không ạ? 🎯"

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

    def _update_semantic_memory(self, session_id, query, final_score, decision_type, was_education, context, document_text):
        if session_id not in self.conversation_memory:
            self.conversation_memory[session_id] = []        
        interaction = {
            'query': query,
            'semantic_info': {
                'final_score': final_score,
                'confidence_level': context.get('confidence_level', 'unknown') if context else 'unknown',
                'confidence_preserved': context.get('confidence_preserved', False) if context else False,
                'smart_penalty': context.get('smart_penalty', 0) if context else 0,
                'mismatch_issues': context.get('mismatch_issues', []) if context else [],
                'semantic_decision': True
            },
            'timestamp': time.time(),
            'user_type': 'lecturer',
            'decision_type': decision_type,
            'was_education_related': was_education,
            'fixed_semantic_processed': True,
            'document_context_used': bool(document_text),
            'document_context_priority': decision_type == 'use_document_context',
            'external_api_used': decision_type == 'use_external_api',
            'query_length': len(query.split()),
            'architecture': 'fixed_semantic_rag'
        }
        
        self.conversation_memory[session_id].append(interaction)        
        self.conversation_memory[session_id] = self.conversation_memory[session_id][-30:]
        
        logger.info(f"🧠 FIXED semantic memory updated for session {session_id}: {len(self.conversation_memory[session_id])} interactions")

    def _get_personal_address(self, session_id):
        try:
            if hasattr(self.response_generator, '_get_personal_address'):
                return self.response_generator._get_personal_address(session_id)
            return "giảng viên"
        except Exception as e:
            logger.error(f"❌ Error getting personal address: {str(e)}")
            return "giảng viên"

    def _get_empty_query_response(self):
        return {
            'response': "Dạ chào giảng viên! Em có thể hỗ trợ gì cho giảng viên về công việc tại BDU ạ? 🎯",
            'confidence': 0.9,
            'method': 'empty_query',
            'processing_time': 0.01,
            'fixed_semantic_rag': True
        }

    def _get_no_match_response(self):
        return {
            'response': "Dạ giảng viên, em chưa có thông tin về vấn đề này. Giảng viên có thể liên hệ phòng ban liên quan để được hỗ trợ chi tiết ạ. 🎯",
            'confidence': 0.1,
            'method': 'no_match_semantic',
            'decision_type': 'say_dont_know',
            'processing_time': 0.01,
            'fixed_semantic_rag': True
        }

    def _get_out_of_scope_response(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, em chỉ hỗ trợ các vấn đề liên quan đến công việc giảng viên tại BDU thôi ạ! 🎯"
    def _get_error_response(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, em gặp khó khăn kỹ thuật. {personal_address.title()} có thể liên hệ bộ phận IT qua email it@bdu.edu.vn để được hỗ trợ ạ. 🎯"
    def _get_clarification_fallback(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, để em hỗ trợ chính xác nhất, {personal_address} có thể nói rõ hơn về vấn đề cần hỗ trợ không ạ? 🎯"
    def _get_dont_know_fallback(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, em chưa có thông tin về vấn đề này. {personal_address.title()} có thể liên hệ phòng ban liên quan để được hỗ trợ chi tiết ạ. 🎯"
    def _get_document_fallback(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, em đã xem xét tài liệu nhưng gặp khó khăn trong việc trả lời. {personal_address.title()} có thể đặt câu hỏi cụ thể hơn không ạ? 🎯"
    def _handle_external_api_decision(self, query, context, session_id):
        try:
            jwt_token = context.get('jwt_token')
            api_result = external_api_service.get_lecturer_schedule(jwt_token, query)
            
            if api_result.get('success'):
                enhanced_context = {
                    'instruction': 'process_external_api_data',
                    'api_data': api_result,
                    'original_query': query,
                    'fallback_qa_answer': context.get('fallback_qa_answer', ''),
                    'confidence': context.get('confidence', 0)
                }
                
                response = self.response_generator.generate_response(
                    query=query, context=enhanced_context, intent_info=None, entities={}, session_id=session_id
                )                
                return response.get('response', self._get_api_fallback(api_result, session_id))
            else:
                return self._get_api_error_response(api_result, session_id)                
        except Exception as e:
            logger.error(f"❌ Error handling external API: {str(e)}")
            return self._get_api_error_fallback(session_id)
        
    def _handle_authentication_required(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, để em có thể cung cấp thông tin cá nhân như lịch giảng dạy, {personal_address} cần đăng nhập vào ứng dụng trước ạ. 🔐"
    def _get_api_fallback(self, api_result, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, em đã tìm thấy thông tin lịch giảng dạy nhưng gặp khó khăn trong việc trình bày chi tiết. {personal_address.title()} có thể truy cập hệ thống quản lý đào tạo để xem thông tin đầy đủ ạ. 🎯"
    def _get_api_error_response(self, api_result, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, em gặp khó khăn khi truy xuất thông tin cá nhân. {personal_address.title()} có thể thử lại sau hoặc liên hệ bộ phận IT để được hỗ trợ ạ. 🎯"
    def _get_api_error_fallback(self, session_id):
        personal_address = self._get_personal_address(session_id)
        return f"Dạ {personal_address}, em gặp khó khăn kỹ thuật khi truy xuất thông tin cá nhân. {personal_address.title()} có thể thử lại sau ạ. 🎯"
    def _format_sources(self, results):
        sources = []
        for result in results:
            if result and result.get('final_score', 0) > 0.2:
                sources.append({
                    'question': result['question'],
                    'category': result.get('category', 'Giảng viên'),
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
        
        logger.info("✅ FIXED semantic knowledge base reloaded successfully")

class ChatbotAI:
    def __init__(self, shared_response_generator):
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
            # Gọi service để lấy nội dung file link.csv từ Drive
            link_csv_content = drive_service.get_specific_csv_content('link.csv')
            
            if not link_csv_content:
                logger.error("❌ Could not load link.csv from Google Drive. Link mapping will be empty.")
                self.link_mapping = {}
                return

            # Dùng pandas để đọc nội dung CSV từ string
            df_links = pd.read_csv(io.StringIO(link_csv_content), encoding='utf-8')
            
            for index, row in df_links.iterrows():
                # Dùng .get() để tránh lỗi nếu cột không tồn tại
                stt = str(row.get('STT', '')).strip()
                link = str(row.get('Link', '')).strip()
                if stt and link and stt != 'nan' and link != 'nan':
                    self.link_mapping[stt] = link
            
            logger.info(f"✅ Loaded {len(self.link_mapping)} reference links FROM GOOGLE DRIVE")

        except Exception as e:
            logger.error(f"❌ Error loading link mapping FROM GOOGLE DRIVE: {str(e)}")
            self.link_mapping = {}

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
        try:
            self.load_link_mapping()            
            db_qa_entries = []
            try:
                from qa_management.models import QAEntry
                qa_entries = QAEntry.objects.filter(is_active=True).order_by('stt')
                
                for entry in qa_entries:
                    db_qa_entries.append({
                        'question': entry.question,
                        'answer': entry.answer,
                        'category': entry.category or 'Giảng viên',
                        'STT': entry.stt
                    })
                logger.info(f"✅ Loaded {len(db_qa_entries)} entries from QA Management database")
            except Exception as e:
                logger.warning(f"⚠️ QA Management not available: {str(e)}")
            
            csv_knowledge = []
            try:
                drive_data = drive_service.get_csv_data()
                if drive_data:
                    csv_knowledge = drive_data
                    logger.info(f"✅ Loaded {len(csv_knowledge)} records from Google Drive")
            except Exception as e:
                logger.error(f"❌ Failed to load from Google Drive: {str(e)}")
            
            if not csv_knowledge and not db_qa_entries:
                csv_path = os.path.join(settings.BASE_DIR, 'data', 'QA.csv')
                if os.path.exists(csv_path):
                    try:
                        df = pd.read_csv(csv_path, encoding='utf-8')
                        for index, row in df.iterrows():
                            if pd.isna(row.get('question')) or pd.isna(row.get('answer')):
                                continue
                            csv_knowledge.append({
                                'question': str(row['question']),
                                'answer': str(row['answer']),
                                'category': str(row.get('category', 'Chung')),
                                'STT': str(row.get('STT', ''))
                            })
                        logger.info(f"✅ Fallback: Loaded {len(csv_knowledge)} records from local CSV")
                    except Exception as e:
                        logger.error(f"❌ Fallback CSV also failed: {str(e)}")
            
            db_knowledge = list(KnowledgeBase.objects.filter(is_active=True).values(
                'question', 'answer', 'category'
            ))            
            self.knowledge_data = db_qa_entries + csv_knowledge + db_knowledge            
            if self.model and self.knowledge_data:
                self.build_faiss_index()            
            logger.info(f"✅ FIXED semantic knowledge base loaded: {len(self.knowledge_data)} entries")            
        except Exception as e:
            logger.error(f"Error loading knowledge base: {str(e)}")
            self.knowledge_data = []

    def build_faiss_index(self):
        try:
            questions = [item['question'] for item in self.knowledge_data]
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
            
            # Restore Vietnamese tone nếu cần
            original_query = query
            if self.vietnamese_restorer and not self.vietnamese_restorer.has_vietnamese_accents(query):
                restored_query = self.vietnamese_restorer.restore_vietnamese_tone(query)
                if restored_query != query:
                    logger.info(f"🎯 Using restored query for context search: '{query}' -> '{restored_query}'")
                    query = restored_query
            
            # Build enhanced query với context
            enhanced_query = query
            if context_keywords and len(context_keywords) > 0:
                # Thêm context keywords vào query một cách tự nhiên
                context_str = " ".join(context_keywords[:3])  # Chỉ dùng 3 keywords đầu
                enhanced_query = f"{query} {context_str}"
                logger.info(f"🔍 Enhanced query với context: '{query}' -> '{enhanced_query}'")
            
            # Perform semantic search với enhanced query
            query_embedding = self.model.encode([enhanced_query])
            faiss.normalize_L2(query_embedding)
            
            scores, indices = self.index.search(
                query_embedding.astype('float32'), 
                min(top_k, len(self.knowledge_data))
            )
            
            # Build candidates với thông tin context
            candidates = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < len(self.knowledge_data) and score > 0.1:
                    candidate = self.knowledge_data[idx].copy()
                    candidate['semantic_score'] = float(score)
                    candidate['similarity'] = float(score)
                    candidate['reference_links'] = self.get_reference_links(candidate)
                    # 🆕 THÊM: Đánh dấu đây là kết quả có context
                    candidate['context_enhanced'] = bool(context_keywords)
                    candidate['context_keywords_used'] = context_keywords or []
                    candidates.append(candidate)
            
            logger.info(f"🔍 Context-enhanced search found {len(candidates)} candidates")
            return candidates
            
        except Exception as e:
            logger.error(f"Context-enhanced search error: {str(e)}")
            # Fallback to normal search
            return self.semantic_search_top_k(query, top_k)

    def dual_semantic_search(self, query, context_keywords=None, top_k=20):
        """
        🔧 STABILITY IMPROVED: Dual search với logic ổn định hơn
        - Ưu tiên consistency over optimization
        - Thêm fallback mechanisms
        """
        try:
            logger.info(f"🔄 STABLE Dual semantic search for: '{query}' with context: {context_keywords}")
            
            # ALWAYS perform normal search first (baseline)
            normal_candidates = self.semantic_search_top_k(query, top_k)
            logger.info(f"🔍 Normal search: {len(normal_candidates)} candidates, top_score={normal_candidates[0].get('semantic_score', 0):.3f if normal_candidates else 0}")
            
            # Context search only if meaningful context exists
            context_candidates = []
            if context_keywords and len(context_keywords) > 0:
                context_candidates = self.semantic_search_with_context(query, context_keywords, top_k)
                logger.info(f"🔍 Context search: {len(context_candidates)} candidates, top_score={context_candidates[0].get('semantic_score', 0):.3f if context_candidates else 0}")
            
            # STABLE DECISION LOGIC: Prefer consistency
            if not context_candidates or len(context_candidates) == 0:
                logger.info("🔍 Using normal search (no context results)")
                return normal_candidates, 'normal'
            
            if not normal_candidates or len(normal_candidates) == 0:
                logger.info("🔍 Using context search (no normal results)")  
                return context_candidates, 'context'
            
            # Compare with stability bias
            normal_top_score = normal_candidates[0].get('semantic_score', 0)
            context_top_score = context_candidates[0].get('semantic_score', 0)
            score_diff = context_top_score - normal_top_score
            
            # 🔧 STABILITY: More conservative switching với hysteresis
            # Context cần tốt hơn đáng kể MỚI được chọn
            if score_diff > 0.2:  # Tăng từ 0.15 lên 0.2
                logger.info(f"🔍 Context significantly better (+{score_diff:.3f}) - using context")
                return context_candidates, 'context'
            elif score_diff < -0.05:  # Normal rõ ràng tốt hơn
                logger.info(f"🔍 Normal clearly better ({score_diff:.3f}) - using normal")
                return normal_candidates, 'normal'
            else:
                # Trong vùng uncertain, ưu tiên theo query characteristics
                query_lower = query.lower()
                
                # Nếu query có đại từ hoặc tham chiếu, ưu tiên context
                if any(pronoun in query_lower for pronoun in ['ông ấy', 'bà ấy', 'người đó', 'thầy ấy', 'cô ấy']):
                    logger.info(f"🔍 Query has pronoun - preferring context (score_diff: {score_diff:.3f})")
                    return context_candidates, 'context'
                
                # Nếu query có tên riêng, ưu tiên normal để tránh confusion
                has_proper_name = any(word[0].isupper() for word in query.split() if len(word) > 1)
                if has_proper_name:
                    logger.info(f"🔍 Query has proper names - preferring normal for stability (score_diff: {score_diff:.3f})")
                    return normal_candidates, 'normal'
                
                # Default: ưu tiên normal cho stability
                logger.info(f"🔍 Ambiguous case - preferring normal for stability (score_diff: {score_diff:.3f})")
                return normal_candidates, 'normal'
            
        except Exception as e:
            logger.error(f"Dual search error: {str(e)}")
            # ALWAYS fallback to normal search
            return self.semantic_search_top_k(query, top_k), 'fallback'

    
class BDUChatbotService:
    def __init__(self):
        self.response_generator = LocalQwenGenerator()
        self.query_cache = query_response_cache        
        self.semantic_chatbot = PureSemanticChatbotAI(shared_response_generator=self.response_generator)
        self.personal_info_keywords = [
            # Từ khóa cốt lõi
            'tôi là ai', 'toi la ai', 'thông tin của tôi', 'thong tin cua toi',
            'lịch của tôi', 'lich cua toi', 'thời khóa biểu của tôi', 'tkb của tôi',
            'lịch giảng của tôi', 'lich giang cua toi', 'lịch dạy của tôi', 'lich day cua toi',
            'tôi giảng', 'toi giang', 'tôi dạy', 'toi day', 'môn của tôi', 'mon cua toi',
            
            # Từ khóa thời gian
            'hôm nay', 'hom nay', 'ngày mai', 'ngay mai', 
            'tuần này', 'tuan nay', 'tuần sau', 'tuan sau', 'tuần tới', 'tuan toi',
            'tháng này', 'thang nay', 'tháng sau', 'thang sau'
        ]
        
        logger.info("🎯 ENHANCED BDUChatbotService initialized with Top-5 Smart Selection")

    def _needs_external_api(self, query: str) -> bool:
        if not query:
            return False
        
        query_lower = query.lower()
        needs_api = any(keyword in query_lower for keyword in self.personal_info_keywords)
        
        logger.debug(f"🌐 API check: '{query}' -> {needs_api}")
        return needs_api

    def process_query(self, query: str, session_id: str = None, jwt_token: str = None, document_text: str = None) -> dict:
        start_time = time.time()        
        logger.info(f"🎯 ENHANCED BDU Service Processing: '{query}' (session: {session_id}, has_token: {bool(jwt_token)}, has_document: {bool(document_text)})")        
        try:
            if not query or len(query.strip()) < 2:
                try:
                    if hasattr(self.response_generator, '_get_personal_address') and session_id:
                        personal_address = self.response_generator._get_personal_address(session_id)
                        response_text = f"Dạ chào {personal_address}! Em có thể hỗ trợ gì cho {personal_address} về công việc tại BDU ạ? 🎯"
                    else:
                        response_text = "Dạ chào giảng viên! Em có thể hỗ trợ gì cho giảng viên về công việc tại BDU ạ? 🎯"
                except:
                    response_text = "Dạ chào giảng viên! Em có thể hỗ trợ gì cho giảng viên về công việc tại BDU ạ? 🎯"                    
                return {
                    'response': response_text,
                    'confidence': 0.9,
                    'method': 'empty_query',
                    'processing_time': time.time() - start_time,
                    'enhanced_semantic_rag': True,
                    'cache_hit': False
                }
            
            cached_response = self.query_cache.get(query)
            if cached_response:
                cached_response['processing_time'] = time.time() - start_time
                logger.info(f"⚡ CACHE HIT: Response served in {cached_response['processing_time']:.3f}s")
                return cached_response
            
            logger.info("💨 CACHE MISS: Proceeding with ENHANCED semantic processing")
            
            if self._needs_external_api(query):
                logger.info("🚨 API PRIORITY: Personal info query detected")
                
                if jwt_token and jwt_token.strip():
                    api_result = self._handle_external_api_call(query, session_id, jwt_token)
                    api_result['cache_hit'] = False
                    api_result['cache_skipped'] = 'personal_query'
                    return api_result
                else:
                    auth_result = self._handle_authentication_required(session_id)
                    auth_result['cache_hit'] = False
                    auth_result['cache_skipped'] = 'authentication_required'
                    return auth_result
            
            logger.info("📚 Using ENHANCED Semantic RAG System with Top-5 Smart Selection")
            result = self.semantic_chatbot.process_query(query, session_id, jwt_token, document_text)            
            result['api_priority_activated'] = False
            result['fallback_to_enhanced_semantic'] = True
            result['cache_hit'] = False            
            cache_stored = self.query_cache.set(query, result)
            result['cache_stored'] = cache_stored
            
            if cache_stored:
                logger.info(f"💾 Response cached for future requests")            
            return result
            
        except Exception as e:
            logger.error(f"❌ ENHANCED BDU Service Error: {str(e)}")            
            try:
                if hasattr(self.response_generator, '_get_personal_address'):
                    personal_address = self.response_generator._get_personal_address(session_id)
                else:
                    personal_address = "giảng viên"
            except:
                personal_address = "giảng viên"                
            return {
                'response': f"Dạ {personal_address}, em gặp khó khăn kỹ thuật. {personal_address.title()} có thể liên hệ bộ phận IT qua email it@bdu.edu.vn để được hỗ trợ ạ. 🎯",
                'confidence': 0.0,
                'method': 'service_error',
                'processing_time': time.time() - start_time,
                'error': str(e),
                'enhanced_semantic_rag': True,
                'graceful_degradation_used': True,
                'cache_hit': False,
                'cache_stored': False
            }

    def _handle_external_api_call(self, query: str, session_id: str, jwt_token: str) -> dict:
        try:
            logger.info("🌐 Calling external API for personal information")
            
            api_result = external_api_service.get_lecturer_schedule(jwt_token, query)
            
            if api_result.get('success'):
                enhanced_context = {
                    'instruction': 'process_external_api_data',
                    'api_data': api_result,
                    'original_query': query,
                    'confidence': 0.95
                }
                
                response = self.response_generator.generate_response(
                    query=query,
                    context=enhanced_context,
                    intent_info=None,
                    entities={},
                    session_id=session_id
                )
                
                return {
                    'response': response.get('response', self._get_api_fallback(session_id)),
                    'confidence': 0.95,
                    'method': 'external_api_success',
                    'decision_type': 'use_external_api',
                    'processing_time': 0.5,
                    'external_api_used': True,
                    'api_priority_activated': True,
                    'fixed_semantic_rag': True
                }
            else:
                error_type = api_result.get('error_type', 'unknown')
                return {
                    'response': self._get_api_error_response(error_type, session_id),
                    'confidence': 0.1,
                    'method': 'external_api_failed',
                    'decision_type': 'api_error',
                    'processing_time': 0.3,
                    'external_api_used': True,
                    'api_error': api_result.get('error', ''),
                    'api_priority_activated': True,
                    'graceful_degradation_used': True
                }
                
        except Exception as e:
            logger.error(f"❌ Error in external API call: {str(e)}")
            try:
                if hasattr(self.response_generator, '_get_personal_address'):
                    personal_address = self.response_generator._get_personal_address(session_id)
                else:
                    personal_address = "giảng viên"
            except:
                personal_address = "giảng viên"
                
            return {
                'response': f"Dạ {personal_address}, em gặp khó khăn khi truy xuất thông tin cá nhân. {personal_address.title()} có thể thử lại sau ạ. 🎯",
                'confidence': 0.1,
                'method': 'external_api_error',
                'processing_time': 0.2,
                'error': str(e),
                'api_priority_activated': True,
                'graceful_degradation_used': True
            }

    def _handle_authentication_required(self, session_id: str) -> dict:
        try:
            if hasattr(self.response_generator, '_get_personal_address'):
                personal_address = self.response_generator._get_personal_address(session_id)
            else:
                personal_address = "giảng viên"
        except:
            personal_address = "giảng viên"
            
        return {
            'response': f"Dạ {personal_address}, để em có thể cung cấp thông tin cá nhân như lịch giảng dạy, {personal_address} cần đăng nhập vào ứng dụng trước ạ. 🔐",
            'confidence': 0.9,
            'method': 'authentication_required',
            'decision_type': 'require_authentication',
            'processing_time': 0.01,
            'external_api_used': False,
            'api_priority_activated': True,
            'authentication_required': True
        }

    def _get_api_fallback(self, session_id):
        try:
            if hasattr(self.response_generator, '_get_personal_address'):
                personal_address = self.response_generator._get_personal_address(session_id)
            else:
                personal_address = "giảng viên"
        except:
            personal_address = "giảng viên"            
        return f"Dạ {personal_address}, em đã tìm thấy thông tin lịch giảng dạy nhưng gặp khó khăn trong việc trình bày chi tiết. {personal_address.title()} có thể truy cập hệ thống quản lý đào tạo để xem thông tin đầy đủ ạ. 🎯"

    def _get_api_error_response(self, error_type, session_id):
        try:
            if hasattr(self.response_generator, '_get_personal_address'):
                personal_address = self.response_generator._get_personal_address(session_id)
            else:
                personal_address = "giảng viên"
        except:
            personal_address = "giảng viên"
            
        if error_type == 'token_decode_failed':
            return f"Dạ {personal_address}, phiên đăng nhập đã hết hạn. {personal_address.title()} vui lòng đăng nhập lại vào ứng dụng BDU ạ. 🔐"
        elif error_type == 'authentication_failed':
            return f"Dạ {personal_address}, thông tin đăng nhập không hợp lệ. {personal_address.title()} vui lòng đăng nhập lại ạ. 🔐"
        else:
            return f"Dạ {personal_address}, em gặp khó khăn kỹ thuật khi truy xuất thông tin. {personal_address.title()} có thể thử lại sau ạ. 🎯"

    def get_system_status(self):
        semantic_status = self.semantic_chatbot.get_system_status()
        api_status = external_api_service.get_system_status()
        cache_stats = self.query_cache.get_cache_stats()        
        return {
            'service_name': 'BDUChatbotService',
            'architecture': 'context_aware_semantic_rag',  # 🆕 UPDATED
            'chatbot_service': semantic_status,
            'external_api_service': api_status,
            'cache_performance': cache_stats,
            'context_aware_features': [  # 🆕 UPDATED features list
                'entity_extraction_and_memory',
                'context_enhanced_search',
                'dual_search_strategy',
                'smart_context_fallback',
                'conversation_continuity',
                'multi_turn_understanding',
                'entity_relationship_tracking',
                'context_quality_analysis',
                'smart_penalty_system',
                'confidence_preservation', 
                'adaptive_mismatch_tolerance',
                'tiered_decision_logic',
                'targeted_clarification',
                'high_quality_answer_protection',
                'top5_smart_candidate_selection',
                'document_context_processing',
                'external_api_integration',
                'query_response_cache',
                'graceful_degradation'
            ],
            'removed_features': [
                'intent_classification',
                'keyword_matching',
                'ensemble_methods',
                'mega_intent_system',
                'complex_context_analysis',
                'hard_coded_rules',
                'over_aggressive_penalties',
                'single_candidate_limitation',
                'context_lock_in_issues'  # 🆕 REMOVED ISSUE
            ],
            'processing_flow': [  # 🆕 UPDATED flow
                '1. Cache Check',
                '2. Personal Info API Detection', 
                '3. Context Analysis from Conversation Memory',
                '4. Dual Semantic Search (Normal + Context-Enhanced)',
                '5. Smart Search Method Selection',
                '6. Two-Stage Semantic Re-ranking',
                '7. Smart Candidate Selection from Top-5',
                '8. Context Quality Analysis',
                '9. Confidence-Aware Decision Making',
                '10. Response Generation with Smart Fallback',
                '11. Entity Extraction and Memory Update',
                '12. Cache Storage'
            ]
        }

    def test_context_functionality(self, session_id="test_session"):
        """🆕 Test context-aware functionality"""
        logger.info("🧪 Testing context-aware functionality...")
        
        test_results = {
            'entity_extraction': False,
            'context_memory': False, 
            'dual_search': False,
            'context_enhancement': False,
            'conversation_continuity': False
        }        
        try:
            # Test 1: Entity extraction
            if hasattr(self.response_generator, 'memory') and hasattr(self.response_generator.memory, 'entity_extractor'):
                entities = self.response_generator.memory.entity_extractor.extract_entities(
                    "Hiệu trưởng là Cao Việt Hiếu", 
                    "hiệu trưởng là ai"
                )
                test_results['entity_extraction'] = bool(entities)
                logger.info(f"✅ Entity extraction test: {entities}")
            
            # Test 2: Context memory
            if hasattr(self.response_generator, 'memory'):
                self.response_generator.memory.add_interaction(
                    session_id, 
                    "hiệu trưởng là ai?", 
                    "Cao Việt Hiếu", 
                    intent_info={'intent': 'test'}, 
                    entities={}
                )
                
                context_info = self.response_generator.memory.get_context_for_query(
                    session_id, 
                    "vậy Cao Việt Hiếu là ai?"
                )
                test_results['context_memory'] = context_info.get('should_use_context', False)
                logger.info(f"✅ Context memory test: {context_info}")
            
            # Test 3: Dual search
            if hasattr(self.sbert_retriever, 'dual_semantic_search'):
                candidates, method = self.sbert_retriever.dual_semantic_search(
                    "test query", 
                    ["test keyword"], 
                    top_k=5
                )
                test_results['dual_search'] = method in ['normal', 'context', 'fallback']
                logger.info(f"✅ Dual search test: method={method}, candidates={len(candidates)}")
            
            # Test 4: Context enhancement (full pipeline test)
            try:
                result = self.process_query("ai là hiệu trưởng?", session_id=session_id)
                test_results['context_enhancement'] = 'context_info' in result
                logger.info(f"✅ Context enhancement test: {result.get('context_info', {})}")
                
                # Follow-up query để test continuity  
                result2 = self.process_query("vậy người đó làm gì?", session_id=session_id)
                test_results['conversation_continuity'] = result2.get('context_info', {}).get('context_used', False)
                logger.info(f"✅ Conversation continuity test: {result2.get('context_info', {})}")
            except Exception as e:
                logger.error(f"❌ Context enhancement test failed: {str(e)}")
        
        except Exception as e:
            logger.error(f"❌ Context functionality test failed: {str(e)}")
        
        # Cleanup test session
        if session_id and hasattr(self.response_generator, 'memory'):
            if session_id in self.response_generator.memory.conversations:
                del self.response_generator.memory.conversations[session_id]
        
        passed_tests = sum(test_results.values())
        total_tests = len(test_results)
        
        logger.info(f"🧪 Context functionality test completed: {passed_tests}/{total_tests} tests passed")
        logger.info(f"📊 Test results: {test_results}")
        
        return {
            'test_results': test_results,
            'passed': passed_tests,
            'total': total_tests,
            'success_rate': passed_tests / total_tests if total_tests > 0 else 0,
            'fully_functional': passed_tests == total_tests
        }
    
    def get_conversation_memory(self, session_id):
        return self.semantic_chatbot.get_conversation_memory(session_id)
    def clear_conversation_memory(self, session_id=None):
        return self.semantic_chatbot.clear_conversation_memory(session_id)
    def reload_after_qa_update(self):
        return self.semantic_chatbot.reload_after_qa_update()
    @property
    def model(self):
        return self.semantic_chatbot.model
    @property
    def index(self):
        return self.semantic_chatbot.index
    @property
    def knowledge_data(self):
        return self.semantic_chatbot.knowledge_data
    def get_cache_stats(self):
        return self.query_cache.get_cache_stats()
    def clear_cache(self):
        return self.query_cache.clear_cache()
    def update_cache_ttl(self, new_ttl: int):
        self.query_cache.update_ttl(new_ttl)
        logger.info(f"🔄 Cache TTL updated to {new_ttl} seconds")

chatbot_ai = BDUChatbotService()