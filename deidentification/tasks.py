import logging
import os
import time as _time
from pathlib import Path

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery_progress.backend import ProgressRecorder
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from client_app.models import DICOMStudy, TaskRun, Notification
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


# ---------------------------------------------------------------------------
# Serial per-study deidentification
#
# The bulk entry point is only a dispatcher: it stores the study roster on a
# parent TaskRun and dispatches one small Celery task per study. Each link
# records its outcome on the parent run, then dispatches the next link — so no
# single task runs longer than one study, per-study failures are captured in
# between, and a hard-killed link is redelivered and resumed from its on-disk
# manifest without losing the rest of the batch.
#
# A self-perpetuating chain is used instead of celery.chain so broker messages
# stay small no matter how many studies are queued.
# ---------------------------------------------------------------------------

_DEID_TERMINAL_STATUSES = (
    TaskRun.Status.SUCCESS,
    TaskRun.Status.FAILURE,
    TaskRun.Status.CANCELLED,
)


def _deid_run_study_ids(parent_run):
    """Read the study roster off the parent TaskRun's stored dispatch args."""
    try:
        return list(parent_run.task_args[0] or [])
    except (TypeError, IndexError):
        return []


def _deid_record_result(run_id, index, entry):
    """Replace-not-append a per-study outcome on the parent TaskRun, so a
    redelivered link never duplicates its entry. Returns completed count."""
    parent = TaskRun.objects.filter(task_id=run_id).first()
    if not parent:
        return 0
    summary = parent.result_summary if isinstance(parent.result_summary, dict) else {}
    results = dict(summary.get('results') or {})
    results[str(index)] = entry
    summary['results'] = results
    parent.result_summary = summary
    parent.save(update_fields=['result_summary', 'updated_at'])
    return len(results)


def _deid_dispatch_next(run_id, index, total, user_id):
    """Advance the serial chain: dispatch the next study link, or finalize."""
    try:
        if index + 1 < total:
            deidentify_dicom_study_task.delay(run_id, index + 1, user_id=user_id)
        else:
            finalize_deidentification_batch_task.delay(run_id)
    except Exception as e:
        logger.error(
            f"Deid chain broken at index {index}: dispatch failed: {e}",
            exc_info=True,
        )
        parent = TaskRun.objects.filter(task_id=run_id).first()
        if parent and parent.status not in _DEID_TERMINAL_STATUSES:
            _fail_task_run(
                parent,
                f"Dispatch failed after study {index + 1}/{total}: {e}. "
                f"Resume this task to continue from where it stopped.",
            )


@shared_task(bind=True)
def deidentify_dicom_studies_bulk_task(self, study_ids, user_id=None):
    """Dispatcher: creates the parent TaskRun and kicks off the first
    per-study link. Idempotent — on resume it skips ahead to the first study
    with no recorded result."""
    progress_recorder = ProgressRecorder(self)
    task_run = None

    try:
        task_run = _create_task_run(
            task_name='deidentify_dicom_studies_bulk',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            user_id=user_id,
            celery_task_id=self.request.id,
            task_args=self.request.args,
            task_kwargs=self.request.kwargs,
        )

        total = len(study_ids)
        summary = task_run.result_summary if isinstance(task_run.result_summary, dict) else {}
        results = summary.get('results') or {}
        if 'results' not in summary:
            summary['results'] = {}
            task_run.result_summary = summary
            task_run.save(update_fields=['result_summary', 'updated_at'])

        next_index = next((i for i in range(total) if str(i) not in results), None)

        _update_task_run(
            task_run, progress_recorder, len(results), total,
            description=f"Dispatching deidentification for {total} studies",
            throttle_key=self.request.id,
        )

        if next_index is None:
            finalize_deidentification_batch_task.delay(self.request.id)
        else:
            deidentify_dicom_study_task.delay(self.request.id, next_index, user_id=user_id)

        return {'status': 'dispatched', 'run_id': self.request.id, 'total': total}

    except Exception as e:
        logger.error(f"Deidentification dispatcher failed: {e}", exc_info=True)
        if task_run:
            _fail_task_run(task_run, str(e))
        raise


# Keep the soft limit below the global CELERY_TASK_TIME_LIMIT (3600s hard
# kill) so the auto-continue handler actually gets a window to run.
@shared_task(bind=True, soft_time_limit=3300)
def deidentify_dicom_study_task(self, run_id, index, user_id=None):
    """Serial chain link: deidentify ONE study, record the outcome on the
    parent TaskRun, then dispatch the next link (or the finalize task).

    Never propagates per-study errors — a failure is recorded on the parent
    run and on this link's own TaskRun, then the chain advances. Hitting the
    soft time limit redispatches THIS link via auto-continue; the manifest is
    keyed on the stable (run_id, index) pair so the continuation resumes
    mid-study, and the next study is dispatched only after this one finishes —
    keeping the batch strictly serial.
    """
    close_old_connections()

    progress_recorder = ProgressRecorder(self)
    parent = TaskRun.objects.filter(task_id=run_id).first()
    if parent is None:
        logger.error(f"Deid link {index}: parent TaskRun {run_id} not found — aborting")
        return {'status': 'aborted', 'reason': 'parent task run missing'}

    study_ids = _deid_run_study_ids(parent)
    total = len(study_ids)
    if index >= total:
        return {'status': 'skipped', 'reason': 'index out of range'}

    study_id = study_ids[index]
    manifest_path = manifest_path_for_task(f"{run_id}-deid-{index}", 'DEIDENTIFICATION')
    child_run = _create_task_run(
        task_name='deidentify_dicom_study',
        task_type=TaskRun.TaskType.DEIDENTIFICATION,
        user_id=user_id,
        celery_task_id=self.request.id,
        manifest_path=manifest_path,
        task_args=self.request.args,
        task_kwargs=self.request.kwargs,
    )

    summary = parent.result_summary if isinstance(parent.result_summary, dict) else {}
    results = summary.get('results') or {}
    if str(index) in results or parent.status in _DEID_TERMINAL_STATUSES:
        # Another execution of this link already finished it (or the batch is
        # over) — don't reprocess, don't spawn a duplicate chain.
        child_run.status = TaskRun.Status.SUCCESS
        child_run.completed_at = timezone.now()
        child_run.result_summary = {'skipped': 'already recorded or batch finished'}
        child_run.save(update_fields=[
            'status', 'completed_at', 'result_summary', 'updated_at',
        ])
        return {'status': 'skipped', 'reason': 'already recorded'}

    _last_parent_write = [0.0]

    def parent_progress(cur, desc, force=False):
        """Mirror study-level progress onto the parent TaskRun (throttled) and
        under the parent's celery-progress key so its progress page works."""
        now = _time.time()
        if not force and now - _last_parent_write[0] < 2.0:
            return
        _last_parent_write[0] = now
        _update_task_run(parent, None, cur, total, description=desc)
        try:
            percent = round(cur * 100.0 / total, 2) if total else 0
            self.update_state(task_id=run_id, state='PROGRESS', meta={
                'pending': False, 'current': cur, 'total': total,
                'percent': percent, 'description': desc,
            })
        except Exception:
            pass

    try:
        study = DICOMStudy.objects.get(study_instance_uid=study_id)
        job, _ = DeidentificationJob.objects.get_or_create(
            study=study,
            task_run=child_run,
            defaults={'status': DeidentificationJob.Status.PENDING},
        )

        completed_items = read_manifest(manifest_path)

        def progress_callback(phase, cur, tot):
            _update_task_run(
                child_run, progress_recorder, cur, tot,
                description=f"{phase} — {cur}/{tot}",
                throttle_key=self.request.id,
            )
            parent_progress(
                len(results),
                f"[{index + 1}/{total}] Study {study_id[:40]} — {phase} {cur}/{tot}",
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

        entry = {
            'index': index,
            'study_id': study_id,
            'processed': processed,
            'failed': failed,
            'job_id': job.id,
        }
        done_count = _deid_record_result(run_id, index, entry)

        if failed == 0:
            child_run.status = TaskRun.Status.SUCCESS
            child_run.completed_at = timezone.now()
            child_run.result_summary = {
                'processed': processed, 'failed': failed, 'job_id': job.id,
            }
            child_run.save(update_fields=[
                'status', 'completed_at', 'result_summary', 'updated_at',
            ])
        else:
            # Per-study failure is surfaced but does not stop the batch.
            _fail_task_run(
                child_run,
                f"{failed} file(s) failed during deidentification",
            )

        parent_progress(done_count, f"Completed study {index + 1}/{total}", force=True)
        _deid_dispatch_next(run_id, index, total, user_id)
        return entry

    except SoftTimeLimitExceeded:
        logger.warning(
            f"Deid link {index} approaching soft time limit — auto-continuing"
        )
        new_result = _auto_continue_task(
            child_run, deidentify_dicom_study_task,
            [run_id, index], {'user_id': user_id},
            reason="approaching soft time limit",
        )
        if new_result is None:
            # Auto-continue cap hit — record the failure and move on.
            _deid_record_result(run_id, index, {
                'index': index, 'study_id': study_id,
                'error': 'auto-continue attempts exhausted',
                'processed': 0, 'failed': 0,
            })
            _deid_dispatch_next(run_id, index, total, user_id)
        return {'status': 'auto_continued'}

    except Exception as e:
        logger.error(
            f"Deid link {index} failed for study {study_id}: {e}", exc_info=True
        )
        try:
            _deid_record_result(run_id, index, {
                'index': index, 'study_id': study_id, 'error': str(e),
                'processed': 0, 'failed': 0,
            })
        except Exception:
            logger.error("Failed to record deid result on parent run", exc_info=True)
        if child_run:
            _fail_task_run(child_run, str(e))
        _deid_dispatch_next(run_id, index, total, user_id)
        return {'status': 'failed', 'error': str(e)}


@shared_task(bind=True)
def finalize_deidentification_batch_task(self, run_id):
    """Last step of the serial chain: aggregate the per-study results recorded
    on the parent TaskRun into the final verdict + notification, and clean up
    any leftover batch manifests."""
    parent = TaskRun.objects.filter(task_id=run_id).first()
    if parent is None:
        logger.error(f"Finalize deid batch: parent TaskRun {run_id} not found")
        return {'status': 'aborted', 'reason': 'parent task run missing'}

    summary = parent.result_summary if isinstance(parent.result_summary, dict) else {}
    results_map = summary.get('results') or {}
    results = [results_map[k] for k in sorted(results_map, key=lambda x: int(x))]

    total_processed = sum(r.get('processed', 0) for r in results)
    total_failed = sum(r.get('failed', 0) for r in results)
    has_errors = any('error' in r for r in results)

    if total_failed > 0 or has_errors:
        error_lines = [
            f"Deidentification completed with issues: {total_processed} processed, {total_failed} failed",
            "",
        ]
        for r in results:
            if 'error' in r:
                error_lines.append(f"  • Study {r['study_id'][:60]}: {r['error']}")
            elif r.get('failed', 0) > 0:
                error_lines.append(f"  • Study {r['study_id'][:60]}: {r['failed']} file(s) failed during processing")
        summary['message'] = "\n".join(error_lines)
        parent.result_summary = summary
        parent.status = TaskRun.Status.FAILURE
        parent.error_log = summary['message']
        parent.completed_at = timezone.now()
        parent.save(update_fields=[
            'status', 'error_log', 'result_summary', 'completed_at', 'updated_at',
        ])
        if parent.user:
            Notification.objects.create(
                user=parent.user,
                notification_type=Notification.NotificationType.TASK_FAILED,
                title=f"Task completed with issues: {parent.task_name}",
                message=summary['message'],
                task_run=parent,
            )
    else:
        summary['message'] = (
            f"Bulk deidentification complete: {total_processed} files "
            f"processed across {len(results)} studies"
        )
        _complete_task_run(parent, summary)

    # Links mirror progress under the parent's celery-progress key — write the
    # terminal state so the progress page stops polling.
    try:
        self.update_state(
            task_id=run_id,
            state='FAILURE' if (total_failed > 0 or has_errors) else 'SUCCESS',
            meta=summary['message'],
        )
    except Exception:
        pass

    manifest_dir = Path(settings.MEDIA_ROOT) / 'task_manifests'
    if manifest_dir.exists():
        for f in manifest_dir.glob(f"{run_id}-deid-*.jsonl"):
            try:
                f.unlink()
            except OSError:
                pass

    return {'results': results}


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
def build_dicom_download_zip_task(self, patient_ids, user_id=None, job_id=None):
    """Build a ZIP of deidentified DICOM files for the given patient IDs in the background."""
    import tempfile
    import zipfile as _zipfile
    from django.conf import settings as _settings
    from deidentification.models import DeidPatient, DeidentificationJob

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

        # If job_id is provided, only include files from that job's study
        job_study_uid = None
        if job_id:
            job = DeidentificationJob.objects.filter(id=job_id).select_related('study').first()
            if job and job.study:
                from deidentification.models import DeidStudy
                deid_study = DeidStudy.objects.filter(study=job.study).first()
                if deid_study:
                    job_study_uid = deid_study.deidentified_study_instance_uid

        with _zipfile.ZipFile(zip_path, 'w', _zipfile.ZIP_DEFLATED) as zf:
            for idx, patient in enumerate(patients, 1):
                deid_patient = DeidPatient.objects.filter(patient=patient).first()
                if not deid_patient:
                    continue

                deid_patient_dir = os.path.join(output_base, deid_patient.deidentified_patient_id)
                if os.path.isdir(deid_patient_dir):
                    for deid_study in deid_patient.deid_studies.all():
                        # If job_id is set, skip studies not belonging to this job
                        if job_study_uid and deid_study.deidentified_study_instance_uid != job_study_uid:
                            continue
                        study_dir = os.path.join(deid_patient_dir, deid_study.deidentified_study_instance_uid)
                        if not os.path.isdir(study_dir):
                            continue
                        for filename in os.listdir(study_dir):
                            if filename.endswith('.dcm'):
                                file_path = os.path.join(study_dir, filename)
                                arcname = f"{deid_patient.deidentified_patient_id}/dicom/{deid_study.deidentified_study_instance_uid}/{filename}"
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

                patient_folder = deid_patient.deidentified_patient_id
                json_filename = f"{patient_folder}_clinical_data.json"
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


@shared_task(bind=True, soft_time_limit=1800)
def create_missing_records_task(self, records, user_id=None):
    """Asynchronously create missing Patient/Study/Series/Instance records
    from unmatched legacy import data.

    ``records`` is a list of dicts with keys like:
        type, original_id, date_of_birth, parent_patient_id,
        deidentified_date, parent_study_uid, deidentified_series_date, etc.
    """
    from datetime import datetime
    from client_app.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance
    from deidentification.models import DeidStudy, DeidSeries, DeidInstance

    progress_recorder = ProgressRecorder(self)
    task_run = None

    try:
        task_run = _create_task_run(
            task_name='create_missing_records',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            user_id=user_id,
            celery_task_id=self.request.id,
            task_args=self.request.args,
            task_kwargs=self.request.kwargs,
        )

        def _parse_date(val):
            if not val or not str(val).strip():
                return None
            val = str(val).strip()
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d', '%d-%m-%Y'):
                try:
                    return datetime.strptime(val, fmt).date()
                except (ValueError, TypeError):
                    continue
            return None

        type_order = {'patient': 0, 'study': 1, 'series': 2, 'instance': 3}
        records.sort(key=lambda r: type_order.get(r.get('type', ''), 9))

        total = len(records)
        created = []
        errors = []
        skipped = []

        for idx, rec in enumerate(records, 1):
            rtype = rec.get('type', '')
            try:
                if rtype == 'patient':
                    pid = rec.get('original_id', '').strip()
                    if not pid or pid == '__orphan__':
                        errors.append({'id': pid, 'error': 'patient_id required'})
                        continue
                    if Patient.objects.filter(patient_id=pid).exists():
                        skipped.append({'type': 'patient', 'id': pid, 'reason': 'already exists'})
                        continue
                    dob = _parse_date(rec.get('date_of_birth', ''))
                    Patient.objects.create(patient_id=pid, date_of_birth=dob)
                    created.append({'type': 'patient', 'id': pid})

                elif rtype == 'study':
                    study_uid = rec.get('original_id', '').strip()
                    patient_id = rec.get('parent_patient_id', '').strip()
                    if not study_uid or not patient_id or patient_id == '__orphan__':
                        errors.append({'id': study_uid, 'error': 'study_instance_uid and parent_patient_id required'})
                        continue
                    patient = Patient.objects.filter(patient_id=patient_id).first()
                    if not patient:
                        patient = Patient.objects.create(patient_id=patient_id, date_of_birth=None)
                        created.append({'type': 'patient', 'id': patient_id, 'auto': True})
                    if DICOMStudy.objects.filter(study_instance_uid=study_uid).exists():
                        skipped.append({'type': 'study', 'id': study_uid, 'reason': 'already exists'})
                        continue
                    study_date = _parse_date(rec.get('deidentified_date', ''))
                    DICOMStudy.objects.create(
                        study_instance_uid=study_uid, patient=patient, study_date=study_date,
                    )
                    created.append({'type': 'study', 'id': study_uid})

                elif rtype == 'series':
                    series_uid = rec.get('original_id', '').strip()
                    study_uid = rec.get('parent_study_uid', '').strip()
                    if not series_uid or not study_uid:
                        errors.append({'id': series_uid, 'error': 'series_instance_uid and parent_study_uid required'})
                        continue
                    study = DICOMStudy.objects.filter(study_instance_uid=study_uid).first()
                    if not study:
                        errors.append({'id': series_uid, 'error': f'Study {study_uid} not found'})
                        continue
                    if DICOMSeries.objects.filter(series_instance_uid=series_uid).exists():
                        skipped.append({'type': 'series', 'id': series_uid, 'reason': 'already exists'})
                        continue
                    modality = rec.get('modality', 'CT') or 'CT'
                    series_date = _parse_date(rec.get('deidentified_series_date', ''))
                    frame_uid = rec.get('deidentified_frame_of_reference_uid', '').strip() or None
                    series = DICOMSeries.objects.create(
                        study=study, series_instance_uid=series_uid,
                        modality=modality, series_date=series_date,
                        frame_of_reference_uid=frame_uid,
                    )
                    deid_series_uid = rec.get('deidentified_id', '').strip()
                    if deid_series_uid:
                        deid_study = DeidStudy.objects.filter(study=study).first()
                        if deid_study:
                            DeidSeries.objects.update_or_create(
                                series=series,
                                defaults={
                                    'deid_study': deid_study,
                                    'deidentified_series_instance_uid': deid_series_uid,
                                    'deidentified_series_date': series_date,
                                    'deidentified_frame_of_reference_uid': frame_uid,
                                },
                            )
                    created.append({'type': 'series', 'id': series_uid})

                elif rtype == 'instance':
                    sop_uid = rec.get('original_id', '').strip()
                    series_uid = rec.get('parent_series_uid', '').strip()
                    if not sop_uid or not series_uid:
                        errors.append({'id': sop_uid, 'error': 'sop_instance_uid and parent_series_uid required'})
                        continue
                    series = DICOMSeries.objects.filter(series_instance_uid=series_uid).first()
                    if not series:
                        errors.append({'id': sop_uid, 'error': f'Series {series_uid} not found'})
                        continue
                    if DICOMInstance.objects.filter(sop_instance_uid=sop_uid).exists():
                        skipped.append({'type': 'instance', 'id': sop_uid, 'reason': 'already exists'})
                        continue
                    instance = DICOMInstance.objects.create(series=series, sop_instance_uid=sop_uid)
                    deid_sop_uid = rec.get('deidentified_id', '').strip()
                    if deid_sop_uid:
                        deid_series = DeidSeries.objects.filter(series=series).first()
                        if deid_series:
                            DeidInstance.objects.update_or_create(
                                instance=instance,
                                defaults={
                                    'deid_series': deid_series,
                                    'deidentified_sop_instance_uid': deid_sop_uid,
                                },
                            )
                    created.append({'type': 'instance', 'id': sop_uid})

            except Exception as e:
                errors.append({'id': rec.get('original_id', ''), 'error': str(e)})

            if idx % 10 == 0 or idx == total:
                _update_task_run(
                    task_run, progress_recorder, idx, total,
                    f"Creating records {idx}/{total}",
                    throttle_key=self.request.id,
                )

        result = {
            'created_count': len(created),
            'skipped_count': len(skipped),
            'error_count': len(errors),
            'created': created,
            'skipped': skipped,
            'errors': errors,
        }
        _complete_task_run(task_run, result)
        return result

    except Exception as e:
        logger.error(f"Create missing records task failed: {e}", exc_info=True)
        if task_run:
            _fail_task_run(task_run, str(e))
        raise
