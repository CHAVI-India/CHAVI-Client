import json

from django.test import TestCase
from django_celery_beat.models import PeriodicTask

from dicom_archive.models import ArchiveConfiguration
from dicom_archive.services.schedule_sync import (
    PERIODIC_TASK_NAME,
    SCHEDULE_TASK,
    sync_archive_schedule,
)
from dicom_archive.tests.utils import reset_archive_config


class SyncArchiveScheduleTests(TestCase):
    def test_enabled_creates_periodic_task(self):
        reset_archive_config(
            enabled=True, archive_minute='15', archive_hour='3',
        )
        sync_archive_schedule()
        pt = PeriodicTask.objects.get(name=PERIODIC_TASK_NAME)
        self.assertTrue(pt.enabled)
        self.assertEqual(pt.task, SCHEDULE_TASK)
        self.assertEqual(
            pt.task, 'dicom_archive.tasks.task_scheduled_archive',
        )
        self.assertEqual(pt.args, json.dumps([None]))
        self.assertEqual(pt.expire_seconds, 3600)
        self.assertEqual(pt.crontab.minute, '15')
        self.assertEqual(pt.crontab.hour, '3')
        self.assertEqual(pt.crontab.day_of_week, '*')
        self.assertEqual(pt.crontab.day_of_month, '*')
        self.assertEqual(pt.crontab.month_of_year, '*')

    def test_disabled_disables_periodic_task(self):
        reset_archive_config(enabled=True)
        sync_archive_schedule()
        reset_archive_config(enabled=False)
        sync_archive_schedule()
        self.assertFalse(
            PeriodicTask.objects.get(name=PERIODIC_TASK_NAME).enabled,
        )

    def test_disabled_without_existing_task_is_noop(self):
        reset_archive_config(enabled=False)
        sync_archive_schedule()
        self.assertFalse(
            PeriodicTask.objects.filter(name=PERIODIC_TASK_NAME).exists(),
        )


class ArchiveConfigurationSignalTests(TestCase):
    def test_post_save_signal_syncs_schedule(self):
        # The post_save receiver (dicom_archive.signals, wired in
        # DicomArchiveConfig.ready) must keep the PeriodicTask in sync
        # without an explicit sync_archive_schedule() call.
        config = ArchiveConfiguration.load()
        config.enabled = True
        config.archive_minute = '45'
        config.save()
        self.assertTrue(
            PeriodicTask.objects.filter(
                name=PERIODIC_TASK_NAME, enabled=True,
            ).exists(),
        )

    def test_post_save_signal_disables_when_turned_off(self):
        config = ArchiveConfiguration.load()
        config.enabled = True
        config.save()
        config.refresh_from_db()
        config.enabled = False
        config.save()
        self.assertFalse(
            PeriodicTask.objects.get(name=PERIODIC_TASK_NAME).enabled,
        )
