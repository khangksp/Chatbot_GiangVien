import re
from typing import Dict, Any
import logging
logger = logging.getLogger(__name__)

class AdvancedConfidenceManager:
    def __init__(self):
        self.MAX_CONFIDENCE = 1.0
        self.confidence_calibration_rules = {
            'high_semantic_match': 0.95,
            'medium_semantic_match': 0.75, 
            'low_semantic_match': 0.45,
            'keyword_match_bonus': 0.1,
            'context_match_bonus': 0.05,
            'document_context_bonus': 0.1
        }
        
        self.decision_thresholds = {
            'direct_answer': 0.8,
            'enhanced_answer': 0.45,
            'ask_clarification': 0.25,
            'dont_know': 0.1
        }
        
        logger.info("✅ AdvancedConfidenceManager initialized with overflow protection")
    
    def normalize_confidence(self, raw_confidence: float, source: str = "unknown") -> float:
        if raw_confidence is None or not isinstance(raw_confidence, (int, float)):
            logger.warning(f"⚠️ Invalid confidence value: {raw_confidence} from {source}")
            return 0.1
        
        normalized = min(self.MAX_CONFIDENCE, abs(float(raw_confidence)))
        
        if raw_confidence > self.MAX_CONFIDENCE:
            logger.info(f"🛡️ Confidence capped: {raw_confidence:.3f} -> {normalized:.3f} (source: {source})")
        
        return normalized
    
    def calculate_response_confidence(self, semantic_score: float = 0, 
                                   keyword_score: float = 0,
                                   context_bonus: float = 0,
                                   method: str = "hybrid") -> float:
        base_confidence = 0.0
        
        if semantic_score >= 0.8:
            base_confidence = self.confidence_calibration_rules['high_semantic_match']
        elif semantic_score >= 0.6:
            base_confidence = self.confidence_calibration_rules['medium_semantic_match']
        else:
            base_confidence = self.confidence_calibration_rules['low_semantic_match']
        if keyword_score > 0.5:
            base_confidence += self.confidence_calibration_rules['keyword_match_bonus']
        if context_bonus > 0:
            base_confidence += self.confidence_calibration_rules['context_match_bonus']
        method_adjustments = {
            'two_stage_reranking': 0.05,
            'document_context': 0.1,
            'external_api': 0.15,
            'hybrid': 0.0,
            'fallback': -0.2
        }
        
        base_confidence += method_adjustments.get(method, 0.0)
        final_confidence = self.normalize_confidence(base_confidence, f"response_calculation_{method}")
        logger.debug(f"🧮 Confidence calculation: semantic={semantic_score:.3f}, "
                    f"keyword={keyword_score:.3f}, method={method} -> {final_confidence:.3f}")
        return final_confidence
    
    def get_response_strategy(self, confidence: float) -> str:
        confidence = self.normalize_confidence(confidence, "strategy_decision")
        if confidence >= self.decision_thresholds['direct_answer']:
            return 'direct_answer'
        elif confidence >= self.decision_thresholds['enhanced_answer']:
            return 'enhanced_answer'
        elif confidence >= self.decision_thresholds['ask_clarification']:
            return 'ask_clarification'
        else:
            return 'dont_know'