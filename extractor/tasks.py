"""
Background tasks for the extractor app, running under Celery.
"""

from logging import getLogger

from celery import chain, shared_task
from django.contrib.contenttypes.models import ContentType
from django.db import close_old_connections

from extractor.models import EmbeddingConfiguration, BackgroundTask
from extractor.services.embeddings import EmbeddingUnavailableError

log = getLogger(__name__)


def _record_table_result(task, stats, position, total):
    """Append a per-table outcome to the shared BackgroundTask and advance progress."""
    close_old_connections()
    data = task.result_data or {}
    data.setdefault('results', []).append(stats)
    task.result_data = data
    task.save(update_fields=['result_data'])
    task.update_progress(
        f"[{position}/{total}] {stats['table']}", processed_items=position, total_items=total)


@shared_task(bind=True)
def compute_lookup_embeddings_task(self, task_id, config_id, refresh=False):
    """
    Dispatcher: turns a full index build into a sequential chain — one task
    per lookup table, then a finalize step — and returns immediately.
    Progress is tracked on the shared BackgroundTask row.

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

    content_types = list(ContentType.objects.filter(app_label='lookup').order_by('id'))
    if not content_types:
        task.mark_failed('No lookup tables found')
        return

    # Same build-then-swap generation for every link, fixed up front so a
    # re-run after a crash resumes the same version instead of bumping again.
    target_version = config.version + 1 if refresh else config.version
    total = len(content_types)

    task.result_data = {'results': [], 'target_version': target_version}
    task.save(update_fields=['result_data'])
    task.update_progress('Dispatching per-table tasks', processed_items=0, total_items=total)

    links = [
        compute_lookup_table_embeddings_task.si(
            task_id, config_id, ct.id, target_version, refresh, idx, total)
        for idx, ct in enumerate(content_types, 1)
    ]
    links.append(
        finalize_lookup_embeddings_task.si(task_id, config_id, target_version, refresh)
    )

    log.info(f"Dispatching {total} embedding tasks for config {config_id} ({config.model_name})")
    try:
        chain(*links).apply_async()
    except Exception as e:
        log.error(f"Failed to dispatch embedding chain: {e}", exc_info=True)
        task.mark_failed(f"Dispatch failed: {e}")


@shared_task(bind=True)
def compute_lookup_table_embeddings_task(self, task_id, config_id, content_type_id,
                                         target_version, refresh, position, total):
    """
    One chain link: embed a single lookup table under target_version.

    Always returns normally so the chain continues — a per-table failure is
    recorded in result_data['results']. A provider-level failure additionally
    sets result_data['fatal'] so later links short-circuit instead of each
    retrying a doomed model load.
    """
    from extractor.services.embedding_index import compute_lookup_table_embeddings

    close_old_connections()
    task = BackgroundTask.objects.get(task_id=task_id)
    content_type = ContentType.objects.get(id=content_type_id)
    table_name = content_type.model

    data = task.result_data or {}
    if data.get('fatal'):
        _record_table_result(
            task, {'table': table_name, 'count': 0, 'failed': 0, 'skipped': True},
            position, total)
        return

    try:
        config = EmbeddingConfiguration.objects.get(id=config_id)
        stats = compute_lookup_table_embeddings(
            config, content_type, target_version, refresh=refresh)
    except EmbeddingUnavailableError as e:
        data['fatal'] = str(e)
        task.result_data = data
        stats = {'table': table_name, 'count': 0, 'failed': 0, 'error': str(e)}
    except Exception as e:
        log.error(f"Embedding failed for {table_name}: {e}", exc_info=True)
        stats = {'table': table_name, 'count': 0, 'failed': 0, 'error': str(e)}

    _record_table_result(task, stats, position, total)


@shared_task(bind=True)
def finalize_lookup_embeddings_task(self, task_id, config_id, target_version, refresh):
    """
    Last chain link: aggregates per-table results, swaps the index generation
    on refresh, and closes out the BackgroundTask.
    """
    from extractor.services.embedding_index import finalize_lookup_index

    task = BackgroundTask.objects.get(task_id=task_id)
    config = EmbeddingConfiguration.objects.get(id=config_id)
    data = task.result_data or {}
    results = data.get('results', [])
    total_processed = sum(r.get('count', 0) for r in results)
    total_failed = sum(r.get('failed', 0) for r in results)
    errored = [r for r in results if r.get('error')]

    close_old_connections()

    if data.get('fatal'):
        task.mark_failed(f"Embedding provider unavailable: {data['fatal']}")
        return
    if refresh and total_processed == 0:
        task.mark_failed("Refresh produced zero embeddings; keeping the existing index active.")
        return
    if total_processed == 0 and (total_failed > 0 or errored):
        task.mark_failed(
            f"All embedding computations failed "
            f"({len(errored)} table errors, {total_failed} failed items)"
        )
        return

    try:
        if refresh:
            finalize_lookup_index(config, target_version)
    except Exception as e:
        log.error(f"Index swap failed: {e}", exc_info=True)
        close_old_connections()
        task.mark_failed(f"Index swap failed: {e}")
        return

    task.mark_complete({
        'success': True,
        'total_processed': total_processed,
        'total_failed': total_failed,
        'tables_processed': len(results),
        'index_version': target_version,
        'results': results,
    })


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
