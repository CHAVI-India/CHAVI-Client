"""
Celery tasks for asynchronous processing of services.
Each task wraps the core logic from the corresponding service module,
using celery-progress for progress tracking.
"""
import os
import zipfile
import tempfile
import shutil
import hashlib
import json
import io
import logging
import uuid
from pathlib import Path
from datetime import datetime

from celery import shared_task
from celery_progress.backend import ProgressRecorder
from django.conf import settings
from django.utils import timezone
from pydicom import dcmread

from .models import (
    Patient, DICOMStudy, DICOMStudyProject, Project,
    PatientDicomFile, UnprocessedDICOMStudies,
    BulkDICOMUpload, BulkDICOMUploadSession, BulkDICOMStudyMatch,
    _make_canonical_id,
)
from .serializers import *
from .services.patient_data_export import UUIDEncoder, export_patient_data_to_file
from .services.parallel_dicom_export import sanitize_filename, process_study_files
from .services.dicom_data_export import sanitize_filename as dicom_export_sanitize

logger = logging.getLogger(__name__)


def _sanitize(path):
    """Sanitize path by replacing invalid characters."""
    return path.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')


# ---------------------------------------------------------------------------
# 1. Associate DICOM files to project
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_associate_dicom_to_project(self, dicom_study_ids, project_id, user_id):
    """Associate selected DICOM studies with a project."""
    progress = ProgressRecorder(self)
    total = len(dicom_study_ids)
    project = Project.objects.get(chavi_project_id=project_id)
    associations_created = 0
    errors = []

    for i, study_id in enumerate(dicom_study_ids):
        try:
            dicom_study = DICOMStudy.objects.get(pk=study_id)
            association, created = DICOMStudyProject.objects.get_or_create(
                study_instance_uid=dicom_study,
                project=project
            )
            if created:
                associations_created += 1
                logger.info(f"Created association between DICOM study {dicom_study} and project {project}")
        except Exception as e:
            logger.error(f"Error creating association: {str(e)}")
            errors.append(f"Study {study_id}: {str(e)}")

        progress.set_progress(i + 1, total, description=f"Associating study {i + 1} of {total}")

    return {
        'associations_created': associations_created,
        'errors': errors,
        'project_name': project.project_name,
    }


# ---------------------------------------------------------------------------
# 2. Process bulk DICOM import
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_process_bulk_dicom(self, upload_ids, user_id):
    """Process uploaded zip files containing DICOM studies from multiple patients."""
    progress = ProgressRecorder(self)
    total = len(upload_ids)

    processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
    unprocessed_dir = Path(settings.MEDIA_ROOT) / 'Unprocessed_DICOM'
    processed_dir.mkdir(parents=True, exist_ok=True)
    unprocessed_dir.mkdir(parents=True, exist_ok=True)

    overall_processed = 0
    overall_unprocessed = 0
    overall_errors = []

    for idx, upload_id in enumerate(upload_ids):
        try:
            upload = BulkDICOMUpload.objects.get(id=upload_id)
        except BulkDICOMUpload.DoesNotExist:
            overall_errors.append(f"Upload {upload_id} not found")
            progress.set_progress(idx + 1, total, description=f"Upload {idx + 1} of {total} not found")
            continue

        if hasattr(upload, 'status') and upload.status == 'Processed':
            progress.set_progress(idx + 1, total, description=f"Upload {idx + 1} already processed")
            continue

        temp_dir = None
        try:
            temp_dir = Path(tempfile.mkdtemp())
            with zipfile.ZipFile(upload.file.path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            dicom_files = [f for f in temp_dir.glob('**/*') if f.is_file()]
            processed_count = 0
            unprocessed_count = 0
            unmatched_patients = set()
            study_data = {}
            unprocessed_study_folders = {}

            for file_path in dicom_files:
                try:
                    ds = dcmread(file_path)
                    patient_id = ds.PatientID
                    sanitized_patient_id = _sanitize(patient_id)
                    study_instance_uid = ds.StudyInstanceUID
                    sop_instance_uid = ds.SOPInstanceUID

                    if study_instance_uid not in study_data:
                        study_data[study_instance_uid] = {
                            'patient_id': patient_id,
                            'series_descriptions': set(),
                            'modalities': set(),
                            'study_description': None,
                            'study_date': None
                        }

                    if hasattr(ds, 'Modality') and ds.Modality:
                        study_data[study_instance_uid]['modalities'].add(ds.Modality)
                    if hasattr(ds, 'StudyDescription') and ds.StudyDescription:
                        study_data[study_instance_uid]['study_description'] = ds.StudyDescription
                    if hasattr(ds, 'SeriesDescription') and ds.SeriesDescription:
                        study_data[study_instance_uid]['series_descriptions'].add(ds.SeriesDescription)
                    if hasattr(ds, 'StudyDate') and ds.StudyDate:
                        try:
                            study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                            study_data[study_instance_uid]['study_date'] = study_date
                        except ValueError:
                            pass

                    try:
                        patient = Patient.objects.get(patient_id=patient_id)
                        patient_dir = processed_dir / sanitized_patient_id
                        study_dir = patient_dir / _sanitize(study_instance_uid)
                        study_dir.mkdir(parents=True, exist_ok=True)
                        ds.save_as(study_dir / f"{_sanitize(sop_instance_uid)}.dcm", enforce_file_format=True)
                        processed_count += 1
                    except Patient.DoesNotExist:
                        unprocessed_patient_dir = unprocessed_dir / sanitized_patient_id / _sanitize(study_instance_uid)
                        unprocessed_patient_dir.mkdir(parents=True, exist_ok=True)
                        ds.save_as(unprocessed_patient_dir / f"{_sanitize(sop_instance_uid)}.dcm")
                        unprocessed_count += 1
                        unmatched_patients.add(patient_id)
                        unprocessed_study_folders[study_instance_uid] = str(unprocessed_patient_dir)

                except Exception as e:
                    overall_errors.append(f"Error processing file {file_path.name}: {str(e)}")
                    continue

            for study_uid, data in study_data.items():
                try:
                    patient_id = data['patient_id']
                    try:
                        patient = Patient.objects.get(patient_id=patient_id)
                        series_desc_string = ', '.join(sorted(data['series_descriptions'])) if data['series_descriptions'] else ''
                        modalities_string = ', '.join(sorted(data['modalities'])) if data['modalities'] else ''
                        DICOMStudy.objects.update_or_create(
                            patient=patient,
                            study_instance_uid=study_uid,
                            defaults={
                                'study_description': data['study_description'],
                                'study_date': data['study_date'],
                                'series_descriptions': series_desc_string,
                                'study_modalities': modalities_string,
                                'folder_path': str(study_dir.absolute())
                            }
                        )
                    except Patient.DoesNotExist:
                        if study_uid in unprocessed_study_folders:
                            UnprocessedDICOMStudies.objects.update_or_create(
                                study_instance_uid=study_uid,
                                defaults={
                                    'dicom_patient_id': patient_id,
                                    'patient_id': None,
                                    'folder_path': unprocessed_study_folders[study_uid],
                                    'status': 'Unprocessed'
                                }
                            )
                        continue
                except Exception as e:
                    overall_errors.append(f"Error updating study {study_uid}: {str(e)}")
                    continue

            upload.status = 'Processed'
            upload.processed_at = timezone.now()
            upload.save()

            overall_processed += processed_count
            overall_unprocessed += unprocessed_count

        except Exception as e:
            overall_errors.append(f"Error processing upload {upload_id}: {str(e)}")
        finally:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir)

        progress.set_progress(idx + 1, total, description=f"Processed upload {idx + 1} of {total}")

    return {
        'processed': overall_processed,
        'unprocessed': overall_unprocessed,
        'errors': overall_errors,
    }


# ---------------------------------------------------------------------------
# 3. Export DICOM data (admin action)
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_export_dicom_data(self, study_ids, user_id):
    """Export DICOM data into a single zip file."""
    progress = ProgressRecorder(self)
    total = len(study_ids)

    temp_dir = Path(settings.MEDIA_ROOT) / 'temp_export'
    temp_dir.mkdir(exist_ok=True)
    zip_path = temp_dir / f'dicom_export_{self.request.id}.zip'

    processed_studies = 0
    skipped_studies = 0
    total_files = 0

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as zipf:
            for i, study_id in enumerate(study_ids):
                try:
                    study = DICOMStudy.objects.get(pk=study_id)
                except DICOMStudy.DoesNotExist:
                    skipped_studies += 1
                    progress.set_progress(i + 1, total, description=f"Study {i + 1} not found, skipping")
                    continue

                if not study.folder_path or not os.path.exists(study.folder_path):
                    skipped_studies += 1
                    progress.set_progress(i + 1, total, description=f"Study {i + 1} has no valid folder, skipping")
                    continue

                study_path = Path(study.folder_path)
                if not study_path.exists():
                    skipped_studies += 1
                    progress.set_progress(i + 1, total, description=f"Study {i + 1} folder missing, skipping")
                    continue

                try:
                    for file_path in study_path.rglob('*'):
                        if file_path.is_file():
                            try:
                                rel_path = file_path.relative_to(study_path)
                                sanitized_patient_id = dicom_export_sanitize(study.patient.patient_id)
                                arcname = f"{sanitized_patient_id}/{study.study_instance_uid}/{rel_path}"
                                zipf.write(file_path, arcname)
                                total_files += 1
                            except Exception as e:
                                logger.error(f"Error adding file {file_path} to zip: {str(e)}")
                                continue
                    processed_studies += 1
                except Exception as e:
                    logger.error(f"Error processing study {study.study_instance_uid}: {str(e)}")
                    skipped_studies += 1

                progress.set_progress(i + 1, total, description=f"Exporting study {i + 1} of {total}")

        if processed_studies == 0:
            return {'success': False, 'message': 'No valid DICOM studies were found to export.'}

        return {
            'success': True,
            'zip_path': str(zip_path),
            'zip_filename': zip_path.name,
            'processed_studies': processed_studies,
            'skipped_studies': skipped_studies,
            'total_files': total_files,
        }
    except Exception as e:
        logger.error(f"Error creating zip file: {str(e)}")
        return {'success': False, 'message': f'Error creating zip file: {str(e)}'}


# ---------------------------------------------------------------------------
# 4. Process DICOM import per patient
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_process_dicom_per_patient(self, patient_dicom_file_ids, user_id):
    """Process a single patient's DICOM zip file."""
    progress = ProgressRecorder(self)
    total = len(patient_dicom_file_ids)

    processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
    processed_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for idx, obj_id in enumerate(patient_dicom_file_ids):
        try:
            obj = PatientDicomFile.objects.get(id=obj_id)
        except PatientDicomFile.DoesNotExist:
            results.append({'id': obj_id, 'error': 'Not found'})
            progress.set_progress(idx + 1, total, description=f"File {idx + 1} not found")
            continue

        processing_stats = {
            'total_files': 0,
            'successful_files': 0,
            'failed_files': [],
            'successful_studies': 0,
            'failed_studies': []
        }

        if not obj.file:
            obj.processing_log = "Error: No file found"
            obj.processed = True
            obj.save()
            results.append({'id': obj_id, 'error': 'No file found'})
            progress.set_progress(idx + 1, total, description=f"File {idx + 1} has no file")
            continue

        temp_dir = Path(tempfile.mkdtemp())
        patient_id = obj.patient.patient_id
        patient_path = _sanitize(patient_id)
        save_path = processed_dir / patient_path
        save_path.mkdir(exist_ok=True, parents=True)

        study_uids = set()
        study_descriptions = {}
        study_dates = {}
        series_descriptions = {}
        modalities = {}

        try:
            with zipfile.ZipFile(obj.file.path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            dicom_files = [files for files in temp_dir.glob('**/*') if files.is_file()]
            processing_stats['total_files'] = len(dicom_files)

            for file in dicom_files:
                try:
                    ds = dcmread(file)
                    study_instance_uid = ds.StudyInstanceUID

                    if hasattr(ds, 'StudyDescription'):
                        study_descriptions[study_instance_uid] = ds.StudyDescription
                    if hasattr(ds, 'StudyDate') and ds.StudyDate:
                        try:
                            study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                            study_dates[study_instance_uid] = study_date
                        except ValueError:
                            pass
                    if hasattr(ds, 'SeriesDescription'):
                        if study_instance_uid not in series_descriptions:
                            series_descriptions[study_instance_uid] = set()
                        series_descriptions[study_instance_uid].add(ds.SeriesDescription)
                    if hasattr(ds, 'Modality'):
                        if study_instance_uid not in modalities:
                            modalities[study_instance_uid] = set()
                        modalities[study_instance_uid].add(ds.Modality)

                    sop_instance_uid = ds.SOPInstanceUID
                    folder_path = _sanitize(study_instance_uid)
                    file_path = _sanitize(sop_instance_uid)
                    ds.PatientID = patient_id

                    study_dir = Path(save_path) / folder_path
                    study_dir.mkdir(exist_ok=True, parents=True)
                    ds.save_as(study_dir / f"{file_path}.dcm", enforce_file_format=True)

                    study_uids.add(study_instance_uid)
                    processing_stats['successful_files'] += 1

                except Exception as e:
                    processing_stats['failed_files'].append(f"{file.name}: {str(e)}")
                    continue

            for uid in study_uids:
                try:
                    series_desc_string = ', '.join(sorted(series_descriptions.get(uid, []))) if uid in series_descriptions else ''
                    modalities_string = ', '.join(sorted(modalities.get(uid, []))) if uid in modalities else ''
                    DICOMStudy.objects.update_or_create(
                        patient=obj.patient,
                        study_instance_uid=uid,
                        defaults={
                            'study_description': study_descriptions.get(uid),
                            'study_date': study_dates.get(uid),
                            'series_descriptions': series_desc_string,
                            'study_modalities': modalities_string,
                            'folder_path': str(study_dir.absolute()),
                        }
                    )
                    processing_stats['successful_studies'] += 1
                except Exception as e:
                    processing_stats['failed_studies'].append(f"{uid}: {str(e)}")
                    continue

            log_parts = [
                f"Processing completed for {obj.patient.patient_id}\n",
                f"Total files processed: {processing_stats['total_files']}\n",
                f"Successfully processed files: {processing_stats['successful_files']}\n",
                f"Failed files: {len(processing_stats['failed_files'])}\n",
                f"Successfully processed studies: {processing_stats['successful_studies']}\n",
                f"Failed studies: {len(processing_stats['failed_studies'])}"
            ]
            if processing_stats['failed_files']:
                log_parts.append("\nFailed files details:")
                log_parts.extend(processing_stats['failed_files'])
            if processing_stats['failed_studies']:
                log_parts.append("\nFailed studies details:")
                log_parts.extend(processing_stats['failed_studies'])

            obj.processing_log = "\n".join(log_parts)
            obj.processed = True
            obj.save()
            results.append({'id': obj_id, 'success': True, 'studies': processing_stats['successful_studies']})

        except zipfile.BadZipFile:
            obj.processing_log = f"Error: Invalid zip file for {obj.patient.patient_id}"
            obj.processed = True
            obj.save()
            results.append({'id': obj_id, 'error': 'Invalid zip file'})
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

        progress.set_progress(idx + 1, total, description=f"Processed DICOM file {idx + 1} of {total}")

    return {'results': results}


# ---------------------------------------------------------------------------
# 5. Frontend bulk DICOM import: extract and analyze
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_extract_and_analyze_upload(self, session_id, user_id):
    """Extract uploaded zip file and analyze DICOM studies."""
    progress = ProgressRecorder(self)
    session = BulkDICOMUploadSession.objects.get(session_id=session_id)

    try:
        # Use a consistent 0-100 scale across all phases
        # Phase 1: Extract zip (0-5%)
        progress.set_progress(0, 100, description="Extracting zip file...")

        temp_dir = Path(tempfile.mkdtemp(prefix=f'bulk_dicom_{session_id}_'))
        session.temp_directory = str(temp_dir)
        session.status = BulkDICOMUploadSession.StatusChoices.EXTRACTED
        session.save()

        with zipfile.ZipFile(session.uploaded_file.path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        progress.set_progress(5, 100, description="Extracting zip file complete")

        # Phase 2: Read DICOM files (5-50%)
        dicom_files = [f for f in temp_dir.glob('**/*') if f.is_file()]
        total_files = len(dicom_files)
        study_data = {}

        for idx, file_path in enumerate(dicom_files):
            if idx % 10 == 0 or idx == total_files - 1:
                pct = 5 + int((idx + 1) / total_files * 45) if total_files > 0 else 50
                progress.set_progress(pct, 100, description=f"Reading DICOM file {idx + 1} of {total_files}...")
            try:
                ds = dcmread(file_path)
                patient_id = ds.PatientID
                study_instance_uid = ds.StudyInstanceUID

                if study_instance_uid not in study_data:
                    study_data[study_instance_uid] = {
                        'patient_id': patient_id,
                        'study_instance_uid': study_instance_uid,
                        'series_descriptions': set(),
                        'modalities': set(),
                        'study_description': None,
                        'study_date': None,
                        'file_count': 0,
                        'files': []
                    }

                if hasattr(ds, 'Modality') and ds.Modality:
                    study_data[study_instance_uid]['modalities'].add(ds.Modality)
                if hasattr(ds, 'StudyDescription') and ds.StudyDescription:
                    study_data[study_instance_uid]['study_description'] = ds.StudyDescription
                if hasattr(ds, 'SeriesDescription') and ds.SeriesDescription:
                    study_data[study_instance_uid]['series_descriptions'].add(ds.SeriesDescription)
                if hasattr(ds, 'StudyDate') and ds.StudyDate:
                    try:
                        study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                        study_data[study_instance_uid]['study_date'] = study_date
                    except ValueError:
                        pass

                study_data[study_instance_uid]['file_count'] += 1
                study_data[study_instance_uid]['files'].append(file_path)

            except Exception as e:
                logger.error(f"Error reading DICOM file {file_path}: {str(e)}")
                continue

        progress.set_progress(50, 100, description=f"Analyzing {len(study_data)} studies...")

        auto_matched = 0
        manual_required = 0
        total_studies = len(study_data)

        for i, (study_uid, data) in enumerate(study_data.items()):
            patient_id = data['patient_id']

            try:
                patient = Patient.objects.get(patient_id=patient_id)
                match_status = BulkDICOMStudyMatch.MatchStatus.AUTO_MATCHED
                matched_patient = patient
                auto_matched += 1
            except Patient.DoesNotExist:
                canonical_dicom = _make_canonical_id(patient_id)
                canonical_match = None
                for db_patient in Patient.objects.only('patient_id'):
                    canonical_db = _make_canonical_id(db_patient.patient_id)
                    if canonical_db == canonical_dicom or canonical_db.endswith(canonical_dicom):
                        canonical_match = db_patient
                        break
                if canonical_match:
                    match_status = BulkDICOMStudyMatch.MatchStatus.AUTO_MATCHED
                    matched_patient = canonical_match
                    auto_matched += 1
                else:
                    match_status = BulkDICOMStudyMatch.MatchStatus.MANUAL_MATCH_REQUIRED
                    matched_patient = None
                    manual_required += 1

            sanitized_patient_id = _sanitize(patient_id)
            study_temp_folder = temp_dir / sanitized_patient_id / _sanitize(study_uid)
            study_temp_folder.mkdir(parents=True, exist_ok=True)

            for file_path in data['files']:
                try:
                    ds = dcmread(file_path)
                    sop_instance_uid = ds.SOPInstanceUID
                    dest_path = study_temp_folder / f"{_sanitize(sop_instance_uid)}.dcm"
                    shutil.move(str(file_path), str(dest_path))
                except Exception as e:
                    logger.error(f"Error moving file {file_path}: {str(e)}")

            BulkDICOMStudyMatch.objects.create(
                session=session,
                study_instance_uid=study_uid,
                dicom_patient_id=patient_id,
                study_description=data['study_description'],
                study_date=data['study_date'],
                modalities=', '.join(sorted(data['modalities'])) if data['modalities'] else '',
                series_descriptions=', '.join(sorted(data['series_descriptions'])) if data['series_descriptions'] else '',
                file_count=data['file_count'],
                match_status=match_status,
                matched_patient=matched_patient,
                temp_folder_path=str(study_temp_folder)
            )

            pct = 50 + int((i + 1) / total_studies * 50) if total_studies > 0 else 100
            progress.set_progress(pct, 100, description=f"Analyzing study {i + 1} of {total_studies}")

        session.total_studies = len(study_data)
        session.auto_matched_studies = auto_matched
        session.manual_match_required = manual_required
        session.status = BulkDICOMUploadSession.StatusChoices.ANALYZED
        session.save()

        return {
            'success': True,
            'total_studies': len(study_data),
            'auto_matched': auto_matched,
            'manual_required': manual_required,
            'session_id': str(session.session_id),
        }

    except Exception as e:
        logger.error(f"Error during extraction and analysis: {str(e)}", exc_info=True)
        session.status = BulkDICOMUploadSession.StatusChoices.FAILED
        session.error_log = str(e)
        session.save()
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# 6. Frontend bulk DICOM import: process confirmed matches
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_process_confirmed_matches(self, session_id, user_id):
    """Process all confirmed study matches and move files to final locations."""
    progress = ProgressRecorder(self)
    session = BulkDICOMUploadSession.objects.get(session_id=session_id)

    try:
        session.status = BulkDICOMUploadSession.StatusChoices.PROCESSING
        session.save()

        processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
        unprocessed_dir = Path(settings.MEDIA_ROOT) / 'Unprocessed_DICOM'
        processed_dir.mkdir(parents=True, exist_ok=True)
        unprocessed_dir.mkdir(parents=True, exist_ok=True)

        study_matches = BulkDICOMStudyMatch.objects.filter(session=session)
        total_matches = study_matches.count()
        processed_count = 0
        unprocessed_count = 0
        error_count = 0

        for i, study_match in enumerate(study_matches):
            try:
                if study_match.match_status == BulkDICOMStudyMatch.MatchStatus.CONFIRMED and study_match.matched_patient:
                    patient = study_match.matched_patient
                    sanitized_patient_id = _sanitize(patient.patient_id)

                    patient_dir = processed_dir / sanitized_patient_id
                    study_dir = patient_dir / _sanitize(study_match.study_instance_uid)
                    study_dir.mkdir(parents=True, exist_ok=True)

                    is_manually_matched = (study_match.dicom_patient_id != patient.patient_id)

                    temp_folder = Path(study_match.temp_folder_path)
                    if temp_folder.exists():
                        for dicom_file in temp_folder.glob('*.dcm'):
                            dest_file = study_dir / dicom_file.name
                            if is_manually_matched:
                                try:
                                    ds = dcmread(str(dicom_file))
                                    ds.PatientID = patient.patient_id
                                    if hasattr(ds, 'PatientName'):
                                        ds.PatientName = patient.patient_id
                                    ds.save_as(str(dest_file), enforce_file_format=True)
                                except Exception as e:
                                    logger.error(f"Error modifying DICOM metadata for {dicom_file.name}: {str(e)}")
                                    shutil.copy2(str(dicom_file), str(dest_file))
                            else:
                                shutil.copy2(str(dicom_file), str(dest_file))

                    DICOMStudy.objects.update_or_create(
                        patient=patient,
                        study_instance_uid=study_match.study_instance_uid,
                        defaults={
                            'study_description': study_match.study_description,
                            'study_date': study_match.study_date,
                            'series_descriptions': study_match.series_descriptions,
                            'study_modalities': study_match.modalities,
                            'folder_path': str(study_dir.absolute())
                        }
                    )

                    study_match.match_status = BulkDICOMStudyMatch.MatchStatus.PROCESSED
                    study_match.final_folder_path = str(study_dir)
                    study_match.save()
                    processed_count += 1

                elif study_match.match_status == BulkDICOMStudyMatch.MatchStatus.UNMATCHED:
                    sanitized_patient_id = _sanitize(study_match.dicom_patient_id)
                    unprocessed_patient_dir = unprocessed_dir / sanitized_patient_id / _sanitize(study_match.study_instance_uid)
                    unprocessed_patient_dir.mkdir(parents=True, exist_ok=True)

                    temp_folder = Path(study_match.temp_folder_path)
                    if temp_folder.exists():
                        for dicom_file in temp_folder.glob('*.dcm'):
                            dest_file = unprocessed_patient_dir / dicom_file.name
                            shutil.copy2(str(dicom_file), str(dest_file))

                    UnprocessedDICOMStudies.objects.update_or_create(
                        study_instance_uid=study_match.study_instance_uid,
                        defaults={
                            'dicom_patient_id': study_match.dicom_patient_id,
                            'patient_id': None,
                            'folder_path': str(unprocessed_patient_dir),
                            'status': 'Unprocessed'
                        }
                    )

                    study_match.final_folder_path = str(unprocessed_patient_dir)
                    study_match.save()
                    unprocessed_count += 1

            except Exception as e:
                logger.error(f"Error processing study {study_match.study_instance_uid}: {str(e)}", exc_info=True)
                error_count += 1
                continue

            progress.set_progress(i + 1, total_matches, description=f"Processing match {i + 1} of {total_matches}")

        if session.temp_directory:
            temp_dir = Path(session.temp_directory)
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

        session.status = BulkDICOMUploadSession.StatusChoices.COMPLETED
        session.completed_at = timezone.now()
        session.save()

        return {
            'success': True,
            'processed': processed_count,
            'unprocessed': unprocessed_count,
            'errors': error_count,
            'session_id': str(session.session_id),
        }

    except Exception as e:
        logger.error(f"Error during processing: {str(e)}", exc_info=True)
        session.status = BulkDICOMUploadSession.StatusChoices.FAILED
        session.error_log = str(e)
        session.save()
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# 7. Parallel DICOM export (frontend view)
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_export_dicom_data_parallel(self, study_ids, task_id, include_patient_data=False, user_id=None):
    """Export DICOM data using multiprocessing with progress tracking via celery-progress."""
    progress = ProgressRecorder(self)
    from concurrent.futures import ThreadPoolExecutor

    temp_dir = Path(settings.MEDIA_ROOT) / 'temp_export'
    temp_dir.mkdir(exist_ok=True)

    zip_filename = f'dicom_export_{task_id}.zip'
    zip_path = temp_dir / zip_filename
    patient_zip_path = temp_dir / f'patient_data_{task_id}.zip'

    # Get study objects
    studies = DICOMStudy.objects.filter(pk__in=study_ids)
    total_studies = studies.count()

    # Get unique patients if patient data is requested
    patient_ids = set()
    if include_patient_data:
        for study in studies:
            if study.patient and study.patient.patient_id:
                patient_ids.add(study.patient.patient_id)

    # Prepare study data for multiprocessing
    study_data_list = []
    for study in studies:
        study_data_list.append({
            'study_uid': study.study_instance_uid,
            'folder_path': study.folder_path,
            'patient_id': study.patient.patient_id if study.patient else 'unknown'
        })

    # Phase 1: Process studies using threads (0-50% of progress)
    # ThreadPoolExecutor works inside Celery's daemonic worker processes
    processed_results = []

    progress.set_progress(0, total_studies, description="Starting parallel processing...")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_study_files, s) for s in study_data_list]
        for i, future in enumerate(futures):
            result = future.result()
            processed_results.append(result)
            progress.set_progress(i + 1, total_studies, description=f"Processing study {i + 1} of {total_studies}")

    # Phase 2: Export patient data if requested (50-60%)
    patient_data_result = None
    if include_patient_data and patient_ids:
        progress.set_progress(0, 2, description=f"Exporting patient data for {len(patient_ids)} patients...")
        patient_queryset = Patient.objects.filter(patient_id__in=patient_ids)
        patient_data_result = export_patient_data_to_file(patient_queryset, patient_zip_path)
        progress.set_progress(1, 2, description="Patient data export complete")

    # Phase 3: Create DICOM ZIP (60-100%)
    processed_studies = 0
    skipped_studies = 0
    total_files = 0
    error_messages = []

    dicom_zip_path = temp_dir / f'dicom_only_{task_id}.zip'
    total_results = len(processed_results)

    with zipfile.ZipFile(dicom_zip_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as zipf:
        for idx, result in enumerate(processed_results):
            if result['success']:
                for file_info in result['files']:
                    try:
                        zipf.write(file_info['file_path'], file_info['arcname'])
                        total_files += 1
                    except Exception as e:
                        logger.error(f"Error adding file to zip: {str(e)}")
                        continue
                processed_studies += 1
            else:
                skipped_studies += 1
                error_msg = f"Study {result['study_uid']}: {result.get('error', 'Unknown error')}"
                error_messages.append(error_msg)

            progress.set_progress(idx + 1, total_results, description=f"Zipping study {idx + 1} of {total_results}")

    if processed_studies == 0:
        return {
            'success': False,
            'message': 'No valid DICOM studies were found to export.'
        }

    # Rename to final path
    dicom_zip_path.rename(zip_path)

    if include_patient_data and patient_data_result and patient_data_result.get('success'):
        final_message = f'Export complete! {processed_studies} DICOM studies ({total_files} files), {patient_data_result.get("processed_patients", 0)} patient records.'
    else:
        final_message = f'Export complete! {processed_studies} studies, {total_files} files.'

    return_data = {
        'success': True,
        'message': final_message,
        'zip_path': str(zip_path),
        'zip_filename': zip_filename,
        'processed': processed_studies,
        'skipped': skipped_studies,
        'total_files': total_files,
        'include_patient_data': include_patient_data,
        'processed_patients': patient_data_result.get('processed_patients', 0) if patient_data_result else 0,
        'errors': error_messages[:10],
    }

    if include_patient_data and patient_data_result and patient_data_result.get('success'):
        return_data['patient_data_zip_path'] = str(patient_zip_path)
        return_data['patient_data_zip_filename'] = f'patient_data_{task_id}.zip'

    return return_data


# ---------------------------------------------------------------------------
# 8. Export patient data (admin action + frontend view)
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_export_patient_data(self, patient_ids, user_id):
    """Export patient data as individual JSON files within a zip archive."""
    progress = ProgressRecorder(self)

    temp_dir = Path(settings.MEDIA_ROOT) / 'temp_export'
    temp_dir.mkdir(exist_ok=True)
    zip_path = temp_dir / f'patient_data_export_{self.request.id}.zip'

    total = len(patient_ids)
    total_files = 0

    context = {}

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for i, patient_id in enumerate(patient_ids):
            try:
                patient = Patient.objects.get(patient_id=patient_id)
            except Patient.DoesNotExist:
                progress.set_progress(i + 1, total, description=f"Patient {i + 1} not found, skipping")
                continue

            patient_data = {
                'patients': [],
                'dicom_studies': [],
                'diagnoses': [],
                'outcomes': [],
                'lesions': [],
                'lesion_responses': [],
                'germline_genomic_alterations': [],
                'pathologies': [],
                'immunohistochemistries': [],
                'cytogenetics': [],
                'somatic_genomic_alterations': [],
                'gene_expression_data': [],
                'epigenetic_data': [],
                'other_treatments': [],
                'radiotherapies': [],
                'radiotherapy_volumes': [],
                'radiotherapy_dose_volume_data': [],
                'surgeries': [],
                'concomitant_medications': [],
                'systemic_therapies': [],
                'systemic_therapy_schedules': [],
                'adverse_effects': [],
                'pro_instruments': [],
                'pro_domains': [],
                'pro_questions': [],
                'patient_reported_outcomes': [],
                'patient_outcomes': [],
                'comorbidities': [],
                'stage_information': [],
                'laboratory_results': [],
                'symptoms': [],
                'patient_assessments': [],
                'dicom_study_projects': []
            }

            patient_data['patients'].append(PatientSerializer(patient, context=context).data)

            dicom_studies = DICOMStudy.objects.filter(patient=patient)
            patient_data['dicom_studies'].extend(DICOMStudySerializer(dicom_studies, many=True, context=context).data)

            dicom_study_projects = DICOMStudyProject.objects.filter(study_instance_uid__patient=patient)
            patient_data['dicom_study_projects'].extend(DICOMStudyProjectSerializer(dicom_study_projects, many=True, context=context).data)

            diagnoses = Diagnosis.objects.filter(patient=patient)
            patient_data['diagnoses'].extend(DiagnosisSerializer(diagnoses, many=True, context=context).data)

            for diagnosis in diagnoses:
                outcomes = Outcome.objects.filter(diagnosis=diagnosis)
                patient_data['outcomes'].extend(OutcomeSerializer(outcomes, many=True, context=context).data)

                lesions = Lesion.objects.filter(diagnosis=diagnosis)
                patient_data['lesions'].extend(LesionSerializer(lesions, many=True, context=context).data)

                for lesion in lesions:
                    lesion_responses = LesionResponse.objects.filter(lesion=lesion)
                    patient_data['lesion_responses'].extend(LesionResponseSerializer(lesion_responses, many=True, context=context).data)

                pathologies = Pathology.objects.filter(diagnosis=diagnosis)
                patient_data['pathologies'].extend(PathologySerializer(pathologies, many=True, context=context).data)

                for pathology in pathologies:
                    immunohistochemistries = Immunohistochemistry.objects.filter(pathology=pathology)
                    patient_data['immunohistochemistries'].extend(ImmunohistochemistrySerializer(immunohistochemistries, many=True, context=context).data)

                    cytogenetics = Cytogenetics.objects.filter(pathology=pathology)
                    patient_data['cytogenetics'].extend(CytogeneticsSerializer(cytogenetics, many=True, context=context).data)

                    genomic_alterations = SomaticGenomicAlterations.objects.filter(pathology=pathology)
                    patient_data['somatic_genomic_alterations'].extend(SomaticGenomicAlterationsSerializer(genomic_alterations, many=True, context=context).data)

                    gene_expression_data = GeneExpressionData.objects.filter(pathology=pathology)
                    patient_data['gene_expression_data'].extend(GeneExpressionDataSerializer(gene_expression_data, many=True, context=context).data)

                    epigenetic_data = EpigeneticData.objects.filter(pathology=pathology)
                    patient_data['epigenetic_data'].extend(EpigeneticDataSerializer(epigenetic_data, many=True, context=context).data)

                other_treatments = OtherTreatment.objects.filter(diagnosis=diagnosis)
                patient_data['other_treatments'].extend(OtherTreatmentSerializer(other_treatments, many=True, context=context).data)

                radiotherapies = Radiotherapy.objects.filter(diagnosis=diagnosis)
                patient_data['radiotherapies'].extend(RadiotherapySerializer(radiotherapies, many=True, context=context).data)

                for radiotherapy in radiotherapies:
                    rt_volumes = RadiotherapyVolume.objects.filter(radiotherapy=radiotherapy)
                    patient_data['radiotherapy_volumes'].extend(RadiotherapyVolumeSerializer(rt_volumes, many=True, context=context).data)

                    rt_dose_volumes = RadiotherapyDoseVolumeData.objects.filter(radiotherapy=radiotherapy)
                    patient_data['radiotherapy_dose_volume_data'].extend(RadiotherapyDoseVolumeDataSerializer(rt_dose_volumes, many=True, context=context).data)

                surgeries = Surgery.objects.filter(diagnosis=diagnosis)
                patient_data['surgeries'].extend(SurgerySerializer(surgeries, many=True, context=context).data)

                medications = ConcomitantMedications.objects.filter(diagnosis=diagnosis)
                patient_data['concomitant_medications'].extend(ConcomitantMedicationsSerializer(medications, many=True, context=context).data)

                systemic_therapies = SystemicTherapy.objects.filter(diagnosis=diagnosis)
                patient_data['systemic_therapies'].extend(SystemicTherapySerializer(systemic_therapies, many=True, context=context).data)

                for therapy in systemic_therapies:
                    schedules = SystemicTherapySchedule.objects.filter(systemic_therapy=therapy)
                    patient_data['systemic_therapy_schedules'].extend(SystemicTherapyScheduleSerializer(schedules, many=True, context=context).data)

                adverse_effects = AdverseEffects.objects.filter(diagnosis=diagnosis)
                patient_data['adverse_effects'].extend(AdverseEffectsSerializer(adverse_effects, many=True, context=context).data)

                stage_info = StageInformation.objects.filter(diagnosis=diagnosis)
                patient_data['stage_information'].extend(StageInformationSerializer(stage_info, many=True, context=context).data)

            patient_reported_outcomes = PatientReportedOutcome.objects.filter(patient=patient)
            patient_data['patient_reported_outcomes'].extend(PatientReportedOutcomeSerializer(patient_reported_outcomes, many=True, context=context).data)

            patient_outcomes = PatientOutcome.objects.filter(patient=patient)
            patient_data['patient_outcomes'].extend(PatientOutcomeSerializer(patient_outcomes, many=True, context=context).data)

            comorbidities = Comorbidity.objects.filter(patient=patient)
            patient_data['comorbidities'].extend(ComorbiditySerializer(comorbidities, many=True, context=context).data)

            genomic_alterations = GermlineGenomicAlterations.objects.filter(patient=patient)
            patient_data['germline_genomic_alterations'].extend(GermlineGenomicAlterationsSerializer(genomic_alterations, many=True, context=context).data)

            symptoms = Symptom.objects.filter(patient=patient)
            patient_data['symptoms'].extend(SymptomSerializer(symptoms, many=True, context=context).data)

            patient_assessments = PatientAssessment.objects.filter(patient=patient)
            patient_data['patient_assessments'].extend(PatientAssessmentSerializer(patient_assessments, many=True, context=context).data)

            lab_results = LaboratoryResults.objects.filter(patient=patient)
            patient_data['laboratory_results'].extend(LaboratoryResultsSerializer(lab_results, many=True, context=context).data)

            patient_json = json.dumps(patient_data, indent=2, cls=UUIDEncoder)
            patient_id_hash = hashlib.sha256(str(patient.patient_id).encode()).hexdigest()
            filename = f"patient_{patient_id_hash}_data.json"
            zip_file.writestr(filename, patient_json)
            total_files += 1

            progress.set_progress(i + 1, total, description=f"Exporting patient {i + 1} of {total}")

    return {
        'success': True,
        'zip_path': str(zip_path),
        'zip_filename': zip_path.name,
        'processed_patients': total_files,
    }


# ---------------------------------------------------------------------------
# 9. Process unprocessed DICOM studies
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def task_process_unprocessed_dicom(self, unprocessed_study_uids, user_id):
    """Process unprocessed DICOM studies."""
    progress = ProgressRecorder(self)
    total = len(unprocessed_study_uids)

    processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
    processed_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for idx, study_uid in enumerate(unprocessed_study_uids):
        try:
            obj = UnprocessedDICOMStudies.objects.get(study_instance_uid=study_uid)
        except UnprocessedDICOMStudies.DoesNotExist:
            results.append({'study_uid': study_uid, 'error': 'Not found'})
            progress.set_progress(idx + 1, total, description=f"Study {idx + 1} not found")
            continue

        if not obj.patient_id:
            results.append({'study_uid': study_uid, 'error': 'No associated patient'})
            progress.set_progress(idx + 1, total, description=f"Study {idx + 1} has no patient")
            continue

        if not obj.folder_path:
            results.append({'study_uid': study_uid, 'error': 'No folder path'})
            progress.set_progress(idx + 1, total, description=f"Study {idx + 1} has no folder")
            continue

        processing_stats = {
            'total_files': 0,
            'successful_files': 0,
            'failed_files': [],
            'successful_studies': 0,
            'failed_studies': []
        }

        try:
            patient_id = obj.patient_id.patient_id
            patient_path = _sanitize(patient_id)
            save_path = processed_dir / patient_path
            save_path.mkdir(exist_ok=True, parents=True)

            study_uids = set()
            study_descriptions = {}
            study_dates = {}
            series_descriptions = {}
            modalities = {}

            folder_path = Path(obj.folder_path)
            dicom_files = [file for file in folder_path.glob('**/*') if file.is_file()]
            processing_stats['total_files'] = len(dicom_files)

            for file in dicom_files:
                try:
                    ds = dcmread(file)
                    ds.PatientID = patient_id
                    study_instance_uid = ds.StudyInstanceUID

                    if hasattr(ds, 'StudyDescription'):
                        study_descriptions[study_instance_uid] = ds.StudyDescription
                    if hasattr(ds, 'StudyDate') and ds.StudyDate:
                        try:
                            study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                            study_dates[study_instance_uid] = study_date
                        except ValueError:
                            pass
                    if hasattr(ds, 'SeriesDescription'):
                        if study_instance_uid not in series_descriptions:
                            series_descriptions[study_instance_uid] = set()
                        series_descriptions[study_instance_uid].add(ds.SeriesDescription)
                    if hasattr(ds, 'Modality'):
                        if study_instance_uid not in modalities:
                            modalities[study_instance_uid] = set()
                        modalities[study_instance_uid].add(ds.Modality)

                    sop_instance_uid = ds.SOPInstanceUID
                    folder_path_sanitized = _sanitize(study_instance_uid)
                    file_path_sanitized = _sanitize(sop_instance_uid)

                    study_dir = Path(save_path) / folder_path_sanitized
                    study_dir.mkdir(exist_ok=True, parents=True)
                    ds.save_as(study_dir / f"{file_path_sanitized}.dcm")

                    study_uids.add(study_instance_uid)
                    processing_stats['successful_files'] += 1

                except Exception as e:
                    processing_stats['failed_files'].append(f"{file.name}: {str(e)}")
                    continue

            for uid in study_uids:
                try:
                    series_desc_string = ', '.join(sorted(series_descriptions.get(uid, []))) if uid in series_descriptions else ''
                    modalities_string = ', '.join(sorted(modalities.get(uid, []))) if uid in modalities else ''

                    DICOMStudy.objects.update_or_create(
                        patient=obj.patient_id,
                        study_instance_uid=uid,
                        defaults={
                            'study_description': study_descriptions.get(uid),
                            'study_date': study_dates.get(uid),
                            'series_descriptions': series_desc_string,
                            'study_modalities': modalities_string,
                            'folder_path': str(study_dir.absolute())
                        }
                    )
                    processing_stats['successful_studies'] += 1
                except Exception as e:
                    processing_stats['failed_studies'].append(f"{uid}: {str(e)}")
                    continue

            obj.status = "Processed"
            obj.save()
            results.append({'study_uid': study_uid, 'success': True, 'studies': processing_stats['successful_studies']})

        except Exception as e:
            results.append({'study_uid': study_uid, 'error': str(e)})

        progress.set_progress(idx + 1, total, description=f"Processing study {idx + 1} of {total}")

    return {'results': results}
