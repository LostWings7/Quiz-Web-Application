"""
Django Management Command: classify_bloom

Batch-classifies existing quiz questions into Bloom's Taxonomy levels using
the local Hugging Face zero-shot classifier (CPU-only, no API keys).
"""

import time
from django.core.management.base import BaseCommand, CommandError

from ai_reports.bloom.constants import DEFAULT_REVIEW_THRESHOLD
from ai_reports.bloom.service import BloomClassificationService
from exam.models import Question, Quiz


class Command(BaseCommand):
    help = "Batch classify quiz questions into Bloom's Taxonomy using local Hugging Face model."

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiz',
            type=int,
            dest='quiz_id',
            help='ID of a specific quiz to classify.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            dest='classify_all',
            help='Process questions across all quizzes.',
        )
        parser.add_argument(
            '--unclassified-only',
            action='store_true',
            default=True,
            dest='unclassified_only',
            help='Only classify questions that do not yet have a bloom_level (default: True).',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            help='Force reclassification and overwrite existing reviewed/manual classifications.',
        )
        parser.add_argument(
            '--threshold',
            type=float,
            default=DEFAULT_REVIEW_THRESHOLD,
            dest='threshold',
            help=f'Confidence threshold below which questions are flagged for review (default: {DEFAULT_REVIEW_THRESHOLD}).',
        )

    def handle(self, *args, **options):
        quiz_id = options.get('quiz_id')
        classify_all = options.get('classify_all')
        unclassified_only = options.get('unclassified_only')
        force = options.get('force')
        threshold = options.get('threshold')

        if not quiz_id and not classify_all:
            self.stdout.write(
                self.style.WARNING(
                    "No target specified. Please provide either --quiz <quiz_id> or --all."
                )
            )
            return

        if quiz_id:
            try:
                quiz = Quiz.objects.get(id=quiz_id)
                questions_qs = Question.objects.filter(quiz=quiz)
                self.stdout.write(self.style.NOTICE(f"Targeting Quiz '{quiz.title}' (ID: {quiz.id}) with {questions_qs.count()} questions."))
            except Quiz.DoesNotExist:
                raise CommandError(f"Quiz with ID {quiz_id} does not exist.")
        else:
            questions_qs = Question.objects.all()
            self.stdout.write(self.style.NOTICE(f"Targeting ALL quizzes ({questions_qs.count()} total questions)."))

        self.stdout.write(self.style.NOTICE(f"Initializing local BloomClassifier (threshold={threshold}, force={force})..."))
        service = BloomClassificationService()

        start_time = time.time()
        try:
            stats = service.batch_classify_questions(
                questions=questions_qs,
                unclassified_only=unclassified_only,
                force=force,
                save=True,
                review_threshold=threshold,
            )
        except Exception as e:
            raise CommandError(f"Classification failed: {e}")

        total_elapsed = time.time() - start_time

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS("Bloom's Taxonomy Classification Summary"))
        self.stdout.write("=" * 50)
        self.stdout.write(f"Total Questions Evaluated : {stats['total_processed']}")
        self.stdout.write(f"Classified & Saved       : {stats['classified']}")
        self.stdout.write(f"Skipped / Already Done   : {stats['skipped']}")
        self.stdout.write(f"Flagged for Review (<{threshold*100:.0f}%) : {stats['needs_review']}")
        self.stdout.write(f"Errors                   : {stats['errors']}")
        self.stdout.write(f"Average Inference Time   : {stats['average_inference_time_ms']} ms/question")
        self.stdout.write(f"Total Elapsed Time       : {total_elapsed:.2f}s")
        self.stdout.write("=" * 50 + "\n")
