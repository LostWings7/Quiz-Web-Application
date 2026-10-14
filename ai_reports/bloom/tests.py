"""
Unit and Integration Tests for Bloom's Taxonomy Classification and Analytics.

Covers all 19 test requirements:
1. Valid Bloom levels.
2. Classifier output structure.
3. Scores approximately summing to 1.
4. Confidence extraction.
5. Configurable review threshold.
6. Classification caching / model reuse.
7. Batch classification.
8. Question model Bloom fields.
9. Manual classification.
10. Teacher acceptance of zero-shot suggestion.
11. Teacher override.
12. Existing unclassified questions.
13. Bloom analytics calculations.
14. Empty quiz.
15. Quiz with partially classified questions.
16. Quiz with all four Bloom levels.
17. Main Analytics card data.
18. Expanded Bloom Analytics page.
19. No Gemini / external API calls involved.
"""

from unittest.mock import MagicMock, patch
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from ai_reports.bloom.classifier import BloomClassifier, clean_text_for_classification
from ai_reports.bloom.constants import (
    BLOOM_ANALYZE,
    BLOOM_APPLY,
    BLOOM_CHOICES,
    BLOOM_REMEMBER,
    BLOOM_SOURCE_CHOICES,
    BLOOM_UNDERSTAND,
    CANDIDATE_LABELS,
    CANONICAL_BLOOM_LEVELS,
    DEFAULT_REVIEW_THRESHOLD,
    SOURCE_MANUAL,
    SOURCE_ZERO_SHOT,
)
from ai_reports.bloom.service import BloomAnalyticsService, BloomClassificationService
from exam.models import Question, QuestionOption, Quiz, QuizResult, Subtopic


class MockZeroShotPipeline:
    """Mock pipeline that returns valid NLI distribution for fast unit tests."""

    def __call__(self, texts, candidate_labels=None, hypothesis_template=None, multi_label=False, batch_size=16):
        single = isinstance(texts, str)
        items = [texts] if single else texts

        results = []
        for text in items:
            t = text.lower()
            if "define" in t or "what is" in t or "remember" in t:
                scores = [0.80, 0.10, 0.05, 0.05]
            elif "explain" in t or "why" in t or "understand" in t:
                scores = [0.10, 0.75, 0.10, 0.05]
            elif "calculate" in t or "solve" in t or "apply" in t:
                scores = [0.05, 0.10, 0.75, 0.10]
            elif "analyze" in t or "compare" in t or "trade-off" in t:
                scores = [0.05, 0.10, 0.15, 0.70]
            else:
                # Ambiguous / Low confidence case
                scores = [0.35, 0.30, 0.20, 0.15]

            labels = candidate_labels or CANDIDATE_LABELS
            # Sort labels by score descending
            ranked = sorted(zip(labels, scores), key=lambda x: x[1], reverse=True)
            results.append({
                "sequence": text,
                "labels": [r[0] for r in ranked],
                "scores": [r[1] for r in ranked],
            })

        return results[0] if single else results


class BloomClassifierUnitTests(TestCase):
    """Test suite for BloomClassifier and Zero-Shot Pipeline isolation."""

    def setUp(self):
        BloomClassifier.reset_pipeline()
        self.mock_pipe = MockZeroShotPipeline()

    def tearDown(self):
        BloomClassifier.reset_pipeline()

    @patch('ai_reports.bloom.classifier.BloomClassifier.get_pipeline')
    def test_1_valid_bloom_levels(self, mock_get_pipeline):
        """Test 1: Output level is always one of the 4 canonical Bloom levels."""
        mock_get_pipeline.return_value = self.mock_pipe
        classifier = BloomClassifier()
        res = classifier.classify("What is the definition of momentum?")
        self.assertIn(res["level"], CANONICAL_BLOOM_LEVELS)

    @patch('ai_reports.bloom.classifier.BloomClassifier.get_pipeline')
    def test_2_classifier_output_structure(self, mock_get_pipeline):
        """Test 2: Classifier returns expected schema with all required keys."""
        mock_get_pipeline.return_value = self.mock_pipe
        classifier = BloomClassifier()
        res = classifier.classify("Calculate force given mass and acceleration.")
        self.assertIn("level", res)
        self.assertIn("confidence", res)
        self.assertIn("scores", res)
        self.assertIn("needs_review", res)
        self.assertIsInstance(res["confidence"], float)
        self.assertIsInstance(res["scores"], dict)
        self.assertIsInstance(res["needs_review"], bool)

    @patch('ai_reports.bloom.classifier.BloomClassifier.get_pipeline')
    def test_3_scores_sum_to_approximately_one(self, mock_get_pipeline):
        """Test 3: Probability distribution across all 4 levels sums to ~1.0."""
        mock_get_pipeline.return_value = self.mock_pipe
        classifier = BloomClassifier()
        res = classifier.classify("Explain how photosynthesis converts light energy.")
        total_prob = sum(res["scores"].values())
        self.assertAlmostEqual(total_prob, 1.0, places=2)

    @patch('ai_reports.bloom.classifier.BloomClassifier.get_pipeline')
    def test_4_confidence_extraction(self, mock_get_pipeline):
        """Test 4: Confidence value matches the maximum score in the distribution."""
        mock_get_pipeline.return_value = self.mock_pipe
        classifier = BloomClassifier()
        res = classifier.classify("Define polymorphism.")
        max_score = max(res["scores"].values())
        self.assertEqual(res["confidence"], max_score)
        self.assertEqual(res["scores"][res["level"]], res["confidence"])

    @patch('ai_reports.bloom.classifier.BloomClassifier.get_pipeline')
    def test_5_configurable_review_threshold(self, mock_get_pipeline):
        """Test 5: needs_review flags properly based on configurable threshold."""
        mock_get_pipeline.return_value = self.mock_pipe
        classifier = BloomClassifier(review_threshold=0.45)
        
        # High confidence question (> 0.45)
        res_high = classifier.classify("Define osmosis.")
        self.assertFalse(res_high["needs_review"])

        # Ambiguous question (max confidence 0.35 < 0.45)
        res_ambiguous = classifier.classify("Is green better than blue?")
        self.assertTrue(res_ambiguous["needs_review"])

        # Override threshold on call
        res_custom = classifier.classify("Is green better than blue?", review_threshold=0.30)
        self.assertFalse(res_custom["needs_review"])

    def test_6_classification_caching_and_model_reuse(self):
        """Test 6: BloomClassifier reuses cached pipeline instance without re-instantiation."""
        BloomClassifier.reset_pipeline()
        mock_pipe_instance = MagicMock()
        with patch('ai_reports.bloom.classifier.transformers.pipeline', return_value=mock_pipe_instance) as mock_hf_pipeline:
            pipe1 = BloomClassifier.get_pipeline()
            pipe2 = BloomClassifier.get_pipeline()
            self.assertEqual(pipe1, pipe2)
            self.assertEqual(pipe1, mock_pipe_instance)
            mock_hf_pipeline.assert_called_once()

    @patch('ai_reports.bloom.classifier.BloomClassifier.get_pipeline')
    def test_7_batch_classification(self, mock_get_pipeline):
        """Test 7: Batch classification handles multiple questions efficiently."""
        mock_get_pipeline.return_value = self.mock_pipe
        classifier = BloomClassifier()
        texts = [
            "Define acceleration.",
            "Explain Newton's second law.",
            "Calculate kinetic energy.",
            "Compare bubble sort vs merge sort.",
        ]
        results = classifier.classify_batch(texts)
        self.assertEqual(len(results), 4)
        expected_levels = ["Remember", "Understand", "Apply", "Analyze"]
        for res, expected in zip(results, expected_levels):
            self.assertEqual(res["level"], expected)


class QuestionModelBloomTests(TestCase):
    """Test suite for Question model Bloom fields, manual edits, and overrides."""

    def setUp(self):
        self.quiz = Quiz.objects.create(code="BIO101", title="Biology Midterm")
        self.q1 = Question.objects.create(
            quiz=self.quiz,
            text="Define mitosis and describe its phases.",
            order=1,
            correct_answer="A"
        )
        QuestionOption.objects.create(question=self.q1, label="A", text="Cell division", is_correct=True, order=1)

    def test_8_question_model_bloom_fields(self):
        """Test 8: Question model includes bloom_level, confidence, source, and reviewed fields."""
        self.q1.bloom_level = BLOOM_REMEMBER
        self.q1.bloom_confidence = 0.85
        self.q1.bloom_classification_source = SOURCE_ZERO_SHOT
        self.q1.bloom_reviewed = True
        self.q1.save()

        refreshed = Question.objects.get(id=self.q1.id)
        self.assertEqual(refreshed.bloom_level, 'remember')
        self.assertEqual(refreshed.bloom_confidence, 0.85)
        self.assertEqual(refreshed.bloom_classification_source, 'zero_shot')
        self.assertTrue(refreshed.bloom_reviewed)

    def test_9_manual_classification(self):
        """Test 9: Teacher can manually assign Bloom level."""
        self.q1.bloom_level = BLOOM_APPLY
        self.q1.bloom_classification_source = SOURCE_MANUAL
        self.q1.bloom_reviewed = True
        self.q1.save()

        refreshed = Question.objects.get(id=self.q1.id)
        self.assertEqual(refreshed.bloom_level, 'apply')
        self.assertEqual(refreshed.bloom_classification_source, 'manual')
        self.assertTrue(refreshed.bloom_reviewed)

    def test_10_teacher_acceptance_of_zero_shot_suggestion(self):
        """Test 10: Accepting AI suggestion sets source to zero_shot and reviewed to True."""
        service = BloomClassificationService(classifier=BloomClassifier())
        with patch.object(BloomClassifier, 'get_pipeline', return_value=MockZeroShotPipeline()):
            res = service.classify_question(self.q1, save=True)
            self.q1.refresh_from_db()
            self.assertEqual(self.q1.bloom_classification_source, 'zero_shot')
            self.assertTrue(self.q1.bloom_reviewed)

    def test_11_teacher_override_persists(self):
        """Test 11: Teacher override changes level to manual and prevents automatic overwrite."""
        self.q1.bloom_level = BLOOM_ANALYZE
        self.q1.bloom_classification_source = SOURCE_MANUAL
        self.q1.bloom_reviewed = True
        self.q1.save()

        service = BloomClassificationService(classifier=BloomClassifier())
        with patch.object(BloomClassifier, 'get_pipeline', return_value=MockZeroShotPipeline()):
            # Without force=True, manual classification is preserved
            res = service.classify_question(self.q1, force=False, save=True)
            self.q1.refresh_from_db()
            self.assertEqual(self.q1.bloom_level, 'analyze')
            self.assertEqual(self.q1.bloom_classification_source, 'manual')

    def test_12_existing_unclassified_questions(self):
        """Test 12: Existing unclassified questions have null bloom fields and remain valid."""
        q_old = Question.objects.create(quiz=self.quiz, text="What is gravity?", order=2)
        self.assertIsNone(q_old.bloom_level)
        self.assertIsNone(q_old.bloom_confidence)
        self.assertIsNone(q_old.bloom_classification_source)
        self.assertFalse(q_old.bloom_reviewed)


class BloomAnalyticsServiceTests(TestCase):
    """Test suite for Bloom analytics calculations, empty states, and dashboard integration."""

    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(username="staff", is_staff=True)
        self.client.force_login(self.staff_user)

        self.quiz = Quiz.objects.create(code="PHYS201", title="Physics 101")
        self.student1 = User.objects.create_user(username="student1")
        self.student2 = User.objects.create_user(username="student2")

        # Create 4 questions, one for each Bloom level
        self.q_rem = Question.objects.create(
            quiz=self.quiz, text="Define velocity", order=1,
            bloom_level=BLOOM_REMEMBER, bloom_confidence=0.88,
            bloom_classification_source=SOURCE_ZERO_SHOT, bloom_reviewed=True
        )
        QuestionOption.objects.create(question=self.q_rem, label="A", text="Speed with direction", is_correct=True, order=1)

        self.q_und = Question.objects.create(
            quiz=self.quiz, text="Explain why friction occurs", order=2,
            bloom_level=BLOOM_UNDERSTAND, bloom_confidence=0.79,
            bloom_classification_source=SOURCE_ZERO_SHOT, bloom_reviewed=True
        )
        QuestionOption.objects.create(question=self.q_und, label="A", text="Surface irregularities", is_correct=True, order=1)

        self.q_app = Question.objects.create(
            quiz=self.quiz, text="Calculate force for 10kg at 2 m/s^2", order=3,
            bloom_level=BLOOM_APPLY, bloom_confidence=0.82,
            bloom_classification_source=SOURCE_ZERO_SHOT, bloom_reviewed=True
        )
        QuestionOption.objects.create(question=self.q_app, label="A", text="20N", is_correct=True, order=1)

        self.q_ana = Question.objects.create(
            quiz=self.quiz, text="Analyze the efficiency of two engines", order=4,
            bloom_level=BLOOM_ANALYZE, bloom_confidence=0.75,
            bloom_classification_source=SOURCE_ZERO_SHOT, bloom_reviewed=True
        )
        QuestionOption.objects.create(question=self.q_ana, label="A", text="Engine B has lower heat loss", is_correct=True, order=1)

        # Create student results
        # Student 1 gets all correct
        QuizResult.objects.create(
            quiz=self.quiz, user=self.student1, score=4,
            answers={
                str(self.q_rem.id): "A",
                str(self.q_und.id): "A",
                str(self.q_app.id): "A",
                str(self.q_ana.id): "A",
            }
        )
        # Student 2 gets Remember and Understand right, Apply and Analyze wrong
        QuizResult.objects.create(
            quiz=self.quiz, user=self.student2, score=2,
            answers={
                str(self.q_rem.id): "A",
                str(self.q_und.id): "A",
                str(self.q_app.id): "WRONG",
                str(self.q_ana.id): "WRONG",
            }
        )

    def test_13_bloom_analytics_calculations(self):
        """Test 13: Accurate calculation of question counts, correct/incorrect, accuracy by level."""
        data = BloomAnalyticsService.get_quiz_bloom_analytics(self.quiz)
        stats = data["level_stats"]

        # Remember: 2 attempts, 2 correct -> 100%
        self.assertEqual(stats["Remember"]["correct_responses"], 2)
        self.assertEqual(stats["Remember"]["accuracy"], 100.0)

        # Understand: 2 attempts, 2 correct -> 100%
        self.assertEqual(stats["Understand"]["correct_responses"], 2)
        self.assertEqual(stats["Understand"]["accuracy"], 100.0)

        # Apply: 2 attempts, 1 correct -> 50%
        self.assertEqual(stats["Apply"]["correct_responses"], 1)
        self.assertEqual(stats["Apply"]["accuracy"], 50.0)

        # Analyze: 2 attempts, 1 correct -> 50%
        self.assertEqual(stats["Analyze"]["correct_responses"], 1)
        self.assertEqual(stats["Analyze"]["accuracy"], 50.0)

        # Strongest / Weakest levels
        self.assertIn(data["strongest_level"], ["Remember", "Understand"])
        self.assertIn(data["weakest_level"], ["Apply", "Analyze"])

    def test_14_empty_quiz_analytics(self):
        """Test 14: Handles empty quiz with 0 questions and 0 submissions gracefully."""
        empty_quiz = Quiz.objects.create(code="EMPTY1", title="Empty Quiz")
        data = BloomAnalyticsService.get_quiz_bloom_analytics(empty_quiz)
        self.assertEqual(data["total_questions"], 0)
        self.assertEqual(data["classified_count"], 0)
        self.assertEqual(data["overall_accuracy"], 0.0)
        self.assertEqual(data["strongest_level"], "N/A")
        self.assertEqual(data["weakest_level"], "N/A")

    def test_15_partially_classified_quiz(self):
        """Test 15: Handles quiz where only a subset of questions are classified."""
        partial_quiz = Quiz.objects.create(code="PART1", title="Partial Quiz")
        q1 = Question.objects.create(quiz=partial_quiz, text="Q1", bloom_level=BLOOM_REMEMBER, order=1)
        q2 = Question.objects.create(quiz=partial_quiz, text="Q2", bloom_level=None, order=2)
        data = BloomAnalyticsService.get_quiz_bloom_analytics(partial_quiz)
        self.assertEqual(data["total_questions"], 2)
        self.assertEqual(data["classified_count"], 1)
        self.assertEqual(data["unclassified_count"], 1)
        self.assertEqual(len(data["unclassified_questions"]), 1)

    def test_16_quiz_with_all_four_bloom_levels(self):
        """Test 16: Question distribution covers all 4 Bloom levels."""
        data = BloomAnalyticsService.get_quiz_bloom_analytics(self.quiz)
        counts = data["distribution_counts"]
        for level in CANONICAL_BLOOM_LEVELS:
            self.assertEqual(counts[level], 1)
        self.assertEqual(data["classified_count"], 4)

    def test_17_main_analytics_dashboard_card(self):
        """Test 17: Main analytics dashboard returns 200 and renders Bloom analytics context."""
        url = reverse('dashboard_analytics') + f'?quiz={self.quiz.id}'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bloom's Taxonomy")

    def test_18_expanded_bloom_analytics_page(self):
        """Test 18: Expanded Bloom analytics view returns 200 with full metric breakdown."""
        url = reverse('dashboard_bloom_analytics') + f'?quiz={self.quiz.id}'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bloom's Taxonomy Analysis")
        self.assertContains(response, "Cognitive Performance Trend")

    def test_19_no_gemini_or_external_api_calls(self):
        """Test 19: Verify zero external network calls or Gemini imports in Bloom module."""
        import ai_reports.bloom.classifier as b_classifier
        import ai_reports.bloom.service as b_service
        
        # Verify no google/gemini imports in bloom code
        classifier_src = open(b_classifier.__file__).read()
        service_src = open(b_service.__file__).read()
        self.assertNotIn("google.genai", classifier_src)
        self.assertNotIn("gemini", classifier_src.lower())
        self.assertNotIn("google.genai", service_src)
        self.assertNotIn("gemini", service_src.lower())

    @patch('ai_reports.bloom.classifier.BloomClassifier.get_pipeline')
    def test_20_bulk_classify_preview_and_save_ajax(self, mock_get_pipeline):
        """Test 20: Verify batch preview and batch save AJAX endpoints for questions page."""
        mock_pipe = MagicMock()
        mock_pipe.return_value = [
            {"labels": ["recall, define, or list facts"], "scores": [0.88, 0.06, 0.04, 0.02]},
            {"labels": ["solve, apply, or demonstrate a method"], "scores": [0.82, 0.10, 0.05, 0.03]}
        ]
        mock_get_pipeline.return_value = mock_pipe

        # Create unclassified questions
        q1 = Question.objects.create(quiz=self.quiz, text="What is atom?")
        q2 = Question.objects.create(quiz=self.quiz, text="Calculate energy.")

        # Test preview endpoint
        preview_url = reverse('dashboard_quiz_classify_bloom_batch_preview', kwargs={'quiz_id': self.quiz.id})
        response = self.client.get(preview_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["unclassified_count"], 2)
        self.assertEqual(len(data["questions"]), 2)

        # Test save endpoint
        save_url = reverse('dashboard_quiz_save_bloom_batch', kwargs={'quiz_id': self.quiz.id})
        payload = {
            "classifications": [
                {"id": q1.id, "level": "remember", "confidence": 0.88, "source": "zero_shot", "reviewed": True},
                {"id": q2.id, "level": "apply", "confidence": 0.82, "source": "manual", "reviewed": True},
            ]
        }
        import json
        save_resp = self.client.post(save_url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(save_resp.status_code, 200)
        self.assertTrue(save_resp.json()["success"])

        # Check DB update
        q1.refresh_from_db()
        q2.refresh_from_db()
        self.assertEqual(q1.bloom_level, "remember")
        self.assertEqual(q1.bloom_classification_source, "zero_shot")
        self.assertEqual(q2.bloom_level, "apply")
        self.assertEqual(q2.bloom_classification_source, "manual")
        self.assertTrue(q1.bloom_reviewed)
        self.assertTrue(q2.bloom_reviewed)

    def test_21_confirmed_taxonomy_does_not_need_review(self):
        """Test 21: Once a teacher confirms a taxonomy (bloom_reviewed=True), it is not flagged as needing review even if confidence is low."""
        quiz = Quiz.objects.create(code="CONFIRM1", title="Confirmed Quiz")

        # Question confirmed by teacher with low confidence
        q_confirmed = Question.objects.create(
            quiz=quiz, text="Q confirmed", order=1,
            bloom_level=BLOOM_APPLY, bloom_confidence=0.30,
            bloom_classification_source=SOURCE_ZERO_SHOT, bloom_reviewed=True
        )
        # Question not yet reviewed by teacher with low confidence
        q_unreviewed = Question.objects.create(
            quiz=quiz, text="Q unreviewed", order=2,
            bloom_level=BLOOM_UNDERSTAND, bloom_confidence=0.30,
            bloom_classification_source=SOURCE_ZERO_SHOT, bloom_reviewed=False
        )

        data = BloomAnalyticsService.get_quiz_bloom_analytics(quiz)

        # Total needing review should only be 1 (the unreviewed one), not the confirmed one
        self.assertEqual(data["needs_review_count"], 1)

        apply_qs = data["questions_by_level"]["Apply"]
        understand_qs = data["questions_by_level"]["Understand"]

        self.assertFalse(apply_qs[0]["needs_review"])
        self.assertTrue(apply_qs[0]["bloom_reviewed"])

        self.assertTrue(understand_qs[0]["needs_review"])
        self.assertFalse(understand_qs[0]["bloom_reviewed"])

    def test_22_bulk_import_with_mapped_bloom_level(self):
        """Test 22: Verify that questions imported via bulk import with a mapped bloom_level column are correctly stored."""
        quiz = Quiz.objects.create(code="BULK1", title="Bulk Import Quiz")
        session = self.client.session
        session['question_import_payload'] = {
            'quiz_id': quiz.id,
            'has_header': True,
            'rows': [
                ['order', 'text', 'opt1', 'opt2', 'correct', 'bloom'],
                ['1', 'What is RAM?', 'Memory', 'Storage', '1', 'Remember'],
                ['2', 'Analyze this algorithm complexity.', 'O(n)', 'O(1)', '1', 'Analyze'],
            ],
            'highlighted': [],
            'supports_color': False,
            'filename': 'questions.csv',
            'extracted_images': {},
        }
        session.save()

        import_url = reverse('dashboard_question_import')
        post_data = {
            'action': 'import',
            'map_order': '0',
            'map_text': '1',
            'map_option_0': '2',
            'map_option_1': '3',
            'map_correct_option': '4',
            'map_bloom_level': '5',
        }
        response = self.client.post(import_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        questions = list(Question.objects.filter(quiz=quiz).order_by('order'))
        self.assertEqual(len(questions), 2)

        self.assertEqual(questions[0].bloom_level, 'remember')
        self.assertEqual(questions[0].bloom_confidence, 1.0)
        self.assertEqual(questions[0].bloom_classification_source, SOURCE_MANUAL)
        self.assertTrue(questions[0].bloom_reviewed)

        self.assertEqual(questions[1].bloom_level, 'analyze')
        self.assertEqual(questions[1].bloom_confidence, 1.0)
        self.assertEqual(questions[1].bloom_classification_source, SOURCE_MANUAL)
        self.assertTrue(questions[1].bloom_reviewed)

    def test_23_bulk_import_with_default_bloom_level(self):
        """Test 23: Verify that questions imported with a default bloom level fallback receive that classification."""
        quiz = Quiz.objects.create(code="BULK2", title="Bulk Default Quiz")
        session = self.client.session
        session['question_import_payload'] = {
            'quiz_id': quiz.id,
            'has_header': True,
            'rows': [
                ['order', 'text', 'opt1', 'opt2', 'correct'],
                ['1', 'Apply Newton second law.', 'F=ma', 'E=mc2', '1'],
            ],
            'highlighted': [],
            'supports_color': False,
            'filename': 'questions.csv',
            'extracted_images': {},
        }
        session.save()

        import_url = reverse('dashboard_question_import')
        post_data = {
            'action': 'import',
            'map_order': '0',
            'map_text': '1',
            'map_option_0': '2',
            'map_option_1': '3',
            'map_correct_option': '4',
            'map_bloom_level': '',
            'default_bloom_level': 'apply',
        }
        response = self.client.post(import_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        q = Question.objects.get(quiz=quiz, text='Apply Newton second law.')
        self.assertEqual(q.bloom_level, 'apply')
        self.assertEqual(q.bloom_classification_source, SOURCE_MANUAL)
        self.assertTrue(q.bloom_reviewed)

    def test_24_bulk_import_with_auto_classify_bloom(self):
        """Test 24: Verify that questions imported with auto_classify_bloom=1 trigger zero-shot auto-classification."""
        quiz = Quiz.objects.create(code="BULK3", title="Bulk AI Quiz")
        session = self.client.session
        session['question_import_payload'] = {
            'quiz_id': quiz.id,
            'has_header': True,
            'rows': [
                ['order', 'text', 'opt1', 'opt2', 'correct'],
                ['1', 'Explain the greenhouse effect.', 'Warming', 'Cooling', '1'],
            ],
            'highlighted': [],
            'supports_color': False,
            'filename': 'questions.csv',
            'extracted_images': {},
        }
        session.save()

        import_url = reverse('dashboard_question_import')
        post_data = {
            'action': 'import',
            'map_order': '0',
            'map_text': '1',
            'map_option_0': '2',
            'map_option_1': '3',
            'map_correct_option': '4',
            'auto_classify_bloom': '1',
        }

        with patch('ai_reports.bloom.service.BloomClassificationService.batch_classify_questions') as mock_batch:
            mock_batch.return_value = {'total_processed': 1, 'classified': 1, 'needs_review': 0}
            response = self.client.post(import_url, data=post_data)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(mock_batch.called)

    def test_25_sample_template_includes_bloom_level(self):
        """Test 25: Verify that the sample import CSV template includes bloom_level column."""
        sample_url = reverse('dashboard_question_import_sample')
        response = self.client.get(sample_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('bloom_level', content)
        self.assertIn('Remember', content)



