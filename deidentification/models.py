import logging

from django.db import models
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField, EncryptedIntegerField

from client_app.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance

logger = logging.getLogger(__name__)


class DeidPatient(models.Model):
    patient = models.OneToOneField(
        Patient,
        on_delete=models.CASCADE,
        related_name='deid_record',
        help_text="FK to the original patient record (plaintext patient_id is the PK)."
    )
    deidentified_patient_id = EncryptedCharField(
        max_length=255,
        help_text="Deidentified patient ID (UUID-based, encrypted at rest)."
    )
    date_shift_value = EncryptedIntegerField(
        help_text="Number of days shifted for date deidentification (-100 to +100, encrypted)."
    )
    deidentified_date_of_birth = EncryptedCharField(
        max_length=8,
        null=True,
        blank=True,
        help_text="Deidentified date of birth in YYYYMMDD format (encrypted)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"DeidPatient for {self.patient.patient_id}"

    class Meta:
        verbose_name = "Deidentified Patient"
        verbose_name_plural = "Deidentified Patients"


class DeidStudy(models.Model):
    study = models.OneToOneField(
        DICOMStudy,
        on_delete=models.CASCADE,
        related_name='deid_record',
        help_text="FK to the original DICOM study (plaintext study_instance_uid is the PK)."
    )
    deid_patient = models.ForeignKey(
        DeidPatient,
        on_delete=models.CASCADE,
        related_name='deid_studies',
        help_text="FK to the deidentified patient record."
    )
    deidentified_study_instance_uid = EncryptedCharField(
        max_length=128,
        help_text="Deidentified Study Instance UID (encrypted at rest)."
    )
    deidentified_study_date = EncryptedCharField(
        max_length=8,
        help_text="Deidentified study date in YYYYMMDD format (encrypted)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"DeidStudy for {self.study.study_instance_uid[:30]}..."

    class Meta:
        verbose_name = "Deidentified Study"
        verbose_name_plural = "Deidentified Studies"


class DeidSeries(models.Model):
    series = models.OneToOneField(
        DICOMSeries,
        on_delete=models.CASCADE,
        related_name='deid_record',
        help_text="FK to the original DICOM series (plaintext series_instance_uid is the PK)."
    )
    deid_study = models.ForeignKey(
        DeidStudy,
        on_delete=models.CASCADE,
        related_name='deid_series',
        help_text="FK to the deidentified study record."
    )
    deidentified_series_instance_uid = EncryptedCharField(
        max_length=128,
        help_text="Deidentified Series Instance UID (encrypted at rest)."
    )
    deidentified_series_date = EncryptedCharField(
        max_length=8,
        null=True,
        blank=True,
        help_text="Deidentified series date in YYYYMMDD format (encrypted)."
    )
    deidentified_frame_of_reference_uid = EncryptedCharField(
        max_length=128,
        null=True,
        blank=True,
        help_text="Deidentified Frame of Reference UID (encrypted at rest)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"DeidSeries for {self.series.series_instance_uid[:30]}..."

    class Meta:
        verbose_name = "Deidentified Series"
        verbose_name_plural = "Deidentified Series"


class DeidInstance(models.Model):
    instance = models.OneToOneField(
        DICOMInstance,
        on_delete=models.CASCADE,
        related_name='deid_record',
        help_text="FK to the original DICOM instance (plaintext sop_instance_uid is the PK)."
    )
    deid_series = models.ForeignKey(
        DeidSeries,
        on_delete=models.CASCADE,
        related_name='deid_instances',
        help_text="FK to the deidentified series record."
    )
    deidentified_sop_instance_uid = EncryptedCharField(
        max_length=128,
        help_text="Deidentified SOP Instance UID (encrypted at rest)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"DeidInstance for {self.instance.sop_instance_uid[:30]}..."

    class Meta:
        verbose_name = "Deidentified Instance"
        verbose_name_plural = "Deidentified Instances"


class DeidentificationJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        SUCCESS = 'SUCCESS', 'Success'
        FAILURE = 'FAILURE', 'Failure'
        PARTIAL = 'PARTIAL', 'Partial Success'

    study = models.ForeignKey(
        DICOMStudy,
        on_delete=models.CASCADE,
        related_name='deid_jobs',
        help_text="The DICOM study being deidentified."
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    output_path = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Relative path from MEDIA_ROOT to the deidentified output directory."
    )
    total_file_count = models.IntegerField(default=0)
    processed_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    failed_series_count = models.IntegerField(default=0)
    error_log = models.TextField(null=True, blank=True)
    task_run = models.ForeignKey(
        'client_app.TaskRun',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deid_jobs',
        help_text="Associated Celery TaskRun for progress tracking."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"DeidJob {self.id} - {self.study.study_instance_uid[:20]}... - {self.status}"

    class Meta:
        verbose_name = "Deidentification Job"
        verbose_name_plural = "Deidentification Jobs"
        ordering = ['-created_at']


class PixelRedactionLog(models.Model):
    job = models.ForeignKey(
        DeidentificationJob,
        on_delete=models.CASCADE,
        related_name='pixel_redaction_logs',
        help_text="The deidentification job this log belongs to."
    )
    file_path = models.CharField(max_length=500, help_text="Path to the deidentified file.")
    bboxes = models.JSONField(
        help_text="Bounding box coordinates of redacted regions, stored as JSON."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PixelRedactionLog for {self.file_path[:50]}..."

    class Meta:
        verbose_name = "Pixel Redaction Log"
        verbose_name_plural = "Pixel Redaction Logs"
