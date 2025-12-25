# Generated manually to add mssv field to ChatHistory

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('knowledge', '0004_alter_chathistory_session_title_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='chathistory',
            name='mssv',
            field=models.CharField(
                blank=True,
                help_text='MSSV của sinh viên (nếu là sinh viên)',
                max_length=20,
                null=True,
                verbose_name='Mã số sinh viên'
            ),
        ),
    ]

