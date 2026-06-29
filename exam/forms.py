from django import forms
from django.contrib.auth.models import User
from .models import Question, Quiz, Subtopic

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

	class Meta:
		model=User
		fields=['first_name','last_name','username','email','password','is_active']

	def save(self, commit=True):
		user=super().save(commit=False)
		password=self.cleaned_data.get('password')
		if password:
			user.set_password(password)
		if commit:
			user.save()
		return user

class StudentEditForm(forms.ModelForm):
	class Meta:
		model=User
		fields=['first_name','last_name','username','email','is_active']

class StudentPasswordForm(forms.Form):
	password=forms.CharField(widget=forms.PasswordInput)

class CsvUploadForm(forms.Form):
	file=forms.FileField()


class ImportColumnMappingForm(forms.Form):
    """Built dynamically in views; placeholder for shared widget attrs."""
    pass
