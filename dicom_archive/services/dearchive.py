"""De-archival (restore) of previously archived study folders."""
import logging
import shutil
from pathlib import Path

from django.utils import timezone

from dicom_archive.models import ArchivedStudy
from dicom_archive.services.archive import MANIFEST_NAME, ArchiveError

logger = logging.getLogger(__name__)


def dearchival_required_for_studies(study_uids: list) -> list:
    """Deduped, input-ordered uids whose archive record is currently
    ARCHIVED — i.e., the study lives in the archive, not locally."""
    seen = list(dict.fromkeys(study_uids))
    archived = set(
        ArchivedStudy.objects
        .filter(
            study__study_instance_uid__in=seen,
            status=ArchivedStudy.Status.ARCHIVED,
        )
        .values_list('study__study_instance_uid', flat=True)
    )
    return [uid for uid in seen if uid in archived]


def dearchive_study(record: ArchivedStudy, user=None) -> ArchivedStudy:
    """Move one archived study back to record.local_path_before.

    The archive manifest is dropped during the move. If the local folder
    already exists (e.g., the patient was re-ingested), incoming items are
    merged in without overwriting existing local files (colliding names get
    a numbered suffix). On any failure the record stays ARCHIVED so the
    de-archive can be retried.
    """
    src = record.location.resolved_path / record.archive_rel_path
    if not src.is_dir():
        raise ArchiveError(
            f"Archive folder missing for {record.study_id}: {src}"
        )
    dst = Path(record.local_path_before)

    try:
        dst.mkdir(parents=True, exist_ok=True)
        for item in sorted(src.iterdir()):
            if item.name == MANIFEST_NAME:
                item.unlink()
                continue
            target = dst / item.name
            if target.exists():
                for index in range(1, 1000):
                    candidate = f"{item.name}__archive_{index}"
                    if not (dst / candidate).exists():
                        target = dst / candidate
                        break
                else:
                    raise ArchiveError(
                        f"Cannot resolve name collision for "
                        f"{item.name} in {dst}"
                    )
            shutil.move(str(item), str(target))
        src.rmdir()
    except ArchiveError:
        raise
    except (OSError, shutil.Error) as exc:
        raise ArchiveError(
            f"Failed to de-archive {record.study_id}: {exc}"
        ) from exc

    # Tidy up: drop the per-patient folder in the archive location when the
    # de-archived study was its only occupant (never fatal — cosmetic only).
    parent = src.parent
    try:
        if (parent != record.location.resolved_path
                and parent.is_dir() and not any(parent.iterdir())):
            parent.rmdir()
    except OSError as exc:
        logger.warning(
            'Could not remove empty archive patient folder %s: %s',
            parent, exc,
        )

    record.status = ArchivedStudy.Status.DEARCHIVED
    record.dearchived_at = timezone.now()
    record.save(update_fields=['status', 'dearchived_at', 'updated_at'])
    return record


def dearchive_studies(study_uids, user=None) -> dict:
    """De-archive every requested uid that is actually ARCHIVED, with
    per-study failure isolation. Returns
    {'dearchived': [uid, ...], 'failed': {uid: error}}.
    Uids with no ARCHIVED record are silently skipped (already local)."""
    dearchived = []
    failed = {}
    records = {
        record.study_id: record
        for record in ArchivedStudy.objects
        .filter(
            study__study_instance_uid__in=list(study_uids),
            status=ArchivedStudy.Status.ARCHIVED,
        )
        .select_related('location', 'study')
    }
    for uid in study_uids:
        record = records.get(uid)
        if record is None:
            continue
        try:
            dearchive_study(record, user=user)
            dearchived.append(uid)
        except ArchiveError as exc:
            failed[uid] = str(exc)
            logger.error('De-archive failed for %s: %s', uid, exc)
    return {'dearchived': dearchived, 'failed': failed}


def ensure_studies_local(study_uids: list) -> dict:
    """Make sure each study's files are on local disk.

    Returns {uid: 'local' | 'dearchived' | 'failed'} — 'local' when the
    study has no ARCHIVED record, 'dearchived' when it was just restored,
    'failed' when the restore could not complete.
    """
    required = set(dearchival_required_for_studies(study_uids))
    outcome = dearchive_studies(sorted(required)) if required else {}
    failed = set(outcome.get('failed', {}))
    return {
        uid: (
            'failed' if uid in failed
            else 'dearchived' if uid in required
            else 'local'
        )
        for uid in dict.fromkeys(study_uids)
    }
