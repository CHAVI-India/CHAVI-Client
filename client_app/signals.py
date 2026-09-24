import logging

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from client_app.models import Patient
from dicom_server.tasks import task_auto_retrieve_patient

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Patient)
def _cache_old_consent(sender, instance, **kwargs):
    instance._old_chavi_consent = None
    if instance.pk:
        try:
            instance._old_chavi_consent = Patient.objects.get(pk=instance.pk).chavi_consent
        except Patient.DoesNotExist:
            pass


@receiver(post_save, sender=Patient)
def _trigger_auto_retrieval(sender, instance, created, **kwargs):
    if not instance.chavi_consent:
        return
    if created or getattr(instance, '_old_chavi_consent', None) is not True:
        try:
            task_auto_retrieve_patient.delay(instance.patient_id)
        except Exception:
            logger.exception('Failed to dispatch auto-retrieval for patient %s', instance.patient_id)
