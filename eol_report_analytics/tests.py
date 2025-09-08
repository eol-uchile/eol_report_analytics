#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Python Standard Libraries
from collections import defaultdict
import json

# Installed packages (via pip)
from django.test import Client
from django.urls import reverse
from django.utils.translation import gettext as _
from mock import patch, Mock

# Edx dependencies
from common.djangoapps.student.tests.factories import CourseAccessRoleFactory, UserFactory, CourseEnrollmentFactory
from common.djangoapps.student.roles import CourseInstructorRole
from lms.djangoapps.courseware.models import StudentModule
from opaque_keys.edx.keys import UsageKey
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory
from lms.djangoapps.instructor_task.models import ReportStore

# Internal project dependencies
from .views import EolReportAnalyticsView, generate

class TestEolReportAnalyticsView(ModuleStoreTestCase):
    def setUp(self):
        super(TestEolReportAnalyticsView, self).setUp()
        self.course = CourseFactory.create(
            org='mss',
            course='999',
            display_name='2021',
            emit_signals=True)
        aux = CourseOverview.get_from_id(self.course.id)
        self.block_id = 'block-v1:mss+999+2021+type@problem+block@aecf834d50a34f93a03f43bd20723ed7'
        with patch('common.djangoapps.student.models.cc.User.save'):
            # staff user
            self.client_instructor = Client()
            self.client_student = Client()
            self.user_instructor = UserFactory(
                username='instructor',
                password='12345',
                email='instructor@edx.org',
                is_staff=True)
            role = CourseInstructorRole(self.course.id)
            role.add_users(self.user_instructor)
            self.client_instructor.login(
                username='instructor', password='12345')
            self.student = UserFactory(
                username='student',
                password='test',
                email='student@edx.org')
            # Enroll the student in the course
            CourseEnrollmentFactory(
                user=self.student, course_id=self.course.id, mode='honor')
            self.student2 = UserFactory(
                username='student2',
                password='test',
                email='student2@edx.org')
            # Enroll the student in the course
            CourseEnrollmentFactory(
                user=self.student2, course_id=self.course.id, mode='honor')
            self.client_student.login(
                username='student', password='test')
            # Create and Enroll data researcher user
            self.data_researcher_user = UserFactory(
                username='data_researcher_user',
                password='test',
                email='data.researcher@edx.org')
            CourseEnrollmentFactory(
                user=self.data_researcher_user,
                course_id=self.course.id, mode='audit')
            CourseAccessRoleFactory(
                course_id=self.course.id,
                user=self.data_researcher_user,
                role='data_researcher',
                org=self.course.id.org
            )
            self.client_data_researcher = Client()
            self.assertTrue(self.client_data_researcher.login(username='data_researcher_user', password='test'))

    def _verify_csv_file_report(self, report_store, expected_data):
        """
        Verify course survey data.
        """
        report_csv_filename = report_store.links_for(self.course.id)[0][0]
        report_path = report_store.path_to(self.course.id, report_csv_filename)
        with report_store.storage.open(report_path) as csv_file:
            csv_file_data = csv_file.read()
            # Removing unicode signature (BOM) from the beginning
            csv_file_data = csv_file_data.decode("utf-8-sig")
            for data in expected_data:
                self.assertIn(data, csv_file_data)

    def test_report_analytics_get_url(self):
        """
            Test eol_report_analytics view
        """
        response = self.client_instructor.get(reverse('eol_report_analytics:data'))
        request = response.request
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request['PATH_INFO'], '/eol_report_analytics/data')
    
    @patch("eol_report_analytics.views.get_user_id_doc_id_pairs")
    @patch("eol_report_analytics.views.modulestore")
    @patch("eol_report_analytics.views.EolReportAnalyticsView.get_report_xblock")
    def test_eol_report_analytics_get_all_data(self, report, store_mock, mock_user_id_doc_id_pairs):
        """
            Test eol_report_analytics view data
        """
        mock_user_id_doc_id_pairs.return_value = [(self.student.id, '09472337K')]
        u1_state_1 = {_("Answer ID"): 'answer_id_1',
            _("Question"): 'question_text_1',
            _("Answer"): 'correct_answer_text_1',
            _("Correct Answer") : 'correct_answer_text_1'
            }
        u1_state_2 = {_("Answer ID"): 'answer_id_2',
            _("Question"): 'question_text_2',
            _("Answer"): 'asdadsadsa',
            _("Correct Answer") : 'correct_answer_text_2'
            }
        u2_state_1 = {_("Answer ID"): 'answer_id_1',
            _("Question"): 'question_text_1',
            _("Answer"): 'correct_answer_text_1',
            _("Correct Answer") : 'correct_answer_text_1'
            }
        u2_state_2 = {_("Answer ID"): 'answer_id_2',
            _("Question"): 'question_text_2',
            _("Answer"): 'correct_answer_text_4',
            _("Correct Answer") : 'correct_answer_text_2'
            }
        generated_report_data = {
            self.student.username : [u1_state_1,u1_state_2],
            self.student2.username : [u2_state_1,u2_state_2],
            }               
        report.return_value = generated_report_data
        store_mock = Mock()
        data = {'block': self.block_id, 'course': str(self.course.id), 'base_url':'this_is_a_url'}
        task_input = {'data': data }
        usage_key = UsageKey.from_string(self.block_id)
        module = StudentModule(
            module_state_key=usage_key,
            student=self.student,
            course_id=usage_key.course_key,
            module_type='problem',
            state='{"score": {"raw_earned": 1, "raw_possible": 3}, "seed": 1, "attempts": 1, "input_state": {"answer_id_1": 1, "answer_id_2": 2}}')
        module.save()
        module2 = StudentModule(
            module_state_key=usage_key,
            student=self.student2,
            course_id=usage_key.course_key,
            module_type='problem',
            state='{"score": {"raw_earned": 2, "raw_possible": 3}, "seed": 1, "attempts": 2, "input_state": {"answer_id_1": 1, "answer_id_2": 2}}')
        module2.save()
        with patch('lms.djangoapps.instructor_task.tasks_helper.runner._get_current_task'):
            result = generate(
                None, None, self.course.id,
                task_input, 'Eol_Report_Analytics'
            )
        report_store = ReportStore.from_config(config_name='GRADES_DOWNLOAD')
        header_row = ";".join(['Username', 'Email', 'Documento_id', 'Intentos', 'Pregunta 1', 'Pregunta 2', 'Ptos Obtenidos', 'Tolal de la Pregunta', 'Nota'])
        student_row1 = ";".join([
            self.student.username,
            self.student.email,
            '09472337K',
            '1',
            u1_state_1[_("Answer")],
            u1_state_2[_("Answer")],
            '1','3', str(float(1)/float(3)).replace(".",",")
        ])
        student_row2 = ";".join([
            self.student2.username,
            self.student2.email,
            '',
            '2',
            u2_state_1[_("Answer")],
            u2_state_2[_("Answer")],
            '2','3', str(float(2)/float(3)).replace(".",",")
        ])
        expected_data = [
            header_row, 
            student_row1, 
            student_row2,
            'Usuarios inscritos;2',
            'Cuantos contestaron;2;1,0',
            'Cuantos no contestaron;0;0',
            'Promedio;0,5',
            'Desviacion estandar;0,16666666666666666',
            'Pregunta con mas correctas;P1;2;1,0;0;0',
            'Pregunta con menos correctas;P2;0;0;2;1,0',
            'Preguntas;;Respuesta;Indice de dificultad;% de correctas;% de incorrectas;Rango indice discriminatorio;Indice discriminatorio',
            'Pregunta 1;question_text_1;correct_answer_text_1;Muy fácil;1,0;0',
            'Pregunta 2;question_text_2;correct_answer_text_2;Muy dificil;0;1,0',
            ]
        self._verify_csv_file_report(report_store, expected_data)

    @patch("eol_report_analytics.views.get_user_id_doc_id_pairs")
    def test_get_enrolled_users_with_doc_id(self, mock_user_id_doc_id_pairs):
        """
            Test that doc_id is being added correctly to enrolled users, in the case when one of the
            students has a doc_id associated to it.
        """
        mock_user_id_doc_id_pairs.return_value = [(self.student.id, '09472337K')]
        enrolled_users = EolReportAnalyticsView().get_all_enrolled_users(self.course.id)
        self.assertEqual(enrolled_users[self.student.username]['doc_id'], '09472337K')
        self.assertEqual(enrolled_users[self.student2.username]['doc_id'], '')

    @patch("eol_report_analytics.views.get_user_id_doc_id_pairs")
    def test_get_enrolled_users_without_doc_id(self, mock_user_id_doc_id_pairs):
        """
            Test that doc_id is being set correctly in the case when no user has a doc_id associated.
        """
        mock_user_id_doc_id_pairs.return_value = []
        enrolled_users = EolReportAnalyticsView().get_all_enrolled_users(self.course.id)
        self.assertEqual(enrolled_users[self.student.username]['doc_id'], '')
        self.assertEqual(enrolled_users[self.student2.username]['doc_id'], '')

    @patch("eol_report_analytics.views.get_user_id_doc_id_pairs")
    @patch("eol_report_analytics.views.modulestore")
    @patch("eol_report_analytics.views.EolReportAnalyticsView.get_report_xblock")
    def test_eol_report_analytics_get_all_data_correct(self, report, store_mock, mock_user_id_doc_id_pairs):
        """
            Test eol_report_analytics view data
        """
        mock_user_id_doc_id_pairs.return_value = []
        u1_state_1 = {_("Answer ID"): 'answer_id_1',
            _("Question"): 'question_text_1',
            _("Answer"): 'correct_answer_text_1',
            _("Correct Answer") : 'correct_answer_text_1'
            }
        u1_state_2 = {_("Answer ID"): 'answer_id_2',
            _("Question"): 'question_text_2',
            _("Answer"): 'correct_answer_text_2',
            _("Correct Answer") : 'correct_answer_text_2'
            }
        u2_state_1 = {_("Answer ID"): 'answer_id_1',
            _("Question"): 'question_text_1',
            _("Answer"): 'correct_answer_text_1',
            _("Correct Answer") : 'correct_answer_text_1'
            }
        u2_state_2 = {_("Answer ID"): 'answer_id_2',
            _("Question"): 'question_text_2',
            _("Answer"): 'correct_answer_text_2',
            _("Correct Answer") : 'correct_answer_text_2'
            }
        generated_report_data = {
            self.student.username : [u1_state_1,u1_state_2],
            self.student2.username : [u2_state_1,u2_state_2],
            }               
        report.return_value = generated_report_data
        store_mock = Mock()
        data = {'block': self.block_id, 'course': str(self.course.id), 'base_url':'this_is_a_url'}
        task_input = {'data': data }
        usage_key = UsageKey.from_string(self.block_id)
        module = StudentModule(
            module_state_key=usage_key,
            student=self.student,
            course_id=usage_key.course_key,
            module_type='problem',
            state='{"score": {"raw_earned": 3, "raw_possible": 3}, "seed": 1, "attempts": 1, "input_state": {"answer_id_1": 1, "answer_id_2": 2}}')
        module.save()
        module2 = StudentModule(
            module_state_key=usage_key,
            student=self.student2,
            course_id=usage_key.course_key,
            module_type='problem',
            state='{"score": {"raw_earned": 3, "raw_possible": 3}, "seed": 1, "attempts": 2, "input_state": {"answer_id_1": 1, "answer_id_2": 2}}')
        module2.save()
        with patch('lms.djangoapps.instructor_task.tasks_helper.runner._get_current_task'):
            result = generate(
                None, None, self.course.id,
                task_input, 'Eol_Report_Analytics'
            )
        report_store = ReportStore.from_config(config_name='GRADES_DOWNLOAD')
        header_row = ";".join(['Username', 'Email', 'Documento_id', 'Intentos', 'Pregunta 1', 'Pregunta 2', 'Ptos Obtenidos', 'Tolal de la Pregunta', 'Nota'])
        student_row1 = ";".join([
            self.student.username,
            self.student.email,
            '',
            '1',
            u1_state_1[_("Answer")],
            u1_state_2[_("Answer")],
            '3','3', '1,0'
        ])
        student_row2 = ";".join([
            self.student2.username,
            self.student2.email,
            '',
            '2',
            u2_state_1[_("Answer")],
            u2_state_2[_("Answer")],
            '3','3', '1,0'
        ])
        expected_data = [
            header_row, 
            student_row1, 
            student_row2,
            'Usuarios inscritos;2',
            'Cuantos contestaron;2;1,0',
            'Cuantos no contestaron;0;0',
            'Promedio;1,0',
            'Desviacion estandar;0',
            'Pregunta con mas correctas;P1 - P2;2;1,0;0;0',
            'Pregunta con menos correctas;;0;0;0;0',
            'Preguntas;;Respuesta;Indice de dificultad;% de correctas;% de incorrectas;Rango indice discriminatorio;Indice discriminatorio',
            'Pregunta 1;question_text_1;correct_answer_text_1;Muy fácil;1,0;0',
            'Pregunta 2;question_text_2;correct_answer_text_2;Muy fácil;1,0;0',
            ]
        self._verify_csv_file_report(report_store, expected_data)

    @patch("eol_report_analytics.views.modulestore")
    @patch("eol_report_analytics.views.EolReportAnalyticsView.get_report_xblock")
    def test_eol_report_analytics_get_no_responses(self, report, store_mock):
        """
            Test eol_report_analytics view data no student responses
        """
        generated_report_data = defaultdict(list)            
        report.return_value = generated_report_data
        store_mock = Mock()
        data = {'block': self.block_id, 'course': str(self.course.id), 'base_url':'this_is_a_url'}
        task_input = {'data': data}
        usage_key = UsageKey.from_string(self.block_id)
        module = StudentModule(
            module_state_key=usage_key,
            student=self.student,
            course_id=usage_key.course_key,
            module_type='problem',
            state='{}')
        module.save()
        with patch('lms.djangoapps.instructor_task.tasks_helper.runner._get_current_task'):
            result = generate(
                None, None, self.course.id,
                task_input, 'Eol_Report_Analytics'
            )
        report_store = ReportStore.from_config(config_name='GRADES_DOWNLOAD')
        expected_data = [
            'Cuantos contestaron;0',
            'Cuantos no contestaron;2',
            'Promedio;0',
            'Desviacion estandar'
            ]
        self._verify_csv_file_report(report_store, expected_data)

    @patch("eol_report_analytics.views.modulestore")
    def test_eol_report_analytics_no_data_course(self, store_mock):
        """
            Test eol_report_analytics view no exitst course params
        """
        store_mock = Mock()
        data = {
            'block':self.block_id
        }
        response = self.client_instructor.get(reverse('eol_report_analytics:data'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Falta parametro course o parametro incorrecto'})

    @patch("eol_report_analytics.views.modulestore")
    def test_eol_report_analytics_course_no_exists(self, store_mock):
        """
            Test eol_report_analytics view when course_no_exists
        """
        store_mock = Mock()
        data = {
            'block':self.block_id,
            'course': 'course-v1:eol+test101+2020'
        }
        response = self.client_instructor.get(reverse('eol_report_analytics:data'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Falta parametro course o parametro incorrecto'})

    def test_eol_report_analytics_no_data_block(self):
        """
            Test eol_report_analytics view no exitst block params
        """
        data = {
            'course':str(self.course.id)
        }
        response = self.client_instructor.get(reverse('eol_report_analytics:data'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Falta parametro block o parametro incorrecto'})

    def test_eol_report_analytics_block_no_exists(self):
        """
            Test eol_report_analytics view when block no exists
        """
        data = {
            'block':self.block_id,
            'course': str(self.course.id)
        }
        response = self.client_instructor.get(reverse('eol_report_analytics:data'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Falta parametro block o parametro incorrecto'})

    def test_eol_report_analytics_block_no_problem(self):
        """
            Test eol_report_analytics view when block type is not problem type
        """
        data = {
            'block':'block-v1:mss+999+2021+type@scorm+block@aecf834d50a34f93a03f43bd20723ed7',
            'course': str(self.course.id)
        }
        response = self.client_instructor.get(reverse('eol_report_analytics:data'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Falta parametro block o parametro incorrecto'})

    def test_eol_report_analytics_get_user_is_anonymous(self):
        """
            Test eol_report_analytics view when user is anonymous
        """
        client = Client()
        response = self.client.get(reverse('eol_report_analytics:data'))
        request = response.request
        self.assertEqual(response.status_code, 404)

    @patch("eol_report_analytics.views.EolReportAnalyticsView.validate_and_get_data")
    def test_eol_report_analytics_get_user_no_permission(self, data_mock):
        """
            Test eol_report_analytics view when user is a student
        """
        usage_key = UsageKey.from_string(self.block_id)
        data = {
            'block':self.block_id,
            'course': str(usage_key.course_key)
        }
        data_mock.return_value = data
        response = self.client_student.get(reverse('eol_report_analytics:data'), data)
        request = response.request
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Usuario no tiene rol para esta funcionalidad'})

    @patch("eol_report_analytics.views.EolReportAnalyticsView.have_permission")
    @patch("eol_report_analytics.views.EolReportAnalyticsView.validate_and_get_data")
    def test_eol_report_analytics_get_data_researcher(self, data_mock, permission_mock):
        """
            Test eol_report_analytics view when user is data researcher
        """
        permission_mock.return_value = True
        usage_key = UsageKey.from_string(self.block_id)
        data = {
            'block':self.block_id,
            'course': str(usage_key.course_key)
        }
        data_mock.return_value = data
        response = self.client_data_researcher.get(reverse('eol_report_analytics:data'), data)
        request = response.request
        r = json.loads(response._container[0].decode())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(r['status'], 'La analitica de preguntas esta siendo creado, en un momento estará disponible para descargar.')
    
    def test_order_best_quartile(self):
        """
            test order_best_quartile
        """
        scores = [1,1,1,1,1,1,0.75,1,0.75,1,0.75,1,1,1,1,1,1,1,1,1,1,0.75,1,1,1,1,1,1,1,1,1,1,1,1,0.75,0.75,1,0.5,1,1,1,0.25,1,1,1,1,1,1,0.75,0.75,1,1,1,0.75,1,1,1,0.75,1,1,1,1,0.75]
        quartile = int(len(scores) / 4)
        best_quartile = defaultdict(list)
        best_quartile_list = []
        for x in scores:
            aux_analytics = {'score': x, 'correct': ['a{}'.format(x)]}
            best_quartile, best_quartile_list = EolReportAnalyticsView().order_best_quartile(best_quartile, best_quartile_list, quartile, aux_analytics)
        expected_best_quartile = defaultdict(list)
        expected_best_quartile[1] = [['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1'],['a1']]
        self.assertEqual(best_quartile, expected_best_quartile)
        self.assertEqual(best_quartile_list, [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1])

    def test_order_worst_quartile(self):
        """
            test order_worst_quartile
        """
        scores = [1,1,1,1,1,1,0.75,1,0.75,1,0.75,1,1,1,1,1,1,1,1,1,1,0.75,1,1,1,1,1,1,1,1,1,1,1,1,0.75,0.75,1,0.5,1,1,1,0.25,1,1,1,1,1,1,0.75,0.75,1,1,1,0.75,1,1,1,0.75,1,1,1,1,0.75]
        quartile = int(len(scores) / 4)
        worst_quartile = defaultdict(list)
        worst_quartile_list = []
        for x in scores:
            aux_analytics = {'score': x, 'correct': ['a{}'.format(x)]}
            worst_quartile, worst_quartile_list = EolReportAnalyticsView().order_worst_quartile(worst_quartile, worst_quartile_list, quartile, aux_analytics)
        expected_worst_quartile = defaultdict(list)
        expected_worst_quartile[1] = [['a1'],['a1']]
        expected_worst_quartile[0.75] = [['a0.75'],['a0.75'],['a0.75'],['a0.75'],['a0.75'],['a0.75'],['a0.75'],['a0.75'],['a0.75'],['a0.75'],['a0.75']]
        expected_worst_quartile[0.5] = [['a0.5']]
        expected_worst_quartile[0.25] = [['a0.25']]
        self.assertEqual(worst_quartile, expected_worst_quartile)
        self.assertEqual(worst_quartile_list, [0.25,0.5,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,1,1])
    
    def test_get_discriminatory_index(self):
        """
            test get_discriminatory_index
        """
        scores = [1,1,1,1,1,1,0.75,1,0.75,1,0.75,1,1,1,1,1,1,1,1,1,1,0.75,1,1,1,1,1,1,1,1,1,1,1,1,0.75,0.75,1,0.5,1,1,1,0.25,1,1,1,1,1,1,0.75,0.75,1,1,1,0.75,1,1,1,0.75,1,1,1,1,0.75]
        quartile = int(len(scores) / 4)
        best_quartile = defaultdict(list)
        best_quartile[1] = [['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d']]
        worst_quartile = defaultdict(list)
        worst_quartile[1] = [['a','b','c','d'],['a','b','c','d']]
        worst_quartile[0.75] = [['b','c','d'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c']]
        worst_quartile[0.5] = [['b','c']]
        worst_quartile[0.25] = [['c']]
        best_quartile_list = [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]
        worst_quartile_list = [0.25,0.5,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,1,1]
        best, worst = EolReportAnalyticsView().get_discriminatory_index(best_quartile, best_quartile_list, worst_quartile, worst_quartile_list, quartile, len(scores))
        self.assertEqual((best.get('a', 0) - worst.get('a', 0)) / int(len(scores)/4), (15-12)/int(63/4))
        self.assertEqual((best.get('b', 0) - worst.get('b', 0)) / int(len(scores)/4), (15-14)/int(63/4))
        self.assertEqual((best.get('c', 0) - worst.get('c', 0)) / int(len(scores)/4), (15-15)/int(63/4))
        self.assertEqual((best.get('d', 0) - worst.get('d', 0)) / int(len(scores)/4), (15-3)/int(63/4))
    
    def test_get_discriminatory_index_diff_quartile(self):
        """
            test get_discriminatory_index
        """
        scores = [1,1,1,1,1,1,0.75,1,0.75,1,0.75,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0.75,1,1,1,1,1,1,1,1,1,1,1,1,0.75,0.75,1,0.5,1,1,1,0.25,1,1,1,1,1,1,0.75,0.75,1,1,1,0.75,1,1,1,0.75,1,1,1,1,0.75]
        quartile = int(len(scores) / 4)
        answered = 63
        best_quartile = defaultdict(list)
        best_quartile[1] = [['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d']]
        worst_quartile = defaultdict(list)
        worst_quartile[1] = [['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d'],['a','b','c','d']]
        worst_quartile[0.75] = [['b','c','d'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c'],['a','b','c']]
        worst_quartile[0.5] = [['b','c']]
        worst_quartile[0.25] = [['c']]
        best_quartile_list = [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]
        worst_quartile_list = [0.25,0.5,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,0.75,1,1,1,1,1]
        best, worst = EolReportAnalyticsView().get_discriminatory_index(best_quartile, best_quartile_list, worst_quartile, worst_quartile_list, quartile, 63)
        self.assertEqual((best.get('a', 0) - worst.get('a', 0)) / int(answered/4), (15-12)/int(answered/4))
        self.assertEqual((best.get('b', 0) - worst.get('b', 0)) / int(answered/4), (15-14)/int(answered/4))
        self.assertEqual((best.get('c', 0) - worst.get('c', 0)) / int(answered/4), (15-15)/int(answered/4))
        self.assertEqual((best.get('d', 0) - worst.get('d', 0)) / int(answered/4), (15-3)/int(answered/4))
