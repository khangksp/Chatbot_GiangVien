import os
import logging
import torch
from django.conf import settings

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print("Warning: sentence-transformers not installed. Fine-tuned model will not be available.")

logger = logging.getLogger(__name__)

class PhoBERTRetrieverService:    
    def __init__(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu') if torch.cuda.is_available() else 'cpu'
        self.fine_tuned_model = None
        self.base_model = None
        self.fallback_mode = True  # Start in fallback mode
        
        # Fine-tuned model path
        self.fine_tuned_model_path = os.path.join(settings.BASE_DIR, 'fine_tuned_phobert')
        
        logger.info("🎯 PhoBERTRetrieverService: Pure semantic retriever service initialized")
        self._load_models_with_priority()

    def _load_models_with_priority(self):
        """
        🎯 SIMPLIFIED: Load models with priority: Fine-tuned > Base > Fallback
        """
        
        # Priority 1: Try to load fine-tuned sentence transformer model
        if self._load_fine_tuned_model():
            logger.info("✅ Using fine-tuned PhoBERT model for semantic retrieval")
            self.fallback_mode = False
            return
        
        # Priority 2: Try to load base PhoBERT model (fallback)
        if self._load_base_model():
            logger.info("✅ Using base PhoBERT model for semantic retrieval")
            self.fallback_mode = False
            return
        
        # Priority 3: Fallback mode (no semantic model available)
        logger.warning("⚠️ No semantic model available - system will use fallback keyword matching")
        self.fallback_mode = True

    def _load_fine_tuned_model(self):
        """
        🎯 CORE: Load fine-tuned sentence transformer model
        """
        try:
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                logger.info("📦 sentence-transformers not available, skipping fine-tuned model")
                return False
            
            if not os.path.exists(self.fine_tuned_model_path):
                logger.info(f"📁 Fine-tuned model not found at {self.fine_tuned_model_path}")
                return False
            
            # Check if it's a valid sentence-transformers model
            config_path = os.path.join(self.fine_tuned_model_path, 'config.json')
            model_bin_path = os.path.join(self.fine_tuned_model_path, 'pytorch_model.bin')
            model_safetensors_path = os.path.join(self.fine_tuned_model_path, 'model.safetensors')

            if not os.path.exists(config_path) or not (os.path.exists(model_bin_path) or os.path.exists(model_safetensors_path)):
                logger.warning(f"⚠️ Fine-tuned model directory incomplete at {self.fine_tuned_model_path}")
                return False
            
            logger.info(f"🔥 Loading fine-tuned sentence transformer model from: {self.fine_tuned_model_path}")
            self.fine_tuned_model = SentenceTransformer(self.fine_tuned_model_path)
            
            # Test the model with a simple encoding
            test_text = "Test encoding for PhoBERT retriever"
            test_embedding = self.fine_tuned_model.encode([test_text])
            
            if test_embedding is not None and len(test_embedding) > 0:
                logger.info("✅ Fine-tuned PhoBERT retriever model loaded and tested successfully")
                return True
            else:
                logger.error("❌ Fine-tuned model test failed")
                self.fine_tuned_model = None
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ Failed to load fine-tuned model: {str(e)}")
            self.fine_tuned_model = None
            return False

    def _load_base_model(self):
        """
        🎯 FALLBACK: Load base PhoBERT model as fallback
        """
        try:
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                return False
                
            model_name = "vinai/phobert-base"
            logger.info(f"🔥 Loading base PhoBERT model: {model_name}")
            
            self.base_model = SentenceTransformer(model_name)
            
            # Test the model
            test_text = "Test encoding for base PhoBERT"
            test_embedding = self.base_model.encode([test_text])
            
            if test_embedding is not None and len(test_embedding) > 0:
                logger.info("✅ Base PhoBERT model loaded successfully")
                return True
            else:
                logger.error("❌ Base model test failed")
                self.base_model = None
                return False
            
        except Exception as e:
            logger.warning(f"⚠️ Base PhoBERT not available: {str(e)}")
            self.base_model = None
            return False

    def encode_text(self, text):
        """
        🎯 CORE METHOD: Encode text using available model (fine-tuned > base > None)
        
        Args:
            text (str): Text to encode
            
        Returns:
            numpy.ndarray: Text embedding or None if no model available
        """
        
        # Priority 1: Use fine-tuned model
        if self.fine_tuned_model:
            try:
                embeddings = self.fine_tuned_model.encode([text])
                return embeddings.reshape(1, -1) if embeddings is not None else None
            except Exception as e:
                logger.error(f"Error encoding with fine-tuned model: {str(e)}")
        
        # Priority 2: Use base model
        if self.base_model:
            try:
                embeddings = self.base_model.encode([text])
                return embeddings.reshape(1, -1) if embeddings is not None else None
            except Exception as e:
                logger.error(f"Error encoding text with base model: {str(e)}")
        
        # Priority 3: No encoding available
        logger.warning("⚠️ No semantic model available for text encoding")
        return None

    def encode_batch(self, texts):
        """
        🎯 BATCH ENCODING: Encode multiple texts efficiently
        
        Args:
            texts (list): List of texts to encode
            
        Returns:
            numpy.ndarray: Batch of text embeddings or None
        """
        
        if not texts:
            return None
        
        # Priority 1: Use fine-tuned model
        if self.fine_tuned_model:
            try:
                embeddings = self.fine_tuned_model.encode(texts)
                return embeddings
            except Exception as e:
                logger.error(f"Error batch encoding with fine-tuned model: {str(e)}")
        
        # Priority 2: Use base model
        if self.base_model:
            try:
                embeddings = self.base_model.encode(texts)
                return embeddings
            except Exception as e:
                logger.error(f"Error batch encoding with base model: {str(e)}")
        
        # Priority 3: No encoding available
        logger.warning("⚠️ No semantic model available for batch encoding")
        return None

    def get_model_info(self):
        """
        🎯 UTILITY: Get information about loaded models
        
        Returns:
            dict: Model information
        """
        return {
            'fine_tuned_model_available': bool(self.fine_tuned_model),
            'base_model_available': bool(self.base_model), 
            'fine_tuned_model_path': self.fine_tuned_model_path,
            'fallback_mode': self.fallback_mode,
            'model_priority': 'fine_tuned' if self.fine_tuned_model else 'base' if self.base_model else 'none',
            'device': str(self.device),
            'sentence_transformers_available': SENTENCE_TRANSFORMERS_AVAILABLE,
            'service_type': 'pure_semantic_retriever'
        }

    def get_system_status(self):
        """
        🎯 SIMPLIFIED: Get system status for pure semantic retriever
        """
        model_info = self.get_model_info()
        
        return {
            'service_name': 'PhoBERTRetrieverService',
            'service_type': 'pure_semantic_retriever_service',
            'model_loaded': not self.fallback_mode,
            'fine_tuned_model_loaded': bool(self.fine_tuned_model),
            'base_model_loaded': bool(self.base_model),
            'fallback_mode': self.fallback_mode,
            'model_info': model_info,
            'capabilities': [
                'semantic_text_encoding',
                'batch_text_encoding', 
                'fine_tuned_model_support',
                'model_priority_system',
                'graceful_fallback'
            ],
            'removed_features': [
                'intent_classification',
                'keyword_matching',
                'ensemble_methods',
                'mega_intent_system',
                'hard_coded_rules'
            ],
            'architecture': 'pure_semantic_rag'
        }

    def is_available(self):
        """
        🎯 UTILITY: Check if semantic encoding is available
        
        Returns:
            bool: True if any model is available for encoding
        """
        return bool(self.fine_tuned_model or self.base_model)

    def get_embedding_dimension(self):
        """
        🎯 UTILITY: Get embedding dimension of current model
        
        Returns:
            int: Embedding dimension or None
        """
        try:
            if self.fine_tuned_model:
                return self.fine_tuned_model.get_sentence_embedding_dimension()
            elif self.base_model:
                return self.base_model.get_sentence_embedding_dimension()
            else:
                return None
        except Exception as e:
            logger.error(f"Error getting embedding dimension: {str(e)}")
            return None

    def reload_models(self):
        """
        🎯 UTILITY: Reload models (useful after fine-tuning)
        """
        logger.info("🔄 Reloading PhoBERT retriever models...")
        
        # Clear existing models
        self.fine_tuned_model = None
        self.base_model = None
        self.fallback_mode = True
        
        # Reload with priority
        self._load_models_with_priority()
        
        logger.info("✅ PhoBERT retriever models reloaded successfully")

# Global instance for the application
retriever_service = PhoBERTRetrieverService()