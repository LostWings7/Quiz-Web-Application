"""
Bloom's Taxonomy Analytics Services and Constants for the Exam application.

Provides deterministic Bloom's taxonomy performance metrics, distributions,
and cognitive progression analytics directly from database records without any AI dependencies.
"""

import html
from collections import defaultdict
from typing import Any, Dict, List, Optional

# Canonical 4 Bloom's Levels (DB value -> Display Label)
BLOOM_REMEMBER = 'remember'
BLOOM_UNDERSTAND = 'understand'
BLOOM_APPLY = 'apply'
BLOOM_ANALYZE = 'analyze'

BLOOM_CHOICES = [
    (BLOOM_REMEMBER, 'Remember'),
    (BLOOM_UNDERSTAND, 'Understand'),
    (BLOOM_APPLY, 'Apply'),
    (BLOOM_ANALYZE, 'Analyze'),
]

# Display names (Title-cased canonical names)
CANONICAL_BLOOM_LEVELS = ['Remember', 'Understand', 'Apply', 'Analyze']

# Map from lowercase DB value to Title-case display name
DB_TO_DISPLAY_MAP = {
    BLOOM_REMEMBER: 'Remember',
    BLOOM_UNDERSTAND: 'Understand',
    BLOOM_APPLY: 'Apply',
    BLOOM_ANALYZE: 'Analyze',
}

# Map from Title-case display name to lowercase DB value
DISPLAY_TO_DB_MAP = {
    'Remember': BLOOM_REMEMBER,
    'Understand': BLOOM_UNDERSTAND,
    'Apply': BLOOM_APPLY,
    'Analyze': BLOOM_ANALYZE,
}

# Classification Sources
SOURCE_MANUAL = 'manual'
SOURCE_ZERO_SHOT = 'zero_shot'

BLOOM_SOURCE_CHOICES = [
    (SOURCE_MANUAL, 'Manual'),
    (SOURCE_ZERO_SHOT, 'Zero-shot'),
]

DEFAULT_REVIEW_THRESHOLD = 0.45


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


class BloomAnalyticsService:
    """
    Deterministic analytics calculator for Bloom's Taxonomy.
    Reads persisted question.bloom_level values and computes statistics from QuizResults.
    Requires no external AI packages or models.
    """

    @classmethod
    def get_quiz_bloom_analytics(cls, quiz, results=None) -> Dict[str, Any]:
        """
        Compute full Bloom's Taxonomy analytics for a given quiz.
        """
        if results is None:
            results = quiz.quizresult_set.all().select_related('user')
        
        results_list = list(results)
        total_attempts = len(results_list)

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
                'question_count': level_counts[level],
                'total_responses': 0,
                'correct_responses': 0,
                'incorrect_responses': 0,
                'accuracy': 0.0,
            }
            for level in CANONICAL_BLOOM_LEVELS
        }

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
                stat['total_responses'] += total_q_attempts
                stat['correct_responses'] += correct_count
                stat['incorrect_responses'] += incorrect_count
                total_classified_correct += correct_count
                total_classified_responses += total_q_attempts
            else:
                unclassified_question_details.append(q_data)

        for level, stat in level_stats.items():
            if stat['total_responses'] > 0:
                stat['accuracy'] = round(stat['correct_responses'] * 100 / stat['total_responses'], 1)
            else:
                stat['accuracy'] = 0.0

        overall_bloom_accuracy = (
            round(total_classified_correct * 100 / total_classified_responses, 1)
            if total_classified_responses > 0 else 0.0
        )

        active_levels = [
            (level, level_stats[level]['accuracy'])
            for level in CANONICAL_BLOOM_LEVELS
            if level_stats[level]['question_count'] > 0
        ]

        all_tied = False
        if active_levels and total_attempts > 0:
            accuracies = [x[1] for x in active_levels]
            all_tied = len(set(accuracies)) == 1
            if all_tied:
                if accuracies[0] == 0:
                    strongest_level = 'Tied (0.0%)'
                    weakest_level = 'Tied (0.0%)'
                else:
                    strongest_level = f'Tied ({accuracies[0]}%)'
                    weakest_level = f'Tied ({accuracies[0]}%)'
            else:
                strongest_level = max(active_levels, key=lambda x: x[1])[0]
                weakest_level = min(active_levels, key=lambda x: x[1])[0]
        else:
            strongest_level = 'N/A'
            weakest_level = 'N/A'

        trend_values = [level_stats[level]['accuracy'] for level in CANONICAL_BLOOM_LEVELS]
        rem_acc = level_stats['Remember']['accuracy']
        ana_acc = level_stats['Analyze']['accuracy']
        trend_delta = round(ana_acc - rem_acc, 1)

        review_queue = [
            q for q in (unclassified_question_details + [
                q for group in question_details_by_level.values() for q in group if q['needs_review']
            ])
        ]

        factual_insights = {
            'strongest_level': strongest_level,
            'strongest_accuracy': level_stats[strongest_level]['accuracy'] if strongest_level in level_stats else (accuracies[0] if (active_levels and all_tied) else 0.0),
            'weakest_level': weakest_level,
            'weakest_accuracy': level_stats[weakest_level]['accuracy'] if weakest_level in level_stats else (accuracies[0] if (active_levels and all_tied) else 0.0),
            'overall_accuracy': overall_bloom_accuracy,
            'trend_start': rem_acc,
            'trend_end': ana_acc,
            'trend_delta': trend_delta,
            'distribution_percentages': distribution_percentages,
        }

        return {
            'quiz': quiz,
            'total_questions': total_questions,
            'classified_count': classified_count,
            'unclassified_count': unclassified_count,
            'needs_review_count': needs_review_count,
            'overall_accuracy': overall_bloom_accuracy,
            'strongest_level': strongest_level,
            'weakest_level': weakest_level,
            'distribution_counts': level_counts,
            'distribution_percentages': distribution_percentages,
            'level_stats': level_stats,
            'trend_values': trend_values,
            'trend_delta': trend_delta,
            'questions_by_level': question_details_by_level,
            'unclassified_questions': unclassified_question_details,
            'review_queue': review_queue,
            'factual_insights': factual_insights,
            'chart_data': {
                'barLabels': CANONICAL_BLOOM_LEVELS,
                'barValues': [level_stats[l]['accuracy'] for l in CANONICAL_BLOOM_LEVELS],
                'doughnutLabels': CANONICAL_BLOOM_LEVELS,
                'doughnutValues': [level_counts[l] for l in CANONICAL_BLOOM_LEVELS],
            }
        }
