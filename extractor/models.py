import os
from django.db import models
from django.core.validators import FileExtensionValidator,URLValidator
from django.core.exceptions import ValidationError
from encrypted_model_fields.fields import EncryptedCharField, EncryptedTextField
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from pgvector.django import VectorField
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        if self.model_api_key_expires:
            errors = {}
            if not self.model_api_key_validity:
                errors['model_api_key_validity'] = 'Validity date is required when API key can expire.'
            if not self.model_api_refresh_key:
                errors['model_api_refresh_key'] = 'Refresh key is required when API key can expire.'
            if errors:
                raise ValidationError(errors)

    def __str__(self):
        return self.llm_model_name

    class Meta:
        ordering = ['-created_at']


class FileUpload(models.Model):
    '''
    This model stores information about uploaded files from which data will be extracted. This file text will be provided to the instructor as a structured data input after processing. Note that for some formats the file itself will be provided.
    '''
    file = models.FileField(upload_to='uploads/', validators=[FileExtensionValidator(['pdf', 'csv', 'xlsx'])])
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
        log.info("Saving file upload...")
        '''
        This is a function that will automatically extract the extension from the file name and save it. 
        '''
        if self.file:
            ext = os.path.splitext(self.file.name)[1].lower()
            file_type = self.EXTENSION_TO_FILE_TYPE.get(ext)
            self.file_type = file_type
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        '''
        Override delete to remove the physical file from disk when the model instance is deleted.
        '''
        if self.file:
            if os.path.isfile(self.file.path):
                os.remove(self.file.path)
                log.info(f"Deleted file from disk: {self.file.path}")
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.file.name

    class Meta:
        ordering = ['-created_at']

class ProcessedText(models.Model):
    '''
    This model stores information about processed file from an uploaded text file.
    '''
    file_upload = models.ForeignKey(FileUpload, on_delete=models.CASCADE)
    processed_file_path = models.CharField(max_length = 512, null=True, blank=True)
    processed_by_user = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True, help_text="The user who processed this file.")    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def delete(self, *args, **kwargs):
        '''
        Override delete to remove the processed file from disk when the model instance is deleted.
        '''
        if self.processed_file_path:
            if os.path.isfile(self.processed_file_path):
                os.remove(self.processed_file_path)
                log.info(f"Deleted processed file from disk: {self.processed_file_path}")
        super().delete(*args, **kwargs)

    def __str__(self):
        if self.file_upload and self.file_upload.file:
            return self.file_upload.file.name
        return f"ProcessedText {self.pk}"

    class Meta:
        ordering = ['-created_at']

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.clientapp_database_table}.{self.clientapp_field_name}"

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.response_model} - {self.role}"

    class Meta:
        ordering = ['-created_at']

class ExtractionStatusChoices(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"

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
    raw_llm_response = models.JSONField(help_text="Raw LLM response as JSON. To be stored in database only for debugging",null=True,blank=True)
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
    ACCURATE = "accurate", "Accurate"
    PARTIAL = "partial", "Partial"
    INACCURATE = "inaccurate", "Inaccurate"

class ExtractionResult(models.Model):
    '''
    This will store the extracted data for a specific field. We will also store the details of who verified the data and if the extracted data was correct or not. If the extracted data was edited then it will also be corrected.
    '''
    extraction_job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE,help_text="Extraction job for which the data has been extracted")
    database_field = models.ForeignKey(DatabaseField, on_delete=models.CASCADE,help_text="Database table field for which the data has been extracted")
    extracted_data = EncryptedTextField(help_text="Extracted data after Instructor parses the text. This will be stored as an encrypted text.")
    data_accuracy = models.CharField(max_length=50, choices=DataAccuracyChoices.choices, default=DataAccuracyChoices.ACCURATE)
    data_edited = models.BooleanField(default=False, help_text="Whether the data was edited by the user")
    edited_data = EncryptedTextField(help_text="Edited data after user edits the extracted data. This will be stored as an encrypted text.",null=True,blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.CASCADE,help_text="User who verified the data")
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
    api_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="API key if using a cloud provider like OpenAI"
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
        dimensions=None,  # Will be set based on EmbeddingConfiguration
        help_text="Vector embedding of the text"
    )
    embedding_config = models.ForeignKey(
        EmbeddingConfiguration,
        on_delete=models.CASCADE,
        help_text="Configuration used to generate this embedding"
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

