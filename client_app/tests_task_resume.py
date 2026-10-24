"""
Verification tests for the task-resume remediation (see
docs/task_resume_audit_and_remediation.md).

Covers:
  * the extended on-disk checkpoint service (payload entries, last-wins)
  * the legacy-import service (full run, resume skip + stats reconstruction,
    unmatched-row cap)
  * the legacy-import task (inputs deleted only on success, kept on failure,
    soft-time-limit auto-continue)
  * TASK_REGISTRY / RESUME_NOTES coverage for every newly-resumable task
  * archive idempotency (already-archived studies are skipped)
  * retrieval skip-done (a rerun does not re-pull completed items)
  * stuck-batch recovery (lost chord results / hard-killed header tasks)
  * the progress-page resume bar
"""
import base64
import os
import sqlite3
import tempfile
from datetime import timedelta
from unittest import mock

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from client_app.models import (
    Patient, DICOMStudy, DICOMSeries, DICOMInstance, TaskRun,
)
from client_app.services.task_checkpoint import (
    write_manifest_entry, read_manifest_entries, read_manifest,
)
from client_app import views as client_views


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encrypt_value(plaintext: str, key: bytes) -> str:
    """Mirror of legacy_import._decrypt_value (AES-CBC + PKCS7, iv prepended)."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ct).decode()


def _ensure_site():
    """Patient.center defaults to the first SiteConfiguration row."""
    from client_app.models import SiteConfiguration
    if not SiteConfiguration.objects.exists():
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Center')


def _make_legacy_db(path, key, patients, studies, series, instances):
    """Create a legacy SQLite DB with the four expected tables.

    Each argument is a list of already-encrypted/plain field tuples matching
    the column order the importer reads.
    """
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE patients ("
              "encrypted_patient_id TEXT, deidentified_patient_id TEXT, "
              "deidentified_date_of_birth TEXT, encrypted_date_shift_value TEXT)")
    c.execute("CREATE TABLE dicom_studies ("
              "encrypted_study_uid TEXT, deidentified_study_uid TEXT, "
              "deidentified_study_date TEXT, encrypted_patient_id TEXT)")
    c.execute("CREATE TABLE dicom_series ("
              "encrypted_series_uid TEXT, deidentified_series_uid TEXT, "
              "deidentified_series_date TEXT, "
              "deidentified_frame_of_reference_uid TEXT, encrypted_study_uid TEXT)")
    c.execute("CREATE TABLE dicom_instances ("
              "encrypted_sop_instance_uid TEXT, deidentified_sop_instance_uid TEXT, "
              "encrypted_series_uid TEXT)")
    c.executemany("INSERT INTO patients VALUES (?,?,?,?)", patients)
    c.executemany("INSERT INTO dicom_studies VALUES (?,?,?,?)", studies)
    c.executemany("INSERT INTO dicom_series VALUES (?,?,?,?,?)", series)
    c.executemany("INSERT INTO dicom_instances VALUES (?,?,?)", instances)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 1. Checkpoint service
# ---------------------------------------------------------------------------

class TaskCheckpointServiceTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, 'm.jsonl')

    def test_write_and_read_entries_with_payload(self):
        write_manifest_entry(self.path, 'patient:1', status='done')
        write_manifest_entry(self.path, 'study:2', status='unmatched',
                             payload={'type': 'study', 'original_id': 'X'})
        entries = read_manifest_entries(self.path)
        self.assertEqual(set(entries), {'patient:1', 'study:2'})
        self.assertEqual(entries['patient:1']['status'], 'done')
        self.assertEqual(entries['study:2']['payload']['original_id'], 'X')

    def test_read_manifest_entries_last_wins(self):
        write_manifest_entry(self.path, 'patient:1', status='unmatched',
                             payload={'n': 1})
        write_manifest_entry(self.path, 'patient:1', status='done')
        entries = read_manifest_entries(self.path)
        self.assertEqual(entries['patient:1']['status'], 'done')

    def test_read_manifest_wrapper_only_done(self):
        write_manifest_entry(self.path, 'a', status='done')
        write_manifest_entry(self.path, 'b', status='unmatched')
        self.assertEqual(read_manifest(self.path), {'a'})

    def test_read_missing_file(self):
        self.assertEqual(read_manifest_entries(self.path), {})
        self.assertEqual(read_manifest(self.path), set())


# ---------------------------------------------------------------------------
# 2. Legacy import service
# ---------------------------------------------------------------------------

class LegacyImportServiceTests(TestCase):
    def setUp(self):
        from deidentification.models import DeidPatient
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.key = os.urandom(16)
        _ensure_site()
        self.db_path = os.path.join(self._tmp.name, 'legacy.db')
        self.key_path = os.path.join(self._tmp.name, 'key.bin')
        with open(self.key_path, 'wb') as f:
            f.write(self.key)

        # client_app side: P1 exists (matches), P2 does not (unmatched)
        self.p1 = Patient.objects.create(patient_id='P1')
        self.p2_missing = 'P2'

        patients = [
            (_encrypt_value('P1', self.key), 'DP1', '1990-01-01',
             _encrypt_value('5', self.key)),
            (_encrypt_value('P2', self.key), 'DP2', '1991-01-01',
             _encrypt_value('6', self.key)),
        ]
        _make_legacy_db(self.db_path, self.key, patients, [], [], [])
        self.DeidPatient = DeidPatient

    def _run(self, completed_entries=None, cap=None):
        from deidentification.services.legacy_import import import_legacy_mappings
        return import_legacy_mappings(
            self.db_path, self.key_path,
            completed_entries=completed_entries,
            manifest_write_callback=(lambda i, s='done', p=None: cap.append((i, s, p))) if cap is not None else None,
        )

    def test_full_run(self):
        cap = []
        stats = self._run(cap=cap)
        self.assertEqual(stats['patients'], 1)
        self.assertEqual(stats['unmatched'], 1)
        self.assertEqual(stats['unmatched_total'], 1)
        self.assertTrue(self.DeidPatient.objects.filter(patient=self.p1).exists())
        # both rows checkpointed
        self.assertEqual({i for i, _, _ in cap}, {'patient:1', 'patient:2'})

    def test_resume_skips_completed_and_reconstructs_stats(self):
        # Simulate a prior run that already imported P1 (rowid 1).
        completed = {'patient:1': {'item_id': 'patient:1', 'status': 'done'}}
        cap = []
        stats = self._run(completed_entries=completed, cap=cap)
        # Only the unmatched row (rowid 2) is processed this run.
        self.assertEqual([i for i, _, _ in cap], ['patient:2'])
        # Stats reconstructed to match a full run.
        self.assertEqual(stats['patients'], 1)
        self.assertEqual(stats['unmatched'], 1)
        self.assertEqual(stats['unmatched_total'], 1)

    def test_unmatched_rows_capped(self):
        from deidentification.services import legacy_import as li
        # Rebuild a DB with more unmatched patients than the (patched) cap.
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        many = [
            (_encrypt_value(f'PX{i}', self.key), f'DPX{i}', '1990-01-01',
             _encrypt_value('1', self.key))
            for i in range(8)
        ]
        _make_legacy_db(self.db_path, self.key, many, [], [], [])
        with mock.patch.object(li, 'UNMATCHED_ROWS_CAP', 5):
            stats = self._run()
        self.assertEqual(stats['unmatched_total'], 8)
        self.assertEqual(len(stats['unmatched_rows']), 5)


# ---------------------------------------------------------------------------
# 3. Legacy import task
# ---------------------------------------------------------------------------

class LegacyImportTaskTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.media = override_settings(MEDIA_ROOT=self._tmp.name)
        self.media.enable()
        self.addCleanup(self.media.disable)
        self.user = User.objects.create_user(username='legacy', password='pw')
        self.db_path = os.path.join(self._tmp.name, 'up.db')
        self.key_path = os.path.join(self._tmp.name, 'up.key')
        for p in (self.db_path, self.key_path):
            with open(p, 'wb') as f:
                f.write(b'x')
        # close_old_connections would drop the TestCase connection.
        self._conn = mock.patch('deidentification.tasks.close_old_connections')
        self._conn.start()
        self.addCleanup(self._conn.stop)

    def _apply(self, task_id='legacy-1'):
        from deidentification.tasks import import_legacy_mapping_task
        return import_legacy_mapping_task.apply(
            args=[self.db_path, self.key_path],
            kwargs={'user_id': self.user.id},
            task_id=task_id,
        )

    def test_success_deletes_inputs(self):
        with mock.patch(
            'deidentification.services.legacy_import.import_legacy_mappings',
            return_value={'patients': 1, 'unmatched': 0, 'unmatched_rows': [],
                          'unmatched_total': 0},
        ):
            res = self._apply()
        self.assertEqual(res.state, 'SUCCESS')
        self.assertFalse(os.path.exists(self.db_path))
        self.assertFalse(os.path.exists(self.key_path))
        run = TaskRun.objects.get(task_id='legacy-1')
        self.assertEqual(run.status, TaskRun.Status.SUCCESS)

    def test_failure_keeps_inputs(self):
        with mock.patch(
            'deidentification.services.legacy_import.import_legacy_mappings',
            side_effect=RuntimeError('boom'),
        ):
            res = self._apply()
        # Eager mode swallows the exception into the result state.
        self.assertEqual(res.state, 'FAILURE')
        # Inputs must survive a failure so a resume can re-read them.
        self.assertTrue(os.path.exists(self.db_path))
        self.assertTrue(os.path.exists(self.key_path))
        run = TaskRun.objects.get(task_id='legacy-1')
        self.assertEqual(run.status, TaskRun.Status.FAILURE)

    def test_soft_time_limit_auto_continues(self):
        from celery.exceptions import SoftTimeLimitExceeded
        with mock.patch(
            'deidentification.services.legacy_import.import_legacy_mappings',
            side_effect=SoftTimeLimitExceeded(),
        ), mock.patch(
            'deidentification.tasks._auto_continue_task',
            return_value=mock.Mock(id='new-celery-id'),
        ) as mock_ac:
            res = self._apply()
        self.assertEqual(res.result, {'auto_continued': True})
        mock_ac.assert_called_once()
        # Inputs kept for the continuation.
        self.assertTrue(os.path.exists(self.db_path))


# ---------------------------------------------------------------------------
# 4. Registry / notes coverage
# ---------------------------------------------------------------------------

class TaskRegistryCoverageTests(TestCase):
    NEWLY_RESUMABLE = [
        'import_legacy_mapping',
        'build_dicom_download_zip',
        'build_clinical_download_zip',
        'create_missing_records',
        'finalize_deidentification_batch',
        'archive_studies',
        'dearchive_studies',
        'dicom_server.task_retrieve_studies',
        'dicom_server.task_retrieve_patient_selection',
    ]

    def test_newly_resumable_tasks_registered(self):
        for name in self.NEWLY_RESUMABLE:
            self.assertIn(name, client_views.TASK_REGISTRY, name)

    def test_every_registered_task_has_a_note(self):
        missing = set(client_views.TASK_REGISTRY) - set(client_views.RESUME_NOTES)
        self.assertEqual(missing, set())

    def test_can_resume_helper(self):
        user = User.objects.create_user(username='reg', password='pw')
        resumable = TaskRun.objects.create(
            task_id='r-1', task_name='import_legacy_mapping',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            status=TaskRun.Status.FAILURE, user=user,
            task_args=['a', 'b'], task_kwargs={},
        )
        not_registered = TaskRun.objects.create(
            task_id='r-2', task_name='not_a_real_task',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            status=TaskRun.Status.FAILURE, user=user,
            task_args=['a'], task_kwargs={},
        )
        no_args = TaskRun.objects.create(
            task_id='r-3', task_name='import_legacy_mapping',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            status=TaskRun.Status.FAILURE, user=user,
            task_args=None, task_kwargs=None,
        )
        self.assertTrue(client_views.task_run_can_resume(resumable))
        self.assertFalse(client_views.task_run_can_resume(not_registered))
        self.assertFalse(client_views.task_run_can_resume(no_args))


# ---------------------------------------------------------------------------
# 5. Archive idempotency
# ---------------------------------------------------------------------------

class ArchiveIdempotencyTests(TestCase):
    def setUp(self):
        from dicom_archive.models import ArchiveLocation  # noqa: F401
        _ensure_site()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_already_archived_study_is_skipped(self):
        from dicom_archive.models import ArchiveLocation, ArchivedStudy
        from dicom_archive.services.archive import archive_studies

        loc = ArchiveLocation.objects.create(name='L1', path='/tmp/arch')
        patient = Patient.objects.create(patient_id='PA')
        study = DICOMStudy.objects.create(patient=patient, study_instance_uid='S1')
        # Pre-existing ARCHIVED record at the same location.
        ArchivedStudy.objects.create(
            study=study, location=loc, status=ArchivedStudy.Status.ARCHIVED,
            archive_rel_path='PA/S1',
        )
        with mock.patch(
            'dicom_archive.services.archive.archive_study',
        ) as mock_one:
            result = archive_studies([study], loc)
        self.assertEqual(result['skipped'], ['S1'])
        self.assertEqual(result['archived'], [])
        self.assertEqual(result['failed'], {})
        mock_one.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Retrieval skip-done
# ---------------------------------------------------------------------------

class RetrievalSkipDoneTests(TestCase):
    def setUp(self):
        from dicom_server.models import RemoteDICOMNode, RetrievalJob, RetrievalJobStudy
        _ensure_site()
        self.node = RemoteDICOMNode.objects.create(
            name='N', ae_title='AE', host='127.0.0.1', port=104, prefer_c_get=True)
        self.patient = Patient.objects.create(patient_id='RP')
        self.job = RetrievalJob.objects.create(node=self.node, patient=self.patient)
        # Two whole-study work items; the first is already done.
        self.s1 = RetrievalJobStudy.objects.create(
            job=self.job, study_instance_uid='STUDY-1',
            status='done', completed=5, failed=0, warning=0)
        self.s2 = RetrievalJobStudy.objects.create(
            job=self.job, study_instance_uid='STUDY-2', status=None)

    def test_done_item_is_not_re_pulled(self):
        from dicom_server.tasks import _run_job_retrieval
        with mock.patch(
            'dicom_server.services.qr_client.get_study',
            return_value={'status': 0, 'completed': 3, 'failed': 0, 'warning': 0},
        ) as mock_get:
            result = _run_job_retrieval(self.job, self.node, self.patient)
        # Only the not-done study is pulled.
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(mock_get.call_args[0][1], 'STUDY-2')
        # Instances fold in the done study's stored count (5) + new (3).
        self.assertEqual(result['instances_completed'], 8)
        self.assertEqual(result['status'], 'SUCCESS')


# ---------------------------------------------------------------------------
# 7. Stuck batch recovery
# ---------------------------------------------------------------------------

class StuckBatchRecoveryTests(TestCase):
    def setUp(self):
        from dicom_server.models import (
            RemoteDICOMNode, RetrievalBatch, RetrievalBatchPatient,
            RetrievalJob,
        )
        _ensure_site()
        self.Node = RemoteDICOMNode
        self.Batch = RetrievalBatch
        self.Row = RetrievalBatchPatient
        self.Job = RetrievalJob
        self.node = RemoteDICOMNode.objects.create(
            name='N', ae_title='AE', host='127.0.0.1', port=104)
        self.user = User.objects.create_user(username='batch', password='pw')

    def _batch(self, status, **kw):
        return self.Batch.objects.create(
            node=self.node, created_by=self.user, status=status, **kw)

    def test_querying_all_terminal_refires_finalizer(self):
        from dicom_server import tasks as dt
        b = self._batch(self.Batch.Status.QUERYING)
        p = Patient.objects.create(patient_id='Q1')
        self.Row.objects.create(
            batch=b, patient=p,
            query_status=self.Row.QueryStatus.DONE)
        with mock.patch.object(dt.task_finalize_batch_query, 'delay') as m:
            dt.task_recover_stuck_batches.apply()
        m.assert_called_once_with(None, b.pk)

    def test_retrieving_all_terminal_refires_finalizer(self):
        from dicom_server import tasks as dt
        b = self._batch(self.Batch.Status.RETRIEVING)
        p = Patient.objects.create(patient_id='R1')
        j = self.Job.objects.create(
            node=self.node, patient=p, batch=b,
            status=self.Job.Status.SUCCESS)
        with mock.patch.object(dt.task_finalize_retrieval_batch, 'delay') as m:
            dt.task_recover_stuck_batches.apply()
        m.assert_called_once_with(None, b.pk)

    def test_stale_querying_batch_marked_failed(self):
        from dicom_server import tasks as dt
        b = self._batch(self.Batch.Status.QUERYING)
        p = Patient.objects.create(patient_id='S1')
        self.Row.objects.create(
            batch=b, patient=p,
            query_status=self.Row.QueryStatus.QUERYING)
        # Age the batch beyond the stale threshold.
        self.Batch.objects.filter(pk=b.pk).update(
            created_at=timezone.now() - timedelta(minutes=120))
        dt.task_recover_stuck_batches.apply()
        b.refresh_from_db()
        self.assertEqual(b.status, self.Batch.Status.FAILED)
        self.assertIn('recovery_error', b.summary or {})


# ---------------------------------------------------------------------------
# 8. Progress page resume bar
# ---------------------------------------------------------------------------

class TaskProgressResumeBarTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('progadmin', 'p@x.com', 'pw')
        self.client.force_login(self.user)

    def test_failed_resumable_task_shows_resume_bar(self):
        tr = TaskRun.objects.create(
            task_id='prog-1', task_name='import_legacy_mapping',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            status=TaskRun.Status.FAILURE, user=self.user,
            task_args=['a', 'b'], task_kwargs={}, error_log='boom')
        r = self.client.get('/task-progress/prog-1/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('resumeBar', html)
        # Visible on load because the run is already failed.
        self.assertIn('display: block', html)
        # The resume form is present (action URL only renders when resumable).
        self.assertIn(f'/tasks/{tr.pk}/resume/', html)

    def test_non_resumable_failed_task_shows_details_only(self):
        tr = TaskRun.objects.create(
            task_id='prog-2', task_name='not_a_real_task',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            status=TaskRun.Status.FAILURE, user=self.user,
            task_args=['a'], task_kwargs={}, error_log='boom')
        r = self.client.get('/task-progress/prog-2/')
        html = r.content.decode()
        self.assertIn('resumeBar', html)
        # No resume form for a non-redispatchable task type.
        self.assertNotIn(f'/tasks/{tr.pk}/resume/', html)
        self.assertIn('View details', html)
