from django import forms
from django.contrib.auth.models import User
from .models import Question, Quiz, Subtopic, Class, Section, StudentProfile

class CodeForm(forms.Form):
	code=forms.CharField(label='Enter Quiz Code', max_length=100)

class QuestionAdminForm(forms.ModelForm):
	class Meta:
		model=Question
		fields='__all__'

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		if 'quiz' in self.data:
			try:
				quiz_id=int(self.data.get('quiz'))
				self.fields['subtopic'].queryset=Subtopic.objects.filter(quiz_id=quiz_id)
			except (ValueError, TypeError):
				pass
		elif self.instance.pk:
			self.fields['subtopic'].queryset=Subtopic.objects.filter(quiz=self.instance.quiz)
		else:
			self.fields['subtopic'].queryset=Subtopic.objects.none()

class QuizDashboardForm(forms.ModelForm):
	class Meta:
		model=Quiz
		fields=['title','code','is_active','randomize_questions','timer_enabled','duration_minutes']
		widgets={
			'title': forms.TextInput(attrs={'placeholder':'Quiz name'}),
			'code': forms.TextInput(attrs={'placeholder':'QUIZ2026'}),
			'duration_minutes': forms.NumberInput(attrs={'min':1}),
		}

class QuestionDashboardForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = [
            'quiz',
            'subtopic',
            'text',
            'image',
        ]

        widgets={
			'text': forms.Textarea(attrs={'rows':4}),
		}

    def __init__(self, *args, **kwargs):
        quiz = kwargs.pop('quiz', None)
        super().__init__(*args, **kwargs)

        if quiz:
            self.quiz = quiz
            self.fields['quiz'].initial = quiz
            self.fields['quiz'].widget = forms.HiddenInput()
            self.fields['subtopic'].queryset = Subtopic.objects.filter(quiz=quiz)

        elif self.instance.pk:
            self.quiz = self.instance.quiz
            self.fields['quiz'].widget = forms.HiddenInput()
            self.fields['subtopic'].queryset = Subtopic.objects.filter(
                quiz=self.instance.quiz
            )

        else:
            self.quiz = None
            self.fields['subtopic'].queryset = Subtopic.objects.all()

    def save(self, commit=True):
        question = super().save(commit=False)

        if self.quiz:
            question.quiz = self.quiz

        if commit:
            question.save()

        return question

class StudentForm(forms.ModelForm):
	password=forms.CharField(widget=forms.PasswordInput, required=False)
	class_group=forms.ModelChoiceField(queryset=Class.objects.all(), required=False, label='Class')
	section=forms.ModelChoiceField(queryset=Section.objects.none(), required=False, label='Section')

	class Meta:
		model=User
		fields=['first_name','last_name','username','email','password','is_active']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.is_bound:
			try:
				class_id = self.data.get('class_group')
				if class_id:
					self.fields['section'].queryset = Section.objects.filter(class_group_id=class_id)
			except (ValueError, TypeError):
				pass
		elif self.instance.pk:
			profile, _ = StudentProfile.objects.get_or_create(user=self.instance)
			if profile.class_group:
				self.fields['class_group'].initial = profile.class_group
				self.fields['section'].queryset = Section.objects.filter(class_group=profile.class_group)
			if profile.section:
				self.fields['section'].initial = profile.section

	def clean(self):
		cleaned_data = super().clean()
		class_group = cleaned_data.get('class_group')
		section = cleaned_data.get('section')
		if section and section.class_group != class_group:
			raise forms.ValidationError("The selected section does not belong to the selected class.")
		return cleaned_data

	def save(self, commit=True):
		user=super().save(commit=False)
		password=self.cleaned_data.get('password')
		if password:
			user.set_password(password)
		if commit:
			user.save()
			profile, _ = StudentProfile.objects.get_or_create(user=user)
			profile.class_group = self.cleaned_data.get('class_group')
			profile.section = self.cleaned_data.get('section')
			profile.save()
		return user

class StudentEditForm(forms.ModelForm):
	class_group=forms.ModelChoiceField(queryset=Class.objects.all(), required=False, label='Class')
	section=forms.ModelChoiceField(queryset=Section.objects.none(), required=False, label='Section')

	class Meta:
		model=User
		fields=['first_name','last_name','username','email','is_active']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.is_bound:
			try:
				class_id = self.data.get('class_group')
				if class_id:
					self.fields['section'].queryset = Section.objects.filter(class_group_id=class_id)
			except (ValueError, TypeError):
				pass
		elif self.instance.pk:
			profile, _ = StudentProfile.objects.get_or_create(user=self.instance)
			if profile.class_group:
				self.fields['class_group'].initial = profile.class_group
				self.fields['section'].queryset = Section.objects.filter(class_group=profile.class_group)
			if profile.section:
				self.fields['section'].initial = profile.section

	def clean(self):
		cleaned_data = super().clean()
		class_group = cleaned_data.get('class_group')
		section = cleaned_data.get('section')
		if section and section.class_group != class_group:
			raise forms.ValidationError("The selected section does not belong to the selected class.")
		return cleaned_data

	def save(self, commit=True):
		user=super().save(commit=False)
		if commit:
			user.save()
			profile, _ = StudentProfile.objects.get_or_create(user=user)
			profile.class_group = self.cleaned_data.get('class_group')
			profile.section = self.cleaned_data.get('section')
			profile.save()
		return user

class StudentPasswordForm(forms.Form):
	password=forms.CharField(widget=forms.PasswordInput)

class CsvUploadForm(forms.Form):
	file=forms.FileField()

class ImportColumnMappingForm(forms.Form):
    """Built dynamically in views; placeholder for shared widget attrs."""
    pass

class ClassForm(forms.ModelForm):
	class Meta:
		model = Class
		fields = ['name', 'notes']
		widgets = {
			'name': forms.TextInput(attrs={'placeholder': 'e.g. Class 10'}),
			'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional notes about this class'}),
		}

class SectionForm(forms.ModelForm):
	class Meta:
		model = Section
		fields = ['class_group', 'name']
		widgets = {
			'name': forms.TextInput(attrs={'placeholder': 'e.g. A'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['class_group'].queryset = Class.objects.all()

