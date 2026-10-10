"""On-disk cleanup when a DICOMStudy (or its Patient) is deleted."""
import shutil
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase

from dicom_archive.models import ArchiveLocation, ArchivedStudy
from dicom_archive.services.archive import archive_study
from dicom_archive.tests.utils import make_study, reset_archive_config


class CleanupTests(TestCase):
    def setUp(self):
        cache.clear()  # Django does not clear caches between tests
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        reset_archive_config(delete_local_after_archive=True)
        self.location = ArchiveLocation.objects.create(
            name='archive-test',
            storage_type=ArchiveLocation.StorageType.LOCAL,
            path=str(self.tmp / 'archive'),
            is_default=True,
        )

    def test_delete_study_removes_local_folder(self):
        patient, study, src = make_study(
            patient_id='PT100', study_uid='1.2.3.4.90')
        self.assertTrue(src.exists())
        study.delete()
        self.assertFalse(src.exists())

    def test_delete_archived_study_removes_archive_folder(self):
        patient, study, src = make_study(
            patient_id='PT101', study_uid='1.2.3.4.91')
        record = archive_study(study, self.location, reason='MANUAL')
        archive_dir = self.location.resolved_path / record.archive_rel_path
        self.assertTrue(archive_dir.exists())
        study.delete()
        self.assertFalse(archive_dir.exists())
        self.assertFalse(
            ArchivedStudy.objects.filter(study__patient=patient).exists())

    def test_delete_patient_cascades_to_all_study_folders(self):
        patient, study_a, src_a = make_study(
            patient_id='PT102', study_uid='1.2.3.4.92')
        _, study_b, src_b = make_study(
            patient_id='PT102', study_uid='1.2.3.4.93')
        patient.delete()
        self.assertFalse(src_a.exists())
        self.assertFalse(src_b.exists())
