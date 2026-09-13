import os
from django.conf import settings
from django.contrib.auth.models import User
from django.template.loader import get_template
from django.test import Client, TestCase
from django.urls import reverse

from exam.models import (
    Class,
    Question,
    QuestionOption,
    Quiz,
    QuizResult,
    SchoolProfile,
    Section,
    StudentProfile,
    Subtopic,
)


class TemplateIntegrityTests(TestCase):
    """
    Automated check that scans every HTML template in the project and verifies
    it can be loaded and parsed without TemplateSyntaxError or unclosed tags.
    """

    def test_all_templates_compile_cleanly(self):
        templates_dir = os.path.join(settings.BASE_DIR, 'exam', 'templates')
        errors = []

        for root, dirs, files in os.walk(templates_dir):
            for filename in files:
                if filename.endswith('.html') and filename != 'test.html':
                    rel_path = os.path.relpath(os.path.join(root, filename), templates_dir)
                    # Normalize Windows backslashes for Django loader
                    django_template_name = rel_path.replace('\\', '/')
                    try:
                        get_template(django_template_name)
                    except Exception as e:
                        errors.append(f"{django_template_name}: {e}")

        self.assertEqual(len(errors), 0, f"Template syntax errors found in:\n" + "\n".join(errors))


class BaseExamTestSetup(TestCase):
    """
    Common fixture setup with sample classes, sections, users, quizzes,
    questions, options, and quiz results.
    """

    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin_user = User.objects.create_superuser(
            username='admin_test',
            email='admin@test.com',
            password='AdminPassword123!'
        )

        # Student user
        self.student_user = User.objects.create_user(
            username='student_test',
            email='student@test.com',
            password='StudentPassword123!',
            first_name='Alex',
            last_name='Student'
        )

        # Academic Cohorts
        self.class_group = Class.objects.create(name='Class 10A')
        self.section = Section.objects.create(class_group=self.class_group, name='Alpha')

        # Link student profile
        self.student_user.profile.class_group = self.class_group
        self.student_user.profile.section = self.section
        self.student_user.profile.save()

        # School Profile
        self.school_profile = SchoolProfile.get_instance()
        self.school_profile.school_name = "Global Science Academy"
        self.school_profile.save()

        # Quiz
        self.quiz = Quiz.objects.create(
            code='BIO101',
            title='Cellular Biology Assessment',
            is_active=True,
            timer_enabled=True,
            duration_minutes=45,
            show_detailed_results=True,
        )
        self.quiz.assigned_classes.add(self.class_group)
        self.quiz.assigned_sections.add(self.section)

        # Subtopics
        self.subtopic1 = Subtopic.objects.create(quiz=self.quiz, name='Organelles')
        self.subtopic2 = Subtopic.objects.create(quiz=self.quiz, name='Mitosis')

        # Questions & Options
        self.q1 = Question.objects.create(
            quiz=self.quiz,
            text='What is the primary function of the mitochondrion?',
            subtopic=self.subtopic1,
            order=1,
            bloom_level='remember',
            bloom_confidence=0.92,
            bloom_classification_source='zero_shot',
        )
        self.opt1_a = QuestionOption.objects.create(question=self.q1, label='A', text='Cellular energy production (ATP)', is_correct=True, order=1)
        self.opt1_b = QuestionOption.objects.create(question=self.q1, label='B', text='Protein packaging', is_correct=False, order=2)
        self.opt1_c = QuestionOption.objects.create(question=self.q1, label='C', text='Photosynthesis', is_correct=False, order=3)
        self.opt1_d = QuestionOption.objects.create(question=self.q1, label='D', text='Lipid degradation', is_correct=False, order=4)

        self.q2 = Question.objects.create(
            quiz=self.quiz,
            text='Explain how cellular respiration differs from fermentation.',
            subtopic=self.subtopic2,
            order=2,
            bloom_level='understand',
            bloom_confidence=0.88,
            bloom_classification_source='zero_shot',
        )
        self.opt2_a = QuestionOption.objects.create(question=self.q2, label='A', text='Aerobic vs Anaerobic pathway', is_correct=True, order=1)
        self.opt2_b = QuestionOption.objects.create(question=self.q2, label='B', text='No difference', is_correct=False, order=2)

        # Quiz Result
        self.result = QuizResult.objects.create(
            quiz=self.quiz,
            user=self.student_user,
            score=2,
            answers={
                str(self.q1.id): str(self.opt1_a.id),
                str(self.q2.id): str(self.opt2_a.id)
            }
        )


class StudentPortalViewTests(BaseExamTestSetup):
    """
    Tests ensuring all student-facing views render without errors.
    """

    def test_login_page_renders(self):
        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sign In")

    def test_student_home_dashboard(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Welcome back")

    def test_enter_code_get(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('enter-code'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter Assessment Code")

    def test_enter_code_post_valid(self):
        self.client.force_login(self.student_user)
        resp = self.client.post(reverse('enter-code'), {'code': 'BIO101'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cellular Biology Assessment")

    def test_enter_code_post_invalid(self):
        self.client.force_login(self.student_user)
        resp = self.client.post(reverse('enter-code'), {'code': 'INVALID_CODE'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid exam code")

    def test_quiz_results_list_view(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('render_results'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "My Assessment Results")
        self.assertContains(resp, "Cellular Biology Assessment")

    def test_student_result_detail_view(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('student_result_detail', args=[self.result.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cellular Biology Assessment")
        self.assertContains(resp, "Score Achieved")


class DashboardAdminViewTests(BaseExamTestSetup):
    """
    Tests ensuring every single page and subview in the teacher/admin dashboard
    loads with HTTP 200 and renders cleanly.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin_user)

    def test_dashboard_home(self):
        resp = self.client.get(reverse('dashboard_home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Dashboard Overview")

    def test_dashboard_quizzes_list(self):
        resp = self.client.get(reverse('dashboard_quizzes'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Quiz Management")
        self.assertContains(resp, "Cellular Biology Assessment")

    def test_dashboard_quiz_create_page(self):
        resp = self.client.get(reverse('dashboard_quiz_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create Quiz")

    def test_dashboard_quiz_edit_page(self):
        resp = self.client.get(reverse('dashboard_quiz_edit', args=[self.quiz.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cellular Biology Assessment")

    def test_dashboard_quiz_questions_page(self):
        resp = self.client.get(reverse('dashboard_quiz_questions', args=[self.quiz.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Question Bank")
        self.assertContains(resp, "Cellular Biology Assessment")

    def test_dashboard_quiz_results_page(self):
        resp = self.client.get(reverse('dashboard_quiz_results', args=[self.quiz.id]))
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_questions_create_page(self):
        resp = self.client.get(reverse('dashboard_question_create') + f"?quiz={self.quiz.id}")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_question_edit_page(self):
        resp = self.client.get(reverse('dashboard_question_edit', args=[self.q1.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Edit Question")

    def test_dashboard_questions_import_page(self):
        resp = self.client.get(reverse('dashboard_question_import'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Import Questions")

    def test_dashboard_questions_import_sample(self):
        resp = self.client.get(reverse('dashboard_question_import_sample'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')

    def test_dashboard_students_list(self):
        resp = self.client.get(reverse('dashboard_students'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Student Management")
        self.assertContains(resp, "student_test")

    def test_dashboard_student_create_page(self):
        resp = self.client.get(reverse('dashboard_student_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create Student")

    def test_dashboard_student_edit_page(self):
        resp = self.client.get(reverse('dashboard_student_edit', args=[self.student_user.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Edit Student")

    def test_dashboard_student_import_page(self):
        resp = self.client.get(reverse('dashboard_student_import'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Import Students")

    def test_dashboard_classes_list(self):
        resp = self.client.get(reverse('dashboard_classes'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Classes & Sections")
        self.assertContains(resp, "Class 10A")

    def test_dashboard_class_create_post(self):
        resp = self.client.post(reverse('dashboard_class_create'), {'name': 'Class 11B'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Class.objects.filter(name='Class 11B').exists())

    def test_dashboard_class_edit_post(self):
        resp = self.client.post(reverse('dashboard_class_edit', args=[self.class_group.id]), {'name': 'Class 10A Renamed'})
        self.assertEqual(resp.status_code, 302)
        self.class_group.refresh_from_db()
        self.assertEqual(self.class_group.name, 'Class 10A Renamed')

    def test_dashboard_class_students_page(self):
        resp = self.client.get(reverse('dashboard_class_students', args=[self.class_group.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Class 10A")

    def test_dashboard_results_overview(self):
        resp = self.client.get(reverse('dashboard_results'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Results Management")

    def test_dashboard_results_export_csv(self):
        resp = self.client.get(reverse('dashboard_results_export_csv'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')

    def test_dashboard_analytics_overview(self):
        resp = self.client.get(reverse('dashboard_analytics'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cellular Biology Assessment")

    def test_dashboard_bloom_analytics(self):
        resp = self.client.get(reverse('dashboard_bloom_analytics'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bloom's Taxonomy")

    def test_dashboard_analytics_detail_subpages(self):
        chart_types = [
            'score',
            'overall',
            'difficulty',
            'cro',
            'subtopic',
            'ranking',
            'scorecard',
        ]
        for c_type in chart_types:
            with self.subTest(chart_type=c_type):
                resp = self.client.get(reverse('dashboard_analytics_detail', args=[c_type]) + f"?quiz={self.quiz.id}")
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, "Cellular Biology Assessment")

    def test_dashboard_settings_page(self):
        resp = self.client.get(reverse('dashboard_settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Platform Settings")
        self.assertContains(resp, "Global Science Academy")


class AnalyticsQuizSelectionPersistenceTests(BaseExamTestSetup):
    """
    Dedicated test suite verifying the single state hierarchy:
    1. URL ?quiz=<id> is primary
    2. Django session['active_quiz_id'] fallback
    3. Safe handling of invalid / stale session IDs
    4. Persistence across Overview, Detail subviews, and Bloom Analytics
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin_user)

        # Create Quiz B
        self.quiz_b = Quiz.objects.create(
            code='CHEM101',
            title='Organic Chemistry Assessment',
            is_active=True,
            timer_enabled=True,
            duration_minutes=30,
        )
        self.quiz_b.assigned_classes.add(self.class_group)
        self.quiz_b.assigned_sections.add(self.section)

    def test_analytics_overview_with_query_param_stores_session(self):
        # Test 1: GET Analytics with ?quiz=A -> Quiz A selected, session contains A
        resp = self.client.get(f"{reverse('dashboard_analytics')}?quiz={self.quiz.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_quiz'].id, self.quiz.id)
        self.assertEqual(self.client.session.get('active_quiz_id'), str(self.quiz.id))

    def test_analytics_overview_no_param_uses_session(self):
        # Test 2: GET Analytics with no quiz, session contains B -> Quiz B selected
        session = self.client.session
        session['active_quiz_id'] = str(self.quiz_b.id)
        session.save()

        resp = self.client.get(reverse('dashboard_analytics'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_quiz'].id, self.quiz_b.id)
        self.assertEqual(self.client.session.get('active_quiz_id'), str(self.quiz_b.id))

    def test_analytics_overview_invalid_session_fallback(self):
        # Test 3: GET Analytics with invalid session quiz ID -> no crash, fallback occurs
        session = self.client.session
        session['active_quiz_id'] = "999999"  # Non-existent ID
        session.save()

        resp = self.client.get(reverse('dashboard_analytics'))
        self.assertEqual(resp.status_code, 200)
        # Falls back safely to first quiz without 500 error
        self.assertIsNotNone(resp.context['selected_quiz'])
        self.assertEqual(resp.context['selected_quiz'].id, self.quiz.id)
        self.assertEqual(self.client.session.get('active_quiz_id'), str(self.quiz.id))

    def test_analytics_detail_with_query_param_stores_session(self):
        # Test 4: GET Analytics detail with ?quiz=A -> Quiz A selected, session contains A
        resp = self.client.get(f"{reverse('dashboard_analytics_detail', args=['score'])}?quiz={self.quiz.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_quiz'].id, self.quiz.id)
        self.assertEqual(self.client.session.get('active_quiz_id'), str(self.quiz.id))

    def test_analytics_detail_no_param_uses_session(self):
        # Test 5: GET Analytics detail with no quiz, session contains B -> Quiz B selected
        session = self.client.session
        session['active_quiz_id'] = str(self.quiz_b.id)
        session.save()

        resp = self.client.get(reverse('dashboard_analytics_detail', args=['score']))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_quiz'].id, self.quiz_b.id)
        self.assertEqual(self.client.session.get('active_quiz_id'), str(self.quiz_b.id))

    def test_bloom_analytics_with_query_param_stores_session(self):
        # Test 6: GET Bloom Analytics with ?quiz=B -> Quiz B selected, session contains B
        resp = self.client.get(f"{reverse('dashboard_bloom_analytics')}?quiz={self.quiz_b.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_quiz'].id, self.quiz_b.id)
        self.assertEqual(self.client.session.get('active_quiz_id'), str(self.quiz_b.id))

    def test_bloom_analytics_no_param_uses_session(self):
        # Test 7: GET Bloom Analytics with no quiz, session contains A -> Quiz A selected
        session = self.client.session
        session['active_quiz_id'] = str(self.quiz.id)
        session.save()

        resp = self.client.get(reverse('dashboard_bloom_analytics'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_quiz'].id, self.quiz.id)
        self.assertEqual(self.client.session.get('active_quiz_id'), str(self.quiz.id))

    def test_navigation_urls_rendered_with_selected_quiz(self):
        # Test 8: Switching quiz on Analytics updates navigation URLs correctly
        resp = self.client.get(f"{reverse('dashboard_analytics')}?quiz={self.quiz_b.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"?quiz={self.quiz_b.id}")
        self.assertContains(resp, 'syncAnalyticsNavigation')
        self.assertContains(resp, 'quizx_active_quiz_id')


class LegacyAnalysisViewTests(BaseExamTestSetup):
    """
    Tests ensuring analytical report views and CSV/PDF export views function properly.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin_user)

    def test_overall_analysis_view(self):
        resp = self.client.get(reverse('overall_analysis', args=[self.quiz.id]))
        self.assertEqual(resp.status_code, 200)

    def test_overall_analysis_export_csv(self):
        resp = self.client.get(reverse('export_overall_analysis_csv', args=[self.quiz.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')

    def test_full_scorecard_view(self):
        resp = self.client.get(reverse('full_scorecard', args=[self.quiz.id]))
        self.assertEqual(resp.status_code, 200)

    def test_question_analysis_view(self):
        resp = self.client.get(reverse('question_analysis', args=[self.quiz.id]))
        self.assertEqual(resp.status_code, 200)

    def test_cro_chart_view(self):
        resp = self.client.get(reverse('cro_chart', args=[self.quiz.id]))
        self.assertEqual(resp.status_code, 200)

    def test_view_student_response(self):
        resp = self.client.get(reverse('view_student_response', args=[self.quiz.id, self.student_user.id]))
        self.assertEqual(resp.status_code, 200)


class SecurityAndPermissionTests(BaseExamTestSetup):
    """
    Tests ensuring unauthenticated or unauthorized users cannot access dashboard endpoints.
    """

    def test_unauthenticated_user_redirected_from_dashboard(self):
        resp = self.client.get(reverse('dashboard_home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp.url)

    def test_student_user_cannot_access_dashboard(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('dashboard_home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp.url)


# Superuser Database & Maintenance Test Integration
from exam.test_db_maintenance import (
    DatabaseMaintenanceSecurityTests,
    DatabaseMaintenanceCoreTests,
    DatabaseMaintenanceOperationsTests,
)

