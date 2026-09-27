"""Celery tasks for DICOM query/retrieve operations."""
import logging

from celery import shared_task
from django.utils import timezone

from client_app.models import Patient, DICOMStudy
from client_app.tasks import (
    _create_task_run, _update_task_run, _complete_task_run, _fail_task_run,
)
from dicom_server.models import AutoRetrievalState, RemoteDICOMNode, RetrievalJob
from dicom_server.services import qr_client

logger = logging.getLogger(__name__)


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

    def _job_update(**fields):
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
            job.save()

    try:
        requested = set(job.study_uids or []) if job else set()
        if requested:
            # Study UIDs were pre-selected (auto-retrieval) — retrieve them
            # directly instead of re-running C-FIND; each still gets its own
            # sub-op stats below. Connectivity failures surface there.
            studies = [{'study_instance_uid': uid} for uid in sorted(requested)]
        else:
            _update_task_run(task_run, None, 10, 100, description='Querying studies (C-FIND)')
            studies = qr_client.find_studies_for_patient(node, patient, patient_id_aliases)
        _job_update(studies_found=studies)

        total = len(studies)
        stats_all = []
        instances = 0
        for i, study in enumerate(studies):
            uid = study['study_instance_uid']
            _update_task_run(
                task_run, None, 10 + int(80 * i / max(total, 1)), 100,
                description=f'Retrieving study {i + 1}/{total}',
            )
            try:
                if node.prefer_c_get:
                    stats = qr_client.get_study(node, uid, patient.patient_id)
                else:
                    stats = qr_client.move_study(node, uid, patient.patient_id)
            except Exception as e:
                logger.exception('Retrieval of study %s failed', uid)
                stats = {'status': None, 'completed': 0, 'failed': -1, 'error': str(e)}
            stats_all.append({'study_instance_uid': uid, **stats})
            instances += stats.get('completed', 0)

        failed = sum(1 for s in stats_all if s['failed'])
        if total == 0:
            final = RetrievalJob.Status.SUCCESS
        elif failed == 0:
            final = RetrievalJob.Status.SUCCESS
        elif failed < total:
            final = RetrievalJob.Status.PARTIAL
        else:
            final = RetrievalJob.Status.FAILED

        result = {'studies': stats_all, 'instances_completed': instances, 'status': final}
        _job_update(
            status=final, instances_received=instances,
            studies_found=studies, completed_at=timezone.now(),
            error_log='' if failed == 0 else str(stats_all),
        )
        _update_task_run(task_run, None, 100, 100, description='Done')
        _complete_task_run(task_run, result)
        return result
    except Exception as e:
        logger.exception('Retrieval job failed')
        _job_update(status=RetrievalJob.Status.FAILED, error_log=str(e),
                    completed_at=timezone.now())
        _fail_task_run(task_run, e)
        raise


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
        patient = Patient.objects.get(patient_id=patient_id, chavi_consent=True)
    except (RemoteDICOMNode.DoesNotExist, Patient.DoesNotExist) as e:
        logger.warning('Auto-retrieval prerequisites failed: %s', e)
        return {'skipped': True, 'reason': str(e)}

    state, _ = AutoRetrievalState.objects.get_or_create(patient=patient, node=node)

    if not force and state.last_attempt_at:
        elapsed = (timezone.now() - state.last_attempt_at).total_seconds() / 60
        if elapsed < node.auto_retrieve_min_interval_minutes:
            return {'skipped': True, 'reason': 'minimum interval not elapsed'}

    state.last_attempt_at = timezone.now()
    state.save(update_fields=['last_attempt_at'])

    aliases = node.patient_id_aliases_for(patient)

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
    """Event-driven: immediately retrieve one patient from all active nodes."""
    try:
        patient = Patient.objects.get(patient_id=patient_id, chavi_consent=True)
    except Patient.DoesNotExist:
        return {'skipped': True, 'reason': 'patient not found or no consent'}

    nodes = RemoteDICOMNode.objects.filter(is_active=True, auto_retrieve_enabled=True)
    for node in nodes:
        task_auto_retrieve_patient_node.delay(node.pk, patient.patient_id, force=True)

    return {'patient': patient_id, 'nodes': list(nodes.values_list('pk', flat=True))}
