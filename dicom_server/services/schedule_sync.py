"""Keep django_celery_beat.PeriodicTask rows in sync with RemoteDICOMNode schedules."""
import json
import logging

from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from dicom_server.models import RemoteDICOMNode

logger = logging.getLogger(__name__)

SCHEDULE_TASK = 'dicom_server.tasks.task_auto_retrieve_node'


def _periodic_task_name(node_id: int) -> str:
    return f'dicom-auto-retrieve-node-{node_id}'


def sync_node_schedule(node):
    """Create/update/disable the PeriodicTask for a RemoteDICOMNode."""
    name = _periodic_task_name(node.pk)

    if not node.auto_retrieve_enabled:
        PeriodicTask.objects.filter(name=name).update(enabled=False)
        return

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=node.auto_retrieve_minute,
        hour=node.auto_retrieve_hour,
        day_of_week=node.auto_retrieve_day_of_week,
        day_of_month=node.auto_retrieve_day_of_month,
        month_of_year=node.auto_retrieve_month_of_year,
        timezone=str(settings.TIME_ZONE),
    )

    PeriodicTask.objects.update_or_create(
        name=name,
        defaults={
            'task': SCHEDULE_TASK,
            'args': json.dumps([node.pk]),
            'crontab': crontab,
            'enabled': True,
            'expire_seconds': 3600,
        },
    )


def sync_all_node_schedules():
    for node in RemoteDICOMNode.objects.all():
        sync_node_schedule(node)
