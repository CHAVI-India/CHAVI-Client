from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.utils import timezone

from client_app.models import Patient, DICOMStudy, SiteConfiguration
from dicom_server.models import RemoteDICOMNode, RetrievalJob, AutoRetrievalState
from dicom_server.tasks import (
    _auto_retrieve_patient_node,
    task_auto_retrieve_node,
    task_auto_retrieve_patient_batch,
)


def _fake_async_result():
    result = MagicMock()
    result.id = 'fake-task-id'
    return result


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AutoRetrievalTaskTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test')
        self.patient = self._create_patient('P001')
        self.node = RemoteDICOMNode.objects.create(
            name='node', ae_title='AET', host='localhost', port=104,
            auto_retrieve_enabled=True, auto_retrieve_batch_size=2,
        )

    def _create_patient(self, patient_id, consent=True):
        # .update() bypasses the post_save signal that would otherwise dispatch
        # a real (eager) auto-retrieval task during test fixture setup.
        patient = Patient.objects.create(patient_id=patient_id, chavi_consent=False)
        if consent:
            Patient.objects.filter(pk=patient.pk).update(chavi_consent=True)
            patient.chavi_consent = True
        return patient

    @patch('dicom_server.tasks.task_retrieve_studies')
    @patch('dicom_server.tasks.qr_client.find_studies_for_patient')
    def test_creates_job_for_unknown_study(self, mock_find, mock_retrieve):
        mock_retrieve.delay.return_value = _fake_async_result()
        mock_find.return_value = [
            {'study_instance_uid': '1.2.3', 'study_date': '20240101', 'study_description': '', 'modalities': 'CT', 'instances': 1}
        ]
        result = _auto_retrieve_patient_node(self.node.pk, self.patient.patient_id)
        self.assertEqual(result['new'], 1)
        self.assertTrue(RetrievalJob.objects.filter(patient=self.patient, node=self.node).exists())
        mock_retrieve.delay.assert_called_once()

    @patch('dicom_server.tasks.qr_client.find_studies_for_patient')
    def test_skips_already_known_study(self, mock_find):
        DICOMStudy.objects.create(patient=self.patient, study_instance_uid='1.2.3')
        mock_find.return_value = [
            {'study_instance_uid': '1.2.3', 'study_date': '20240101', 'study_description': '', 'modalities': 'CT', 'instances': 1}
        ]
        result = _auto_retrieve_patient_node(self.node.pk, self.patient.patient_id)
        self.assertEqual(result['new'], 0)
        self.assertFalse(RetrievalJob.objects.exists())

    def test_respects_min_interval(self):
        AutoRetrievalState.objects.create(
            patient=self.patient, node=self.node,
            last_attempt_at=timezone.now(),
        )
        with patch('dicom_server.tasks.qr_client.find_studies_for_patient') as mock_find:
            mock_find.return_value = []
            result = _auto_retrieve_patient_node(self.node.pk, self.patient.patient_id, force=False)
            self.assertTrue(result['skipped'])
            self.assertIn('minimum interval', result['reason'])

    @patch('dicom_server.tasks.qr_client.find_studies_for_patient')
    def test_force_bypasses_interval(self, mock_find):
        AutoRetrievalState.objects.create(
            patient=self.patient, node=self.node,
            last_attempt_at=timezone.now(),
        )
        mock_find.return_value = []
        result = _auto_retrieve_patient_node(self.node.pk, self.patient.patient_id, force=True)
        self.assertFalse(result['skipped'])

    @patch('dicom_server.tasks.task_auto_retrieve_patient_batch.delay')
    def test_node_task_dispatches_batches(self, mock_batch):
        self._create_patient('P002')
        self._create_patient('P003')
        result = task_auto_retrieve_node(self.node.pk)
        self.assertEqual(result['batches'], 2)  # batch_size = 2
        self.assertEqual(mock_batch.call_count, 2)

    @patch('dicom_server.tasks.task_retrieve_studies')
    @patch('dicom_server.tasks.qr_client.find_studies_for_patient')
    def test_batch_task_processes_multiple_patients(self, mock_find, mock_retrieve):
        p2 = self._create_patient('P002')
        mock_retrieve.delay.return_value = _fake_async_result()
        mock_find.return_value = [
            {'study_instance_uid': '1.2.3', 'study_date': '20240101', 'study_description': '', 'modalities': 'CT', 'instances': 1}
        ]
        result = task_auto_retrieve_patient_batch(self.node.pk, [self.patient.patient_id, p2.patient_id])
        self.assertEqual(len(result), 2)
        self.assertEqual(RetrievalJob.objects.count(), 2)

    def test_non_consented_patient_skipped(self):
        p2 = self._create_patient('P002', consent=False)
        result = _auto_retrieve_patient_node(self.node.pk, p2.patient_id)
        self.assertTrue(result['skipped'])
        self.assertFalse(RetrievalJob.objects.exists())
