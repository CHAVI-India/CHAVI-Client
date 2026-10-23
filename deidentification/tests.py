import tempfile
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings


class IndianIdRecognizerTests(SimpleTestCase):
    def _recognizer(self, name):
        from deidentification.utils.indian_id_recognizers import (
            build_indian_id_recognizers,
        )

        return {r.name: r for r in build_indian_id_recognizers()}[name]

    def test_lenient_aadhaar_matches_ocr_text(self):
        recognizer = self._recognizer("LenientAadhaarRecognizer")
        results = recognizer.analyze(
            "AADHAAR 1234 5678 9012", entities=["IN_AADHAAR"]
        )
        self.assertTrue(
            any(r.entity_type == "IN_AADHAAR" for r in results)
        )

    def test_indian_mobile_matches(self):
        recognizer = self._recognizer("IndianMobileRecognizer")
        results = recognizer.analyze(
            "PH +91 98765 43210", entities=["PHONE_NUMBER"]
        )
        self.assertTrue(
            any(r.entity_type == "PHONE_NUMBER" for r in results)
        )


class BurnedInAnnotationGateTests(SimpleTestCase):
    """(0028,0301) BurnedInAnnotation gate for pixel scrubbing."""

    def test_is_no_variants(self):
        from types import SimpleNamespace

        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _burnt_in_annotation_is_no,
        )

        self.assertTrue(_burnt_in_annotation_is_no(SimpleNamespace(BurnedInAnnotation='NO')))
        self.assertTrue(_burnt_in_annotation_is_no(SimpleNamespace(BurnedInAnnotation=' no ')))
        self.assertFalse(_burnt_in_annotation_is_no(SimpleNamespace(BurnedInAnnotation='YES')))
        self.assertFalse(_burnt_in_annotation_is_no(SimpleNamespace()))  # absent

    def test_bia_no_skips_engine_entirely(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        import deidentification.utils.burnt_in_pixel_scrubbing as m

        dcm = SimpleNamespace(BurnedInAnnotation='NO', PixelData=b'\x00')
        with patch.object(
            m, '_get_engine',
            side_effect=AssertionError('engine must not be built for BIA=NO'),
        ):
            out, bboxes = m.scrub_burnt_in_pixels(dcm, modality='CT')

        self.assertIs(out, dcm)
        self.assertIsNone(bboxes)

    def test_bia_yes_still_runs_pipeline(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        import deidentification.utils.burnt_in_pixel_scrubbing as m

        dcm = SimpleNamespace(BurnedInAnnotation='YES', PixelData=b'\x00')
        engine = MagicMock()
        with patch.object(m, '_get_engine', return_value=engine):
            with patch.object(
                m, '_ocr_burnt_in_text_bboxes',
                return_value=[{"left": 0, "top": 0, "width": 1, "height": 1}],
            ):
                m.scrub_burnt_in_pixels(dcm, modality='CT')
        engine._add_redact_box.assert_called_once()


class OcrWholeTextScrubTests(SimpleTestCase):
    """Pixel scrubbing redacts every word OCR finds (no NER)."""

    def _fake_dcm(self):
        from types import SimpleNamespace
        return SimpleNamespace(PixelData=b'\x00')

    def _fake_engine(self, words):
        """Mock engine wired the way _ocr_burnt_in_text_bboxes() uses it."""
        import numpy as np

        import deidentification.utils.burnt_in_pixel_scrubbing as m
        from presidio_image_redactor import BboxProcessor

        engine = MagicMock()
        engine._check_if_greyscale.return_value = True
        engine._rescale_dcm_pixel_array.return_value = np.zeros((8, 8), dtype=np.uint8)
        padded = object()
        engine._add_padding.return_value = padded
        analyzer = engine.image_analyzer_engine
        analyzer.image_preprocessor.preprocess_image.return_value = (padded, {})
        inner_ocr = MagicMock()
        inner_ocr.perform_ocr.return_value = {
            "text": words, "left": [25] * len(words), "top": [25] * len(words),
            "width": [10] * len(words), "height": [5] * len(words),
            "conf": [0.9] * len(words),
        }
        analyzer.ocr = inner_ocr
        engine.bbox_processor = BboxProcessor()
        return engine

    def test_no_text_returns_instance_unchanged(self):
        import deidentification.utils.burnt_in_pixel_scrubbing as m
        from unittest.mock import patch

        dcm = self._fake_dcm()
        engine = self._fake_engine(words=['', '   '])
        with patch.object(m, '_get_engine', return_value=engine):
            out, bboxes = m.scrub_burnt_in_pixels(dcm, modality='CT')

        self.assertIs(out, dcm)
        self.assertIsNone(bboxes)
        engine._add_redact_box.assert_not_called()

    def test_all_words_are_redacted(self):
        import deidentification.utils.burnt_in_pixel_scrubbing as m
        from unittest.mock import patch

        dcm = self._fake_dcm()
        engine = self._fake_engine(words=['RAMESH KUMAR', 'DOB 01/02/1980', 'CT HEAD'])
        with patch.object(m, '_get_engine', return_value=engine):
            out, bboxes = m.scrub_burnt_in_pixels(dcm, modality='CT')

        self.assertIsNot(out, dcm)
        # OCR ran exactly once and every detected word got a box.
        engine.image_analyzer_engine.ocr.perform_ocr.assert_called_once()
        self.assertEqual(len(bboxes), 3)
        # Padding removed: OCR saw the image padded by DEFAULT_PADDING_WIDTH.
        self.assertEqual(bboxes[0]["left"], 0)
        # Bboxes carry coordinates only — no OCR'd text (PHI) leaks out.
        for b in bboxes:
            self.assertEqual(set(b.keys()), {"left", "top", "width", "height"})
        engine._add_redact_box.assert_called_once()
        args = engine._add_redact_box.call_args.args
        self.assertIs(args[0], dcm)
        self.assertEqual(args[1], bboxes)

    def test_engine_builds_without_analyzer(self):
        """_get_engine must not build a Presidio AnalyzerEngine (no NER)."""
        import deidentification.utils.burnt_in_pixel_scrubbing as m
        from unittest.mock import MagicMock, patch

        fake_analyzer = MagicMock()
        with patch(
            "presidio_image_redactor.DicomImageRedactorEngine",
        ) as mock_redactor, patch(
            "presidio_image_redactor.ImageAnalyzerEngine",
        ) as mock_image_analyzer, patch.object(m, '_get_ocr') as mock_ocr:
            mock_ocr.return_value = fake_analyzer
            m._engine = None
            try:
                m._get_engine()
            finally:
                m._engine = None

        call_kwargs = mock_image_analyzer.call_args.kwargs
        self.assertIs(type(call_kwargs["analyzer_engine"]), m._UnusedAnalyzer)
        self.assertIs(call_kwargs["ocr"], fake_analyzer)
        mock_redactor.assert_called_once_with(
            image_analyzer_engine=mock_image_analyzer.return_value
        )


class DeidentificationChainTests(TestCase):
    """Serial per-study deidentification: dispatcher → per-study links → finalize."""

    def setUp(self):
        from django.contrib.auth.models import User
        from client_app.models import Patient, DICOMStudy, SiteConfiguration
        from deidentification.tasks import (
            deidentify_dicom_studies_bulk_task,
            deidentify_dicom_study_task,
            finalize_deidentification_batch_task,
        )

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._media = override_settings(MEDIA_ROOT=self._tmp.name)
        self._media.enable()
        self.addCleanup(self._media.disable)

        self.bulk_task = deidentify_dicom_studies_bulk_task
        self.link_task = deidentify_dicom_study_task
        self.fin_task = finalize_deidentification_batch_task

        # close_old_connections() would drop the TestCase's wrapped
        # transaction connection — patch it out.
        self._conn_patch = patch('deidentification.tasks.close_old_connections')
        self._conn_patch.start()
        self.addCleanup(self._conn_patch.stop)

        self.user = User.objects.create_user(username='deidtester', password='pw')
        # Patient.center defaults to the first SiteConfiguration row.
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P1')
        self.study_a = DICOMStudy.objects.create(
            patient=self.patient, study_instance_uid='UID-A')
        self.study_b = DICOMStudy.objects.create(
            patient=self.patient, study_instance_uid='UID-B')

    def _make_parent(self, run_id='run-1', results=None):
        from client_app.models import TaskRun
        return TaskRun.objects.create(
            task_id=run_id,
            task_name='deidentify_dicom_studies_bulk',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            status=TaskRun.Status.PROGRESS,
            user=self.user,
            task_args=[['UID-A', 'UID-B']],
            task_kwargs={'user_id': self.user.id},
            result_summary={'results': results or {}},
        )

    def test_dispatcher_creates_parent_and_dispatches_first_link(self):
        from client_app.models import TaskRun

        with patch.object(self.link_task, 'delay') as mock_delay:
            res = self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='parent-1',
            )

        self.assertEqual(res.result['status'], 'dispatched')
        mock_delay.assert_called_once_with('parent-1', 0, user_id=self.user.id)
        parent = TaskRun.objects.get(task_id='parent-1')
        self.assertEqual(parent.result_summary['results'], {})
        self.assertEqual(parent.task_type, TaskRun.TaskType.DEIDENTIFICATION)

    def test_dispatcher_resume_skips_recorded_indices(self):
        """A resumed dispatcher must not re-dispatch already-finished studies."""
        self._make_parent(run_id='parent-2', results={
            '0': {'index': 0, 'study_id': 'UID-A', 'processed': 5, 'failed': 0},
        })

        with patch.object(self.link_task, 'delay') as mock_delay:
            self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='parent-2',
            )

        mock_delay.assert_called_once_with('parent-2', 1, user_id=self.user.id)

    def test_dispatcher_finalizes_when_all_done(self):
        self._make_parent(run_id='parent-3', results={
            '0': {'index': 0, 'study_id': 'UID-A', 'processed': 5, 'failed': 0},
            '1': {'index': 1, 'study_id': 'UID-B', 'processed': 3, 'failed': 0},
        })

        with patch.object(self.fin_task, 'delay') as mock_delay:
            self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='parent-3',
            )

        mock_delay.assert_called_once_with('parent-3')

    @patch('deidentification.tasks.deidentify_study', return_value=(5, 0))
    def test_link_records_result_and_dispatches_next(self, mock_deid):
        from client_app.models import TaskRun
        from deidentification.models import DeidentificationJob

        self._make_parent(run_id='run-1')
        with patch.object(self.link_task, 'delay') as mock_delay:
            self.link_task.apply(
                args=['run-1', 0], kwargs={'user_id': self.user.id},
                task_id='link-0',
            )

        mock_deid.assert_called_once()
        mock_delay.assert_called_once_with('run-1', 1, user_id=self.user.id)

        parent = TaskRun.objects.get(task_id='run-1')
        entry = parent.result_summary['results']['0']
        self.assertEqual(entry['study_id'], 'UID-A')
        self.assertEqual(entry['processed'], 5)
        self.assertEqual(entry['failed'], 0)

        child = TaskRun.objects.get(task_id='link-0')
        self.assertEqual(child.status, TaskRun.Status.SUCCESS)
        job = DeidentificationJob.objects.get(study=self.study_a)
        self.assertEqual(job.task_run_id, child.pk)

    @patch('deidentification.tasks.deidentify_study', return_value=(5, 0))
    def test_last_link_dispatches_finalize(self, mock_deid):
        self._make_parent(run_id='run-last')
        with patch.object(self.fin_task, 'delay') as mock_delay:
            self.link_task.apply(
                args=['run-last', 1], kwargs={'user_id': self.user.id},
                task_id='link-last',
            )

        mock_delay.assert_called_once_with('run-last')

    @patch('deidentification.tasks.deidentify_study', side_effect=RuntimeError('boom'))
    def test_link_failure_recorded_and_chain_continues(self, mock_deid):
        from client_app.models import TaskRun

        self._make_parent(run_id='run-f')
        with patch.object(self.link_task, 'delay') as mock_delay:
            res = self.link_task.apply(
                args=['run-f', 0], kwargs={'user_id': self.user.id},
                task_id='link-f0',
            )

        # The link must not propagate — the chain advances to the next study.
        self.assertEqual(res.result['status'], 'failed')
        mock_delay.assert_called_once_with('run-f', 1, user_id=self.user.id)

        parent = TaskRun.objects.get(task_id='run-f')
        self.assertEqual(parent.result_summary['results']['0']['error'], 'boom')
        child = TaskRun.objects.get(task_id='link-f0')
        self.assertEqual(child.status, TaskRun.Status.FAILURE)

    @patch('deidentification.tasks.deidentify_study')
    def test_link_skips_already_recorded_index(self, mock_deid):
        """Redelivery after a result was recorded must be a no-op."""
        self._make_parent(run_id='run-skip', results={
            '0': {'index': 0, 'study_id': 'UID-A', 'processed': 5, 'failed': 0},
        })
        with patch.object(self.link_task, 'delay') as mock_delay:
            res = self.link_task.apply(
                args=['run-skip', 0], kwargs={'user_id': self.user.id},
                task_id='link-skip',
            )

        self.assertEqual(res.result['status'], 'skipped')
        mock_deid.assert_not_called()
        mock_delay.assert_not_called()

    def test_finalize_marks_parent_failed_with_summary(self):
        from client_app.models import TaskRun

        self._make_parent(run_id='run-fin', results={
            '0': {'index': 0, 'study_id': 'UID-A', 'processed': 5, 'failed': 0},
            '1': {'index': 1, 'study_id': 'UID-B', 'error': 'boom', 'processed': 0, 'failed': 0},
        })
        self.fin_task.apply(args=['run-fin'], task_id='fin-1')

        parent = TaskRun.objects.get(task_id='run-fin')
        self.assertEqual(parent.status, TaskRun.Status.FAILURE)
        self.assertIn('boom', parent.error_log)
        self.assertIn('UID-B', parent.error_log)

    def test_finalize_success(self):
        from client_app.models import TaskRun

        self._make_parent(run_id='run-ok', results={
            '0': {'index': 0, 'study_id': 'UID-A', 'processed': 5, 'failed': 0},
            '1': {'index': 1, 'study_id': 'UID-B', 'processed': 3, 'failed': 0},
        })
        self.fin_task.apply(args=['run-ok'], task_id='fin-2')

        parent = TaskRun.objects.get(task_id='run-ok')
        self.assertEqual(parent.status, TaskRun.Status.SUCCESS)
        self.assertIn('8 files', parent.result_summary['message'])


class DeidQueueRoutingTests(SimpleTestCase):
    """Deid chain tasks route to the dedicated 'deid' queue so a
    single-concurrency worker serializes deidentification across batches."""

    def _route_queue(self, task_name):
        from celery.app.routes import Router, prepare

        from chavi_client.celery import app

        router = Router(prepare(app.conf.task_routes), dict(app.amqp.queues), app=app)
        route = router.route({}, task_name)
        queue = route.get('queue')
        return getattr(queue, 'name', queue)

    def test_deid_chain_tasks_route_to_deid_queue(self):
        for name in (
            'deidentification.tasks.deidentify_dicom_studies_bulk_task',
            'deidentification.tasks.deidentify_dicom_study_task',
            'deidentification.tasks.finalize_deidentification_batch_task',
        ):
            self.assertEqual(self._route_queue(name), 'deid', name)

    def test_other_deid_tasks_stay_on_default_queue(self):
        for name in (
            'deidentification.tasks.build_dicom_download_zip_task',
            'deidentification.tasks.import_legacy_mapping_task',
        ):
            self.assertEqual(self._route_queue(name), 'default', name)
