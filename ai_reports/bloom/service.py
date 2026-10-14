"""
Bloom's Taxonomy Classification and Analytics Services.

Provides:
1. BloomClassificationService: Manages zero-shot classification and persistence for Question models.
2. BloomAnalyticsService: Calculates deterministic Bloom's taxonomy performance, distributions,
   and cognitive trends from existing QuizResult records without model re-inference.
"""

import html
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from django.db.models import QuerySet

from .classifier import BloomClassifier
from .constants import (
    BLOOM_CHOICES,
    CANONICAL_BLOOM_LEVELS,
    DB_TO_DISPLAY_MAP,
    DEFAULT_REVIEW_THRESHOLD,
    DISPLAY_TO_DB_MAP,
    SOURCE_MANUAL,
    SOURCE_ZERO_SHOT,
)

logger = logging.getLogger(__name__)


def answer_is_correct(question, answer) -> bool:
    """
    Evaluates whether a given answer is correct for the specified question.
    Reuses the existing quiz answer evaluation logic.
    """
    if not answer:
        return False
    correct = question.options.filter(is_correct=True).first()
    if correct:
        return str(answer) in {str(correct.id), str(correct.label)}
    return str(answer) == str(question.correct_answer)


class BloomClassificationService:
    """
    Service for running local zero-shot classification on Question instances.
    """

    def __init__(self, classifier: Optional[BloomClassifier] = None):
        self.classifier = classifier or BloomClassifier()

    def classify_text(self, text: str, review_threshold: float = DEFAULT_REVIEW_THRESHOLD) -> Dict[str, Any]:
        """
        Classify raw question text directly.
        """
        return self.classifier.classify(text, review_threshold=review_threshold)

    def classify_question(
        self,
        question,
        force: bool = False,
        save: bool = False,
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    ) -> Dict[str, Any]:
        """
        Classify a single Question instance.
        
        :param question: exam.models.Question instance.
        :param force: If True, overwrites existing manual/reviewed classifications.
        :param save: If True, updates question fields in database.
        :param review_threshold: Confidence review threshold.
        :return: Classification result dict.
        """
        # If question has already been reviewed manually and force is False, skip
        if getattr(question, 'bloom_reviewed', False) and getattr(question, 'bloom_classification_source', None) == SOURCE_MANUAL and not force:
            db_level = getattr(question, 'bloom_level', None)
            display_level = DB_TO_DISPLAY_MAP.get(db_level, 'Remember')
            conf = getattr(question, 'bloom_confidence', 1.0) or 1.0
            return {
                "level": display_level,
                "confidence": conf,
                "scores": {display_level: conf},
                "needs_review": False,
                "skipped": True,
            }

        res = self.classifier.classify(question.text, review_threshold=review_threshold)
        db_level = DISPLAY_TO_DB_MAP.get(res["level"])

        if save:
            question.bloom_level = db_level
            question.bloom_confidence = res["confidence"]
            question.bloom_classification_source = SOURCE_ZERO_SHOT
            # If confidence meets threshold, it is considered auto-classified; teacher review is optional
            question.bloom_reviewed = not res["needs_review"]
            question.save(update_fields=[
                'bloom_level',
                'bloom_confidence',
                'bloom_classification_source',
                'bloom_reviewed',
            ])

        return res

    def batch_classify_questions(
        self,
        questions: QuerySet,
        unclassified_only: bool = True,
        force: bool = False,
        save: bool = True,
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    ) -> Dict[str, Any]:
        """
        Batch classify a QuerySet of Question instances.
        
        :param questions: QuerySet of Question objects.
        :param unclassified_only: Only process questions without a bloom_level.
        :param force: Overwrite manually reviewed questions if True.
        :param save: Save updates to database.
        :param review_threshold: Review threshold.
        :return: Summary dictionary with statistics and timings.
        """
        target_qs = questions
        if unclassified_only and not force:
            target_qs = target_qs.filter(bloom_level__isnull=True)
        elif not force:
            # Exclude manual reviews unless force is specified
            target_qs = target_qs.exclude(bloom_classification_source=SOURCE_MANUAL, bloom_reviewed=True)

        question_list = list(target_qs)
        total_count = len(question_list)

        if total_count == 0:
            return {
                "total_processed": 0,
                "classified": 0,
                "skipped": questions.count(),
                "needs_review": 0,
                "errors": 0,
                "average_inference_time_ms": 0.0,
                "total_time_seconds": 0.0,
            }

        texts = [q.text for q in question_list]
        start_time = time.time()

        results = self.classifier.classify_batch(texts, review_threshold=review_threshold)
        elapsed_time = time.time() - start_time

        classified_count = 0
        needs_review_count = 0
        updated_questions = []

        for q, res in zip(question_list, results):
            db_level = DISPLAY_TO_DB_MAP.get(res["level"])
            q.bloom_level = db_level
            q.bloom_confidence = res["confidence"]
            q.bloom_classification_source = SOURCE_ZERO_SHOT
            q.bloom_reviewed = not res["needs_review"]
            classified_count += 1
            if res["needs_review"]:
                needs_review_count += 1
            updated_questions.append(q)

        if save and updated_questions:
            from exam.models import Question
            Question.objects.bulk_update(
                updated_questions,
                ['bloom_level', 'bloom_confidence', 'bloom_classification_source', 'bloom_reviewed']
            )

        avg_time_ms = (elapsed_time / total_count * 1000) if total_count > 0 else 0.0

        return {
            "total_processed": total_count,
            "classified": classified_count,
            "skipped": max(0, questions.count() - total_count),
            "needs_review": needs_review_count,
            "errors": 0,
            "average_inference_time_ms": round(avg_time_ms, 2),
            "total_time_seconds": round(elapsed_time, 2),
        }


class BloomAnalyticsService:
    """
    Deterministic analytics calculator for Bloom's Taxonomy.
    Reads persisted question.bloom_level values and computes statistics from QuizResults.
    Never calls the AI classifier.
    """

    @classmethod
    def get_quiz_bloom_analytics(cls, quiz, results=None) -> Dict[str, Any]:
        """
        Compute full Bloom's Taxonomy analytics for a given quiz.
        
        :param quiz: Quiz model instance.
        :param results: Optional pre-queried QuizResult queryset.
        :return: Dictionary containing distributions, performance metrics, cognitive trend, and question breakdowns.
        """
        if results is None:
            results = quiz.quizresult_set.all().select_related('user')
        
        results_list = list(results)
        total_attempts = len(results_list)

        # Questions for this quiz with options prefetched
        questions = list(quiz.questions.all().prefetch_related('options', 'subtopic'))
        total_questions = len(questions)

        # 1. Distribution
        level_counts = {level: 0 for level in CANONICAL_BLOOM_LEVELS}
        unclassified_count = 0
        needs_review_count = 0

        for q in questions:
            display_level = DB_TO_DISPLAY_MAP.get(q.bloom_level)
            if display_level:
                level_counts[display_level] += 1
            else:
                unclassified_count += 1
            
            # Check review status: once a teacher confirms the taxonomy (bloom_reviewed=True), it no longer needs review
            if q.bloom_level and not q.bloom_reviewed:
                needs_review_count += 1

        classified_count = total_questions - unclassified_count
        distribution_percentages = {
            level: round((count / total_questions * 100), 1) if total_questions > 0 else 0.0
            for level, count in level_counts.items()
        }

        # 2. Performance by Bloom Level
        level_stats = {
            level: {
                "question_count": level_counts[level],
                "total_responses": 0,
                "correct_responses": 0,
                "incorrect_responses": 0,
                "accuracy": 0.0,
            }
            for level in CANONICAL_BLOOM_LEVELS
        }

        # Per-question accuracy and option breakdown
        question_details_by_level = {level: [] for level in CANONICAL_BLOOM_LEVELS}
        unclassified_question_details = []

        total_classified_correct = 0
        total_classified_responses = 0

        for idx, question in enumerate(questions, 1):
            total_q_attempts = total_attempts
            correct_count = sum(
                1 for r in results_list if answer_is_correct(question, r.answers.get(str(question.id)))
            )
            incorrect_count = total_q_attempts - correct_count
            accuracy = round((correct_count * 100 / total_q_attempts), 1) if total_q_attempts > 0 else 0.0
            difficulty = round(100.0 - accuracy, 1)

            # Option breakdown
            opts_counts = {str(opt.id): 0 for opt in question.options.all()}
            for opt in question.options.all():
                if opt.label:
                    opts_counts[opt.label] = 0

            for r in results_list:
                ans = r.answers.get(str(question.id))
                if ans:
                    opts_counts[str(ans)] = opts_counts.get(str(ans), 0) + 1

            opts_stats = []
            for opt in question.options.all():
                c = opts_counts.get(str(opt.id), 0) + opts_counts.get(opt.label, 0)
                pct = round(c * 100 / total_q_attempts, 1) if total_q_attempts > 0 else 0.0
                opts_stats.append({
                    'text': html.unescape(opt.text),
                    'is_correct': opt.is_correct,
                    'count': c,
                    'percentage': pct,
                })

            q_data = {
                'id': question.id,
                'order': idx,
                'text': html.unescape(question.text),
                'raw_text': question.text,
                'accuracy': accuracy,
                'difficulty': difficulty,
                'subtopic': question.subtopic.name if question.subtopic else 'General',
                'bloom_level': DB_TO_DISPLAY_MAP.get(question.bloom_level, 'Unclassified'),
                'bloom_confidence': round(question.bloom_confidence * 100, 1) if question.bloom_confidence else None,
                'bloom_classification_source': question.get_bloom_classification_source_display() if question.bloom_classification_source else 'None',
                'bloom_reviewed': question.bloom_reviewed,
                'needs_review': bool(question.bloom_level and not question.bloom_reviewed),
                'options': opts_stats,
            }

            display_level = DB_TO_DISPLAY_MAP.get(question.bloom_level)
            if display_level:
                question_details_by_level[display_level].append(q_data)
                stat = level_stats[display_level]
                stat["total_responses"] += total_q_attempts
                stat["correct_responses"] += correct_count
                stat["incorrect_responses"] += incorrect_count
                total_classified_correct += correct_count
                total_classified_responses += total_q_attempts
            else:
                unclassified_question_details.append(q_data)

        # Calculate final level accuracies
        for level, stat in level_stats.items():
            if stat["total_responses"] > 0:
                stat["accuracy"] = round(stat["correct_responses"] * 100 / stat["total_responses"], 1)
            else:
                stat["accuracy"] = 0.0

        # Overall Bloom accuracy
        overall_bloom_accuracy = (
            round(total_classified_correct * 100 / total_classified_responses, 1)
            if total_classified_responses > 0 else 0.0
        )

        # 3. Strongest & Weakest Bloom Level (only consider levels with >= 1 question)
        active_levels = [
            (level, level_stats[level]["accuracy"])
            for level in CANONICAL_BLOOM_LEVELS
            if level_stats[level]["question_count"] > 0
        ]

        all_tied = False
        if active_levels and total_attempts > 0:
            accuracies = [x[1] for x in active_levels]
            all_tied = len(set(accuracies)) == 1
            if all_tied:
                if accuracies[0] == 0:
                    strongest_level = "Tied (0.0%)"
                    weakest_level = "Tied (0.0%)"
                else:
                    strongest_level = f"Tied ({accuracies[0]}%)"
                    weakest_level = f"Tied ({accuracies[0]}%)"
            else:
                strongest_level = max(active_levels, key=lambda x: x[1])[0]
                weakest_level = min(active_levels, key=lambda x: x[1])[0]
        else:
            strongest_level = "N/A"
            weakest_level = "N/A"

        # 4. Cognitive Performance Trend: Remember -> Understand -> Apply -> Analyze
        trend_values = [level_stats[level]["accuracy"] for level in CANONICAL_BLOOM_LEVELS]
        rem_acc = level_stats["Remember"]["accuracy"]
        ana_acc = level_stats["Analyze"]["accuracy"]
        trend_delta = round(ana_acc - rem_acc, 1)

        # 5. Review Queue
        review_queue = [
            q for q in (unclassified_question_details + [
                q for group in question_details_by_level.values() for q in group if q['needs_review']
            ])
        ]

        # 6. Structured Factual Summary
        factual_insights = {
            "strongest_level": strongest_level,
            "strongest_accuracy": level_stats[strongest_level]["accuracy"] if strongest_level in level_stats else (accuracies[0] if (active_levels and all_tied) else 0.0),
            "weakest_level": weakest_level,
            "weakest_accuracy": level_stats[weakest_level]["accuracy"] if weakest_level in level_stats else (accuracies[0] if (active_levels and all_tied) else 0.0),
            "overall_accuracy": overall_bloom_accuracy,
            "trend_start": rem_acc,
            "trend_end": ana_acc,
            "trend_delta": trend_delta,
            "distribution_percentages": distribution_percentages,
        }

        return {
            "quiz": quiz,
            "total_questions": total_questions,
            "classified_count": classified_count,
            "unclassified_count": unclassified_count,
            "needs_review_count": needs_review_count,
            "overall_accuracy": overall_bloom_accuracy,
            "strongest_level": strongest_level,
            "weakest_level": weakest_level,
            "distribution_counts": level_counts,
            "distribution_percentages": distribution_percentages,
            "level_stats": level_stats,
            "trend_values": trend_values,
            "trend_delta": trend_delta,
            "questions_by_level": question_details_by_level,
            "unclassified_questions": unclassified_question_details,
            "review_queue": review_queue,
            "factual_insights": factual_insights,
            "chart_data": {
                "barLabels": CANONICAL_BLOOM_LEVELS,
                "barValues": [level_stats[l]["accuracy"] for l in CANONICAL_BLOOM_LEVELS],
                "doughnutLabels": CANONICAL_BLOOM_LEVELS,
                "doughnutValues": [level_counts[l] for l in CANONICAL_BLOOM_LEVELS],
            }
        }
