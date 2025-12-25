from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import JsonResponse
from django.db.models import Avg
import pandas as pd
import io
from .models import KnowledgeBase, ChatHistory, UserFeedback
from .serializers import KnowledgeBaseSerializer, ChatHistorySerializer
import logging

logger = logging.getLogger(__name__)

class KnowledgeBaseViewSet(viewsets.ModelViewSet):
    queryset = KnowledgeBase.objects.filter(is_active=True)
    serializer_class = KnowledgeBaseSerializer
    
    @action(detail=False, methods=['get'])
    def categories(self, request):
        categories = KnowledgeBase.objects.values_list('category', flat=True).distinct()
        return Response([cat for cat in categories if cat])

class ChatHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ChatHistory.objects.all()  # ← FIX: Thêm queryset
    serializer_class = ChatHistorySerializer
    
    def get_queryset(self):
        session_id = self.request.query_params.get('session_id')
        if session_id:
            return ChatHistory.objects.filter(session_id=session_id)
        return ChatHistory.objects.all()
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        total_chats = ChatHistory.objects.count()
        avg_confidence = ChatHistory.objects.aggregate(
            avg_confidence=Avg('confidence_score')
        )['avg_confidence'] or 0
        
        return Response({
            'total_chats': total_chats,
            'average_confidence': round(avg_confidence, 2)
        })

class UploadCSVView(APIView):
    def post(self, request):
        if 'file' not in request.FILES:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        csv_file = request.FILES['file']
        
        try:
            # Read CSV
            df = pd.read_csv(io.StringIO(csv_file.read().decode('utf-8')))
            
            if 'question' not in df.columns or 'answer' not in df.columns:
                return Response({'error': 'CSV must have "question" and "answer" columns'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            # Create knowledge base entries
            created_count = 0
            for _, row in df.iterrows():
                if pd.notna(row['question']) and pd.notna(row['answer']):
                    KnowledgeBase.objects.create(
                        question=str(row['question']).strip(),
                        answer=str(row['answer']).strip(),
                        category=str(row.get('category', '')).strip() or None
                    )
                    created_count += 1
            
            return Response({
                'message': f'Successfully uploaded {created_count} entries',
                'created_count': created_count
            })
            
        except Exception as e:
            logger.error(f"Error uploading CSV: {str(e)}")
            return Response({'error': f'Error processing CSV: {str(e)}'}, 
                          status=status.HTTP_500_INTERNAL_SERVER_ERROR)
