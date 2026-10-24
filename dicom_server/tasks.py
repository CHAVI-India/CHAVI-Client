"""Celery tasks for DICOM query/retrieve operations."""
import logging
import time
from datetime import datetime

from celery import chord, group, shared_task
from django.utils import timezone

from client_app.models import Patient, DICOMStudy, TaskRun, Notification
from client_app.tasks import (
    _create_task_run, _update_task_run, _complete_task_run, _fail_task_run,
)
from dicom_server.models import (
    AutoRetrievalState, BulkRetrievalSchedule, RemoteDICOMNode,
    RetrievalBatch, RetrievalBatchPatient, RetrievalJob, RetrievalJobSeries,
    RetrievalJobStudy,
)
from dicom_server.services import qr_client

logger = logging.getLogger(__name__)


def _finish_task_run_quiet(task_run, result, error=None):
    """Close out a TaskRun without creating a Notification.

    Bulk flows dispatch one Celery task per patient — notifying on every
    sub-task would spam the user; the batch finalizer notifies once instead.
    """
    if not task_run:
        return
    if error is not None:
        task_run.status = TaskRun.Status.FAILURE
        task_run.error_log = str(error)
    else:
        task_run.status = TaskRun.Status.SUCCESS
        task_run.progress_current = task_run.progress_total
    task_run.result_summary = result
    task_run.completed_at = timezone.now()
    task_run.save(update_fields=[
        'status', 'result_summary', 'error_log', 'completed_at',
        'progress_current', 'updated_at',
    ])


def _job_work_items(job):
    """Flatten a job's study/series relations into per-series work items.

    Returns a list of dicts:
      [{'study_instance_uid': str, 'series_instance_uid': str|None,
        'remote_patient_id': str|None}]

    A study with no series rows yields one item with series_instance_uid=None
    (meaning "whole study"). Returns [] when job is None, unsaved, or has no studies."""
    if job is None or job.pk is None:
        return []
    flat = []
    for study in job.studies.prefetch_related('series').order_by('study_instance_uid'):
        remote_pid = study.remote_patient_id
        if study.series.exists():
            for s in study.series.order_by('series_instance_uid'):
                flat.append({
                    'study_instance_uid': study.study_instance_uid,
                    'series_instance_uid': s.series_instance_uid,
                    'remote_patient_id': remote_pid,
                })
        else:
            flat.append({
                'study_instance_uid': study.study_instance_uid,
                'series_instance_uid': None,
                'remote_patient_id': remote_pid,
            })
    return flat


def _parse_dicom_date(value):
    """Parse a DICOM date string (YYYYMMDD) to date or None."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), '%Y%m%d').date()
    except (ValueError, TypeError):
        return None


def _mark_item_done(job, study_uid, series_uid, stats):
    """Update the RetrievalJobStudy (and Series if applicable) with outcome."""
    if job is None:
        return
    if series_uid:
        RetrievalJobSeries.objects.filter(
            study__job=job, study__study_instance_uid=study_uid,
            series_instance_uid=series_uid,
        ).update(
            status='done',
            completed=stats.get('completed', 0),
            failed=stats.get('failed', 0),
            warning=stats.get('warning', 0),
        )
    else:
        job.studies.filter(study_instance_uid=study_uid).update(
            status='done',
            completed=stats.get('completed', 0),
            failed=stats.get('failed', 0),
            warning=stats.get('warning', 0),
        )


def _mark_item_failed(job, study_uid, series_uid, error):
    if job is None:
        return
    if series_uid:
        RetrievalJobSeries.objects.filter(
            study__job=job, study__study_instance_uid=study_uid,
            series_instance_uid=series_uid,
        ).update(status='failed', failed=1)
    else:
        job.studies.filter(study_instance_uid=study_uid).update(
            status='failed', failed=1,
        )


def _run_job_retrieval(job, node, patient, task_run=None, patient_id_aliases=None):
    """Retrieve all of a job's requested items via C-MOVE/C-GET.
    Updates RetrievalJobStudy/Series rows with outcome. Returns
    {'studies': [item results], 'instances_completed': n, 'status': ...}."""

    def _job_update(**fields):
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
            job.save()

    # If no studies are pre-registered, run C-FIND and create them
    if job and not job.studies.exists():
        _update_task_run(task_run, None, 10, 100, description='Querying studies (C-FIND)')
        found = qr_client.find_studies_for_patient(node, patient, patient_id_aliases)
        for s in found:
            RetrievalJobStudy.objects.create(
                job=job,
                study_instance_uid=s['study_instance_uid'],
                remote_patient_id=s.get('remote_patient_id'),
                study_date=_parse_dicom_date(s.get('study_date')),
                study_description=s.get('study_description'),
                modalities=s.get('modalities'),
                accession_number=s.get('accession_number'),
            )

    flat = _job_work_items(job)
    total = len(flat)
    instances = 0
    item_results = []  # still returned in result dict for API compat

    # Outcomes of items already completed in a previous run (UI resume or
    # auto-continue). Keyed (study_uid, series_uid|None) to match the work
    # items; skipping them makes a rerun continue instead of re-pulling.
    done_items = {}
    if job is not None:
        for study_row in job.studies.prefetch_related('series').all():
            if study_row.status == 'done' and not study_row.series.exists():
                done_items[(study_row.study_instance_uid, None)] = study_row
            for series_row in study_row.series.all():
                if series_row.status == 'done':
                    done_items[
                        (study_row.study_instance_uid, series_row.series_instance_uid)
                    ] = series_row

    # Graceful timeout: bail out before the soft limit (3.5h) so the job is
    # marked PARTIAL instead of being orphaned in RUNNING by a SIGKILL.
    _retrieval_deadline = time.monotonic() + 3.5 * 3600 - 120  # 2 min margin

    for i, target in enumerate(flat):
        study_uid = target['study_instance_uid']
        series_uid = target['series_instance_uid']
        remote_pid = target['remote_patient_id'] or patient.patient_id

        # Resume: fold in the stored outcome and skip the network call.
        done_row = done_items.get((study_uid, series_uid))
        if done_row is not None:
            item_results.append({
                'study_instance_uid': study_uid,
                'series_instance_uid': series_uid,
                'completed': done_row.completed or 0,
                'failed': done_row.failed or 0,
                'warning': done_row.warning or 0,
            })
            instances += done_row.completed or 0
            _update_task_run(
                task_run, None, 10 + int(80 * (i + 1) / max(total, 1)), 100,
                description=f'Retrieving {i + 1}/{total} (already done, skipping)',
            )
            continue

        if time.monotonic() > _retrieval_deadline:
            timeout_reason = (
                f'Timeout: reached 2 min before soft limit with '
                f'{total - i} item(s) remaining'
            )
            logger.warning('Retrieval timeout for job %s: %s', job.pk, timeout_reason)
            for remaining in flat[i:]:
                if (remaining['study_instance_uid'],
                        remaining['series_instance_uid']) in done_items:
                    continue
                _mark_item_failed(
                    job, remaining['study_instance_uid'],
                    remaining['series_instance_uid'], timeout_reason,
                )
                item_results.append({
                    'study_instance_uid': remaining['study_instance_uid'],
                    'series_instance_uid': remaining['series_instance_uid'],
                    'completed': 0, 'failed': 1, 'warning': 0,
                    'error': timeout_reason,
                })
            break
        _update_task_run(
            task_run, None, 10 + int(80 * i / max(total, 1)), 100,
            description=f'Retrieving {i + 1}/{total}',
        )
        try:
            if node.prefer_c_get:
                stats = (
                    qr_client.get_series(node, study_uid, series_uid, remote_pid)
                    if series_uid else
                    qr_client.get_study(node, study_uid, remote_pid)
                )
            else:
                stats = (
                    qr_client.move_series(node, study_uid, series_uid, remote_pid)
                    if series_uid else
                    qr_client.move_study(node, study_uid, remote_pid)
                )
        except qr_client.QRModelNotAcceptedError as e:
            logger.error('Retrieve method not supported by %s: %s', node, e)
            stats = {'status': None, 'completed': 0, 'failed': -1, 'error': str(e)}
            # Mark all remaining as failed
            for remaining in flat[i:]:
                _mark_item_failed(job, remaining['study_instance_uid'],
                                  remaining['series_instance_uid'], str(e))
                item_results.append({
                    'study_instance_uid': remaining['study_instance_uid'],
                    'series_instance_uid': remaining['series_instance_uid'],
                    **stats,
                })
            break
        except Exception as e:
            logger.exception('Retrieval of %s/%s failed', study_uid, series_uid)
            stats = {'status': None, 'completed': 0, 'failed': -1, 'error': str(e)}
            _mark_item_failed(job, study_uid, series_uid, str(e))

        _mark_item_done(job, study_uid, series_uid, stats)
        item_results.append({
            'study_instance_uid': study_uid,
            'series_instance_uid': series_uid,
            **stats,
        })
        instances += stats.get('completed', 0)

    failed = sum(1 for s in item_results if s['failed'])
    if total == 0 or failed == 0:
        final = RetrievalJob.Status.SUCCESS
    elif failed < total:
        final = RetrievalJob.Status.PARTIAL
    else:
        final = RetrievalJob.Status.FAILED

    result = {'studies': item_results, 'instances_completed': instances, 'status': final}
    _job_update(
        status=final, instances_received=instances,
        completed_at=timezone.now(),
        error_log='' if failed == 0 else str(item_results),
    )
    return result


@shared_task(bind=True, time_limit=4 * 3600, soft_time_limit=3.5 * 3600)
def task_retrieve_studies(self, node_id, patient_id, user_id=None, job_id=None, patient_id_aliases=None):
    """C-FIND then retrieve (C-MOVE/C-GET) all studies for a patient from a
    remote node. Tracks progress on the linked RetrievalJob + TaskRun.

    If patient_id_aliases is given, the canonical patient_id plus those aliases
    are queried so that different remote patient ID formats are discovered.

    Carries its own 4h/3.5h limits (matching task_retrieve_patient_selection)
    so the graceful in-task deadline in _run_job_retrieval can fire instead of
    the global 1h hard limit SIGKILLing the task mid-retrieval. Reruns are
    incremental: items already marked done on the job are skipped.
    """
    task_run = _create_task_run(
        task_name='dicom_server.task_retrieve_studies',
        task_type='DICOM_IMPORT',
        user_id=user_id,
        celery_task_id=self.request.id,
        task_args=self.request.args,
        task_kwargs=self.request.kwargs,
    )

    job = None
    try:
        node = RemoteDICOMNode.objects.get(pk=node_id)
        patient = Patient.objects.get(patient_id=patient_id)
        if job_id:
            job = RetrievalJob.objects.get(pk=job_id)
            job.status = RetrievalJob.Status.RUNNING
            job.celery_task_id = self.request.id or ''
            job.save(update_fields=['status', 'celery_task_id'])
    except (RemoteDICOMNode.DoesNotExist, Patient.DoesNotExist, RetrievalJob.DoesNotExist) as e:
        _fail_task_run(task_run, e)
        if job_id:
            RetrievalJob.objects.filter(pk=job_id).update(
                status=RetrievalJob.Status.FAILED, error_log=str(e),
                completed_at=timezone.now(),
            )
        raise

    try:
        result = _run_job_retrieval(job, node, patient, task_run, patient_id_aliases)
        _update_task_run(task_run, None, 100, 100, description='Done')
        _complete_task_run(task_run, result)
        return result
    except Exception as e:
        logger.exception('Retrieval job failed')
        if job:
            job.status = RetrievalJob.Status.FAILED
            job.error_log = str(e)
            job.completed_at = timezone.now()
            job.save()
        _fail_task_run(task_run, e)
        raise


# ---------------------------------------------------------------------------
# Bulk retrieval: query phase (C-FIND per patient) and chord-dispatched
# retrieval phase
# ---------------------------------------------------------------------------

@shared_task(bind=True)
def task_query_patient_studies(self, batch_id, patient_pk):
    """C-FIND a batch patient's remote studies + series and store the tree on
    its RetrievalBatchPatient row. Never raises — a failure marks the row
    ERROR so the chord callback still fires and other patients continue."""
    try:
        batch = RetrievalBatch.objects.get(pk=batch_id)
    except RetrievalBatch.DoesNotExist as e:
        return {'patient': patient_pk, 'status': 'ERROR', 'error': str(e)}

    task_run = _create_task_run(
        task_name='dicom_server.task_query_patient_studies',
        task_type='DICOM_IMPORT',
        user_id=batch.created_by_id,
        celery_task_id=self.request.id,
        task_args=self.request.args,
        task_kwargs=self.request.kwargs,
    )

    def _finish(status, error='', studies=None, ids=None):
        item_updates = {'query_status': status, 'error': error}
        if studies is not None:
            item_updates['studies'] = studies
        if ids is not None:
            item_updates['remote_patient_ids'] = ids
        RetrievalBatchPatient.objects.filter(
            batch_id=batch_id, patient_id=patient_pk,
        ).update(**item_updates)
        result = {'patient': patient_pk, 'status': status,
                  'studies': len(studies or []), 'error': error}
        _finish_task_run_quiet(task_run, result)
        return result

    try:
        item = RetrievalBatchPatient.objects.select_related('patient').get(
            batch_id=batch_id, patient_id=patient_pk,
        )
    except RetrievalBatchPatient.DoesNotExist as e:
        _fail_task_run(task_run, e)
        return {'patient': patient_pk, 'status': 'ERROR', 'error': str(e)}

    item.query_status = RetrievalBatchPatient.QueryStatus.QUERYING
    item.save(update_fields=['query_status'])

    patient = item.patient
    if not patient.chavi_consent:
        return _finish('ERROR', error='patient has not consented')

    node = batch.node
    ids = node.remote_patient_ids_for(
        patient, extra_transforms=batch.extra_transforms,
    )
    try:
        studies, errors = qr_client.find_studies_with_series(node, ids)
    except Exception as e:
        logger.exception('Batch query failed for patient %s on %s', patient_pk, node)
        return _finish('ERROR', error=str(e), ids=ids)

    known_uids = set(
        DICOMStudy.objects.filter(
            study_instance_uid__in=[
                s['study_instance_uid'] for s in studies if s.get('study_instance_uid')
            ],
        ).values_list('study_instance_uid', flat=True)
    )
    for study in studies:
        study['already_local'] = study.get('study_instance_uid') in known_uids

    error = '; '.join(errors)
    return _finish('DONE', error=error, studies=studies, ids=ids)


@shared_task(bind=True)
def task_finalize_batch_query(self, results, batch_id):
    """Chord body for the query phase — flips the batch to
    AWAITING_SELECTION once every patient row has a terminal query status."""
    try:
        batch = RetrievalBatch.objects.get(pk=batch_id)
    except RetrievalBatch.DoesNotExist as e:
        return {'batch': batch_id, 'status': 'ERROR', 'error': str(e)}

    task_run = _create_task_run(
        task_name='dicom_server.task_finalize_batch_query',
        task_type='DICOM_IMPORT',
        user_id=batch.created_by_id,
        celery_task_id=self.request.id,
    )

    if batch.status != RetrievalBatch.Status.QUERYING:
        result = {'batch': batch_id, 'status': batch.status, 'skipped': True}
        _finish_task_run_quiet(task_run, result)
        return result

    counts = {'DONE': 0, 'ERROR': 0}
    for status in batch.patients.values_list('query_status', flat=True):
        if status in counts:
            counts[status] += 1
    summary = {'queried': counts['DONE'], 'errors': counts['ERROR'],
               'total': batch.patients.count()}
    batch.summary = summary
    # Defensive: if any row is somehow still PENDING/QUERYING keep QUERYING —
    # the polling UI derives per-patient progress from the rows regardless.
    if counts['DONE'] + counts['ERROR'] >= summary['total']:
        batch.status = RetrievalBatch.Status.AWAITING_SELECTION
    batch.save(update_fields=['status', 'summary'])
    result = {'batch': batch_id, 'status': batch.status, **summary}
    _finish_task_run_quiet(task_run, result)
    return result


@shared_task(bind=True, time_limit=4 * 3600, soft_time_limit=3.5 * 3600)
def task_retrieve_patient_selection(self, job_id):
    """Retrieve one patient's selected studies/series as part of a bulk chord.

    Never raises — returns {'job_id', 'status', ...} so a single patient's
    failure cannot sink the chord callback."""
    try:
        job = RetrievalJob.objects.select_related('node', 'patient').get(pk=job_id)
    except RetrievalJob.DoesNotExist as e:
        return {'job_id': job_id, 'status': 'FAILED', 'error': str(e)}

    task_run = _create_task_run(
        task_name='dicom_server.task_retrieve_patient_selection',
        task_type='DICOM_IMPORT',
        user_id=job.created_by_id,
        celery_task_id=self.request.id,
        task_args=self.request.args,
        task_kwargs=self.request.kwargs,
    )

    job.status = RetrievalJob.Status.RUNNING
    job.celery_task_id = self.request.id or ''
    job.save(update_fields=['status', 'celery_task_id'])

    try:
        result = _run_job_retrieval(job, job.node, job.patient, task_run)
        _update_task_run(task_run, None, 100, 100, description='Done')
        _finish_task_run_quiet(task_run, result)
        return {'job_id': job_id, **result}
    except Exception as e:
        logger.exception('Bulk retrieval job %s failed', job_id)
        job.status = RetrievalJob.Status.FAILED
        job.error_log = str(e)
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'error_log', 'completed_at'])
        result = {'job_id': job_id, 'status': 'FAILED', 'error': str(e)}
        _finish_task_run_quiet(task_run, result, error=e)
        return result


@shared_task(bind=True)
def task_finalize_retrieval_batch(self, results, batch_id):
    """Chord body for the retrieve phase — aggregates job statuses onto the
    RetrievalBatch summary and notifies the user once."""
    task_run = _create_task_run(
        task_name='dicom_server.task_finalize_retrieval_batch',
        task_type='DICOM_IMPORT',
        user_id=None,
        celery_task_id=self.request.id,
    )
    try:
        batch = RetrievalBatch.objects.get(pk=batch_id)
    except RetrievalBatch.DoesNotExist as e:
        _fail_task_run(task_run, e)
        raise
    if batch.created_by_id:
        task_run.user_id = batch.created_by_id
        task_run.save(update_fields=['user_id', 'updated_at'])

    jobs = list(batch.jobs.select_related('patient'))
    succeeded = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.SUCCESS]
    partial = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.PARTIAL]
    failed = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.FAILED]
    running = [j.patient_id for j in jobs if j.status in (
        RetrievalJob.Status.PENDING, RetrievalJob.Status.RUNNING,
    )]
    skipped = list(
        batch.patients.filter(selected=False).values_list('patient_id', flat=True)
    )

    if running:
        final = batch.status  # defensive — header tasks all returned already
    elif not failed and not partial:
        final = RetrievalBatch.Status.SUCCESS
    elif succeeded or partial:
        final = RetrievalBatch.Status.PARTIAL
    else:
        final = RetrievalBatch.Status.FAILED

    batch.summary = {
        'total': len(jobs), 'succeeded': succeeded, 'partial': partial,
        'failed': failed, 'skipped': skipped,
        'instances': sum(j.instances_received for j in jobs),
    }
    batch.status = final
    batch.completed_at = timezone.now()
    batch.save(update_fields=['status', 'summary', 'completed_at'])
    _complete_task_run(task_run, batch.summary)
    return {'batch': batch_id, 'status': final, **batch.summary}


# ---------------------------------------------------------------------------
# Auto-retrieval tasks
# ---------------------------------------------------------------------------

def _auto_retrieve_patient_node(node_id, patient_id, force=False):
    """Find unknown studies for one patient on one node and retrieve them.

    This function is synchronous; it is called inside batch workers and the
    single-patient Celery task wrapper.
    """
    try:
        node = RemoteDICOMNode.objects.get(pk=node_id, is_active=True)
    except RemoteDICOMNode.DoesNotExist:
        return {'skipped': True, 'reason': f'node {node_id} not found or inactive'}
    try:
        patient = Patient.objects.get(patient_id=patient_id)
    except Patient.DoesNotExist:
        return {'skipped': True, 'reason': f'patient {patient_id} not found'}
    if not patient.chavi_consent:
        return {'skipped': True, 'reason': f'patient {patient_id} has not consented'}

    state, _ = AutoRetrievalState.objects.get_or_create(patient=patient, node=node)

    if not force and state.last_attempt_at:
        elapsed = (timezone.now() - state.last_attempt_at).total_seconds() / 60
        if elapsed < node.auto_retrieve_min_interval_minutes:
            return {'skipped': True, 'reason': 'minimum interval not elapsed'}

    state.last_attempt_at = timezone.now()
    state.save(update_fields=['last_attempt_at'])

    aliases = node.remote_patient_ids_for(patient)

    try:
        studies = qr_client.find_studies_for_patient(node, patient, aliases)
    except Exception as e:
        logger.exception('Auto-retrieval C-FIND failed for %s on %s', patient_id, node)
        return {'skipped': True, 'reason': f'c-find failed: {e}'}

    found_uids = {s.get('study_instance_uid') for s in studies if s.get('study_instance_uid')}
    known_uids = set(
        DICOMStudy.objects.filter(study_instance_uid__in=found_uids)
        .values_list('study_instance_uid', flat=True)
    )
    unknown_uids = found_uids - known_uids

    if not unknown_uids:
        state.last_success_at = timezone.now()
        state.last_known_study_uids = sorted(found_uids)
        state.save(update_fields=['last_success_at', 'last_known_study_uids'])
        return {'skipped': False, 'found': len(found_uids), 'new': 0}

    # Create job + study rows with the remote_patient_id from C-FIND
    job = RetrievalJob.objects.create(
        node=node, patient=patient, created_by=None,
    )
    remote_pid_by_uid = {
        s['study_instance_uid']: s.get('remote_patient_id')
        for s in studies if s.get('study_instance_uid')
    }
    RetrievalJobStudy.objects.bulk_create([
        RetrievalJobStudy(
            job=job, study_instance_uid=uid,
            remote_patient_id=remote_pid_by_uid.get(uid),
        )
        for uid in sorted(unknown_uids)
    ])

    try:
        result = task_retrieve_studies.delay(
            node.pk, patient.patient_id, None, job.pk, patient_id_aliases=aliases,
        )
        job.celery_task_id = result.id or ''
        job.save(update_fields=['celery_task_id'])
    except Exception as e:
        logger.exception('Failed to dispatch auto-retrieval job')
        job.status = RetrievalJob.Status.FAILED
        job.error_log = f'Failed to dispatch task: {e}'
        job.save(update_fields=['status', 'error_log'])
        return {'skipped': False, 'error': str(e)}

    state.last_known_study_uids = sorted(found_uids)
    state.save(update_fields=['last_known_study_uids'])

    return {'skipped': False, 'found': len(found_uids), 'new': len(unknown_uids), 'job': job.pk}


@shared_task(bind=True)
def task_auto_retrieve_patient_node(self, node_id, patient_id, force=False):
    """Celery wrapper for a single patient-node auto-retrieval."""
    return _auto_retrieve_patient_node(node_id, patient_id, force=force)


@shared_task(bind=True)
def task_auto_retrieve_patient_batch(self, node_id, patient_ids, force=False):
    """Process a batch of patients for one node synchronously.

    This keeps the number of Celery messages low: one message per batch
    instead of one message per patient.
    """
    results = []
    for pid in patient_ids:
        results.append(_auto_retrieve_patient_node(node_id, pid, force=force))
    return results


@shared_task(bind=True)
def task_auto_retrieve_node(self, node_id):
    """Periodic task: enqueue batched auto-retrieval for every consented patient against one node."""
    try:
        node = RemoteDICOMNode.objects.get(pk=node_id, is_active=True, auto_retrieve_enabled=True)
    except RemoteDICOMNode.DoesNotExist:
        return {'skipped': True, 'reason': 'node not active or not enabled'}

    patient_ids = list(
        Patient.objects.filter(chavi_consent=True)
        .values_list('patient_id', flat=True)
    )

    batch_size = node.auto_retrieve_batch_size or 50
    if batch_size <= 0:
        batch_size = 50

    dispatched = 0
    for i in range(0, len(patient_ids), batch_size):
        chunk = patient_ids[i:i + batch_size]
        task_auto_retrieve_patient_batch.delay(node.pk, chunk)
        dispatched += 1

    return {'node': node.pk, 'batches': dispatched, 'patients': len(patient_ids)}


@shared_task(bind=True)
def task_auto_retrieve_patient(self, patient_id):
    """Event-driven: immediately retrieve one patient from all auto-retrieval-enabled nodes."""
    nodes = RemoteDICOMNode.objects.filter(is_active=True, auto_retrieve_enabled=True)
    if not nodes.exists():
        return {'skipped': True, 'reason': 'no auto-retrieval-enabled nodes'}
    try:
        patient = Patient.objects.get(patient_id=patient_id)
    except Patient.DoesNotExist:
        return {'skipped': True, 'reason': f'patient {patient_id} not found'}
    if not patient.chavi_consent:
        return {'skipped': True, 'reason': f'patient {patient_id} has not consented'}

    for node in nodes:
        task_auto_retrieve_patient_node.delay(node.pk, patient.patient_id, force=True)

    return {'patient': patient_id, 'nodes': list(nodes.values_list('pk', flat=True))}


# ---------------------------------------------------------------------------
# Scheduled bulk retrieval
# ---------------------------------------------------------------------------

def _aggregate_retrieval_batch(batch):
    """Compute (final_status, summary) for a retrieve-phase batch. Same shape as
    task_finalize_retrieval_batch uses. Returns RetrievalBatch.Status values."""
    jobs = list(batch.jobs.select_related('patient'))
    succeeded = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.SUCCESS]
    partial = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.PARTIAL]
    failed = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.FAILED]
    running = [j.patient_id for j in jobs if j.status in (
        RetrievalJob.Status.PENDING, RetrievalJob.Status.RUNNING,
    )]
    skipped = list(
        batch.patients.filter(selected=False).values_list('patient_id', flat=True)
    )
    if running:
        final = batch.status
    elif not failed and not partial:
        final = RetrievalBatch.Status.SUCCESS
    elif succeeded or partial:
        final = RetrievalBatch.Status.PARTIAL
    else:
        final = RetrievalBatch.Status.FAILED
    summary = {
        'total': len(jobs), 'succeeded': succeeded, 'partial': partial,
        'failed': failed, 'skipped': skipped,
        'instances': sum(j.instances_received for j in jobs),
    }
    return final, summary


def _prepare_bulk_schedule_batch(schedule):
    """Create the RetrievalBatch + one row per consented schedule patient.
    Returns (batch, patients)."""
    patients = list(schedule.patients.filter(chavi_consent=True))
    batch = RetrievalBatch.objects.create(
        node=schedule.node, created_by=schedule.created_by,
        extra_transforms=schedule.extra_transforms,
    )
    if patients:
        RetrievalBatchPatient.objects.bulk_create(
            RetrievalBatchPatient(batch=batch, patient=p) for p in patients
        )
    return batch, patients


@shared_task(bind=True)
def task_bulk_schedule_run(self, schedule_id):
    """Entry task for a scheduled bulk retrieval (one-off eta or beat).
    Builds a RetrievalBatch, runs the per-patient C-FIND query chord, and hands
    off to task_bulk_schedule_finalize_query which auto-selects + retrieves."""
    task_run = _create_task_run(
        task_name='dicom_server.tasks.task_bulk_schedule_run',
        task_type='DICOM_IMPORT', user_id=None, celery_task_id=self.request.id,
    )
    try:
        schedule = BulkRetrievalSchedule.objects.select_related('node').get(
            pk=schedule_id, is_active=True,
        )
    except BulkRetrievalSchedule.DoesNotExist as e:
        _fail_task_run(task_run, e)
        return {'schedule': schedule_id, 'skipped': True, 'error': str(e)}
    if schedule.created_by_id:
        task_run.user_id = schedule.created_by_id
        task_run.save(update_fields=['user_id', 'updated_at'])

    if not schedule.node.is_active:
        _complete_task_run(task_run, {'skipped': True, 'reason': 'node inactive'})
        return {'schedule': schedule_id, 'skipped': True, 'reason': 'node inactive'}

    batch, patients = _prepare_bulk_schedule_batch(schedule)
    schedule.last_batch = batch
    schedule.save(update_fields=['last_batch', 'updated_at'])

    if not patients:
        schedule.last_status = 'SKIPPED'
        schedule.last_run_at = timezone.now()
        schedule.save(update_fields=['last_status', 'last_run_at', 'updated_at'])
        _complete_task_run(task_run, {'skipped': True, 'reason': 'no consented patients'})
        return {'schedule': schedule_id, 'skipped': True, 'reason': 'no consented patients'}

    try:
        header = group(
            task_query_patient_studies.s(batch.pk, p.patient_id) for p in patients
        )
        result = chord(header)(task_bulk_schedule_finalize_query.s(batch.pk, schedule.pk))
        batch.query_group_id = str(result.id or '')
        batch.save(update_fields=['query_group_id'])
    except Exception as e:
        logger.exception('Failed to dispatch scheduled bulk query')
        batch.status = RetrievalBatch.Status.FAILED
        batch.save(update_fields=['status'])
        _fail_task_run(task_run, e)
        raise

    _complete_task_run(task_run, {'batch': batch.pk, 'patients': len(patients)})
    return {'schedule': schedule_id, 'batch': batch.pk, 'patients': len(patients)}


def _populate_study_metadata(job, found_list):
    """Copy C-FIND metadata from the found-list dicts onto job study rows."""
    for found in found_list:
        suid = found.get('study_instance_uid')
        if not suid:
            continue
        RetrievalJobStudy.objects.filter(
            job=job, study_instance_uid=suid,
        ).update(
            study_date=_parse_dicom_date(found.get('study_date')),
            study_description=found.get('study_description'),
            modalities=found.get('modalities'),
            accession_number=found.get('accession_number'),
        )
        # Series metadata
        for se in (found.get('series') or []):
            RetrievalJobSeries.objects.filter(
                study__job=job, study__study_instance_uid=suid,
                series_instance_uid=se.get('series_instance_uid', ''),
            ).update(
                series_description=se.get('series_description'),
                modality=se.get('modality'),
                series_date=_parse_dicom_date(se.get('series_date')),
            )


def _record_schedule_run(schedule, status):
    schedule.last_status = status
    schedule.last_run_at = timezone.now()
    schedule.save(update_fields=['last_status', 'last_run_at', 'updated_at'])


def _dispatch_retrieval_chunk(batch, schedule, start, cap, total):
    """Dispatch one chunk (cap patients) of retrieval as a chord. The chord
    body is the next-chunk relay, or the finalizer when this is the last
    chunk. Because only one chunk is ever in flight, at most `cap` patients
    are retrieved concurrently."""
    chunk = batch.jobs.order_by('pk')[start:start + cap]
    if not chunk:
        return None
    if start + cap >= total:
        body = task_bulk_schedule_finalize_retrieval.s(batch.pk, schedule.pk)
    else:
        body = task_bulk_schedule_chunk_done.s(batch.pk, start + cap, total, cap, schedule.pk)
    return chord(group(task_retrieve_patient_selection.s(j.pk) for j in chunk))(body)


@shared_task(bind=True)
def task_bulk_schedule_finalize_query(self, results, batch_id, schedule_id):
    """Chord body for the query phase of a scheduled bulk run. Selects
    studies/series via bulk_selection (per the schedule's criteria) into
    per-patient RetrievalJobs, then starts the bounded retrieve phase."""
    from dicom_server.services import bulk_selection
    task_run = _create_task_run(
        task_name='dicom_server.tasks.task_bulk_schedule_finalize_query',
        task_type='DICOM_IMPORT', user_id=None, celery_task_id=self.request.id,
    )
    try:
        batch = RetrievalBatch.objects.get(pk=batch_id)
        schedule = BulkRetrievalSchedule.objects.get(pk=schedule_id)
    except (RetrievalBatch.DoesNotExist, BulkRetrievalSchedule.DoesNotExist) as e:
        _fail_task_run(task_run, e)
        return {'batch': batch_id, 'status': 'ERROR', 'error': str(e)}
    if batch.created_by_id:
        task_run.user_id = batch.created_by_id
        task_run.save(update_fields=['user_id', 'updated_at'])

    if batch.status != RetrievalBatch.Status.QUERYING:
        _finish_task_run_quiet(task_run, {'skipped': True, 'status': batch.status})
        return {'batch': batch_id, 'status': batch.status, 'skipped': True}

    criteria = schedule.selection_criteria()
    new_only = schedule.retrieve_new_only
    for row in batch.patients.select_related('patient'):
        if row.query_status != RetrievalBatchPatient.QueryStatus.DONE:
            continue
        entries = bulk_selection.build_selections_for_patient(
            row.studies or [], criteria, new_only=new_only,
        )
        if not entries:
            continue
        job = RetrievalJob.objects.create(
            node=batch.node, patient=row.patient,
            created_by=batch.created_by, batch=batch,
        )
        # Create study + series rows
        study_rows = []
        for entry in entries:
            suid = entry['study_instance_uid']
            study = RetrievalJobStudy(
                job=job, study_instance_uid=suid,
                remote_patient_id=entry.get('remote_patient_id'),
            )
            study_rows.append(study)
        RetrievalJobStudy.objects.bulk_create(study_rows)
        # Link series
        for entry in entries:
            suid = entry['study_instance_uid']
            series_uids = entry.get('series_instance_uids')
            if series_uids:
                job_study = job.studies.get(study_instance_uid=suid)
                RetrievalJobSeries.objects.bulk_create([
                    RetrievalJobSeries(study=job_study, series_instance_uid=suid2)
                    for suid2 in series_uids
                ])
        # Populate C-FIND metadata onto the study/series rows (for display)
        chosen_uids = {e['study_instance_uid'] for e in entries}
        found_subset = [
            s for s in (row.studies or [])
            if s.get('study_instance_uid') in chosen_uids
        ]
        _populate_study_metadata(job, found_subset)
        row.selected = True
        row.job = job
        row.save(update_fields=['selected', 'job'])

    total_jobs = batch.jobs.count()
    if total_jobs == 0:
        final, summary = _aggregate_retrieval_batch(batch)
        batch.summary = summary
        batch.status = final
        batch.completed_at = timezone.now()
        batch.save(update_fields=['status', 'summary', 'completed_at'])
        _record_schedule_run(schedule, final)
        _complete_task_run(task_run, summary)
        return {'batch': batch_id, 'status': final, **summary}

    batch.status = RetrievalBatch.Status.RETRIEVING
    batch.save(update_fields=['status'])
    cap = schedule.max_concurrent_patients or 2
    _dispatch_retrieval_chunk(batch, schedule, 0, cap, total_jobs)
    _complete_task_run(task_run, {'dispatched': True, 'jobs': total_jobs, 'cap': cap})
    return {'batch': batch_id, 'status': batch.status, 'jobs': total_jobs}


@shared_task(bind=True)
def task_bulk_schedule_chunk_done(self, results, batch_id, next_start, total, cap, schedule_id):
    """Chord body for a non-final retrieve chunk — dispatch the next chunk so
    the next `cap` patients start only after this chunk has completed."""
    batch = RetrievalBatch.objects.get(pk=batch_id)
    schedule = BulkRetrievalSchedule.objects.get(pk=schedule_id)
    _dispatch_retrieval_chunk(batch, schedule, next_start, cap, total)
    return {'batch': batch_id, 'next_start': next_start}


@shared_task(bind=True)
def task_bulk_schedule_finalize_retrieval(self, results, batch_id, schedule_id):
    """Final chord body for a scheduled bulk run — aggregate job statuses onto
    the batch, record the run on the schedule, and notify the owner."""
    task_run = _create_task_run(
        task_name='dicom_server.tasks.task_bulk_schedule_finalize_retrieval',
        task_type='DICOM_IMPORT', user_id=None, celery_task_id=self.request.id,
    )
    try:
        batch = RetrievalBatch.objects.get(pk=batch_id)
        schedule = BulkRetrievalSchedule.objects.get(pk=schedule_id)
    except (RetrievalBatch.DoesNotExist, BulkRetrievalSchedule.DoesNotExist) as e:
        _fail_task_run(task_run, e)
        return {'batch': batch_id, 'status': 'ERROR', 'error': str(e)}
    if batch.created_by_id:
        task_run.user_id = batch.created_by_id
        task_run.save(update_fields=['user_id', 'updated_at'])

    final, summary = _aggregate_retrieval_batch(batch)
    batch.summary = summary
    batch.status = final
    batch.completed_at = timezone.now()
    batch.save(update_fields=['status', 'summary', 'completed_at'])
    _record_schedule_run(schedule, final)
    _complete_task_run(task_run, summary)
    return {'batch': batch_id, 'schedule': schedule_id, 'status': final, **summary}


# ---------------------------------------------------------------------------
# Stuck batch recovery
#
# If a chord's *result* message is lost (broker restart, queue purge, timeout)
# or a header task is hard-killed, the chord body never fires and the
# RetrievalBatch stays in QUERYING / RETRIEVING forever. This beat task
# detects such batches and either re-fires the (idempotent) finalizer or marks
# the batch FAILED with a clear reason + notification.
# ---------------------------------------------------------------------------

# A query phase with no progress for longer than this means a query task died
# without recording an outcome (a single-patient C-FIND should never take this
# long).
_QUERY_STALE_MINUTES = 60
# A retrieval job running longer than this means the retrieve task was
# hard-killed (its own hard limit is 4h; add margin).
_RETRIEVAL_STALE_HOURS = 5


def _schedule_for_batch(batch):
    """Return the BulkRetrievalSchedule whose last_batch is this batch, or None."""
    return batch.schedule_runs.first()


def _fire_query_finalizer(batch):
    schedule = _schedule_for_batch(batch)
    if schedule is not None:
        task_bulk_schedule_finalize_query.delay(None, batch.pk, schedule.pk)
    else:
        task_finalize_batch_query.delay(None, batch.pk)


def _fire_retrieval_finalizer(batch):
    schedule = _schedule_for_batch(batch)
    if schedule is not None:
        task_bulk_schedule_finalize_retrieval.delay(None, batch.pk, schedule.pk)
    else:
        task_finalize_retrieval_batch.delay(None, batch.pk)


def _fail_stuck_batch(batch, reason):
    summary = dict(batch.summary or {})
    summary['recovery_error'] = reason
    batch.summary = summary
    batch.status = RetrievalBatch.Status.FAILED
    batch.completed_at = timezone.now()
    batch.save(update_fields=['status', 'summary', 'completed_at'])
    if batch.created_by_id:
        Notification.objects.create(
            user=batch.created_by,
            notification_type=Notification.NotificationType.TASK_FAILED,
            title=f"Retrieval batch stuck: {batch.pk}",
            message=f"Retrieval batch {batch.pk} was marked failed: {reason}",
        )
    logger.warning('Marked stuck retrieval batch %s FAILED: %s', batch.pk, reason)


@shared_task(bind=True)
def task_recover_stuck_batches(self):
    """Beat task: recover RetrievalBatches stuck because a chord result was
    lost (broker restart/timeout) or a header task was hard-killed.

    Per stuck batch:
      * all work rows terminal and no partial finalization  -> re-fire the
        idempotent finalizer (the lost chord body);
      * otherwise stale (no progress beyond the threshold)  -> mark FAILED
        with a clear reason and notify the owner.
    """
    from datetime import timedelta
    now = timezone.now()
    actions = []

    query_terminal = {
        RetrievalBatchPatient.QueryStatus.DONE,
        RetrievalBatchPatient.QueryStatus.ERROR,
    }
    job_terminal = {
        RetrievalJob.Status.SUCCESS,
        RetrievalJob.Status.PARTIAL,
        RetrievalJob.Status.FAILED,
    }

    # --- QUERYING batches ---
    for batch in RetrievalBatch.objects.filter(
        status=RetrievalBatch.Status.QUERYING,
    ).select_related('node'):
        rows = list(batch.patients.values_list('query_status', flat=True))
        if not rows:
            _fail_stuck_batch(batch, 'no patient rows were ever created')
            actions.append(('failed', batch.pk))
            continue
        if all(s in query_terminal for s in rows):
            # Chord body lost. Re-fire only when finalization has not already
            # started (no jobs) — otherwise a mid-finalize kill is safer left
            # as a visible failure than risk duplicate jobs.
            if batch.jobs.count() == 0:
                _fire_query_finalizer(batch)
                actions.append(('query-finalizer', batch.pk))
            else:
                _fail_stuck_batch(
                    batch,
                    'query finalization was interrupted after creating jobs; '
                    're-run the batch',
                )
                actions.append(('failed', batch.pk))
            continue
        if (now - batch.created_at) > timedelta(minutes=_QUERY_STALE_MINUTES):
            _fail_stuck_batch(
                batch,
                f'query phase made no progress for over {_QUERY_STALE_MINUTES} minutes',
            )
            actions.append(('failed', batch.pk))

    # --- RETRIEVING batches ---
    for batch in RetrievalBatch.objects.filter(
        status=RetrievalBatch.Status.RETRIEVING,
    ).select_related('node'):
        jobs = list(batch.jobs.all())
        if not jobs:
            _fail_stuck_batch(batch, 'no retrieval jobs were ever created')
            actions.append(('failed', batch.pk))
            continue
        if all(j.status in job_terminal for j in jobs):
            _fire_retrieval_finalizer(batch)
            actions.append(('retrieval-finalizer', batch.pk))
            continue
        oldest_running = min(
            (j.created_at for j in jobs if j.status not in job_terminal),
            default=None,
        )
        if oldest_running and (now - oldest_running) > timedelta(hours=_RETRIEVAL_STALE_HOURS):
            _fail_stuck_batch(
                batch,
                f'a retrieval job has been running for over {_RETRIEVAL_STALE_HOURS} hours',
            )
            actions.append(('failed', batch.pk))

    if actions:
        logger.info('Stuck batch recovery actions: %s', actions)
    return {'actions': actions}
