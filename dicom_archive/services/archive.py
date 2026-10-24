"""File move/copy archiving of local DICOM study folders.

No DICOM network transfer — plain filesystem operations on the study
folders under MEDIA_ROOT/processed_dicom/<patient_id>/<study_uid>.
"""
import json
import logging
import re
import shutil
from pathlib import Path

from django.utils import timezone

from dicom_archive.models import ArchiveConfiguration, ArchivedStudy
from dicom_archive.services.locations import prepare_location

logger = logging.getLogger(__name__)

MANIFEST_NAME = '_archive_manifest.json'


class ArchiveError(Exception):
    """Raised when a study cannot be archived or de-archived."""


def _sanitize_segment(value: str) -> str:
    """Make a patient ID / UID safe for use as a single path segment."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', value or '') or 'unknown'


def _study_stats(folder: Path):
    """(file_count, size_bytes, instance_count) for a study folder.

    instance_count counts *.dcm files (case-insensitive); the manifest
    itself is excluded from file_count/size_bytes.
    """
    files = [
        p for p in folder.rglob('*') if p.is_file() and p.name != MANIFEST_NAME
    ]
    size_bytes = sum(p.stat().st_size for p in files)
    instance_count = len([p for p in files if p.suffix.lower() == '.dcm'])
    return len(files), size_bytes, instance_count


def archive_study(study, location, user=None, reason='MANUAL') -> ArchivedStudy:
    """Archive one local study folder into the given location.

    The delete-vs-keep policy is location-independent: it follows
    ArchiveConfiguration.delete_local_after_archive (True=move+delete local,
    False=copy+keep local).
    Raises ArchiveError on any failure; per-study failure isolation is the
    caller's job (see archive_studies).
    """
    local = Path(study.folder_path) if study.folder_path else None
    if local is None or not local.is_dir():
        raise ArchiveError(
            f"Local study folder missing for "
            f"{study.study_instance_uid}: {study.folder_path!r}"
        )

    base = prepare_location(location)
    patient_segment = _sanitize_segment(study.patient.patient_id)
    dest = base / patient_segment / study.study_instance_uid
    if dest.exists() and any(dest.iterdir()):
        raise ArchiveError(f"Archive destination is not empty: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        config = ArchiveConfiguration.load()
        if config.delete_local_after_archive:
            shutil.move(str(local), str(dest))
        else:
            shutil.copytree(str(local), str(dest))
    except (OSError, shutil.Error) as exc:
        raise ArchiveError(
            f"Failed to copy study folder to {dest}: {exc}"
        ) from exc

    if config.delete_local_after_archive:
        # The local copy moved away: drop the now-empty per-patient folder
        # under processed_dicom (never fatal — cosmetic only; the
        # processed_dicom root itself is never removed).
        parent = local.parent
        try:
            if (parent.name != 'processed_dicom'
                    and parent.is_dir() and not any(parent.iterdir())):
                parent.rmdir()
        except OSError as exc:
            logger.warning(
                'Could not remove empty local patient folder %s: %s',
                parent, exc,
            )

    try:
        file_count, size_bytes, instance_count = _study_stats(dest)
        manifest = {
            'study_instance_uid': study.study_instance_uid,
            'patient_id': study.patient.patient_id,
            'archived_at': timezone.now().isoformat(),
            'file_count': file_count,
            'size_bytes': size_bytes,
        }
        (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    except OSError as exc:
        raise ArchiveError(
            f"Failed to write archive manifest in {dest}: {exc}"
        ) from exc

    record = ArchivedStudy.objects.filter(study=study).first()
    values = {
        'location': location,
        'status': ArchivedStudy.Status.ARCHIVED,
        'reason': reason,
        'local_path_before': str(local),
        'archive_rel_path': f"{patient_segment}/{study.study_instance_uid}",
        'size_bytes': size_bytes,
        'instance_count': instance_count,
        'archived_at': timezone.now(),
        'archived_by': user,
        'error_log': '',
    }
    if record:
        for field, value in values.items():
            setattr(record, field, value)
        record.save()
    else:
        record = ArchivedStudy.objects.create(study=study, **values)
    return record


def archive_studies(studies, location, user=None, reason='MANUAL') -> dict:
    """Archive many studies with per-study failure isolation.

    Returns {'archived': [study_uid, ...], 'failed': {study_uid: error},
    'skipped': [study_uid, ...]}. A study already archived at the target
    location is skipped (not failed) so a resumed run finishes only the
    remaining studies. One bad study never fails the rest of the batch.
    """
    archived = []
    failed = {}
    skipped = []
    for study in studies:
        uid = study.study_instance_uid
        existing = ArchivedStudy.objects.filter(
            study=study, status=ArchivedStudy.Status.ARCHIVED,
        ).first()
        if existing is not None and existing.location_id == location.id:
            skipped.append(uid)
            continue
        try:
            archive_study(study, location, user=user, reason=reason)
            archived.append(uid)
        except ArchiveError as exc:
            failed[uid] = str(exc)
            logger.error('Archive failed for %s: %s', uid, exc)
    return {'archived': archived, 'failed': failed, 'skipped': skipped}


def cleanup_study_files(study) -> dict:
    """Delete on-disk DICOM files for a study whose row is being deleted.

    Removes the local study folder (``study.folder_path``) and, when an
    ``ArchivedStudy`` record exists, the archived copy
    (``location.resolved_path / archive_rel_path``). Never raises — a
    failing delete is logged and reported in ``errors`` so the signal
    handler can never abort the caller's deletion.
    """
    result = {'deleted_local': False, 'deleted_archive': False, 'errors': []}

    local = Path(getattr(study, 'folder_path') or '')
    if local and local.exists():
        try:
            shutil.rmtree(local)
            result['deleted_local'] = True
        except OSError as e:
            logger.warning(f"cleanup: could not remove local folder {local}: {e}")
            result['errors'].append(f'local: {e}')

    record = getattr(study, 'archive_record', None)
    if record is not None:
        archived = Path(record.location.resolved_path) / record.archive_rel_path
        if archived.exists():
            try:
                shutil.rmtree(archived)
                result['deleted_archive'] = True
            except OSError as e:
                logger.warning(
                    f"cleanup: could not remove archive folder {archived}: {e}")
                result['errors'].append(f'archive: {e}')

    return result
