"""Frontend tests: permission gating, config/node management, retrieval dispatch."""
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from client_app.models import Patient, SiteConfiguration
from dicom_server.models import (
    DICOMServerConfiguration, RemoteDICOMNode, RetrievalJob,
)


class DicomFrontendTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test Hospital')
        cls.patient = Patient.objects.create(patient_id='MR/25/004771', gender='Female')
        cls.staff = User.objects.create_user('staff', password='pw', is_staff=True)
        cls.perm_user = User.objects.create_user('qruser', password='pw')
        cls.perm_user.user_permissions.add(
            Permission.objects.get(
                codename='add_dicomstudy', content_type__app_label='client_app',
            )
        )
        cls.plain_user = User.objects.create_user('plain', password='pw')
        cls.node = RemoteDICOMNode.objects.create(
            name='Stub PACS', ae_title='STUBPACS', host='127.0.0.1',
            port=104, prefer_c_get=True,
        )


class TestPermissionGating(DicomFrontendTestCase):
    QR_URLS = ['dashboard', 'retrieve', 'job_list']
    STAFF_URLS = ['config_edit', 'node_list', 'node_create']

    def test_anonymous_redirected_to_login(self):
        for name in self.QR_URLS + self.STAFF_URLS:
            resp = self.client.get(reverse(f'dicom_server:{name}'))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn('/accounts/login/', resp.url, name)

    def test_anonymous_detail_and_echo_redirected(self):
        resp = self.client.get(reverse('dicom_server:job_detail', args=[1]))
        self.assertEqual(resp.status_code, 302)
        resp = self.client.post(reverse('dicom_server:node_echo', args=[self.node.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_plain_user_denied_everywhere(self):
        self.client.force_login(self.plain_user)
        for name in self.QR_URLS + self.STAFF_URLS:
            resp = self.client.get(reverse(f'dicom_server:{name}'))
            self.assertEqual(resp.status_code, 403, name)

    def test_perm_user_can_access_qr_but_not_staff_pages(self):
        self.client.force_login(self.perm_user)
        for name in self.QR_URLS:
            resp = self.client.get(reverse(f'dicom_server:{name}'))
            self.assertEqual(resp.status_code, 200, name)
        for name in self.STAFF_URLS:
            resp = self.client.get(reverse(f'dicom_server:{name}'))
            self.assertEqual(resp.status_code, 403, name)

    def test_staff_without_perm_denied_qr_pages(self):
        # is_staff alone does not grant retrieval — the permission is required.
        self.client.force_login(self.staff)
        for name in self.QR_URLS:
            resp = self.client.get(reverse(f'dicom_server:{name}'))
            self.assertEqual(resp.status_code, 403, name)
        for name in self.STAFF_URLS:
            resp = self.client.get(reverse(f'dicom_server:{name}'))
            self.assertEqual(resp.status_code, 200, name)


class TestConfigView(DicomFrontendTestCase):
    def test_staff_can_update_config(self):
        self.client.force_login(self.staff)
        resp = self.client.post(reverse('dicom_server:config_edit'), {
            'ae_title': 'NEWTITLE', 'port': 4242, 'bind_address': '0.0.0.0',
            'max_pdu': 16382, 'qr_timeout': 30, 'is_enabled': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        cfg = DICOMServerConfiguration.load()
        self.assertEqual(cfg.ae_title, 'NEWTITLE')
        self.assertEqual(cfg.port, 4242)

    def test_config_singleton(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('dicom_server:config_edit'))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse('dicom_server:config_edit'), {
            'ae_title': 'SECOND', 'port': 11112, 'bind_address': '0.0.0.0',
            'max_pdu': 16382, 'qr_timeout': 30,
        })
        self.assertEqual(DICOMServerConfiguration.objects.count(), 1)


class TestNodeCRUD(DicomFrontendTestCase):
    def test_staff_node_lifecycle(self):
        self.client.force_login(self.staff)
        # create
        resp = self.client.post(reverse('dicom_server:node_create'), {
            'name': 'New PACS', 'ae_title': 'NEWPACS', 'host': '10.0.0.1',
            'port': 104, 'is_active': 'on', 'prefer_c_get': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        node = RemoteDICOMNode.objects.get(name='New PACS')
        # edit
        resp = self.client.post(reverse('dicom_server:node_update', args=[node.pk]), {
            'name': 'Renamed', 'ae_title': 'NEWPACS', 'host': '10.0.0.2',
            'port': 11112, 'is_active': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        node.refresh_from_db()
        self.assertEqual(node.name, 'Renamed')
        self.assertFalse(node.prefer_c_get)
        # delete
        resp = self.client.post(reverse('dicom_server:node_delete', args=[node.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(RemoteDICOMNode.objects.filter(pk=node.pk).exists())

    def test_plain_user_cannot_create_node(self):
        self.client.force_login(self.plain_user)
        resp = self.client.post(reverse('dicom_server:node_create'), {
            'name': 'X', 'ae_title': 'X', 'host': 'x', 'port': 1,
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(RemoteDICOMNode.objects.filter(name='X').exists())

    @mock.patch('dicom_server.views.qr_client.echo', return_value=True)
    def test_echo_action_staff(self, mock_echo):
        self.client.force_login(self.staff)
        resp = self.client.post(reverse('dicom_server:node_echo', args=[self.node.pk]))
        self.assertEqual(resp.status_code, 302)
        mock_echo.assert_called_once_with(self.node)
        # result surfaces as a flash message on the node list page
        resp = self.client.post(
            reverse('dicom_server:node_echo', args=[self.node.pk]), follow=True,
        )
        self.assertContains(resp, 'C-ECHO succeeded')

    @mock.patch('dicom_server.views.qr_client.echo', return_value=False)
    def test_echo_failure_shows_error_message(self, mock_echo):
        self.client.force_login(self.staff)
        resp = self.client.post(
            reverse('dicom_server:node_echo', args=[self.node.pk]), follow=True,
        )
        self.assertContains(resp, 'C-ECHO failed')

    @mock.patch('dicom_server.views.qr_client.echo', return_value=True)
    def test_echo_action_denied_for_perm_user(self, mock_echo):
        self.client.force_login(self.perm_user)
        resp = self.client.post(reverse('dicom_server:node_echo', args=[self.node.pk]))
        self.assertEqual(resp.status_code, 403)
        mock_echo.assert_not_called()


class TestRetrieveView(DicomFrontendTestCase):
    def _post(self):
        return self.client.post(reverse('dicom_server:retrieve'), {
            'node': self.node.pk, 'patient': self.patient.pk,
        })

    @mock.patch('dicom_server.views.task_retrieve_studies.delay')
    def test_retrieve_creates_job_and_dispatches(self, mock_delay):
        mock_delay.return_value = mock.Mock(id='task-123')
        self.client.force_login(self.perm_user)
        resp = self._post()
        job = RetrievalJob.objects.get()
        self.assertRedirects(resp, reverse('dicom_server:job_detail', args=[job.pk]))
        self.assertEqual(job.node, self.node)
        self.assertEqual(job.patient, self.patient)
        self.assertEqual(job.created_by, self.perm_user)
        self.assertEqual(job.celery_task_id, 'task-123')
        mock_delay.assert_called_once_with(
            self.node.pk, self.patient.patient_id, self.perm_user.pk, job.pk,
        )

    @mock.patch('dicom_server.views.task_retrieve_studies.delay')
    def test_retrieve_dispatch_failure_marks_job_failed(self, mock_delay):
        mock_delay.side_effect = RuntimeError('broker down')
        self.client.force_login(self.perm_user)
        resp = self._post()
        job = RetrievalJob.objects.get()
        self.assertEqual(job.status, RetrievalJob.Status.FAILED)
        self.assertIn('broker down', job.error_log)
        self.assertRedirects(resp, reverse('dicom_server:job_detail', args=[job.pk]))

    def test_retrieve_form_invalid_without_patient(self):
        self.client.force_login(self.perm_user)
        resp = self.client.post(reverse('dicom_server:retrieve'), {'node': self.node.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(RetrievalJob.objects.exists())

    def test_retrieve_denied_without_permission(self):
        self.client.force_login(self.plain_user)
        resp = self._post()
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(RetrievalJob.objects.exists())


class TestJobPages(DicomFrontendTestCase):
    def test_job_detail_shows_studies_and_instances(self):
        job = RetrievalJob.objects.create(
            node=self.node, patient=self.patient, created_by=self.perm_user,
            status=RetrievalJob.Status.SUCCESS, instances_received=3,
            studies_found=[{
                'study_instance_uid': '1.2.3.4', 'study_date': '20240101',
                'study_description': 'CT Chest', 'modalities': 'CT',
            }],
        )
        self.client.force_login(self.perm_user)
        resp = self.client.get(reverse('dicom_server:job_detail', args=[job.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '1.2.3.4')
        self.assertContains(resp, 'Success')
