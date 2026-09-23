"""Celery tasks for DICOM query/retrieve operations."""
import logging

from celery import shared_task
from django.utils import timezone

from client_app.models import Patient
from client_app.tasks import (
    _create_task_run, _update_task_run, _complete_task_run, _fail_task_run,
)
from dicom_server.models import RemoteDICOMNode, RetrievalJob
from dicom_server.services import qr_client

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def task_retrieve_studies(self, node_id, patient_id, user_id=None, job_id=None):
    """C-FIND then retrieve (C-MOVE/C-GET) all studies for a patient from a
    remote node. Tracks progress on the linked RetrievalJob + TaskRun."""
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
            job.save(update_fields=['status', 'celery_task_id', 'completed_at', 'error_log'])
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
        _update_task_run(task_run, None, 0, 100, description='Testing connectivity (C-ECHO)')
        if not qr_client.echo(node):
            raise ConnectionError(f'C-ECHO to {node} failed — node unreachable')

        _update_task_run(task_run, None, 10, 100, description='Querying studies (C-FIND)')
        studies = qr_client.find_studies(node, patient.patient_id)
        requested = set(job.study_uids or []) if job else set()
        if requested:
            studies = [s for s in studies if s['study_instance_uid'] in requested]
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
