import os
import json
from celery import Celery
from celery.signals import task_prerun, task_postrun, task_failure

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chavi_client.settings")

app = Celery("chavi_client")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    """Store task start info in TaskResult table for admin visibility."""
    from django.utils import timezone
    try:
        from django_celery_results.models import TaskResult
        TaskResult.objects.update_or_create(
            task_id=task_id,
            defaults={
                'task_name': task.name,
                'status': 'STARTED',
                'date_created': timezone.now(),
                'date_started': timezone.now(),
            }
        )
    except Exception:
        pass


@task_postrun.connect
def task_postrun_handler(task_id, task, retval, state, *args, **kwargs):
    """Store final task result in TaskResult table for admin download links."""
    from django.utils import timezone
    try:
        from django_celery_results.models import TaskResult
        result_str = json.dumps(retval) if retval is not None else None
        TaskResult.objects.update_or_create(
            task_id=task_id,
            defaults={
                'task_name': task.name,
                'status': state,
                'result': result_str,
                'date_done': timezone.now(),
            }
        )
    except Exception:
        pass


@task_failure.connect
def task_failure_handler(task_id, exception, *args, **kwargs):
    """Store task failure info in TaskResult table."""
    from django.utils import timezone
    try:
        from django_celery_results.models import TaskResult
        TaskResult.objects.update_or_create(
            task_id=task_id,
            defaults={
                'status': 'FAILURE',
                'result': str(exception),
                'date_done': timezone.now(),
            }
        )
    except Exception:
        pass
