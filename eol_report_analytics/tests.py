#!/usr/bin/env python
# -*- coding: utf-8 -*-
from mock import patch, Mock, MagicMock
from collections import namedtuple
from django.urls import reverse
from django.test import TestCase, Client
from django.test import Client
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from urllib.parse import parse_qs
from collections import OrderedDict, defaultdict
from opaque_keys.edx.locator import CourseLocator
from opaque_keys.edx.keys import CourseKey, UsageKey, LearningContextKey
from common.djangoapps.student.tests.factories import CourseEnrollmentAllowedFactory, UserFactory, CourseEnrollmentFactory
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.student.roles import CourseInstructorRole, CourseStaffRole
from common.djangoapps.student.tests.factories import CourseAccessRoleFactory
from .views import EolReportAnalyticsView, generate
from rest_framework_jwt.settings import api_settings
from django.test.utils import override_settings
from django.utils.translation import gettext as _
from lms.djangoapps.instructor_task.models import ReportStore
import re
import json
import urllib.parse
import uuid


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
    
    @patch("eol_report_analytics.views.modulestore")
    @patch("eol_report_analytics.views.EolReportAnalyticsView.get_report_xblock")
    def test_eol_report_analytics_get_all_data(self, report, store_mock):
        """
            Test eol_report_analytics view data
        """
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
        from lms.djangoapps.courseware.models import StudentModule
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
        header_row = ",".join(['Username', 'Email', 'Run', 'Intentos', 'Pregunta 1', 'Pregunta 2', 'Ptos Obtenidos', 'Tolal de la Pregunta', 'Nota'])
        student_row1 = ",".join([
            self.student.username,
            self.student.email,
            '',
            '1',
            u1_state_1[_("Answer")],
            u1_state_2[_("Answer")],
            '1','3', str(float(1)/float(3))
        ])
        student_row2 = ",".join([
            self.student2.username,
            self.student2.email,
            '',
            '2',
            u2_state_1[_("Answer")],
            u2_state_2[_("Answer")],
            '2','3', str(float(2)/float(3))
        ])
        expected_data = [
            header_row, 
            student_row1, 
            student_row2,
            'Usuarios inscritos,2',
            'Cuantos contestaron,2,1.0',
            'Cuantos no contestaron,0,0',
            'Promedio,0.5',
            'Desviacion estandar,0.16666666666666666',
            'Pregunta con mas correctas,1,2,1.0,0,0',
            'Pregunta con menos correctas,2,0,0,2,1.0',
            'Preguntas,,Respuesta,% de correctas,% de incorrectas',
            'Pregunta 1,question_text_1,correct_answer_text_1,1.0,0',
            'Pregunta 2,question_text_2,correct_answer_text_2,0,1.0',
            ]
        self._verify_csv_file_report(report_store, expected_data)

    @patch("eol_report_analytics.views.modulestore")
    @patch("eol_report_analytics.views.EolReportAnalyticsView.get_report_xblock")
    def test_eol_report_analytics_get_all_data_correct(self, report, store_mock):
        """
            Test eol_report_analytics view data
        """
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
        from lms.djangoapps.courseware.models import StudentModule
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
        header_row = ",".join(['Username', 'Email', 'Run', 'Intentos', 'Pregunta 1', 'Pregunta 2', 'Ptos Obtenidos', 'Tolal de la Pregunta', 'Nota'])
        student_row1 = ",".join([
            self.student.username,
            self.student.email,
            '',
            '1',
            u1_state_1[_("Answer")],
            u1_state_2[_("Answer")],
            '3','3', '1.0'
        ])
        student_row2 = ",".join([
            self.student2.username,
            self.student2.email,
            '',
            '2',
            u2_state_1[_("Answer")],
            u2_state_2[_("Answer")],
            '3','3', '1.0'
        ])
        expected_data = [
            header_row, 
            student_row1, 
            student_row2,
            'Usuarios inscritos,2',
            'Cuantos contestaron,2,1.0',
            'Cuantos no contestaron,0,0',
            'Promedio,1.0',
            'Desviacion estandar,0',
            'Pregunta con mas correctas,1 - 2,2,1.0,0,0',
            'Pregunta con menos correctas,,0,0,0,0',
            'Preguntas,,Respuesta,% de correctas,% de incorrectas',
            'Pregunta 1,question_text_1,correct_answer_text_1,1.0,0',
            'Pregunta 2,question_text_2,correct_answer_text_2,1.0,0',
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
        from lms.djangoapps.courseware.models import StudentModule
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
            'Cuantos contestaron,0',
            'Cuantos no contestaron,2',
            'Promedio,0',
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