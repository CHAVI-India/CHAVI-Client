from unittest.mock import patch
from django.test import TestCase

from client_app.models import Patient, SiteConfiguration


class PatientAutoRetrievalSignalTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test')

    @patch('dicom_server.tasks.task_auto_retrieve_patient')
    def test_creating_consented_patient_triggers_retrieval(self, mock_task):
        Patient.objects.create(patient_id='P001', chavi_consent=True)
        self.assertTrue(mock_task.delay.called)
        mock_task.delay.assert_called_with('P001')

    @patch('dicom_server.tasks.task_auto_retrieve_patient')
    def test_updating_consent_triggers_retrieval(self, mock_task):
        p = Patient.objects.create(patient_id='P001', chavi_consent=False)
        mock_task.delay.reset_mock()
        p.chavi_consent = True
        p.save()
        self.assertTrue(mock_task.delay.called)

    @patch('dicom_server.tasks.task_auto_retrieve_patient')
    def test_unconsented_patient_does_not_trigger(self, mock_task):
        Patient.objects.create(patient_id='P001', chavi_consent=False)
        self.assertFalse(mock_task.delay.called)

    @patch('dicom_server.tasks.task_auto_retrieve_patient')
    def test_update_without_consent_change_does_not_trigger(self, mock_task):
        p = Patient.objects.create(patient_id='P001', chavi_consent=True)
        mock_task.delay.reset_mock()
        p.save()
        self.assertFalse(mock_task.delay.called)
