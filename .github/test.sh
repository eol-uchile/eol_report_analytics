#!/bin/dash
pip install -e git+https://github.com/eol-uchile/uchileedxlogin@dcd9131ec2bb8d0fbe30f51251ef44a5f8a14af9#egg=uchileedxlogin
pip install -e /openedx/requirements/eol_report_analytics

cd /openedx/requirements/eol_report_analytics
cp /openedx/edx-platform/setup.cfg .
mkdir test_root
cd test_root/
ln -s /openedx/staticfiles .

cd /openedx/requirements/eol_report_analytics

DJANGO_SETTINGS_MODULE=lms.envs.test EDXAPP_TEST_MONGO_HOST=mongodb pytest eol_report_analytics/tests.py