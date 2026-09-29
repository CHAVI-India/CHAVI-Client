"""Celery tasks for DICOM query/retrieve operations."""
import logging

from celery import shared_task
from django.utils import timezone

from client_app.models import Patient, DICOMStudy, TaskRun
from client_app.tasks import (
    _create_task_run, _update_task_run, _complete_task_run, _fail_task_run,
)
from dicom_server.models import (
    AutoRetrievalState, RemoteDICOMNode, RetrievalBatch,
    RetrievalBatchPatient, RetrievalJob,
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
    """Normalised retrieval items for a job.

    -> [{'study_instance_uid': str, 'series_instance_uids': [str]|None,
         'remote_patient_id': str|None}] or None when the job requests a
    C-FIND-all retrieval (no selections/study_uids). A null
    series_instance_uids means the whole study."""
    if job and job.selections:
        return job.selections
    if job and job.study_uids:
        return [
            {'study_instance_uid': uid, 'series_instance_uids': None,
             'remote_patient_id': None}
            for uid in sorted(job.study_uids)
        ]
    return None


def _run_job_retrieval(job, node, patient, task_run=None, patient_id_aliases=None):
    """Retrieve all of a job's requested items (whole studies or selected
    series) via C-MOVE/C-GET. Returns
    {'studies': [item results], 'instances_completed': n, 'status': ...}.

    job may be None (fire-and-forget C-FIND-all retrieval with no job row)."""
    def _job_update(**fields):
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
            job.save()

    items = _job_work_items(job)
    if items is not None:
        # Study/series were pre-selected — retrieve them directly instead of
        # re-running C-FIND; connectivity failures surface as per-item stats.
        if job and not job.studies_found:
            _job_update(studies_found=items)
    else:
        _update_task_run(task_run, None, 10, 100, description='Querying studies (C-FIND)')
        found = qr_client.find_studies_for_patient(node, patient, patient_id_aliases)
        _job_update(studies_found=found)
        items = [
            {'study_instance_uid': s['study_instance_uid'],
             'series_instance_uids': None,
             'remote_patient_id': s.get('remote_patient_id')}
            for s in found
        ]

    # Flatten to (study, series|None) work units so fail-fast bookkeeping is
    # uniform for study-level and series-level retrievals.
    flat = []
    for item in items:
        study_uid = item['study_instance_uid']
        remote_pid = item.get('remote_patient_id') or patient.patient_id
        for series_uid in (item.get('series_instance_uids') or [None]):
            flat.append({
                'study_instance_uid': study_uid,
                'series_instance_uid': series_uid,
                'remote_patient_id': remote_pid,
            })

    total = len(flat)
    item_results = []
    instances = 0
    for i, target in enumerate(flat):
        study_uid = target['study_instance_uid']
        series_uid = target['series_instance_uid']
        remote_pid = target['remote_patient_id']
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
            # Every remaining item would hit the same rejection — mark them
            # all failed now instead of opening doomed associations.
            stats = {'status': None, 'completed': 0, 'failed': -1, 'error': str(e)}
            for remaining in flat[i:]:
                item_results.append({
                    'study_instance_uid': remaining['study_instance_uid'],
                    'series_instance_uid': remaining['series_instance_uid'],
                    **stats,
                })
            break
        except Exception as e:
            logger.exception('Retrieval of %s/%s failed', study_uid, series_uid)
            stats = {'status': None, 'completed': 0, 'failed': -1, 'error': str(e)}
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
        status=final, instances_received=instances, item_results=item_results,
        completed_at=timezone.now(),
        error_log='' if failed == 0 else str(item_results),
    )
    return result


@shared_task(bind=True)
def task_retrieve_studies(self, node_id, patient_id, user_id=None, job_id=None, patient_id_aliases=None):
    """C-FIND then retrieve (C-MOVE/C-GET) all studies for a patient from a
    remote node. Tracks progress on the linked RetrievalJob + TaskRun.

    If patient_id_aliases is given, the canonical patient_id plus those aliases
    are queried so that different remote patient ID formats are discovered."""
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


@shared_task(bind=True)
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

    job = RetrievalJob.objects.create(
        node=node,
        patient=patient,
        created_by=None,
        study_uids=sorted(unknown_uids),
    )

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
