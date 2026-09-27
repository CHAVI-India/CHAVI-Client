import logging

from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from client_app.models import Patient
from dicom_server.models import RemoteDICOMNode
from dicom_server.tasks import task_auto_retrieve_patient

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Patient)
def _cache_old_consent(sender, instance, **kwargs):
    instance._old_chavi_consent = None
    if instance.pk:
        instance._old_chavi_consent = (
            Patient.objects.filter(pk=instance.pk)
            .values_list('chavi_consent', flat=True)
            .first()
        )


@receiver(post_save, sender=Patient)
def _trigger_auto_retrieval(sender, instance, created, **kwargs):
    if not instance.chavi_consent:
        return
    if created or getattr(instance, '_old_chavi_consent', None) is not True:
        # post_save fires before the surrounding transaction commits — defer
        # dispatch until commit so the worker can actually see the patient row.
        def _dispatch():
            if not RemoteDICOMNode.objects.filter(
                is_active=True, auto_retrieve_enabled=True
            ).exists():
                return
            try:
                task_auto_retrieve_patient.delay(instance.patient_id)
            except Exception:
                logger.exception(
                    'Failed to dispatch auto-retrieval for patient %s', instance.patient_id
                )
        transaction.on_commit(_dispatch)
