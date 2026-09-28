import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from pydicom import dcmread

from client_app.models import (
    Patient, DICOMStudy, DICOMSeries, DICOMInstance, SiteConfiguration,
)
from dicom_server.models import InboundDICOMInstance
from dicom_server.services.ingest import ingest_dataset, find_patient, sanitize
from dicom_server.tests.utils import make_test_dataset


class SanitizeTests(TestCase):
    def test_sanitize_replaces_forbidden_chars(self):
        self.assertEqual(sanitize('MR/25\\004:771*?'), 'MR_25_004_771__')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FindPatientTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test Hospital')
        self.patient = Patient.objects.create(patient_id='MR/25/004771', gender='Female')

    def test_exact_match(self):
        self.assertEqual(find_patient('MR/25/004771'), self.patient)

    def test_canonical_suffix_match(self):
        self.assertEqual(find_patient('25004771'), self.patient)

    def test_no_match_returns_none(self):
        self.assertIsNone(find_patient('DOES_NOT_EXIST'))

    def test_empty_returns_none(self):
        self.assertIsNone(find_patient(''))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class IngestDatasetTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test Hospital')
        # .update() bypasses post_save — avoids an auto-retrieval dispatch
        # attempt to a broker that isn't running in tests
        self.patient = Patient.objects.create(patient_id='MR/25/004771', gender='Female')
        Patient.objects.filter(pk=self.patient.pk).update(chavi_consent=True)
        self.patient.chavi_consent = True
        from django.conf import settings
        self.media = Path(settings.MEDIA_ROOT)

    def test_exact_match_stores_file_study_and_audit(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        result = ingest_dataset(ds, calling_ae='TESTSCU', remote_addr='127.0.0.1')

        self.assertEqual(result.status, 0x0000)
        self.assertEqual(result.patient, self.patient)

        # File stored at processed_dicom/<san_patient>/<san_study>/<san_sop>.dcm
        expected = (
            self.media / 'processed_dicom' / 'MR_25_004771'
            / sanitize(ds.StudyInstanceUID) / f"{sanitize(ds.SOPInstanceUID)}.dcm"
        )
        self.assertTrue(expected.exists())
        self.assertEqual(dcmread(expected).PatientID, 'MR/25/004771')

        # DICOMStudy upserted
        study = DICOMStudy.objects.get(study_instance_uid=ds.StudyInstanceUID)
        self.assertEqual(study.patient, self.patient)
        self.assertEqual(study.study_modalities, 'CT')
        self.assertIn('Test Series', study.series_descriptions)

        # Audit row
        entry = InboundDICOMInstance.objects.get()
        self.assertEqual(entry.status, 'STORED')
        self.assertEqual(entry.matched_patient, self.patient)
        self.assertEqual(entry.sop_instance_uid, ds.SOPInstanceUID)

        # Series/instance hierarchy populated at ingest time
        series = DICOMSeries.objects.get(series_instance_uid=ds.SeriesInstanceUID)
        self.assertEqual(series.study, study)
        self.assertEqual(series.modality, 'CT')
        instance = DICOMInstance.objects.get(sop_instance_uid=ds.SOPInstanceUID)
        self.assertEqual(instance.series, series)

    def test_canonical_match_rewrites_patient_id(self):
        ds = make_test_dataset(patient_id='25004771')
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        self.assertEqual(ds.PatientID, 'MR/25/004771')
        self.assertEqual(ds.PatientName, 'MR/25/004771')
        self.assertEqual(
            InboundDICOMInstance.objects.get().dicom_patient_id, '25004771'
        )

    def test_non_consented_patient_rejected(self):
        Patient.objects.create(patient_id='NOCONSENT/1', gender='Male')
        ds = make_test_dataset(patient_id='NOCONSENT/1')
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0xA7FD)
        self.assertFalse(DICOMStudy.objects.exists())
        entry = InboundDICOMInstance.objects.get()
        self.assertEqual(entry.status, 'REJECTED')
        self.assertIn('consent', entry.reject_reason.lower())

    def test_unknown_patient_rejected_nothing_stored(self):
        ds = make_test_dataset(patient_id='NOPE')
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0xA700)
        self.assertEqual(DICOMStudy.objects.count(), 0)
        entry = InboundDICOMInstance.objects.get()
        self.assertEqual(entry.status, 'REJECTED')
        self.assertIn('Unknown PatientID', entry.reject_reason)
        # No file stored for the rejected SOP Instance UID
        stored = list((self.media / 'processed_dicom').glob('**/*.dcm')) if (self.media / 'processed_dicom').exists() else []
        self.assertFalse(any(ds.SOPInstanceUID in f.name for f in stored))

    def test_missing_patient_id_rejected(self):
        ds = make_test_dataset(patient_id='')
        del ds.PatientID
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0xA900)

    def test_study_uid_collision_reassigns_patient(self):
        other = Patient.objects.create(patient_id='OTHER/1', gender='Male')
        ds = make_test_dataset(patient_id='MR/25/004771')
        DICOMStudy.objects.create(patient=other, study_instance_uid=ds.StudyInstanceUID)
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        study = DICOMStudy.objects.get(study_instance_uid=ds.StudyInstanceUID)
        self.assertEqual(study.patient, self.patient)

    def test_db_failure_removes_orphan_file(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        with mock.patch(
            'dicom_server.services.ingest._upsert_study',
            side_effect=RuntimeError('db down'),
        ):
            result = ingest_dataset(ds)
        self.assertEqual(result.status, 0xC000)
        dest = (
            self.media / 'processed_dicom' / 'MR_25_004771'
            / sanitize(ds.StudyInstanceUID) / f"{sanitize(ds.SOPInstanceUID)}.dcm"
        )
        self.assertFalse(dest.exists())
        self.assertFalse(DICOMStudy.objects.exists())

    def test_duplicate_resend_is_idempotent(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        ingest_dataset(ds)
        ingest_dataset(ds)  # same SOPInstanceUID again
        self.assertEqual(DICOMStudy.objects.count(), 1)
        self.assertEqual(DICOMSeries.objects.count(), 1)
        self.assertEqual(DICOMInstance.objects.count(), 1)
        self.assertEqual(InboundDICOMInstance.objects.filter(status='STORED').count(), 2)

    def test_modalities_merge_across_instances(self):
        study_uid = None
        for modality in ('CT', 'MR'):
            ds = make_test_dataset(
                patient_id='MR/25/004771', modality=modality,
                series_description=f'Series {modality}',
            )
            if study_uid is None:
                study_uid = ds.StudyInstanceUID
            else:
                ds.StudyInstanceUID = study_uid
                ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
            ingest_dataset(ds)
        study = DICOMStudy.objects.get(study_instance_uid=study_uid)
        self.assertEqual(study.study_modalities, 'CT, MR')
        self.assertIn('Series CT', study.series_descriptions)
        self.assertIn('Series MR', study.series_descriptions)
