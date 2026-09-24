import logging

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from client_app.models import Patient

logger = logging.getLogger(__name__)

_old_consent = {}


@receiver(pre_save, sender=Patient)
def _cache_old_consent(sender, instance, **kwargs):
    if instance.pk:
        try:
            _old_consent[instance.pk] = Patient.objects.get(pk=instance.pk).chavi_consent
        except Patient.DoesNotExist:
            _old_consent.pop(instance.pk, None)


@receiver(post_save, sender=Patient)
def _trigger_auto_retrieval(sender, instance, created, **kwargs):
    if not instance.chavi_consent:
        return
    old_consent = _old_consent.pop(instance.pk, None)
    if created or old_consent is not True:
        try:
            from dicom_server.tasks import task_auto_retrieve_patient
            task_auto_retrieve_patient.delay(instance.patient_id)
        except Exception:
            logger.exception('Failed to dispatch auto-retrieval for patient %s', instance.patient_id)
