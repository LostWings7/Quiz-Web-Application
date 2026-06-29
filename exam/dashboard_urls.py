from django.urls import path

from . import dashboard_views as views

urlpatterns = [
    path('', views.dashboard_home, name='dashboard_home'),
    path('quizzes/', views.quiz_list, name='dashboard_quizzes'),
    path('quizzes/create/', views.quiz_create, name='dashboard_quiz_create'),
    path('quizzes/<int:quiz_id>/edit/', views.quiz_edit, name='dashboard_quiz_edit'),
    path('quizzes/<int:quiz_id>/questions/', views.quiz_questions, name='dashboard_quiz_questions'),
    path('quizzes/<int:quiz_id>/delete/', views.quiz_delete, name='dashboard_quiz_delete'),
    path('quizzes/<int:quiz_id>/duplicate/', views.quiz_duplicate, name='dashboard_quiz_duplicate'),
    path('quizzes/<int:quiz_id>/results/', views.quiz_results, name='dashboard_quiz_results'),
    path('quizzes/<int:quiz_id>/report/pdf/', views.quiz_detailed_report_pdf, name='dashboard_quiz_report_pdf'),
    path('quizzes/<int:quiz_id>/toggle/', views.quiz_toggle, name='dashboard_quiz_toggle'),
    path('quizzes/<int:quiz_id>/toggle-review/', views.quiz_toggle_review, name='dashboard_quiz_toggle_review'),
    path('results/<int:result_id>/delete/', views.result_delete, name='dashboard_result_delete'),

    path('questions/create/', views.question_create, name='dashboard_question_create'),
    path('questions/import/', views.question_import, name='dashboard_question_import'),
    path('questions/reorder/', views.question_reorder, name='dashboard_question_reorder'),
    path('questions/<int:question_id>/edit/', views.question_edit, name='dashboard_question_edit'),
    path('questions/<int:question_id>/delete/', views.question_delete, name='dashboard_question_delete'),
    path('students/', views.student_list, name='dashboard_students'),
    path('students/create/', views.student_create, name='dashboard_student_create'),
    path('students/import/', views.student_import, name='dashboard_student_import'),
    path('students/<int:user_id>/edit/', views.student_edit, name='dashboard_student_edit'),
    path('students/<int:user_id>/delete/', views.student_delete, name='dashboard_student_delete'),
    path('students/<int:user_id>/reset-password/', views.student_reset_password, name='dashboard_student_reset_password'),
    path('students/<int:user_id>/toggle/', views.student_toggle, name='dashboard_student_toggle'),
    path('results/', views.results_list, name='dashboard_results'),
    path('results/export/csv/', views.results_export_csv, name='dashboard_results_export_csv'),
    path('results/export/pdf/', views.results_export_pdf, name='dashboard_results_export_pdf'),
    path('analytics/', views.analytics, name='dashboard_analytics'),
    path('analytics/<str:chart_type>/', views.analytics_detail, name='dashboard_analytics_detail'),
    path('settings/', views.settings_view, name='dashboard_settings'),
]
