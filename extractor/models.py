import os
from django.db import models
from django.core.validators import FileExtensionValidator,URLValidator
from django.core.exceptions import ValidationError
from client_app.models import *
from encrypted_model_fields.fields import EncryptedCharField


class FileTypeChoices(models.TextChoices):
    PDF = 'pdf', 'PDF'
    CSV = 'csv', 'CSV'
    EXCEL = 'excel', 'Excel'

# Create your models here.

class LLMConfiguration(models.Model):
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
    file = models.FileField(upload_to='uploads/', validators=[FileExtensionValidator(['pdf', 'csv', 'xlsx'])])
    file_type = models.CharField(max_length=100, choices=FileTypeChoices.choices, blank=True)
    patient_id = models.ForeignKey('client_app.Patients', on_delete=models.CASCADE)
    processing_date_time = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    EXTENSION_TO_FILE_TYPE = {
        '.pdf': FileTypeChoices.PDF,
        '.csv': FileTypeChoices.CSV,
        '.xlsx': FileTypeChoices.EXCEL,
    }

    def save(self, *args, **kwargs):
        if self.file:
            ext = os.path.splitext(self.file.name)[1].lower()
            file_type = self.EXTENSION_TO_FILE_TYPE.get(ext)
            if file_type:
                self.file_type = file_type
            else:
                raise ValidationError({'file': f'Unsupported file extension: {ext}'})
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

class Entity(models.Model):
    '''
    An entity corresponds to a database table field from the client_app application. A collection of entities will be used to make up a response model for Instructor to use.
    '''
    chavi_field = models.CharField(max_length=255,help_text="Select the CHAVI Field which is to be extracted")
    entity_type = models.CharField(max_length=512, choices=EntityTypeChoices.choices,help_text="Select the type of Field value which is stored in the database")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.chavi_field


class ResponseModel(model.Model):
    '''
    A response model is used to define a pydantic model which will be used by instructor to extract the data using LLM.
    '''
    entity = models.ForeignKey(TargetedEntity, on_delete=models.CASCADE,help_text="Entity for which the value is extracted")
    llm_model = models.ForeignKey(LLMModel, on_delete=models.CASCADE,null=True,blank=True,help_text="LLM Model used for data extraction")
    value = models.TextField(null=True, blank=True,help_text="Value obtained for the entity")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.value
