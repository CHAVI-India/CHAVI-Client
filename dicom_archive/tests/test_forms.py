"""Form validation for archive config + locations (plan 03, Task 2)."""
import tempfile
from pathlib import Path

from django.test import TestCase

from dicom_archive.forms import ArchiveConfigurationForm, ArchiveLocationForm


class TestArchiveConfigurationForm(TestCase):
    VALID = {
        'enabled': 'on',
        'archive_after_days': '30',
        'archive_minute': '0',
        'archive_hour': '2',
        'archive_day_of_week': '*',
        'archive_day_of_month': '*',
        'archive_month_of_year': '*',
        'batch_limit': '25',
    }

    def test_valid_data(self):
        form = ArchiveConfigurationForm(data=self.VALID)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['archive_after_days'], 30)

    def test_rejects_bad_cron_minute(self):
        # Model clean() (plan 01) rejects anything outside ^[\d\-,*/]+$ —
        # ModelForm._post_clean surfaces it as a field error.
        form = ArchiveConfigurationForm(data=dict(self.VALID, archive_minute='every'))
        self.assertFalse(form.is_valid())
        self.assertIn('archive_minute', form.errors)

    def test_rejects_bad_day_of_month(self):
        form = ArchiveConfigurationForm(
            data=dict(self.VALID, archive_day_of_month='1st'))
        self.assertFalse(form.is_valid())
        self.assertIn('archive_day_of_month', form.errors)


class TestArchiveLocationForm(TestCase):
    def test_valid_local_path_in_writable_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            form = ArchiveLocationForm(data={
                'name': 'Test drive',
                'storage_type': 'LOCAL',
                'path': str(Path(tmp) / 'archive'),
                'is_active': 'on',
            })
            self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_unwritable_path(self):
        form = ArchiveLocationForm(data={
            'name': 'Bad drive',
            'storage_type': 'LOCAL',
            'path': '/nonexistent-no-permission/archive',
            'is_active': 'on',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('path', form.errors)

    def test_rejects_relative_mount_path(self):
        form = ArchiveLocationForm(data={
            'name': 'Bad mount',
            'storage_type': 'MOUNT',
            'path': 'relative/share',
            'is_active': 'on',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('path', form.errors)
