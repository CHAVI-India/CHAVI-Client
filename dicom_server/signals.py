"""Signal receivers for dicom_server (loaded via DicomServerConfig.ready)."""
import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django_celery_beat.models import PeriodicTask

from dicom_server.models import RemoteDICOMNode
from dicom_server.services.schedule_sync import sync_node_schedule

logger = logging.getLogger(__name__)


@receiver(post_save, sender=RemoteDICOMNode)
def _sync_node_schedule_on_save(sender, instance, **kwargs):
    sync_node_schedule(instance)


@receiver(post_delete, sender=RemoteDICOMNode)
def _disable_node_schedule_on_delete(sender, instance, **kwargs):
    PeriodicTask.objects.filter(name=f'dicom-auto-retrieve-node-{instance.pk}').delete()
