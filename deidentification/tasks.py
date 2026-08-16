import logging
import os
import time as _time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery_progress.backend import ProgressRecorder
from django.utils import timezone

from client_app.models import DICOMStudy, TaskRun
from client_app.tasks import (
    _create_task_run,
    _update_task_run,
    _complete_task_run,
    _fail_task_run,
    _auto_continue_task,
)
from client_app.services.task_checkpoint import (
    manifest_path_for_task,
    write_manifest_entry,
    read_manifest,
    cleanup_manifest,
)
from deidentification.models import DeidentificationJob
from deidentification.services.dicom_deidentification_flow import deidentify_study

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=3600)
def deidentify_dicom_study_task(self, study_id, user_id=None):
    progress_recorder = ProgressRecorder(self)
    task_run = None
    manifest_path = None

    try:
        manifest_path = manifest_path_for_task(self.request.id, 'DEIDENTIFICATION')
        task_run = _create_task_run(
            task_name='deidentify_dicom_study',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            user_id=user_id,
            celery_task_id=self.request.id,
            manifest_path=manifest_path,
            task_args=self.request.args,
            task_kwargs=self.request.kwargs,
        )

        study = DICOMStudy.objects.get(study_instance_uid=study_id)

        job = DeidentificationJob.objects.create(
            study=study,
            status=DeidentificationJob.Status.PENDING,
            task_run=task_run,
        )

        completed_items = read_manifest(manifest_path)

        def progress_callback(phase, current, total):
            _update_task_run(
                task_run, progress_recorder, current, total,
                description=f"{phase} — {current}/{total}",
                throttle_key=self.request.id,
            )

        def manifest_write_callback(item_id):
            if item_id not in completed_items:
                write_manifest_entry(manifest_path, item_id)
                completed_items.add(item_id)

        processed, failed = deidentify_study(
            study, job, progress_callback, manifest_write_callback,
            completed_items=completed_items,
        )

        cleanup_manifest(manifest_path)
        _complete_task_run(
            task_run,
            f"Deidentification complete: {processed} processed, {failed} failed",
        )

        return {
            'processed': processed,
            'failed': failed,
            'job_id': job.id,
        }

    except SoftTimeLimitExceeded:
        logger.warning("Soft time limit exceeded for deidentification task — auto-continuing")
        if task_run:
            _auto_continue_task(
                task_run, deidentify_dicom_study_task,
                [study_id], {'user_id': user_id},
                reason="approaching soft time limit",
            )
        return {'status': 'auto_continued'}

    except Exception as e:
        logger.error(f"Deidentification task failed: {e}", exc_info=True)
        if task_run:
            _fail_task_run(task_run, str(e))
        raise


@shared_task(bind=True, soft_time_limit=3600)
def deidentify_dicom_studies_bulk_task(self, study_ids, user_id=None):
    progress_recorder = ProgressRecorder(self)
    task_run = None
    manifest_path = None

    try:
        manifest_path = manifest_path_for_task(self.request.id, 'DEIDENTIFICATION')
        task_run = _create_task_run(
            task_name='deidentify_dicom_studies_bulk',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            user_id=user_id,
            celery_task_id=self.request.id,
            manifest_path=manifest_path,
            task_args=self.request.args,
            task_kwargs=self.request.kwargs,
        )

        completed_items = read_manifest(manifest_path)
        total = len(study_ids)
        results = []

        for idx, study_id in enumerate(study_ids, 1):
            if f"study:{study_id}" in completed_items:
                logger.info(f"Skipping already-completed study {study_id}")
                results.append({'study_id': study_id, 'status': 'skipped'})
                continue

            _update_task_run(
                task_run, progress_recorder, idx, total,
                description=f"Processing study {idx}/{total}",
                throttle_key=self.request.id,
            )

            try:
                study = DICOMStudy.objects.get(study_instance_uid=study_id)
                job = DeidentificationJob.objects.create(
                    study=study,
                    status=DeidentificationJob.Status.PENDING,
                    task_run=task_run,
                )

                def progress_callback(phase, current, total):
                    _update_task_run(
                        task_run, progress_recorder, current, total,
                        description=f"{phase} — {current}/{total}",
                        throttle_key=self.request.id,
                    )

                def manifest_write_callback(item_id):
                    if item_id not in completed_items:
                        write_manifest_entry(manifest_path, item_id)
                        completed_items.add(item_id)

                processed, failed = deidentify_study(
                    study, job, progress_callback, manifest_write_callback,
                    completed_items=completed_items,
                )

                write_manifest_entry(manifest_path, f"study:{study_id}")
                completed_items.add(f"study:{study_id}")

                results.append({
                    'study_id': study_id,
                    'processed': processed,
                    'failed': failed,
                    'job_id': job.id,
                })

            except Exception as e:
                logger.error(f"Failed to deidentify study {study_id}: {e}", exc_info=True)
                results.append({'study_id': study_id, 'error': str(e)})

        cleanup_manifest(manifest_path)

        total_processed = sum(r.get('processed', 0) for r in results)
        total_failed = sum(r.get('failed', 0) for r in results)
        has_errors = any('error' in r for r in results)

        if total_failed > 0 or has_errors:
            error_lines = []
            error_lines.append(f"Deidentification completed with issues: {total_processed} processed, {total_failed} failed")
            error_lines.append("")
            for r in results:
                if 'error' in r:
                    error_lines.append(f"  • Study {r['study_id'][:60]}: {r['error']}")
                elif r.get('failed', 0) > 0:
                    error_lines.append(f"  • Study {r['study_id'][:60]}: {r['failed']} file(s) failed during processing")
            summary = "\n".join(error_lines)
            if task_run:
                task_run.status = TaskRun.Status.FAILURE
                task_run.error_log = summary
                task_run.completed_at = timezone.now()
                task_run.save(update_fields=['status', 'error_log', 'completed_at', 'updated_at'])
                if task_run.user:
                    from client_app.models import Notification
                    Notification.objects.create(
                        user=task_run.user,
                        notification_type=Notification.NotificationType.TASK_FAILED,
                        title=f"Task completed with issues: {task_run.task_name}",
                        message=summary,
                        task_run=task_run,
                    )
        else:
            _complete_task_run(task_run, f"Bulk deidentification complete: {total_processed} files processed across {len(results)} studies")

        return {'results': results}

    except SoftTimeLimitExceeded:
        logger.warning("Soft time limit exceeded for bulk deidentification — auto-continuing")
        if task_run:
            _auto_continue_task(
                task_run, deidentify_dicom_studies_bulk_task,
                [study_ids], {'user_id': user_id},
                reason="approaching soft time limit",
            )
        return {'status': 'auto_continued'}

    except Exception as e:
        logger.error(f"Bulk deidentification task failed: {e}", exc_info=True)
        if task_run:
            _fail_task_run(task_run, str(e))
        raise


@shared_task(bind=True, soft_time_limit=600)
def import_legacy_mapping_task(self, db_path, key_path, user_id=None):
    progress_recorder = ProgressRecorder(self)
    task_run = None

    try:
        manifest_path = manifest_path_for_task(self.request.id, 'DEIDENTIFICATION')

        task_run = _create_task_run(
            task_name='import_legacy_mapping',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            user_id=user_id,
            celery_task_id=self.request.id,
            manifest_path=manifest_path,
            task_args=self.request.args,
            task_kwargs=self.request.kwargs,
        )

        _update_task_run(task_run, progress_recorder, 0, 1, 'Starting legacy import...')

        from deidentification.services.legacy_import import import_legacy_mappings
        result = import_legacy_mappings(db_path, key_path, progress_callback=lambda current, total, desc: _update_task_run(
            task_run, progress_recorder, current, total, desc, throttle_key=self.request.id,
        ))

        _complete_task_run(task_run, result)
        return {'result': result}

    except Exception as e:
        logger.error(f"Legacy import task failed: {e}", exc_info=True)
        if task_run:
            _fail_task_run(task_run, str(e))
        raise
    finally:
        # Clean up temporary uploaded files
        for path in [db_path, key_path]:
            try:
                if path and os.path.exists(path):
                    os.unlink(path)
            except Exception as cleanup_err:
                logger.warning(f"Failed to clean up temp file {path}: {cleanup_err}")


@shared_task(bind=True, soft_time_limit=3600)
def build_dicom_download_zip_task(self, patient_ids, user_id=None):
    """Build a ZIP of deidentified DICOM files for the given patient IDs in the background."""
    import hashlib
    import tempfile
    import zipfile as _zipfile
    from django.conf import settings as _settings
    from deidentification.models import DeidPatient

    progress_recorder = ProgressRecorder(self)
    task_run = None

    try:
        task_run = _create_task_run(
            task_name='build_dicom_download_zip',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            user_id=user_id,
            celery_task_id=self.request.id,
            task_args=self.request.args,
            task_kwargs=self.request.kwargs,
        )

        from client_app.models import Patient
        patients = list(Patient.objects.filter(patient_id__in=patient_ids)) if patient_ids else list(Patient.objects.all())

        total = len(patients)
        _update_task_run(task_run, progress_recorder, 0, total, 'Starting DICOM ZIP build...')

        output_base = os.path.join(_settings.MEDIA_ROOT, 'deidentification', 'output')
        zip_dir = os.path.join(_settings.MEDIA_ROOT, 'deidentification', 'downloads')
        os.makedirs(zip_dir, exist_ok=True)

        zip_path = os.path.join(zip_dir, f"deidentified_dicom_{self.request.id}.zip")
        file_count = 0

        with _zipfile.ZipFile(zip_path, 'w', _zipfile.ZIP_DEFLATED) as zf:
            for idx, patient in enumerate(patients, 1):
                deid_patient = DeidPatient.objects.filter(patient=patient).first()
                if not deid_patient:
                    continue

                patient_hash = hashlib.sha256(str(patient.patient_id).encode()).hexdigest()[:16]
                patient_folder = f"patient_{patient_hash}"

                deid_patient_dir = os.path.join(output_base, deid_patient.deidentified_patient_id)
                if os.path.isdir(deid_patient_dir):
                    for deid_study in deid_patient.deid_studies.all():
                        study_dir = os.path.join(deid_patient_dir, deid_study.deidentified_study_instance_uid)
                        if not os.path.isdir(study_dir):
                            continue
                        for filename in os.listdir(study_dir):
                            if filename.endswith('.dcm'):
                                file_path = os.path.join(study_dir, filename)
                                arcname = f"{patient_folder}/dicom/{deid_study.deidentified_study_instance_uid}/{filename}"
                                zf.write(file_path, arcname)
                                file_count += 1

                _update_task_run(task_run, progress_recorder, idx, total, f"Packed patient {idx}/{total}")

        result = {
            'zip_path': os.path.relpath(zip_path, _settings.MEDIA_ROOT),
            'file_count': file_count,
            'patient_count': total,
        }
        _complete_task_run(task_run, result)
        return result

    except SoftTimeLimitExceeded:
        logger.warning("Soft time limit exceeded for DICOM ZIP build — task may be incomplete")
        if task_run:
            _fail_task_run(task_run, "ZIP build timed out — too many files")
        raise

    except Exception as e:
        logger.error(f"DICOM ZIP build failed: {e}", exc_info=True)
        if task_run:
            _fail_task_run(task_run, str(e))
        raise


@shared_task(bind=True, soft_time_limit=1800)
def build_clinical_download_zip_task(self, patient_ids, user_id=None):
    """Build a ZIP of deidentified clinical JSON files for the given patient IDs in the background."""
    import hashlib
    import json as _json
    import tempfile
    import zipfile as _zipfile
    from django.conf import settings as _settings
    from client_app.services.patient_data_export import UUIDEncoder

    progress_recorder = ProgressRecorder(self)
    task_run = None

    try:
        task_run = _create_task_run(
            task_name='build_clinical_download_zip',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            user_id=user_id,
            celery_task_id=self.request.id,
            task_args=self.request.args,
            task_kwargs=self.request.kwargs,
        )

        from client_app.models import Patient
        from deidentification.models import DeidPatient
        from deidentification.services.clinical_data_deidentification import deidentify_clinical_data

        patients = list(Patient.objects.filter(patient_id__in=patient_ids)) if patient_ids else list(Patient.objects.all())

        total = len(patients)
        _update_task_run(task_run, progress_recorder, 0, total, 'Starting clinical ZIP build...')

        zip_dir = os.path.join(_settings.MEDIA_ROOT, 'deidentification', 'downloads')
        os.makedirs(zip_dir, exist_ok=True)

        zip_path = os.path.join(zip_dir, f"deidentified_clinical_{self.request.id}.zip")
        included_count = 0

        with _zipfile.ZipFile(zip_path, 'w', _zipfile.ZIP_DEFLATED) as zf:
            for idx, patient in enumerate(patients, 1):
                deid_patient = DeidPatient.objects.filter(patient=patient).first()
                if not deid_patient:
                    continue

                from deidentification.views import _serialize_patient_clinical_data
                from django.test import RequestFactory
                factory = RequestFactory()
                dummy_request = factory.get('/')

                patient_data = _serialize_patient_clinical_data(patient, dummy_request)
                try:
                    deidentified_clinical = deidentify_clinical_data(patient, patient_data)
                except ValueError as e:
                    logger.warning(f"Skipping clinical data for {patient.patient_id}: {e}")
                    continue

                patient_hash = hashlib.sha256(str(patient.patient_id).encode()).hexdigest()[:16]
                json_filename = f"patient_{patient_hash}_clinical_data.json"
                clinical_json = _json.dumps(deidentified_clinical, indent=2, cls=UUIDEncoder)
                zf.writestr(json_filename, clinical_json)
                included_count += 1

                _update_task_run(task_run, progress_recorder, idx, total, f"Processed patient {idx}/{total}")

        result = {
            'zip_path': os.path.relpath(zip_path, _settings.MEDIA_ROOT),
            'patient_count': included_count,
        }
        _complete_task_run(task_run, result)
        return result

    except SoftTimeLimitExceeded:
        logger.warning("Soft time limit exceeded for clinical ZIP build — task may be incomplete")
        if task_run:
            _fail_task_run(task_run, "ZIP build timed out")
        raise

    except Exception as e:
        logger.error(f"Clinical ZIP build failed: {e}", exc_info=True)
        if task_run:
            _fail_task_run(task_run, str(e))
        raise
