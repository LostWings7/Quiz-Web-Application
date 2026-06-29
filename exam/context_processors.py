from django.urls import reverse

from .models import Quiz


def _crumb(label, url_name=None, url_kwargs=None, current=False):
    item = {'label': label, 'current': current}
    if url_name and not current:
        item['url'] = reverse(url_name, kwargs=url_kwargs or {})
    return item


def dashboard_breadcrumbs(request):
    if not request.path.startswith('/dashboard'):
        return {'breadcrumbs': []}

    match = getattr(request, 'resolver_match', None)
    if not match or not match.url_name or not match.url_name.startswith('dashboard_'):
        return {'breadcrumbs': [_crumb('Dashboard', current=True)]}

    name = match.url_name
    kwargs = match.kwargs
    crumbs = [_crumb('Dashboard', 'dashboard_home')]

    if name == 'dashboard_home':
        crumbs[0]['current'] = True
        crumbs[0].pop('url', None)
        return {'breadcrumbs': crumbs}

    if name.startswith('dashboard_student'):
        crumbs.append(_crumb('Students', 'dashboard_students'))
        if name == 'dashboard_students':
            crumbs[-1]['current'] = True
            crumbs[-1].pop('url', None)
        elif name == 'dashboard_student_create':
            crumbs.append(_crumb('Create Student', current=True))
        elif name == 'dashboard_student_import':
            crumbs.append(_crumb('Import CSV', current=True))
        elif name == 'dashboard_student_edit':
            crumbs.append(_crumb('Edit Student', current=True))
        elif name == 'dashboard_student_reset_password':
            crumbs.append(_crumb('Reset Password', current=True))
        elif name in ('dashboard_student_delete', 'dashboard_student_toggle'):
            crumbs.append(_crumb('Students', current=True))
        return {'breadcrumbs': crumbs}

    if name.startswith('dashboard_quiz') or name.startswith('dashboard_question'):
        crumbs.append(_crumb('Quizzes', 'dashboard_quizzes'))

        quiz = None
        quiz_id = kwargs.get('quiz_id')
        if quiz_id:
            quiz = Quiz.objects.filter(id=quiz_id).first()

        if name == 'dashboard_quizzes':
            crumbs[-1]['current'] = True
            crumbs[-1].pop('url', None)
        elif name == 'dashboard_quiz_create':
            crumbs.append(_crumb('Create Quiz', current=True))
        elif name in ('dashboard_quiz_edit', 'dashboard_quiz_questions', 'dashboard_quiz_delete',
                      'dashboard_quiz_duplicate', 'dashboard_quiz_toggle') and quiz:
            crumbs.append(_crumb(quiz.title, 'dashboard_quiz_edit', {'quiz_id': quiz.id}))
            if name == 'dashboard_quiz_edit':
                crumbs.append(_crumb('Edit Quiz', current=True))
            elif name == 'dashboard_quiz_questions':
                crumbs[-1] = _crumb(quiz.title, 'dashboard_quiz_edit', {'quiz_id': quiz.id})
                crumbs.append(_crumb('Questions', current=True))
            else:
                crumbs.append(_crumb(name.replace('dashboard_quiz_', '').replace('_', ' ').title(), current=True))

        elif name == 'dashboard_question_create':
            quiz_id = request.GET.get('quiz')
            if quiz_id:
                quiz = Quiz.objects.filter(id=quiz_id).first()
            if quiz:
                crumbs.append(_crumb(quiz.title, 'dashboard_quiz_edit', {'quiz_id': quiz.id}))
                crumbs.append(_crumb('Questions', 'dashboard_quiz_questions', {'quiz_id': quiz.id}))
            crumbs.append(_crumb('Create Question', current=True))
        elif name == 'dashboard_question_import':
            quiz_id = request.session.get('question_import_payload', {}).get('quiz_id')
            if quiz_id:
                quiz = Quiz.objects.filter(id=quiz_id).first()
                if quiz:
                    crumbs.append(_crumb(quiz.title, 'dashboard_quiz_edit', {'quiz_id': quiz.id}))
            crumbs.append(_crumb('Import Questions', current=True))
        elif name == 'dashboard_question_edit':
            from .models import Question
            question = Question.objects.filter(id=kwargs.get('question_id')).select_related('quiz').first()
            if question and question.quiz:
                q = question.quiz
                crumbs.append(_crumb(q.title, 'dashboard_quiz_edit', {'quiz_id': q.id}))
                crumbs.append(_crumb('Questions', 'dashboard_quiz_questions', {'quiz_id': q.id}))
            crumbs.append(_crumb('Edit Question', current=True))
        elif name == 'dashboard_question_delete':
            crumbs.append(_crumb('Delete Question', current=True))
        elif name == 'dashboard_question_reorder':
            crumbs.append(_crumb('Reorder Questions', current=True))
        return {'breadcrumbs': crumbs}

    if name.startswith('dashboard_results'):
        crumbs.append(_crumb('Results', 'dashboard_results'))
        if name == 'dashboard_results':
            crumbs[-1]['current'] = True
            crumbs[-1].pop('url', None)
        else:
            crumbs.append(_crumb('Export', current=True))
        return {'breadcrumbs': crumbs}

    if name == 'dashboard_analytics':
        crumbs.append(_crumb('Analytics', current=True))
        return {'breadcrumbs': crumbs}

    if name == 'dashboard_settings':
        crumbs.append(_crumb('Settings', current=True))
        return {'breadcrumbs': crumbs}

    crumbs[0]['current'] = True
    crumbs[0].pop('url', None)
    return {'breadcrumbs': crumbs}
