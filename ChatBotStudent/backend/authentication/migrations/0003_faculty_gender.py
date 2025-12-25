from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0002_add_personalization_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='faculty',
            name='gender',
            field=models.CharField(blank=True, choices=[('male', 'Nam'), ('female', 'Nữ'), ('other', 'Khác')], default='other', help_text='Giới tính để xác định cách xưng hô (thầy/cô)', max_length=10, verbose_name='Giới tính'),
        ),
    ]
