import json
import shutil
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase

from dicom_archive.models import ArchiveLocation, ArchivedStudy
from dicom_archive.services.archive import (
    MANIFEST_NAME,
    ArchiveError,
    archive_studies,
    archive_study,
)
from dicom_archive.tests.utils import make_study, reset_archive_config


class ArchiveTestBase(TestCase):
    def setUp(self):
        cache.clear()  # Django does not clear caches between tests
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.location = ArchiveLocation.objects.create(
            name='primary', storage_type='LOCAL',
            path=str(self.tmp / 'archive'),
        )


class ArchiveStudyTests(ArchiveTestBase):
    def test_archive_moves_by_default(self):
        patient, study, src = make_study(
            patient_id='PT001', study_uid='1.2.3.4.5',
            tmp_root=self.tmp / 'media', n_files=3,
        )
        record = archive_study(study, self.location, reason='MANUAL')

        dest = self.tmp / 'archive' / 'PT001' / '1.2.3.4.5'
        self.assertFalse(src.exists())  # moved
        self.assertTrue(dest.is_dir())
        self.assertEqual(len(list(dest.glob('img_*.dcm'))), 3)

        manifest = json.loads((dest / MANIFEST_NAME).read_text())
        self.assertEqual(manifest['study_instance_uid'], '1.2.3.4.5')
        self.assertEqual(manifest['patient_id'], 'PT001')
        self.assertEqual(manifest['file_count'], 3)
        self.assertGreater(manifest['size_bytes'], 0)
        self.assertIn('archived_at', manifest)

        record.refresh_from_db()
        self.assertEqual(record.status, 'ARCHIVED')
        self.assertEqual(record.reason, 'MANUAL')
        self.assertEqual(record.local_path_before, str(src))
        self.assertEqual(record.archive_rel_path, 'PT001/1.2.3.4.5')
        self.assertEqual(record.instance_count, 3)
        self.assertGreater(record.size_bytes, 0)
        self.assertIsNotNone(record.archived_at)

    def test_archive_move_removes_empty_patient_folder_from_local(self):
        """With the default move policy, the per-patient folder under
        processed_dicom is removed once its last study is archived.
        The processed_dicom root itself stays."""
        patient, study, src = make_study(
            patient_id='PT030', study_uid='1.2.3.4.30',
            tmp_root=self.tmp / 'media',
        )
        patient_dir = src.parent
        processed_root = patient_dir.parent
        archive_study(study, self.location, reason='MANUAL')
        self.assertFalse(patient_dir.exists())
        self.assertTrue(processed_root.is_dir())

    def test_archive_move_keeps_patient_folder_with_other_studies(self):
        _, study_a, src_a = make_study(
            patient_id='PT031', study_uid='1.2.3.4.31',
            tmp_root=self.tmp / 'media',
        )
        _, study_b, src_b = make_study(
            patient_id='PT031', study_uid='1.2.3.4.32',
            tmp_root=self.tmp / 'media',
        )
        archive_study(study_a, self.location, reason='MANUAL')
        patient_dir = src_a.parent
        self.assertTrue(patient_dir.is_dir())  # still holds study .32
        self.assertEqual([p.name for p in patient_dir.iterdir()],
                         ['1.2.3.4.32'])

    def test_archive_copies_when_delete_disabled(self):
        reset_archive_config(delete_local_after_archive=False)
        patient, study, src = make_study(
            patient_id='PT002', study_uid='1.2.3.4.6',
            tmp_root=self.tmp / 'media',
        )
        archive_study(study, self.location)
        self.assertTrue(src.is_dir())  # copy leaves the source in place
        self.assertEqual(len(list(src.glob('img_*.dcm'))), 3)
        # copy keeps the whole local layout, patient folder included
        self.assertTrue(src.parent.is_dir())
        dest = self.tmp / 'archive' / 'PT002' / '1.2.3.4.6'
        self.assertEqual(len(list(dest.glob('img_*.dcm'))), 3)

    def test_missing_local_folder_raises(self):
        patient, study, src = make_study(
            patient_id='PT003', study_uid='1.2.3.4.7',
            tmp_root=self.tmp / 'media',
        )
        shutil.rmtree(src)
        with self.assertRaises(ArchiveError):
            archive_study(study, self.location)
        self.assertFalse(
            ArchivedStudy.objects.filter(study=study).exists()
        )

    def test_non_empty_destination_raises(self):
        patient, study, src = make_study(
            patient_id='PT004', study_uid='1.2.3.4.8',
            tmp_root=self.tmp / 'media',
        )
        pre = self.tmp / 'archive' / 'PT004' / '1.2.3.4.8'
        pre.mkdir(parents=True)
        (pre / 'stray.dcm').write_text('stray')
        with self.assertRaises(ArchiveError):
            archive_study(study, self.location)
        self.assertTrue(src.is_dir())  # source untouched


class ArchiveStudiesBatchTests(ArchiveTestBase):
    def test_per_study_failure_isolation(self):
        make_study(
            patient_id='PT010', study_uid='1.2.3.4.10',
            tmp_root=self.tmp / 'media',
        )
        _, bad, bad_src = make_study(
            patient_id='PT011', study_uid='1.2.3.4.11',
            tmp_root=self.tmp / 'media',
        )
        shutil.rmtree(bad_src)

        from client_app.models import DICOMStudy
        studies = list(DICOMStudy.objects.filter(study_instance_uid__in=[
            '1.2.3.4.11', '1.2.3.4.10',
        ]))

        result = archive_studies(studies, self.location, reason='MANUAL')
        self.assertEqual(result['archived'], ['1.2.3.4.10'])
        self.assertIn('1.2.3.4.11', result['failed'])
        self.assertIn(
            'Local study folder missing', result['failed']['1.2.3.4.11'],
        )
        self.assertTrue((self.tmp / 'archive' / 'PT010' / '1.2.3.4.10').is_dir())

    def test_rearchive_of_dearchived_study_upserts_record(self):
        """Contract: DEARCHIVED records do not block re-archival — the
        existing record is updated in place (OneToOne: no history)."""
        from dicom_archive.services.dearchive import dearchive_study
        patient, study, src = make_study(
            patient_id='PT020', study_uid='1.2.3.4.20',
            tmp_root=self.tmp / 'media', n_files=3,
        )
        record = archive_study(study, self.location, reason='MANUAL')
        record = dearchive_study(record)  # back locally, status DEARCHIVED
        self.assertEqual(record.status, 'DEARCHIVED')
        self.assertIsNotNone(record.dearchived_at)

        # folder is local again -> re-archive must succeed, not be blocked
        self.assertTrue(src.is_dir())  # de-archive restored the local copy
        record2 = archive_study(study, self.location, reason='SCHEDULED')
        self.assertEqual(ArchivedStudy.objects.filter(study=study).count(), 1)
        self.assertEqual(record2.pk, record.pk)  # updated in place
        self.assertEqual(record2.status, 'ARCHIVED')
        self.assertEqual(record2.reason, 'SCHEDULED')
        # spec: the upsert keeps the previous dearchived_at (no history is
        # kept, but the field is not reset on re-archive — plan 01 values)
        self.assertIsNotNone(record2.dearchived_at)
        dest = self.tmp / 'archive' / 'PT020' / '1.2.3.4.20'
        self.assertEqual(len(list(dest.glob('img_*.dcm'))), 3)
        self.assertFalse(src.exists())  # default policy: move

        # re-archiving a study that is already ARCHIVED (local folder was
        # deleted by the move) is a clean failure, record stays ARCHIVED
        with self.assertRaises(ArchiveError):
            archive_study(study, self.location, reason='MANUAL')
        record2.refresh_from_db()
        self.assertEqual(record2.status, 'ARCHIVED')
