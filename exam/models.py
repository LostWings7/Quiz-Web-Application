from django.db import models
from django.contrib.auth.models import User
from django.db.models import JSONField

# Create your models here.
class Quiz(models.Model):
	code=models.CharField(max_length=100, unique=True)
	title=models.CharField(max_length=200)
	is_active=models.BooleanField(default=True)
	randomize_questions=models.BooleanField(default=True)
	timer_enabled=models.BooleanField(default=False)
	duration_minutes=models.PositiveIntegerField(default=30)
	show_detailed_results=models.BooleanField(default=False)
	created_at=models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return self.title

class Subtopic(models.Model):
	quiz=models.ForeignKey(Quiz, on_delete=models.CASCADE, null=True, blank=True)
	name=models.CharField(max_length=100)

	def __str__(self):
		return self.name

class Question(models.Model):
	quiz=models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
	text=models.TextField()
	image=models.ImageField(upload_to='questions/',null=True,blank=True)
	subtopic=models.ForeignKey(Subtopic, on_delete=models.CASCADE, null=True, blank=True)
	order=models.PositiveIntegerField(default=0)
	option_a=models.CharField(max_length=255, blank=True)
	option_b=models.CharField(max_length=255, blank=True)
	option_c=models.CharField(max_length=255, blank=True)
	option_d=models.CharField(max_length=255, blank=True)
	correct_answer=models.CharField(max_length=20, blank=True)

	def __str__(self):
		return self.text

	def get_options(self):
		options = list(self.options.all())
		if options:
			return options

		legacy_options = [
			('A', self.option_a),
			('B', self.option_b),
			('C', self.option_c),
			('D', self.option_d),
		]
		return [
			QuestionOption(question=self, label=label, text=text, is_correct=(label == self.correct_answer), order=index)
			for index, (label, text) in enumerate(legacy_options)
			if text
		]

	def correct_option_id(self):
		correct = self.options.filter(is_correct=True).first()
		return str(correct.id) if correct else self.correct_answer

	def correct_option_text(self):
		correct = self.options.filter(is_correct=True).first()
		if correct:
			return correct.text
		for option in self.get_options():
			if option.is_correct:
				return option.text
		return self.correct_answer

	def correct_option_label(self):
		correct = self.options.filter(is_correct=True).first()
		if correct and correct.label:
			return correct.label
		for option in self.get_options():
			if option.is_correct and option.label:
				return option.label
		if self.correct_answer and len(self.correct_answer) <= 2:
			return self.correct_answer.upper()
		return '—'

	class Meta:
		ordering=['order','id']

class QuestionOption(models.Model):
	question=models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
	text=models.TextField()
	label=models.CharField(max_length=8, blank=True)
	is_correct=models.BooleanField(default=False)
	order=models.PositiveIntegerField(default=0)

	def __str__(self):
		return self.text

	class Meta:
		ordering=['order','id']

class QuizResult(models.Model):
	quiz=models.ForeignKey(Quiz,on_delete=models.CASCADE)
	user=models.ForeignKey(User,on_delete=models.CASCADE)
	score=models.IntegerField()
	submitted_at=models.DateTimeField(auto_now_add=True)
	answers = JSONField(default=dict) 

	class Meta:
		unique_together=('quiz','user')
