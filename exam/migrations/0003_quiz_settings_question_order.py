import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exam', '0002_quizresult_answers'),
    ]

    operations = [
        migrations.AddField(
            model_name='quiz',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='quiz',
            name='duration_minutes',
            field=models.PositiveIntegerField(default=30),
        ),
        migrations.AddField(
            model_name='quiz',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='quiz',
            name='randomize_questions',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='quiz',
            name='timer_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='question',
            name='order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name='question',
            options={'ordering': ['order', 'id']},
        ),
    ]
