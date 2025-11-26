#!/usr/bin/env python
# -- coding: utf-8 --

# Python Standard Libraries
import codecs
import csv
import json
import logging
import six
from collections import OrderedDict, defaultdict, Counter
from datetime import datetime
from functools import partial
from statistics import mean, pstdev
from time import time

# Installed packages (via pip)
from capa.capa_problem import LoncapaProblem, LoncapaSystem
from celery import task
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.utils.translation import gettext as _, ugettext_noop
from django.views.generic.base import View
from pytz import UTC
from eol_sso.services.interface import get_user_id_with_indiv_id_list

# Edx dependencies
from common.djangoapps.util.file import course_filename_prefix_generator
from lms.djangoapps.courseware.access import has_access
from lms.djangoapps.courseware.courses import get_course_with_access
from lms.djangoapps.courseware.models import StudentModule
from lms.djangoapps.instructor import permissions
from lms.djangoapps.instructor_task.api_helper import submit_task, AlreadyRunningError
from lms.djangoapps.instructor_task.models import ReportStore
from lms.djangoapps.instructor_task.tasks_base import BaseInstructorTask
from lms.djangoapps.instructor_task.tasks_helper.runner import run_main_task, TaskProgress
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey, UsageKey
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError

logger = logging.getLogger(__name__)

def safe_div(num, den):
    return num / den if den else 0

def task_process_data(request, data):
    course_key = CourseKey.from_string(data['course'])
    task_type = 'Eol_Report_Analytics'
    task_class = process_data
    task_input = {'data': data }
    task_key = "{}_{}".format(task_type, data['course'])

    return submit_task(
        request,
        task_type,
        task_class,
        course_key,
        task_input,
        task_key)

@task(base=BaseInstructorTask, queue='edx.lms.core.low')
def process_data(entry_id, xmodule_instance_args):
    action_name = ugettext_noop('generated')
    task_fn = partial(generate, xmodule_instance_args)

    return run_main_task(entry_id, task_fn, action_name)

def generate(_xmodule_instance_args, _entry_id, course_id, task_input, action_name):
    """
    For a given `course_id`, generate a CSV file containing
    all student answers to a given problem, and store using a `ReportStore`.
    """
    start_time = time()
    start_date = datetime.now(UTC)
    num_reports = 1
    task_progress = TaskProgress(action_name, num_reports, start_time)
    current_step = {'step': 'EolReportAnalytics - Calculating students answers to problem'}
    task_progress.update_task_state(extra_meta=current_step)
    
    data = task_input.get('data')
    students = EolReportAnalyticsView().get_all_enrolled_users(data['course'])

    report_store = ReportStore.from_config('GRADES_DOWNLOAD')
    csv_name = 'Analitica_de_Preguntas'

    report_name = u"{course_prefix}_{csv_name}_{timestamp_str}.csv".format(
        course_prefix=course_filename_prefix_generator(course_id),
        csv_name=csv_name,
        timestamp_str=start_date.strftime("%Y-%m-%d-%H%M")
    )
    output_buffer = ContentFile('')
    if six.PY2:
        output_buffer.write(codecs.BOM_UTF8)
    csvwriter = csv.writer(
            output_buffer,
            delimiter=';',
            dialect='excel')
    student_states = EolReportAnalyticsView().get_all_states(data['block'])
    csvwriter = EolReportAnalyticsView()._build_student_data(data, students, data['block'], student_states, csvwriter)

    current_step = {'step': 'EolReportAnalytics - Uploading CSV'}
    task_progress.update_task_state(extra_meta=current_step)

    output_buffer.seek(0)
    report_store.store(course_id, report_name, output_buffer)
    current_step = {
        'step': 'EolReportAnalytics - CSV uploaded',
        'report_name': report_name,
    }

    return task_progress.update_task_state(extra_meta=current_step)

def _get_utf8_encoded_rows(row):
    """
    Given a list of `rows` containing unicode strings, return a
    new list of rows with those strings encoded as utf-8 for CSV
    compatibility.
    """

    if six.PY2:
        return [six.text_type(item).encode('utf-8') for item in row]
    else:
        return [six.text_type(item) for item in row]

class EolReportAnalyticsView(View):
    """
        Return a csv with progress students
    """
    @transaction.non_atomic_requests
    def dispatch(self, args, **kwargs):
        return super(EolReportAnalyticsView, self).dispatch(args, **kwargs)

    def get(self, request, **kwargs):
        if not request.user.is_anonymous:
            data = self.validate_and_get_data(request)
            if data['course'] is None:
                logger.error("EolReportAnalytics - Falta parametro course o parametro incorrecto, user: {}, course: {}, block: {}".format(request.user, request.GET.get('course', ''), request.GET.get('block', '')))
                return JsonResponse({'error': 'Falta parametro course o parametro incorrecto'})
            elif data['block'] is None:
                logger.error("EolReportAnalytics - Falta parametro block o parametro incorrecto, user: {}, course: {}, block: {}".format(request.user, request.GET.get('course', ''), request.GET.get('block', '')))
                return JsonResponse({'error': 'Falta parametro block o parametro incorrecto'})
            elif data['block'] is False and data['course'] is False:
                logger.error("EolReportAnalytics - El bloque no pertenece al curso, user: {}, course: {}, block: {}".format(request.user, request.GET.get('course', ''), request.GET.get('block', '')))
                return JsonResponse({'error': 'El bloque no pertenece al curso'})
            elif not self.have_permission(request.user, data['course']):
                logger.error("EolReportAnalytics - Usuario no tiene rol para esta funcionalidad, user: {}, course: {}, block: {}".format(request.user, request.GET.get('course', ''), request.GET.get('block', '')))
                return JsonResponse({'error': 'Usuario no tiene rol para esta funcionalidad'})
            data['base_url'] = request.build_absolute_uri('')
            return self.get_context(request, data)
        else:
            logger.error("EolReportAnalytics - User is Anonymous")
        raise Http404()

    def get_context(self, request, data):
        try:
            task = task_process_data(request, data)
            success_status = 'La analitica de preguntas esta siendo creado, en un momento estará disponible para descargar.'
            return JsonResponse({"status": success_status, "task_id": task.task_id})
        except AlreadyRunningError:
            logger.error("EolReportAnalytics - Task Already Running Error, user: {}, data: {}".format(request.user, data))
            return JsonResponse({'error_task': 'AlreadyRunningError'})

    def have_permission(self, user, course_id):
        """
            Verify if the user is instructor
        """
        """
        any([
            request.user.is_staff,
            CourseStaffRole(course_key).has_user(request.user),
            CourseInstructorRole(course_key).has_user(request.user)
        ])
        """
        try:
            course_key = CourseKey.from_string(course_id)
            course = get_course_with_access(user, "load", course_key)
            data_researcher_access = user.has_perm(permissions.CAN_RESEARCH, course_key)
            return bool(has_access(user, 'instructor', course)) or bool(has_access(user, 'staff', course)) or data_researcher_access
        except Exception:
            return False

    def validate_and_get_data(self, request):
        """
            Verify format and course id
        """
        data = {'course': None, 'block': None}
        # valida curso
        if request.GET.get("course", "") != "":
            # valida si existe el curso
            if self.validate_course(request.GET.get("course", "")):
                data['course'] = request.GET.get("course", "")
        if request.GET.get("block", "") != "":
            # valida si existe el block_id
            if self.validate_block(request.GET.get("block", "")):
                data['block'] = request.GET.get("block", "")
        if data['block'] and data['course']:
            id_curso = CourseKey.from_string(request.GET.get("course"))
            block_key = UsageKey.from_string(request.GET.get("block"))
            if block_key.course_key != id_curso:
                data = {'course': False, 'block': False}
        return data

    def validate_course(self, id_curso):
        """
            Verify if course.id exists
        """
        try:
            aux = CourseKey.from_string(id_curso)
            return CourseOverview.objects.filter(id=aux).exists()
        except InvalidKeyError:
            return False

    def validate_block(self, block_id):
        """
            Verify if block_id exists
        """
        try:
            block_key = UsageKey.from_string(block_id)
            if block_key.block_type != 'problem':
                return False
            store = modulestore()
            block_item = store.get_item(block_key)
            return True
        except (InvalidKeyError, ItemNotFoundError) as e:
            return False

    def get_all_states(self, block_id):
        """
            Get all student module
        """
        usage_key = UsageKey.from_string(block_id)
        smdat = StudentModule.objects.filter(course_id=usage_key.course_key, module_state_key=usage_key).order_by('student__username').values('student__username', 'state')
        response = []
        for module in smdat:
            response.append({'username': module['student__username'], 'state': module['state']})

        return response

    def _build_student_data(self, data, students, block, student_states, csvwriter):
        """
            Create list of list to make csv report
        """
        url_base = data['base_url']
        course_id = data['course']
        course_key = CourseKey.from_string(course_id)
        header = ['Username', 'Email', 'Documento_id', 'Intentos']
        analytics = {'users': 0, 'correct': {}, 'incorrect': {}, 'score': []}
        best_quartile = defaultdict(list)
        best_quartile_list = []
        worst_quartile = defaultdict(list)
        worst_quartile_list = []
        quartile = 0
        store = modulestore()
        with store.bulk_operations(course_key):
            block_key = UsageKey.from_string(block)
            block_item = store.get_item(block_key)
            generated_report_data = self.get_report_xblock(block_key, student_states, block_item)
            if generated_report_data is not None:
                quartile = int(len(generated_report_data) / 4)
                jumo_to_url = url_base + reverse('jump_to', kwargs={
                            'course_id': course_id,
                            'location': block})
                aux_headers = self.get_headers(student_states)
                if aux_headers is not None:
                    for i in range(len(aux_headers)):
                        header.append('Pregunta {}'.format(i + 1))
                    header.append('Ptos Obtenidos')
                    header.append('Tolal de la Pregunta')
                    header.append('Nota')
                    csvwriter.writerow(_get_utf8_encoded_rows(header))
                    for response in student_states:
                        if response['username'] not in students:
                            continue
                        # A human-readable location for the current block
                        # A machine-friendly location for the current block
                        # A block that has a single state per user can contain multiple responses
                        # within the same state.
                        if block_key.block_type != 'problem':
                            pass
                        else:
                            user_states = generated_report_data.get(response['username'])
                            if user_states:
                                responses, aux_analytics = self.set_data(
                                        response,
                                        students,
                                        user_states,
                                        aux_headers
                                        )
                                if responses:
                                    analytics['users'] += 1
                                    analytics['score'].append(aux_analytics['score'])
                                    for x in aux_analytics['correct']:
                                        if x in analytics['correct']:
                                            analytics['correct'][x] += 1
                                        else:
                                            analytics['correct'][x] = 1
                                    for x in aux_analytics['incorrect']:
                                        if x in analytics['incorrect']:
                                            analytics['incorrect'][x] += 1
                                        else:
                                            analytics['incorrect'][x] = 1
                                    csvwriter.writerow(_get_utf8_encoded_rows(responses))
                                    #TO DO: optimaze get discriminatory index
                                    best_quartile, best_quartile_list = self.order_best_quartile(best_quartile, best_quartile_list, quartile, aux_analytics)
                                    worst_quartile, worst_quartile_list = self.order_worst_quartile(worst_quartile, worst_quartile_list, quartile, aux_analytics)

        #Analytics Here!
        n_total_students = len(students)
        n_students_answered = analytics['users']
        n_students_not_answered = n_total_students - n_students_answered
        pct_answered = safe_div(n_students_answered, n_total_students)
        pct_not_answered = safe_div(n_students_not_answered, n_total_students)
        csvwriter.writerow([])
        csvwriter.writerow([])
        csvwriter.writerow(['Analitica'])
        csvwriter.writerow([])
        csvwriter.writerow(['','','%'])
        csvwriter.writerow(['Usuarios inscritos', n_total_students])
        csvwriter.writerow(['Cuantos contestaron', n_students_answered, str(pct_answered).replace(".", ",")])
        csvwriter.writerow(['Cuantos no contestaron', n_students_not_answered, str(pct_not_answered).replace(".", ",")])
        if analytics['score']:
            csvwriter.writerow(['Promedio', str(mean(analytics['score'])).replace(".",",")])
            csvwriter.writerow(['Desviacion estandar', str(pstdev(analytics['score'])).replace(".",",")])
        else:
            csvwriter.writerow(['Promedio', 0])
            csvwriter.writerow(['Desviacion estandar', ''])
        mcq = [[],0]
        lcq = [[],0]
        for x in analytics['correct']:
            if mcq[1] > analytics['correct'][x]:
                continue
            if mcq[1] < analytics['correct'][x]:
                mcq[0] = [x]
                mcq[1] = analytics['correct'][x]
            else:
                mcq[0].append(x)
        for x in analytics['incorrect']:
            if lcq[1] > analytics['incorrect'][x]:
                continue
            if lcq[1] < analytics['incorrect'][x]:
                lcq[0] = [x]
                lcq[1] = analytics['incorrect'][x]
            else:
                lcq[0].append(x)

        questions = self.get_questions(generated_report_data)
        if questions:
            csvwriter.writerow([])
            csvwriter.writerow(['', 'Pregunta(s)', 'Correctas', '% de Correctas', 'Incorrectas', '% de Incorrectas'])
            aux = ['Pregunta con mas correctas', '', 0, 0, 0, 0]
            for idq in mcq[0]:
                aux[1] = aux[1] + 'P{} - '.format(aux_headers.index(idq) + 1)
            aux[1] = aux[1][:-3]
            aux[2] = mcq[1]
            aux[3] = str(mcq[1] / analytics['users']).replace(".",",")
            if len(mcq[0]) > 0:
                aux[4] = analytics['incorrect'][mcq[0][0]] if mcq[0][0] in analytics['incorrect'] else '0'
                aux[5] = str(analytics['incorrect'][mcq[0][0]] / analytics['users']).replace(".",",") if mcq[0][0] in analytics['incorrect'] else '0'
            csvwriter.writerow(aux)
            aux = ['Pregunta con menos correctas', '', 0, 0, 0, 0]
            for idq in lcq[0]:
                aux[1] = aux[1] + 'P{} - '.format(aux_headers.index(idq) + 1)
            aux[1] = aux[1][:-3]
            aux[4] = lcq[1]
            aux[5] = str(lcq[1] / analytics['users']).replace(".",",")
            if len(lcq[0]) > 0:
                aux[2] = analytics['correct'][lcq[0][0]] if lcq[0][0] in analytics['correct'] else '0'
                aux[3] = str(analytics['correct'][lcq[0][0]] / analytics['users']).replace(".",",") if lcq[0][0] in analytics['correct'] else '0'
            csvwriter.writerow(aux)
            csvwriter.writerow([])
            csvwriter.writerow([])
            csvwriter.writerow(_get_utf8_encoded_rows(['Preguntas', '', 'Respuesta','Indice de dificultad', '% de correctas', '% de incorrectas', 'Rango indice discriminatorio', 'Indice discriminatorio']))
            
            best, worst = self.get_discriminatory_index(best_quartile, best_quartile_list, worst_quartile, worst_quartile_list, quartile, analytics['users'])
            for x in range(len(aux_headers)):
                row = [
                    'Pregunta {}'.format(x + 1), 
                    questions[aux_headers[x]]['question'],
                    questions[aux_headers[x]]['correct']
                ]
                if aux_headers[x] in analytics['correct']:
                    aux = analytics['correct'][aux_headers[x]] / analytics['users']
                    if aux >= 0.8 and aux <= 1:
                        row.append("Muy fácil")
                    elif aux >= 0.65 and aux < 0.8:
                        row.append("Relativamente fácil")
                    elif aux >= 0.5 and aux < 0.65:
                        row.append("Dificultad adecuada")
                    elif aux >= 0.3 and aux < 0.5:
                        row.append("Relativamente dificil")
                    elif aux >= 0.1 and aux < 0.3:
                        row.append("Dificil")
                    elif aux >= 0 and aux < 0.1:
                        row.append("Muy dificil")
                    else:
                        row.append("")
                    row.append(str(aux).replace(".",","))
                else:
                    row.append("Muy dificil")
                    row.append(0)
                if aux_headers[x] in analytics['incorrect']:
                    row.append(str(analytics['incorrect'][aux_headers[x]] / analytics['users']).replace(".",","))
                else:
                    row.append(0)
                if int(analytics['users']/4) != 0:
                    aux = (best.get(aux_headers[x], 0) - worst.get(aux_headers[x], 0)) / int(analytics['users']/4)
                    if aux >= 0.4 and aux < 1:
                        row.append("Excelente discriminación")
                    elif aux > 0 and aux < 0.4:
                        row.append("Medianamente discriminador")
                    elif aux == 0 or aux == 1:
                        row.append("Nula discriminación")
                    elif aux >= -1 and aux < 0:
                        row.append("Ítem a modificar")
                    else:
                        row.append("")
                    row.append(str(aux).replace(".",","))
                csvwriter.writerow(_get_utf8_encoded_rows(row))
        return csvwriter

    def get_discriminatory_index(self, best_quartile, best_quartile_list, worst_quartile, worst_quartile_list, quartile, answered):
        discriminatory_index = {}
        if quartile != int(answered / 4):
            q = int(answered / 4)
            aux = quartile - q
            for x in range(aux):
                if len(best_quartile[best_quartile_list[x]]) > 1:
                    best_quartile[best_quartile_list[x]].pop()
                else:
                    best_quartile.pop(best_quartile_list[x])
                y = x + q
                if len(worst_quartile[worst_quartile_list[y]]) > 1:
                    worst_quartile[worst_quartile_list[y]].pop()
                else:
                    worst_quartile.pop(worst_quartile_list[y])

        best = Counter(x for xs in best_quartile.values() for xq in xs for x in xq)
        worst = Counter(x for xs in worst_quartile.values() for xq in xs for x in xq)
        return best, worst

    def order_best_quartile(self, best_quartile, best_quartile_list, quartile, aux_analytics):
        if len(best_quartile_list) < quartile:
            best_quartile_list.append(aux_analytics['score'])
            best_quartile[aux_analytics['score']].append(aux_analytics['correct'])
        else:
            if quartile != 0 and best_quartile_list[0] < aux_analytics['score']:
                if len(best_quartile[best_quartile_list[0]]) > 1:
                    best_quartile[best_quartile_list[0]].pop()
                else:
                    best_quartile.pop(best_quartile_list[0])
                best_quartile_list[0] = aux_analytics['score']
                best_quartile[aux_analytics['score']].append(aux_analytics['correct'])
        best_quartile_list.sort()
        return best_quartile, best_quartile_list

    def order_worst_quartile(self, worst_quartile, worst_quartile_list, quartile, aux_analytics):
        if len(worst_quartile_list) < quartile:
            worst_quartile_list.append(aux_analytics['score'])
            worst_quartile[aux_analytics['score']].append(aux_analytics['correct'])
        else:
            if quartile != 0 and worst_quartile_list[-1] > aux_analytics['score']:
                if len(worst_quartile[worst_quartile_list[-1]]) > 1:
                    worst_quartile[worst_quartile_list[-1]].pop()
                else:
                    worst_quartile.pop(worst_quartile_list[-1])
                worst_quartile_list[-1] = aux_analytics['score']
                worst_quartile[aux_analytics['score']].append(aux_analytics['correct'])
        worst_quartile_list.sort()
        return worst_quartile, worst_quartile_list

    def get_headers(self, student_states):
        for response in student_states:
            raw_state = json.loads(response['state'])
            if 'attempts' not in raw_state:
                continue
            return list(raw_state['input_state'].keys())
        return None
    
    def get_questions(self, generated_report_data):
        questions = {}
        for username in generated_report_data:
            if questions:
                break
            for user_state in generated_report_data[username]:
                if _("Correct Answer") in user_state:
                    questions[user_state[_("Answer ID")]] = {'question':user_state[_("Question")].replace(";",""), 'correct':user_state[_("Correct Answer")].replace(";","")}
                else:
                    questions[user_state[_("Answer ID")]] = {'question':user_state[_("Question")].replace(";",""), 'correct':''}
        return questions

    def set_data(self, response, students, user_states, questions_ids):
        """
            Create a row according 
            ['Username', 'Email', 'Documento_id', 'Intentos', 'preg1', 'preg2, ... 'pregN' , 'Nota']
        """
        aux_analytics = defaultdict(list)
        raw_state = json.loads(response['state'])
        if 'attempts' not in raw_state:
            return [], aux_analytics

        # For each response in the block, copy over the basic data like the
        # title, location, block_key and state, and add in the responses
        pts_question = int(raw_state['score']['raw_possible']) / len(user_states)
        responses = [
                response['username'], 
                students[response['username']]['email'], 
                students[response['username']]['indiv_id'],
                raw_state['attempts']
                ]
        aux_response = {}
        for user_state in user_states:
            correct_answer = ''
            if _("Correct Answer") in user_state:
                correct_answer = user_state[_("Correct Answer")].replace(";","")
            aux_response[user_state[_("Answer ID")]] = user_state[_("Answer")].replace(";","")
            if user_state[_("Answer")].replace(";","") == correct_answer:
                aux_analytics['correct'].append(user_state[_("Answer ID")])
            else:
                aux_analytics['incorrect'].append(user_state[_("Answer ID")])
        for x in questions_ids:
            responses.append(aux_response[x])
        responses.append(raw_state['score']['raw_earned'])
        responses.append(raw_state['score']['raw_possible'])
        aux_analytics['score'] = float(raw_state['score']['raw_earned'])/float(raw_state['score']['raw_possible'])
        responses.append(str(float(raw_state['score']['raw_earned'])/float(raw_state['score']['raw_possible'])).replace(".",","))
        return responses, aux_analytics

    def get_all_enrolled_users(self, course_key):
        """
            Get all enrolled student 
        """
        students = OrderedDict()
        enrolled_students = User.objects.filter(
            courseenrollment__course_id=course_key,
            courseenrollment__is_active=1,
            courseenrollment__mode='honor'
        ).order_by('username').values('id', 'username', 'email')
        user_id_list = enrolled_students.values_list('id', flat=True)
        user_indiv_id_list = get_user_id_with_indiv_id_list(user_id_list)
        user_indiv_id_dict = {id: indiv_id for id, indiv_id in user_indiv_id_list}
        for user in enrolled_students:
            indiv_id = user_indiv_id_dict.get(user['id'], '')
            students[user['username']] = {'email': user['email'], 'indiv_id': indiv_id}
        return students

    def get_report_xblock(self, block_key, user_states, block):
        """
        # Blocks can implement the generate_report_data method to provide their own
        # human-readable formatting for user state.
        """
        generated_report_data = defaultdict(list)

        if block_key.block_type != 'problem':
            return None
        elif hasattr(block, 'generate_report_data'):
            try:
                for username, state in self.generate_report_data(user_states, block):
                    generated_report_data[username].append(state)
            except NotImplementedError:
                logger.info('EolReportAnalytics - block {} dont have implemented generate_report_data'.format(str(block_key)))
                pass
        return generated_report_data

    def generate_report_data(self, user_states, block):
        """
        Return a list of student responses to this block in a readable way.
        Arguments:
            user_state_iterator: iterator over UserStateClient objects.
                E.g. the result of user_state_client.iter_all_for_block(block_key)
            limit_responses (int|None): maximum number of responses to include.
                Set to None (default) to include all.
        Returns:
            each call returns a tuple like:
            ("username", {
                           "Question": "2 + 2 equals how many?",
                           "Answer": "Four",
                           "Answer ID": "98e6a8e915904d5389821a94e48babcf_10_1"
            })
        """

        if block.category != 'problem':
            raise NotImplementedError()

        capa_system = LoncapaSystem(
            ajax_url=None,
            # TODO set anonymous_student_id to the anonymous ID of the user which answered each problem
            # Anonymous ID is required for Matlab, CodeResponse, and some custom problems that include
            # '$anonymous_student_id' in their XML.
            # For the purposes of this report, we don't need to support those use cases.
            anonymous_student_id=None,
            cache=None,
            can_execute_unsafe_code=lambda: None,
            get_python_lib_zip=None,
            DEBUG=None,
            filestore=block.runtime.resources_fs,
            i18n=block.runtime.service(block, "i18n"),
            node_path=None,
            render_template=None,
            seed=1,
            STATIC_URL=None,
            xqueue=None,
            matlab_api_key=None,
        )

        for response in user_states:
            user_state = json.loads(response['state'])
            if 'student_answers' not in user_state:
                continue

            lcp = LoncapaProblem(
                problem_text=block.data,
                id=block.location.html_id(),
                capa_system=capa_system,
                # We choose to run without a fully initialized CapaModule
                capa_module=None,
                state={
                    'done': user_state.get('done'),
                    'correct_map': user_state.get('correct_map'),
                    'student_answers': user_state.get('student_answers'),
                    'has_saved_answers': user_state.get('has_saved_answers'),
                    'input_state': user_state.get('input_state'),
                    'seed': user_state.get('seed'),
                },
                seed=user_state.get('seed'),
                # extract_tree=False allows us to work without a fully initialized CapaModule
                # We'll still be able to find particular data in the XML when we need it
                extract_tree=False,
            )

            for answer_id, orig_answers in lcp.student_answers.items():
                # Some types of problems have data in lcp.student_answers that isn't in lcp.problem_data.
                # E.g. formulae do this to store the MathML version of the answer.
                # We exclude these rows from the report because we only need the text-only answer.
                if answer_id.endswith('_dynamath'):
                    continue

                question_text = lcp.find_question_label(answer_id)
                answer_text = lcp.find_answer_text(answer_id, current_answer=orig_answers)
                correct_answer_text = lcp.find_correct_answer_text(answer_id)

                report = {
                    _("Answer ID"): answer_id,
                    _("Question"): question_text,
                    _("Answer"): answer_text,
                }
                if correct_answer_text is not None:
                    report[_("Correct Answer")] = correct_answer_text
                yield (response['username'], report)
