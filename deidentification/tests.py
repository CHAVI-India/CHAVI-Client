import tempfile
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

HF_RECOGNIZER = (
    "presidio_analyzer.predefined_recognizers.ner."
    "huggingface_ner_recognizer.HuggingFaceNerRecognizer"
)


class AnalyzerEngineBuildTests(SimpleTestCase):
    """Engine construction for the pixel-scrub analyzer."""

    def _recognizer_names(self, analyzer):
        return [r.name for r in analyzer.registry.recognizers]

    @override_settings(DEID_PIXEL_NER_BACKEND="none")
    def test_none_backend_has_no_hf_recognizer(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _build_analyzer_engine,
        )

        analyzer = _build_analyzer_engine()
        names = self._recognizer_names(analyzer)
        self.assertNotIn("HuggingFaceNerRecognizer", names)
        self.assertIn("LenientAadhaarRecognizer", names)
        self.assertIn("IndianMobileRecognizer", names)

    @override_settings(DEID_PIXEL_NER_BACKEND="hf")
    def test_hf_backend_registers_recognizer(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _build_analyzer_engine,
        )

        with patch(f"{HF_RECOGNIZER}.load"):
            analyzer = _build_analyzer_engine()
        self.assertIn("HuggingFaceNerRecognizer", self._recognizer_names(analyzer))

    @override_settings(DEID_PIXEL_NER_BACKEND="hf")
    def test_hf_load_failure_degrades_to_spacy(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _build_analyzer_engine,
        )

        with patch(f"{HF_RECOGNIZER}.load", side_effect=RuntimeError("boom")):
            analyzer = _build_analyzer_engine()
        self.assertNotIn(
            "HuggingFaceNerRecognizer", self._recognizer_names(analyzer)
        )

    @override_settings(DEID_PIXEL_NER_BACKEND="hf", DEID_LENIENT_INDIAN_IDS=False)
    def test_lenient_ids_can_be_disabled(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _build_analyzer_engine,
        )

        with patch(f"{HF_RECOGNIZER}.load"):
            analyzer = _build_analyzer_engine()
        names = self._recognizer_names(analyzer)
        self.assertNotIn("LenientAadhaarRecognizer", names)


class LabelMapTests(SimpleTestCase):
    def test_label_map_covers_model_labels(self):
        from django.conf import settings

        # Label set of DEID_HF_NER_MODEL — every predicted label must be
        # mapped or HuggingFaceNerRecognizer drops it silently.
        model_labels = {
            "VENDOR", "DATE", "HCW", "HOSPITAL", "ID", "PATIENT", "PHONE",
        }
        self.assertTrue(
            model_labels.issubset(set(settings.DEID_HF_LABEL_MAP.keys()))
        )


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


class CaseNormalizingOcrTests(SimpleTestCase):
    def _fake_ocr_result(self):
        return {
            "text": ["NAME", "RAMESH", "KUMAR", "", "  ", "45Y"],
            "left": [0, 0, 0, 0, 0, 0],
            "top": [0, 0, 0, 0, 0, 0],
            "width": [10, 10, 10, 10, 10, 10],
            "height": [10, 10, 10, 10, 10, 10],
            "conf": [90, 90, 90, -1, -1, 90],
        }

    @override_settings(DEID_PIXEL_NORMALIZE_CASE=True)
    def test_words_title_cased_and_length_preserved(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import _get_ocr

        with patch(
            "presidio_image_redactor.tesseract_ocr.pytesseract.image_to_data",
            return_value=self._fake_ocr_result(),
        ):
            ocr = _get_ocr()
            result = ocr.perform_ocr(None)

        self.assertEqual(
            result["text"], ["Name", "Ramesh", "Kumar", "", "  ", "45Y"]
        )

    @override_settings(DEID_PIXEL_NORMALIZE_CASE=False)
    def test_plain_tesseract_when_disabled(self):
        from presidio_image_redactor import TesseractOCR

        from deidentification.utils.burnt_in_pixel_scrubbing import _get_ocr

        ocr = _get_ocr()
        self.assertIs(type(ocr), TesseractOCR)


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
