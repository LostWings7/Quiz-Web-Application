from collections import Counter, defaultdict
import csv
import io
import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.db.models import Avg, Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from .forms import QuestionDashboardForm, QuizDashboardForm, StudentForm, StudentEditForm, StudentPasswordForm, ClassForm, SectionForm
from .import_forms import QuestionImportUploadForm, StudentImportUploadForm
from .import_utils import (
    build_column_choices,
    cell_value,
    parse_order_value,
    parse_uploaded_file,
    preview_headers,
    preview_rows,
)
from .models import Question, QuestionOption, Quiz, QuizResult, Subtopic, Class, Section, StudentProfile, QuestionImage, OptionImage

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
            {
                'text': option.text,
                'is_correct': option.is_correct,
                'image_url': option.image.url if option.image else None,
            }
            for option in question.get_options()
        ]
        if rows:
            return rows
    return [{'text': '', 'is_correct': True, 'image_url': None}]


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
            uploaded_image = request.FILES.get(f'option_image_{index}')
            keep_image = request.POST.get(f'keep_option_image_{index}', '')
            rows.append({
                'text': text,
                'is_correct': index == correct_index,
                'image': uploaded_image,
                'keep_image': keep_image,
            })

    if rows and not any(row['is_correct'] for row in rows):
        rows[0]['is_correct'] = True

    return rows


def save_question_options(question, rows):
    old_options = list(question.options.all().order_by('order'))
    question.options.all().delete()
    for index, row in enumerate(rows):
        image_to_save = None
        if row.get('image'):
            image_to_save = row['image']
        elif row.get('keep_image'):
            if index < len(old_options) and old_options[index].image:
                image_to_save = old_options[index].image

        QuestionOption.objects.create(
            question=question,
            text=row['text'],
            label=option_label(index),
            is_correct=row['is_correct'],
            order=index,
            image=image_to_save,
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
    recent_attempts = QuizResult.objects.select_related('quiz', 'user').order_by('-submitted_at')[:8]
    recent_users = User.objects.filter(is_staff=False).order_by('-date_joined')[:8]
    
    # Class stats
    total_classes = Class.objects.count()
    
    class_list = Class.objects.annotate(student_count=Count('students', distinct=True))
    students_per_class = [{'name': c.name, 'count': c.student_count} for c in class_list]

    section_list = Section.objects.annotate(student_count=Count('students', distinct=True)).select_related('class_group')
    students_per_section = [{'name': f"{s.class_group.name} - {s.name}", 'count': s.student_count} for s in section_list]

    return render(request, 'dashboard/home.html', {
        'total_quizzes': Quiz.objects.count(),
        'total_students': User.objects.filter(is_staff=False).count(),
        'total_questions': total_questions,
        'total_attempts': total_attempts,
        'recent_attempts': recent_attempts,
        'recent_users': recent_users,
        'total_classes': total_classes,
        'students_per_class': students_per_class,
        'students_per_section': students_per_section,
    })


@staff_member_required
def quiz_list(request):
    query = request.GET.get('q', '')
    # Support multi-select: classes=1,2,3 or sections=1,2,3
    classes_param = request.GET.get('classes', '')
    sections_param = request.GET.get('sections', '')
    class_ids = [c for c in classes_param.split(',') if c.strip().isdigit()] if classes_param else []
    section_ids = [s for s in sections_param.split(',') if s.strip().isdigit()] if sections_param else []
    
    quizzes = Quiz.objects.annotate(question_count=Count('questions')).prefetch_related('assigned_classes', 'assigned_sections').order_by('-created_at', 'title')
    
    if query:
        quizzes = quizzes.filter(
            Q(title__icontains=query) |
            Q(code__icontains=query)
        )
        
    if class_ids:
        quizzes = quizzes.filter(Q(assigned_classes__id__in=class_ids)).distinct()
        if section_ids:
            quizzes = quizzes.filter(Q(assigned_sections__id__in=section_ids)).distinct()

    quiz_rows = []
    for quiz in quizzes:
        results = QuizResult.objects.filter(quiz=quiz)
        participants = results.values('user').distinct().count()
        avg_score = results.aggregate(avg=Avg('score'))['avg'] or 0
        quiz_rows.append({
            'quiz': quiz,
            'question_count': quiz.question_count,
            'participants': participants,
            'average_score': round(avg_score, 1),
        })
        
    all_classes = Class.objects.all().order_by('name')
    all_sections = Section.objects.all().select_related('class_group').order_by('class_group__name', 'name')
    
    if request.GET.get('format') == 'json':
        rows_data = [{
            'id': r['quiz'].id,
            'title': r['quiz'].title,
            'code': r['quiz'].code,
            'participants': r['participants'],
            'is_active': r['quiz'].is_active,
            'show_detailed_results': r['quiz'].show_detailed_results,
            'visibility': r['quiz'].get_visibility_preview(),
            'edit_url': f"/dashboard/quizzes/{r['quiz'].id}/edit/",
            'toggle_url': f"/dashboard/quizzes/{r['quiz'].id}/toggle/",
            'toggle_review_url': f"/dashboard/quizzes/{r['quiz'].id}/toggle-review/",
            'duplicate_url': f"/dashboard/quizzes/{r['quiz'].id}/duplicate/",
            'results_url': f"/dashboard/results/?quiz={r['quiz'].id}",
            'delete_url': f"/dashboard/quizzes/{r['quiz'].id}/delete/",
        } for r in quiz_rows]
        return JsonResponse({'quizzes': rows_data})
    
    return render(request, 'dashboard/quiz_list.html', {
        'quiz_rows': quiz_rows,
        'classes_param': classes_param,
        'sections_param': sections_param,
        'selected_class_ids': class_ids,
        'selected_section_ids': section_ids,
        'query': query,
        'all_classes': all_classes,
        'all_sections': all_sections,
    })



@staff_member_required
def quiz_create(request):
    form = QuizDashboardForm(request.POST or None)
    all_classes = Class.objects.prefetch_related('sections').annotate(student_count=Count('students', distinct=True)).order_by('name')
    if request.method == 'POST' and form.is_valid():
        quiz = form.save()
        assigned_class_ids = request.POST.getlist('assigned_classes')
        assigned_section_ids = request.POST.getlist('assigned_sections')
        quiz.assigned_classes.set(assigned_class_ids)
        quiz.assigned_sections.set(Section.objects.filter(id__in=assigned_section_ids, class_group_id__in=assigned_class_ids))
        messages.success(request, 'Quiz created successfully.')
        return redirect('dashboard_quiz_edit', quiz_id=quiz.id)
    return render(request, 'dashboard/form.html', {
        'form': form,
        'title': 'Create Quiz',
        'submit_label': 'Create Quiz',
        'all_classes': all_classes,
        'selected_class_ids': [],
        'selected_section_ids': [],
    })


@staff_member_required
def quiz_edit(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    form = QuizDashboardForm(request.POST or None, instance=quiz)
    all_classes = Class.objects.prefetch_related('sections').annotate(student_count=Count('students', distinct=True)).order_by('name')
    if request.method == 'POST' and form.is_valid():
        quiz = form.save()
        assigned_class_ids = request.POST.getlist('assigned_classes')
        assigned_section_ids = request.POST.getlist('assigned_sections')
        quiz.assigned_classes.set(assigned_class_ids)
        quiz.assigned_sections.set(Section.objects.filter(id__in=assigned_section_ids, class_group_id__in=assigned_class_ids))
        messages.success(request, 'Quiz updated successfully.')
        return redirect('dashboard_quizzes')
    
    selected_class_ids = [str(c.id) for c in quiz.assigned_classes.all()]
    selected_section_ids = [str(s.id) for s in quiz.assigned_sections.all()]
    
    return render(request, 'dashboard/form.html', {
        'form': form,
        'title': 'Edit Quiz',
        'submit_label': 'Save Changes',
        'all_classes': all_classes,
        'selected_class_ids': selected_class_ids,
        'selected_section_ids': selected_section_ids,
    })

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
    
    # Copy restrictions if copy_restrictions query param is true (default is true)
    if request.GET.get('copy_restrictions', '1') == '1':
        copy.assigned_classes.set(quiz.assigned_classes.all())
        copy.assigned_sections.set(quiz.assigned_sections.all())
        
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


def option_rows_for_question(question=None):
    if question:
        rows = []
        for option in question.get_options():
            imgs = []
            if option.image:
                imgs.append({'id_val': 'main', 'url': option.image.url})
            for extra in option.images.all():
                imgs.append({'id_val': str(extra.id), 'url': extra.image.url})
            rows.append({
                'id': option.id,
                'text': option.text,
                'is_correct': option.is_correct,
                'images': imgs,
            })
        if rows:
            return rows
    return [{'text': '', 'is_correct': True, 'images': []}]


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
            uploaded_images = request.FILES.getlist(f'option_images_{index}')
            delete_image_ids = request.POST.getlist(f'delete_option_image_ids_{index}')
            rows.append({
                'index': index,
                'text': text,
                'is_correct': index == correct_index,
                'uploaded_images': uploaded_images,
                'delete_image_ids': delete_image_ids,
            })

    if rows and not any(row['is_correct'] for row in rows):
        rows[0]['is_correct'] = True

    return rows


def save_question_options(question, rows):
    from .models import OptionImage
    old_options = list(question.options.all().order_by('order'))

    old_option_images_map = {}
    for index, old_opt in enumerate(old_options):
        old_option_images_map[index] = {
            'main': old_opt.image,
            'extras': list(old_opt.images.all()),
        }

    question.options.all().delete()

    for new_idx, row in enumerate(rows):
        orig_idx = row.get('index', new_idx)
        delete_ids = set(row.get('delete_image_ids', []))

        main_img = None
        old_extras_to_keep = []

        if orig_idx in old_option_images_map:
            old_info = old_option_images_map[orig_idx]
            if 'main' not in delete_ids:
                main_img = old_info['main']
            for extra_img in old_info['extras']:
                if str(extra_img.id) not in delete_ids:
                    old_extras_to_keep.append(extra_img.image)

        opt_obj = QuestionOption.objects.create(
            question=question,
            text=row['text'],
            label=option_label(new_idx),
            is_correct=row['is_correct'],
            order=new_idx,
            image=main_img,
        )

        for kept_img in old_extras_to_keep:
            OptionImage.objects.create(option=opt_obj, image=kept_img)

        for new_file in row.get('uploaded_images', []):
            if not opt_obj.image:
                opt_obj.image = new_file
                opt_obj.save(update_fields=['image'])
            else:
                OptionImage.objects.create(option=opt_obj, image=new_file)


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

            for f in request.FILES.getlist('extra_question_images'):
                QuestionImage.objects.create(question=question, image=f)

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
            question = form.save()
            save_question_options(question, option_rows)

            for f in request.FILES.getlist('extra_question_images'):
                QuestionImage.objects.create(question=question, image=f)

            for img_id in request.POST.getlist('delete_question_image_ids'):
                if img_id == 'main':
                    if question.image:
                        question.image.delete(save=False)
                        question.image = None
                        question.save(update_fields=['image'])
                else:
                    QuestionImage.objects.filter(id=img_id, question=question).delete()

            messages.success(request, 'Question updated successfully.')
            return redirect(
                'dashboard_quiz_questions',
                quiz_id=question.quiz.id
            )

    question_images = []
    if question.image:
        question_images.append({'id_val': 'main', 'url': question.image.url})
    for extra in question.additional_images.all():
        question_images.append({'id_val': extra.id, 'url': extra.image.url})

    return render(request, 'dashboard/form.html', {
        'form': form,
        'title': 'Edit Question',
        'submit_label': 'Save Changes',
        'option_rows': option_rows,
        'quiz': question.quiz,
        'question_images': question_images,
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
            return redirect('dashboard_quiz_questions', quiz_id=quiz_id)
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
    classes_param = request.GET.get('classes', '')
    sections_param = request.GET.get('sections', '')
    class_ids = [c for c in classes_param.split(',') if c.strip().isdigit()] if classes_param else []
    section_ids = [s for s in sections_param.split(',') if s.strip().isdigit()] if sections_param else []
    
    students = User.objects.filter(is_staff=False).select_related('profile__class_group', 'profile__section')
    
    if query:
        students = students.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )
        
    if class_ids:
        students = students.filter(profile__class_group_id__in=class_ids)
    if section_ids:
        students = students.filter(profile__section_id__in=section_ids)
            
    students = students.order_by('first_name', 'username')
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(students, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    all_classes = Class.objects.all().order_by('name')
    all_sections = Section.objects.all().select_related('class_group').order_by('class_group__name', 'name')
    
    if request.GET.get('format') == 'json':
        def group_display(student):
            try:
                p = student.profile
                if p.class_group and p.section:
                    return f"{p.class_group.name}-{p.section.name}"
                elif p.class_group:
                    return p.class_group.name
                return '—'
            except Exception:
                return '—'
        
        students_data = [{
            'id': s.id,
            'name': s.get_full_name() or s.username,
            'username': s.username,
            'group': group_display(s),
            'section_id': s.profile.section_id if hasattr(s, 'profile') and s.profile and s.profile.section_id else None,
            'is_active': s.is_active,
            'email': s.email,
            'edit_url': f"/dashboard/students/{s.id}/edit/",
            'reset_url': f"/dashboard/students/{s.id}/reset-password/",
            'toggle_url': f"/dashboard/students/{s.id}/toggle/",
            'delete_url': f"/dashboard/students/{s.id}/delete/",
        } for s in page_obj]
        return JsonResponse({
            'students': students_data,
            'page': {
                'current': page_obj.number,
                'total': page_obj.paginator.num_pages,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
                'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
            }
        })
    
    return render(request, 'dashboard/student_list.html', {
        'page_obj': page_obj,
        'query': query,
        'classes_param': classes_param,
        'sections_param': sections_param,
        'selected_class_ids': class_ids,
        'selected_section_ids': section_ids,
        'all_classes': all_classes,
        'all_sections': all_sections,
    })

@staff_member_required
def student_bulk_action(request):
    if request.method == 'POST':
        student_ids = request.POST.getlist('student_ids')
        action = request.POST.get('action')
        
        if not student_ids:
            messages.error(request, "No students selected.")
            return redirect('dashboard_students')
            
        if action == 'assign':
            class_id = request.POST.get('class_group')
            section_id = request.POST.get('section')
            
            class_obj = Class.objects.filter(id=class_id).first() if class_id else None
            section_obj = Section.objects.filter(id=section_id).first() if section_id else None
            
            if section_obj and section_obj.class_group != class_obj:
                messages.error(request, "Selected section does not belong to the selected class.")
                return redirect('dashboard_students')
                
            # Ensure every user has a profile
            for uid in student_ids:
                user = User.objects.filter(id=uid).first()
                if user:
                    profile, _ = StudentProfile.objects.get_or_create(user=user)
                    profile.class_group = class_obj
                    profile.section = section_obj
                    profile.save()
            messages.success(request, f"Successfully updated class/section for selected students.")
            
        elif action == 'promote':
            class_id = request.POST.get('promote_class')
            class_obj = Class.objects.filter(id=class_id).first() if class_id else None
            
            for uid in student_ids:
                user = User.objects.filter(id=uid).first()
                if user:
                    profile, _ = StudentProfile.objects.get_or_create(user=user)
                    profile.class_group = class_obj
                    profile.section = None
                    profile.save()
            messages.success(request, f"Successfully promoted selected students to {class_obj.name if class_obj else 'No Class'}.")
            
    return redirect('dashboard_students')


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
            map_class = request.POST.get('map_class', '')
            map_section = request.POST.get('map_section', '')

            if map_username == '':
                messages.error(request, 'Username column is required.')
                return redirect('dashboard_student_import')

            data_rows = rows[1:] if has_header else rows
            
            # Validation Step
            validation_errors = []
            row_idx = 1
            for row in data_rows:
                username = cell_value(row, map_username)
                if not username:
                    row_idx += 1
                    continue
                class_name = cell_value(row, map_class) if map_class else None
                section_name = cell_value(row, map_section) if map_section else None
                
                if class_name:
                    try:
                        c_obj = Class.objects.get(name=class_name)
                        if section_name:
                            try:
                                Section.objects.get(class_group=c_obj, name=section_name)
                            except Section.DoesNotExist:
                                validation_errors.append(f"Row {row_idx}: Section '{section_name}' does not exist in Class '{class_name}'.")
                    except Class.DoesNotExist:
                        validation_errors.append(f"Row {row_idx}: Class '{class_name}' does not exist.")
                elif section_name:
                    validation_errors.append(f"Row {row_idx}: Section '{section_name}' specified without a class.")
                row_idx += 1
                
            if validation_errors:
                messages.error(request, "Import failed due to validation errors: " + " ".join(validation_errors[:5]))
                return redirect('dashboard_student_import')

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
                
                # Assign class & section
                class_name = cell_value(row, map_class) if map_class else None
                section_name = cell_value(row, map_section) if map_section else None
                
                profile, _ = StudentProfile.objects.get_or_create(user=user)
                if class_name:
                    c_obj = Class.objects.get(name=class_name)
                    profile.class_group = c_obj
                    if section_name:
                        s_obj = Section.objects.get(class_group=c_obj, name=section_name)
                        profile.section = s_obj
                    else:
                        profile.section = None
                else:
                    profile.class_group = None
                    profile.section = None
                profile.save()

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

@staff_member_required
def classes_list(request):
	classes = Class.objects.prefetch_related('sections', 'students').annotate(
		student_count=Count('students', distinct=True)
	).order_by('name')
	
	# For each class, precompute section student counts
	for c in classes:
		for s in c.sections.all():
			s.student_count = s.students.count()

	# Forms for inline additions
	class_form = ClassForm()
	
	return render(request, 'dashboard/classes.html', {
		'classes': classes,
		'class_form': class_form,
	})

@staff_member_required
def class_create(request):
	if request.method == 'POST':
		form = ClassForm(request.POST)
		if form.is_valid():
			form.save()
			messages.success(request, 'Class created successfully.')
		else:
			for field, errors in form.errors.items():
				for error in errors:
					messages.error(request, f'Error: {error}')
	return redirect('dashboard_classes')

@staff_member_required
def class_edit(request, class_id):
	class_obj = get_object_or_404(Class, id=class_id)
	if request.method == 'POST':
		form = ClassForm(request.POST, instance=class_obj)
		if form.is_valid():
			form.save()
			messages.success(request, 'Class updated successfully.')
		else:
			for field, errors in form.errors.items():
				for error in errors:
					messages.error(request, f'Error: {error}')
	return redirect('dashboard_classes')


@staff_member_required
def class_edit_ajax(request, class_id):
	"""AJAX endpoint for full class editing: rename + section CRUD."""
	class_obj = get_object_or_404(Class, id=class_id)
	if request.method != 'POST':
		return JsonResponse({'error': 'Method not allowed'}, status=405)
	
	action = request.POST.get('action', 'rename')
	
	if action == 'rename':
		name = request.POST.get('name', '').strip()
		if not name:
			return JsonResponse({'success': False, 'error': 'Class name cannot be empty.'})
		if Class.objects.filter(name=name).exclude(id=class_id).exists():
			return JsonResponse({'success': False, 'error': 'A class with this name already exists.'})
		class_obj.name = name
		class_obj.notes = request.POST.get('notes', '')
		class_obj.save()
		return JsonResponse({'success': True, 'name': class_obj.name})
	
	elif action == 'add_section':
		section_name = request.POST.get('name', '').strip()
		if not section_name:
			return JsonResponse({'success': False, 'error': 'Section name cannot be empty.'})
		if Section.objects.filter(class_group=class_obj, name=section_name).exists():
			return JsonResponse({'success': False, 'error': f'Section "{section_name}" already exists in this class.'})
		section = Section.objects.create(class_group=class_obj, name=section_name)
		return JsonResponse({'success': True, 'section': {'id': section.id, 'name': section.name, 'student_count': 0}})
	
	elif action == 'rename_section':
		section_id = request.POST.get('section_id')
		new_name = request.POST.get('name', '').strip()
		section = get_object_or_404(Section, id=section_id, class_group=class_obj)
		if not new_name:
			return JsonResponse({'success': False, 'error': 'Section name cannot be empty.'})
		if Section.objects.filter(class_group=class_obj, name=new_name).exclude(id=section_id).exists():
			return JsonResponse({'success': False, 'error': f'Section "{new_name}" already exists in this class.'})
		section.name = new_name
		section.save()
		return JsonResponse({'success': True, 'section': {'id': section.id, 'name': section.name}})
	
	elif action == 'delete_section':
		section_id = request.POST.get('section_id')
		section = get_object_or_404(Section, id=section_id, class_group=class_obj)
		# Move students in this section to no section (keep them in the class)
		StudentProfile.objects.filter(section=section).update(section=None)
		section.delete()
		return JsonResponse({'success': True})
	
	return JsonResponse({'error': 'Unknown action'}, status=400)


@staff_member_required
def class_delete(request, class_id):
	class_obj = get_object_or_404(Class, id=class_id)
	if request.method == 'POST':
		class_obj.delete()
		if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
			return JsonResponse({'success': True})
		messages.success(request, 'Class deleted successfully.')
	return redirect('dashboard_classes')


@staff_member_required
def section_create(request):
	if request.method == 'POST':
		class_id = request.POST.get('class_group')
		name = request.POST.get('name', '').strip()
		class_obj = get_object_or_404(Class, id=class_id)
		if not name:
			return JsonResponse({'success': False, 'error': 'Section name cannot be empty.'})
		if Section.objects.filter(class_group=class_obj, name=name).exists():
			return JsonResponse({'success': False, 'error': f'Section "{name}" already exists.'})
		section = Section.objects.create(class_group=class_obj, name=name)
		if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
			return JsonResponse({'success': True, 'section': {'id': section.id, 'name': section.name}})
		messages.success(request, 'Section created successfully.')
	return redirect('dashboard_classes')


@staff_member_required
def section_edit(request, section_id):
	section_obj = get_object_or_404(Section, id=section_id)
	if request.method == 'POST':
		name = request.POST.get('name', '').strip()
		if not name:
			if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
				return JsonResponse({'success': False, 'error': 'Section name cannot be empty.'})
			messages.error(request, 'Section name cannot be empty.')
		elif Section.objects.filter(class_group=section_obj.class_group, name=name).exclude(id=section_id).exists():
			if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
				return JsonResponse({'success': False, 'error': f'Section "{name}" already exists in this class.'})
			messages.error(request, f'Section "{name}" already exists.')
		else:
			section_obj.name = name
			section_obj.save()
			if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
				return JsonResponse({'success': True, 'section': {'id': section_obj.id, 'name': section_obj.name}})
			messages.success(request, 'Section updated successfully.')
	return redirect('dashboard_classes')


@staff_member_required
def section_delete(request, section_id):
	section_obj = get_object_or_404(Section, id=section_id)
	if request.method == 'POST':
		StudentProfile.objects.filter(section=section_obj).update(section=None)
		section_obj.delete()
		if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
			return JsonResponse({'success': True})
		messages.success(request, 'Section deleted successfully.')
	return redirect('dashboard_classes')


@staff_member_required
def get_sections_ajax(request):
	class_id = request.GET.get('class_id')
	class_ids = request.GET.getlist('class_ids')
	if class_ids:
		sections = Section.objects.filter(class_group_id__in=class_ids).select_related('class_group')
		data = [{'id': s.id, 'name': f"{s.class_group.name} - {s.name}"} for s in sections]
	elif class_id:
		sections = Section.objects.filter(class_group_id=class_id)
		data = [{'id': s.id, 'name': s.name} for s in sections]
	else:
		data = []
	return JsonResponse(data, safe=False)


@staff_member_required
def student_search_ajax(request):
	"""Search students for the 'Add Existing Student' in class modal. Returns recently-created students first."""
	class_id = request.GET.get('class_id')
	q = request.GET.get('q', '').strip()
	
	students = User.objects.filter(is_staff=False).select_related('profile__class_group', 'profile__section')
	
	# Optionally exclude students already in this class
	if class_id:
		students = students.exclude(profile__class_group_id=class_id)
	
	if q:
		students = students.filter(
			Q(username__icontains=q) |
			Q(first_name__icontains=q) |
			Q(last_name__icontains=q) |
			Q(email__icontains=q)
		)
	
	students = students.order_by('-date_joined')[:20]
	
	data = []
	for s in students:
		try:
			p = s.profile
			if p.class_group and p.section:
				group = f"{p.class_group.name}-{p.section.name}"
			elif p.class_group:
				group = p.class_group.name
			else:
				group = 'Unassigned'
		except Exception:
			group = 'Unassigned'
		
		data.append({
			'id': s.id,
			'name': s.get_full_name() or s.username,
			'username': s.username,
			'group': group,
		})
	
	return JsonResponse(data, safe=False)


@staff_member_required
def class_add_student_ajax(request, class_id):
	"""Add an existing student to a class (and optionally a section)."""
	if request.method != 'POST':
		return JsonResponse({'error': 'Method not allowed'}, status=405)
	
	class_obj = get_object_or_404(Class, id=class_id)
	student_id = request.POST.get('student_id')
	section_id = request.POST.get('section_id', '')
	
	student = get_object_or_404(User, id=student_id, is_staff=False)
	profile, _ = StudentProfile.objects.get_or_create(user=student)
	
	section_obj = None
	if section_id:
		section_obj = get_object_or_404(Section, id=section_id, class_group=class_obj)
	
	profile.class_group = class_obj
	profile.section = section_obj
	profile.save()
	
	name = student.get_full_name() or student.username
	if section_obj:
		group = f"{class_obj.name}-{section_obj.name}"
	else:
		group = class_obj.name
	
	return JsonResponse({
		'success': True,
		'student': {
			'id': student.id,
			'name': name,
			'username': student.username,
			'group': group,
			'section_id': section_obj.id if section_obj else None,
			'section_name': section_obj.name if section_obj else '',
		}
	})


@staff_member_required
def class_remove_student_ajax(request, class_id):
	"""Remove a student from a class (set class/section to null)."""
	if request.method != 'POST':
		return JsonResponse({'error': 'Method not allowed'}, status=405)
	
	get_object_or_404(Class, id=class_id)
	student_id = request.POST.get('student_id')
	student = get_object_or_404(User, id=student_id, is_staff=False)
	
	try:
		profile = student.profile
		profile.class_group = None
		profile.section = None
		profile.save()
	except StudentProfile.DoesNotExist:
		pass
	
	return JsonResponse({'success': True})


@staff_member_required
def class_move_student_ajax(request, class_id):
	"""Move a student to a different section within the same class."""
	if request.method != 'POST':
		return JsonResponse({'error': 'Method not allowed'}, status=405)
	
	class_obj = get_object_or_404(Class, id=class_id)
	student_id = request.POST.get('student_id')
	section_id = request.POST.get('section_id', '')
	
	student = get_object_or_404(User, id=student_id, is_staff=False)
	profile, _ = StudentProfile.objects.get_or_create(user=student)
	
	section_obj = None
	if section_id:
		section_obj = get_object_or_404(Section, id=section_id, class_group=class_obj)
	
	profile.section = section_obj
	profile.save()
	
	if section_obj:
		group = f"{class_obj.name}-{section_obj.name}"
	else:
		group = class_obj.name
	
	return JsonResponse({'success': True, 'group': group, 'section_id': section_obj.id if section_obj else None})


@staff_member_required
def class_students(request, class_id=None, section_id=None):
	query = request.GET.get('q', '')
	sort_by = request.GET.get('sort', 'first_name')
	order = request.GET.get('order', 'asc')
	
	students = User.objects.filter(is_staff=False).select_related('profile__class_group', 'profile__section')
	
	title = "Class Students"
	subtitle = "All students assigned to this class"
	class_obj = None
	section_obj = None
	breadcrumbs = [
		{'label': 'Dashboard', 'url': '/dashboard/'},
		{'label': 'Classes', 'url': '/dashboard/classes/'},
	]
	
	if section_id:
		section_obj = get_object_or_404(Section, id=section_id)
		class_obj = section_obj.class_group
		students = students.filter(profile__section=section_obj)
		title = f"Section {section_obj.name}"
		subtitle = f"Students in {class_obj.name}, Section {section_obj.name}"
		breadcrumbs.append({'label': class_obj.name, 'url': f'/dashboard/classes/{class_obj.id}/students/'})
		breadcrumbs.append({'label': f'Section {section_obj.name}', 'url': '', 'current': True})
	elif class_id:
		class_obj = get_object_or_404(Class, id=class_id)
		students = students.filter(profile__class_group=class_obj)
		title = class_obj.name
		subtitle = f"All students assigned to {class_obj.name}"
		breadcrumbs.append({'label': class_obj.name, 'url': '', 'current': True})
		
	if query:
		students = students.filter(
			Q(username__icontains=query) |
			Q(first_name__icontains=query) |
			Q(last_name__icontains=query) |
			Q(email__icontains=query)
		)
		
	# Sorting
	if sort_by in ['first_name', 'username', 'email', 'last_login', 'is_active']:
		order_prefix = '-' if order == 'desc' else ''
		if sort_by == 'first_name':
			students = students.order_by(f'{order_prefix}first_name', f'{order_prefix}username')
		else:
			students = students.order_by(f'{order_prefix}{sort_by}')
		
	# Pagination
	from django.core.paginator import Paginator
	paginator = Paginator(students, 25)
	page_number = request.GET.get('page')
	page_obj = paginator.get_page(page_number)
	
	return render(request, 'dashboard/class_student_list.html', {
		'page_obj': page_obj,
		'query': query,
		'sort_by': sort_by,
		'order': order,
		'title': title,
		'subtitle': subtitle,
		'class_obj': class_obj,
		'section_obj': section_obj,
		'breadcrumbs': breadcrumbs,
	})


