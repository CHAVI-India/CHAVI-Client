import shutil
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase

from dicom_archive.models import ArchiveLocation
from dicom_archive.services.archive import MANIFEST_NAME, archive_study
from dicom_archive.services.dearchive import (
    ArchiveError,
    dearchive_studies,
    dearchive_study,
    dearchival_required_for_studies,
    ensure_studies_local,
)
from dicom_archive.tests.utils import make_study


class DearchiveTestBase(TestCase):
    def setUp(self):
        cache.clear()  # Django does not clear caches between tests
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.location = ArchiveLocation.objects.create(
            name='primary', storage_type='LOCAL',
            path=str(self.tmp / 'archive'),
        )

    def _archive_one(self, patient_id, study_uid):
        patient, study, src = make_study(
            patient_id=patient_id, study_uid=study_uid,
            tmp_root=self.tmp / 'media', n_files=3,
        )
        record = archive_study(study, self.location, reason='MANUAL')
        return record, patient, src


class DearchivalRequiredTests(DearchiveTestBase):
    def test_only_archived_records_require_dearchival(self):
        self._archive_one('PT001', '1.2.3.4.51')
        r_done, _, _ = self._archive_one('PT002', '1.2.3.4.52')
        dearchive_study(r_done)  # back to DEARCHIVED
        make_study(
            patient_id='PT003', study_uid='1.2.3.4.53',
            tmp_root=self.tmp / 'media',
        )  # no archive record at all

        required = dearchival_required_for_studies([
            '1.2.3.4.52', '1.2.3.4.51', '1.2.3.4.51',
            '1.2.3.4.53', '1.2.3.4.99',
        ])
        self.assertEqual(required, ['1.2.3.4.51'])


class DearchiveStudyTests(DearchiveTestBase):
    def test_dearchive_removes_empty_patient_folder_in_archive(self):
        """After the last study of a patient is de-archived, the empty
        per-patient folder in the archive location is removed."""
        record, patient, src = self._archive_one('PT013', '1.2.3.4.561')
        patient_dir = self.tmp / 'archive' / 'PT013'
        self.assertTrue(patient_dir.is_dir())
        dearchive_study(record)
        self.assertFalse(patient_dir.exists())

    def test_dearchive_keeps_patient_folder_with_other_studies(self):
        rec_a, patient, _ = self._archive_one('PT014', '1.2.3.4.562')
        rec_b, _, _ = self._archive_one('PT014', '1.2.3.4.563')
        dearchive_study(rec_a)
        patient_dir = self.tmp / 'archive' / 'PT014'
        self.assertTrue(patient_dir.is_dir())  # still holds study .563
        self.assertEqual(
            [p.name for p in patient_dir.iterdir()], ['1.2.3.4.563'])

    def test_dearchive_restores_files_and_updates_record(self):
        record, patient, src = self._archive_one('PT010', '1.2.3.4.54')
        result = dearchive_study(record)
        self.assertEqual(result.status, 'DEARCHIVED')
        self.assertIsNotNone(result.dearchived_at)
        self.assertTrue(src.is_dir())
        self.assertEqual(len(list(src.glob('img_*.dcm'))), 3)
        self.assertFalse((src / MANIFEST_NAME).exists())
        self.assertFalse(
            (self.tmp / 'archive' / 'PT010' / '1.2.3.4.54').exists()
        )

    def test_dearchive_missing_archive_folder_raises(self):
        record, patient, src = self._archive_one('PT011', '1.2.3.4.55')
        shutil.rmtree(self.tmp / 'archive')
        with self.assertRaises(ArchiveError):
            dearchive_study(record)
        record.refresh_from_db()
        self.assertEqual(record.status, 'ARCHIVED')  # stays retryable

    def test_dearchive_merges_into_existing_local_folder(self):
        record, patient, src = self._archive_one('PT012', '1.2.3.4.56')
        src.mkdir(parents=True)  # patient re-ingested after archival
        (src / 'new_file.dcm').write_text('new')
        dearchive_study(record)
        self.assertTrue((src / 'new_file.dcm').exists())
        self.assertEqual(len(list(src.glob('img_*.dcm'))), 3)


class DearchiveStudiesBatchTests(DearchiveTestBase):
    def test_isolation_and_skips_non_archived(self):
        self._archive_one('PT020', '1.2.3.4.57')
        self._archive_one('PT021', '1.2.3.4.58')
        shutil.rmtree(self.tmp / 'archive' / 'PT021' / '1.2.3.4.58')
        make_study(
            patient_id='PT022', study_uid='1.2.3.4.59',
            tmp_root=self.tmp / 'media',
        )

        result = dearchive_studies([
            '1.2.3.4.57', '1.2.3.4.58', '1.2.3.4.59',
        ])
        self.assertEqual(result['dearchived'], ['1.2.3.4.57'])
        self.assertIn('1.2.3.4.58', result['failed'])
        self.assertNotIn('1.2.3.4.59', result['dearchived'])
        self.assertNotIn('1.2.3.4.59', result['failed'])


class EnsureStudiesLocalTests(DearchiveTestBase):
    def test_local_dearchived_and_failed_states(self):
        self._archive_one('PT030', '1.2.3.4.60')
        self._archive_one('PT031', '1.2.3.4.61')
        shutil.rmtree(self.tmp / 'archive' / 'PT031' / '1.2.3.4.61')
        make_study(
            patient_id='PT032', study_uid='1.2.3.4.62',
            tmp_root=self.tmp / 'media',
        )

        mapping = ensure_studies_local([
            '1.2.3.4.60', '1.2.3.4.61', '1.2.3.4.62',
        ])
        self.assertEqual(mapping, {
            '1.2.3.4.60': 'dearchived',
            '1.2.3.4.61': 'failed',
            '1.2.3.4.62': 'local',
        })
