import re
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.core.cache import cache


AE_TITLE_VALIDATOR = RegexValidator(
    r'^[A-Z0-9_\-]{1,16}$',
    'AE titles must be 1-16 characters: A-Z, 0-9, underscore or hyphen.',
)


class DICOMServerConfiguration(models.Model):
    """Singleton: local AE / listener configuration. Edited by staff via the
    frontend (or admin). Cached — always read via DICOMServerConfiguration.load()."""
    ae_title = models.CharField(
        max_length=16, default='CHAVI_CLIENT', validators=[AE_TITLE_VALIDATOR],
        help_text="This server's AE Title — max 16 chars, uppercase letters, "
                  "digits, underscore or hyphen only (e.g. CHAVI_CLIENT). "
                  "Remote PACS must route C-MOVE destinations to this AE title.",
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
            cache.set(cls.CACHE_KEY, config, 30)
        return config

    def __str__(self):
        return f"{self.ae_title} @ {self.bind_address}:{self.port}"

    class Meta:
        verbose_name = "DICOM Server Configuration"


class RemoteDICOMNode(models.Model):
    """A remote DICOM peer (PACS/modality) this server can query/retrieve from."""
    name = models.CharField(max_length=100, help_text="Friendly name, e.g. 'Hospital PACS'")
    ae_title = models.CharField(
        max_length=16, validators=[AE_TITLE_VALIDATOR],
        help_text="Called AE Title of the remote node — max 16 chars, "
                  "UPPERCASE letters, digits, underscore or hyphen only "
                  "(e.g. DICOMSRVR, not dicomsrvr).",
    )
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=104)
    is_active = models.BooleanField(default=True)
    prefer_c_get = models.BooleanField(
        default=False,
        help_text="Use C-GET instead of C-MOVE for retrieval. Required when the remote "
                  "cannot open a connection back to this server (e.g. we are behind NAT).",
    )
    auto_retrieve_enabled = models.BooleanField(
        default=False,
        help_text="When checked, Celery Beat will periodically auto-retrieve studies for consented patients from this node.",
    )
    auto_retrieve_minute = models.CharField(max_length=20, default='0')
    auto_retrieve_hour = models.CharField(max_length=20, default='22')
    auto_retrieve_day_of_week = models.CharField(max_length=20, default='*')
    auto_retrieve_day_of_month = models.CharField(max_length=20, default='*')
    auto_retrieve_month_of_year = models.CharField(max_length=20, default='*')
    auto_retrieve_min_interval_minutes = models.PositiveIntegerField(
        default=60,
        help_text='Minimum minutes between auto-retrieval attempts for the same patient on this node.'
    )
    auto_retrieve_batch_size = models.PositiveIntegerField(
        default=50,
        help_text='Number of patients processed in one batch task during the periodic sweep.'
    )
    patient_id_transforms = models.JSONField(
        default=list, blank=True,
        help_text='Ordered transform rules applied to the local patient ID to generate '
                  'remote-ID candidates for C-FIND. Each rule: '
                  '{"pattern": "<regex>", "replacement": "<replacement>"} — e.g. '
                  '{"pattern": "^MR/(\\d+)/(\\d+)$", "replacement": "\\1_\\2"} turns '
                  'MR/25/004771 into 25_004771.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    _CRON_FIELD_RE = re.compile(r'^[\d\-\,\*/]+$')

    @property
    def crontab_tuple(self):
        return (
            self.auto_retrieve_minute,
            self.auto_retrieve_hour,
            self.auto_retrieve_day_of_week,
            self.auto_retrieve_day_of_month,
            self.auto_retrieve_month_of_year,
        )

    def clean(self):
        super().clean()
        self.host = (self.host or '').strip()
        for name, value in [
            ('auto_retrieve_minute', self.auto_retrieve_minute),
            ('auto_retrieve_hour', self.auto_retrieve_hour),
            ('auto_retrieve_day_of_week', self.auto_retrieve_day_of_week),
            ('auto_retrieve_day_of_month', self.auto_retrieve_day_of_month),
            ('auto_retrieve_month_of_year', self.auto_retrieve_month_of_year),
        ]:
            if not self._CRON_FIELD_RE.match(value or ''):
                raise ValidationError({name: 'Invalid cron field value.'})

    def patient_id_aliases_for(self, patient):
        return list(
            self.patient_aliases.filter(patient=patient)
            .values_list('remote_patient_id', flat=True)
        )

    def remote_patient_ids_for(self, patient, extra_transforms=None):
        """Ordered, deduped candidate remote PatientIDs for C-FIND:
        canonical patient_id, then PatientIDAlias rows, then transform outputs."""
        from dicom_server.services import patient_ids
        ids = [patient.patient_id]
        ids += self.patient_id_aliases_for(patient)
        ids += patient_ids.apply_transforms(
            patient.patient_id,
            (self.patient_id_transforms or []) + list(extra_transforms or []),
        )
        return list(dict.fromkeys(ids))

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
    batch = models.ForeignKey(
        'RetrievalBatch', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='jobs',
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


class RetrievalJobStudy(models.Model):
    """One study targeted by a retrieval job. Carries C-FIND metadata and
    retrieval outcome so the job detail view and ingest can use it."""
    job = models.ForeignKey(
        RetrievalJob, on_delete=models.CASCADE, related_name='studies',
    )
    study_instance_uid = models.CharField(max_length=255)
    remote_patient_id = models.CharField(max_length=255, null=True, blank=True)
    # C-FIND metadata
    study_date = models.DateField(null=True, blank=True)
    study_description = models.CharField(max_length=255, null=True, blank=True)
    modalities = models.CharField(max_length=255, null=True, blank=True)
    accession_number = models.CharField(max_length=255, null=True, blank=True)
    # Retrieval outcome (populated by _run_job_retrieval)
    status = models.CharField(max_length=20, null=True, blank=True)
    completed = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    warning = models.IntegerField(default=0)

    class Meta:
        unique_together = ['job', 'study_instance_uid']
        ordering = ['study_instance_uid']

    def __str__(self):
        return f'{self.job_id} / {self.study_instance_uid[:20]}'


class RetrievalJobSeries(models.Model):
    """One series targeted within a RetrievalJobStudy. Empty set = whole study."""
    study = models.ForeignKey(
        RetrievalJobStudy, on_delete=models.CASCADE, related_name='series',
    )
    series_instance_uid = models.CharField(max_length=255)
    # C-FIND metadata
    series_description = models.CharField(max_length=255, null=True, blank=True)
    modality = models.CharField(max_length=16, null=True, blank=True)
    series_date = models.DateField(null=True, blank=True)
    # Retrieval outcome
    status = models.CharField(max_length=20, null=True, blank=True)
    completed = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    warning = models.IntegerField(default=0)

    class Meta:
        unique_together = ['study', 'series_instance_uid']
        ordering = ['series_instance_uid']

    def __str__(self):
        return f'{self.study_id} / {self.series_instance_uid[:20]}'


class PatientIDAlias(models.Model):
    """A remote PatientID used for a given patient at a given node."""
    node = models.ForeignKey(
        RemoteDICOMNode, on_delete=models.CASCADE, related_name='patient_aliases'
    )
    patient = models.ForeignKey(
        'client_app.Patient', on_delete=models.CASCADE, related_name='dicom_patient_aliases'
    )
    remote_patient_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [
            ['node', 'patient', 'remote_patient_id'],
            ['node', 'remote_patient_id'],
        ]
        verbose_name = 'Patient ID alias'
        verbose_name_plural = 'Patient ID aliases'

    def __str__(self):
        return f'{self.patient.patient_id} @ {self.node.name} = {self.remote_patient_id}'


class AutoRetrievalState(models.Model):
    """Throttle/audit record for automated retrieval of one patient from one node."""
    patient = models.ForeignKey(
        'client_app.Patient', on_delete=models.CASCADE, related_name='auto_retrieval_states'
    )
    node = models.ForeignKey(
        RemoteDICOMNode, on_delete=models.CASCADE, related_name='auto_retrieval_states'
    )
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_known_study_uids = models.JSONField(default=list, blank=True)

    class Meta:
        unique_together = ('patient', 'node')
        verbose_name = 'Auto-retrieval state'
        verbose_name_plural = 'Auto-retrieval states'

    def __str__(self):
        return f'{self.patient.patient_id} / {self.node.name}'


class RetrievalBatch(models.Model):
    """One bulk query -> select -> retrieve session from the bulk retrieval UI.

    Serves both as the transient query session (patients' remote studies are
    discovered) and as the audit log for the retrieval run."""
    class Status(models.TextChoices):
        QUERYING = 'QUERYING', 'Querying remote node'
        AWAITING_SELECTION = 'AWAITING_SELECTION', 'Awaiting selection'
        RETRIEVING = 'RETRIEVING', 'Retrieving'
        SUCCESS = 'SUCCESS', 'Success'
        PARTIAL = 'PARTIAL', 'Partial'
        FAILED = 'FAILED', 'Failed'

    node = models.ForeignKey(
        RemoteDICOMNode, on_delete=models.PROTECT, related_name='retrieval_batches',
    )
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.QUERYING,
    )
    extra_transforms = models.JSONField(
        default=list, blank=True,
        help_text='Ad-hoc transform rules applied to this query only (same '
                  '{pattern, replacement} shape as node.patient_id_transforms).',
    )
    query_group_id = models.CharField(max_length=255, blank=True, default='')
    retrieve_group_id = models.CharField(max_length=255, blank=True, default='')
    summary = models.JSONField(
        null=True, blank=True,
        help_text='Aggregate counts + patient lists: {total, succeeded, '
                  'partial, failed, skipped, instances}',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Batch {self.pk} {self.node.name} [{self.status}]'


class RetrievalBatchPatient(models.Model):
    """One patient's query results and linked retrieval job within a batch."""
    class QueryStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        QUERYING = 'QUERYING', 'Querying'
        DONE = 'DONE', 'Done'
        ERROR = 'ERROR', 'Error'

    batch = models.ForeignKey(
        RetrievalBatch, on_delete=models.CASCADE, related_name='patients',
    )
    patient = models.ForeignKey(
        'client_app.Patient', on_delete=models.PROTECT,
        related_name='retrieval_batch_rows',
    )
    remote_patient_ids = models.JSONField(
        default=list, blank=True,
        help_text='Remote PatientIDs actually queried for this patient.',
    )
    query_status = models.CharField(
        max_length=10, choices=QueryStatus.choices,
        default=QueryStatus.PENDING,
    )
    studies = models.JSONField(
        null=True, blank=True,
        help_text='Study->series tree: [{study_instance_uid, study_date, '
                  'study_description, accession_number, modalities, instances, '
                  'remote_patient_id, already_local, series_error?, series: ['
                  '{series_instance_uid, series_description, modality, '
                  'series_number, series_date, accession_number, instances, '
                  'rt_error?, instances_error?, parent_series_uids?, '
                  'unresolved_refs?, rt_instances?: [{sop_instance_uid, '
                  'instance_number, structure_set_label, structure_set_name, '
                  'rt_plan_label, rt_plan_name, approval_status, '
                  'referenced_series_uids, referenced_structure_set_uids, '
                  'referenced_plan_uids}]}]}]',
    )
    error = models.TextField(blank=True, default='')
    selected = models.BooleanField(default=False)
    job = models.ForeignKey(
        RetrievalJob, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='batch_rows',
    )

    class Meta:
        unique_together = ['batch', 'patient']
        ordering = ['patient_id']

    def __str__(self):
        return f'{self.patient_id} @ batch {self.batch_id} [{self.query_status}]'


class BulkRetrievalSchedule(models.Model):
    """A saved, off-peak plan to bulk-query + retrieve a set of patients from a
    node. Runs either once (ONE_OFF, dispatched with an eta) or repeatedly
    (PERIODIC, a django_celery_beat.PeriodicTask). Retrieval is capped at
    ``max_concurrent_patients`` so remote nodes are not stressed."""
    class Mode(models.TextChoices):
        ONE_OFF = 'ONE_OFF', 'One-off (run once at a set time)'
        PERIODIC = 'PERIODIC', 'Periodic (repeats on a schedule)'

    name = models.CharField(max_length=200)
    node = models.ForeignKey(
        RemoteDICOMNode, on_delete=models.PROTECT, related_name='bulk_schedules',
    )
    patients = models.ManyToManyField(
        'client_app.Patient', related_name='bulk_schedules',
    )
    extra_transforms = models.JSONField(default=list, blank=True)
    mode = models.CharField(
        max_length=10, choices=Mode.choices, default=Mode.ONE_OFF,
    )
    # One-off timing
    run_at = models.DateTimeField(null=True, blank=True)
    # Periodic crontab (same field format as RemoteDICOMNode)
    minute = models.CharField(max_length=20, default='0')
    hour = models.CharField(max_length=20, default='2')
    day_of_week = models.CharField(max_length=20, default='*')
    day_of_month = models.CharField(max_length=20, default='*')
    month_of_year = models.CharField(max_length=20, default='*')
    max_concurrent_patients = models.PositiveIntegerField(
        default=2,
        help_text='Max patients retrieved at the same time (per chunk).',
    )
    retrieve_new_only = models.BooleanField(
        default=True,
        help_text='When set, only retrieve studies not already stored locally.',
    )
    # ---- Declarative selection criteria (empty = no constraint on that axis) ----
    select_modalities = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Comma-separated modalities to retrieve, e.g. "CT,MR,RTPLAN". Empty = all.',
    )
    select_approval = models.CharField(
        max_length=12, blank=True, default='',
        choices=[('', 'Any'), ('approved', 'Approved only'), ('unapproved', 'Not approved')],
        help_text='RT plan approval filter (RTDOSE inherits its parent plan\'s verdict).',
    )
    select_series_description = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Only series whose description contains this text (case-insensitive).',
    )
    select_rt_label = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Only RT series whose plan/structure-set label or name contains this text.',
    )
    study_date_from = models.DateField(null=True, blank=True)
    study_date_to = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
    )
    is_active = models.BooleanField(default=True)
    one_off_task_id = models.CharField(max_length=255, blank=True, default='')
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True, default='')
    last_batch = models.ForeignKey(
        'RetrievalBatch', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='schedule_runs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    _CRON_FIELD_RE = re.compile(r'^[\d\-\,\*/]+$')

    @property
    def crontab_tuple(self):
        return (
            self.minute, self.hour, self.day_of_week,
            self.day_of_month, self.month_of_year,
        )

    @property
    def beat_name(self):
        return f'dicom-bulk-schedule-{self.pk}'

    @property
    def schedule_display(self):
        if self.mode == self.Mode.ONE_OFF:
            return (
                f"once at {self.run_at:%Y-%m-%d %H:%M %Z}" if self.run_at
                else 'one-off (no time set)'
            )
        return (
            f"cron: {self.minute} {self.hour} {self.day_of_month} "
            f"{self.month_of_year} {self.day_of_week}"
        )

    def selection_criteria(self):
        from dicom_server.services import bulk_selection
        mods = [
            m.strip()
            for m in (self.select_modalities or '').replace(',', ' ').split()
            if m.strip()
        ]
        return bulk_selection.SelectionCriteria(
            modalities=mods,
            approval=self.select_approval or '',
            series_description=(self.select_series_description or '').strip(),
            rt_label=(self.select_rt_label or '').strip(),
            study_date_from=self.study_date_from.isoformat() if self.study_date_from else '',
            study_date_to=self.study_date_to.isoformat() if self.study_date_to else '',
        )

    def clean(self):
        super().clean()
        for name, value in [
            ('minute', self.minute), ('hour', self.hour),
            ('day_of_week', self.day_of_week),
            ('day_of_month', self.day_of_month),
            ('month_of_year', self.month_of_year),
        ]:
            if not self._CRON_FIELD_RE.match(value or ''):
                raise ValidationError({name: 'Invalid cron field value.'})
        if self.mode == self.Mode.ONE_OFF and not self.run_at:
            raise ValidationError({'run_at': 'Required for one-off schedules.'})

    def __str__(self):
        return f'{self.name} [{self.get_mode_display()}]'

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Bulk retrieval schedule'
        verbose_name_plural = 'Bulk retrieval schedules'

