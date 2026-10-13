"""
Background tasks for the extractor app, running under Celery.
"""

from logging import getLogger
from time import perf_counter

from celery import shared_task
from django.contrib.contenttypes.models import ContentType
from django.db import close_old_connections
from django.utils import timezone

from extractor.models import EmbeddingConfiguration, BackgroundTask, LookupEmbedding
from extractor.services.embeddings import EmbeddingUnavailableError

log = getLogger(__name__)


def _record_table_result(task, stats, position, total):
    """
    Record a per-table outcome on the shared BackgroundTask and advance
    progress. A redelivered task replaces its table's earlier result rather
    than appending a duplicate — the finalize gate reads one outcome per
    table.
    """
    close_old_connections()
    data = task.result_data or {}
    results = [r for r in data.get('results', []) if r.get('table') != stats.get('table')]
    results.append(stats)
    data['results'] = results
    task.result_data = data
    task.save(update_fields=['result_data'])
    task.update_progress(
        f"[{position}/{total}] {stats['table']}", processed_items=position, total_items=total)
    log.info(
        "Table %s done (%d/%d tables): %d rows, %d failed%s",
        stats.get('table'), position, total, stats.get('count', 0),
        stats.get('failed', 0),
        f", error: {stats['error']}" if stats.get('error') else "")


@shared_task(bind=True)
def compute_lookup_embeddings_task(self, task_id, config_id, refresh=False):
    """
    Dispatcher: starts the build by dispatching the first lookup table's first
    chunk task (extractor.tasks.embed_lookup_table_chunk), which self-perpetuates
    across chunks and tables and ends in finalize_lookup_embeddings_task.
    Returns immediately. Progress is tracked on the shared BackgroundTask row.

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

    content_types = list(ContentType.objects.filter(app_label='lookup')
                             .order_by('id'))
    if not content_types:
        task.mark_failed('No lookup tables found')
        return

    # Same build-then-swap generation for every chunk, fixed up front so a
    # re-run after a crash resumes the same version instead of bumping again.
    target_version = config.version + 1 if refresh else config.version
    total = len(content_types)

    task.result_data = {'results': [], 'target_version': target_version}
    task.save(update_fields=['result_data'])
    task.update_progress('Dispatching chunked embedding tasks',
                         processed_items=0, total_items=total)

    # Kick off the first table's first chunk; each chunk enqueues the next.
    first = content_types[0]
    log.info(f"Starting chunked embedding build for config {config_id} "
             f"({config.model_name}): {total} tables, target v{target_version}")
    try:
        embed_lookup_table_chunk.apply_async(args=[
            task_id, config_id, first.id, target_version, refresh,
            1, total])
    except Exception as e:
        log.error(f"Failed to dispatch first embedding chunk: {e}", exc_info=True)
        task.mark_failed(f"Dispatch failed: {e}")


def _advance_to_next_table_or_finalize(task_id, config_id, target_version,
                                       refresh, table_index, table_total):
    """
    After a table's last chunk: dispatch the first chunk task of the next lookup
    table, or the finalize task if this was the last one. table_index is the
    1-based position of the table that just finished; table_total is the number
    of tables captured when the build was dispatched (so the boundary matches
    the build's own table set, not whatever the live table count is now).
    """
    if table_index < table_total:
        tables = list(ContentType.objects.filter(app_label='lookup').order_by('id'))
        next_ct = tables[table_index]  # 0-based: current was tables[table_index-1]
        embed_lookup_table_chunk.apply_async(args=[
            task_id, config_id, next_ct.id, target_version, refresh,
            table_index + 1, table_total])
    else:
        finalize_lookup_embeddings_task.apply_async(args=[
            task_id, config_id, target_version, refresh])


@shared_task(bind=True)
def embed_lookup_table_chunk(self, task_id, config_id, content_type_id,
                             target_version, refresh, table_index, table_total):
    """
    One self-perpetuating unit of work: embed the next chunk (<= CHUNK_SIZE
    texts) of ONE lookup table, then enqueue the next chunk.

    Reads the DB for what still needs embedding, so a redelivered or duplicate
    chunk is a harmless no-op (unique constraint + ignore_conflicts). When the
    table is exhausted it advances to the next table; the last table triggers
    finalize_lookup_embeddings_task.

    Deliberately short (< 30 min) so each delivery is ACKed well before the
    broker's consumer_ack_timeout — the 406 delivery-ack timeout can't fire and
    duplicate execution can't corrupt data.
    """
    import extractor.services.embedding_index as ei

    close_old_connections()
    task = BackgroundTask.objects.get(task_id=task_id)
    data = task.result_data or {}

    # A prior chunk already recorded a provider failure — stop the chain.
    if data.get('fatal'):
        return

    content_type = ContentType.objects.get(id=content_type_id)
    table_name = content_type.model

    try:
        config = EmbeddingConfiguration.objects.get(id=config_id)
    except EmbeddingConfiguration.DoesNotExist:
        task.mark_failed('Configuration not found')
        return

    # Keys this table failed on earlier this run (excluded, not retried).
    exclude_keys = set(map(tuple, data.get('failed', {}).get(table_name, [])))

    # Read phase: find the next chunk. A failure here is a table-level error.
    try:
        chunk, remaining = ei.collect_pending_rows(
            config, content_type, target_version,
            exclude_keys=exclude_keys, chunk_size=ei.CHUNK_SIZE)
    except EmbeddingUnavailableError as e:
        data['fatal'] = str(e)
        task.result_data = data
        task.mark_failed(f"Embedding provider unavailable: {e}")
        return
    except Exception as e:
        log.error(f"Collect failed for {table_name}: {e}", exc_info=True)
        _record_table_result(
            task, {'table': table_name, 'count': 0, 'failed': 0,
                   'error': str(e)}, table_index, table_total)
        _advance_to_next_table_or_finalize(
            task_id, config_id, target_version, refresh,
            table_index, table_total)
        return

    # Table already exhausted (e.g. resume after a crash) -> record + advance.
    if not chunk:
        _record_table_result(
            task, {
                'table': table_name,
                'count': LookupEmbedding.objects.filter(
                    content_type=content_type, embedding_config=config,
                    index_version=target_version, is_current=True).count(),
                'failed': len(exclude_keys),
            }, table_index, table_total)
        _advance_to_next_table_or_finalize(
            task_id, config_id, target_version, refresh,
            table_index, table_total)
        return

    # Encode phase.
    close_old_connections()  # model load / encode idles the connection
    try:
        provider = ei.get_provider(config)
    except EmbeddingUnavailableError as e:
        data['fatal'] = str(e)
        task.result_data = data
        task.mark_failed(f"Embedding provider unavailable: {e}")
        return

    chunk_size = ei.CHUNK_SIZE
    # remaining includes this chunk, so numbering matches the serial driver's
    # logs; a redelivered chunk lands on the next pending rows and renumbers.
    chunk_number = (remaining - len(chunk)) // chunk_size + 1
    chunk_total = (remaining + chunk_size - 1) // chunk_size
    log.info(
        "Embedding %s v%s (table %d/%d) chunk %d/%d: %d rows",
        table_name, target_version, table_index, table_total,
        chunk_number, chunk_total, len(chunk))

    encode_started = perf_counter()
    count, failed, failed_keys = ei.embed_one_chunk(
        provider, config, content_type, target_version, chunk)
    log.info(
        "Saved %s v%s (table %d/%d) chunk %d/%d: %d rows, %d failed (encode %.2fs)",
        table_name, target_version, table_index, table_total,
        chunk_number, chunk_total, count, failed, perf_counter() - encode_started)

    if failed:
        # Record the failed keys so the next pass skips them (no infinite retry).
        failed_list = data.setdefault('failed', {}).setdefault(table_name, [])
        for key in failed_keys:
            if list(key) not in failed_list:
                failed_list.append(list(key))
        task.result_data = data
        task.save(update_fields=['result_data'])

    if remaining <= len(chunk):
        # This chunk was the last -> record the table and move on.
        _record_table_result(
            task, {
                'table': table_name,
                'count': LookupEmbedding.objects.filter(
                    content_type=content_type, embedding_config=config,
                    index_version=target_version, is_current=True).count(),
                'failed': len(data.get('failed', {}).get(table_name, [])),
            }, table_index, table_total)
        _advance_to_next_table_or_finalize(
            task_id, config_id, target_version, refresh,
            table_index, table_total)
    else:
        # More rows remain -> enqueue the next chunk of the same table.
        embed_lookup_table_chunk.apply_async(args=[
            task_id, config_id, content_type_id, target_version, refresh,
            table_index, table_total])
    # A small return value keeps the worker's "succeeded in Xs: <result>"
    # line self-documenting (and gives the result backend something).
    return {'table': table_name, 'version': target_version,
            'chunk': chunk_number, 'chunk_total': chunk_total,
            'rows': count, 'failed': failed, 'remaining': remaining - len(chunk)}


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
    log.info(
        "Embedding build for config %s finished: %d rows, %d failed, "
        "%d tables (target v%s)",
        config_id, total_processed, total_failed, len(results), target_version)

    close_old_connections()

    if data.get('fatal'):
        task.mark_failed(f"Embedding provider unavailable: {data['fatal']}")
        return
    if refresh:
        # A resumed run can legitimately add zero rows — completeness is
        # clean per-table results plus committed target-version rows, not
        # this run's write count.
        built = LookupEmbedding.objects.filter(
            embedding_config=config, index_version=target_version,
            is_current=True).exists()
        if total_failed or errored or not built:
            task.mark_failed(
                "Refresh incomplete; keeping the existing index active. "
                "Re-run to resume the partial build.")
            return
    elif total_processed == 0 and (total_failed > 0 or errored):
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
def advance_extraction_job(self, job_id, approved_status=None):
    """
    Celery task: advance one extraction job by a single stage — the job
    status says which stage runs next:

      pending              -> stage_prepare (builds the mining prompt,
                              parks at awaiting_mining)
      awaiting_mining      -> stage_mine (mining LLM call, builds the
                              extraction prompt, parks at awaiting_extraction)
      awaiting_extraction  -> stage_extract (extraction LLM call, saves
                              results, completes)
      failed               -> re-run stage_prepare (explicit re-dispatch)

    `approved_status` records the awaiting_* status an approval click
    claimed before dispatching — the view flips the job to processing up
    front, so the stage to run comes from that argument, not the row.
    Direct dispatches (no approved_status) claim the stage atomically
    instead. Anything else (processing, completed, skipped) is a no-op so
    double dispatches are safe. Retries are disabled — a failed job stays
    failed and can be re-dispatched explicitly, so transient provider
    errors never double-charge silently.
    """
    from extractor.models import ExtractionJob, ExtractionStatusChoices
    from extractor.services.file_processor import FileProcessorService
    from extractor.services.instructor_extractor import InstructorExtractionService

    try:
        job = ExtractionJob.objects.select_related(
            'response_model__client', 'processed_file', 'extracted_by'
        ).get(id=job_id)
    except ExtractionJob.DoesNotExist:
        log.error(f"ExtractionJob {job_id} not found")
        return {'success': False, 'error': 'job not found'}

    stage_by_status = {
        ExtractionStatusChoices.PENDING: InstructorExtractionService.stage_prepare,
        ExtractionStatusChoices.AWAITING_MINING: InstructorExtractionService.stage_mine,
        ExtractionStatusChoices.AWAITING_EXTRACTION: InstructorExtractionService.stage_extract,
        # An explicit re-dispatch after failure restarts the pipeline
        ExtractionStatusChoices.FAILED: InstructorExtractionService.stage_prepare,
    }
    if approved_status is not None:
        # The approval view already claimed the job — run the stage that
        # was awaiting; bail if the job was reset or moved on meanwhile.
        if job.extraction_status != ExtractionStatusChoices.PROCESSING:
            log.info(
                f"Job {job_id} is {job.extraction_status}, not processing; "
                f"skipping approved {approved_status} stage")
            return {'success': True, 'reused': True,
                    'status': job.extraction_status}
        stage = stage_by_status.get(approved_status)
    else:
        stage = stage_by_status.get(job.extraction_status)
        if stage is None:
            log.info(f"Job {job_id} already {job.extraction_status}; skipping")
            return {'success': True, 'reused': True, 'status': job.extraction_status}
        # Claim the stage so a duplicate queued task no-ops
        if not ExtractionJob.objects.filter(
                id=job_id,
                extraction_status=job.extraction_status).update(
                extraction_status=ExtractionStatusChoices.PROCESSING):
            log.info(f"Job {job_id} stage already claimed; skipping")
            return {'success': True, 'reused': True,
                    'status': ExtractionStatusChoices.PROCESSING}
        job.extraction_status = ExtractionStatusChoices.PROCESSING

    from django.conf import settings
    if (getattr(settings, 'EXTRACTOR_DEID_ENABLED', True)
            and job.processed_file_id is not None):
        pf = job.processed_file
        if not pf.deidentified:
            msg = (
                f"Job {job_id} references non-deidentified text "
                f"(ProcessedText {pf.id}) — blocked"
            )
            log.error(msg)
            job.extraction_status = ExtractionStatusChoices.FAILED
            job.extraction_end_datetime = timezone.now()
            job.extraction_error = msg
            job.save()
            return {'success': False, 'error': msg}
        if (getattr(settings, 'EXTRACTOR_DEID_REQUIRE_REVIEW', True)
                and not pf.deid_reviewed):
            msg = (
                f"Job {job_id} references unreviewed deidentified text "
                f"(ProcessedText {pf.id}) — blocked"
            )
            log.error(msg)
            job.extraction_status = ExtractionStatusChoices.FAILED
            job.extraction_end_datetime = timezone.now()
            job.extraction_error = msg
            job.save()
            return {'success': False, 'error': msg}

    content = FileProcessorService.get_processed_content(job.processed_file)
    try:
        result = stage(job, content)
    except Exception as e:
        log.error(f"Extraction job {job_id} failed: {e}", exc_info=True)
        job.extraction_status = ExtractionStatusChoices.FAILED
        job.extraction_end_datetime = timezone.now()
        job.extraction_error = str(e)
        job.save()
        return {'success': False, 'error': str(e)}
    return result or {'success': True, 'status': job.extraction_status}


@shared_task(bind=True, max_retries=0)
def ocr_processed_text_task(self, task_id, processed_text_id, user_id=None):
    """
    Celery task: OCR a scanned PDF into a new versioned ProcessedText row.
    Progress is tracked on the BackgroundTask row created by the view.
    """
    from django.conf import settings
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
        result = {
            'success': True,
            'processed_text_id': new_version.id,
            'version': new_version.version,
            'content_length': new_version.content_length,
        }
        if getattr(settings, 'EXTRACTOR_DEID_AUTO_RUN', True) and new_version:
            deid_task = BackgroundTask.objects.create(
                task_id=f"deid-{new_version.id}-{int(timezone.now().timestamp())}",
                task_name=f"Deidentify processed file {new_version.id}",
                status='pending',
            )
            deidentify_processed_text_task.delay(
                deid_task.task_id, new_version.id,
                user_id=user.id if user else None)
            result['deid_task_id'] = deid_task.task_id
        task.mark_complete(result)
    except Exception as e:
        log.error(f"OCR task failed for processed_text {processed_text_id}: {e}", exc_info=True)
        task.mark_failed(str(e))


@shared_task(bind=True, max_retries=0)
def deidentify_processed_text_task(self, task_id, processed_text_id, user_id=None):
    """
    Celery task: deidentify a ProcessedText version into a new versioned
    row. Progress is tracked on the BackgroundTask row created by the view
    or the caller that auto-dispatched it.
    """
    from django.conf import settings
    from extractor.models import ProcessedText
    from extractor.services.text_deidentification import TextDeidentificationService
    from django.contrib.auth import get_user_model
    User = get_user_model()

    try:
        task = BackgroundTask.objects.get(task_id=task_id)
    except BackgroundTask.DoesNotExist:
        log.error(f"BackgroundTask {task_id} not found")
        return

    task.mark_running()
    task.update_progress('Running deidentification...')

    try:
        pt = ProcessedText.objects.select_related(
            'file_upload__patient_id').get(id=processed_text_id)
        user = User.objects.filter(id=user_id).first() if user_id else None
        new_version = TextDeidentificationService.deidentify(pt, user=user)
        if new_version is None:
            task.mark_complete({'success': True, 'skipped': 'already deidentified'})
            return
        task.mark_complete({
            'success': True,
            'processed_text_id': new_version.id,
            'version': new_version.version,
            'content_length': new_version.content_length,
            'engine': new_version.deid_engine,
            'entities': new_version.deid_entities,
        })
    except Exception as e:
        log.error(
            f"Deid task failed for processed_text {processed_text_id}: {e}",
            exc_info=True)
        task.mark_failed(str(e))
