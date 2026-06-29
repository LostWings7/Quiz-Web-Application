import django.db.models.deletion
from django.db import migrations, models


def copy_legacy_options(apps, schema_editor):
    Question = apps.get_model('exam', 'Question')
    QuestionOption = apps.get_model('exam', 'QuestionOption')

    for question in Question.objects.all():
        if QuestionOption.objects.filter(question=question).exists():
            continue

        legacy_options = [
            ('A', question.option_a),
            ('B', question.option_b),
            ('C', question.option_c),
            ('D', question.option_d),
        ]
        created_options = []
        for index, (label, text) in enumerate(legacy_options):
            if not text:
                continue
            created_options.append(
                QuestionOption.objects.create(
                    question=question,
                    label=label,
                    text=text,
                    is_correct=question.correct_answer == label,
                    order=index,
                )
            )

        if created_options and not any(option.is_correct for option in created_options):
            created_options[0].is_correct = True
            created_options[0].save(update_fields=['is_correct'])

        correct = next((option for option in created_options if option.is_correct), None)
        if correct:
            question.correct_answer = str(correct.id)
            question.save(update_fields=['correct_answer'])


class Migration(migrations.Migration):

    dependencies = [
        ('exam', '0004_alter_question_quiz'),
    ]

    operations = [
        migrations.AlterField(
            model_name='question',
            name='correct_answer',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AlterField(
            model_name='question',
            name='option_a',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='question',
            name='option_b',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='question',
            name='option_c',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='question',
            name='option_d',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterUniqueTogether(
            name='quizresult',
            unique_together={('quiz', 'user')},
        ),
        migrations.CreateModel(
            name='QuestionOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField()),
                ('label', models.CharField(blank=True, max_length=8)),
                ('is_correct', models.BooleanField(default=False)),
                ('order', models.PositiveIntegerField(default=0)),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='options', to='exam.question')),
            ],
            options={
                'ordering': ['order', 'id'],
            },
        ),
        migrations.RunPython(copy_legacy_options, migrations.RunPython.noop),
    ]
