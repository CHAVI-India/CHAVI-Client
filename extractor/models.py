import os
from django.db import models
from django.core.validators import FileExtensionValidator,URLValidator
from django.core.exceptions import ValidationError
from client_app.models import *
from encrypted_model_fields.fields import EncryptedCharField
from logging import getLogger

log = getLogger(__name__)

class FileTypeChoices(models.TextChoices):
    PDF = 'pdf', 'PDF'
    CSV = 'csv', 'CSV'
    EXCEL = 'excel', 'Excel'

# Create your models here.

class ClientConfiguration(models.Model):
    '''
    A client configuration stores the necessary information such that Instructor can connect to the large language models.
    '''
    model_name = models.CharField(max_length=100)
    model_provider = models.CharField(max_length=100)
    model_api_key = EncryptedCharField(max_length=512)
    model_api_key_expires = models.BooleanField(default=False)
    model_api_key_validity = models.DateTimeField(null=True,blank=True)
    model_api_refresh_key = EncryptedCharField(max_length=512,null=True,blank=True)
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
        return self.model_name


class FileUpload(models.Model):
    '''
    This model stores information about uploaded files from which data will be extracted. This file text will be provided to the instructor as a structured data input.
    '''
    file = models.FileField(upload_to='uploads/', validators=[FileExtensionValidator(['pdf', 'csv', 'xlsx'])])
    file_type = models.CharField(max_length=100, choices=FileTypeChoices.choices, blank=True)
    patient_id = models.ForeignKey('client_app.Patients', on_delete=models.CASCADE)
    processing_date_time = models.DateTimeField(null=True, blank=True,help_text="This is the date and time on which the uploaded file was processed.")
    processed_file_path = models.CharField(max_length=1024, blank=True, null=True, help_text="This is the full path where the processed file is being stored.")
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

    def __str__(self):
        return self.file.name



class EntityTypeChoices(models.TextChoices):
    'string' = 'str', 'string'
    'boolean' = 'bool', 'boolean'
    'float' = 'float', 'float'
    'integer' = 'int', 'integer'
    'dictionary' = 'dict', 'dict'
    'tuple' = 'tuple', 'tuple'
    'list'  = 'list','list'
    'date' = 'datetime.date', 'date'
    'datetime' = 'datetime.datetime','datetime'
    'timedelta' = 'datetime.timedelta','timedelta'
    'time' = 'datetime.time','time'


class DatabaseTable(models.Model):
    '''
    An database table refers to the database table for which the data is to be extracted. This table refers to a client app table. 
    '''
    clientapp_table_name = models.CharField(max_length=512, help_text="This is the table in CHAVI to which the field belongs")
    clientapp_table_pk_field_name = models.CharField(max_length=512, help_text="This is the name of field which has the primary key for the table.")
    clientapp_table_fk_fields = models.JSONField(help_text="This a JSON representation of the FK field relationships for the table. It stores the FK relationship between the table and the patient table. Note that the FK relationship can traverse multiple intermediate tables. However the Patient table is the primary table.",null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.clientapp_table_name

    class Meta:
        verbose_name = "Entity Table (Database Table)"
        verbose_name_plural = "Entity Tables (Database Tables)"


class DatabaseField(models.Model):
    '''
    An database field from the client_app application. A collection of fields will be used to make up a response model for Instructor to use. There will also be validation rules which will be extracted from the model definition. Additionally this model will also specify the lookup table, its primary key field name and the value field name if this field is a lookup field.
    '''
    clientapp_database_table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE)
    clientapp_field_name = models.CharField(max_length=512,help_text="Select the client app Field which is to be extracted")
    field_type = models.CharField(max_length=512, choices=EntityTypeChoices.choices,help_text="Select the type of Field value which is stored in the database")
    field_validation = models.JSONField(help_text="This field will store any additional validation that has been defined for the CHAVI field. This would be converted to pydantic format and used for validating the model output.",null=True,blank=True)
    lookup_field = models.BooleanField(default=False, help_text="The client app database has an extensive number of fields which are linked to lookup tables. These fields need to be extracted with the lookup table data being provided as an enumerated list or a related table in the instructor extraction system.")
    lookup_table = models.CharField(max_length=512, blank=True, null=True, help_text="The lookup table name to which this field is linked if this is a lookup field")
    lookup_table_value_field_name = models.CharField(max_length=512, blank=True, null=True, help_text="The field containing the value which is to be matched / extracted using Instructor")
    lookup_table_pk_field_name = models.CharField(max_length=512, blank=True, null=True, help_text="The field containing the primary key to which the data will be linked")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.clientapp_database_table}.{self.clientapp_field_name}"

    class Meta:
        constraints = [models.UniqueConstraint(fields=['clientapp_database_table', 'clientapp_field_name'], name='unique_entity_per_table')]
        verbose_name = "Database Table Field"
        verbose_name_plural = "Database Table Fields"


class ResponseModel(models.Model):
    '''
    A response model is used to define a pydantic model which will be used by instructor to extract the data using LLM. This response model will be defined based on the data available in the database table and the fields selected for extraction.
    '''
    entity_table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE,help_text="Database table for which the response model is defined")
    client = models.ForeignKey(ClientConfiguration, on_delete=models.CASCADE,null=True,blank=True,help_text="Client configuration used for data extraction")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.entity_table.database_table_name} - {self.client.client_name}"


class InstructorRole(models.TextChoices):
    SYSTEM = "system", "System"
    USER = "user", "User"


class InstructorMessage(models.Model):
    '''
    This will be storing the prepared prompts which will be passed on to Instructor as a system prompt in a message format such that the data can be extracted.
    '''
    response_model = models.ForeignKey(ResponseModel, on_delete=models.CASCADE,help_text="Response model for which the message is defined")
    role = models.CharField(max_length=10, choices=InstructorRole.choices, help_text="Role of the message sender. The default value is system.", default=InstructorRole.SYSTEM)
    prompt = models.TextField(help_text="The prompt to be used for data extraction to be passed onto Instructor")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.response_model} - {self.prompt}"
