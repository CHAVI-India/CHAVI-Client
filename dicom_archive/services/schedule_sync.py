"""Keep the django_celery_beat.PeriodicTask row in sync with the
ArchiveConfiguration schedule (mirrors dicom_server.services.schedule_sync)."""
import json
import logging

from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from dicom_archive.models import ArchiveConfiguration

logger = logging.getLogger(__name__)

SCHEDULE_TASK = 'dicom_archive.tasks.task_scheduled_archive'
PERIODIC_TASK_NAME = 'dicom-archive-scheduled-sweep'


def sync_archive_schedule(config=None) -> None:
    """Create/update/enable the PeriodicTask, or disable it.

    ``config`` may be passed explicitly (the post_save signal passes the
    just-saved instance, because load() could otherwise return the stale
    cached copy — the signal fires before save() deletes the cache key).
    """
    config = config or ArchiveConfiguration.load()

    if not config.enabled:
        PeriodicTask.objects.filter(name=PERIODIC_TASK_NAME).update(enabled=False)
        return

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=config.archive_minute,
        hour=config.archive_hour,
        day_of_week=config.archive_day_of_week,
        day_of_month=config.archive_day_of_month,
        month_of_year=config.archive_month_of_year,
        timezone=str(settings.TIME_ZONE),
    )

    PeriodicTask.objects.update_or_create(
        name=PERIODIC_TASK_NAME,
        defaults={
            'task': SCHEDULE_TASK,
            'args': json.dumps([None]),
            'crontab': crontab,
            'enabled': True,
            'expire_seconds': 3600,
        },
    )
