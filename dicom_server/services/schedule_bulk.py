"""Dispatch/sync BulkRetrievalSchedule runs: one-off (Celery eta) or periodic
(django_celery_beat.PeriodicTask). Mirrors services/schedule_sync.py."""
import json
import logging

from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask

logger = logging.getLogger(__name__)

RUN_TASK = 'dicom_server.tasks.task_bulk_schedule_run'


def _ensure_periodic(schedule):
    minute, hour, dow, dom, moy = schedule.crontab_tuple
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=minute, hour=hour, day_of_week=dow,
        day_of_month=dom, month_of_year=moy,
        timezone=str(settings.TIME_ZONE),
    )
    PeriodicTask.objects.update_or_create(
        name=schedule.beat_name,
        defaults={
            'task': RUN_TASK,
            'args': json.dumps([schedule.pk]),
            'crontab': crontab,
            'enabled': True,
        },
    )


def _dispatch_one_off(schedule):
    from dicom_server.tasks import task_bulk_schedule_run
    result = task_bulk_schedule_run.apply_async(
        kwargs={'schedule_id': schedule.pk}, eta=schedule.run_at,
    )
    schedule.one_off_task_id = result.id or ''
    schedule.save(update_fields=['one_off_task_id', 'updated_at'])
    return result


def revoke_one_off(schedule):
    if not schedule.one_off_task_id:
        return
    from celery import current_app
    try:
        current_app.control.revoke(schedule.one_off_task_id, terminate=False)
    except Exception:
        logger.exception('Failed to revoke one-off task %s', schedule.one_off_task_id)
    schedule.one_off_task_id = ''
    schedule.save(update_fields=['one_off_task_id', 'updated_at'])


def sync_bulk_schedule(schedule):
    """Idempotently bring the dispatch in line with the schedule's state."""
    if not schedule.is_active:
        PeriodicTask.objects.filter(name=schedule.beat_name).update(enabled=False)
        if schedule.one_off_task_id:
            revoke_one_off(schedule)
        return
    if schedule.mode == schedule.Mode.PERIODIC:
        _ensure_periodic(schedule)
        if schedule.one_off_task_id:
            revoke_one_off(schedule)
    elif schedule.mode == schedule.Mode.ONE_OFF:
        PeriodicTask.objects.filter(name=schedule.beat_name).update(enabled=False)
        if not schedule.one_off_task_id:
            _dispatch_one_off(schedule)
