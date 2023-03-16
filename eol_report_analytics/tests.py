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
from opaque_keys.edx.locator import CourseLocator
from common.djangoapps.student.tests.factories import CourseEnrollmentAllowedFactory, UserFactory, CourseEnrollmentFactory
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.student.roles import CourseInstructorRole, CourseStaffRole
from common.djangoapps.student.tests.factories import CourseAccessRoleFactory
from .views import EolReportAnalyticsView, generate
#from .utils import get_data_course
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
        super(TestXblockCompletionView, self).setUp()
        self.course = CourseFactory.create(
            org='mss',
            course='999',
            display_name='2021',
            emit_signals=True)
        aux = CourseOverview.get_from_id(self.course.id)

    def test_test(self):
        pass
