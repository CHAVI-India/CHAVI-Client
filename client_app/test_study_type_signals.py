from unittest.mock import patch
from django.test import TestCase

from client_app.models import Patient, SiteConfiguration
from dicom_server.models import RemoteDICOMNode


class PatientAutoRetrievalSignalTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test')
        RemoteDICOMNode.objects.create(
            name='node', ae_title='AET', host='localhost', port=104,
            auto_retrieve_enabled=True,
        )

    @patch('client_app.signals.task_auto_retrieve_patient')
    def test_creating_consented_patient_triggers_retrieval(self, mock_task):
        with self.captureOnCommitCallbacks(execute=True):
            Patient.objects.create(patient_id='P001', chavi_consent=True)
        self.assertTrue(mock_task.delay.called)
        mock_task.delay.assert_called_with('P001')

    @patch('client_app.signals.task_auto_retrieve_patient')
    def test_updating_consent_triggers_retrieval(self, mock_task):
        p = Patient.objects.create(patient_id='P001', chavi_consent=False)
        mock_task.delay.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            p.chavi_consent = True
            p.save()
        self.assertTrue(mock_task.delay.called)

    @patch('client_app.signals.task_auto_retrieve_patient')
    def test_unconsented_patient_does_not_trigger(self, mock_task):
        with self.captureOnCommitCallbacks(execute=True):
            Patient.objects.create(patient_id='P001', chavi_consent=False)
        self.assertFalse(mock_task.delay.called)

    @patch('client_app.signals.task_auto_retrieve_patient')
    def test_update_without_consent_change_does_not_trigger(self, mock_task):
        p = Patient.objects.create(patient_id='P001', chavi_consent=True)
        mock_task.delay.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            p.save()
        self.assertFalse(mock_task.delay.called)

    @patch('client_app.signals.task_auto_retrieve_patient')
    def test_no_enabled_node_does_not_dispatch(self, mock_task):
        RemoteDICOMNode.objects.all().update(auto_retrieve_enabled=False)
        with self.captureOnCommitCallbacks(execute=True):
            Patient.objects.create(patient_id='P001', chavi_consent=True)
        self.assertFalse(mock_task.delay.called)
