"""Celery tasks for archive / de-archive runs (tracked on client_app.TaskRun).

Per-study failures are captured in the result's 'failed' map; the TaskRun
is SUCCESS when the batch itself ran, mirroring the retrieval tasks in
dicom_server/tasks.py.
"""
import logging
from pathlib import Path

from celery import shared_task
from celery_progress.backend import ProgressRecorder
from django.contrib.auth import get_user_model

from client_app.models import DICOMStudy, TaskRun
from client_app.tasks import (
    _complete_task_run,
    _create_task_run,
    _fail_task_run,
    _update_task_run,
)
from dicom_archive.models import (
    ArchiveConfiguration,
    ArchiveLocation,
    ArchivedStudy,
)
from dicom_archive.services.archive import archive_studies
from dicom_archive.services.dearchive import dearchive_studies
from dicom_archive.services.locations import candidate_studies

logger = logging.getLogger(__name__)


def _user_for(user_id):
    if not user_id:
        return None
    return get_user_model().objects.filter(id=user_id).first()


@shared_task(bind=True)
def archive_studies_task(self, study_uids, location_id, user_id=None, reason='MANUAL') -> dict:
    """Archive a batch of local studies into one ArchiveLocation."""
    progress_recorder = ProgressRecorder(self)
    task_run = _create_task_run(
        task_name='archive_studies',
        task_type=TaskRun.TaskType.DICOM_ARCHIVE,
        user_id=user_id,
        celery_task_id=self.request.id,
        task_args=self.request.args,
        task_kwargs=self.request.kwargs,
    )
    try:
        location = ArchiveLocation.objects.get(pk=location_id)
        studies = list(
            DICOMStudy.objects.filter(study_instance_uid__in=study_uids)
        )
        _update_task_run(
            task_run, progress_recorder, 0, max(len(studies), 1),
            description='Archiving',
        )
        result = archive_studies(
            studies, location, user=_user_for(user_id), reason=reason,
        )
        _update_task_run(
            task_run, progress_recorder,
            max(len(studies), 1), max(len(studies), 1),
            description='Done',
        )
        _complete_task_run(task_run, result)
        return result
    except Exception as exc:
        logger.exception('Archive batch failed')
        _fail_task_run(task_run, exc)
        raise


@shared_task(bind=True)
def dearchive_studies_task(self, study_uids, user_id=None) -> dict:
    """Restore a batch of archived studies to their original local folders."""
    progress_recorder = ProgressRecorder(self)
    task_run = _create_task_run(
        task_name='dearchive_studies',
        task_type=TaskRun.TaskType.DICOM_DEARCHIVE,
        user_id=user_id,
        celery_task_id=self.request.id,
        task_args=self.request.args,
        task_kwargs=self.request.kwargs,
    )
    try:
        _update_task_run(
            task_run, progress_recorder, 0, max(len(study_uids), 1),
            description='De-archiving',
        )
        result = dearchive_studies(list(study_uids), user=_user_for(user_id))
        _update_task_run(
            task_run, progress_recorder,
            max(len(study_uids), 1), max(len(study_uids), 1),
            description='Done',
        )
        _complete_task_run(task_run, result)
        return result
    except Exception as exc:
        logger.exception('De-archive batch failed')
        _fail_task_run(task_run, exc)
        raise


@shared_task
def task_scheduled_archive(self, user_id=None) -> dict:
    """Celery Beat entry point for the periodic archive sweep.

    Dispatched by the django-celery-beat PeriodicTask with
    args=[None], hence the leading positional ``self`` parameter.
    Takes up to config.batch_limit oldest eligible studies whose folder
    still exists on disk and dispatches archive_studies_task against the
    default active location (else the first active location).
    """
    config = ArchiveConfiguration.load()
    if not config.enabled:
        return {'status': 'disabled'}

    location = ArchiveLocation.objects.filter(
        is_active=True, is_default=True,
    ).first()
    if location is None:
        location = ArchiveLocation.objects.filter(
            is_active=True,
        ).order_by('name').first()
    if location is None:
        return {'status': 'nothing_to_do'}

    candidates = [
        study
        for study in candidate_studies(config).order_by('study_instance_uid')
        if study.folder_path and Path(study.folder_path).is_dir()
    ][:config.batch_limit]
    if not candidates:
        return {'status': 'empty'}

    study_uids = [study.study_instance_uid for study in candidates]
    archive_studies_task.delay(
        study_uids, location.pk, user_id=user_id,
        reason=ArchivedStudy.Reason.SCHEDULED,
    )
    return {
        'status': 'dispatched',
        'study_uids': study_uids,
        'location_id': location.pk,
    }
