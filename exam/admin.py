from django.contrib import admin
from django.urls import path, reverse
from django.utils.html import format_html
from django.shortcuts import redirect
from .models import Quiz,Question,QuestionOption,QuizResult,Subtopic
from .forms import QuestionAdminForm
from .views import overall_analysis_view, question_analysis_view

# Register your models here.
class QuestionInline(admin.TabularInline):
	model=Question
	extra=1

class QuestionOptionInline(admin.TabularInline):
	model=QuestionOption
	extra=1

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
	inlines=[QuestionOptionInline]
	list_display=['text','quiz','subtopic','correct_option_text']

class QuizResultAdmin(admin.ModelAdmin):
	list_display=['quiz_title','user','score']

	def quiz_title(self,obj):
		return obj.quiz.title
	quiz_title.short_description = 'Quiz'

@admin.register(Subtopic)
class SubtopicAdmin(admin.ModelAdmin):
	list_display=['name','quiz']

class QuizAdmin(admin.ModelAdmin):
	inlines=[QuestionInline]
	list_display = ['title', 'view_overall_analysis_link']

	def view_overall_analysis_link(self, obj):
	    return format_html(
	        '<a class="button" href="/admin/exam/quiz/{}/overall-analysis/">Overall Analysis</a>', obj.id
	    )
	view_overall_analysis_link.short_description = 'Overall Analysis'

	def get_urls(self):
	    urls = super().get_urls()
	    custom_urls = [
	        path(
	            '<int:quiz_id>/overall-analysis/',
	            self.admin_site.admin_view(overall_analysis_view),
	            name='quiz-overall-analysis',
	        ),
	    ]
	    return custom_urls + urls

admin.site.register(Quiz,QuizAdmin)
admin.site.register(QuizResult,QuizResultAdmin)
