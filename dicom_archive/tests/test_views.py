"""Frontend tests for dicom_archive (plan 03).

Task 1: permission gating. Task 2: location CRUD + config update.
Task 3: manual trigger + task-status JSON views.
"""
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from client_app.models import DICOMStudy, Patient, SiteConfiguration, TaskRun
from dicom_archive.models import ArchiveConfiguration, ArchiveLocation, ArchivedStudy
from dicom_archive.services.locations import WRITE_TEST_FILENAME


class ArchiveViewTestCase(TestCase):
    """Shared fixtures for every plan-03 test class."""

    def setUp(self):
        # The ArchiveConfiguration singleton caches its instance for 30 s;
        # the test DB rolls back between tests, so a stale cached row would
        # point at a deleted pk. Clear the cache on every test.
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Hospital')
        # Archive administrator: every dicom_archive model permission.
        cls.admin = User.objects.create_user(
            'archive-admin', password='pw', is_staff=True)
        cls.admin.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_archive',
            codename__in=[
                'view_archiveconfiguration', 'change_archiveconfiguration',
                'view_archivelocation', 'add_archivelocation',
                'change_archivelocation', 'delete_archivelocation',
                'view_archivedstudy', 'add_archivedstudy',
            ],
        ))
        # Viewer: can browse archives, cannot configure or trigger.
        cls.viewer = User.objects.create_user('archive-viewer', password='pw')
        cls.viewer.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_archive',
            codename__in=['view_archivedstudy'],
        ))
        cls.plain = User.objects.create_user('archive-plain', password='pw')

        cls.patient = Patient.objects.create(
            patient_id='MR/25/000001', gender='Female')
        cls.study = DICOMStudy.objects.create(
            patient=cls.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.9',
            study_date='2025-01-15',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.9',
        )
        cls.location = ArchiveLocation.objects.create(
            name='NAS archive',
            storage_type=ArchiveLocation.StorageType.LOCAL,
            path='archive/studies',
            is_default=True,
        )
        cls.record = ArchivedStudy.objects.create(
            study=cls.study,
            location=cls.location,
            status=ArchivedStudy.Status.ARCHIVED,
            local_path_before=cls.study.folder_path,
            archive_rel_path='MR_25_000001/1.2.3.4.5.6.7.8.9',
            size_bytes=123,
            instance_count=4,
        )


class TestPermissionGating(ArchiveViewTestCase):
    GATED_URLS = ['dashboard', 'browse', 'archived_list']

    def test_anonymous_redirected_to_login(self):
        for name in self.GATED_URLS:
            resp = self.client.get(reverse(f'dicom_archive:{name}'))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn('/accounts/login/', resp.url, name)

    def test_plain_user_denied_everywhere(self):
        self.client.force_login(self.plain)
        for name in self.GATED_URLS:
            resp = self.client.get(reverse(f'dicom_archive:{name}'))
            self.assertEqual(resp.status_code, 403, name)

    def test_viewer_denied_dashboard(self):
        # viewer has only view_archivedstudy; dashboard needs
        # view_archiveconfiguration. 403 needs no template render.
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertEqual(resp.status_code, 403)


class TestLocationCrud(ArchiveViewTestCase):
    def test_anonymous_redirected_on_location_pages(self):
        for name in ['location_list', 'location_create']:
            resp = self.client.get(reverse(f'dicom_archive:{name}'))
            self.assertEqual(resp.status_code, 302, name)

    def test_plain_user_denied_location_pages(self):
        self.client.force_login(self.plain)
        for name in ['location_list', 'location_create']:
            resp = self.client.get(reverse(f'dicom_archive:{name}'))
            self.assertEqual(resp.status_code, 403, name)

    def test_viewer_denied_location_create_and_delete(self):
        self.client.force_login(self.viewer)
        self.assertEqual(
            self.client.get(
                reverse('dicom_archive:location_create')).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse('dicom_archive:location_delete',
                        args=[self.location.pk])).status_code, 403)

    def test_create_location(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as tmp:
            resp = self.client.post(
                reverse('dicom_archive:location_create'),
                {'name': 'Backup NAS', 'storage_type': 'MOUNT',
                 'path': tmp, 'is_active': 'on'})
        self.assertEqual(resp.status_code, 302, resp.content)
        self.assertEqual(resp.url, reverse('dicom_archive:location_list'))
        loc = ArchiveLocation.objects.get(name='Backup NAS')
        self.assertTrue(loc.is_active)
        self.assertEqual(loc.storage_type, 'MOUNT')

    def test_update_location(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as tmp:
            resp = self.client.post(
                reverse('dicom_archive:location_update',
                        args=[self.location.pk]),
                {'name': 'NAS archive', 'storage_type': 'LOCAL',
                 'path': tmp, 'is_default': 'on', 'is_active': 'on'})
        self.assertEqual(resp.status_code, 302, resp.content)
        self.location.refresh_from_db()
        self.assertEqual(self.location.path, tmp)
        self.assertTrue(self.location.is_default)

    def test_delete_location_without_records(self):
        self.client.force_login(self.admin)
        empty = ArchiveLocation.objects.create(
            name='Empty', storage_type=ArchiveLocation.StorageType.LOCAL,
            path='archive/empty')
        resp = self.client.post(
            reverse('dicom_archive:location_delete', args=[empty.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ArchiveLocation.objects.filter(pk=empty.pk).exists())

    def test_delete_location_with_records_refused(self):
        # fixture self.location holds self.record (ARCHIVED)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:location_delete', args=[self.location.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ArchiveLocation.objects.filter(pk=self.location.pk).exists())

    def test_config_update_rejects_bad_cron_and_keeps_old_value(self):
        self.client.force_login(self.admin)
        config = ArchiveConfiguration.load()
        original_minute = config.archive_minute
        resp = self.client.post(
            reverse('dicom_archive:config_edit'),
            {'enabled': 'on', 'archive_after_days': '30',
             'archive_minute': 'soon', 'archive_hour': '2',
             'archive_day_of_week': '*', 'archive_day_of_month': '*',
             'archive_month_of_year': '*', 'batch_limit': '25'})
        # form re-renders with the error; nothing is saved
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'archive_minute')
        config.refresh_from_db()
        self.assertEqual(config.archive_minute, original_minute)


class TestManualTriggers(ArchiveViewTestCase):
    def test_archive_trigger_requires_login_and_perm(self):
        url = reverse('dicom_archive:archive_trigger')
        resp = self.client.post(
            url, data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 302)  # anon -> login
        self.client.force_login(self.viewer)     # lacks add_archivedstudy
        resp = self.client.post(
            url, data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    @mock.patch('dicom_archive.views.archive_studies_task')
    def test_archive_trigger_dispatches_and_reports(self, mock_task):
        mock_task.delay.return_value = SimpleNamespace(id='celery-archive-1')
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({
                'study_uids': [self.study.study_instance_uid],
                'location_id': self.location.pk,
            }),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['task_id'], 'celery-archive-1')
        self.assertEqual(body['redirect_url'],
                         reverse('client_app:taskrun_list'))
        self.assertIn('Archiving 1 study', body['message'])
        mock_task.delay.assert_called_once_with(
            [self.study.study_instance_uid], self.location.pk,
            user_id=self.admin.pk, reason='MANUAL')

    def test_archive_trigger_rejects_unknown_uid(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({'study_uids': ['1.9.9.9'],
                             'location_id': self.location.pk}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('unknown or non-local', resp.json()['error'])

    def test_archive_trigger_rejects_inactive_location(self):
        self.client.force_login(self.admin)
        ArchiveLocation.objects.filter(pk=self.location.pk).update(
            is_active=False)
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({'study_uids': [self.study.study_instance_uid],
                             'location_id': self.location.pk}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('active archive location', resp.json()['error'])

    def test_archive_trigger_rejects_empty_and_bad_json(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({'study_uids': [],
                             'location_id': self.location.pk}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('non-empty list', resp.json()['error'])
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data='{not json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Invalid JSON body')

    def test_archive_trigger_dispatch_failure_is_500(self):
        with mock.patch(
                'dicom_archive.views.archive_studies_task') as mock_task:
            mock_task.delay.side_effect = RuntimeError('broker down')
            self.client.force_login(self.admin)
            resp = self.client.post(
                reverse('dicom_archive:archive_trigger'),
                data=json.dumps({'study_uids': [
                    self.study.study_instance_uid],
                    'location_id': self.location.pk}),
                content_type='application/json')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'],
                         'Could not dispatch archive task')

    @mock.patch('dicom_archive.views.dearchive_studies_task')
    def test_dearchive_trigger_dispatches(self, mock_task):
        mock_task.delay.return_value = SimpleNamespace(id='celery-dearch-1')
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:dearchive_trigger'),
            data=json.dumps(
                {'study_uids': [self.study.study_instance_uid]}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['task_id'], 'celery-dearch-1')
        self.assertEqual(body['redirect_url'],
                         reverse('client_app:taskrun_list'))
        self.assertIn('De-archiving 1 study', body['message'])
        mock_task.delay.assert_called_once_with(
            [self.study.study_instance_uid], user_id=self.admin.pk)

    def test_dearchive_trigger_rejects_non_archived_study(self):
        second = DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.10',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.10',
        )
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:dearchive_trigger'),
            data=json.dumps(
                {'study_uids': [second.study_instance_uid]}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('no archived study found', resp.json()['error'])

    def test_browse_page_carries_csrf_token_and_dispatch_passes_csrf(self):
        """Regression (production bug): the trigger JS reads the CSRF
        token from ``input[name=csrfmiddlewaretoken]``. The browse page
        only renders GET filter forms, so without an explicit
        ``{% csrf_token %}`` the real browser POST gets a 403 HTML page
        and the JS dies in JSON.parse. Django's test client does not
        enforce CSRF, so this test switches it on to prove the token on
        the page actually authorizes the dispatch."""
        self.client.force_login(self.admin)
        page = self.client.get(reverse('dicom_archive:browse'))
        match = re.search(
            rb'name="csrfmiddlewaretoken" value="([^"]+)"',
            page.content)
        self.assertIsNotNone(
            match, 'browse page has no CSRF token input')
        self.client.enforce_csrf_checks = True
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({
                'study_uids': [self.study.study_instance_uid],
                'location_id': self.location.pk,
            }),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=match.group(1).decode())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('task_id', resp.json())


class TestTaskStatusView(ArchiveViewTestCase):
    def test_unknown_task_is_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('dicom_archive:task_status', args=['nope']))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'task run not found')

    def test_status_by_celery_task_id(self):
        run = TaskRun.objects.create(
            task_id='celery-archive-1',
            task_name='archive_studies',
            task_type='DICOM_ARCHIVE',
            status=TaskRun.Status.PROGRESS,
            progress_current=3, progress_total=10,
            progress_description='3 of 10',
        )
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('dicom_archive:task_status', args=[run.task_id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['task_run_id'], run.pk)
        self.assertEqual(body['status'], 'PROGRESS')
        self.assertEqual(body['progress_current'], 3)
        self.assertEqual(body['progress_percent'], 30)
        self.assertIsNone(body['completed_at'])

    def test_status_by_taskrun_pk(self):
        run = TaskRun.objects.create(
            task_id='celery-archive-2',
            task_name='dearchive_studies',
            task_type='DICOM_DEARCHIVE',
            status=TaskRun.Status.SUCCESS,
        )
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('dicom_archive:task_status', args=[str(run.pk)]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['task_id'], 'celery-archive-2')

    def test_status_requires_perm(self):
        self.client.force_login(self.plain)
        resp = self.client.get(
            reverse('dicom_archive:task_status', args=['x']))
        self.assertEqual(resp.status_code, 403)


class TestLocationTestView(ArchiveViewTestCase):
    """POST /archive/locations/test/ — live probe of a saved location or
    unsaved form values; leaves a visible verification file on the share."""

    def _post(self, payload):
        return self.client.post(
            reverse('dicom_archive:location_test'),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_anonymous_redirected_to_login(self):
        self.assertEqual(self._post({}).status_code, 302)

    def test_plain_user_denied(self):
        self.client.force_login(self.plain)
        self.assertEqual(self._post({}).status_code, 403)

    def test_viewer_without_location_view_denied(self):
        # viewer has view_archivedstudy only; probing needs
        # view_archivelocation
        self.client.force_login(self.viewer)
        self.assertEqual(self._post({}).status_code, 403)

    def test_probe_saved_location(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as tmp:
            loc = ArchiveLocation.objects.create(
                name='Probe NAS',
                storage_type=ArchiveLocation.StorageType.MOUNT,
                path=tmp,
            )
            resp = self._post({'location_id': loc.pk})
            self.assertEqual(resp.status_code, 200, resp.content)
            body = resp.json()
            self.assertTrue(body['ok'])
            self.assertEqual(body['path'], tmp)
            self.assertTrue(Path(body['test_file']).is_file())
            self.assertEqual(Path(body['test_file']).parent, Path(tmp))

    def test_probe_unknown_location_404(self):
        self.client.force_login(self.admin)
        resp = self._post({'location_id': 999999})
        self.assertEqual(resp.status_code, 404)
        self.assertIn('unknown location_id', resp.json()['error'])

    def test_probe_unsaved_form_values(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as tmp:
            resp = self._post({'storage_type': 'MOUNT', 'path': tmp})
            self.assertEqual(resp.status_code, 200, resp.content)
            body = resp.json()
            self.assertTrue(body['ok'])
            self.assertTrue((Path(tmp) / WRITE_TEST_FILENAME).is_file())

    def test_probe_requires_storage_type_and_path(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self._post({'storage_type': 'MOUNT', 'path': ''}).status_code,
            400)
        self.assertEqual(
            self._post({'storage_type': 'FTP', 'path': '/x'}).status_code,
            400)
        self.assertEqual(self._post({}).status_code, 400)
