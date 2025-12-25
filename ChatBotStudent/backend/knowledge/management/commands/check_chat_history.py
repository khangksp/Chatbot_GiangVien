"""
Django management command to check chat history in database.
Usage: python manage.py check_chat_history [options]
"""
from django.core.management.base import BaseCommand
from knowledge.models import ChatHistory
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Check chat history records in database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=10,
            help='Number of recent records to show (default: 10)'
        )
        parser.add_argument(
            '--session-id',
            type=str,
            help='Filter by session_id'
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Filter by user (faculty_code)'
        )
        parser.add_argument(
            '--last-hours',
            type=int,
            help='Show records from last N hours'
        )
        parser.add_argument(
            '--count-only',
            action='store_true',
            help='Show only count of records'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        session_id = options.get('session_id')
        user_filter = options.get('user')
        last_hours = options.get('last_hours')
        count_only = options['count_only']

        # Build query
        queryset = ChatHistory.objects.all()

        # Filter by session_id
        if session_id:
            queryset = queryset.filter(session_id=session_id)
            self.stdout.write(self.style.SUCCESS(f'Filtering by session_id: {session_id}'))

        # Filter by user
        if user_filter:
            queryset = queryset.filter(user__faculty_code=user_filter)
            self.stdout.write(self.style.SUCCESS(f'Filtering by user: {user_filter}'))

        # Filter by time
        if last_hours:
            time_threshold = timezone.now() - timedelta(hours=last_hours)
            queryset = queryset.filter(timestamp__gte=time_threshold)
            self.stdout.write(self.style.SUCCESS(f'Filtering by last {last_hours} hours'))

        # Get count
        total_count = queryset.count()

        if count_only:
            self.stdout.write(self.style.SUCCESS(f'\nTotal chat history records: {total_count}'))
            return

        # Order by timestamp descending
        queryset = queryset.order_by('-timestamp')[:limit]

        self.stdout.write(self.style.SUCCESS(f'\n=== Chat History Records (showing {min(limit, total_count)} of {total_count} total) ===\n'))

        if not queryset.exists():
            self.stdout.write(self.style.WARNING('No records found.'))
            return

        for idx, record in enumerate(queryset, 1):
            self.stdout.write(self.style.SUCCESS(f'\n--- Record #{idx} ---'))
            self.stdout.write(f'ID: {record.id}')
            self.stdout.write(f'Session ID: {record.session_id}')
            self.stdout.write(f'User: {record.user.faculty_code if record.user else "Anonymous/Student"}')
            self.stdout.write(f'Timestamp: {record.timestamp}')
            self.stdout.write(f'User Message: {record.user_message[:100]}{"..." if len(record.user_message) > 100 else ""}')
            self.stdout.write(f'Bot Response: {record.bot_response[:100]}{"..." if len(record.bot_response) > 100 else ""}')
            self.stdout.write(f'Confidence: {record.confidence_score:.2f}')
            self.stdout.write(f'Response Time: {record.response_time:.3f}s')
            self.stdout.write(f'Method: {record.method or "N/A"}')
            self.stdout.write(f'Strategy: {record.strategy or "N/A"}')
            self.stdout.write(f'Intent: {record.intent or "N/A"}')

        self.stdout.write(self.style.SUCCESS(f'\n=== End of Records ===\n'))

