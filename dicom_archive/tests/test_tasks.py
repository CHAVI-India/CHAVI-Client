import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from client_app.models import TaskRun
from dicom_archive.models import ArchiveLocation
from dicom_archive.tasks import (
    archive_studies_task,
    dearchive_studies_task,
    task_scheduled_archive,
)
from dicom_archive.tests.utils import make_study, reset_archive_config


class TaskTestBase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.location = ArchiveLocation.objects.create(
            name='primary', storage_type='LOCAL', is_default=True,
            path=str(self.tmp / 'archive'),
        )


class ScheduledArchiveTaskTests(TaskTestBase):
    def test_disabled_config_dispatches_nothing(self):
        reset_archive_config(enabled=False)
        self.assertEqual(task_scheduled_archive(None), {'status': 'disabled'})
        self.assertFalse(TaskRun.objects.exists())

    def test_no_active_location(self):
        self.location.delete()
        reset_archive_config(enabled=True)
        self.assertEqual(
            task_scheduled_archive(None), {'status': 'nothing_to_do'},
        )

    def test_no_candidates(self):
        reset_archive_config(enabled=True, archive_after_days=30)
        make_study(
            patient_id='PT100', study_uid='1.2.3.4.70',
            tmp_root=self.tmp / 'media',
            study_date=date.today() - timedelta(days=2),
        )
        self.assertEqual(task_scheduled_archive(None), {'status': 'empty'})
        self.assertFalse(TaskRun.objects.exists())

    def test_dispatches_correct_uids_with_scheduled_reason(self):
        reset_archive_config(
            enabled=True, archive_after_days=30, batch_limit=2,
        )
        old = date.today() - timedelta(days=120)
        uids = []
        for i in range(3):
            _, study, _ = make_study(
                patient_id=f'PT1{i:02d}', study_uid=f'1.2.3.4.8{i}',
                tmp_root=self.tmp / 'media', study_date=old,
            )
            uids.append(study.study_instance_uid)

        with patch.object(archive_studies_task, 'delay') as mock_delay:
            result = task_scheduled_archive(None)

        self.assertEqual(result['status'], 'dispatched')
        self.assertEqual(result['study_uids'], uids[:2])
        self.assertEqual(result['location_id'], self.location.pk)
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(args[0], uids[:2])
        self.assertEqual(args[1], self.location.pk)
        self.assertIsNone(kwargs.get('user_id'))
        self.assertEqual(kwargs.get('reason'), 'SCHEDULED')


class ArchiveStudiesTaskTests(TaskTestBase):
    def test_archive_task_records_success_with_partial_failure(self):
        make_study(
            patient_id='PT200', study_uid='1.2.3.4.90',
            tmp_root=self.tmp / 'media',
        )
        _, bad, bad_src = make_study(
            patient_id='PT201', study_uid='1.2.3.4.91',
            tmp_root=self.tmp / 'media',
        )
        shutil.rmtree(bad_src)

        result = archive_studies_task.apply(
            args=[['1.2.3.4.91', '1.2.3.4.90'], self.location.pk],
            kwargs={'user_id': None, 'reason': 'MANUAL'},
            task_id='arch-1',
        )

        self.assertEqual(result.result['archived'], ['1.2.3.4.90'])
        self.assertIn('1.2.3.4.91', result.result['failed'])
        run = TaskRun.objects.get(task_id='arch-1')
        self.assertEqual(run.status, TaskRun.Status.SUCCESS)
        self.assertEqual(run.task_type, TaskRun.TaskType.DICOM_ARCHIVE)
        self.assertEqual(run.task_name, 'archive_studies')

    def test_archive_task_unknown_location_records_failure(self):
        """A broken batch (location vanished) must land on TaskRun FAILURE
        with the error captured — the UI poll then reports it."""
        make_study(
            patient_id='PT210', study_uid='1.2.3.4.95',
            tmp_root=self.tmp / 'media',
        )
        self.location.delete()
        with self.assertRaises(Exception):
            archive_studies_task.apply(
                args=[['1.2.3.4.95'], 999999],
                kwargs={'user_id': None, 'reason': 'MANUAL'},
                task_id='arch-fail-1',
                throw=True,
            )
        run = TaskRun.objects.get(task_id='arch-fail-1')
        self.assertEqual(run.status, TaskRun.Status.FAILURE)
        self.assertIsNotNone(run.completed_at)
        self.assertIn('no longer exists', run.error_log)
        self.assertIn('999999', run.error_log)


class DearchiveStudiesTaskTests(TaskTestBase):
    def test_dearchive_task_records_success(self):
        make_study(
            patient_id='PT300', study_uid='1.2.3.4.92',
            tmp_root=self.tmp / 'media',
        )
        from dicom_archive.services.archive import archive_study
        from client_app.models import DICOMStudy
        study = DICOMStudy.objects.get(study_instance_uid='1.2.3.4.92')
        archive_study(study, self.location, reason='SCHEDULED')

        result = dearchive_studies_task.apply(
            args=[['1.2.3.4.92']], kwargs={'user_id': None},
            task_id='dearch-1',
        )

        self.assertEqual(result.result['dearchived'], ['1.2.3.4.92'])
        run = TaskRun.objects.get(task_id='dearch-1')
        self.assertEqual(run.status, TaskRun.Status.SUCCESS)
        self.assertEqual(run.task_type, TaskRun.TaskType.DICOM_DEARCHIVE)
        self.assertEqual(run.task_name, 'dearchive_studies')
