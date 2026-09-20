"""
Background tasks for the extractor app, running under Celery.
"""

from logging import getLogger

from celery import shared_task

from extractor.models import EmbeddingConfiguration, BackgroundTask
from extractor.services.embedding_index import compute_lookup_embeddings
from extractor.services.embeddings import EmbeddingUnavailableError

log = getLogger(__name__)


@shared_task(bind=True)
def compute_lookup_embeddings_task(self, task_id, config_id, refresh=False):
    """
    Celery task: compute embeddings for all lookup tables.

    Args:
        task_id: ID of the BackgroundTask tracking this job (progress UI polls it)
        config_id: ID of the EmbeddingConfiguration to use
        refresh: If True, build a new index generation and swap it in only on success
    """
    try:
        task = BackgroundTask.objects.get(task_id=task_id)
    except BackgroundTask.DoesNotExist:
        log.error(f"BackgroundTask {task_id} not found")
        return

    task.mark_running()

    try:
        config = EmbeddingConfiguration.objects.get(id=config_id)
    except EmbeddingConfiguration.DoesNotExist:
        task.mark_failed('Configuration not found')
        return

    log.info(f"Starting embedding computation with config {config_id} ({config.model_name})")

    try:
        result = compute_lookup_embeddings(
            config,
            refresh=refresh,
            progress_callback=lambda msg: task.update_progress(msg),
        )
    except EmbeddingUnavailableError as e:
        task.mark_failed(f"Embedding provider unavailable: {e}")
        return
    except Exception as e:
        log.error(f"Embedding computation failed: {e}", exc_info=True)
        task.mark_failed(str(e))
        return

    task.mark_complete({'success': True, **result})


@shared_task(bind=True, max_retries=0)
def run_extraction_job(self, job_id):
    """
    Celery task: run one extraction job (one processed file x one model).
    Retries are disabled — a failed job stays failed and can be re-dispatched
    explicitly, so transient provider errors never double-charge silently.
    """
    from extractor.models import ExtractionJob
    from extractor.services.file_processor import FileProcessorService
    from extractor.services.instructor_extractor import InstructorExtractionService

    try:
        job = ExtractionJob.objects.select_related(
            'response_model__client', 'processed_file', 'extracted_by'
        ).get(id=job_id)
    except ExtractionJob.DoesNotExist:
        log.error(f"ExtractionJob {job_id} not found")
        return {'success': False, 'error': 'job not found'}

    if job.extraction_status not in ('pending', 'failed'):
        log.info(f"Job {job_id} already {job.extraction_status}; skipping")
        return {'success': True, 'reused': True, 'status': job.extraction_status}

    content = FileProcessorService.get_processed_content(job.processed_file)
    result = InstructorExtractionService.extract_data(job, content, job.extracted_by)
    return result


@shared_task(bind=True, max_retries=0)
def ocr_processed_text_task(self, task_id, processed_text_id, user_id=None):
    """
    Celery task: OCR a scanned PDF into a new versioned ProcessedText row.
    Progress is tracked on the BackgroundTask row created by the view.
    """
    from extractor.models import ProcessedText
    from extractor.services.file_processor import FileProcessorService
    from django.contrib.auth import get_user_model
    User = get_user_model()

    try:
        task = BackgroundTask.objects.get(task_id=task_id)
    except BackgroundTask.DoesNotExist:
        log.error(f"BackgroundTask {task_id} not found")
        return

    task.mark_running()
    task.update_progress('Rendering pages and running OCR...')

    try:
        pt = ProcessedText.objects.select_related('file_upload').get(id=processed_text_id)
        user = User.objects.filter(id=user_id).first() if user_id else None
        new_version = FileProcessorService.ocr_pdf(pt, user=user)
        task.mark_complete({
            'success': True,
            'processed_text_id': new_version.id,
            'version': new_version.version,
            'content_length': new_version.content_length,
        })
    except Exception as e:
        log.error(f"OCR task failed for processed_text {processed_text_id}: {e}", exc_info=True)
        task.mark_failed(str(e))
