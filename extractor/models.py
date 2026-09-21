import os
import uuid
from pathlib import Path
from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.core.validators import FileExtensionValidator,URLValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField, EncryptedTextField
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from pgvector.django import VectorField
from extractor.services.url_policy import normalize_base_url, validate_base_url
from logging import getLogger

log = getLogger(__name__)

class FileTypeChoices(models.TextChoices):
    PDF = 'pdf', 'PDF'
    CSV = 'csv', 'CSV'
    EXCEL = 'excel', 'Excel'

class ProcessingStatusChoices(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'

# Create your models here.

class ClientConfiguration(models.Model):
    '''
    A client configuration stores the necessary information such that Instructor can connect to the large language models.
    '''
    llm_model_name = models.CharField(max_length=100,help_text="Name of the LLM model to use")
    model_provider = models.CharField(max_length=100,help_text="Provider of the LLM model")
    model_api_key = EncryptedCharField(max_length=512,help_text="API key for the LLM model")
    model_api_key_expires = models.BooleanField(default=False,help_text="Whether the API key expires")
    model_api_key_validity = models.DateTimeField(null=True,blank=True,help_text="Validity date of the API key")
    model_api_refresh_key = EncryptedCharField(max_length=512,null=True,blank=True,help_text="Refresh key for the API key")
    model_base_url = models.CharField(max_length=255, validators=[URLValidator()])
    request_timeout = models.PositiveIntegerField(default=60, help_text="Seconds to wait for a provider response before failing")
    context_size = models.PositiveIntegerField(default=8192, help_text="Model context window in tokens; prompts larger than this are refused rather than silently truncated")
    model_max_tokens = models.PositiveIntegerField(default=4096, help_text="Maximum tokens in a single provider response")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        self.model_base_url = validate_base_url(self.model_base_url, 'model base URL')
        if self.model_api_key_expires:
            errors = {}
            if not self.model_api_key_validity:
                errors['model_api_key_validity'] = 'Validity date is required when API key can expire.'
            if not self.model_api_refresh_key:
                errors['model_api_refresh_key'] = 'Refresh key is required when API key can expire.'
            if errors:
                raise ValidationError(errors)

    def api_key_expired(self):
        """True when the key is marked as expiring and its validity date has passed."""
        return bool(self.model_api_key_expires and self.model_api_key_validity
                    and self.model_api_key_validity < timezone.now())

    def __str__(self):
        return self.llm_model_name

    class Meta:
        ordering = ['-created_at']


def file_upload_path(instance, filename):
    '''
    Store uploads under an opaque generated name so the original filename
    (which may contain patient identifiers) never reaches disk or logs.
    '''
    ext = os.path.splitext(filename)[1].lower()
    return f'uploads/{uuid.uuid4().hex}{ext}'


class FileUpload(models.Model):
    '''
    This model stores information about uploaded files from which data will be extracted. This file text will be provided to the instructor as a structured data input after processing. Note that for some formats the file itself will be provided.
    '''
    file = models.FileField(upload_to=file_upload_path, validators=[FileExtensionValidator(['pdf', 'csv', 'xlsx'])])
    original_filename = models.CharField(max_length=512, blank=True, help_text="Filename as uploaded; stored for display only.")
    file_type = models.CharField(max_length=100, choices=FileTypeChoices.choices, blank=True)
    patient_id = models.ForeignKey('client_app.Patient', on_delete=models.CASCADE, null=True, blank=True, help_text="Please select the patient for whose data is being extracted.")
    processing_status = models.CharField(max_length=100, choices=ProcessingStatusChoices.choices, default=ProcessingStatusChoices.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    EXTENSION_TO_FILE_TYPE = {
        '.pdf': FileTypeChoices.PDF,
        '.csv': FileTypeChoices.CSV,
        '.xlsx': FileTypeChoices.EXCEL,
    }

    def save(self, *args, **kwargs):
        '''
        This is a function that will automatically extract the extension from the file name and save it.
        '''
        if self.file:
            ext = os.path.splitext(self.file.name)[1].lower()
            file_type = self.EXTENSION_TO_FILE_TYPE.get(ext)
            self.file_type = file_type
            if not self.original_filename:
                self.original_filename = os.path.basename(self.file.name)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        '''
        Override delete to remove the physical file from disk when the model instance is deleted.
        '''
        if self.file:
            if os.path.isfile(self.file.path):
                os.remove(self.file.path)
                log.info(f"Deleted file from disk for upload {self.id}")
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.original_filename or self.file.name

    class Meta:
        ordering = ['-created_at']

class ProcessedText(models.Model):
    '''
    This model stores information about processed file from an uploaded text file.
    '''
    file_upload = models.ForeignKey(FileUpload, on_delete=models.CASCADE)
    processed_file_path = models.CharField(max_length = 512, null=True, blank=True)
    processed_by_user = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True, help_text="The user who processed this file.")
    source_sheet = models.CharField(max_length=255, blank=True, help_text="Worksheet name when derived from an Excel workbook.")
    content_length = models.IntegerField(default=0, help_text="Length of the extracted text content in characters.")
    processing_warning = models.CharField(max_length=255, blank=True, help_text="Non-fatal processing caveat, e.g. 'no_text' or 'encoding_fallback'.")
    version = models.IntegerField(default=1, help_text="Processing version; increments on reprocessing.")
    is_source_alias = models.BooleanField(default=False, help_text="True when this row points at the original upload rather than a derived file.")
    ocr_applied = models.BooleanField(default=False, help_text="True when this version's text was produced by OCR rather than direct text extraction.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def resolve_path(self):
        '''
        Resolve processed_file_path against MEDIA_ROOT, rejecting absolute
        paths and traversal outside the media directory.
        '''
        if not self.processed_file_path:
            return None
        media_root = Path(settings.MEDIA_ROOT).resolve()
        candidate = (media_root / self.processed_file_path).resolve()
        if media_root != candidate and media_root not in candidate.parents:
            raise ValidationError(f"Processed file path escapes MEDIA_ROOT: {self.processed_file_path}")
        return candidate

    def __str__(self):
        if self.file_upload_id and self.file_upload.original_filename:
            return self.file_upload.original_filename
        return f"ProcessedText {self.pk}"

    class Meta:
        ordering = ['-created_at']


def _delete_processed_file(sender, instance, **kwargs):
    '''
    Remove the derived file from disk on every deletion path (model delete,
    queryset delete, cascade). Source aliases are skipped: the file belongs to
    the FileUpload and is removed with it.
    '''
    if instance.is_source_alias:
        return
    try:
        file_path = instance.resolve_path()
        if file_path and file_path.is_file():
            file_path.unlink()
            log.info(f"Deleted processed file for ProcessedText {instance.id}")
    except Exception as e:
        log.error(f"Error deleting processed file for ProcessedText {instance.id}: {e}")


post_delete.connect(_delete_processed_file, sender=ProcessedText)

class EntityTypeChoices(models.TextChoices):
    STRING = 'str', 'string'
    BOOLEAN = 'bool', 'boolean'
    FLOAT = 'float', 'float'
    INTEGER = 'int', 'integer'
    DICTIONARY = 'dict', 'dict'
    TUPLE = 'tuple', 'tuple'
    LIST = 'list', 'list'
    DATE = 'datetime.date', 'date'
    DATETIME = 'datetime.datetime','datetime'
    TIMEDELTA = 'datetime.timedelta','timedelta'
    TIME = 'datetime.time','time'


class DatabaseTable(models.Model):
    '''
    A database table refers to the Django model in the Clientapp for which data is to be extracted. Uses ContentType for referential integrity.
    '''
    clientapp_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, limit_choices_to={'app_label': 'client_app'}, help_text="The client_app model to which this table refers")
    clientapp_table_pk_field_name = models.CharField(max_length=512, help_text="This is the name of field which has the primary key for the table.")
    clientapp_table_fk_fields = models.JSONField(help_text="This a JSON representation of the FK field relationships for the table. It stores the FK relationship between the table and the patient table. Note that the FK relationship can traverse multiple intermediate tables. However the Patient table is the primary table.",null=True,blank=True)
    date_validation_pairs = models.JSONField(null=True, blank=True, help_text="Pairs of (start_date_field, end_date_field) captured from the source model's date_validation_pairs; enforced on extracted records.")
    match_fields = models.JSONField(null=True, blank=True, help_text="Ordered key-sets for duplicate detection before write-back, e.g. [['diagnosis','diagnosis_date']]. Populated from defaults; admin-editable.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.clientapp_content_type.app_label}.{self.clientapp_content_type.model}"

    def clean(self):
        if self.clientapp_content_type:
            try:
                model = self.clientapp_content_type.model_class()
                if model:
                    field_names = [f.name for f in model._meta.get_fields()]
                    
                    if self.clientapp_table_pk_field_name and self.clientapp_table_pk_field_name not in field_names:
                        raise ValidationError({
                            'clientapp_table_pk_field_name': f'PK field "{self.clientapp_table_pk_field_name}" does not exist on {model.__name__}. Available fields: {", ".join(field_names)}'
                        })
            except Exception:
                pass

    class Meta:
        verbose_name = "Entity Table (Database Table)"
        verbose_name_plural = "Entity Tables (Database Tables)"
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['clientapp_content_type'], name='unique_clientapp_content_type')]


class DatabaseField(models.Model):
    '''
    An database field from the client_app application. A collection of fields will be used to make up a response model for Instructor to use. There will also be validation rules which will be extracted from the model definition. Additionally this model will also specify the lookup table, its primary key field name and the value field name if this field is a lookup field.
    '''
    clientapp_database_table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE)
    clientapp_field_name = models.CharField(max_length=512,help_text="Select the client app Field which is to be extracted")
    field_type = models.CharField(max_length=512, choices=EntityTypeChoices.choices,help_text="Select the type of Field value which is stored in the database")
    field_validation = models.JSONField(help_text="This field will store any additional validation that has been defined for the CHAVI field. This would be converted to pydantic format and used for validating the model output.",null=True,blank=True)
    lookup_field = models.BooleanField(default=False, help_text="The client app database has an extensive number of fields which are linked to lookup tables. These fields need to be extracted with the lookup table data being provided as an enumerated list or a related table in the instructor extraction system.")
    lookup_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, limit_choices_to={'app_label': 'lookup'}, help_text="The lookup table to which this field is linked")
    lookup_table_value_field_name = models.CharField(max_length=512, blank=True, null=True, help_text="The field containing the value which is to be matched / extracted using Instructor")
    lookup_table_pk_field_name = models.CharField(max_length=512, blank=True, null=True, help_text="The field containing the primary key to which the data will be linked")
    lookup_label_fields = models.JSONField(null=True, blank=True, help_text="Ordered list of lookup fields joined into the display label (e.g. ['ctcae_grade','ctcae_description'] -> 'Grade 3 — Severe'). Empty means use lookup_table_value_field_name alone.")
    lookup_config_source = models.CharField(max_length=10, choices=[('auto', 'Auto-discovered'), ('manual', 'Manual')], default='auto', help_text="'auto' = schema discovery may update the lookup field choices; 'manual' = a human set them and discovery must not overwrite.")
    relation_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True, related_name='extractor_field_relations', help_text="For non-lookup relationship fields: the model this FK points at (e.g. diagnosis for pathology.diagnosis)")
    relation_pk_field = models.CharField(max_length=512, blank=True, null=True, help_text="Primary key field on the related model this FK links to")
    help_text = models.CharField(max_length=512, blank=True, help_text="Help text captured from the source model field; shown to the LLM at extraction time.")
    is_active = models.BooleanField(default=True, help_text="False when the field no longer exists on the source model after re-discovery.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.clientapp_database_table}.{self.clientapp_field_name}"

    def is_extractable(self):
        """
        Whether this field should be sent to the LLM for extraction.

        Excluded:
        - internal relationship fields (non-lookup FKs like pathology.diagnosis)
          — write-back resolves them from parent_record, never from text
        - auto-generated primary keys (uuid default / non-editable, e.g.
          chavi_*_id UUIDs and auto 'id') — generated on save, not document
          content. Natural-key PKs without a default (e.g. study_instance_uid)
          stay extractable.
        """
        if (self.field_validation or {}).get('is_relationship'):
            return False

        table = self.clientapp_database_table
        if table and self.clientapp_field_name == (table.clientapp_table_pk_field_name or ''):
            model_class = table.clientapp_content_type.model_class()
            if model_class:
                try:
                    mf = model_class._meta.get_field(self.clientapp_field_name)
                    if mf.has_default() or not mf.editable:
                        return False
                except Exception:
                    pass
        return True

    def clean(self):
        errors = {}
        
        # Validate that clientapp_field_name exists on the target model
        if self.clientapp_database_table and self.clientapp_field_name:
            try:
                table_model = self.clientapp_database_table.clientapp_content_type.model_class()
                if table_model:
                    field_names = [f.name for f in table_model._meta.get_fields()]
                    if self.clientapp_field_name not in field_names:
                        errors['clientapp_field_name'] = f'Field "{self.clientapp_field_name}" does not exist on {table_model.__name__}. Available fields: {", ".join(field_names)}'
            except Exception:
                pass  # Model may not exist, skip validation
        
        # Validate lookup field requirements
        if self.lookup_field:
            if not self.lookup_content_type:
                errors['lookup_content_type'] = 'Lookup table is required when lookup_field is True.'
            if not self.lookup_table_value_field_name:
                errors['lookup_table_value_field_name'] = 'Lookup table value field name is required when lookup_field is True.'
            if not self.lookup_table_pk_field_name:
                errors['lookup_table_pk_field_name'] = 'Lookup table PK field name is required when lookup_field is True.'
            
            # Validate that specified fields exist on the lookup model
            if self.lookup_content_type:
                try:
                    lookup_model = self.lookup_content_type.model_class()
                    if lookup_model:
                        field_names = [f.name for f in lookup_model._meta.get_fields()]
                        
                        if self.lookup_table_value_field_name and self.lookup_table_value_field_name not in field_names:
                            errors['lookup_table_value_field_name'] = f'Field "{self.lookup_table_value_field_name}" does not exist on {lookup_model.__name__}. Available fields: {", ".join(field_names)}'
                        
                        if self.lookup_table_pk_field_name and self.lookup_table_pk_field_name not in field_names:
                            errors['lookup_table_pk_field_name'] = f'Field "{self.lookup_table_pk_field_name}" does not exist on {lookup_model.__name__}. Available fields: {", ".join(field_names)}'
                except Exception:
                    pass  # Model may not exist, skip field validation
        
        if errors:
            raise ValidationError(errors)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['clientapp_database_table', 'clientapp_field_name'], name='unique_entity_per_table')]
        verbose_name = "Database Table Field"
        verbose_name_plural = "Database Table Fields"
        ordering = ['-created_at']


class ResponseModel(models.Model):
    '''
    A response model is used to define a pydantic model which will be used by instructor to extract the data using LLM. This model will be created from tables and fields in the ResponseModelTable and ResponseModelTableField models.
    '''
    client = models.ForeignKey(ClientConfiguration, on_delete=models.CASCADE,help_text="Client configuration used for data extraction")
    name = models.CharField(max_length=512, help_text="Name of the response model")
    is_complete = models.BooleanField(default=True, help_text="False while the model is mid-wizard (tables/fields not yet chosen); incomplete models are hidden from extraction lists")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"ResponseModel - {self.name} - {self.client.llm_model_name}"

    class Meta:
        ordering = ['-created_at']


class InstructorRole(models.TextChoices):
    '''
    A role is specified for instructor messages for data extraction.
    '''
    SYSTEM = "system", "System"
    USER = "user", "User"


class ResponseModelTable(models.Model):
    '''
    This model is used to define the tables that are selected for extraction in a response model.
    '''
    response_model = models.ForeignKey(ResponseModel, on_delete=models.CASCADE,help_text="Response model for which the fields are defined")
    database_table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE,help_text="Database table for which the response model is defined")
    auto_added = models.BooleanField(default=False, help_text="True when this table was auto-included as a required ancestor of a selected table")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.response_model} - {self.database_table}"

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['response_model', 'database_table'], name='unique_response_model_database_table')]

class ResponseModelTableField(models.Model):
    '''
    This model is used to define the fields that are selected for extraction in a response model for a specific table.
    '''
    response_model_table = models.ForeignKey(ResponseModelTable, on_delete=models.CASCADE,help_text="Response model table for which the fields are defined")
    field = models.ForeignKey(DatabaseField, on_delete=models.CASCADE,help_text="Database field for which the response model is defined")
    order = models.PositiveIntegerField(default=0, help_text="Order of the field in the response model")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.response_model_table} - {self.field}"

    def clean(self):
        if self.field and self.response_model_table:
            expected_table = self.response_model_table.database_table
            actual_table = self.field.clientapp_database_table
            if expected_table != actual_table:
                raise ValidationError({
                    'field': f'Field "{self.field}" does not belong to table "{expected_table}". It belongs to "{actual_table}".'
                })

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['response_model_table', 'field'], name='unique_response_model_table_field')]


class InstructorMessage(models.Model):
    '''
    This will be storing the prepared prompts which will be passed on to Instructor as a system prompt in a message format such that the data can be extracted.
    '''
    response_model = models.ForeignKey(ResponseModel, on_delete=models.CASCADE,help_text="Response model for which the message is defined")
    role = models.CharField(max_length=10, choices=InstructorRole.choices, help_text="Role of the message sender. The default value is system.", default=InstructorRole.SYSTEM)
    prompt = models.JSONField(help_text="The prompt to be used for data extraction to be passed onto Instructor. Stored as JSON in database.")
    order = models.PositiveIntegerField(default=0, help_text="Explicit ordering of messages; lower numbers are sent first.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.response_model} - {self.role}"

    class Meta:
        ordering = ['order', 'created_at']

class ExtractionStatusChoices(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    AWAITING_MINING = "awaiting_mining", "Awaiting approval: lookup mining"
    AWAITING_EXTRACTION = "awaiting_extraction", "Awaiting approval: extraction"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    PARTIAL = "partial", "Partial"

class ExtractionJob(models.Model):
    '''
    This will store the data about the extraction job as well as the tokens used for the extraction and the raw response received from the LLM.
    '''
    response_model = models.ForeignKey(ResponseModel, on_delete=models.CASCADE,help_text="Response model for which the extraction is being performed")
    processed_file = models.ForeignKey(ProcessedText, on_delete=models.CASCADE,help_text="The processed text from which the data has been extracted")
    processed_file_chunked = models.BooleanField(default=False, help_text="Whether the processed file has been chunked")
    extraction_start_datetime = models.DateTimeField(null=True, blank=True, help_text="When the extraction started")
    extraction_end_datetime = models.DateTimeField(null=True, blank=True, help_text="When the extraction ended")
    extraction_status = models.CharField(max_length=50, choices=ExtractionStatusChoices.choices, default=ExtractionStatusChoices.PENDING)
    extraction_error = models.TextField(blank=True, null=True, help_text="Error message if extraction failed")
    tokens_used = models.PositiveIntegerField(help_text="Number of tokens used for extraction",null=True,blank=True)
    raw_llm_response = EncryptedTextField(help_text="Raw LLM response as a JSON string, encrypted like extracted_data. For debugging only.",null=True,blank=True)
    input_content_hash = models.CharField(max_length=64, blank=True, help_text="SHA-256 of the processed text this job ran on")
    prompt_snapshot = models.TextField(blank=True, help_text="The exact messages sent to the model (frozen at dispatch)")
    config_snapshot = models.JSONField(null=True, blank=True, help_text="Provider/model/schema version frozen at dispatch")
    retry_count = models.PositiveIntegerField(default=0, help_text="How many instructor retries the provider call used")
    stage_trace = models.JSONField(default=list, blank=True, help_text="Ordered stage artifacts: prompt/result entries shown on the job detail page")
    extracted_by = models.ForeignKey(User, on_delete=models.CASCADE,help_text="User who performed the extraction")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.response_model} - {self.created_at}"

    class Meta:
        ordering = ['-created_at']


class DataAccuracyChoices(models.TextChoices):
    '''
    This will store the accuracy of the extracted data
    '''
    UNREVIEWED = "unreviewed", "Unreviewed"
    ACCURATE = "accurate", "Accurate"
    PARTIAL = "partial", "Partial"
    INACCURATE = "inaccurate", "Inaccurate"


class ResultStateChoices(models.TextChoices):
    '''
    Whether an extraction result row carries a found value.
    '''
    EXTRACTED = "extracted", "Extracted"
    NOT_FOUND = "not_found", "Not found"
    UNRESOLVED = "unresolved", "Unresolved lookup"

class ExtractedRecord(models.Model):
    '''
    One extracted record (one row of a clinical table) produced by an extraction
    job. A document may yield several records per table — e.g. two diagnoses.
    '''
    extraction_job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE, related_name='extracted_records', help_text="Extraction job that produced this record")
    database_table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE, help_text="The table this record belongs to")
    parent_record = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='child_records', help_text="The extracted parent record this record belongs to (nested extraction)")
    record_index = models.PositiveIntegerField(default=0, help_text="Position of this record within the table's extracted list")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.database_table} record {self.record_index} (job {self.extraction_job_id})"

    class Meta:
        ordering = ['database_table', 'record_index']


class ExtractionResult(models.Model):
    '''
    This will store the extracted data for a specific field. We will also store the details of who verified the data and if the extracted data was correct or not. If the extracted data was edited then it will also be corrected.
    '''
    extraction_job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE,help_text="Extraction job for which the data has been extracted")
    database_field = models.ForeignKey(DatabaseField, on_delete=models.CASCADE,help_text="Database table field for which the data has been extracted")
    record = models.ForeignKey(ExtractedRecord, on_delete=models.CASCADE, null=True, blank=True, related_name='results', help_text="The extracted record this value belongs to")
    extracted_data = EncryptedTextField(help_text="Extracted data after Instructor parses the text. This will be stored as an encrypted text.")
    result_state = models.CharField(max_length=20, choices=ResultStateChoices.choices, default=ResultStateChoices.EXTRACTED, help_text="extracted / not_found / unresolved-lookup")
    data_accuracy = models.CharField(max_length=50, choices=DataAccuracyChoices.choices, default=DataAccuracyChoices.UNREVIEWED)
    data_edited = models.BooleanField(default=False, help_text="Whether the data was edited by the user")
    edited_data = EncryptedTextField(help_text="Edited data after user edits the extracted data. This will be stored as an encrypted text.",null=True,blank=True)
    revision_history = models.JSONField(default=list, blank=True, help_text="Audit trail of review actions: [{action, old, new, user, at}]")
    evidence = EncryptedTextField(null=True, blank=True, help_text="Source-text snippet where this value was found in the processed document; encrypted like extracted_data. Empty when the value couldn't be located verbatim.")
    verified_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, help_text="User who verified the data")
    verification_date_time = models.DateTimeField(help_text="Date and time when the data was verified",null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.database_field} - {self.created_at}"

    class Meta:
        ordering = ['-created_at']

class RecordOperationChoices(models.TextChoices):
    CREATE = "create", "Create"
    UPDATE = "update", "Update"

class RecordCreation(models.Model):
    '''
    This will store the record creation or update from a specific extraction job for a specific table.
    One RecordCreation entry represents one actual record created or updated in client_app (e.g., one Diagnosis).
    '''
    extraction_job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE,help_text="Extraction job that produced this record")
    database_table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE,help_text="The table for which the record was created")
    extracted_record = models.ForeignKey(ExtractedRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='record_creations', help_text="The extracted record that was written back")
    created_record_pk = models.CharField(max_length=255, help_text="The actual primary key of the created/updated record in client_app")
    operation = models.CharField(max_length=20, choices=RecordOperationChoices.choices, default=RecordOperationChoices.CREATE, help_text="Whether this was a create or update operation")
    record_created = models.BooleanField(default=False, help_text="Whether the record operation was successful")
    record_created_by = models.ForeignKey(User, on_delete=models.CASCADE,help_text="User who performed the record operation")
    record_created_at = models.DateTimeField(auto_now_add=True, help_text="When the record operation was performed")
    record_created_error = models.TextField(blank=True, null=True, help_text="Error message if record operation failed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.database_table} - {self.created_record_pk} - {self.operation} - {self.record_created_at}"

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['extraction_job', 'database_table', 'created_record_pk', 'operation'], name='unique_record_operation_per_extraction')]


class RecordCreationField(models.Model):
    '''
    Links specific extracted fields to the record they were used to create/update.
    This allows tracking which ExtractionResult values were applied to which RecordCreation.
    '''
    record_creation = models.ForeignKey(RecordCreation, on_delete=models.CASCADE,help_text="The record creation this field belongs to")
    extraction_result = models.ForeignKey(ExtractionResult, on_delete=models.CASCADE,help_text="The extracted field value")
    previous_value = models.TextField(blank=True, null=True, help_text="Previous value before update (for update operations)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.record_creation} - {self.extraction_result.database_field}"

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['record_creation', 'extraction_result'], name='unique_field_per_record_creation')]


class EmbeddingConfiguration(models.Model):
    '''
    Configuration for the embedding model used for semantic search in lookup matching.
    '''
    model_name = models.CharField(
        max_length=255,
        help_text="Name of the embedding model (e.g., 'all-MiniLM-L6-v2', 'BioBERT')"
    )
    model_provider = models.CharField(
        max_length=100,
        default='sentence-transformers',
        help_text="Provider: 'sentence-transformers', 'openai', 'huggingface'"
    )
    embedding_dimension = models.IntegerField(
        help_text="Dimension of the embedding vectors (e.g., 384, 768, 1536)"
    )
    api_key = EncryptedCharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Provider credential: API key for OpenAI endpoints, or a Hugging Face access token (hf_..., created at hf.co/settings/tokens) for local sentence-transformers models"
    )
    base_url = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Base URL for OpenAI-compatible embedding endpoints (leave blank for api.openai.com)"
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Index generation. New builds write under version+1 and only become live when the build succeeds."
    )
    candidate_threshold = models.FloatField(
        default=0.5,
        help_text="Minimum similarity (0-1) when picking candidate options to show the LLM — looser than match threshold"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this configuration is currently active"
    )
    similarity_threshold = models.FloatField(
        default=0.7,
        help_text="Minimum similarity score (0-1) for considering a match valid"
    )
    top_k_results = models.IntegerField(
        default=5,
        help_text="Number of top similar results to show to LLM"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        # Optional endpoint for OpenAI-compatible providers; blank means api.openai.com
        if self.base_url:
            self.base_url = validate_base_url(self.base_url, 'embedding base URL')
        # The vector column is dimensionless — each config declares its own
        # dimension and providers verify the model's real output against it.
        if self.embedding_dimension is not None and self.embedding_dimension <= 0:
            raise ValidationError(
                {'embedding_dimension': 'Embedding dimension must be a positive integer.'}
            )

    def __str__(self):
        return f"{self.model_name} ({'Active' if self.is_active else 'Inactive'})"
    
    class Meta:
        ordering = ['-is_active', '-created_at']
        verbose_name = "Embedding Configuration"
        verbose_name_plural = "Embedding Configurations"


class LookupEmbedding(models.Model):
    '''
    Pre-computed embeddings for lookup table entries to enable fast semantic search.
    Uses pgvector for efficient similarity search.
    '''
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        limit_choices_to={'app_label': 'lookup'},
        help_text="The lookup table this embedding belongs to"
    )
    object_id = models.CharField(
        max_length=255,
        help_text="Primary key of the lookup record"
    )
    field_name = models.CharField(
        max_length=255,
        help_text="Field name that was embedded (e.g., 'icd_description')"
    )
    text_value = models.TextField(
        help_text="The original text that was embedded"
    )
    embedding = VectorField(
        # Dimensionless column: rows for different configs may use different
        # dimensions; queries filter by config + index_version before distance.
        help_text="Vector embedding of the text"
    )
    embedding_config = models.ForeignKey(
        EmbeddingConfiguration,
        on_delete=models.CASCADE,
        help_text="Configuration used to generate this embedding"
    )
    index_version = models.PositiveIntegerField(
        default=1,
        help_text="Index generation this embedding belongs to; queries only use rows matching the config's live version"
    )
    is_current = models.BooleanField(
        default=True,
        help_text="False when the lookup record was deleted or its text changed since the embedding was computed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.content_type.model}.{self.object_id} - {self.field_name}"
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'field_name']),
            models.Index(fields=['object_id']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id', 'field_name', 'embedding_config'],
                name='unique_lookup_embedding'
            )
        ]
        verbose_name = "Lookup Embedding"
        verbose_name_plural = "Lookup Embeddings"


class BackgroundTask(models.Model):
    """
    Track background task progress without external dependencies.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('complete', 'Complete'),
        ('failed', 'Failed'),
    ]
    
    task_id = models.CharField(max_length=100, unique=True, db_index=True)
    task_name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Progress tracking
    current_step = models.CharField(max_length=255, blank=True)
    progress_percent = models.IntegerField(default=0)
    total_items = models.IntegerField(default=0)
    processed_items = models.IntegerField(default=0)
    
    # Results
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.task_name} ({self.status})"
    
    def mark_running(self):
        self.status = 'running'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    def mark_complete(self, result_data=None):
        self.status = 'complete'
        self.progress_percent = 100
        self.completed_at = timezone.now()
        if result_data:
            self.result_data = result_data
        self.save(update_fields=['status', 'progress_percent', 'completed_at', 'result_data'])
    
    def mark_failed(self, error_message):
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'error_message', 'completed_at'])
    
    def update_progress(self, current_step, processed_items=None, total_items=None):
        self.current_step = current_step
        if processed_items is not None:
            self.processed_items = processed_items
        if total_items is not None:
            self.total_items = total_items
        
        # Calculate percentage
        if self.total_items > 0:
            self.progress_percent = int((self.processed_items / self.total_items) * 100)
        
        self.save(update_fields=['current_step', 'processed_items', 'total_items', 'progress_percent'])

