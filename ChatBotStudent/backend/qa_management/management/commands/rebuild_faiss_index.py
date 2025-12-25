"""
Management command to rebuild FAISS index after Q&A data changes
Usage: python manage.py rebuild_faiss_index [--force]
"""

from django.core.management.base import BaseCommand, CommandError
from qa_management.models import QAEntry
import time

class Command(BaseCommand):
    help = 'Rebuild FAISS index for chatbot after Q&A data changes'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force rebuild even if index seems recent',
        )
    
    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🚀 Starting FAISS index rebuild...')
        )
        
        start_time = time.time()
        
        try:
            # Import chatbot AI service
            from ai_models.services import chatbot_ai
            
            # Check current index status
            current_count = len(chatbot_ai.knowledge_data) if chatbot_ai.knowledge_data else 0
            db_count = QAEntry.objects.filter(is_active=True).count()
            
            self.stdout.write(f'📊 Current index size: {current_count} entries')
            self.stdout.write(f'📊 Database active entries: {db_count} entries')
            
            if current_count == db_count and not options['force']:
                self.stdout.write(
                    self.style.WARNING(
                        '⚠️ Index appears up-to-date. Use --force to rebuild anyway.'
                    )
                )
                return
            
            # Force reload from Google Drive and rebuild index
            self.stdout.write('🔄 Forcing refresh from Google Drive...')
            
            # Clear cache and reload
            if hasattr(chatbot_ai.sbert_retriever, 'cached_data'):
                chatbot_ai.sbert_retriever.cached_data = None
                chatbot_ai.sbert_retriever.cache_timestamp = 0
            
            # Reload knowledge base
            self.stdout.write('📚 Reloading knowledge base...')
            chatbot_ai.sbert_retriever.load_knowledge_base()
            
            new_count = len(chatbot_ai.knowledge_data) if chatbot_ai.knowledge_data else 0
            
            # Build new FAISS index
            if chatbot_ai.sbert_retriever.model and new_count > 0:
                self.stdout.write('🔧 Building FAISS index...')
                chatbot_ai.sbert_retriever.build_faiss_index()
                
                duration = time.time() - start_time
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ FAISS index rebuilt successfully in {duration:.1f}s'
                    )
                )
                self.stdout.write(f'📊 New index size: {new_count} entries')
                
                # Test the index
                self.stdout.write('🧪 Testing index...')
                test_query = "ngân hàng đề thi"
                test_result = chatbot_ai.sbert_retriever.generate_response(test_query)
                
                if test_result.get('confidence', 0) > 0:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✅ Index test passed (confidence: {test_result["confidence"]:.3f})'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            '⚠️ Index test returned low confidence - check data quality'
                        )
                    )
                
                # Show system status
                system_status = chatbot_ai.get_system_status()
                self.stdout.write('')
                self.stdout.write('📈 System Status:')
                self.stdout.write(f'   SBERT Model: {"✅" if system_status["sbert_model"] else "❌"}')
                self.stdout.write(f'   FAISS Index: {"✅" if system_status["faiss_index"] else "❌"}')
                self.stdout.write(f'   Knowledge Entries: {system_status["knowledge_entries"]}')
                self.stdout.write(f'   Gemini Available: {"✅" if system_status["gemini_available"] else "❌"}')
                
            else:
                raise CommandError('❌ Cannot build index: missing model or no data')
                
        except Exception as e:
            duration = time.time() - start_time
            self.stdout.write(
                self.style.ERROR(
                    f'❌ FAISS rebuild failed after {duration:.1f}s: {str(e)}'
                )
            )
            raise CommandError(str(e))