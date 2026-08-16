import logging
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import pydicom
from django.conf import settings
from django.utils import timezone

from client_app.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance
from deidentification.models import (
    DeidPatient, DeidStudy, DeidSeries, DeidInstance,
    DeidentificationJob, PixelRedactionLog,
)
from deidentification.services.patient_deidentification import deidentify_patient_data
from deidentification.services.study_deidentification import deidentify_study_data
from deidentification.services.series_deidentification import deidentify_series_data
from deidentification.services.instance_deidentification import deidentify_instance_data
from deidentification.services.referenced_sop_mapping import get_sop_instance_mapping
from deidentification.services.referenced_for_mapping import get_frame_of_reference_mapping
from deidentification.utils.date_replacement import deidentify_dates
from deidentification.utils.name_replacement import deidentify_names
from deidentification.utils.address_phone_replacement import deidentify_address_phone
from deidentification.utils.tag_replacement import deidentify_tags
from deidentification.utils.phi_scrubbing import scrub_phi_patterns
from deidentification.utils.referenced_sop_instance_replacement import replace_referenced_sop_instances
from deidentification.utils.referenced_frame_of_reference_replacement import replace_referenced_frame_of_reference
from deidentification.utils.burnt_in_pixel_scrubbing import scrub_burnt_in_pixels

logger = logging.getLogger(__name__)

DEFAULT_SUB_BATCH_SIZE = 50


def _read_dicom(file_path: str, stop_before_pixels: bool = False) -> pydicom.Dataset:
    try:
        return pydicom.dcmread(file_path, stop_before_pixels=stop_before_pixels)
    except Exception:
        return pydicom.dcmread(file_path, force=True, stop_before_pixels=stop_before_pixels)


def _validate_required_attrs(dcm: pydicom.Dataset):
    required = ['PatientID', 'StudyInstanceUID', 'SeriesInstanceUID']
    missing = [attr for attr in required if not hasattr(dcm, attr)]
    if missing:
        raise ValueError(f"DICOM file missing essential attributes: {', '.join(missing)}")


def _enumerate_dicom_files(folder_path: str) -> List[Path]:
    p = Path(folder_path)
    if not p.exists():
        raise FileNotFoundError(f"Study folder does not exist: {folder_path}")
    files = [f for f in p.rglob('*') if f.is_file()]
    files.sort()
    return files


def pass0_extract_metadata(study: DICOMStudy, progress_callback=None) -> int:
    folder_path = study.folder_path
    if not folder_path:
        raise ValueError(
            f"Study {study.study_instance_uid} has no DICOM files (folder_path is empty). "
            f"This study was likely imported from legacy data without uploading the actual DICOM files. "
            f"Please upload the DICOM files for this study before attempting deidentification."
        )

    files = _enumerate_dicom_files(folder_path)
    total = len(files)
    count = 0

    for idx, file_path in enumerate(files, 1):
        if progress_callback:
            progress_callback("Pass 0: Extracting metadata", idx, total)

        try:
            dcm = _read_dicom(str(file_path), stop_before_pixels=True)
            _validate_required_attrs(dcm)

            series_uid = getattr(dcm, 'SeriesInstanceUID', '')
            sop_uid = getattr(dcm, 'SOPInstanceUID', '')
            if not series_uid or not sop_uid:
                continue

            series_date_str = getattr(dcm, 'SeriesDate', '')
            if not series_date_str:
                series_date_str = getattr(dcm, 'StudyDate', '')

            series_date = None
            if series_date_str:
                try:
                    series_date = datetime.strptime(series_date_str, "%Y%m%d").date()
                except ValueError:
                    pass

            modality = getattr(dcm, 'Modality', '')
            frame_of_ref = getattr(dcm, 'FrameOfReferenceUID', None)

            dicom_series, _ = DICOMSeries.objects.get_or_create(
                series_instance_uid=series_uid,
                defaults={
                    'study': study,
                    'series_date': series_date,
                    'modality': modality,
                    'frame_of_reference_uid': frame_of_ref,
                },
            )

            DICOMInstance.objects.get_or_create(
                sop_instance_uid=sop_uid,
                defaults={'series': dicom_series},
            )

            count += 1
        except Exception as e:
            logger.warning(f"Pass 0: Failed to extract metadata from {file_path}: {e}")
            continue

    logger.info(f"Pass 0 complete: extracted {count}/{total} files for study {study.study_instance_uid[:30]}...")
    return count


def pass1_generate_mappings(study: DICOMStudy, progress_callback=None) -> int:
    folder_path = study.folder_path
    files = _enumerate_dicom_files(folder_path)
    total = len(files)
    count = 0

    for idx, file_path in enumerate(files, 1):
        if progress_callback:
            progress_callback("Pass 1: Building mappings", idx, total)

        try:
            dcm = _read_dicom(str(file_path), stop_before_pixels=True)
            _validate_required_attrs(dcm)

            patient_id = getattr(dcm, 'PatientID', '')
            birth_date = getattr(dcm, 'PatientBirthDate', '')
            age = getattr(dcm, 'PatientAge', '')
            study_uid = getattr(dcm, 'StudyInstanceUID', '')
            study_date = getattr(dcm, 'StudyDate', '')
            series_uid = getattr(dcm, 'SeriesInstanceUID', '')
            sop_uid = getattr(dcm, 'SOPInstanceUID', '')

            if not all([patient_id, study_uid, series_uid, sop_uid]):
                raise ValueError("Missing required DICOM fields")

            patient = Patient.objects.filter(patient_id=patient_id).first()
            if not patient:
                raise ValueError(f"Patient {patient_id} not found in database")

            deid_patient_id, deid_dob, days_shift = deidentify_patient_data(
                patient, birth_date, study_date, age
            )

            deid_patient = DeidPatient.objects.get(patient=patient)

            deid_study_uid, deid_study_date = deidentify_study_data(
                deid_patient, study, study_date, days_shift
            )

            deid_study = DeidStudy.objects.get(study=study)

            dicom_series = DICOMSeries.objects.filter(
                study=study, series_instance_uid=series_uid
            ).first()
            if not dicom_series:
                raise ValueError(f"DICOMSeries not found for series {series_uid}")

            deid_series_uid, deid_series_date, deid_frame_uid = deidentify_series_data(
                deid_study, dicom_series, days_shift
            )

            deid_series = DeidSeries.objects.get(series=dicom_series)

            dicom_instance = DICOMInstance.objects.filter(
                series=dicom_series, sop_instance_uid=sop_uid
            ).first()
            if not dicom_instance:
                raise ValueError(f"DICOMInstance not found for SOP {sop_uid}")

            deidentify_instance_data(deid_series, dicom_instance)

            count += 1
        except Exception as e:
            logger.error(f"Pass 1: Failed for {file_path}: {e}")
            continue

    logger.info(f"Pass 1 complete: built mappings for {count}/{total} files")
    return count


def _group_files_by_series(
    files: List[Path], study: DICOMStudy
) -> Dict[str, List[Path]]:
    groups = defaultdict(list)
    for f in files:
        try:
            dcm = _read_dicom(str(f), stop_before_pixels=True)
            series_uid = getattr(dcm, 'SeriesInstanceUID', '')
            if series_uid:
                groups[series_uid].append(f)
        except Exception:
            logger.warning(f"Could not read series UID from {f}")
    return dict(groups)


def _deidentify_single_file(
    dcm: pydicom.Dataset,
    deid_patient: DeidPatient,
    deid_study: DeidStudy,
    deid_series: DeidSeries,
    deid_instance: DeidInstance,
    uid_mapping: Dict[str, str],
    for_mapping: Dict[str, str],
    modality: str,
) -> Optional[dict]:
    deid_patient_id = deid_patient.deidentified_patient_id
    deid_dob = deid_patient.deidentified_date_of_birth
    deid_study_uid = deid_study.deidentified_study_instance_uid
    deid_study_date = deid_study.deidentified_study_date
    deid_series_uid = deid_series.deidentified_series_instance_uid
    deid_series_date = deid_series.deidentified_series_date
    deid_frame_uid = deid_series.deidentified_frame_of_reference_uid
    deid_sop_uid = deid_instance.deidentified_sop_instance_uid
    days_shifted = deid_patient.date_shift_value

    bboxes = None

    try:
        dcm, bboxes = scrub_burnt_in_pixels(dcm, modality=modality)
    except Exception as e:
        logger.error(f"Burnt-in pixel scrubbing failed: {e}")
        raise

    try:
        dcm.remove_private_tags()
    except Exception as e:
        logger.warning(f"Failed to remove private tags: {e}")
        raise

    if not replace_referenced_sop_instances(dcm, uid_mapping):
        raise RuntimeError("Failed to replace referenced SOP instances")

    if not replace_referenced_frame_of_reference(dcm, for_mapping):
        raise RuntimeError("Failed to replace referenced Frame of Reference UIDs")

    if not deidentify_dates(dcm, days_shifted):
        raise RuntimeError("Failed to shift dates")

    if not deidentify_names(dcm):
        raise RuntimeError("Failed to anonymize names")

    if not deidentify_address_phone(dcm):
        raise RuntimeError("Failed to anonymize address/phone")

    if not deidentify_tags(dcm):
        raise RuntimeError("Failed to replace device/procedure/free-text tags")

    dcm.PatientID = deid_patient_id
    dcm.PatientBirthDate = deid_dob
    dcm.StudyInstanceUID = deid_study_uid
    dcm.StudyDate = deid_study_date
    dcm.SeriesInstanceUID = deid_series_uid
    if deid_series_date:
        dcm.SeriesDate = deid_series_date
    dcm.SOPInstanceUID = deid_sop_uid
    dcm.file_meta.MediaStorageSOPInstanceUID = deid_sop_uid

    if hasattr(dcm, 'StudyID'):
        dcm.StudyID = "123456789"
    dcm.AccessionNumber = "123456789101112"

    if hasattr(dcm, 'FrameOfReferenceUID') and deid_frame_uid:
        dcm.FrameOfReferenceUID = deid_frame_uid

    if not hasattr(dcm.file_meta, 'TransferSyntaxUID'):
        dcm.file_meta.TransferSyntaxUID = '1.2.840.10008.1.2'

    if hasattr(dcm, 'BurnedInAnnotation'):
        dcm.BurnedInAnnotation = 'NO'

    return {'dcm': dcm, 'bboxes': bboxes, 'deid_sop_uid': deid_sop_uid, 'modality': modality}


def pass2_deidentify_files(
    study: DICOMStudy,
    job: DeidentificationJob,
    output_base: str,
    progress_callback=None,
    manifest_write_callback=None,
    completed_items=None,
) -> Tuple[int, int]:
    if completed_items is None:
        completed_items = set()
    folder_path = study.folder_path
    files = _enumerate_dicom_files(folder_path)
    total = len(files)

    patient = study.patient
    deid_patient = DeidPatient.objects.get(patient=patient)
    deid_study = DeidStudy.objects.get(study=study)

    uid_mapping = get_sop_instance_mapping(deid_patient)
    for_mapping = get_frame_of_reference_mapping(deid_patient)

    series_groups = _group_files_by_series(files, study)

    processed_count = 0
    failed_count = 0
    failed_series_count = 0
    global_idx = 0

    sub_batch_size = getattr(settings, 'DEID_SUB_BATCH_SIZE', DEFAULT_SUB_BATCH_SIZE)
    log_bboxes = getattr(settings, 'DEID_LOG_PIXEL_REDACTION_BBOXES', True)

    for series_uid, series_files in series_groups.items():
        series_failed = False
        deidentified_results = []

        series_key = f"series:{series_uid}"
        if series_key in completed_items:
            logger.info(f"Pass 2: Series {series_uid} already complete — skipping")
            processed_count += len(series_files)
            continue

        dicom_series = DICOMSeries.objects.filter(
            study=study, series_instance_uid=series_uid
        ).first()
        if not dicom_series:
            logger.error(f"Pass 2: DICOMSeries not found for {series_uid}")
            failed_series_count += 1
            failed_count += len(series_files)
            continue

        deid_series = DeidSeries.objects.filter(series=dicom_series).first()
        if not deid_series:
            logger.error(f"Pass 2: DeidSeries not found for {series_uid}")
            failed_series_count += 1
            failed_count += len(series_files)
            continue

        modality = dicom_series.modality

        for batch_start in range(0, len(series_files), sub_batch_size):
            batch_key = f"series:{series_uid}:batch:{batch_start}"
            if batch_key in completed_items:
                logger.info(f"Pass 2: Sub-batch {batch_key} already complete — skipping")
                processed_count += len(series_files[batch_start:batch_start + sub_batch_size])
                global_idx += len(series_files[batch_start:batch_start + sub_batch_size])
                continue

            batch = series_files[batch_start:batch_start + sub_batch_size]

            for file_path in batch:
                global_idx += 1
                if progress_callback:
                    progress_callback("Pass 2: Deidentifying", global_idx, total)

                try:
                    dcm = _read_dicom(str(file_path))
                    _validate_required_attrs(dcm)

                    sop_uid = getattr(dcm, 'SOPInstanceUID', '')
                    dicom_instance = DICOMInstance.objects.filter(
                        series=dicom_series, sop_instance_uid=sop_uid
                    ).first()
                    if not dicom_instance:
                        raise ValueError(f"DICOMInstance not found for SOP {sop_uid}")

                    deid_instance = DeidInstance.objects.get(instance=dicom_instance)

                    result = _deidentify_single_file(
                        dcm, deid_patient, deid_study, deid_series,
                        deid_instance, uid_mapping, for_mapping, modality,
                    )
                    if result:
                        deidentified_results.append(result)
                        processed_count += 1
                    else:
                        raise RuntimeError("Deidentification returned None")

                except Exception as e:
                    logger.error(f"Pass 2: Failed on {file_path} (series {series_uid}): {e}")
                    series_failed = True
                    failed_count += 1
                    break

            if series_failed:
                break

            if manifest_write_callback:
                manifest_write_callback(f"series:{series_uid}:batch:{batch_start}")

        if series_failed:
            logger.warning(f"Pass 2: Series {series_uid} failed — skipping all files")
            failed_series_count += 1
            deidentified_results = []
            continue

        for result in deidentified_results:
            dcm = result['dcm']
            deid_sop_uid = result['deid_sop_uid']
            file_modality = result['modality']

            output_path = os.path.join(
                output_base,
                deid_patient.deidentified_patient_id,
                deid_study.deidentified_study_instance_uid,
                f"{deid_sop_uid}-{file_modality}.dcm",
            )
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            dcm.save_as(output_path, enforce_file_format=True)

            if log_bboxes and result.get('bboxes'):
                PixelRedactionLog.objects.create(
                    job=job,
                    file_path=output_path,
                    bboxes=result['bboxes'],
                )

        if manifest_write_callback:
            manifest_write_callback(f"series:{series_uid}")

        logger.info(f"Pass 2: Series {series_uid} written ({len(deidentified_results)} files)")

    logger.info(f"Pass 2 complete: processed={processed_count}, failed={failed_count}, failed_series={failed_series_count}")
    return processed_count, failed_count


def deidentify_study(
    study: DICOMStudy,
    job: DeidentificationJob,
    progress_callback=None,
    manifest_write_callback=None,
    completed_items=None,
) -> Tuple[int, int]:
    job.status = DeidentificationJob.Status.PROCESSING
    job.save(update_fields=['status', 'updated_at'])

    try:
        pass0_extract_metadata(study, progress_callback)
        pass1_generate_mappings(study, progress_callback)

        output_base = os.path.join(
            settings.MEDIA_ROOT, 'deidentification', 'output'
        )
        job.output_path = os.path.join('deidentification', 'output')
        job.save(update_fields=['output_path', 'updated_at'])

        processed, failed = pass2_deidentify_files(
            study, job, output_base, progress_callback, manifest_write_callback,
            completed_items=completed_items,
        )

        job.processed_count = processed
        job.failed_count = failed
        job.total_file_count = processed + failed

        if failed == 0:
            job.status = DeidentificationJob.Status.SUCCESS
        elif processed > 0:
            job.status = DeidentificationJob.Status.PARTIAL
        else:
            job.status = DeidentificationJob.Status.FAILURE

        job.completed_at = timezone.now()
        job.save(update_fields=[
            'processed_count', 'failed_count', 'total_file_count',
            'status', 'completed_at', 'updated_at',
        ])

        return processed, failed

    except Exception as e:
        logger.error(f"Deidentification failed for study {study.study_instance_uid}: {e}", exc_info=True)
        job.status = DeidentificationJob.Status.FAILURE
        job.error_log = str(e)
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'error_log', 'completed_at', 'updated_at'])
        raise
