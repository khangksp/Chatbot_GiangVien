from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings

class Migration(migrations.Migration):
    
    dependencies = [
        ('knowledge', '0002_chathistory_entities_chathistory_intent_and_more'),
        ('authentication', '0002_add_personalization_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='chathistory',
            name='user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='chat_history',
                to='authentication.faculty'
            ),
        ),
        migrations.AddField(
            model_name='chathistory',
            name='session_title',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        # Thêm database indexes để tối ưu performance
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_chathistory_user_session ON chat_history (user_id, session_id);",
            reverse_sql="DROP INDEX IF EXISTS idx_chathistory_user_session;"
        ),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_chathistory_user_timestamp ON chat_history (user_id, timestamp DESC);",
            reverse_sql="DROP INDEX IF EXISTS idx_chathistory_user_timestamp;"
        ),
    ]