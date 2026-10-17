"""Tests for migration 0035_recover_archived_studies.

Covers both operations:

1. verify_and_repair_local_studies — the local folder must exist AND its
   .dcm files must carry the study's patient ID (built with real pydicom
   files in a temp MEDIA_ROOT):
     * matching files  -> folder_path corrected, row kept;
     * foreign-patient files -> DB rows deleted, on-disk files (local AND
       archive copy) left untouched — also proves the post_delete
       file-cleanup receiver is disconnected;
     * empty folder -> DB rows deleted;
     * no local folder (archived) -> skipped, row kept.

2. recover_archived_studies — restores studies that 0034 deleted after
   their files were archived:
     * full restore of study + series + instances + ArchivedStudy record
       from manifest + .dcm files;
     * idempotency (second run changes nothing);
     * skips when the manifest patient no longer exists;
     * keeps an existing study row and only recreates the missing
       archive record.
"""
import importlib
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

from django.apps import apps
from django.test import TestCase, override_settings
from django.utils import timezone

from client_app.models import (
    DICOMInstance,
    DICOMSeries,
    DICOMStudy,
    Patient,
    SiteConfiguration,
)
from dicom_archive.models import ArchiveLocation, ArchivedStudy

migration = importlib.import_module(
    'client_app.migrations.0035_recover_archived_studies'
)

MR_SOP_CLASS = '1.2.840.10008.5.1.4.1.1.4'
CT_SOP_CLASS = '1.2.840.10008.5.1.4.1.1.2'


def make_dcm(path, *, patient_id, study_uid, series_uid, sop_uid,
             modality='CT', sop_class=CT_SOP_CLASS,
             study_date='20240101', series_date='20240102',
             study_description='CT HEAD', series_description='AXIAL',
             frame_uid='1.2.3.4.99'):
    """Write a minimal but valid file-form DICOM object."""
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = meta
    ds.PatientID = patient_id
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop_uid
    ds.Modality = modality
    ds.StudyDate = study_date
    ds.SeriesDate = series_date
    ds.StudyDescription = study_description
    ds.SeriesDescription = series_description
    ds.FrameOfReferenceUID = frame_uid
    ds.save_as(str(path), enforce_file_format=True)
    return Path(path)


class MigrationBase(TestCase):
    """Shared fixtures: temp MEDIA_ROOT, archive location, site, patients."""

    def setUp(self):
        self.media_root = Path(tempfile.mkdtemp(prefix='chavi_media_'))
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

        self.site = SiteConfiguration.objects.create(
            chavi_center_id='TEST01', center_name='Test Site'
        )
        self.patient = Patient.objects.create(
            patient_id='MR/25:004771', center=self.site
        )

        # LOCAL location, relative to MEDIA_ROOT -> <media>/archive
        self.location = ArchiveLocation.objects.create(
            name='Test Archive', storage_type='LOCAL', path='archive'
        )
        self.archive_base = self.media_root / 'archive'

    # -- helpers ------------------------------------------------------------

    def processed_dir(self, patient_id=None, uid=None):
        p = patient_id or self.patient.patient_id
        return (
            self.media_root / 'processed_dicom'
            / migration._sanitize(p) / migration._sanitize(uid or '')
        )

    def archive_dir(self, patient_id, uid):
        return (self.archive_base
                / migration._sanitize(patient_id) / uid)

    def write_manifest(self, study_dir, *, patient_id, uid, instance_count):
        (study_dir / migration.MANIFEST_NAME).write_text(json.dumps({
            'study_instance_uid': uid,
            'patient_id': patient_id,
            'archived_at': timezone.now().isoformat(),
            'file_count': instance_count,
            'size_bytes': 12345,
        }), encoding='utf-8')

    def run_verify(self):
        with override_settings(MEDIA_ROOT=str(self.media_root)):
            migration.verify_and_repair_local_studies(apps, None)

    def run_recover(self):
        with override_settings(MEDIA_ROOT=str(self.media_root)):
            migration.recover_archived_studies(apps, None)

    def make_study(self, uid, folder_path, patient=None):
        return DICOMStudy.objects.create(
            patient=patient or self.patient,
            study_instance_uid=uid,
            folder_path=folder_path,
        )


class VerifyLocalStudiesTests(MigrationBase):

    UID = '1.2.840.113619.2.55.3.1'

    def test_fixes_path_when_files_match_patient(self):
        local = self.processed_dir(uid=self.UID)
        local.mkdir(parents=True)
        make_dcm(local / '1.dcm', patient_id=self.patient.patient_id,
                 study_uid=self.UID, series_uid='10.1', sop_uid='100.1')
        stale = str(self.processed_dir(uid='some-other-uid'))
        study = self.make_study(self.UID, stale)
        self.make_series(study)

        self.run_verify()

        study.refresh_from_db()
        self.assertEqual(study.folder_path, str(local))
        self.assertTrue(DICOMSeries.objects.filter(study=study).exists())

    def make_series(self, study, uid='10.1', n=1):
        series = DICOMSeries.objects.create(
            study=study, series_instance_uid=uid, modality='CT')
        for i in range(n):
            DICOMInstance.objects.create(
                series=series, sop_instance_uid=f'100.{i}')
        return series

    def test_deletes_study_with_foreign_patient_files(self):
        """Files carrying another patient's ID -> DB rows deleted, files
        (local AND archive copy) left untouched."""
        local = self.processed_dir(uid=self.UID)
        local.mkdir(parents=True)
        make_dcm(local / '1.dcm', patient_id='SOMEONE/ELSE',
                 study_uid=self.UID, series_uid='10.1', sop_uid='100.1')

        # Also park a copy "in the archive" with a record: if the
        # post_delete file-cleanup receiver fired, both copies would be
        # rmtree'd.
        archived = self.archive_dir('MR_25_004771', self.UID)
        archived.mkdir(parents=True)
        make_dcm(archived / '1.dcm', patient_id=self.patient.patient_id,
                 study_uid=self.UID, series_uid='10.1', sop_uid='100.1')

        study = self.make_study(self.UID, str(local))
        self.make_series(study)
        ArchivedStudy.objects.create(
            study=study, location=self.location,
            status=ArchivedStudy.Status.ARCHIVED,
            local_path_before=str(local),
            archive_rel_path=f'MR_25_004771/{self.UID}',
        )

        self.run_verify()

        self.assertFalse(DICOMStudy.objects.filter(pk=self.UID).exists())
        self.assertFalse(DICOMSeries.objects.filter(study=study).exists())
        self.assertFalse(ArchivedStudy.objects.filter(study=study).exists())
        # Files must survive the DB-only cleanup.
        self.assertTrue((local / '1.dcm').is_file())
        self.assertTrue((archived / '1.dcm').is_file())

    def test_deletes_study_with_empty_folder(self):
        local = self.processed_dir(uid=self.UID)
        local.mkdir(parents=True)
        study = self.make_study(self.UID, str(local))
        self.make_series(study)

        self.run_verify()

        self.assertFalse(DICOMStudy.objects.filter(pk=self.UID).exists())
        self.assertFalse(DICOMSeries.objects.filter(study=study).exists())
        self.assertTrue(local.is_dir())  # folder left on disk

    def test_keeps_archived_study_without_local_folder(self):
        """No local folder at all (archived) -> verify pass leaves the row
        alone; recovery is operation 2's job."""
        study = self.make_study(self.UID, str(self.processed_dir(uid=self.UID)))
        ArchivedStudy.objects.create(
            study=study, location=self.location,
            status=ArchivedStudy.Status.ARCHIVED,
            local_path_before=str(self.processed_dir(uid=self.UID)),
            archive_rel_path=f'MR_25_004771/{self.UID}',
        )

        self.run_verify()

        self.assertTrue(DICOMStudy.objects.filter(pk=self.UID).exists())


class ArchiveRecoveryTests(MigrationBase):

    UID = '1.2.840.113619.2.55.3.2'

    def _build_archive_folder(self, uid=UID, patient_id=None, n_files=4):
        pid = patient_id or self.patient.patient_id
        study_dir = self.archive_dir(pid, uid)
        study_dir.mkdir(parents=True)
        for i in range(2):  # 2 series x 2 instances
            modality = 'CT' if i == 0 else 'MR'
            sop_class = CT_SOP_CLASS if i == 0 else MR_SOP_CLASS
            for j in range(2):
                make_dcm(
                    study_dir / f'{i}_{j}.dcm',
                    patient_id=pid,
                    study_uid=uid,
                    series_uid=f'10.{i}',
                    sop_uid=f'100.{i}.{j}',
                    modality=modality,
                    sop_class=sop_class,
                    series_description='AXIAL' if i == 0 else 'COR',
                )
        self.write_manifest(study_dir, patient_id=pid,
                            uid=uid, instance_count=n_files)
        return study_dir

    def test_restores_deleted_archived_study(self):
        """The 0034 damage scenario: study/children/record all gone,
        files safe in the archive -> everything restored."""
        self._build_archive_folder()

        self.run_recover()

        study = DICOMStudy.objects.get(pk=self.UID)
        self.assertEqual(study.patient_id, self.patient.patient_id)
        # Canonical local path — the value archiving never changed.
        self.assertEqual(
            study.folder_path,
            str(self.processed_dir(uid=self.UID)),
        )
        self.assertEqual(study.study_description, 'CT HEAD')
        self.assertEqual(study.study_date, date(2024, 1, 1))
        self.assertEqual(study.study_modalities, 'CT, MR')
        self.assertEqual(study.series_descriptions, 'AXIAL, COR')

        series = {s.series_instance_uid: s
                  for s in DICOMSeries.objects.filter(study=study)}
        self.assertEqual(set(series), {'10.0', '10.1'})
        self.assertEqual(series['10.0'].modality, 'CT')
        self.assertEqual(series['10.1'].modality, 'MR')
        self.assertEqual(series['10.0'].frame_of_reference_uid, '1.2.3.4.99')
        self.assertEqual(
            DICOMInstance.objects.filter(series__study=study).count(), 4)

        record = ArchivedStudy.objects.get(study=study)
        self.assertEqual(record.status, ArchivedStudy.Status.ARCHIVED)
        self.assertEqual(record.location_id, self.location.id)
        self.assertEqual(record.archive_rel_path, f'MR_25_004771/{self.UID}')
        self.assertEqual(record.local_path_before, study.folder_path)
        self.assertEqual(record.size_bytes, 12345)
        self.assertEqual(record.instance_count, 4)
        self.assertIsNotNone(record.archived_at)

        # Idempotency: a second run must not duplicate anything.
        self.run_recover()
        self.assertEqual(DICOMStudy.objects.filter(pk=self.UID).count(), 1)
        self.assertEqual(DICOMSeries.objects.filter(study=study).count(), 2)
        self.assertEqual(
            DICOMInstance.objects.filter(series__study=study).count(), 4)
        self.assertEqual(ArchivedStudy.objects.filter(study=study).count(), 1)

    def test_skips_folder_whose_patient_no_longer_exists(self):
        self._build_archive_folder(uid='1.2.840.113619.9.9.9',
                                   patient_id='GONE/1')

        self.run_recover()

        self.assertFalse(DICOMStudy.objects.filter(pk='1.2.840.113619.9.9.9')
                         .exists())
        self.assertEqual(ArchivedStudy.objects.count(), 0)

    def test_keeps_existing_study_and_recreates_missing_record(self):
        """Study row survived 0034 (local copy was kept) but the record was
        cascade-deleted... record recreated, study not duplicated."""
        self._build_archive_folder()
        local = self.processed_dir(uid=self.UID)
        study = self.make_study(self.UID, str(local))
        series = DICOMSeries.objects.create(
            study=study, series_instance_uid='10.0', modality='CT')
        DICOMInstance.objects.create(series=series, sop_instance_uid='100.0.0')

        self.run_recover()

        self.assertEqual(DICOMStudy.objects.filter(pk=self.UID).count(), 1)
        # Children already present -> not duplicated.
        self.assertEqual(DICOMSeries.objects.filter(study=study).count(), 1)
        self.assertEqual(DICOMInstance.objects.filter(series=series).count(), 1)
        record = ArchivedStudy.objects.get(study=study)
        self.assertEqual(record.archive_rel_path, f'MR_25_004771/{self.UID}')
        self.assertEqual(record.status, ArchivedStudy.Status.ARCHIVED)
