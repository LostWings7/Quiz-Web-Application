from collections import Counter, defaultdict
import csv
import io
import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.db.models import Avg, Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from .forms import QuestionDashboardForm, QuizDashboardForm, StudentForm, StudentEditForm, StudentPasswordForm
from .import_forms import QuestionImportUploadForm, StudentImportUploadForm
from .import_utils import (
    build_column_choices,
    cell_value,
    parse_order_value,
    parse_uploaded_file,
    preview_headers,
    preview_rows,
)
from .models import Question, QuestionOption, Quiz, QuizResult, Subtopic

QUESTION_IMPORT_SESSION = 'question_import_payload'
STUDENT_IMPORT_SESSION = 'student_import_payload'


def display_name(user):
    full_name = user.get_full_name().strip()
    return full_name or user.username


def option_label(index):
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    if index < len(letters):
        return letters[index]
    return str(index + 1)


def unique_quiz_code(base_code):
    candidate = f'{base_code}-COPY'
    counter = 2
    while Quiz.objects.filter(code=candidate).exists():
        candidate = f'{base_code}-COPY-{counter}'
        counter += 1
    return candidate


def unique_quiz_title(base_title):
    candidate = f'{base_title} Copy'
    counter = 2
    while Quiz.objects.filter(title=candidate).exists():
        candidate = f'{base_title} Copy {counter}'
        counter += 1
    return candidate


def option_rows_for_question(question=None):
    if question:
        rows = [
            {'text': option.text, 'is_correct': option.is_correct}
            for option in question.get_options()
        ]
        if rows:
            return rows
    return [{'text': '', 'is_correct': True}]


def option_rows_from_post(request):
    texts = [text.strip() for text in request.POST.getlist('option_text')]
    correct_index = request.POST.get('correct_option', '0')
    try:
        correct_index = int(correct_index)
    except (TypeError, ValueError):
        correct_index = 0

    rows = []
    for index, text in enumerate(texts):
        if text:
            rows.append({
                'text': text,
                'is_correct': index == correct_index,
            })

    if rows and not any(row['is_correct'] for row in rows):
        rows[0]['is_correct'] = True

    return rows


def save_question_options(question, rows):
    question.options.all().delete()
    for index, row in enumerate(rows):
        QuestionOption.objects.create(
            question=question,
            text=row['text'],
            label=option_label(index),
            is_correct=row['is_correct'],
            order=index,
        )
    correct = question.options.filter(is_correct=True).first()
    question.correct_answer = str(correct.id) if correct else ''
    question.option_a = rows[0]['text'] if len(rows) > 0 else ''
    question.option_b = rows[1]['text'] if len(rows) > 1 else ''
    question.option_c = rows[2]['text'] if len(rows) > 2 else ''
    question.option_d = rows[3]['text'] if len(rows) > 3 else ''
    question.save(update_fields=['correct_answer', 'option_a', 'option_b', 'option_c', 'option_d'])


def answer_is_correct(question, answer):
    if not answer:
        return False
    correct = question.options.filter(is_correct=True).first()
    if correct:
        return str(answer) in {str(correct.id), str(correct.label)}
    return str(answer) == str(question.correct_answer)


def option_rows_from_csv(row):
    option_texts = []
    if row.get('options'):
        option_texts = [value.strip() for value in row['options'].split('|') if value.strip()]
    else:
        index = 1
        while row.get(f'option_{index}'):
            option_texts.append(row[f'option_{index}'].strip())
            index += 1
        if not option_texts:
            option_texts = [
                row.get('option_a', '').strip(),
                row.get('option_b', '').strip(),
                row.get('option_c', '').strip(),
                row.get('option_d', '').strip(),
            ]
            option_texts = [value for value in option_texts if value]

    correct_raw = (row.get('correct_answer') or row.get('correct_option') or '1').strip()
    try:
        correct_index = int(correct_raw) - 1
    except ValueError:
        correct_index = max(0, ord(correct_raw.upper()[:1]) - ord('A'))

    rows = [
        {'text': text, 'is_correct': index == correct_index}
        for index, text in enumerate(option_texts)
    ]
    if rows and not any(row['is_correct'] for row in rows):
        rows[0]['is_correct'] = True
    return rows


def quiz_metrics():
    rows = []
    for quiz in Quiz.objects.annotate(question_count=Count('questions')).order_by('-created_at', 'title'):
        results = QuizResult.objects.filter(quiz=quiz)
        participants = results.values('user').distinct().count()
        avg_score = results.aggregate(avg=Avg('score'))['avg'] or 0
        rows.append({
            'quiz': quiz,
            'question_count': quiz.question_count,
            'participants': participants,
            'average_score': round(avg_score, 1),
        })
    return rows


@staff_member_required
def dashboard_home(request):
    total_questions = Question.objects.count()
    total_attempts = QuizResult.objects.count()
    average_score = QuizResult.objects.aggregate(avg=Avg('score'))['avg'] or 0
    recent_attempts = QuizResult.objects.select_related('quiz', 'user').order_by('-submitted_at')[:8]
    recent_users = User.objects.filter(is_staff=False).order_by('-date_joined')[:8]
    return render(request, 'dashboard/home.html', {
        'total_quizzes': Quiz.objects.count(),
        'total_students': User.objects.filter(is_staff=False).count(),
        'total_questions': total_questions,
        'total_attempts': total_attempts,
        'average_score': round(average_score, 1),
        'recent_attempts': recent_attempts,
        'recent_users': recent_users,
    })


@staff_member_required
def quiz_list(request):
    return render(request, 'dashboard/quiz_list.html', {'quiz_rows': quiz_metrics()})


@staff_member_required
def quiz_create(request):
    form = QuizDashboardForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        quiz = form.save()
        messages.success(request, 'Quiz created successfully.')
        return redirect('dashboard_quiz_edit', quiz_id=quiz.id)
    return render(request, 'dashboard/form.html', {'form': form, 'title': 'Create Quiz', 'submit_label': 'Create Quiz'})


@staff_member_required
def quiz_edit(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    form = QuizDashboardForm(request.POST or None, instance=quiz)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Quiz updated successfully.')
        return redirect('dashboard_quizzes')
    return render(request, 'dashboard/form.html', {'form': form, 'title': 'Edit Quiz', 'submit_label': 'Save Changes'})

@staff_member_required
def quiz_questions(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)

    questions = (
        Question.objects
        .filter(quiz=quiz)
        .select_related("subtopic")
        .order_by("order", "id")
    )

    return render(
        request,
        "dashboard/quiz_questions.html",
        {
            "quiz": quiz,
            "questions": questions,
        },
    )

@staff_member_required
def quiz_delete(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    if request.method == 'POST':
        quiz.delete()
        messages.success(request, 'Quiz deleted.')
        return redirect('dashboard_quizzes')
    return render(request, 'dashboard/confirm_delete.html', {'object_name': quiz.title, 'cancel_url': 'dashboard_quizzes'})


@staff_member_required
def quiz_duplicate(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    copy = Quiz.objects.create(
        title=unique_quiz_title(quiz.title),
        code=unique_quiz_code(quiz.code),
        is_active=False,
        randomize_questions=quiz.randomize_questions,
        timer_enabled=quiz.timer_enabled,
        duration_minutes=quiz.duration_minutes,
    )
    subtopic_map = {}
    for subtopic in Subtopic.objects.filter(quiz=quiz):
        subtopic_map[subtopic.id] = Subtopic.objects.create(quiz=copy, name=subtopic.name)
    for question in Question.objects.filter(quiz=quiz):
        original_subtopic_id = question.subtopic_id
        original_options = option_rows_for_question(question)
        question.pk = None
        question.quiz = copy
        if original_subtopic_id:
            question.subtopic = subtopic_map.get(original_subtopic_id)
        question.correct_answer = ''
        question.save()
        save_question_options(question, original_options)
    messages.success(request, 'Quiz duplicated. The copy is inactive until you activate it.')
    return redirect('dashboard_quizzes')


@staff_member_required
def quiz_toggle(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    quiz.is_active = not quiz.is_active
    quiz.save(update_fields=['is_active'])
    messages.success(request, 'Quiz status updated.')
    return redirect('dashboard_quizzes')

@staff_member_required
def quiz_toggle_review(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    quiz.show_detailed_results = not quiz.show_detailed_results
    quiz.save(update_fields=['show_detailed_results'])
    messages.success(request, 'Detailed Results visibility updated.')
    return redirect('dashboard_quizzes')





@staff_member_required
def question_create(request):
    quiz = Quiz.objects.filter(id=request.GET.get('quiz')).first()
    form = QuestionDashboardForm(request.POST or None, request.FILES or None, quiz=quiz)
    option_rows = option_rows_from_post(request) if request.method == 'POST' else option_rows_for_question()
    if request.method == 'POST' and form.is_valid():
        if not option_rows:
            messages.error(request, 'Add at least one option for the question.')
        else:
            question = form.save()
            save_question_options(question, option_rows)
            messages.success(request, 'Question created successfully.')
            if quiz:
                return redirect('dashboard_quiz_questions', quiz_id=quiz.id)
            return redirect('dashboard_quizzes')
    return render(request, 'dashboard/form.html', {
        'form': form,
        'title': 'Create Question',
        'submit_label': 'Create Question',
        'option_rows': option_rows,
        'quiz': quiz,
    })


@staff_member_required
def question_edit(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    form = QuestionDashboardForm(
        request.POST or None,
        request.FILES or None,
        instance=question,
        quiz=question.quiz,
    )
    option_rows = option_rows_from_post(request) if request.method == 'POST' else option_rows_for_question(question)
    if request.method == 'POST' and form.is_valid():
        if not option_rows:
            messages.error(request, 'Add at least one option for the question.')
        else:
            form.save()
            save_question_options(question, option_rows)
            messages.success(request, 'Question updated successfully.')
            return redirect(
                'dashboard_quiz_questions',
                quiz_id=question.quiz.id
            )
    return render(request, 'dashboard/form.html', {
        'form': form,
        'title': 'Edit Question',
        'submit_label': 'Save Changes',
        'option_rows': option_rows,
        'quiz': question.quiz,
    })


@staff_member_required
def question_delete(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    quiz_id = question.quiz.id

    if request.method == 'POST':
        question.delete()
        messages.success(request, 'Question deleted.')

        return redirect(
            'dashboard_quiz_questions',
            quiz_id=quiz_id
        )

    return render(
        request,
        'dashboard/confirm_delete.html',
        {
            'object_name': question.text[:80],
            'cancel_url': 'dashboard_quiz_questions',
            'quiz_id': quiz_id,
        }
    )

@staff_member_required
def question_reorder(request):
    quiz_id = request.POST.get('quiz_filter') or request.GET.get('quiz')
    source = request.POST.get('source')
    
    if request.method == 'POST':
        for question_id, order in request.POST.items():
            if question_id.startswith('order_'):
                Question.objects.filter(id=question_id.replace('order_', '')).update(order=order or 0)
        messages.success(request, 'Question order updated.')
        if source == 'quiz' and quiz_id:
            return redirect('dashboard_quiz_questions', pk=quiz_id)
        if quiz_id:
            return redirect('dashboard_quiz_questions', quiz_id=quiz_id)
        return redirect('dashboard_quizzes')
    return redirect('dashboard_quizzes')


@staff_member_required
def question_import(request):
    quiz_param = request.GET.get('quiz')

    if request.GET.get('cancel'):
        request.session.pop(QUESTION_IMPORT_SESSION, None)
        if quiz_param:
            return redirect(f"/dashboard/questions/import/?quiz={quiz_param}")
        return redirect('dashboard_question_import')

    # If the user clicks "Bulk Import" from a quiz, they arrive with a ?quiz= param.
    # We should clear any stale session payload to ensure they get a fresh upload screen.
    if request.method == 'GET' and quiz_param:
        request.session.pop(QUESTION_IMPORT_SESSION, None)

    payload = request.session.get(QUESTION_IMPORT_SESSION)

    if request.method == 'POST':
        action = request.POST.get('action', 'upload')

        if action == 'upload':
            form = QuestionImportUploadForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    parsed = parse_uploaded_file(form.cleaned_data['file'])
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    request.session[QUESTION_IMPORT_SESSION] = {
                        'quiz_id': form.cleaned_data['quiz'].id,
                        'has_header': form.cleaned_data['has_header'],
                        'rows': parsed['rows'],
                        'highlighted': parsed['highlighted'],
                        'supports_color': parsed['supports_color'],
                        'filename': parsed['filename'],
                    }
                    request.session.modified = True
                    return redirect('dashboard_question_import')
        elif action == 'import' and payload:
            quiz = get_object_or_404(Quiz, id=payload['quiz_id'])
            has_header = payload['has_header']
            rows = payload['rows']
            highlighted = [tuple(item) for item in payload['highlighted']]

            map_text = request.POST.get('map_text', '')
            map_order = request.POST.get('map_order', '')
            map_subtopic = request.POST.get('map_subtopic', '')

            option_columns = []
            index = 0
            while f'map_option_{index}' in request.POST:
                col = request.POST.get(f'map_option_{index}', '')
                if col != '':
                    option_columns.append(int(col))
                index += 1

            if map_text == '':
                messages.error(request, 'Select a column for question text.')
                return redirect('dashboard_question_import')

            if not option_columns:
                messages.error(request, 'Map at least one option column.')
                return redirect('dashboard_question_import')

            data_rows = rows[1:] if has_header else rows
            created = 0
            skipped = 0

            for row_idx, row in enumerate(data_rows):
                actual_row_idx = row_idx + (1 if has_header else 0)
                text = cell_value(row, map_text)
                if not text:
                    skipped += 1
                    continue

                highlighted_cols = {
                    int(col) for row_num, col in highlighted if int(row_num) == actual_row_idx
                }
                correct_col = next(
                    (int(col) for col in option_columns if int(col) in highlighted_cols),
                    None,
                )

                options = []
                correct_idx = None
                for col in option_columns:
                    value = cell_value(row, col)
                    if value:
                        if correct_col is not None and int(col) == correct_col:
                            correct_idx = len(options)
                        options.append({'text': value, 'is_correct': False})

                if not options:
                    skipped += 1
                    continue

                if correct_idx is None:
                    if payload['supports_color']:
                        skipped += 1
                        continue
                    correct_idx = 0

                options[correct_idx]['is_correct'] = True

                subtopic = None
                subtopic_name = cell_value(row, map_subtopic)
                if subtopic_name:
                    subtopic, _ = Subtopic.objects.get_or_create(quiz=quiz, name=subtopic_name)

                question = Question.objects.create(
                    quiz=quiz,
                    subtopic=subtopic,
                    order=parse_order_value(cell_value(row, map_order)),
                    text=text,
                )
                save_question_options(question, options)
                created += 1

            request.session.pop(QUESTION_IMPORT_SESSION, None)
            messages.success(request, f'Imported {created} questions. Skipped {skipped} rows.')
            return redirect('dashboard_quiz_questions', quiz_id=quiz.id)

    if payload:
        rows = payload['rows']
        has_header = payload['has_header']
        headers = preview_headers(rows, has_header)
        num_columns = max((len(row) for row in rows), default=0)
        columns = build_column_choices(num_columns, headers, has_header)
        quiz = get_object_or_404(Quiz, id=payload['quiz_id'])
        return render(request, 'dashboard/import_questions_map.html', {
            'quiz': quiz,
            'columns': columns,
            'has_header': has_header,
            'preview': preview_rows(rows, has_header),
            'preview_headers': headers,
            'supports_color': payload['supports_color'],
            'filename': payload['filename'],
            'row_count': len(rows) - (1 if has_header else 0),
        })

    form = QuestionImportUploadForm(initial={'quiz': request.GET.get('quiz')})
    return render(request, 'dashboard/import_questions_upload.html', {'form': form})


@staff_member_required
def student_list(request):
    query = request.GET.get('q', '')
    students = User.objects.filter(is_staff=False).annotate(quiz_count=Count('quizresult')).order_by('first_name', 'username')
    if query:
        students = students.filter(Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query))
    return render(request, 'dashboard/student_list.html', {'students': students, 'query': query})


@staff_member_required
def student_create(request):
    form = StudentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Student created successfully.')
        return redirect('dashboard_students')
    return render(request, 'dashboard/form.html', {'form': form, 'title': 'Create Student', 'submit_label': 'Create Student'})


@staff_member_required
def student_edit(request, user_id):
    student = get_object_or_404(User, id=user_id, is_staff=False)
    form = StudentEditForm(request.POST or None, instance=student)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Student updated successfully.')
        return redirect('dashboard_students')
    return render(request, 'dashboard/form.html', {'form': form, 'title': 'Edit Student', 'submit_label': 'Save Changes'})


@staff_member_required
def student_delete(request, user_id):
    student = get_object_or_404(User, id=user_id, is_staff=False)
    if request.method == 'POST':
        student.delete()
        messages.success(request, 'Student deleted.')
        return redirect('dashboard_students')
    return render(request, 'dashboard/confirm_delete.html', {'object_name': display_name(student), 'cancel_url': 'dashboard_students'})


@staff_member_required
def student_reset_password(request, user_id):
    student = get_object_or_404(User, id=user_id, is_staff=False)
    form = StudentPasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        student.set_password(form.cleaned_data['password'])
        student.save(update_fields=['password'])
        messages.success(request, 'Password reset successfully.')
        return redirect('dashboard_students')
    return render(request, 'dashboard/form.html', {'form': form, 'title': f'Reset Password: {display_name(student)}', 'submit_label': 'Reset Password'})


@staff_member_required
def student_toggle(request, user_id):
    student = get_object_or_404(User, id=user_id, is_staff=False)
    student.is_active = not student.is_active
    student.save(update_fields=['is_active'])
    messages.success(request, 'Student status updated.')
    return redirect('dashboard_students')


@staff_member_required
def student_import(request):
    if request.GET.get('cancel'):
        request.session.pop(STUDENT_IMPORT_SESSION, None)
        return redirect('dashboard_student_import')

    payload = request.session.get(STUDENT_IMPORT_SESSION)

    if request.method == 'POST':
        action = request.POST.get('action', 'upload')

        if action == 'upload':
            form = StudentImportUploadForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    parsed = parse_uploaded_file(form.cleaned_data['file'])
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    request.session[STUDENT_IMPORT_SESSION] = {
                        'has_header': form.cleaned_data['has_header'],
                        'rows': parsed['rows'],
                        'filename': parsed['filename'],
                    }
                    request.session.modified = True
                    return redirect('dashboard_student_import')
        elif action == 'import' and payload:
            rows = payload['rows']
            has_header = payload['has_header']
            map_username = request.POST.get('map_username', '')
            map_first_name = request.POST.get('map_first_name', '')
            map_last_name = request.POST.get('map_last_name', '')
            map_email = request.POST.get('map_email', '')
            map_password = request.POST.get('map_password', '')

            if map_username == '':
                messages.error(request, 'Username column is required.')
                return redirect('dashboard_student_import')

            data_rows = rows[1:] if has_header else rows
            created = 0
            updated = 0
            skipped = 0

            for row in data_rows:
                username = cell_value(row, map_username)
                if not username:
                    skipped += 1
                    continue

                user, was_created = User.objects.get_or_create(username=username)
                first_name = cell_value(row, map_first_name)
                last_name = cell_value(row, map_last_name)
                email = cell_value(row, map_email)
                password = cell_value(row, map_password)

                if first_name:
                    user.first_name = first_name
                if last_name:
                    user.last_name = last_name
                if email:
                    user.email = email
                if password:
                    user.set_password(password)
                user.is_staff = False
                user.save()

                if was_created:
                    created += 1
                else:
                    updated += 1

            request.session.pop(STUDENT_IMPORT_SESSION, None)
            messages.success(
                request,
                f'Imported {created} new students. Updated {updated} existing. Skipped {skipped} rows.',
            )
            return redirect('dashboard_students')

    if payload:
        rows = payload['rows']
        has_header = payload['has_header']
        headers = preview_headers(rows, has_header)
        num_columns = max((len(row) for row in rows), default=0)
        columns = build_column_choices(num_columns, headers, has_header)
        return render(request, 'dashboard/import_students_map.html', {
            'columns': columns,
            'has_header': has_header,
            'preview': preview_rows(rows, has_header),
            'preview_headers': headers,
            'filename': payload['filename'],
            'row_count': len(rows) - (1 if has_header else 0),
        })

    form = StudentImportUploadForm()
    return render(request, 'dashboard/import_students_upload.html', {'form': form})


@staff_member_required
def results_list(request):
    query = request.GET.get('q', '')
    quiz_id = request.GET.get('quiz', '')
    results = QuizResult.objects.select_related('quiz', 'user').order_by('-submitted_at')
    if quiz_id:
        results = results.filter(quiz_id=quiz_id)
    if query:
        results = results.filter(Q(user__username__icontains=query) | Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) | Q(quiz__title__icontains=query))
    return render(request, 'dashboard/results.html', {
        'results': results,
        'quizzes': Quiz.objects.order_by('title'),
        'query': query,
        'selected_quiz': quiz_id,
    })


@staff_member_required
def results_export_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="quiz-results.csv"'
    writer = csv.writer(response)
    writer.writerow(['Student', 'Username', 'Quiz', 'Score', 'Submitted At'])
    for result in QuizResult.objects.select_related('user', 'quiz').order_by('-submitted_at'):
        writer.writerow([display_name(result.user), result.user.username, result.quiz.title, result.score, result.submitted_at])
    return response


@staff_member_required
def results_export_pdf(request):
    html = render_to_string('dashboard/results_pdf.html', {'results': QuizResult.objects.select_related('user', 'quiz')})
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="quiz-results.pdf"'
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('PDF generation error', status=500)
    return response


@staff_member_required
def quiz_results(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    query = request.GET.get('q', '')
    results = QuizResult.objects.filter(quiz=quiz).select_related('user').order_by('-submitted_at')
    if query:
        results = results.filter(Q(user__username__icontains=query) | Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query))
    return render(request, 'dashboard/quiz_results_list.html', {
        'quiz': quiz,
        'results': results,
        'query': query,
    })


@staff_member_required
def result_delete(request, result_id):
    if request.method == 'POST':
        result = get_object_or_404(QuizResult, id=result_id)
        result.delete()
        messages.success(request, 'Attempt deleted successfully.')
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_results'))


@staff_member_required
def quiz_detailed_report_pdf(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    
    results = QuizResult.objects.filter(quiz=quiz).select_related('user').order_by('-submitted_at')
    questions = Question.objects.filter(quiz=quiz).select_related('subtopic').order_by('order', 'id')
    
    students_present = results.count()
    total_questions = questions.count()
    subtopics = Subtopic.objects.filter(quiz=quiz)
    
    total_score = sum(r.score for r in results)
    avg_score_raw = (total_score / students_present) if students_present > 0 else 0
    avg_score = round(avg_score_raw, 1)
    
    scorecard = []
    for r in results:
        scorecard.append({
            'student_name': display_name(r.user),
            'username': r.user.username,
            'score': r.score,
            'correct_out_of_total': f"{r.score}/{total_questions}",
        })
    scorecard.sort(key=lambda x: x['score'], reverse=True)
    
    score_counts = defaultdict(int)
    for r in results:
        score_counts[r.score] += 1
    
    max_count = max(score_counts.values()) if score_counts else 1
    distribution = []
    for i in range(total_questions + 1):
        count = score_counts[i]
        height_pct = (count / max_count) * 100 if count > 0 else 0
        distribution.append({
            'score': i,
            'count': count,
            'height_pct': height_pct
        })
        
    topic_performance = []
    topic_correct = defaultdict(int)
    topic_total = defaultdict(int)
    
    for q in questions:
        topic_name = q.subtopic.name if q.subtopic else 'Uncategorized'
        for r in results:
            if answer_is_correct(q, r.answers.get(str(q.id))):
                topic_correct[topic_name] += 1
            topic_total[topic_name] += 1
            
    for t_name, total in topic_total.items():
        correct = topic_correct[t_name]
        pct = (correct / total) * 100 if total > 0 else 0
        topic_performance.append({
            'topic': t_name,
            'percentage': round(pct, 1)
        })
    topic_performance.sort(key=lambda x: x['percentage'], reverse=True)
    
    question_analysis = []
    for idx, q in enumerate(questions, start=1):
        options = q.get_options()
        responses = defaultdict(int)
        for r in results:
            ans = r.answers.get(str(q.id))
            responses[str(ans)] += 1
            
        opt_dist = []
        for o in options:
            count = responses[str(o.id)] + responses[str(o.label)]
            pct = (count / students_present) * 100 if students_present > 0 else 0
            opt_dist.append({
                'label': o.label,
                'is_correct': o.is_correct,
                'percentage': round(pct, 1)
            })
            
        question_analysis.append({
            'q_num': idx,
            'text': q.text,
            'options_dist': opt_dist
        })

    html = render_to_string('dashboard/quiz_report_pdf.html', {
        'quiz': quiz,
        'students_present': students_present,
        'total_questions': total_questions,
        'subtopics': subtopics,
        'avg_score': avg_score,
        'scorecard': scorecard,
        'distribution': distribution,
        'topic_performance': topic_performance,
        'question_analysis': question_analysis,
    }, request=request)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="quiz-{quiz.id}-report.pdf"'
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('PDF generation error', status=500)
    return response


@staff_member_required
def analytics(request):
    quizzes = Quiz.objects.all()
    if not quizzes.exists():
        return render(request, 'dashboard/analytics.html', {'quizzes': [], 'chart_data': {}})

    quiz_id = request.GET.get('quiz')
    if quiz_id:
        selected_quiz = get_object_or_404(Quiz, id=quiz_id)
    else:
        selected_quiz = quizzes.first()

    results = QuizResult.objects.filter(quiz=selected_quiz).select_related('user')
    total_questions = selected_quiz.questions.count() or 1

    percentages = []
    for result in results:
        percentages.append(round(result.score * 100 / total_questions))
    
    bins = Counter('0-39' if p < 40 else '40-69' if p < 70 else '70-100' for p in percentages)
    pass_rate = round(sum(1 for p in percentages if p >= 40) * 100 / len(percentages), 1) if percentages else 0
    average_score = round(sum(percentages) / len(percentages), 1) if percentages else 0

    subtopics = defaultdict(lambda: {'correct': 0, 'total': 0})
    difficulty_labels = []
    difficulty_values = []
    cro_counts = {'critical': 0, 'recommended': 0, 'optional': 0}

    for idx, question in enumerate(selected_quiz.questions.select_related('subtopic'), 1):
        total = results.count()
        correct = sum(1 for result in results if answer_is_correct(question, result.answers.get(str(question.id))))
        accuracy = round(correct * 100 / total, 1) if total else 0
        difficulty_labels.append(f'Q{idx}')
        difficulty_values.append(accuracy)

        if accuracy < 50:
            cro_counts['critical'] += 1
        elif accuracy < 77:
            cro_counts['recommended'] += 1
        else:
            cro_counts['optional'] += 1

        subtopic_name = question.subtopic.name if question.subtopic else 'Uncategorized'
        subtopics[subtopic_name]['correct'] += correct
        subtopics[subtopic_name]['total'] += total

    rankings = []
    for result in results:
        pct = round(result.score * 100 / total_questions, 1)
        rankings.append({
            'name': display_name(result.user),
            'score': result.score,
            'percentage': pct,
            'submitted_at': result.submitted_at
        })
    rankings.sort(key=lambda item: item['percentage'], reverse=True)

    chart_data = {
        'scoreLabels': ['0-39', '40-69', '70-100'],
        'scoreValues': [bins.get('0-39', 0), bins.get('40-69', 0), bins.get('70-100', 0)],
        'difficultyLabels': difficulty_labels,
        'difficultyValues': difficulty_values,
        'subtopicLabels': list(subtopics.keys()),
        'subtopicValues': [round(v['correct'] * 100 / v['total'], 1) if v['total'] else 0 for v in subtopics.values()],
        'rankingLabels': [item['name'] for item in rankings[:10]],
        'rankingValues': [item['percentage'] for item in rankings[:10]],
        'croLabels': ['Critical (<50%)', 'Recommended (50-76%)', 'Optional (>=77%)'],
        'croValues': [cro_counts['critical'], cro_counts['recommended'], cro_counts['optional']],
        'averageScore': average_score,
    }

    return render(request, 'dashboard/analytics.html', {
        'quizzes': quizzes,
        'selected_quiz': selected_quiz,
        'average_score': average_score,
        'pass_rate': pass_rate,
        'attempt_count': len(percentages),
        'chart_data': chart_data,
        'scorecard': rankings,
    })

@staff_member_required
def analytics_detail(request, chart_type):
    quiz_id = request.GET.get('quiz')
    if not quiz_id:
        return redirect('dashboard_analytics')
    
    selected_quiz = get_object_or_404(Quiz, id=quiz_id)
    results = QuizResult.objects.filter(quiz=selected_quiz).select_related('user')
    total_questions = selected_quiz.questions.count() or 1

    percentages = [round(r.score * 100 / total_questions) for r in results]
    
    text_metrics = {}
    chart_data = {}
    table_data = []

    if chart_type == 'score':
        bins = Counter('0-39' if p < 40 else '40-69' if p < 70 else '70-100' for p in percentages)
        chart_data = {
            'labels': ['0-39', '40-69', '70-100'],
            'values': [bins.get('0-39', 0), bins.get('40-69', 0), bins.get('70-100', 0)],
            'type': 'doughnut',
            'title': 'Score Distribution'
        }
        text_metrics = {
            'Total Students': len(percentages),
            'Max Score': f"{max(percentages)}%" if percentages else "N/A",
            'Min Score': f"{min(percentages)}%" if percentages else "N/A",
            'Average Score': f"{round(sum(percentages) / len(percentages), 1)}%" if percentages else "N/A",
            'Passed (>= 40%)': sum(1 for p in percentages if p >= 40)
        }
    elif chart_type == 'overall':
        average_score = round(sum(percentages) / len(percentages), 1) if percentages else 0
        chart_data = {
            'labels': ['Score', 'Remaining'],
            'values': [average_score, 100 - average_score],
            'type': 'doughnut',
            'title': 'Overall Score',
            'isSpeedDial': True
        }
        text_metrics = {
            'Total Attempts': len(percentages),
            'Overall Average': f"{average_score}%",
            'Pass Rate': f"{round(sum(1 for p in percentages if p >= 40) * 100 / len(percentages), 1) if percentages else 0}%"
        }
    elif chart_type == 'difficulty':
        difficulty_data = []
        for idx, question in enumerate(selected_quiz.questions.prefetch_related('options'), 1):
            total = results.count()
            
            opts_counts = {str(opt.id): 0 for opt in question.options.all()}
            for opt in question.options.all():
                if opt.label:
                    opts_counts[opt.label] = 0
            
            for result in results:
                ans = result.answers.get(str(question.id))
                if ans:
                    opts_counts[str(ans)] = opts_counts.get(str(ans), 0) + 1
                    
            correct = sum(1 for result in results if answer_is_correct(question, result.answers.get(str(question.id))))
            accuracy = round(correct * 100 / total, 1) if total else 0
            
            opts_stats = []
            for opt in question.options.all():
                c = opts_counts.get(str(opt.id), 0) + opts_counts.get(opt.label, 0)
                pct = round(c * 100 / total, 1) if total else 0
                opts_stats.append({
                    'text': opt.text,
                    'is_correct': opt.is_correct,
                    'percentage': pct
                })
                
            difficulty_data.append({
                'label': f'Q{idx}',
                'accuracy': accuracy,
                'question_text': question.text,
                'options': opts_stats
            })
            
        chart_data = {
            'labels': [q['label'] for q in difficulty_data],
            'values': [q['accuracy'] for q in difficulty_data],
            'type': 'line',
            'title': 'Question Difficulty'
        }
        
        if difficulty_data:
            max_acc = max(q['accuracy'] for q in difficulty_data)
            min_acc = min(q['accuracy'] for q in difficulty_data)
            easiest_qs = [q for q in difficulty_data if q['accuracy'] == max_acc]
            hardest_qs = [q for q in difficulty_data if q['accuracy'] == min_acc]
            avg_acc = round(sum(q['accuracy'] for q in difficulty_data) / len(difficulty_data), 1)
        else:
            easiest_qs, hardest_qs, avg_acc = [], [], "N/A"
            
        text_metrics = {
            'Easiest Questions (Tied)': len(easiest_qs),
            'Hardest Questions (Tied)': len(hardest_qs),
            'Average Accuracy': f"{avg_acc}%"
        }
        table_data = {
            'easiest': easiest_qs,
            'hardest': hardest_qs
        }
    elif chart_type == 'subtopic':
        subtopics = defaultdict(lambda: {'correct': 0, 'total': 0})
        for question in selected_quiz.questions.select_related('subtopic'):
            total = results.count()
            correct = sum(1 for result in results if answer_is_correct(question, result.answers.get(str(question.id))))
            subtopic_name = question.subtopic.name if question.subtopic else 'Uncategorized'
            subtopics[subtopic_name]['correct'] += correct
            subtopics[subtopic_name]['total'] += total
        
        sub_labels = list(subtopics.keys())
        sub_values = [round(v['correct'] * 100 / v['total'], 1) if v['total'] else 0 for v in subtopics.values()]
        chart_data = {
            'labels': sub_labels,
            'values': sub_values,
            'type': 'bar',
            'title': 'Subtopic Accuracy'
        }
        text_metrics = {
            'Strongest Topic': sub_labels[sub_values.index(max(sub_values))] if sub_values else "N/A",
            'Weakest Topic': sub_labels[sub_values.index(min(sub_values))] if sub_values else "N/A",
            'Total Topics': len(sub_labels),
        }
    elif chart_type == 'ranking':
        rankings = []
        for result in results:
            pct = round(result.score * 100 / total_questions, 1)
            rankings.append({
                'name': display_name(result.user),
                'percentage': pct,
            })
        rankings.sort(key=lambda item: item['percentage'], reverse=True)
        chart_data = {
            'labels': [item['name'] for item in rankings[:10]],
            'values': [item['percentage'] for item in rankings[:10]],
            'type': 'bar',
            'title': 'Student Rankings'
        }
        text_metrics = {
            'Top Student': rankings[0]['name'] if rankings else "N/A",
            'Average of Top 10': f"{round(sum(item['percentage'] for item in rankings[:10]) / len(rankings[:10]), 1)}%" if rankings else "N/A",
            'Total Ranked': len(rankings),
        }
    elif chart_type == 'scorecard':
        rankings = []
        for result in results:
            pct = round(result.score * 100 / total_questions, 1)
            rankings.append({
                'name': display_name(result.user),
                'score': result.score,
                'percentage': pct,
                'submitted_at': result.submitted_at
            })
        rankings.sort(key=lambda item: item['percentage'], reverse=True)
        chart_data = {
            'title': 'Class Scorecard',
            'type': 'none',
        }
        text_metrics = {
            'Total Students': len(rankings),
            'Average Score': f"{round(sum(item['percentage'] for item in rankings) / len(rankings), 1)}%" if rankings else "N/A"
        }
        table_data = rankings
    elif chart_type == 'cro':
        cro_counts = {'critical': 0, 'recommended': 0, 'optional': 0}
        for idx, question in enumerate(selected_quiz.questions.prefetch_related('options'), 1):
            total = results.count()
            
            opts_counts = {str(opt.id): 0 for opt in question.options.all()}
            for opt in question.options.all():
                if opt.label:
                    opts_counts[opt.label] = 0
            
            for result in results:
                ans = result.answers.get(str(question.id))
                if ans:
                    opts_counts[str(ans)] = opts_counts.get(str(ans), 0) + 1
                    
            correct = sum(1 for result in results if answer_is_correct(question, result.answers.get(str(question.id))))
            accuracy = round(correct * 100 / total, 1) if total else 0
            
            opts_stats = []
            for opt in question.options.all():
                c = opts_counts.get(str(opt.id), 0) + opts_counts.get(opt.label, 0)
                pct = round(c * 100 / total, 1) if total else 0
                opts_stats.append({
                    'text': opt.text,
                    'is_correct': opt.is_correct,
                    'percentage': pct
                })
            
            category = 'Optional'
            color = 'rgba(16, 185, 129, 0.2)'
            text_color = '#10b981'
            icon = 'fa-solid fa-circle-check'
            if accuracy < 50:
                cro_counts['critical'] += 1
                category = 'Critical'
                color = 'rgba(239, 68, 68, 0.2)'
                text_color = '#ef4444'
                icon = 'fa-solid fa-triangle-exclamation'
            elif accuracy < 77:
                cro_counts['recommended'] += 1
                category = 'Recommended'
                color = 'rgba(245, 158, 11, 0.2)'
                text_color = '#f59e0b'
                icon = 'fa-solid fa-star'
            else:
                cro_counts['optional'] += 1
            
            table_data.append({
                'id': idx,
                'text': question.text[:100] + '...' if len(question.text) > 100 else question.text,
                'accuracy': accuracy,
                'category': category,
                'color': color,
                'text_color': text_color,
                'icon': icon,
                'options': opts_stats
            })
        chart_data = {
            'labels': ['Critical (<50%)', 'Recommended (50-76%)', 'Optional (>=77%)'],
            'values': [cro_counts['critical'], cro_counts['recommended'], cro_counts['optional']],
            'type': 'pie',
            'title': 'CRO Chart'
        }
        text_metrics = {
            'Critical Questions': cro_counts['critical'],
            'Recommended Questions': cro_counts['recommended'],
            'Optional Questions': cro_counts['optional'],
        }

    return render(request, 'dashboard/analytics_detail.html', {
        'selected_quiz': selected_quiz,
        'chart_data': chart_data,
        'text_metrics': text_metrics,
        'table_data': table_data,
        'chart_type': chart_type
    })

@staff_member_required
def settings_view(request):
    return render(request, 'dashboard/settings.html')
