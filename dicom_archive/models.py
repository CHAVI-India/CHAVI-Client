"""Models for the dicom_archive app.

Storage backends are path-based only (LOCAL folder or MOUNTed NAS/LAN
share) — no remote DICOM (C-MOVE/C-GET) storage is in scope.
"""
import re

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models


class ArchiveLocation(models.Model):
    """Where archived study folders are stored."""

    class StorageType(models.TextChoices):
        LOCAL = 'LOCAL', 'Local folder'
        MOUNT = 'MOUNT', 'Mounted share (NAS/LAN)'

    name = models.CharField(max_length=100, unique=True)
    storage_type = models.CharField(
        max_length=10, choices=StorageType.choices, default=StorageType.LOCAL,
    )
    path = models.CharField(
        max_length=500,
        help_text="LOCAL: absolute, or relative to MEDIA_ROOT. "
                  "MOUNT: must be an absolute path to the mounted share.",
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        _ = self.resolved_path  # raises ValidationError for invalid paths

    @property
    def resolved_path(self) -> "pathlib.Path":
        from dicom_archive.services.locations import resolve_location_path
        return resolve_location_path(self)

    def __str__(self):
        return f"{self.name} ({self.storage_type})"

    class Meta:
        verbose_name = 'Archive Location'
        verbose_name_plural = 'Archive Locations'
        ordering = ['name']


class ArchiveConfiguration(models.Model):
    """Singleton archive policy — exact DICOMServerConfiguration pattern
    (pk forced to first row on save, CACHE_KEY, load() with 30 s cache).
    Always read via ArchiveConfiguration.load()."""

    enabled = models.BooleanField(default=False)
    archive_after_days = models.PositiveIntegerField(
        default=90,
        help_text='Archive studies older than this many days (from '
                  'study_date, falling back to created_at).',
    )
    delete_local_after_archive = models.BooleanField(
        default=True,
        help_text="True = delete the local study folder after a successful "
                  "archive (the folder is moved into the archive); "
                  "False = keep a local copy.",
    )
    archive_minute = models.CharField(max_length=20, default='0')
    archive_hour = models.CharField(max_length=20, default='2')
    archive_day_of_week = models.CharField(max_length=20, default='*')
    archive_day_of_month = models.CharField(max_length=20, default='*')
    archive_month_of_year = models.CharField(max_length=20, default='*')
    batch_limit = models.PositiveIntegerField(
        default=25, help_text='Maximum studies per scheduled run.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    CACHE_KEY = 'dicom_archive_config'
    _CRON_FIELD_RE = re.compile(r'^[\d\-\,\*/]+$')

    def save(self, *args, **kwargs):
        if self.__class__.objects.count():
            self.pk = self.__class__.objects.first().pk
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def load(cls):
        config = cache.get(cls.CACHE_KEY)
        if config is None:
            config, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, config, 30)
        return config

    @property
    def crontab_tuple(self) -> tuple:
        return (
            self.archive_minute,
            self.archive_hour,
            self.archive_day_of_week,
            self.archive_day_of_month,
            self.archive_month_of_year,
        )

    def clean(self):
        super().clean()
        for name, value in [
            ('archive_minute', self.archive_minute),
            ('archive_hour', self.archive_hour),
            ('archive_day_of_week', self.archive_day_of_week),
            ('archive_day_of_month', self.archive_day_of_month),
            ('archive_month_of_year', self.archive_month_of_year),
        ]:
            if not self._CRON_FIELD_RE.match(value or ''):
                raise ValidationError({name: 'Invalid cron field value.'})

    def __str__(self):
        state = 'enabled' if self.enabled else 'disabled'
        return f"Archive config ({state}, >{self.archive_after_days}d)"

    class Meta:
        verbose_name = 'Archive Configuration'
        verbose_name_plural = 'Archive Configurations'


class ArchivedStudy(models.Model):
    """One archived study: location, state, and audit trail."""

    class Status(models.TextChoices):
        ARCHIVING = 'ARCHIVING', 'Archiving'
        ARCHIVED = 'ARCHIVED', 'Archived'
        DEARCHIVING = 'DEARCHIVING', 'De-archiving'
        DEARCHIVED = 'DEARCHIVED', 'De-archived'

    class Reason(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        MANUAL = 'MANUAL', 'Manual'

    study = models.OneToOneField(
        'client_app.DICOMStudy',
        on_delete=models.CASCADE,
        related_name='archive_record',
    )
    location = models.ForeignKey(
        'ArchiveLocation',
        on_delete=models.PROTECT,
        related_name='archived_studies',
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ARCHIVING,
    )
    reason = models.CharField(
        max_length=10, choices=Reason.choices, default=Reason.MANUAL,
    )
    local_path_before = models.CharField(
        max_length=500,
        help_text="study.folder_path (absolute) at archive time — "
                  "de-archive restores to exactly this path.",
    )
    archive_rel_path = models.CharField(
        max_length=500,
        help_text="'<patient_id>/<study_uid>' under the location's path.",
    )
    size_bytes = models.BigIntegerField(default=0)
    instance_count = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)
    dearchived_at = models.DateTimeField(null=True, blank=True)
    error_log = models.TextField(blank=True, default='')
    archived_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-id']
        verbose_name = 'Archived Study'
        verbose_name_plural = 'Archived Studies'

    def __str__(self):
        return f"{self.study.study_instance_uid} [{self.status}]"
