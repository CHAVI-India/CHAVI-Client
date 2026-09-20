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
