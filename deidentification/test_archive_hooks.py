"""Tests for the de-archival hooks wired into the deidentification chain.

Coverage:
  (a) the dispatcher de-archives archived roster studies before the first
      serial link is dispatched;
  (b) no archived studies => no de-archive dispatch;
  (c) de-archive failure => parent TaskRun FAILURE, no link dispatched;
  (d) the per-study guard 'failed' path records on the parent run, fails
      the child run, and advances the chain.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone


class ArchiveHookTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from client_app.models import Patient, DICOMStudy, SiteConfiguration
        from deidentification.tasks import (
            deidentify_dicom_studies_bulk_task,
            deidentify_dicom_study_task,
        )

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._media = override_settings(MEDIA_ROOT=self._tmp.name)
        self._media.enable()
        self.addCleanup(self._media.disable)

        self.bulk_task = deidentify_dicom_studies_bulk_task
        self.link_task = deidentify_dicom_study_task

        # close_old_connections() would drop the TestCase's wrapped
        # transaction connection — patch it out.
        self._conn_patch = patch('deidentification.tasks.close_old_connections')
        self._conn_patch.start()
        self.addCleanup(self._conn_patch.stop)

        self.user = User.objects.create_user(username='archhook', password='pw')
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P1')
        self.study_a = DICOMStudy.objects.create(
            patient=self.patient, study_instance_uid='UID-A')
        self.study_b = DICOMStudy.objects.create(
            patient=self.patient, study_instance_uid='UID-B')
        self._location = None

    def _make_parent(self, run_id, results=None):
        from client_app.models import TaskRun
        return TaskRun.objects.create(
            task_id=run_id,
            task_name='deidentify_dicom_studies_bulk',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            status=TaskRun.Status.PROGRESS,
            user=self.user,
            task_args=[['UID-A', 'UID-B']],
            task_kwargs={'user_id': self.user.id},
            result_summary={'results': results or {}},
        )

    def _archive_study(self, study, uid):
        """Create the ArchiveLocation + on-disk archive folder + an
        ArchivedStudy(ARCHIVED) row for `study` (uid == its study_instance_uid).
        The study's local folder deliberately does NOT exist on disk."""
        from dicom_archive.models import ArchiveLocation, ArchivedStudy

        if self._location is None:
            archive_root = Path(self._tmp.name) / 'archive_root'
            archive_root.mkdir(parents=True, exist_ok=True)
            self._location = ArchiveLocation.objects.create(
                name='hook-test-loc',
                storage_type=ArchiveLocation.StorageType.LOCAL,
                path=str(archive_root),
                is_active=True,
            )

        local_before = (Path(self._tmp.name) / 'processed_dicom'
                        / study.patient.patient_id / uid)
        dest = Path(self._location.path) / study.patient.patient_id / uid
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'IMG1.dcm').write_text('fake dicom bytes')
        (dest / '_archive_manifest.json').write_text('{"file_count": 1}')

        return ArchivedStudy.objects.create(
            study=study,
            location=self._location,
            status=ArchivedStudy.Status.ARCHIVED,
            reason=ArchivedStudy.Reason.SCHEDULED,
            local_path_before=str(local_before),
            archive_rel_path=f"{study.patient.patient_id}/{uid}",
            size_bytes=15,
            instance_count=1,
            archived_at=timezone.now(),
        )

    def test_bulk_deid_dearchives_archived_studies_before_first_link(self):
        """(a) Mix of archived + local studies for one patient: the archived
        one is de-archived before the first serial link is dispatched."""
        self._archive_study(self.study_a, 'UID-A')
        # study_b stays local — no ArchivedStudy row for it.

        order = []
        with patch('deidentification.tasks.dearchive_studies') as mock_dearch, \
                patch.object(self.link_task, 'delay',
                             side_effect=lambda *a, **k: (order.append('link'), None)[1]) as mock_delay:
            mock_dearch.side_effect = lambda *a, **k: (
                order.append('dearchive'),
                {'dearchived': ['UID-A'], 'failed': {}})[1]
            res = self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='arch-a1',
            )

        # The real service must have found exactly the archived study.
        mock_dearch.assert_called_once_with(['UID-A'])
        # De-archive happened strictly before the first link dispatch.
        self.assertEqual(order, ['dearchive', 'link'])
        mock_delay.assert_called_once_with('arch-a1', 0, user_id=self.user.id)
        self.assertEqual(res.result['status'], 'dispatched')

    def test_guard_failure_records_parent_failure_and_advances_chain(self):
        """(d) The per-study guard reports 'failed' for this study: the
        failure is recorded on the parent run, the child run is failed, and
        the chain still advances to the next study."""
        from client_app.models import TaskRun

        self._make_parent(run_id='arch-d1')
        with patch('deidentification.tasks.ensure_studies_local',
                   return_value={'UID-A': 'failed'}) as mock_ensure, \
                patch('deidentification.tasks.deidentify_study') as mock_deid, \
                patch.object(self.link_task, 'delay') as mock_delay:
            res = self.link_task.apply(
                args=['arch-d1', 0], kwargs={'user_id': self.user.id},
                task_id='arch-d1-link0',
            )

        self.assertEqual(res.result['status'], 'failed')
        mock_ensure.assert_called_once_with(['UID-A'])
        mock_deid.assert_not_called()
        # Chain advances despite the per-study failure.
        mock_delay.assert_called_once_with('arch-d1', 1, user_id=self.user.id)

        parent = TaskRun.objects.get(task_id='arch-d1')
        entry = parent.result_summary['results']['0']
        self.assertEqual(entry['study_id'], 'UID-A')
        self.assertEqual(entry['processed'], 0)
        self.assertEqual(entry['failed'], 0)
        self.assertIn('de-archival failed', entry['error'])
        child = TaskRun.objects.get(task_id='arch-d1-link0')
        self.assertEqual(child.status, TaskRun.Status.FAILURE)

    def test_bulk_deid_with_no_archived_studies_does_not_dispatch_dearchive(self):
        """(b) No ArchivedStudy rows in the roster => the real service returns
        [] and the dispatcher must not dispatch any de-archive task."""
        with patch('deidentification.tasks.dearchive_studies') as mock_dearch, \
                patch.object(self.link_task, 'delay') as mock_delay:
            res = self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='arch-b1',
            )

        mock_dearch.assert_not_called()
        mock_delay.assert_called_once_with('arch-b1', 0, user_id=self.user.id)
        self.assertEqual(res.result['status'], 'dispatched')

    def test_bulk_deid_dearchival_failure_fails_parent_run(self):
        """(c) De-archive reports a failure => parent TaskRun is FAILURE,
        the error names the study, and no deid link is dispatched."""
        from client_app.models import TaskRun

        self._archive_study(self.study_a, 'UID-A')
        with patch('deidentification.tasks.dearchive_studies') as mock_dearch, \
                patch.object(self.link_task, 'delay') as mock_delay:
            mock_dearch.return_value = {
                'dearchived': [],
                'failed': {'UID-A': 'archive source folder missing'},
            }
            res = self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='arch-c1',
            )

        self.assertEqual(res.result['status'], 'failed')
        mock_dearch.assert_called_once_with(['UID-A'])
        mock_delay.assert_not_called()
        parent = TaskRun.objects.get(task_id='arch-c1')
        self.assertEqual(parent.status, TaskRun.Status.FAILURE)
        self.assertIn('1 of 1', parent.error_log)
        self.assertIn('UID-A', parent.error_log)
        self.assertIn('archive source folder missing', parent.error_log)

    @patch('deidentification.tasks.deidentify_study', return_value=(5, 0))
    def test_guard_local_state_passes_through_to_deidentify(self, mock_deid):
        """Guard returns 'local' (nothing archived): the study deidentifies
        normally and the chain advances."""
        from client_app.models import TaskRun

        self._make_parent(run_id='arch-e1')
        with patch('deidentification.tasks.ensure_studies_local',
                   return_value={'UID-A': 'local'}) as mock_ensure, \
                patch.object(self.link_task, 'delay') as mock_delay:
            res = self.link_task.apply(
                args=['arch-e1', 0], kwargs={'user_id': self.user.id},
                task_id='arch-e1-link0',
            )

        mock_ensure.assert_called_once_with(['UID-A'])
        mock_deid.assert_called_once()
        self.assertEqual(res.result['processed'], 5)
        mock_delay.assert_called_once_with('arch-e1', 1, user_id=self.user.id)
        child = TaskRun.objects.get(task_id='arch-e1-link0')
        self.assertEqual(child.status, TaskRun.Status.SUCCESS)

    @patch('deidentification.tasks.deidentify_study', return_value=(5, 0))
    def test_guard_dearchived_state_passes_through_to_deidentify(self, mock_deid):
        """Guard returns 'dearchived' (restored now): the study deidentifies
        normally and the chain advances."""
        from client_app.models import TaskRun

        self._make_parent(run_id='arch-e2')
        with patch('deidentification.tasks.ensure_studies_local',
                   return_value={'UID-A': 'dearchived'}) as mock_ensure, \
                patch.object(self.link_task, 'delay') as mock_delay:
            res = self.link_task.apply(
                args=['arch-e2', 0], kwargs={'user_id': self.user.id},
                task_id='arch-e2-link0',
            )

        mock_ensure.assert_called_once_with(['UID-A'])
        mock_deid.assert_called_once()
        self.assertEqual(res.result['processed'], 5)
        mock_delay.assert_called_once_with('arch-e2', 1, user_id=self.user.id)
        child = TaskRun.objects.get(task_id='arch-e2-link0')
        self.assertEqual(child.status, TaskRun.Status.SUCCESS)

    def test_bulk_deid_dearchival_partial_failure_message_lists_all_uids(self):
        """Dispatcher failure message lists every failed study (sorted)."""
        from client_app.models import TaskRun

        self._archive_study(self.study_a, 'UID-A')
        self._archive_study(self.study_b, 'UID-B')
        with patch('deidentification.tasks.dearchive_studies') as mock_dearch, \
                patch.object(self.link_task, 'delay') as mock_delay:
            mock_dearch.return_value = {
                'dearchived': [],
                'failed': {'UID-B': 'disk full', 'UID-A': 'timeout'},
            }
            self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='arch-f1',
            )

        parent = TaskRun.objects.get(task_id='arch-f1')
        self.assertEqual(parent.status, TaskRun.Status.FAILURE)
        self.assertIn('2 of 2', parent.error_log)
        self.assertIn('UID-A — timeout', parent.error_log)
        self.assertIn('UID-B — disk full', parent.error_log)
        mock_delay.assert_not_called()
