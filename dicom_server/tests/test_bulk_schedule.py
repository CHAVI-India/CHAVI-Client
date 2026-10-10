"""Tests for scheduled bulk retrieval: model, selection criteria service,
dispatch/schedule tasks, form, and views."""
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from unittest import mock

from django.test import override_settings

from client_app.models import Patient, SiteConfiguration
from dicom_server.models import (
    BulkRetrievalSchedule, RemoteDICOMNode, RetrievalBatch,
    RetrievalBatchPatient, RetrievalJob,
)
from dicom_server.tasks import (
    _aggregate_retrieval_batch, _prepare_bulk_schedule_batch,
    task_bulk_schedule_run,
)
from dicom_server.tasks import task_bulk_schedule_finalize_query
from dicom_server.tasks import (
    task_bulk_schedule_chunk_done, task_bulk_schedule_finalize_retrieval,
)
from dicom_server.services import bulk_selection
from dicom_server.services.bulk_selection import (
    SelectionCriteria, build_selections_for_patient, select_study,
)


class ModelSetupMixin:
    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test',
        )
        cls.node = RemoteDICOMNode.objects.create(
            name='Stub PACS', ae_title='STUBPACS', host='127.0.0.1', port=104,
        )

    def _patient(self, patient_id='P001', consent=True):
        p = Patient.objects.create(patient_id=patient_id, gender='Female')
        if consent:
            Patient.objects.filter(pk=p.pk).update(chavi_consent=True)
            p.chavi_consent = True
        return p


class BulkRetrievalScheduleModelTests(ModelSetupMixin, TestCase):
    def test_one_off_defaults(self):
        run_at = timezone.now() + timedelta(hours=2)
        s = BulkRetrievalSchedule.objects.create(
            name='nightly-ish', node=self.node, mode='ONE_OFF', run_at=run_at,
        )
        s.patients.set([self._patient()])
        self.assertEqual(s.max_concurrent_patients, 2)
        self.assertTrue(s.retrieve_new_only)
        self.assertEqual(s.beat_name, f'dicom-bulk-schedule-{s.pk}')

    def test_crontab_tuple(self):
        s = BulkRetrievalSchedule(
            name='x', node=self.node, mode='PERIODIC',
            minute='30', hour='2', day_of_week='*',
            day_of_month='*', month_of_year='*',
        )
        self.assertEqual(s.crontab_tuple, ('30', '2', '*', '*', '*'))

    def test_invalid_cron_field_rejected(self):
        s = BulkRetrievalSchedule(
            name='x', node=self.node, mode='PERIODIC', minute='61x',
        )
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_one_off_requires_run_at(self):
        s = BulkRetrievalSchedule(name='x', node=self.node, mode='ONE_OFF')
        with self.assertRaises(ValidationError):
            s.full_clean()


def _fake_studies(uids, already_local=()):
    local = set(already_local)
    return [
        {'study_instance_uid': u, 'study_date': '20240101',
         'study_description': '', 'modalities': 'CT', 'instances': 1,
         'remote_patient_id': 'P001', 'already_local': u in local}
        for u in uids
    ], []


class PrepareBatchTests(ModelSetupMixin, TestCase):
    def test_one_row_per_consented_patient(self):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        p_con = self._patient('PC')
        p_no = self._patient('PN', consent=False)
        s.patients.set([p_con, p_no])
        batch, patients = _prepare_bulk_schedule_batch(s)
        self.assertIsInstance(batch, RetrievalBatch)
        self.assertEqual(batch.node_id, self.node.pk)
        self.assertEqual([p.patient_id for p in patients], ['PC'])
        self.assertEqual(batch.patients.count(), 1)


class AggregateTests(ModelSetupMixin, TestCase):
    def _batch_with_jobs(self):
        batch = RetrievalBatch.objects.create(node=self.node)
        p1 = self._patient('A'); p2 = self._patient('B'); p3 = self._patient('C')
        for p, status, instances in [
            (p1, 'SUCCESS', 5), (p2, 'PARTIAL', 2), (p3, 'FAILED', 0),
        ]:
            j = RetrievalJob.objects.create(
                node=self.node, patient=p, status=status,
                instances_received=instances, batch=batch,
            )
            RetrievalBatchPatient.objects.create(
                batch=batch, patient=p, selected=True, job=j,
            )
        return batch

    def test_aggregate_mixed(self):
        batch = self._batch_with_jobs()
        final, summary = _aggregate_retrieval_batch(batch)
        self.assertEqual(final, 'PARTIAL')
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['instances'], 7)
        self.assertEqual(sorted(summary['succeeded']), ['A'])
        self.assertEqual(sorted(summary['failed']), ['C'])


class RunTaskTests(ModelSetupMixin, TestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @mock.patch('dicom_server.tasks.task_bulk_schedule_finalize_query', create=True)
    @mock.patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_creates_batch_and_dispatches(self, mock_find, mock_final):
        mock_find.return_value = _fake_studies(['1.1'])
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        s.patients.set([self._patient('P001')])
        task_bulk_schedule_run(schedule_id=s.pk)
        s.refresh_from_db()
        self.assertIsNotNone(s.last_batch_id)
        self.assertEqual(s.last_batch.patients.count(), 1)
        self.assertTrue(s.last_batch.query_group_id)
        mock_find.assert_called()
        mock_final.s.assert_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @mock.patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_inactive_node_skips(self, mock_find):
        self.node.is_active = False
        self.node.save()
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        s.patients.set([self._patient('P001')])
        res = task_bulk_schedule_run(schedule_id=s.pk)
        self.assertTrue(res.get('skipped'))
        self.assertFalse(RetrievalBatch.objects.exists())


def _series(uid, mod, desc='', parents=(), rt=None):
    se = {
        'series_instance_uid': uid, 'modality': mod,
        'series_description': desc, 'series_number': '',
        'series_date': '20240101', 'instances': 1,
    }
    if parents:
        se['parent_series_uids'] = list(parents)
    if rt is not None:
        se['rt_instances'] = rt
    return se


def _study(uid, series, already_local=False):
    mods = sorted({(s.get('modality') or '') for s in series if s.get('modality')})
    return {
        'study_instance_uid': uid, 'study_date': '20240101',
        'study_description': 'Study', 'accession_number': 'A1',
        'modalities': '\\'.join(mods) if mods else 'OT',
        'instances': sum(s.get('instances') or 0 for s in series),
        'remote_patient_id': 'P001', 'already_local': already_local,
        'series': series,
    }


def _rt_study(uid='ST-1', already_local=False):
    img = _series('S-IMG', 'CT', 'Images')
    struct = _series('S-STRUCT', 'RTSTRUCT', 'Structures', parents=('S-IMG',),
                     rt=[{'sop_instance_uid': 'SOP-SS', 'structure_set_label': 'Body',
                          'structure_set_name': 'Body',
                          'referenced_series_uids': ['S-IMG']}])
    plan = _series('S-PLAN', 'RTPLAN', 'Plan A', parents=('S-STRUCT',),
                   rt=[{'sop_instance_uid': 'SOP-PLAN', 'rt_plan_label': 'PlanA',
                        'rt_plan_name': 'Plan A', 'approval_status': 'APPROVED',
                        'referenced_structure_set_uids': ['SOP-SS']}])
    plan_bad = _series('S-PLAN2', 'RTPLAN', 'Plan B', parents=('S-STRUCT',),
                       rt=[{'sop_instance_uid': 'SOP-PLAN2', 'rt_plan_label': 'PlanB',
                            'approval_status': 'REJECTED',
                            'referenced_structure_set_uids': ['SOP-SS']}])
    dose = _series('S-DOSE', 'RTDOSE', 'Dose', parents=('S-PLAN',),
                   rt=[{'sop_instance_uid': 'SOP-DOSE',
                        'referenced_plan_uids': ['SOP-PLAN']}])
    return _study(uid, [img, struct, plan, plan_bad, dose], already_local)


class SelectionCriteriaParseTests(ModelSetupMixin, TestCase):
    def test_model_builds_criteria(self):
        s = BulkRetrievalSchedule.objects.create(
            name='x', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
            select_modalities='CT, MR', select_approval='approved',
            select_rt_label='Body', select_series_description='Dose',
        )
        c = s.selection_criteria()
        self.assertEqual(c.modalities, ['CT', 'MR'])
        self.assertEqual(c.approval, 'approved')
        self.assertEqual(c.rt_label, 'Body')
        self.assertTrue(c.series_filter_active())


class BulkSelectionTests(TestCase):
    def test_no_criteria_selects_whole_study(self):
        self.assertEqual(select_study(_rt_study(), SelectionCriteria()),
                         ('ST-1', None))

    def test_new_only_skips_local(self):
        st = _rt_study(already_local=True)
        self.assertEqual(build_selections_for_patient([st], SelectionCriteria(),
                                                         new_only=True), [])

    def test_modality_filter_no_ancestors(self):
        sel = select_study(_rt_study(), SelectionCriteria(modalities=['CT']))
        self.assertEqual(sel, ('ST-1', ['S-IMG']))

    def test_dose_pulls_plan_and_struct(self):
        sel = select_study(_rt_study(), SelectionCriteria(modalities=['RTDOSE']))
        self.assertIsNotNone(sel)
        self.assertEqual(set(sel[1]), {'S-DOSE', 'S-PLAN', 'S-STRUCT', 'S-IMG'})

    def test_approval_approved_excludes_unapproved_plan(self):
        sel = select_study(_rt_study(), SelectionCriteria(approval='approved'))
        chosen = set(sel[1])
        self.assertIn('S-PLAN', chosen)
        self.assertNotIn('S-PLAN2', chosen)

    def test_approval_unapproved_only(self):
        sel = select_study(_rt_study(), SelectionCriteria(approval='unapproved'))
        self.assertIn('S-PLAN2', sel[1])
        self.assertNotIn('S-PLAN', set(sel[1]))

    def test_rt_label_match_pulls_struct(self):
        sel = select_study(_rt_study(), SelectionCriteria(rt_label='PlanA'))
        self.assertIn('S-PLAN', sel[1])
        self.assertIn('S-STRUCT', set(sel[1]))
        self.assertNotIn('S-PLAN2', set(sel[1]))

    def test_series_description_match(self):
        sel = select_study(_rt_study(), SelectionCriteria(series_description='Dose'))
        self.assertEqual(set(sel[1]), {'S-STRUCT', 'S-DOSE', 'S-PLAN', 'S-IMG'})

    def test_no_matching_series_yields_none(self):
        self.assertIsNone(
            select_study(_rt_study(), SelectionCriteria(modalities=['MR'])))

    def test_build_selections_multiple_studies(self):
        a = _rt_study('ST-1')
        b = _study('ST-2', [_series('S2', 'MR', 'MRI')])
        entries = build_selections_for_patient([a, b],
                                               SelectionCriteria(modalities=['MR']))
        self.assertEqual([e['study_instance_uid'] for e in entries], ['ST-2'])
        self.assertEqual(entries[0]['series_instance_uids'], ['S2'])


class FinalizeQueryTests(ModelSetupMixin, TestCase):
    def _schedule(self, **kw):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        for k, v in kw.items():
            setattr(s, k, v)
        s.save()
        return s

    def _row(self, batch, pid, studies):
        p = self._patient(pid)
        row = RetrievalBatchPatient.objects.create(
            batch=batch, patient=p, query_status='DONE',
        )
        row.studies = studies
        row.save(update_fields=['studies'])
        return row

    @mock.patch('dicom_server.tasks._dispatch_retrieval_chunk')
    def test_no_criteria_selects_whole_study(self, mock_dispatch):
        batch = RetrievalBatch.objects.create(node=self.node, status='QUERYING')
        self._row(batch, 'P001', [_rt_study()])
        s = self._schedule(retrieve_new_only=True)
        task_bulk_schedule_finalize_query(results=[], batch_id=batch.pk, schedule_id=s.pk)
        j = batch.jobs.first()
        self.assertIsNotNone(j)
        self.assertIsNone(j.selections[0]['series_instance_uids'])
        self.assertEqual(j.selections[0]['study_instance_uid'], 'ST-1')
        mock_dispatch.assert_called_once()
        args = mock_dispatch.call_args[0]
        self.assertEqual(args[0].pk, batch.pk)
        self.assertEqual(args[2], 0)   # start
        self.assertEqual(args[4], 1)   # total jobs

    @mock.patch('dicom_server.tasks._dispatch_retrieval_chunk')
    def test_new_only_skips_local(self, mock_dispatch):
        batch = RetrievalBatch.objects.create(node=self.node, status='QUERYING')
        self._row(batch, 'P001', [_rt_study(already_local=True)])
        s = self._schedule(retrieve_new_only=True)
        task_bulk_schedule_finalize_query(results=[], batch_id=batch.pk, schedule_id=s.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'SUCCESS')
        self.assertEqual(batch.jobs.count(), 0)
        mock_dispatch.assert_not_called()

    @mock.patch('dicom_server.tasks._dispatch_retrieval_chunk')
    def test_modality_criteria_selects_series(self, mock_dispatch):
        batch = RetrievalBatch.objects.create(node=self.node, status='QUERYING')
        self._row(batch, 'P001', [_rt_study()])
        s = self._schedule(retrieve_new_only=False, select_modalities='RTDOSE')
        task_bulk_schedule_finalize_query(results=[], batch_id=batch.pk, schedule_id=s.pk)
        sel = batch.jobs.first().selections[0]
        self.assertEqual(
            set(sel['series_instance_uids']),
            {'S-DOSE', 'S-PLAN', 'S-STRUCT', 'S-IMG'},
        )


class ChunkRelayTests(ModelSetupMixin, TestCase):
    @mock.patch('dicom_server.tasks._dispatch_retrieval_chunk')
    def test_dispatches_next_chunk(self, mock_dispatch):
        batch = RetrievalBatch.objects.create(node=self.node, status='RETRIEVING')
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        task_bulk_schedule_chunk_done(
            results=[], batch_id=batch.pk, next_start=2, total=6,
            cap=2, schedule_id=s.pk,
        )
        mock_dispatch.assert_called_once_with(batch, s, 2, 2, 6)


class FinalizeRetrievalTests(ModelSetupMixin, TestCase):
    def _schedule(self):
        return BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )

    def test_aggregates_and_records(self):
        batch = RetrievalBatch.objects.create(node=self.node, status='RETRIEVING')
        s = self._schedule()
        for pid, status, inst in [('A', 'SUCCESS', 5), ('B', 'FAILED', 0)]:
            p = self._patient(pid)
            j = RetrievalJob.objects.create(
                node=self.node, patient=p, status=status,
                instances_received=inst, batch=batch,
            )
            RetrievalBatchPatient.objects.create(
                batch=batch, patient=p, selected=True, job=j,
            )
        task_bulk_schedule_finalize_retrieval(results=[], batch_id=batch.pk, schedule_id=s.pk)
        batch.refresh_from_db()
        s.refresh_from_db()
        self.assertEqual(batch.status, 'PARTIAL')
        self.assertEqual(batch.summary['instances'], 5)
        self.assertEqual(s.last_status, 'PARTIAL')
        self.assertIsNotNone(s.last_run_at)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ScheduledRunIntegrationTests(ModelSetupMixin, TestCase):
    """End-to-end scheduled run (query chord -> auto-select -> chunked
    retrieve -> finalize) with Q/R mocked."""

    def _studies_for(self, pid):
        return ([
            {'study_instance_uid': f'1.2.{pid}', 'study_date': '20240101',
             'study_description': '', 'modalities': 'CT', 'instances': 1,
             'remote_patient_id': pid, 'already_local': False},
        ]), []

    def test_end_to_end_retrieves_all_patients(self):
        p1 = self._patient('A'); p2 = self._patient('B'); p3 = self._patient('C')
        with mock.patch('dicom_server.tasks.qr_client.find_studies_with_series') as mf, \
                mock.patch('dicom_server.tasks.qr_client.move_study') as mm:
            mf.side_effect = lambda node, ids: self._studies_for(ids[0])
            mm.return_value = {'status': '0000', 'completed': 1, 'failed': 0}
            s = BulkRetrievalSchedule.objects.create(
                name='e2e', node=self.node, mode='ONE_OFF',
                run_at=timezone.now() + timedelta(hours=1),
                max_concurrent_patients=1, retrieve_new_only=True,
            )
            s.patients.set([p1, p2, p3])
            task_bulk_schedule_run(schedule_id=s.pk)

        s.refresh_from_db()
        batch = s.last_batch
        batch.refresh_from_db()
        self.assertEqual(batch.jobs.count(), 3)
        self.assertEqual(batch.status, 'SUCCESS')
        self.assertEqual(batch.summary['instances'], 3)
        self.assertEqual(s.last_status, 'SUCCESS')
        self.assertEqual(
            sorted(batch.summary['succeeded']), ['A', 'B', 'C'])
