"""Signal receivers for dicom_archive (loaded via DicomArchiveConfig.ready)."""
import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from client_app.models import DICOMStudy
from dicom_archive.models import ArchiveConfiguration
from dicom_archive.services.archive import cleanup_study_files
from dicom_archive.services.schedule_sync import sync_archive_schedule

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ArchiveConfiguration)
def _sync_archive_schedule_on_save(sender, instance, **kwargs):
    """Keep the beat schedule in sync on every configuration save.

    Never raises into the save path — a beat-sync failure must not break
    editing the archive configuration. The instance is passed so the sync
    sees the new values, not the (still) cached singleton."""
    try:
        sync_archive_schedule(instance)
    except Exception:
        logger.exception(
            'Failed to sync archive schedule for %s', instance,
        )


@receiver(post_delete)
def study_deleted_receiver(sender, instance, **kwargs):
    """Delete a study's DICOM files on disk whenever the study row is
    removed — directly or via cascade from Patient deletion. Per-study
    failures are logged, never raised."""
    if sender is not DICOMStudy:
        return
    try:
        cleanup_study_files(instance)
    except Exception:
        logger.exception(
            f"cleanup failed for study {getattr(instance, 'study_instance_uid', '?')}")
