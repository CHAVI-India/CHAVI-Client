import uuid
from django.db import models
from django.core.cache import cache


class DICOMServerConfiguration(models.Model):
    """Singleton: local AE / listener configuration. Edited by staff via the
    frontend (or admin). Cached — always read via DICOMServerConfiguration.load()."""
    ae_title = models.CharField(
        max_length=16, default='CHAVI_CLIENT',
        help_text="This server's AE Title (max 16 chars). Remote PACS must route "
                  "C-MOVE destinations to this AE title.",
    )
    port = models.PositiveIntegerField(default=11112)
    bind_address = models.CharField(
        max_length=64, default='0.0.0.0',
        help_text="Interface to listen on. Use 0.0.0.0 to accept connections on all interfaces.",
    )
    max_pdu = models.PositiveIntegerField(default=16382)
    qr_timeout = models.PositiveIntegerField(
        default=30,
        help_text="Seconds — association/DIMSE timeout for outbound Q/R requests.",
    )
    is_enabled = models.BooleanField(
        default=True,
        help_text="When unchecked the SCP still listens but rejects inbound C-STORE requests.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    CACHE_KEY = 'dicom_server_config'

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
            cache.set(cls.CACHE_KEY, config, 300)
        return config

    def __str__(self):
        return f"{self.ae_title} @ {self.bind_address}:{self.port}"

    class Meta:
        verbose_name = "DICOM Server Configuration"


class RemoteDICOMNode(models.Model):
    """A remote DICOM peer (PACS/modality) this server can query/retrieve from."""
    name = models.CharField(max_length=100, help_text="Friendly name, e.g. 'Hospital PACS'")
    ae_title = models.CharField(max_length=16, help_text="Called AE Title of the remote node")
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=104)
    is_active = models.BooleanField(default=True)
    prefer_c_get = models.BooleanField(
        default=False,
        help_text="Use C-GET instead of C-MOVE for retrieval. Required when the remote "
                  "cannot open a connection back to this server (e.g. we are behind NAT).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.ae_title}@{self.host}:{self.port})"

    class Meta:
        verbose_name = "Remote DICOM Node"
        ordering = ['name']


class InboundDICOMInstance(models.Model):
    """Audit log — one row per received C-STORE request (SCP or C-GET sub-op)."""
    class Status(models.TextChoices):
        STORED = 'STORED', 'Stored'
        REJECTED = 'REJECTED', 'Rejected'

    received_at = models.DateTimeField(auto_now_add=True)
    calling_ae_title = models.CharField(max_length=16, blank=True, default='')
    called_ae_title = models.CharField(max_length=16, blank=True, default='')
    remote_addr = models.CharField(max_length=64, blank=True, default='')
    dicom_patient_id = models.CharField(max_length=255, blank=True, default='')
    matched_patient = models.ForeignKey(
        'client_app.Patient', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='dicom_inbound_instances',
    )
    study_instance_uid = models.CharField(max_length=128, blank=True, default='')
    series_instance_uid = models.CharField(max_length=128, blank=True, default='')
    sop_instance_uid = models.CharField(max_length=128, blank=True, default='')
    modality = models.CharField(max_length=16, blank=True, default='')
    status = models.CharField(max_length=10, choices=Status.choices)
    reject_reason = models.CharField(max_length=255, blank=True, default='')
    file_path = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['study_instance_uid']),
            models.Index(fields=['sop_instance_uid']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.status} {self.sop_instance_uid or '?'} from {self.calling_ae_title}"


class RetrievalJob(models.Model):
    """Tracks one user-initiated query/retrieve operation against a RemoteDICOMNode."""
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        RUNNING = 'RUNNING', 'Running'
        SUCCESS = 'SUCCESS', 'Success'
        PARTIAL = 'PARTIAL', 'Partial'
        FAILED = 'FAILED', 'Failed'

    node = models.ForeignKey(RemoteDICOMNode, on_delete=models.PROTECT, related_name='retrieval_jobs')
    patient = models.ForeignKey('client_app.Patient', on_delete=models.PROTECT, related_name='retrieval_jobs')
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    study_uids = models.JSONField(
        null=True, blank=True,
        help_text="Requested Study Instance UIDs (null = all studies found for the patient)",
    )
    studies_found = models.JSONField(
        null=True, blank=True, help_text="Study-level C-FIND results",
    )
    instances_received = models.IntegerField(default=0)
    celery_task_id = models.CharField(max_length=255, blank=True, default='')
    error_log = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Job {self.pk} {self.patient_id} <- {self.node.name} [{self.status}]"
