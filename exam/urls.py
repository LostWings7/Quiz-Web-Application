from django.urls import include, path
from django.contrib.auth import views as auth_views
from django.contrib.admin.views.decorators import staff_member_required
from . import views
from .views import enter_code_view, quiz_question_view, quiz_submit_view

urlpatterns = [
    path('dashboard/', include('exam.dashboard_urls')),
    path('enter-code/',enter_code_view,name='enter-code'),
    path('home/',views.home,name='home'),
    path('', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(),name='logout'),
    path('quiz-results/',views.render_results, name='render_results'),
    path('quiz-results/<int:result_id>/detail/', views.student_result_detail, name='student_result_detail'),
    path('main/',views.main, name='main'),
    path('start-quiz/', views.start_quiz_view, name='start_quiz',),
    path('quiz/<int:quiz_id>/question/<int:question_num>/', views.quiz_question_view, name='quiz_question'),
    path("quiz/<int:quiz_id>/question/<int:question_num>/save/", views.save_answer_ajax, name="save_answer_ajax"),
    path('quiz/<int:quiz_id>/submit/', quiz_submit_view, name='quiz_submit'),
    path('admin/overall-analysis/<int:quiz_id>/',views.overall_analysis_view, name='overall_analysis'),
    path('admin/quiz/<int:quiz_id>/export/csv/', views.export_overall_analysis_csv, name='export_overall_analysis_csv'),
    path('admin/quiz/<int:quiz_id>/export/pdf/', views.export_overall_analysis_pdf, name='export_overall_analysis_pdf'),
    path('admin/quiz/<int:quiz_id>/full-scorecard/', views.full_scorecard_view, name='full_scorecard'),
    path('quiz/<int:quiz_id>/response/<int:user_id>/', views.view_student_response, name='view_student_response'),
    path('admin/quiz/<int:quiz_id>/question-analysis/',views.question_analysis_view, name='question_analysis'),
    path('admin/quiz/<int:quiz_id>/cro-chart/', views.cro_chart_view, name='cro_chart'),
]
