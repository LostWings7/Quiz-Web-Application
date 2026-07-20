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
	assigned_classes=models.ManyToManyField('Class', blank=True, related_name='quizzes')
	assigned_sections=models.ManyToManyField('Section', blank=True, related_name='quizzes')

	def __str__(self):
		return self.title

	def get_visibility_preview(self):
		if not self.assigned_classes.exists():
			return "All Classes"
		previews = []
		for class_obj in self.assigned_classes.all():
			class_sections = self.assigned_sections.filter(class_group=class_obj)
			if class_sections.exists():
				sec_names = ", ".join([s.name for s in class_sections])
				previews.append(f"{class_obj.name} (Section {sec_names})")
			else:
				previews.append(f"{class_obj.name} (All Sections)")
		return ", ".join(previews)


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

	def get_all_images(self):
		imgs = []
		if self.image:
			imgs.append(self.image)
		for extra in self.additional_images.all():
			imgs.append(extra.image)
		return imgs

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

class QuestionImage(models.Model):
	question=models.ForeignKey(Question, on_delete=models.CASCADE, related_name='additional_images')
	image=models.ImageField(upload_to='question_images/')
	created_at=models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f"Image for Question {self.question_id}"

class QuestionOption(models.Model):
	question=models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
	text=models.TextField()
	label=models.CharField(max_length=8, blank=True)
	is_correct=models.BooleanField(default=False)
	order=models.PositiveIntegerField(default=0)
	image=models.ImageField(upload_to='options/', null=True, blank=True)

	def __str__(self):
		return self.text

	def get_all_images(self):
		imgs = []
		if self.image:
			imgs.append(self.image)
		for extra in self.images.all():
			imgs.append(extra.image)
		return imgs

	class Meta:
		ordering=['order','id']

class OptionImage(models.Model):
	option=models.ForeignKey(QuestionOption, on_delete=models.CASCADE, related_name='images')
	image=models.ImageField(upload_to='option_images/')
	created_at=models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f"Image for Option {self.option_id}"

class QuizResult(models.Model):
	quiz=models.ForeignKey(Quiz,on_delete=models.CASCADE)
	user=models.ForeignKey(User,on_delete=models.CASCADE)
	score=models.IntegerField()
	submitted_at=models.DateTimeField(auto_now_add=True)
	answers = JSONField(default=dict) 

	class Meta:
		unique_together=('quiz','user')

class Class(models.Model):
	name = models.CharField(max_length=100, unique=True)
	notes = models.TextField(blank=True, null=True)

	def __str__(self):
		return self.name

class Section(models.Model):
	class_group = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='sections')
	name = models.CharField(max_length=100)

	class Meta:
		unique_together = ('class_group', 'name')

	def __str__(self):
		return f"{self.class_group.name} - {self.name}"

class StudentProfile(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
	class_group = models.ForeignKey(Class, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
	section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')

	def clean(self):
		from django.core.exceptions import ValidationError
		if self.section and self.section.class_group != self.class_group:
			raise ValidationError("The section must belong to the selected class.")

	def save(self, *args, **kwargs):
		self.full_clean()
		super().save(*args, **kwargs)

	def __str__(self):
		return f"{self.user.username}'s profile"

from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_student_profile(sender, instance, created, **kwargs):
	if created:
		StudentProfile.objects.get_or_create(user=instance)
