import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from pydicom import dcmread

from client_app.models import (
    Patient, DICOMStudy, DICOMSeries, DICOMInstance, SiteConfiguration,
)
from dicom_server.models import (
    InboundDICOMInstance, PatientIDAlias, RemoteDICOMNode,
    RetrievalJob, RetrievalJobSeries, RetrievalJobStudy,
)
from dicom_server.services.ingest import ingest_dataset, find_patient, sanitize
from dicom_server.tests.utils import make_test_dataset
from dicom_server.tests.utils import make_rt_dataset


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

    def test_alias_match(self):
        node = RemoteDICOMNode.objects.create(
            name='PACS', ae_title='PACS', host='127.0.0.1', port=104,
        )
        PatientIDAlias.objects.create(
            node=node, patient=self.patient, remote_patient_id='PACS-9981',
        )
        self.assertEqual(find_patient('PACS-9981'), self.patient)

    def test_ambiguous_alias_returns_none(self):
        other = Patient.objects.create(patient_id='MR/26/000001', gender='Male')
        n1 = RemoteDICOMNode.objects.create(
            name='N1', ae_title='N1', host='127.0.0.1', port=104,
        )
        n2 = RemoteDICOMNode.objects.create(
            name='N2', ae_title='N2', host='127.0.0.1', port=104,
        )
        PatientIDAlias.objects.create(
            node=n1, patient=self.patient, remote_patient_id='SHARED-1',
        )
        PatientIDAlias.objects.create(
            node=n2, patient=other, remote_patient_id='SHARED-1',
        )
        self.assertIsNone(find_patient('SHARED-1'))


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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class IngestSelectionFilterTests(TestCase):
    """Spec rule 4: partial-selection jobs drop unselected instances."""

    STUDY_UID = '1.2.3'

    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='T', center_name='T')
        self.patient = Patient.objects.create(patient_id='P1', gender='Male')
        Patient.objects.filter(pk=self.patient.pk).update(chavi_consent=True)
        self.patient.chavi_consent = True
        node = RemoteDICOMNode.objects.create(
            name='n', ae_title='TEST', host='127.0.0.1')
        self.job = RetrievalJob.objects.create(
            node=node, patient=self.patient,
            status=RetrievalJob.Status.RUNNING,
        )

    def _job_study(self, series_uids=(), sop_uids=()):
        study = RetrievalJobStudy.objects.create(
            job=self.job, study_instance_uid=self.STUDY_UID)
        RetrievalJobSeries.objects.bulk_create([
            RetrievalJobSeries(study=study, series_instance_uid=s)
            for s in series_uids
        ])
        if sop_uids:
            study.selected_sop_instance_uids = list(sop_uids)
            study.save(update_fields=['selected_sop_instance_uids'])
        return study

    def _audit(self, sop_uid):
        return InboundDICOMInstance.objects.get(sop_instance_uid=sop_uid)

    def test_whole_study_job_accepts_everything(self):
        self._job_study()  # no series rows
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p2', modality='RTPLAN',
            rt_plan_label='final_v2', approval_status='UNAPPROVED')
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        self.assertEqual(self._audit('p2').status, 'STORED')

    def test_rt_instance_in_sop_set_stored(self):
        self._job_study(series_uids=['pl'], sop_uids=['p1', 'ss1'])
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p1', modality='RTPLAN',
            rt_plan_label='final', approval_status='APPROVED')
        ingest_dataset(ds)
        self.assertEqual(self._audit('p1').status, 'STORED')

    def test_rt_instance_not_in_sop_set_dropped(self):
        self._job_study(series_uids=['pl'], sop_uids=['p1', 'ss1'])
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p2', modality='RTPLAN',
            rt_plan_label='final_v2', approval_status='UNAPPROVED')
        result = ingest_dataset(ds)
        # Wire status stays SUCCESS (spec: must not count as failed sub-op).
        self.assertEqual(result.status, 0x0000)
        entry = self._audit('p2')
        self.assertEqual(entry.status, 'REJECTED')
        self.assertEqual(entry.reject_reason,
                         'Instance not selected in retrieval job')
        self.assertFalse(entry.file_path)

    def test_legacy_series_level_selection_accepts_rt_instances(self):
        # Empty SOP set = legacy/scheduled flow: series-level selection
        # behaves exactly as before the filter existed.
        self._job_study(series_uids=['pl'])  # no SOP set
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p2', modality='RTPLAN')
        ingest_dataset(ds)
        self.assertEqual(self._audit('p2').status, 'STORED')

    def test_unselected_image_series_dropped(self):
        self._job_study(series_uids=['ct'], sop_uids=[])
        ds = make_test_dataset(
            patient_id='P1', study_uid=self.STUDY_UID, series_uid='ct2')
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        entry = self._audit(ds.SOPInstanceUID)
        self.assertEqual(entry.status, 'REJECTED')
        self.assertEqual(entry.reject_reason,
                         'Series not selected in retrieval job')

    def test_selected_image_series_stored(self):
        self._job_study(series_uids=['ct'], sop_uids=[])
        ds = make_test_dataset(
            patient_id='P1', study_uid=self.STUDY_UID, series_uid='ct')
        ingest_dataset(ds)
        self.assertEqual(self._audit(ds.SOPInstanceUID).status, 'STORED')

    def test_rt_image_instance_stored_when_its_series_selected(self):
        # RTREG/RTIMAGE are series-level in the selection UI: with a
        # non-empty SOP set from an instance-level selection, an instance
        # of a checked RTIMAGE series must still be stored, not
        # per-SOP-filtered (the UI can never place their SOPs in the set).
        self._job_study(series_uids=['img'], sop_uids=['p1', 'ss1'])
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='img', sop_uid='img1', modality='RTIMAGE')
        ingest_dataset(ds)
        self.assertEqual(self._audit('img1').status, 'STORED')

    def test_rtreg_instance_dropped_when_its_series_not_selected(self):
        # Same job shape: an RTREG instance whose series was NOT checked is
        # dropped at series level (wire status still SUCCESS). No file_meta
        # needed here — the drop happens before any file write.
        self._job_study(series_uids=['ct'], sop_uids=['p1', 'ss1'])
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='reg', sop_uid='reg1', modality='RTREG')
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        entry = self._audit('reg1')
        self.assertEqual(entry.status, 'REJECTED')
        self.assertEqual(entry.reject_reason,
                         'Series not selected in retrieval job')
