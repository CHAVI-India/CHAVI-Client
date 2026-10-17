"""Repair DICOMStudy.folder_path data and recover studies lost to 0034.

Background
----------
Migration 0034 recomputed each study's expected local folder as
``{MEDIA_ROOT}/processed_dicom/{sanitize(patient_id)}/{sanitize(study_uid)}``
and deleted any study whose folder was missing. That was wrong for
*archived* studies: archiving (dicom_archive.services.archive) moves the
folder out of processed_dicom WITHOUT updating folder_path, so the local
folder is missing by design and the data is safe in the archive
location. 0034 therefore deleted, for archived studies:

  * the DICOMStudy row and its DICOMSeries / DICOMInstance rows;
  * the ArchivedStudy record (OneToOneField on_delete=CASCADE);
  * M2M links from Diagnosis / Outcome / Lesion / LesionResponse /
    Radiotherapy / DICOMStudyProject (not recoverable from disk).

The archived files themselves survived: the post_delete receiver that
would also remove the archive copy (dicom_archive.signals.
study_deleted_receiver -> cleanup_study_files) only acts when an
ArchivedStudy record is still present, and the cascade removes it before
the signal fires.

This migration performs two operations (idempotent, safe to re-run):

1. verify_and_repair_local_studies
   For every study whose expected local folder EXISTS on disk, verify
   that the .dcm files inside carry this study's patient ID (every
   import path rewrites ds.PatientID to the database patient ID before
   saving, so a mismatch means the folder does not belong to this
   patient).
     - files match  -> folder_path is corrected to the expected path if
       it drifted;
     - files carry a different patient ID, are unreadable, or the folder
       has no .dcm files -> the study and its child rows are deleted.
       The files are left on disk untouched (they may belong to another
       patient and be their only copy).
   Studies without a local folder (including archived ones) are skipped
   here and handled by operation 2.

2. recover_archived_studies
   Scans every archive location on disk. For each
   ``<patient_segment>/<study_uid>`` folder found:
     - _archive_manifest.json provides patient_id, study_instance_uid,
       archived_at, size_bytes, instance_count;
     - the .dcm files provide study/series/instance metadata
       (descriptions, dates, modalities, series UIDs, SOP UIDs);
     - DICOMStudy.folder_path is set to the canonical local path
       (the value archiving never changed, so the row looks exactly as
       it did before 0034);
     - the ArchivedStudy record is recreated when missing, pointing at
       the archive folder actually found on disk.
   Studies whose manifest patient no longer exists, or whose study row
   survived under a DIFFERENT patient, are skipped and logged.

The post_delete file-cleanup receiver is disconnected while operation 1
deletes rows, so DB-only cleanup can never remove on-disk files.
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import migrations
from django.db.models.signals import post_delete
from django.utils import timezone

logger = logging.getLogger(__name__)

_SANITIZE_RE = re.compile(r'[/\\:*?"<>|]')
MANIFEST_NAME = '_archive_manifest.json'

# How many .dcm files to inspect when verifying PatientID inside a folder.
MAX_PATIENT_ID_CHECK_FILES = 50


def _sanitize(value):
    return _SANITIZE_RE.sub('_', str(value))


def _expected_folder_path(patient_id, study_instance_uid):
    return (
        Path(settings.MEDIA_ROOT)
        / 'processed_dicom'
        / _sanitize(patient_id)
        / _sanitize(study_instance_uid)
    )


def _resolve_location_path(location):
    """Mirror of dicom_archive.services.locations.resolve_location_path."""
    raw = (location.path or '').strip()
    if not raw:
        return None
    resolved = Path(raw).expanduser()
    if location.storage_type == 'MOUNT':
        return resolved if resolved.is_absolute() else None
    if not resolved.is_absolute():
        resolved = Path(settings.MEDIA_ROOT) / resolved
    return resolved


def _check_patient_ids(folder, expected_patient_id):
    """Verify the .dcm files in folder belong to expected_patient_id.

    Returns (verdict, detail) where verdict is 'ok', 'mismatch' or
    'empty'. At most MAX_PATIENT_ID_CHECK_FILES files are inspected.
    """
    files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == '.dcm'
    )
    if not files:
        return 'empty', 'no .dcm files in folder'
    from pydicom import dcmread
    for path in files[:MAX_PATIENT_ID_CHECK_FILES]:
        try:
            ds = dcmread(str(path), stop_before_pixels=True)
        except Exception as exc:
            return 'mismatch', f'unreadable file {path.name}: {exc}'
        actual = str(getattr(ds, 'PatientID', '') or '').strip()
        if actual != expected_patient_id:
            return (
                'mismatch',
                f'file {path.name} carries PatientID {actual!r}, '
                f'expected {expected_patient_id!r}',
            )
    return 'ok', f'{min(len(files), MAX_PATIENT_ID_CHECK_FILES)} files checked'


def _delete_study_rows(apps, study, reason):
    """Delete a study row and its child rows, never the on-disk files.

    The post_delete receiver (which deletes on-disk files) must already
    be disconnected by the caller. Returns (n_series, n_instances).
    """
    DICOMStudy = apps.get_model('client_app', 'DICOMStudy')
    DICOMSeries = apps.get_model('client_app', 'DICOMSeries')
    DICOMInstance = apps.get_model('client_app', 'DICOMInstance')
    study_uid = study.study_instance_uid  # pk is cleared by delete()
    n_instances, _ = (
        DICOMInstance.objects.filter(series__study=study).delete()
    )
    n_series, _ = DICOMSeries.objects.filter(study=study).delete()
    study.delete()
    logger.warning(
        '0035 verify: DELETED study %s (patient %s, folder_path=%r): %s. '
        'Removed %d series, %d instances. Files left on disk.',
        study_uid, study.patient_id,
        study.folder_path, reason, n_series, n_instances,
    )
    return n_series, n_instances


# ---------------------------------------------------------------------------
# Operation 1: verify local folders, fix drifted paths, delete mismatches
# ---------------------------------------------------------------------------

def verify_and_repair_local_studies(apps, schema_editor):
    DICOMStudy = apps.get_model('client_app', 'DICOMStudy')

    ok = fixed = deleted = no_local_folder = 0

    # DB-only deletion below must never trigger the on-disk file cleanup.
    from dicom_archive.signals import study_deleted_receiver
    post_delete.disconnect(study_deleted_receiver)
    try:
        for study in DICOMStudy.objects.iterator(chunk_size=500):
            expected = _expected_folder_path(
                study.patient_id, study.study_instance_uid
            )
            if not expected.is_dir():
                # No local files: archived (handled by operation 2) or
                # genuinely data-less (already dealt with by 0034).
                no_local_folder += 1
                continue
            verdict, detail = _check_patient_ids(expected, study.patient_id)
            if verdict == 'ok':
                ok += 1
                if study.folder_path != str(expected):
                    (DICOMStudy.objects
                     .filter(study_instance_uid=study.study_instance_uid)
                     .update(folder_path=str(expected)))
                    fixed += 1
                    logger.info(
                        '0035 verify: FIXED folder_path for study %s '
                        '(patient %s): %r -> %r (%s)',
                        study.study_instance_uid, study.patient_id,
                        study.folder_path, str(expected), detail,
                    )
                continue
            _delete_study_rows(
                apps,
                study,
                f'folder {expected} does not belong to this patient '
                f'({detail})',
            )
            deleted += 1
    finally:
        post_delete.connect(study_deleted_receiver)

    logger.info(
        '0035 verify pass complete: %d studies with a local folder '
        '(ok=%d, folder_path fixed=%d, deleted=%d), %d studies without a '
        'local folder skipped',
        ok + fixed + deleted, ok, fixed, deleted, no_local_folder,
    )


# ---------------------------------------------------------------------------
# Operation 2: recover archived studies from the archive folders on disk
# ---------------------------------------------------------------------------

def _parse_manifest(study_dir):
    manifest_path = study_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            '0035 recover: could not read manifest %s: %s',
            manifest_path, exc,
        )
        return None
    return data if isinstance(data, dict) else None


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _dicom_date(value):
    value = str(value or '')
    if len(value) == 8 and value.isdigit():
        try:
            return datetime.strptime(value, '%Y%m%d').date()
        except ValueError:
            return None
    return None


def _scan_study_files(study_dir):
    """Read the .dcm files and collect study/series/instance metadata."""
    from pydicom import dcmread

    dcm_files = sorted(
        p for p in study_dir.iterdir()
        if p.is_file() and p.suffix.lower() == '.dcm'
    )

    study_description = None
    study_date = None
    series_descriptions = set()
    modalities = set()
    series_info = {}      # series_uid -> {series_date, modality, frame}
    instances = []        # (series_uid, sop_uid), in file order
    unreadable = 0

    for path in dcm_files:
        try:
            ds = dcmread(str(path), stop_before_pixels=True)
        except Exception as exc:
            unreadable += 1
            logger.warning(
                '0035 recover: could not read DICOM file %s: %s',
                path, exc,
            )
            continue

        if study_description is None:
            desc = str(getattr(ds, 'StudyDescription', '') or '').strip()
            study_description = desc or None
        if study_date is None:
            study_date = _dicom_date(getattr(ds, 'StudyDate', ''))
        modality = str(getattr(ds, 'Modality', '') or '').strip()
        if modality:
            modalities.add(modality)
        series_desc = str(getattr(ds, 'SeriesDescription', '') or '').strip()
        if series_desc:
            series_descriptions.add(series_desc)

        series_uid = str(getattr(ds, 'SeriesInstanceUID', '') or '').strip()
        sop_uid = str(getattr(ds, 'SOPInstanceUID', '') or '').strip()
        if not series_uid or not sop_uid:
            continue
        if series_uid not in series_info:
            series_date = (
                _dicom_date(getattr(ds, 'SeriesDate', ''))
                or _dicom_date(getattr(ds, 'StudyDate', ''))
            )
            frame = str(getattr(ds, 'FrameOfReferenceUID', '') or '').strip()
            series_info[series_uid] = {
                'series_date': series_date,
                'modality': modality[:16],
                'frame_of_reference_uid': frame or None,
            }
        instances.append((series_uid, sop_uid))

    return {
        'study_description': study_description,
        'study_date': study_date,
        'series_descriptions': ', '.join(sorted(series_descriptions)) or None,
        'study_modalities': ', '.join(sorted(modalities)) or None,
        'series': series_info,
        'instances': instances,
        'file_count': len(dcm_files),
        'unreadable': unreadable,
    }


def _recover_one_study(apps, location, patient_dir, study_dir):
    """Recreate DB rows for one '<patient_segment>/<study_uid>' archive
    folder. Returns a dict of counts."""
    Patient = apps.get_model('client_app', 'Patient')
    DICOMStudy = apps.get_model('client_app', 'DICOMStudy')
    DICOMSeries = apps.get_model('client_app', 'DICOMSeries')
    DICOMInstance = apps.get_model('client_app', 'DICOMInstance')
    ArchivedStudy = apps.get_model('dicom_archive', 'ArchivedStudy')

    counts = {'study': 0, 'series': 0, 'instances': 0, 'record': 0,
              'skipped': 0}

    manifest = _parse_manifest(study_dir)
    if manifest:
        patient_id = str(manifest.get('patient_id') or '').strip()
        study_uid = str(manifest.get('study_instance_uid') or '').strip()
    else:
        # No manifest: the study UID is the directory name, but the
        # patient ID cannot be recovered reliably (the parent directory
        # is a sanitised patient ID, which is not reversible).
        logger.warning(
            '0035 recover: SKIPPED %s — no readable manifest with '
            'patient_id', study_dir,
        )
        patient_id, study_uid = '', study_dir.name
    if not patient_id or not study_uid:
        counts['skipped'] += 1
        return counts

    patient = Patient.objects.filter(patient_id=patient_id).first()
    if patient is None:
        logger.warning(
            '0035 recover: SKIPPED %s — patient %r no longer exists in '
            'the database', study_dir, patient_id,
        )
        counts['skipped'] += 1
        return counts

    local_path = _expected_folder_path(patient.patient_id, study_uid)

    study = DICOMStudy.objects.filter(study_instance_uid=study_uid).first()
    if study is not None and study.patient_id != patient.patient_id:
        logger.warning(
            '0035 recover: SKIPPED %s — study row exists under a '
            'different patient (%r != %r)',
            study_dir, study.patient_id, patient.patient_id,
        )
        counts['skipped'] += 1
        return counts

    # Rebuild series/instance rows whenever they are missing. (0034
    # removed them all or none, so a partial gap is only possible after
    # manual editing.)
    needs_children = study is None
    if study is not None and not needs_children:
        needs_children = not DICOMSeries.objects.filter(study=study).exists()

    if needs_children:
        meta = _scan_study_files(study_dir)
        if meta['file_count'] and meta['unreadable'] == meta['file_count']:
            logger.warning(
                '0035 recover: %s — all %d files unreadable; recording '
                'study without children', study_dir, meta['file_count'],
            )

        if study is None:
            study = DICOMStudy.objects.create(
                patient=patient,
                study_instance_uid=study_uid,
                study_description=meta['study_description'],
                study_date=meta['study_date'],
                series_descriptions=meta['series_descriptions'],
                study_modalities=meta['study_modalities'],
                folder_path=str(local_path),
            )
            counts['study'] += 1

        for series_uid, info in meta['series'].items():
            series, created = DICOMSeries.objects.get_or_create(
                series_instance_uid=series_uid,
                defaults={
                    'study': study,
                    'series_date': info['series_date'],
                    'modality': info['modality'],
                    'frame_of_reference_uid': info['frame_of_reference_uid'],
                },
            )
            if created:
                counts['series'] += 1
            for series_uid_of_inst, sop_uid in meta['instances']:
                if series_uid_of_inst != series_uid:
                    continue
                _, created = DICOMInstance.objects.get_or_create(
                    sop_instance_uid=sop_uid, defaults={'series': series}
                )
                if created:
                    counts['instances'] += 1

    record = ArchivedStudy.objects.filter(study=study).first()
    if record is None:
        manifest = _parse_manifest(study_dir) or {}
        try:
            size_bytes = int(manifest.get('size_bytes') or 0)
            instance_count = int(manifest.get('instance_count') or 0)
        except (TypeError, ValueError):
            size_bytes, instance_count = 0, 0
        if not instance_count:
            # The manifest written by archive_study() does not carry
            # instance_count — count the .dcm files on disk instead.
            instance_count = len([
                p for p in study_dir.iterdir()
                if p.is_file() and p.suffix.lower() == '.dcm'
            ])
        ArchivedStudy.objects.create(
            study=study,
            location=location,
            # Use the raw string values: apps.get_model() yields Django's
            # historical model, which rebuilds the class from field
            # definitions and drops the inner TextChoices classes (Status,
            # Reason). Referencing ArchivedStudy.Status / .Reason here
            # raises AttributeError.
            status='ARCHIVED',
            reason='MANUAL',
            local_path_before=str(local_path),
            archive_rel_path=f'{patient_dir.name}/{study_dir.name}',
            size_bytes=size_bytes,
            instance_count=instance_count,
            archived_at=_parse_dt(manifest.get('archived_at')),
            error_log=(
                'Recreated by migration 0035: the original record was '
                'cascade-deleted with the study by migration 0034.'
            ),
        )
        counts['record'] += 1

    logger.info(
        '0035 recover: %s (patient %s) — study %s, %d series, '
        '%d instances, archive record %s (location %s)',
        study_uid, patient.patient_id,
        'RESTORED' if counts['study'] else 'kept',
        counts['series'], counts['instances'],
        'RECREATED' if counts['record'] else 'kept',
        location.name,
    )
    return counts


def recover_archived_studies(apps, schema_editor):
    ArchiveLocation = apps.get_model('dicom_archive', 'ArchiveLocation')

    totals = {'study': 0, 'series': 0, 'instances': 0, 'record': 0,
              'skipped': 0}

    for location in ArchiveLocation.objects.all():
        base = _resolve_location_path(location)
        if base is None or not base.is_dir():
            logger.info(
                '0035 recover: location %s has no accessible directory '
                '(path=%r) — nothing to scan', location.name,
                location.path,
            )
            continue
        logger.info(
            '0035 recover: scanning archive location %s at %s',
            location.name, base,
        )
        for patient_dir in sorted(base.iterdir()):
            if not patient_dir.is_dir():
                continue
            for study_dir in sorted(patient_dir.iterdir()):
                if not study_dir.is_dir():
                    continue
                counts = _recover_one_study(
                    apps, location, patient_dir, study_dir
                )
                for key in totals:
                    totals[key] += counts[key]

    logger.info(
        '0035 recover pass complete: %d studies restored, %d series, '
        '%d instances, %d archive records recreated, %d folders skipped',
        totals['study'], totals['series'], totals['instances'],
        totals['record'], totals['skipped'],
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('client_app', '0034_fix_dicomstudy_folder_paths'),
        ('dicom_archive', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(verify_and_repair_local_studies, noop),
        migrations.RunPython(recover_archived_studies, noop),
    ]
