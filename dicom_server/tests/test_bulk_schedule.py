"""Tests for scheduled bulk retrieval: model, selection criteria service,
dispatch/schedule tasks, form, and views."""
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from unittest import mock

from django.test import override_settings

from client_app.models import Patient, SiteConfiguration
from dicom_server.models import (
    BulkRetrievalSchedule, RemoteDICOMNode, RetrievalBatch,
    RetrievalBatchPatient, RetrievalJob,
)
from dicom_server.tasks import (
    _aggregate_retrieval_batch, _prepare_bulk_schedule_batch,
    task_bulk_schedule_run,
)


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


def _fake_studies(uids, already_local=()):
    local = set(already_local)
    return [
        {'study_instance_uid': u, 'study_date': '20240101',
         'study_description': '', 'modalities': 'CT', 'instances': 1,
         'remote_patient_id': 'P001', 'already_local': u in local}
        for u in uids
    ], []


class PrepareBatchTests(ModelSetupMixin, TestCase):
    def test_one_row_per_consented_patient(self):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        p_con = self._patient('PC')
        p_no = self._patient('PN', consent=False)
        s.patients.set([p_con, p_no])
        batch, patients = _prepare_bulk_schedule_batch(s)
        self.assertIsInstance(batch, RetrievalBatch)
        self.assertEqual(batch.node_id, self.node.pk)
        self.assertEqual([p.patient_id for p in patients], ['PC'])
        self.assertEqual(batch.patients.count(), 1)


class AggregateTests(ModelSetupMixin, TestCase):
    def _batch_with_jobs(self):
        batch = RetrievalBatch.objects.create(node=self.node)
        p1 = self._patient('A'); p2 = self._patient('B'); p3 = self._patient('C')
        for p, status, instances in [
            (p1, 'SUCCESS', 5), (p2, 'PARTIAL', 2), (p3, 'FAILED', 0),
        ]:
            j = RetrievalJob.objects.create(
                node=self.node, patient=p, status=status,
                instances_received=instances, batch=batch,
            )
            RetrievalBatchPatient.objects.create(
                batch=batch, patient=p, selected=True, job=j,
            )
        return batch

    def test_aggregate_mixed(self):
        batch = self._batch_with_jobs()
        final, summary = _aggregate_retrieval_batch(batch)
        self.assertEqual(final, 'PARTIAL')
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['instances'], 7)
        self.assertEqual(sorted(summary['succeeded']), ['A'])
        self.assertEqual(sorted(summary['failed']), ['C'])


class RunTaskTests(ModelSetupMixin, TestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @mock.patch('dicom_server.tasks.task_bulk_schedule_finalize_query', create=True)
    @mock.patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_creates_batch_and_dispatches(self, mock_find, mock_final):
        mock_find.return_value = _fake_studies(['1.1'])
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        s.patients.set([self._patient('P001')])
        task_bulk_schedule_run(schedule_id=s.pk)
        s.refresh_from_db()
        self.assertIsNotNone(s.last_batch_id)
        self.assertEqual(s.last_batch.patients.count(), 1)
        self.assertTrue(s.last_batch.query_group_id)
        mock_find.assert_called()
        mock_final.s.assert_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @mock.patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_inactive_node_skips(self, mock_find):
        self.node.is_active = False
        self.node.save()
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        s.patients.set([self._patient('P001')])
        res = task_bulk_schedule_run(schedule_id=s.pk)
        self.assertTrue(res.get('skipped'))
        self.assertFalse(RetrievalBatch.objects.exists())
