import json

from django import forms

from .models import Quiz


class ImportUploadForm(forms.Form):
    file = forms.FileField(
        label='Spreadsheet file',
        help_text='Upload a .csv or .xlsx file. Use .xlsx to highlight the correct answer with cell color.',
    )
    has_header = forms.BooleanField(
        label='First row is a header row',
        required=False,
        initial=True,
    )

    def clean_file(self):
        uploaded = self.cleaned_data['file']
        name = uploaded.name.lower()
        if not (name.endswith('.csv') or name.endswith('.xlsx')):
            raise forms.ValidationError('Please upload a .csv or .xlsx file.')
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError('File must be smaller than 5 MB.')
        return uploaded


class QuestionImportUploadForm(ImportUploadForm):
    quiz = forms.ModelChoiceField(
        queryset=Quiz.objects.order_by('title'),
        label='Target quiz',
        empty_label=None,
    )


class StudentImportUploadForm(ImportUploadForm):
    pass
