"""
Tests for extractor TaskRun registration: extractor jobs must appear on the
cross-app "Task Runs" dashboard (client_app.TaskRun / taskrun_list.html) and
must support the same resume flow as the other task types (TASK_REGISTRY /
task_run_can_resume / _redispatch_task_run).

Covers:
  * ocr / deid / csv-row tasks register a TaskRun row (success + failure)
  * advance_extraction_job consolidates all stage dispatches on one row and
    stores resume-stable args (no transient approved_status)
  * the embedding chain (dispatcher -> chunk -> finalize) shares one row via
    tracker_id, and failures mark that row failed
  * resume: task_run_can_resume + _redispatch_task_run use the stored args
  * TaskRunListView hides extractor rows from users without the matching
    extractor permission
  * TASK_REGISTRY / RESUME_NOTES coverage for every extractor task
"""
from unittest import mock
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings

from client_app.models import Notification, TaskRun
from client_app import views as client_views
from extractor.models import (
    BackgroundTask,
    ClientConfiguration,
    EmbeddingConfiguration,
    ExtractionJob,
    FileUpload,
    ProcessedText,
    ResponseModel,
)
from extractor.services.instructor_extractor import InstructorExtractionService


def _make_user(username):
    return User.objects.create(username=username)


class OcrTaskRunTests(TestCase):
    """ocr_processed_text_task registers a TaskRun row for the dashboard."""

    def setUp(self):
        self.user = _make_user('ocruser')
        self.upload = FileUpload.objects.create(file='scan.pdf')
        self.pt = ProcessedText.objects.create(
            file_upload=self.upload, content_length=5)
        self.bg = BackgroundTask.objects.create(
            task_id='ocr-1-1', task_name='OCR for processed file 1',
            status='pending')

    def _run_ocr(self):
        from extractor.tasks import ocr_processed_text_task
        new_version = ProcessedText.objects.create(
            file_upload=self.upload, version=2, ocr_applied=True,
            content_length=9)
        with patch('extractor.services.file_processor.'
                   'FileProcessorService.ocr_pdf',
                   return_value=new_version):
            ocr_processed_text_task(self.bg.task_id, self.pt.id,
                                    user_id=self.user.id)

    def test_registers_success_row_with_resume_args(self):
        with override_settings(EXTRACTOR_DEID_AUTO_RUN=False):
            self._run_ocr()
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.task_name, 'ocr_processed_text_task')
        self.assertEqual(tr.task_type, TaskRun.TaskType.EXTRACTOR)
        self.assertEqual(tr.status, TaskRun.Status.SUCCESS)
        self.assertEqual(tr.user, self.user)
        # Stable resume args (BackgroundTask id + processed text id)
        self.assertEqual(tr.task_args, [self.bg.task_id, self.pt.id])
        self.assertEqual(tr.task_kwargs.get('user_id'), self.user.id)
        # Attributed user gets the completion notification
        self.assertEqual(
            Notification.objects.filter(task_run=tr,
                                       notification_type='TASK_COMPLETED'
                                       ).count(), 1)

    def test_failure_marks_row_failed_and_notifies(self):
        with override_settings(EXTRACTOR_DEID_AUTO_RUN=False), patch(
                'extractor.services.file_processor.'
                'FileProcessorService.ocr_pdf',
                side_effect=RuntimeError('ocr backend down')):
            from extractor.tasks import ocr_processed_text_task
            ocr_processed_text_task(self.bg.task_id, self.pt.id,
                                    user_id=self.user.id)
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.status, TaskRun.Status.FAILURE)
        self.assertIn('ocr backend down', tr.error_log)
        self.assertEqual(
            Notification.objects.filter(task_run=tr,
                                       notification_type='TASK_FAILED'
                                       ).count(), 1)

    def test_failed_row_is_resumable_via_registry(self):
        with override_settings(EXTRACTOR_DEID_AUTO_RUN=False), patch(
                'extractor.services.file_processor.'
                'FileProcessorService.ocr_pdf',
                side_effect=RuntimeError('ocr backend down')):
            from extractor.tasks import ocr_processed_text_task
            ocr_processed_text_task(self.bg.task_id, self.pt.id,
                                    user_id=self.user.id)
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertTrue(client_views.task_run_can_resume(tr))
        with mock.patch.object(client_views.TASK_REGISTRY[
                'ocr_processed_text_task'], 'delay') as delay:
            result = client_views._redispatch_task_run(tr)
        self.assertIsNotNone(result)
        delay.assert_called_once_with(
            self.bg.task_id, self.pt.id, user_id=self.user.id)


class DeidTaskRunTests(TestCase):
    """deidentify_processed_text_task registers a TaskRun row."""

    def setUp(self):
        self.user = _make_user('deiduser')
        self.upload = FileUpload.objects.create(file='report.pdf')
        self.pt = ProcessedText.objects.create(
            file_upload=self.upload, content_length=5)
        self.bg = BackgroundTask.objects.create(
            task_id='deid-1-1', task_name='Deidentify processed file 1',
            status='pending')

    def _run_deid(self, **overrides):
        from extractor.tasks import deidentify_processed_text_task
        new_version = ProcessedText.objects.create(
            file_upload=self.upload, version=2, deidentified=True,
            content_length=4)
        overrides.setdefault('return_value', new_version)
        with patch('extractor.services.text_deidentification.'
                   'TextDeidentificationService.deidentify',
                   **overrides):
            deidentify_processed_text_task(
                self.bg.task_id, self.pt.id, user_id=self.user.id,
                backend='presidio')

    def test_registers_success_row(self):
        self._run_deid()
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.task_name, 'deidentify_processed_text_task')
        self.assertEqual(tr.status, TaskRun.Status.SUCCESS)
        self.assertEqual(tr.user, self.user)
        self.assertEqual(tr.task_args, [self.bg.task_id, self.pt.id])
        self.assertEqual(tr.task_kwargs.get('backend'), 'presidio')
        self.assertTrue(client_views.task_run_can_resume(tr))

    def test_already_deidentified_completes_as_skipped(self):
        self.pt.deidentified = True
        self.pt.save()
        self._run_deid(return_value=None)
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.status, TaskRun.Status.SUCCESS)
        self.assertEqual(tr.result_summary.get('skipped'),
                         'already deidentified')

    def test_failure_marks_row_failed(self):
        self._run_deid(side_effect=RuntimeError('deid boom'))
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.status, TaskRun.Status.FAILURE)
        self.assertIn('deid boom', tr.error_log)


class CsvRowTaskRunTests(TestCase):
    """process_csv_row_task registers a TaskRun row per row document."""

    def setUp(self):
        self.user = _make_user('csvrowuser')
        self.upload = FileUpload.objects.create(original_filename='rows.csv')
        self.pt = ProcessedText.objects.create(
            file_upload=self.upload, processed_file_path='uploads/r.md',
            source_sheet='row-0000', content_length=10)
        self.bg = BackgroundTask.objects.create(
            task_id=f'csvrow-{self.pt.id}-1',
            task_name=f'CSV row {self.pt.id}', status='pending')

    def test_registers_success_row(self):
        from extractor.tasks import process_csv_row_task
        fake_out = ProcessedText.objects.create(
            file_upload=self.upload, processed_file_path='out.md',
            deidentified=True, source_sheet='row-0000')
        with patch('extractor.services.text_deidentification.'
                   'TextDeidentificationService.deidentify',
                   return_value=fake_out):
            process_csv_row_task(self.bg.task_id, self.pt.id,
                                 user_id=self.user.id)
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.task_name, 'process_csv_row_task')
        self.assertEqual(tr.status, TaskRun.Status.SUCCESS)
        self.assertEqual(tr.user, self.user)
        self.assertEqual(tr.task_args, [self.bg.task_id, self.pt.id])
        self.assertEqual(tr.result_summary.get('stage'), 'deid_only')

    def test_failure_marks_row_failed(self):
        from extractor.tasks import process_csv_row_task
        with patch('extractor.services.text_deidentification.'
                   'TextDeidentificationService.deidentify',
                   side_effect=RuntimeError('row deid failed')):
            process_csv_row_task(self.bg.task_id, self.pt.id,
                                 user_id=self.user.id)
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.status, TaskRun.Status.FAILURE)
        self.assertIn('row deid failed', tr.error_log)


class ExtractionJobTaskRunTests(TestCase):
    """advance_extraction_job: one TaskRun row per job across all stages,
    resume-stable args, failures and the stuck-processing no-op."""

    def setUp(self):
        from extractor.tests import make_response_model
        self.rm = make_response_model()
        self.user = _make_user('extractuser')
        upload = FileUpload.objects.create(file='scan.pdf')
        self.processed = ProcessedText.objects.create(
            file_upload=upload, content_length=5,
            deidentified=True, deid_reviewed=True)
        self.job = ExtractionJob.objects.create(
            response_model=self.rm, processed_file=self.processed,
            extracted_by=self.user)

    def _fake_prepare(self, job, content):
        job.extraction_status = 'awaiting_mining'
        job.save()
        return None

    def test_single_row_across_stage_dispatches(self):
        from extractor.tasks import advance_extraction_job
        with patch.object(InstructorExtractionService, 'stage_prepare',
                          side_effect=self._fake_prepare):
            advance_extraction_job(self.job.id)
        tr = TaskRun.objects.get(tracker_id=f'extraction-{self.job.id}')
        self.assertEqual(tr.task_name, 'advance_extraction_job')
        self.assertEqual(tr.task_type, TaskRun.TaskType.EXTRACTOR)
        self.assertEqual(tr.status, TaskRun.Status.SUCCESS)
        self.assertEqual(tr.user, self.user)
        # Resume-stable args: job id only, no transient approved_status
        self.assertEqual(tr.task_args, [self.job.id])
        self.assertNotIn('approved_status', tr.task_kwargs or {})
        self.assertEqual(tr.task_kwargs.get('auto_extract'), False)

        # A second (approval-driven) dispatch reuses the same row. The
        # approval view flips the job to processing before dispatching.
        self.job.extraction_status = 'processing'
        self.job.save()
        fake_mine = mock.Mock(side_effect=lambda job, content: None)
        with patch.object(InstructorExtractionService, 'stage_mine',
                          fake_mine):
            advance_extraction_job(self.job.id,
                                   approved_status='awaiting_mining')
        fake_mine.assert_called_once()
        self.assertEqual(
            TaskRun.objects.filter(
                tracker_id=f'extraction-{self.job.id}').count(), 1)
        tr.refresh_from_db()
        self.assertEqual(tr.status, TaskRun.Status.SUCCESS)

    def test_stage_failure_fails_row_and_resume_uses_stored_args(self):
        from extractor.tasks import advance_extraction_job
        with patch.object(InstructorExtractionService, 'stage_prepare',
                          side_effect=RuntimeError('mining provider down')):
            advance_extraction_job(self.job.id)
        tr = TaskRun.objects.get(tracker_id=f'extraction-{self.job.id}')
        self.assertEqual(tr.status, TaskRun.Status.FAILURE)
        self.assertIn('mining provider down', tr.error_log)
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status, 'failed')
        self.assertTrue(client_views.task_run_can_resume(tr))
        with mock.patch.object(client_views.TASK_REGISTRY[
                'advance_extraction_job'], 'delay') as delay:
            result = client_views._redispatch_task_run(tr)
        self.assertIsNotNone(result)
        # Re-dispatch is the direct-claim form (no approved_status), so a
        # failed job restarts at stage_prepare.
        delay.assert_called_once_with(self.job.id, auto_extract=False)

    def test_stuck_processing_redispatch_is_flagged_not_succeeded(self):
        """A worker death mid-stage leaves the job PROCESSING; a resume
        no-ops in the stage engine and must not be recorded as a success."""
        from extractor.tasks import advance_extraction_job
        self.job.extraction_status = 'processing'
        self.job.save()
        with patch.object(InstructorExtractionService, 'stage_prepare') as sp:
            result = advance_extraction_job(self.job.id)
        self.assertTrue(result.get('reused'))
        sp.assert_not_called()
        tr = TaskRun.objects.get(tracker_id=f'extraction-{self.job.id}')
        self.assertEqual(tr.status, TaskRun.Status.FAILURE)
        self.assertIn('mid-stage', tr.error_log)


class EmbeddingChainTaskRunTests(TestCase):
    """The embedding build chain (dispatcher -> chunk -> finalize) must
    consolidate on ONE TaskRun row via tracker_id."""

    def setUp(self):
        from lookup.models import LookupLaterality
        self.model = LookupLaterality
        self.config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', model_provider='sentence-transformers',
            embedding_dimension=384, is_active=True)
        self.user = _make_user('embeduser')
        self.bg = BackgroundTask.objects.create(
            task_id='emb-task-1', task_name='Compute Lookup Embeddings',
            status='pending', result_data={'results': []})
        LookupLaterality.objects.all().delete()
        for code, label in (('C1', 'zz-lab-a'), ('C2', 'zz-lab-b')):
            LookupLaterality.objects.create(code=code, label=label)

        for target in (
                'extractor.services.embedding_index.close_old_connections',
                'extractor.tasks.close_old_connections'):
            patcher = patch(target, lambda: None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_chain_consolidates_on_one_row(self):
        from extractor.tasks import (
            compute_lookup_embeddings_task,
            embed_lookup_table_chunk,
            finalize_lookup_embeddings_task,
        )
        # Dispatcher creates the row
        with patch('extractor.services.embedding_index.'
                   'collect_pending_rows', return_value=([], 0)), \
             patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task,
                          'apply_async') as fin:
            compute_lookup_embeddings_task.run(
                self.bg.task_id, self.config.id, refresh=False,
                user_id=self.user.id)
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.task_name, 'compute_lookup_embeddings_task')
        self.assertEqual(tr.task_type, TaskRun.TaskType.LOOKUP_EMBEDDING)
        self.assertEqual(tr.user, self.user)
        self.assertEqual(tr.task_args, [self.bg.task_id, self.config.id])
        self.assertEqual(tr.task_kwargs.get('refresh'), False)
        self.assertEqual(tr.task_kwargs.get('user_id'), self.user.id)
        self.assertIn(tr.status,
                      (TaskRun.Status.STARTED, TaskRun.Status.PROGRESS))

        # A chunk delivery updates the SAME row (progress mirrored from the
        # BackgroundTask; the table is exhausted so it finalizes)
        with patch('extractor.services.embedding_index.'
                   'collect_pending_rows', return_value=([], 0)), \
             patch.object(finalize_lookup_embeddings_task,
                          'apply_async') as fin:
            embed_lookup_table_chunk.run(
                self.bg.task_id, self.config.id, 1, 1, False, 1, 1)
        tr.refresh_from_db()
        self.assertEqual(
            TaskRun.objects.filter(tracker_id=self.bg.task_id).count(), 1)
        self.assertEqual(tr.status, TaskRun.Status.PROGRESS)
        self.assertEqual(tr.progress_current, 1)
        self.assertEqual(tr.progress_total, 1)

        # Finalize completes the same row
        with patch('extractor.services.embedding_index.'
                   'finalize_lookup_index'):
            finalize_lookup_embeddings_task.run(
                self.bg.task_id, self.config.id, 1, False)
        tr.refresh_from_db()
        self.assertEqual(tr.status, TaskRun.Status.SUCCESS)
        self.assertEqual(
            TaskRun.objects.filter(tracker_id=self.bg.task_id).count(), 1)
        self.assertIsNotNone(tr.result_summary)

    def test_chunk_failure_fails_shared_row(self):
        from extractor.tasks import (
            compute_lookup_embeddings_task,
            embed_lookup_table_chunk,
            finalize_lookup_embeddings_task,
        )
        with patch.object(embed_lookup_table_chunk, 'apply_async'), \
             patch.object(finalize_lookup_embeddings_task, 'apply_async'):
            compute_lookup_embeddings_task.run(
                self.bg.task_id, self.config.id, refresh=False,
                user_id=self.user.id)
        # Provider goes fatal on the chunk
        from extractor.services.embeddings import EmbeddingUnavailableError
        with patch('extractor.services.embedding_index.'
                   'collect_pending_rows',
                   side_effect=EmbeddingUnavailableError('provider dead')):
            embed_lookup_table_chunk.run(
                self.bg.task_id, self.config.id, 1, 1, False, 1, 1)
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertEqual(tr.status, TaskRun.Status.FAILURE)
        self.assertIn('provider dead', tr.error_log)
        self.assertEqual(
            TaskRun.objects.filter(tracker_id=self.bg.task_id).count(), 1)

    def test_failed_build_row_resumes_via_dispatcher(self):
        from extractor.tasks import compute_lookup_embeddings_task
        self._fail_a_build()
        tr = TaskRun.objects.get(tracker_id=self.bg.task_id)
        self.assertTrue(client_views.task_run_can_resume(tr))
        with mock.patch.object(client_views.TASK_REGISTRY[
                'compute_lookup_embeddings_task'], 'delay') as delay:
            result = client_views._redispatch_task_run(tr)
        self.assertIsNotNone(result)
        delay.assert_called_once_with(
            self.bg.task_id, self.config.id, refresh=False,
            user_id=self.user.id)

    def _fail_a_build(self):
        from extractor.tasks import (
            compute_lookup_embeddings_task,
            embed_lookup_table_chunk,
            finalize_lookup_embeddings_task,
        )
        with patch.object(embed_lookup_table_chunk, 'apply_async'), \
             patch.object(finalize_lookup_embeddings_task, 'apply_async'):
            compute_lookup_embeddings_task.run(
                self.bg.task_id, self.config.id, refresh=False,
                user_id=self.user.id)
        # Simulate the chain failing via finalize with a fatal flag
        self.bg.result_data = {'fatal': 'provider dead', 'results': []}
        self.bg.save()
        with patch('extractor.services.embedding_index.'
                   'finalize_lookup_index'):
            finalize_lookup_embeddings_task.run(
                self.bg.task_id, self.config.id, 1, False)


class ExtractorTaskRunVisibilityTests(TestCase):
    """TaskRun list/detail: extractor rows are visible only with the
    matching extractor permission."""

    EXTRACTOR_NAMES = (
        'compute_lookup_embeddings_task',
        'embed_lookup_table_chunk',
        'finalize_lookup_embeddings_task',
        'advance_extraction_job',
        'ocr_processed_text_task',
        'deidentify_processed_text_task',
        'process_csv_row_task',
    )

    def test_all_extractor_tasks_registered_with_notes(self):
        for name in self.EXTRACTOR_NAMES:
            self.assertIn(name, client_views.TASK_REGISTRY,
                          f'{name} missing from TASK_REGISTRY')
            self.assertIn(name, client_views.RESUME_NOTES,
                          f'{name} missing from RESUME_NOTES')

    def _grant(self, user, *codenames):
        from django.apps import apps
        perms = Permission.objects.filter(
            codename__in=codenames).select_related('content_type')
        for perm in perms:
            if perm.content_type.app_label in ('client_app', 'extractor'):
                user.user_permissions.add(perm)

    def test_list_view_permission_filtering(self):
        user = _make_user('viewer')
        run = TaskRun.objects.create(
            task_id='celery-x', task_name='ocr_processed_text_task',
            task_type=TaskRun.TaskType.EXTRACTOR, user=user)

        self.client.force_login(user)
        # No permissions at all -> 403 (view_taskrun required)
        self.assertEqual(
            self.client.get('/tasks/').status_code, 403)

        self._grant(user, 'view_taskrun')
        user = User.objects.get(pk=user.pk)  # permission cache
        self.assertNotContains(self.client.get('/tasks/'), 'ocr_processed')

        self._grant(user, 'view_processedtext')
        user = User.objects.get(pk=user.pk)
        self.assertContains(self.client.get('/tasks/'), 'ocr_processed')

    def test_detail_view_permission_filtering(self):
        user = _make_user('detailviewer')
        run = TaskRun.objects.create(
            task_id='celery-y', task_name='compute_lookup_embeddings_task',
            task_type=TaskRun.TaskType.LOOKUP_EMBEDDING, user=user)

        self.client.force_login(user)
        self._grant(user, 'view_taskrun', 'view_embeddingconfiguration')
        self.assertEqual(
            self.client.get(f'/tasks/{run.pk}/').status_code, 200)
