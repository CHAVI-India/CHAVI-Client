from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase

from client_app.models import TaskRun
from dicom_archive.models import ArchiveConfiguration, ArchivedStudy


class ArchiveConfigurationTests(TestCase):
    def setUp(self):
        cache.clear()  # Django does not clear caches between tests

    def test_load_creates_singleton_with_defaults(self):
        config = ArchiveConfiguration.load()
        self.assertEqual(config.pk, 1)
        self.assertEqual(ArchiveConfiguration.objects.count(), 1)
        self.assertFalse(config.enabled)
        self.assertEqual(config.archive_after_days, 90)
        self.assertTrue(config.delete_local_after_archive)
        self.assertEqual(config.batch_limit, 25)
        self.assertEqual(config.crontab_tuple, ('0', '2', '*', '*', '*'))

    def test_save_keeps_single_row_and_invalidates_cache(self):
        first = ArchiveConfiguration.load()
        first.enabled = True
        first.archive_after_days = 30
        first.save()
        self.assertEqual(ArchiveConfiguration.objects.count(), 1)
        fresh = ArchiveConfiguration.load()
        self.assertEqual(fresh.pk, 1)
        self.assertTrue(fresh.enabled)
        self.assertEqual(fresh.archive_after_days, 30)

    def test_clean_accepts_default_cron_fields(self):
        config = ArchiveConfiguration.load()
        config.full_clean()  # no exception

    def test_clean_rejects_bad_cron_field(self):
        config = ArchiveConfiguration.load()
        config.archive_hour = '2pm'
        with self.assertRaises(ValidationError):
            config.clean()


class TaskTypeAdditionsTests(TestCase):
    def test_new_task_types(self):
        self.assertEqual(TaskRun.TaskType.DICOM_ARCHIVE, 'DICOM_ARCHIVE')
        self.assertEqual(TaskRun.TaskType.DICOM_DEARCHIVE, 'DICOM_DEARCHIVE')

    def test_archived_study_choices(self):
        self.assertEqual(ArchivedStudy.Status.ARCHIVED, 'ARCHIVED')
        self.assertEqual(ArchivedStudy.Status.DEARCHIVED, 'DEARCHIVED')
        self.assertEqual(ArchivedStudy.Reason.SCHEDULED, 'SCHEDULED')
        self.assertEqual(ArchivedStudy.Reason.MANUAL, 'MANUAL')

    def test_admin_registry(self):
        from django.contrib import admin
        from dicom_archive.models import ArchiveLocation
        self.assertIn(ArchiveLocation, admin.site._registry)
        self.assertIn(ArchiveConfiguration, admin.site._registry)
        self.assertIn(ArchivedStudy, admin.site._registry)
