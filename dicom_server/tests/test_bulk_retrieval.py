"""Tests for bulk retrieval: patient-ID transforms, batch models, query and
retrieve-phase tasks, and the new bulk endpoints."""
import json
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from client_app.models import Patient, DICOMStudy, SiteConfiguration
from dicom_server.forms import BulkRetrieveForm
from dicom_server.models import (
    PatientIDAlias, RemoteDICOMNode, RetrievalBatch, RetrievalBatchPatient,
    RetrievalJob,
)
from dicom_server.services import patient_ids
from dicom_server.tasks import (
    _job_work_items, task_finalize_batch_query, task_finalize_retrieval_batch,
    task_query_patient_studies, task_retrieve_patient_selection,
)


class BulkRetrievalTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Hospital',
        )
        cls.node = RemoteDICOMNode.objects.create(
            name='Stub PACS', ae_title='STUBPACS', host='127.0.0.1',
            port=104, prefer_c_get=True,
        )

    def _patient(self, patient_id, consent=True):
        patient = Patient.objects.create(patient_id=patient_id, gender='Female')
        if consent:
            # .update() bypasses the post_save signal (no broker in tests)
            Patient.objects.filter(pk=patient.pk).update(chavi_consent=True)
            patient.chavi_consent = True
        return patient


class TransformTests(TestCase):
    def test_apply_transforms_regex_replacement(self):
        transforms = [
            {'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'\1_\2'},
        ]
        self.assertEqual(
            patient_ids.apply_transforms('MR/25/004771', transforms),
            ['25_004771'],
        )

    def test_apply_transforms_non_matching_rule_produces_nothing(self):
        transforms = [
            {'pattern': r'^RT-(\d+)$', 'replacement': r'\1'},
        ]
        self.assertEqual(
            patient_ids.apply_transforms('MR/25/004771', transforms), [],
        )

    def test_apply_transforms_dedupes_and_skips_invalid(self):
        transforms = [
            {'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'\1\2'},
            {'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'\1\2'},  # duplicate
            {'pattern': '([invalid', 'replacement': 'x'},             # bad regex
            {'pattern': '', 'replacement': 'x'},                      # empty pattern
        ]
        self.assertEqual(
            patient_ids.apply_transforms('MR/25/004771', transforms),
            ['25004771'],
        )

    def test_validate_transforms(self):
        self.assertEqual(patient_ids.validate_transforms([]), [])
        self.assertEqual(
            patient_ids.validate_transforms(
                [{'pattern': 'a', 'replacement': 'b'}]), [],
        )
        errors = patient_ids.validate_transforms([
            {'pattern': '([bad', 'replacement': 'x'},
            {'pattern': 'ok'},
            'not a dict',
        ])
        self.assertEqual(len(errors), 3)

    def test_parse_and_render_lines(self):
        text = '^MR/(\\d+)/(\\d+)$ => \\1_\\2\n\n# comment\n^(.*)$'
        transforms = patient_ids.parse_transform_lines(text)
        self.assertEqual(transforms[0]['replacement'], '\\1_\\2')
        self.assertEqual(transforms[1], {'pattern': '^(.*)$', 'replacement': ''})
        self.assertIn('=>', patient_ids.transforms_to_lines(transforms))


class CandidateIDTests(BulkRetrievalTestCase):
    def test_remote_patient_ids_for_unions_all_sources(self):
        patient = self._patient('MR/25/004771')
        PatientIDAlias.objects.create(
            node=self.node, patient=patient, remote_patient_id='PACS-9981',
        )
        self.node.patient_id_transforms = [
            {'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'\1_\2'},
        ]
        ids = self.node.remote_patient_ids_for(patient)
        self.assertEqual(ids, ['MR/25/004771', 'PACS-9981', '25_004771'])

    def test_remote_patient_ids_for_extra_transforms(self):
        patient = self._patient('MR/25/004771')
        ids = self.node.remote_patient_ids_for(
            patient,
            extra_transforms=[{'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'X\2'}],
        )
        self.assertEqual(ids, ['MR/25/004771', 'X004771'])

    def test_multiple_aliases_per_patient_allowed(self):
        patient = self._patient('MR/25/004771')
        PatientIDAlias.objects.create(
            node=self.node, patient=patient, remote_patient_id='A-1',
        )
        PatientIDAlias.objects.create(
            node=self.node, patient=patient, remote_patient_id='A-2',
        )
        self.assertEqual(
            self.node.patient_aliases.filter(patient=patient).count(), 2,
        )

    def test_remote_id_still_unique_per_node(self):
        p1 = self._patient('P/1')
        p2 = self._patient('P/2')
        PatientIDAlias.objects.create(node=self.node, patient=p1, remote_patient_id='X')
        with self.assertRaises(Exception):
            PatientIDAlias.objects.create(node=self.node, patient=p2, remote_patient_id='X')


class BatchModelTests(BulkRetrievalTestCase):
    def test_batch_and_patient_rows(self):
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(node=self.node)
        item = RetrievalBatchPatient.objects.create(batch=batch, patient=patient)
        self.assertEqual(batch.patients.count(), 1)
        self.assertEqual(item.query_status, 'PENDING')
        self.assertEqual(str(batch), f'Batch {batch.pk} Stub PACS [QUERYING]')

    def test_job_batch_links(self):
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(node=self.node)
        job = RetrievalJob.objects.create(
            node=self.node, patient=patient, batch=batch,
            selections=[{'study_instance_uid': '1.2.3',
                         'series_instance_uids': None}],
        )
        self.assertEqual(batch.jobs.count(), 1)
        self.assertEqual(job.selections[0]['study_instance_uid'], '1.2.3')


class FormTests(BulkRetrievalTestCase):
    def test_bulk_form_rejects_nonconsented_patient(self):
        ok = self._patient('OK/1')
        bad = self._patient('BAD/1', consent=False)
        from django.utils.datastructures import MultiValueDict
        data = MultiValueDict({
            'node': [str(self.node.pk)],
            'patients': ['OK/1', 'BAD/1'],
        })
        form = BulkRetrieveForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn('consent', str(form.errors).lower())

    def test_bulk_form_parses_extra_transforms(self):
        self._patient('OK/1')
        from django.utils.datastructures import MultiValueDict
        data = MultiValueDict({
            'node': [str(self.node.pk)],
            'patients': ['OK/1'],
            'extra_transforms': ['^MR/(\\d+)/(\\d+)$ => \\1_\\2\n[bad'],
        })
        form = BulkRetrieveForm(data)
        self.assertFalse(form.is_valid())
        data['extra_transforms'] = '^MR/(\\d+)/(\\d+)$ => \\1_\\2'
        form = BulkRetrieveForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data['extra_transforms'][0]['replacement'], '\\1_\\2',
        )


class QueryTaskTests(BulkRetrievalTestCase):
    def setUp(self):
        self.patient = self._patient('MR/25/004771')
        self.batch = RetrievalBatch.objects.create(node=self.node)
        self.item = RetrievalBatchPatient.objects.create(
            batch=self.batch, patient=self.patient,
        )

    @mock.patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_query_task_populates_row(self, mock_find):
        mock_find.return_value = ([{
            'study_instance_uid': '1.2.3', 'study_date': '20240101',
            'study_description': 'CT', 'modalities': 'CT', 'instances': 3,
            'remote_patient_id': '25_004771',
            'series': [{'series_instance_uid': '9.9'}],
        }], [])
        result = task_query_patient_studies(self.batch.pk, self.patient.patient_id)
        self.item.refresh_from_db()
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(self.item.query_status, 'DONE')
        self.assertEqual(len(self.item.studies), 1)
        self.assertEqual(
            self.item.studies[0]['series'][0]['series_instance_uid'], '9.9',
        )
        self.assertEqual(self.item.remote_patient_ids, ['MR/25/004771'])

    @mock.patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_query_task_marks_error_row(self, mock_find):
        mock_find.side_effect = ConnectionError('dead')
        result = task_query_patient_studies(self.batch.pk, self.patient.patient_id)
        self.item.refresh_from_db()
        self.assertEqual(result['status'], 'ERROR')
        self.assertEqual(self.item.query_status, 'ERROR')
        self.assertIn('dead', self.item.error)

    def test_query_task_rejects_unconsented(self):
        Patient.objects.filter(pk=self.patient.pk).update(chavi_consent=False)
        task_query_patient_studies(self.batch.pk, self.patient.patient_id)
        self.item.refresh_from_db()
        self.assertEqual(self.item.query_status, 'ERROR')
        self.assertIn('consent', self.item.error)

    @mock.patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_query_task_marks_already_local(self, mock_find):
        DICOMStudy.objects.create(patient=self.patient, study_instance_uid='1.2.3')
        mock_find.return_value = ([{
            'study_instance_uid': '1.2.3', 'series': [],
        }], [])
        task_query_patient_studies(self.batch.pk, self.patient.patient_id)
        self.item.refresh_from_db()
        self.assertTrue(self.item.studies[0]['already_local'])

    @mock.patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_query_task_uses_node_transforms(self, mock_find):
        mock_find.return_value = ([], [])
        self.node.patient_id_transforms = [
            {'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'\1_\2'},
        ]
        self.node.save()
        self.batch.extra_transforms = [
            {'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'X\2'},
        ]
        self.batch.save()
        task_query_patient_studies(self.batch.pk, self.patient.patient_id)
        ids = mock_find.call_args[0][1]
        self.assertEqual(ids, ['MR/25/004771', '25_004771', 'X004771'])

    def test_finalize_batch_query(self):
        RetrievalBatchPatient.objects.filter(pk=self.item.pk).update(
            query_status='DONE')
        result = task_finalize_batch_query([], self.batch.pk)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, 'AWAITING_SELECTION')
        self.assertEqual(result['status'], 'AWAITING_SELECTION')
        self.assertEqual(self.batch.summary['queried'], 1)

    def test_finalize_batch_query_noop_when_done(self):
        self.batch.status = RetrievalBatch.Status.RETRIEVING
        self.batch.save(update_fields=['status'])
        task_finalize_batch_query([], self.batch.pk)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, 'RETRIEVING')


class RetrieveTaskTests(BulkRetrievalTestCase):
    def setUp(self):
        self.patient = self._patient('MR/25/004771')
        self.batch = RetrievalBatch.objects.create(node=self.node)

    def test_job_work_items(self):
        job = RetrievalJob.objects.create(
            node=self.node, patient=self.patient,
            selections=[{'study_instance_uid': '1.1',
                         'series_instance_uids': ['s1']}],
        )
        self.assertEqual(_job_work_items(job), job.selections)
        job2 = RetrievalJob.objects.create(
            node=self.node, patient=self.patient, study_uids=['2.2'],
        )
        self.assertEqual(
            _job_work_items(job2)[0]['study_instance_uid'], '2.2',
        )
        self.assertIsNone(_job_work_items(
            RetrievalJob(node=self.node, patient=self.patient),
        ))

    @mock.patch('dicom_server.tasks.qr_client.get_series')
    @mock.patch('dicom_server.tasks.qr_client.get_study')
    def test_selection_task_study_and_series(self, mock_get, mock_get_series):
        mock_get.return_value = {'status': 0, 'completed': 2, 'failed': 0}
        mock_get_series.return_value = {'status': 0, 'completed': 1, 'failed': 0}
        job = RetrievalJob.objects.create(
            node=self.node, patient=self.patient, batch=self.batch,
            selections=[
                {'study_instance_uid': '1.1', 'series_instance_uids': None},
                {'study_instance_uid': '1.2', 'series_instance_uids': ['s1', 's2'],
                 'remote_patient_id': '25_004771'},
            ],
        )
        result = task_retrieve_patient_selection(job.pk)
        self.assertEqual(result['status'], 'SUCCESS')
        mock_get.assert_called_once_with(self.node, '1.1', 'MR/25/004771')
        self.assertEqual(mock_get_series.call_count, 2)
        mock_get_series.assert_any_call(self.node, '1.2', 's1', '25_004771')
        job.refresh_from_db()
        self.assertEqual(job.status, 'SUCCESS')
        self.assertEqual(job.instances_received, 4)
        self.assertEqual(len(job.item_results), 3)

    @mock.patch('dicom_server.tasks.qr_client.get_study')
    def test_selection_task_never_raises(self, mock_get):
        mock_get.side_effect = RuntimeError('boom')
        job = RetrievalJob.objects.create(
            node=self.node, patient=self.patient,
            selections=[{'study_instance_uid': '1.1',
                         'series_instance_uids': None}],
        )
        result = task_retrieve_patient_selection(job.pk)
        self.assertEqual(result['status'], 'FAILED')
        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILED')

    def test_finalize_retrieval_batch_partial(self):
        p2 = self._patient('P/2')
        RetrievalJob.objects.create(
            node=self.node, patient=self.patient, batch=self.batch,
            status='SUCCESS', instances_received=2,
        )
        RetrievalJob.objects.create(
            node=self.node, patient=p2, batch=self.batch, status='FAILED',
        )
        RetrievalBatchPatient.objects.create(batch=self.batch, patient=p2)
        result = task_finalize_retrieval_batch([], self.batch.pk)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, 'PARTIAL')
        self.assertIn('P/2', self.batch.summary['failed'])
        self.assertIn('MR/25/004771', self.batch.summary['succeeded'])
        self.assertEqual(result['instances'], 2)


class BulkViewTests(BulkRetrievalTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create_user('bulkop', password='pw')
        cls.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_server',
            codename__in=[
                'view_remotedicomnode', 'add_retrievaljob', 'view_retrievaljob',
            ],
        ))
        cls.plain = User.objects.create_user('plainuser', password='pw')
        cls.node_admin = User.objects.create_user('nodeadm', password='pw')
        cls.node_admin.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_server',
            codename__in=['change_remotedicomnode'],
        ))

    def _post_json(self, url, payload):
        return self.client.post(
            url, data=json.dumps(payload), content_type='application/json',
        )

    def test_bulk_page_permission_gating(self):
        self.client.force_login(self.plain)
        self.assertEqual(
            self.client.get(reverse('dicom_server:retrieve_bulk')).status_code,
            403,
        )
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(reverse('dicom_server:retrieve_bulk')).status_code,
            200,
        )

    @mock.patch('dicom_server.views.chord')
    def test_batch_query_creates_rows_and_dispatches(self, mock_chord):
        mock_chord.return_value.return_value.id = 'chord-1'
        self._patient('MR/25/004771')
        self.client.force_login(self.user)
        resp = self._post_json(reverse('dicom_server:batch_query'), {
            'node': self.node.pk, 'patients': ['MR/25/004771'],
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        batch = RetrievalBatch.objects.get()
        self.assertEqual(resp.json()['batch_id'], batch.pk)
        self.assertEqual(batch.patients.count(), 1)
        self.assertEqual(batch.status, 'QUERYING')
        mock_chord.assert_called_once()

    def test_batch_query_rejects_nonconsented(self):
        self._patient('NOC/1', consent=False)
        self.client.force_login(self.user)
        resp = self._post_json(reverse('dicom_server:batch_query'), {
            'node': self.node.pk, 'patients': ['NOC/1'],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(RetrievalBatch.objects.exists())

    def test_batch_query_denied_without_permission(self):
        self._patient('MR/25/004771')
        self.client.force_login(self.plain)
        resp = self._post_json(reverse('dicom_server:batch_query'), {
            'node': self.node.pk, 'patients': ['MR/25/004771'],
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(RetrievalBatch.objects.exists())

    def test_batch_status_shape(self):
        batch = RetrievalBatch.objects.create(node=self.node)
        RetrievalBatchPatient.objects.create(
            batch=batch, patient=self._patient('P/9'),
            studies=[{'study_instance_uid': '1.2'}],
        )
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse('dicom_server:batch_status', args=[batch.pk]))
        data = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['patients'][0]['patient_id'], 'P/9')
        self.assertEqual(
            data['patients'][0]['studies'][0]['study_instance_uid'], '1.2',
        )

    @mock.patch('dicom_server.views.chord')
    def test_batch_retrieve_creates_jobs_and_chord(self, mock_chord):
        mock_chord.return_value.return_value.id = 'chord-2'
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION',
        )
        item = RetrievalBatchPatient.objects.create(
            batch=batch, patient=patient,
            studies=[{
                'study_instance_uid': '1.2', 'remote_patient_id': 'X',
                'series': [{'series_instance_uid': 's1'},
                           {'series_instance_uid': 's2'}],
            }],
        )
        self.client.force_login(self.user)
        resp = self._post_json(
            reverse('dicom_server:batch_retrieve', args=[batch.pk]),
            {'selections': {
                patient.patient_id: [{
                    'study_instance_uid': '1.2',
                    'series_instance_uids': ['s1'],
                }],
            }},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        job = RetrievalJob.objects.get()
        self.assertEqual(job.batch, batch)
        self.assertEqual(
            job.selections[0]['series_instance_uids'], ['s1'],
        )
        self.assertEqual(job.selections[0]['remote_patient_id'], 'X')
        item.refresh_from_db()
        self.assertTrue(item.selected)
        self.assertEqual(item.job, job)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'RETRIEVING')
        mock_chord.assert_called_once()

    def test_batch_retrieve_rejects_unknown_uids(self):
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION',
        )
        RetrievalBatchPatient.objects.create(
            batch=batch, patient=patient,
            studies=[{'study_instance_uid': '1.2',
                      'series': [{'series_instance_uid': 's1'}]}],
        )
        self.client.force_login(self.user)
        url = reverse('dicom_server:batch_retrieve', args=[batch.pk])
        resp = self._post_json(url, {'selections': {
            patient.patient_id: [{'study_instance_uid': 'BOGUS'}],
        }})
        self.assertEqual(resp.status_code, 400)
        resp = self._post_json(url, {'selections': {
            patient.patient_id: [{
                'study_instance_uid': '1.2',
                'series_instance_uids': ['sX'],
            }],
        }})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(RetrievalJob.objects.exists())

    def test_batch_retrieve_requires_awaiting_selection(self):
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(node=self.node)
        RetrievalBatchPatient.objects.create(batch=batch, patient=patient)
        self.client.force_login(self.user)
        resp = self._post_json(
            reverse('dicom_server:batch_retrieve', args=[batch.pk]),
            {'selections': {patient.patient_id: [{'study_instance_uid': 'x'}]}},
        )
        self.assertEqual(resp.status_code, 409)

    def test_alias_create_and_conflict(self):
        patient = self._patient('MR/25/004771')
        other = self._patient('P/2')
        PatientIDAlias.objects.create(
            node=self.node, patient=other, remote_patient_id='X-1',
        )
        batch = RetrievalBatch.objects.create(node=self.node)
        self.client.force_login(self.user)
        url = reverse('dicom_server:batch_alias', args=[batch.pk])
        resp = self._post_json(url, {
            'patient_id': patient.patient_id, 'remote_patient_id': 'X-1',
        })
        self.assertEqual(resp.status_code, 409)
        resp = self._post_json(url, {
            'patient_id': patient.patient_id, 'remote_patient_id': 'X-2',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(PatientIDAlias.objects.filter(
            node=self.node, patient=patient, remote_patient_id='X-2',
        ).exists())

    @mock.patch('dicom_server.views.chord')
    def test_requery_resets_row(self, mock_chord):
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION',
        )
        item = RetrievalBatchPatient.objects.create(
            batch=batch, patient=patient, query_status='ERROR', error='x',
        )
        self.client.force_login(self.user)
        resp = self._post_json(
            reverse('dicom_server:batch_requery', args=[batch.pk]),
            {'patient_id': patient.patient_id},
        )
        self.assertEqual(resp.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.query_status, 'PENDING')
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'QUERYING')

    def test_node_id_rules_endpoint(self):
        url = reverse('dicom_server:node_id_rules', args=[self.node.pk])
        self.client.force_login(self.user)  # lacks change_remotedicomnode
        resp = self._post_json(url, {'transforms': []})
        self.assertEqual(resp.status_code, 403)
        self.client.force_login(self.node_admin)
        resp = self._post_json(url, {'transforms': [
            {'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'\1_\2'},
        ]})
        self.assertEqual(resp.status_code, 200)
        self.node.refresh_from_db()
        self.assertEqual(len(self.node.patient_id_transforms), 1)
        resp = self._post_json(url, {'transforms': [
            {'pattern': '([bad', 'replacement': 'x'},
        ]})
        self.assertEqual(resp.status_code, 400)

    def test_batch_list_and_detail_pages(self):
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(node=self.node)
        item = RetrievalBatchPatient.objects.create(batch=batch, patient=patient)
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(reverse('dicom_server:batch_list')).status_code, 200,
        )
        resp = self.client.get(
            reverse('dicom_server:batch_detail', args=[batch.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'MR/25/004771')
