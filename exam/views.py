from django.shortcuts import render, redirect, get_object_or_404 
from django.http import HttpResponse 
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.template import loader 
from django.db.models import Avg, Max, Min, Count, Q
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings
from collections import defaultdict,Counter
from .models import Quiz, Question, QuizResult, Subtopic
from .forms import CodeForm
from xhtml2pdf import pisa
from io import BytesIO
import random
import csv
import json


def option_value(option):
    return str(option.id) if option.id else option.label


def question_options_for_template(question):
    return [
        {
            'label': option.label,
            'text': option.text,
            'value': option_value(option),
            'legacy_value': option.label,
            'is_correct': option.is_correct,
            'image_urls': [img.url for img in option.get_all_images()],
        }
        for option in question.get_options()
    ]


def answer_is_correct(question, answer):
    if not answer:
        return False
    correct = question.options.filter(is_correct=True).first()
    if correct:
        return str(answer) in {str(correct.id), str(correct.label)}
    return str(answer) == str(question.correct_answer)


def normalize_answer(question, answer):
    if not answer:
        return None
    allowed = set()
    for option in question.get_options():
        allowed.add(str(option_value(option)))
        allowed.add(str(option.label))
    return str(answer) if str(answer) in allowed else None


def home(request):
    return render(request, 'home.html')

@login_required 
def main(request): 
	username = request.user.username 
	template = loader.get_template('base.html') 
	context = {'username': username} 
	return HttpResponse(template.render(context, request))

def render_results(request):
	results=QuizResult.objects.filter(user=request.user).select_related('quiz')
	template = loader.get_template('quiz_results.html')
	context = {'results':results}
	return HttpResponse(template.render(context, request))

@login_required
def student_result_detail(request, result_id):
    if request.user.is_staff:
        result = get_object_or_404(QuizResult, id=result_id)
    else:
        result = get_object_or_404(QuizResult, id=result_id, user=request.user)
        
        # Check if admin allows viewing detailed results
        if not result.quiz.show_detailed_results:
            messages.error(request, "Detailed results are not available for this quiz.")
            return redirect('render_results')
    
    questions = result.quiz.questions.all().order_by('id')
    response_data = []
    
    for question in questions:
        user_answer = result.answers.get(str(question.id))
        
        opts = question_options_for_template(question)
        opts_list = []
        user_answer_text = None
        correct_answer_text = None
        
        for opt_dict in opts:
            opt_val = opt_dict['value']
            opt_text = opt_dict['text']
            
            if str(opt_val) == str(user_answer):
                user_answer_text = opt_text
            if opt_dict['is_correct']:
                correct_answer_text = opt_text
                
            opts_list.append({
                'value': opt_dict['legacy_value'] or opt_val,
                'text': opt_text,
                'is_correct': opt_dict['is_correct'],
                'is_selected': str(opt_val) == str(user_answer),
                'image_url': opt_dict['image_url'],
            })
            
        is_correct = answer_is_correct(question, user_answer)
        
        response_data.append({
            'question': question,
            'options': opts_list,
            'user_answer_val': user_answer,
            'user_answer_text': user_answer_text,
            'correct_answer_val': question.correct_answer,
            'correct_answer_text': correct_answer_text,
            'is_correct': is_correct,
        })
        
    context = {
        'result': result,
        'quiz': result.quiz,
        'response_data': response_data,
    }
    return render(request, 'student_result_detail.html', context)

def is_eligible_for_quiz(user, quiz):
    if user.is_staff or user.is_superuser:
        return True
    
    # Check if quiz is restricted to classes
    if not quiz.assigned_classes.exists():
        return True
    
    from .models import StudentProfile
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    if not profile.class_group:
        return False
        
    # Check if student's class is in the assigned classes
    if not quiz.assigned_classes.filter(id=profile.class_group.id).exists():
        return False
        
    # Check if sections are restricted for this class
    assigned_sections_for_class = quiz.assigned_sections.filter(class_group=profile.class_group)
    if not assigned_sections_for_class.exists():
        return True
        
    if profile.section and assigned_sections_for_class.filter(id=profile.section.id).exists():
        return True
        
    return False

@login_required
def enter_code_view(request):

    request.session.pop("quiz_answers", None)

    if request.method == "POST":

        form = CodeForm(request.POST)

        if form.is_valid():

            code = form.cleaned_data["code"]

            try:

                quiz = Quiz.objects.get(code=code, is_active=True)

                if not is_eligible_for_quiz(request.user, quiz):
                    return render(request, "quiz_not_assigned.html")

                # Store the quiz temporarily
                request.session["pending_quiz"] = quiz.id

                return render(
                    request,
                    "confirm_start.html",
                    {
                        "quiz": quiz,
                        "question_count": quiz.questions.count(),
                    },
                )

            except Quiz.DoesNotExist:

                form.add_error(
                    "code",
                    "Invalid code. Please try again."
                )

    else:

        form = CodeForm()

    return render(
        request,
        "enter_code.html",
        {
            "form": form
        }
    )

@require_POST
@login_required
def start_quiz_view(request):

    quiz_id = request.session.get("pending_quiz")

    if not quiz_id:

        return redirect("enter-code")

    quiz = get_object_or_404(Quiz, id=quiz_id)
    if not is_eligible_for_quiz(request.user, quiz):
        return render(request, "quiz_not_assigned.html")

    # Remove temporary session value
    del request.session["pending_quiz"]

    # Start with a fresh quiz session
    request.session.pop(f"quiz_{quiz_id}_order", None)
    request.session.pop("quiz_answers", None)

    return redirect(
        "quiz_question",
        quiz_id=quiz_id,
        question_num=1
    )

@login_required 
def quiz_question_view(request, quiz_id, question_num):
    quiz = get_object_or_404(Quiz, id=quiz_id)

    if not is_eligible_for_quiz(request.user, quiz):
        return render(request, "quiz_not_assigned.html")

    if QuizResult.objects.filter(quiz=quiz, user=request.user).exists():
        return render(request, 'quiz_already_done.html')

    question_ids = request.session.get(f'quiz_{quiz_id}_order')
    if not question_ids:
        questions = list(Question.objects.filter(quiz=quiz).order_by('order','id').values_list('id', flat=True))
        if quiz.randomize_questions:
            random.shuffle(questions)
        request.session[f'quiz_{quiz_id}_order'] = questions
        question_ids = questions

    question_ordered = Question.objects.filter(id__in=question_ids)
    question_map = {q.id: q for q in question_ordered}
    questions = [question_map[qid] for qid in question_ids]

    total_questions = len(questions)
    if total_questions == 0:
        return redirect('enter-code')

    try:
        current_question_id = question_ids[int(question_num) - 1]
        current_question = Question.objects.get(id=current_question_id)
    except (IndexError, Question.DoesNotExist):
        return redirect('quiz_question', quiz_id=quiz.id, question_num=1)

    quiz_answers = request.session.get('quiz_answers', {})

    if request.method == 'POST':
        answer = normalize_answer(current_question, request.POST.get('answer'))

        # -------------------------
        # Clear Response
        # -------------------------
        if 'clear' in request.POST:
            quiz_answers.pop(str(current_question.id), None)
            request.session['quiz_answers'] = quiz_answers
            request.session.modified = True
            return redirect(
                'quiz_question',
                quiz_id=quiz.id,
                question_num=question_num
            )

        quiz_answers[str(current_question.id)] = answer
        request.session['quiz_answers'] = quiz_answers
        request.session.modified = True

        if 'finish' in request.POST:

            return redirect(
                'quiz_submit',
                quiz_id=quiz.id
            )

        # -------------------------
        # Save only
        # -------------------------
        if 'save' in request.POST:
            return redirect(
                'quiz_question',
                quiz_id=quiz.id,
                question_num=question_num
            )

        # -------------------------
        # Previous
        # -------------------------
        if 'prev' in request.POST:
            prev_q = max(1, int(question_num) - 1)
            return redirect(
                'quiz_question',
                quiz_id=quiz.id,
                question_num=prev_q
            )

        # -------------------------
        # Sidebar navigation
        # -------------------------
        if 'goto' in request.POST:
            goto = int(request.POST['goto'])
            return redirect(
                'quiz_question',
                quiz_id=quiz.id,
                question_num=goto
            )

        # -------------------------
        # Next / Submit
        # -------------------------
        next_q = int(question_num) + 1
        if next_q <= total_questions:
            return redirect(
                'quiz_question',
                quiz_id=quiz.id,
                question_num=next_q
            )

        return redirect(
            'quiz_submit',
            quiz_id=quiz.id
        )

    selected_answer = quiz_answers.get(str(current_question.id), '')

    answered_count = sum(
        1 for answer in quiz_answers.values()
        if answer is not None
    )

    progress_percentage = round((answered_count / total_questions) * 100) if total_questions else 0

    return render(request, 'quiz_question.html', {
        'quiz': quiz,
        'question': current_question,
        'question_options': question_options_for_template(current_question),
        'question_num': int(question_num),
        'total_questions': total_questions,
        'questions': questions,
        'selected_answer': selected_answer,
        'answered_ids': [qid for qid, ans in quiz_answers.items() if ans],
        "answered_count": answered_count,
        "progress_percentage": progress_percentage,
        "timer_enabled": quiz.timer_enabled,
        "duration_seconds": quiz.duration_minutes * 60,
    })

@login_required
def save_answer_ajax(request, quiz_id, question_num):

    if request.method != "POST":
        return JsonResponse({"success": False}, status=400)

    quiz = get_object_or_404(Quiz, id=quiz_id)

    if not is_eligible_for_quiz(request.user, quiz):
        return JsonResponse({"success": False, "error": "Unauthorized"}, status=403)

    question_ids = request.session.get(f'quiz_{quiz_id}_order')

    if not question_ids:
        return JsonResponse(
            {"success": False},
            status=400
        )

    try:
        current_question_id = question_ids[int(question_num) - 1]
        current_question = Question.objects.get(id=current_question_id)

    except (IndexError, Question.DoesNotExist):

        return JsonResponse(
            {"success": False},
            status=400
        )

    quiz_answers = request.session.get("quiz_answers", {})

    action = request.POST.get("action")

    if action == "clear":

        quiz_answers.pop(str(current_question.id), None)

    else:

        answer = normalize_answer(current_question, request.POST.get("answer"))

        quiz_answers[str(current_question.id)] = answer

    request.session["quiz_answers"] = quiz_answers
    request.session.modified = True

    answered_count = sum(
        1 for answer in quiz_answers.values()
        if answer
    )

    progress_percentage = round(
        answered_count * 100 / len(question_ids)
    )

    return JsonResponse({
        "success": True,
        "answered": answered_count,
        "progress": progress_percentage,
        "total": len(question_ids),
    })

@login_required
def quiz_submit_view(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)

    if QuizResult.objects.filter(quiz=quiz, user=request.user).exists():
        return render(request, 'quiz_already_done.html')

    questions = Question.objects.filter(quiz=quiz)
    answers = request.session.get('quiz_answers', {})
    total_questions = questions.count()
    score = 0

    for q in questions:
        if answer_is_correct(q, answers.get(str(q.id))):
            score += 1

    quiz_result = QuizResult.objects.create(
        quiz=quiz,
        user=request.user,
        score=score,
        answers=answers,
    )

    if 'quiz_answers' in request.session:
        del request.session['quiz_answers']

    return render(request, 'quiz_completed.html', {'quiz': quiz,})

@staff_member_required
def overall_analysis_view(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    results = QuizResult.objects.filter(quiz=quiz)
    questions = Question.objects.filter(quiz=quiz)
    total_participants = results.count()
    total_questions=questions.count()

    # Basic stats
    average_score = results.aggregate(avg=Avg('score'))['avg'] or 0
    highest_score = results.aggregate(max=Max('score'))['max'] or 0
    lowest_score = results.aggregate(min=Min('score'))['min'] or 0

    overall_score=0
    length_=0
    bins={
    '0-4':0,
    '4-7':0,
    '7-10':0,
    }
    # Score distribution - rounding to nearest 0.5
    distribution = defaultdict(int)
    for result in results:
        score_ratio = (result.score / total_questions) if total_questions else 0
        if 0 <= round(score_ratio * 10) < 4:
            bins['0-4'] += 1
        if 4 <= round(score_ratio * 10) < 7:
            bins['4-7'] += 1
        if 7 <= round(score_ratio * 10) <= 10:
            bins['7-10'] += 1
        overall_score += round(score_ratio * 100)
        length_ += 1
        # score to the nearest 0.5
        rounded_score = round(score_ratio * 20) / 2
        distribution[rounded_score] += 1

    overall_score = overall_score / length_ if length_ else 0

    # Subtopic-wise accuracy
    subtopic_data = defaultdict(lambda: {'correct': 0, 'total': 0})
    for result in results:
        for q in questions:
            if q.subtopic:
                subtopic_data[q.subtopic.name]['total'] += 1
                if answer_is_correct(q, result.answers.get(str(q.id))):
                    subtopic_data[q.subtopic.name]['correct'] += 1

    subtopic_accuracy = []
    for name, data in subtopic_data.items():
        accuracy = (data['correct'] / data['total']) * 100 if data['total'] else 0
        subtopic_accuracy.append({
            'name': name,
            'accuracy': round(accuracy, 2),
            'total': data['total'],
            'correct': data['correct']
        })

    # Prepare the distribution for the chart
    score_range = [i / 2 for i in range(21)]  # Scores from 0 to 10, in steps of 0.5
    score_data = [distribution.get(score, 0) for score in score_range]

    # Subtopic data
    subtopic_labels = [item['name'] for item in subtopic_accuracy]
    subtopic_values = [item['accuracy'] for item in subtopic_accuracy]

    student_scores = list(results.values('user__username', 'score', 'submitted_at'))
    student_scores.sort(key=lambda x: x['score'], reverse=True)
    for entry in student_scores:
        entry['score'] = round((entry['score']/total_questions)*20) / 2 if total_questions else 0
    # Add rank
    for i, s in enumerate(student_scores, start=1):
        s['rank'] = i

    questions2 = quiz.questions.all().order_by('id')[:5]
    question_labels = ['Q1','Q2','Q3','Q4','Q5']
    question_accuracies = []

    for question in questions2:
        total = results.count()
        correct = 0
        for result in results:
            answer1 = result.answers.get(str(question.id))
            if answer_is_correct(question, answer1):
                correct += 1
        accuracy = round((correct / total) * 100) if total else 0
        question_accuracies.append(accuracy)

    cro_counts = defaultdict(int)
    analysis_data = []

    for question in questions:
        total = QuizResult.objects.filter(quiz=quiz).count()
        count_by_option = defaultdict(int)
        correct_answer = question.correct_option_id()

        for result in QuizResult.objects.filter(quiz=quiz):
            user_answers = result.answers
            answer = user_answers.get(str(question.id))
            count_by_option[answer] += 1

        correct_count = count_by_option.get(correct_answer, 0)
        accuracy = (correct_count / total * 100) if total else 0

        if accuracy < 50:
            cro_counts['critical'] += 1
        elif accuracy < 77:
            cro_counts['recommended'] += 1
        else:
            cro_counts['optional'] += 1

        analysis_data.append({
            'question': question,
            'accuracy': round(accuracy, 1),
        })

    context = {
        'quiz': quiz,
        'total_participants': total_participants,
        'student_scores':student_scores,
        'average_score': round(average_score, 2),
        'highest_score': highest_score,
        'lowest_score': lowest_score,
        'overall_score': round(overall_score, 2),
        'avg_score': round(overall_score/10, 1) if overall_score else 0,
        'distribution': distribution,
        'subtopic_accuracy': subtopic_accuracy,
        'score_bins':bins,
        'score_labels': score_range,
        'score_values': score_data,
        'subtopic_labels': subtopic_labels,
        'subtopic_values': subtopic_values,
        'questions': analysis_data,
        'cro_counts': cro_counts,
        'question_labels': json.dumps(question_labels),
        'question_accuracies': json.dumps(question_accuracies)
    }

    return render(request, 'admin/overall_analysis.html', context)

@staff_member_required
def question_analysis_view(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    results = QuizResult.objects.filter(quiz=quiz)
    total_attempts = results.count()

    questions_data = []

    for question in quiz.questions.all().order_by('id'):
        options = question_options_for_template(question)
        option_counts = {option['value']: 0 for option in options}
        for result in results:
            answer = result.answers.get(str(question.id), None)
            if answer in option_counts:
                option_counts[answer] += 1
        
        option_percentages = {
            opt: round((count / total_attempts) * 100) if total_attempts else 0
            for opt, count in option_counts.items()
        }

        questions_data.append({
            'text': question.text,
            'options': [
                {
                    'label': option['label'],
                    'text': option['text'],
                    'percent': option_percentages[option['value']],
                    'is_correct': option['is_correct'],
                    'image_url': option['image_url'],
                }
                for option in options
            ],
            'correct_answer': question.correct_option_id(),
        })

    return render(request, 'admin/question_analysis.html', {
        'quiz': quiz,
        'questions': questions_data,
    })

def export_overall_analysis_csv(request, quiz_id):
    quiz = Quiz.objects.get(id=quiz_id)
    total_questions = quiz.questions.count() or 1
    
    sort_param = request.GET.get('sort', 'marks')
    if sort_param == 'alpha':
        results = QuizResult.objects.filter(quiz=quiz).select_related('user', 'user__profile', 'user__profile__class_group', 'user__profile__section').order_by('user__first_name', 'user__username')
    else:
        results = QuizResult.objects.filter(quiz=quiz).select_related('user', 'user__profile', 'user__profile__class_group', 'user__profile__section').order_by('-score', 'submitted_at')

    col_params = request.GET.get('cols', '')
    if col_params:
        selected_cols = [c.strip() for c in col_params.split(',') if c.strip()]
    else:
        selected_cols = ['sno', 'name', 'marks', 'date']

    col_mapping = {
        'sno': 'S.No',
        'name': 'Student Name',
        'marks': 'Marks',
        'pct': 'Percentage',
        'date': 'Date Submitted',
        'class': 'Class',
        'section': 'Section'
    }

    headers = [col_mapping[c] for c in selected_cols if c in col_mapping]
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{quiz.title}_scorecard.csv"'

    writer = csv.writer(response)
    writer.writerow(headers)

    for index, result in enumerate(results):
        row = []
        for c in selected_cols:
            if c == 'sno':
                row.append(index + 1)
            elif c == 'name':
                row.append(f"{result.user.first_name} {result.user.last_name}".strip() or result.user.username)
            elif c == 'marks':
                row.append(f'="{result.score}/{total_questions}"')
            elif c == 'pct':
                row.append(f"{round(result.score * 100 / total_questions, 1)}%")
            elif c == 'date':
                row.append(result.submitted_at.strftime('%Y-%m-%d %H:%M'))
            elif c == 'class':
                try:
                    c_name = result.user.profile.class_group.name if result.user.profile.class_group else 'N/A'
                except:
                    c_name = 'N/A'
                row.append(c_name)
            elif c == 'section':
                try:
                    s_name = result.user.profile.section.name if result.user.profile.section else 'N/A'
                except:
                    s_name = 'N/A'
                row.append(s_name)
        writer.writerow(row)

    return response

def export_overall_analysis_pdf(request, quiz_id):
    quiz = Quiz.objects.get(id=quiz_id)
    total_questions = quiz.questions.count() or 1
    
    sort_param = request.GET.get('sort', 'marks')
    if sort_param == 'alpha':
        results = QuizResult.objects.filter(quiz=quiz).select_related('user', 'user__profile', 'user__profile__class_group', 'user__profile__section').order_by('user__first_name', 'user__username')
    else:
        results = QuizResult.objects.filter(quiz=quiz).select_related('user', 'user__profile', 'user__profile__class_group', 'user__profile__section').order_by('-score', 'submitted_at')

    col_params = request.GET.get('cols', '')
    if col_params:
        selected_cols = [c.strip() for c in col_params.split(',') if c.strip()]
    else:
        selected_cols = ['sno', 'name', 'marks', 'date']

    col_mapping = {
        'sno': 'S.No',
        'name': 'Student Name',
        'marks': 'Marks',
        'pct': 'Percentage',
        'date': 'Date Submitted',
        'class': 'Class',
        'section': 'Section'
    }

    headers = [col_mapping[c] for c in selected_cols if c in col_mapping]
    rows = []

    for index, result in enumerate(results):
        row = []
        for c in selected_cols:
            if c == 'sno':
                row.append(index + 1)
            elif c == 'name':
                row.append(f"{result.user.first_name} {result.user.last_name}".strip() or result.user.username)
            elif c == 'marks':
                row.append(f"{result.score}/{total_questions}")
            elif c == 'pct':
                row.append(f"{round(result.score * 100 / total_questions, 1)}%")
            elif c == 'date':
                row.append(result.submitted_at.strftime('%Y-%m-%d %H:%M'))
            elif c == 'class':
                try:
                    c_name = result.user.profile.class_group.name if result.user.profile.class_group else 'N/A'
                except:
                    c_name = 'N/A'
                row.append(c_name)
            elif c == 'section':
                try:
                    s_name = result.user.profile.section.name if result.user.profile.section else 'N/A'
                except:
                    s_name = 'N/A'
                row.append(s_name)
        rows.append(row)

    html = render_to_string('admin/analysis_pdf_template.html', {
        'quiz': quiz,
        'headers': headers,
        'rows': rows,
    })

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{quiz.title}_scorecard.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('PDF generation error', status=500)
    return response

def full_scorecard_view(request, quiz_id):
	quiz=get_object_or_404(Quiz, id=quiz_id)
	results=QuizResult.objects.filter(quiz=quiz).order_by('-score','submitted_at')
	questions = Question.objects.filter(quiz=quiz)

	total_questions=questions.count()

	for idx, r in enumerate(results, start=1):
		r.rank=idx

	for entry in results:
		entry.score=round((entry.score/total_questions)*20)/2 if total_questions else 0

	context={
	'quiz':quiz,
	'results':results,
	}

	return render(request, 'admin/full_scorecard.html', context)

def view_student_response(request, quiz_id, user_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    result = get_object_or_404(QuizResult, quiz=quiz, user_id=user_id)
    answers = result.answers  # stored as {question_id: 'A', ...}

    questions = Question.objects.filter(quiz=quiz).select_related('subtopic')

    response_data = []
    for question in questions:
        selected = answers.get(str(question.id))
        is_correct = answer_is_correct(question, selected)
        options = question_options_for_template(question)
        for option in options:
            option['selected'] = str(selected) in {str(option['value']), str(option['legacy_value'])}
        response_data.append({
            'question': question.text,
            'options': options,
            'selected': selected,
            'correct': question.correct_option_id(),
            'is_correct': is_correct
        })

    return render(request, 'admin/student_response.html', {
        'quiz': quiz,
        'user': result.user,
        'response_data': response_data
    })

def cro_chart_view(request, quiz_id):
    quiz = Quiz.objects.get(id=quiz_id)
    questions = Question.objects.filter(quiz=quiz)

    cro_counts = defaultdict(int)
    analysis_data = []

    for question in questions:
        total = QuizResult.objects.filter(quiz=quiz).count()
        count_by_option = defaultdict(int)
        correct_answer = question.correct_option_id()

        for result in QuizResult.objects.filter(quiz=quiz):
            user_answers = result.answers
            answer = user_answers.get(str(question.id))
            count_by_option[answer] += 1

        correct_count = count_by_option.get(correct_answer, 0)
        accuracy = (correct_count / total * 100) if total else 0

        if accuracy < 50:
            cro_counts['critical'] += 1
        elif accuracy < 77:
            cro_counts['recommended'] += 1
        else:
            cro_counts['optional'] += 1

        analysis_data.append({
            'question': question,
            'accuracy': round(accuracy, 1),
        })

    context = {
        'quiz': quiz,
        'questions': analysis_data,
        'cro_counts': cro_counts,
    }
    return render(request, 'admin/cro_chart.html', context)

def send_quiz_response_email(user, quiz_id, quiz_result):
    if not user.email:
        return

    quiz = get_object_or_404(Quiz, pk=quiz_id)
    result = get_object_or_404(QuizResult, quiz=quiz, user=user)
    answers = result.answers  # stored as {question_id: 'A', ...}

    questions = Question.objects.filter(quiz=quiz).select_related('subtopic')

    response_data = []
    for question in questions:
        selected = answers.get(str(question.id))
        is_correct = answer_is_correct(question, selected)
        options = question_options_for_template(question)
        for option in options:
            option['selected'] = str(selected) in {str(option['value']), str(option['legacy_value'])}
        response_data.append({
            'question': question.text,
            'options': options,
            'selected': selected,
            'correct': question.correct_option_id(),
            'is_correct': is_correct
        })

    context = {
        'quiz': quiz,
        'user': result.user,
        'response_data': response_data,
    }

    html_content = render_to_string('emails/quiz_response_email.html', context)

    email = EmailMessage(
        subject=f"Your Quiz Submission: {quiz_result.quiz.title}",
        body=html_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.content_subtype = 'html'
    email.send()
