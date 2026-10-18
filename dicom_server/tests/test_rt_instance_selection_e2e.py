"""End-to-end: instance-level selection -> job rows -> ingest filtering.

Chains BatchRetrieveView -> RetrievalJob/Study/Series -> ingest_dataset
accept/drop using the ARIA data shape: one RTPLAN series holding two plans
(one approved, one unapproved) plus struct-set and dose series.
"""
import json
import tempfile
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from client_app.models import Patient, SiteConfiguration
from dicom_server.models import (
    InboundDICOMInstance, RemoteDICOMNode, RetrievalBatch,
    RetrievalBatchPatient, RetrievalJob,
)
from dicom_server.services.ingest import ingest_dataset
from dicom_server.tests.utils import make_rt_dataset, make_test_dataset


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RtInstanceSelectionE2ETests(TestCase):
    STUDY_UID = '1.2.840.10008.5.1.4.199471.1.1'

    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Hospital')
        cls.node = RemoteDICOMNode.objects.create(
            name='Stub PACS', ae_title='STUBPACS', host='127.0.0.1')
        cls.user = User.objects.create_user('qruser', password='pw')
        cls.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_server',
            codename__in=['add_retrievaljob', 'view_retrievaljob'],
        ))
        cls.patient = Patient.objects.create(
            patient_id='MR/25/004771', gender='Female')
        Patient.objects.filter(pk=cls.patient.pk).update(chavi_consent=True)
        cls.patient.chavi_consent = True

    def setUp(self):
        self.tree = [{
            'study_instance_uid': self.STUDY_UID, 'remote_patient_id': 'X',
            'study_date': '20250407', 'study_description': 'RT Planning CT',
            'series': [
                {'series_instance_uid': 'ct', 'series_description': 'CECT',
                 'modality': 'CT', 'series_number': 1, 'instances': 2},
                {'series_instance_uid': 'ss', 'modality': 'RTSTRUCT',
                 'series_number': 13, 'instances': 1,
                 'rt_instances': [
                     {'sop_instance_uid': 'ss1', 'structure_set_label':
                      'CT_FINAL', 'referenced_series_uids': ['ct']}]},
                {'series_instance_uid': 'pl', 'modality': 'RTPLAN',
                 'series_number': 14, 'instances': 2,
                 'rt_instances': [
                     {'sop_instance_uid': 'p1', 'rt_plan_label': 'final',
                      'approval_status': 'APPROVED',
                      'referenced_structure_set_uids': ['ss1']},
                     {'sop_instance_uid': 'p2', 'rt_plan_label': 'final_v2',
                      'approval_status': 'UNAPPROVED',
                      'referenced_structure_set_uids': ['ss1']}]},
                {'series_instance_uid': 'ds', 'modality': 'RTDOSE',
                 'series_number': 15, 'instances': 1,
                 'rt_instances': [
                     {'sop_instance_uid': 'd1',
                      'referenced_plan_uids': ['p1']}]},
            ],
        }]
        self.batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION')
        RetrievalBatchPatient.objects.create(
            batch=self.batch, patient=self.patient, studies=self.tree)

    def _post_selection(self, **entry_overrides):
        entry = {'study_instance_uid': self.STUDY_UID}
        entry.update(entry_overrides)
        self.client.force_login(self.user)
        with mock.patch('dicom_server.views.chord') as mock_chord:
            mock_chord.return_value.return_value.id = 'chord-e2e'
            resp = self.client.post(
                reverse('dicom_server:batch_retrieve',
                        args=[self.batch.pk]),
                data=json.dumps({'selections': {
                    self.patient.patient_id: [entry],
                }}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        job = RetrievalJob.objects.get()
        job.status = RetrievalJob.Status.RUNNING
        job.save(update_fields=['status'])
        return job

    def _audit_status(self, sop_uid):
        entry = InboundDICOMInstance.objects.filter(
            sop_instance_uid=sop_uid).first()
        return entry.status if entry else None

    def test_select_only_approved_plan(self):
        job = self._post_selection(sop_instance_uids=['p1'])
        study = job.studies.get()
        self.assertEqual(study.selected_sop_instance_uids, ['p1', 'ss1'])
        self.assertEqual(
            sorted(study.series.values_list('series_instance_uid', flat=True)),
            ['ct', 'pl', 'ss'],
        )
        pid = self.patient.patient_id

        # Approved plan + its struct set + a CT slice: stored.
        self.assertEqual(ingest_dataset(make_rt_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='pl',
            sop_uid='p1', modality='RTPLAN', rt_plan_label='final',
            approval_status='APPROVED')).status, 0x0000)
        self.assertEqual(self._audit_status('p1'), 'STORED')
        self.assertEqual(ingest_dataset(make_rt_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='ss',
            sop_uid='ss1', modality='RTSTRUCT',
            structure_set_label='CT_FINAL')).status, 0x0000)
        self.assertEqual(self._audit_status('ss1'), 'STORED')
        ct = make_test_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='ct')
        ingest_dataset(ct)
        self.assertEqual(self._audit_status(ct.SOPInstanceUID), 'STORED')

        # Unapproved sibling plan in the SAME series: dropped.
        ingest_dataset(make_rt_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='pl',
            sop_uid='p2', modality='RTPLAN', rt_plan_label='final_v2',
            approval_status='UNAPPROVED'))
        self.assertEqual(self._audit_status('p2'), 'REJECTED')

        # Dose of the approved plan: not selected -> dropped.
        ingest_dataset(make_rt_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='ds',
            sop_uid='d1', modality='RTDOSE'))
        self.assertEqual(self._audit_status('d1'), 'REJECTED')

        # Slice of an image series that was never selected: dropped.
        other = make_test_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='ct9')
        ingest_dataset(other)
        self.assertEqual(self._audit_status(other.SOPInstanceUID), 'REJECTED')

    def test_legacy_series_level_job_stores_all_plans_of_series(self):
        job = self._post_selection(series_uids=['pl'])
        self.assertEqual(job.studies.get().selected_sop_instance_uids, [])
        pid = self.patient.patient_id
        for sop in ('p1', 'p2'):
            ingest_dataset(make_rt_dataset(
                patient_id=pid, study_uid=self.STUDY_UID, series_uid='pl',
                sop_uid=sop, modality='RTPLAN'))
            self.assertEqual(self._audit_status(sop), 'STORED')

    def test_whole_study_job_stores_everything(self):
        self._post_selection(series_uids=None, sop_instance_uids=None)
        self.assertEqual(
            RetrievalJob.objects.get().studies.get()
            .selected_sop_instance_uids, [])
        ingest_dataset(make_rt_dataset(
            patient_id=self.patient.patient_id, study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p2', modality='RTPLAN'))
        self.assertEqual(self._audit_status('p2'), 'STORED')
