"""Tests for scheduled bulk retrieval: model, selection criteria service,
dispatch/schedule tasks, form, and views."""
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from client_app.models import Patient, SiteConfiguration
from dicom_server.models import BulkRetrievalSchedule, RemoteDICOMNode


class ModelSetupMixin:
    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test',
        )
        cls.node = RemoteDICOMNode.objects.create(
            name='Stub PACS', ae_title='STUBPACS', host='127.0.0.1', port=104,
        )

    def _patient(self, patient_id='P001', consent=True):
        p = Patient.objects.create(patient_id=patient_id, gender='Female')
        if consent:
            Patient.objects.filter(pk=p.pk).update(chavi_consent=True)
            p.chavi_consent = True
        return p


class BulkRetrievalScheduleModelTests(ModelSetupMixin, TestCase):
    def test_one_off_defaults(self):
        run_at = timezone.now() + timedelta(hours=2)
        s = BulkRetrievalSchedule.objects.create(
            name='nightly-ish', node=self.node, mode='ONE_OFF', run_at=run_at,
        )
        s.patients.set([self._patient()])
        self.assertEqual(s.max_concurrent_patients, 2)
        self.assertTrue(s.retrieve_new_only)
        self.assertEqual(s.beat_name, f'dicom-bulk-schedule-{s.pk}')

    def test_crontab_tuple(self):
        s = BulkRetrievalSchedule(
            name='x', node=self.node, mode='PERIODIC',
            minute='30', hour='2', day_of_week='*',
            day_of_month='*', month_of_year='*',
        )
        self.assertEqual(s.crontab_tuple, ('30', '2', '*', '*', '*'))

    def test_invalid_cron_field_rejected(self):
        s = BulkRetrievalSchedule(
            name='x', node=self.node, mode='PERIODIC', minute='61x',
        )
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_one_off_requires_run_at(self):
        s = BulkRetrievalSchedule(name='x', node=self.node, mode='ONE_OFF')
        with self.assertRaises(ValidationError):
            s.full_clean()
