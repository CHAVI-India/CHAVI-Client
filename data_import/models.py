from django.db import models
from client_app.models import Project
from django.core.validators import FileExtensionValidator
# Create your models here.

class FileImportSessionStep(models.TextChoices):
    UPLOAD = 'upload_csv'
    PATIENT_ID = 'patient_id_mapping'
    MODEL_SELECTION = 'model_selection'
    FIELD_MAPPING = 'field_mapping'
    COLUMN_VALUE = 'column_value_mapping'
    DATE_FORMAT = 'date_format'
    DURATION_DATE = 'duration_date'
    LOOKUP_MAPPING = 'lookup_mapping'
    DEFAULT_VALUES = 'default_values'  # New step 9
    MISSING_RELATIONS = 'missing_relations'  # Now step 10
    REVIEW = 'review'  # Now step 11
    EXECUTE = 'execute_import'  # Now step 12
    


class FileImportSession(models.Model):
    '''
    This is a model to store information about the data import session per file
    '''
    id = models.AutoField(primary_key=True)
    project_name = models.ManyToManyField(Project, help_text="Select the name of the Projects for which this patient data is being imported. Please note that multiple projects may be selected here.",verbose_name="Select Project(s) for the Data Import")
    import_session_name = models.CharField(max_length=255, null=True, blank=True, help_text="Enter a name for this import session. Limit 255 characters",verbose_name="Import Session Name")
    csv_file = models.FileField(upload_to='import_sessions/', validators=[FileExtensionValidator(['csv'])], help_text="Upload a CSV file to import patient data.",verbose_name="CSV File")
    import_session_step = models.CharField(max_length=255, choices=FileImportSessionStep.choices, default=FileImportSessionStep.UPLOAD, help_text="The step of the import session.",verbose_name="Import Session Step")
    patient_id_column = models.CharField(max_length=255, null=True, blank=True, help_text="The CSV column name used for patient ID",verbose_name="Patient ID Column")
    uuids_generated = models.BooleanField(default=False, help_text="Indicates if UUIDs have been generated for this session")
    data_imported = models.BooleanField(default=False, help_text="Indicates if data has been successfully imported")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")

    def __str__(self):
        return self.import_session_name or f"Import Session {self.id}"

    class Meta:
        verbose_name = "File Import Session"
        verbose_name_plural = "File Import Sessions"


class FilePatientID(models.Model):
    '''
    This is a model to store information about the Patient IDs in the CSV file being imported. 
    '''

    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_patient_ids')
    patient_id = models.CharField(max_length=255, null=True, blank=True, help_text="The patient ID from the CSV file.",verbose_name="Patient ID")
    exists_in_client_app_database = models.BooleanField(default=False, help_text="The patient ID exists in the client_app database.",verbose_name="Exists in Client App Database")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")

    def __str__(self):
        return self.patient_id

    class Meta:
        verbose_name = "File Patient ID"
        verbose_name_plural = "File Patient IDs"

class FileMappedModel(models.Model):
    '''
    This is a model to store information about the models in the client_app to which the data should be imported.
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_mapped_models')
    client_app_model_name = models.JSONField(null=True, blank=True, help_text="Enter the name of the client_app models to which the data should be imported.",verbose_name="Client App Model Name")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")

    def __str__(self):
        if self.client_app_model_name:
            return str(self.client_app_model_name) if isinstance(self.client_app_model_name, str) else ', '.join(self.client_app_model_name)
        return f"FileMappedModel {self.id}"

    class Meta:
        verbose_name = "File Mapped Model"
        verbose_name_plural = "File Mapped Models"


class FileMappedField(models.Model):
    '''
    This is a model to store information about the mapped fields for a file import session
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_mapped_fields')
    csv_field_names = models.JSONField(help_text="Select the names of the CSV fields to be mapped to the corresponding fields in the client_app models.",verbose_name="Select the Field Names in the CSV file",null=True, blank=True)
    mapped_client_app_field_name = models.CharField(max_length=255, null=True, blank=True, help_text="Enter the name of the client_app field to be mapped to the CSV field.",verbose_name="Select the Client App Field")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")

    def __str__(self):
        return self.mapped_client_app_field_name or f"FileMappedField {self.id}"
    
    class Meta:
        verbose_name = "File Mapped Field"
        verbose_name_plural = "File Mapped Fields"

class FileColumnFieldValueMapping(models.Model):
    '''
    This is a model to store information about the column field value mappings for a file import session for columns where the column name contains information about the field in chavi client_app
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_column_field_value_mappings')
    csv_column_name = models.JSONField(null=True, blank=True, help_text="Enter the name of the CSV column to be mapped to the corresponding field in the client_app models.",verbose_name="Select the CSV Column Name")
    mapped_client_app_field_name = models.JSONField(null=True,blank=True,help_text="select the client app field name which will store the value corresponding to the column")
    mapped_client_app_field_value = models.JSONField(null=True,blank=True,help_text="define the client app field value which will store the value corresponding to the column")
    mapped_client_app_additional_field_names = models.JSONField(null=True,blank=True, help_text="define the additional client app field names which will be created along with this data when the import is started")
    mapped_client_app_additional_field_values = models.JSONField(null=True,blank=True, help_text="define the additional client app field values which will be created along with this data when the import is started")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")
    
    def __str__(self):
        if self.csv_column_name:
            return str(self.csv_column_name) if isinstance(self.csv_column_name, str) else str(self.csv_column_name)
        return f"FileColumnFieldValueMapping {self.id}"
    
    class Meta:
        verbose_name = "File Column Field Value Mapping"
        verbose_name_plural = "File Column Field Value Mappings"

class DateFormat(models.TextChoices):
    ISO_8601 = 'iso_8601', 'ISO 8601'
    DDMMYYYY = 'ddmmyyyy', 'DDMMYYYY'
    MMDDYYYY = 'mmddyyyy', 'MMDDYYYY'
    YYYYMMDD = 'yyyymmdd', 'YYYYMMDD'
    DMY = 'dmy', 'DMY'
    MDY = 'mdy', 'MDY'
    YMD = 'ymd', 'YMD'
    DDMMYY = 'ddmmyy', 'DDMMYY'
    MMDDYY = 'mmddyy', 'MMDDYY'
    YYMMDD = 'yymmdd', 'YYMMDD'
    
    


class FileDateFieldMapping(models.Model):
    '''
    This is a model to store information about the date field mappings for a file import session
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_date_field_mappings')
    csv_column_name = models.JSONField(null=True, blank=True, help_text="Enter the name of the CSV column to be mapped to the corresponding field in the client_app models.",verbose_name="Select the CSV Column Name")
    date_format = models.CharField(max_length=255, null=True, blank=True, choices=DateFormat.choices, help_text="Enter the date format for the CSV column.",verbose_name="Date Format")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")
    
    def __str__(self):
        if self.csv_column_name:
            return str(self.csv_column_name) if isinstance(self.csv_column_name, str) else str(self.csv_column_name)
        return f"FileDateFieldMapping {self.id}"
    
    class Meta:
        verbose_name = "File Date Field Mapping"
        verbose_name_plural = "File Date Field Mappings"


class DurationUnits(models.TextChoices):
    YEAR = 'year', 'Year'
    MONTH = 'month', 'Month'
    FORTNIGHT = 'fortnight', 'Fortnight'
    WEEK = 'week', 'Week'
    DAY = 'day', 'Day'
    HOUR = 'hour', 'Hour'
    MINUTE = 'minute', 'Minute'
    SECOND = 'second', 'Second'
    MILLISECOND = 'millisecond', 'Millisecond'
    MICROSECOND = 'microsecond', 'Microsecond'
    NANOSECOND = 'nanosecond', 'Nanosecond'


class ReferenceDateType(models.TextChoices):
    START = 'start', 'Start'
    END = 'end', 'End'


class FileDurationDateMapping(models.Model):
    '''
    This is a model to store information about the date data that will be created from a given duration or interval in the csv file.
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_duration_date_mappings')
    csv_duration_field = models.CharField(max_length=255, null=True, blank=True, help_text="Select the duration field (e.g. age, disease free survival, duration to relapse, etc.) from the list of fields in the csv file.",verbose_name="Duration Field in CSV file")
    duration = models.CharField(max_length=255, null=True, blank=True, help_text="Enter the duration for the CSV column.",verbose_name="Duration")
    duration_unit = models.CharField(max_length=255, choices=DurationUnits.choices, null=True, blank=True, help_text="Select unit in which the duration has been specified",verbose_name="Duration Unit")
    reference_date = models.CharField(max_length=255, null=True, blank=True, help_text="Select the reference date field (e.g. diagnosis date, etc.) from the list of fields in the csv file or provide your own default. Note that the default value will be used for ALL patients.",verbose_name="Reference Date")
    reference_date_type = models.CharField(max_length=255, choices=ReferenceDateType.choices, null=True, blank=True, help_text="Select the type of reference date (start or end)",verbose_name="Reference Date Type")
    reference_date_format = models.CharField(max_length=255, choices=DateFormat.choices, null=True, blank=True, help_text="Select the format of the reference date",verbose_name="Reference Date Format")
    client_app_date_field = models.CharField(max_length=255, null=True, blank=True, help_text="Select the date field in the client_app model to which the duration will be added.",verbose_name="Client App Date Field")
    client_app_date_field_value = models.CharField(max_length=255, null=True, blank=True, help_text="The calculated value for the date field in the client_app model.This will be calculated based on the duration and the reference date.",verbose_name="Client App Date Field Value")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")
    
    def __str__(self):
        return self.client_app_date_field_value or self.csv_duration_field or f"FileDurationDateMapping {self.id}"
    
    class Meta:
        verbose_name = "File Duration Date Mapping"
        verbose_name_plural = "File Duration Date Mappings"


class FieldLookupValues(models.Model):
    '''
    This is a model to store information about the lookup values for a field in the csv file.
    Maps CSV values to lookup codes (e.g., "Alive" -> "01", "Dead" -> "02")
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='field_lookup_values')
    csv_column_name = models.CharField(max_length=255, null=True, blank=True, help_text="Select the column name from the csv file.",verbose_name="CSV Column Name")
    csv_value = models.CharField(max_length=255, null=True, blank=True, help_text="The value in the CSV that needs to be mapped.",verbose_name="CSV Value")
    lookup_value = models.CharField(max_length=255, null=True, blank=True, help_text="Enter the lookup code for the CSV value.",verbose_name="Lookup Code")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")
    
    def __str__(self):
        return f"{self.csv_column_name}: {self.csv_value} -> {self.lookup_value}" if self.csv_column_name else f"FieldLookupValues {self.id}"
    
    class Meta:
        verbose_name = "File Lookup Value"
        verbose_name_plural = "File Lookup Values"
        
class FileDefaultValues(models.Model):
    '''
    This is a model to store default values for unmapped fields (Step 9).
    These values apply to all records in the import session.
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_default_values')
    client_app_model_name = models.CharField(max_length=255, null=True, blank=True, help_text="Select the client_app model name.",verbose_name="Client App Model Name")
    client_app_field_name = models.CharField(max_length=255, null=True, blank=True, help_text="Select the client_app field name.",verbose_name="Client App Field Name")
    client_app_field_value = models.CharField(max_length=255, null=True, blank=True, help_text="The default value for this field.",verbose_name="Default Value")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this was last updated.",verbose_name="Updated At")
    
    def __str__(self):
        return f"{self.client_app_model_name}.{self.client_app_field_name} = {self.client_app_field_value}" if self.client_app_model_name and self.client_app_field_name else f"FileDefaultValues {self.id}"
    
    class Meta:
        verbose_name = "File Default Value"
        verbose_name_plural = "File Default Values"


class FileParentRecordMapping(models.Model):
    '''
    This model stores how to handle missing parent FK relationships (Step 10).
    For each child model with unmapped FK, user can either:
    1. Link to an existing parent record in the database
    2. Create a new parent record with specified field values
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_parent_record_mappings')
    child_model_name = models.CharField(max_length=255, help_text="The child model name (e.g., 'Radiotherapy')", verbose_name="Child Model Name")
    parent_fk_field = models.CharField(max_length=255, help_text="The FK field name in child model (e.g., 'diagnosis')", verbose_name="Parent FK Field")
    parent_model_name = models.CharField(max_length=255, help_text="The parent model name (e.g., 'Diagnosis')", verbose_name="Parent Model Name")
    
    # Option 1: Link to existing record
    link_to_existing = models.BooleanField(default=False, help_text="If True, link to an existing parent record", verbose_name="Link to Existing")
    existing_record_id = models.CharField(max_length=255, null=True, blank=True, help_text="UUID/ID of existing parent record to link to", verbose_name="Existing Record ID")
    
    # Option 2: Create new parent
    create_new_parent = models.BooleanField(default=False, help_text="If True, create a new parent record during import", verbose_name="Create New Parent")
    parent_field_values = models.JSONField(null=True, blank=True, help_text="Field values for new parent record {field: value}", verbose_name="Parent Field Values")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    
    def __str__(self):
        return f"{self.child_model_name}.{self.parent_fk_field} → {self.parent_model_name}"
    
    class Meta:
        verbose_name = "File Parent Record Mapping"
        verbose_name_plural = "File Parent Record Mappings"
        unique_together = [['file_import_session', 'child_model_name', 'parent_fk_field']]


class FileMissingRelations(models.Model):
    '''
    DEPRECATED: This model is being replaced by FileParentRecordMapping for FK relationships.
    Currently only used for simple field value assignments that are not FK relationships.
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_missing_relations')
    client_app_model_name = models.CharField(max_length=255, null=True, blank=True, help_text="Select the client_app model name.",verbose_name="Client App Model Name")
    client_app_field_name = models.CharField(max_length=255, null=True, blank=True, help_text="Select the client_app field name.",verbose_name="Client App Field Name")
    client_app_field_value = models.CharField(max_length=255, null=True, blank=True, help_text="Select the client_app field value.",verbose_name="Client App Field Value")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")
    
    def __str__(self):
        return f"{self.client_app_model_name}.{self.client_app_field_name}" if self.client_app_model_name and self.client_app_field_name else f"FileMissingRelations {self.id}"
    
    class Meta:
        verbose_name = "File Missing Relation"
        verbose_name_plural = "File Missing Relations"


class FileImportUUIDValues(models.Model):
    '''
    This is a model to store information about the UUID values for the fields in the csv file.
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_import_uuid_values')
    client_app_model_name = models.CharField(max_length=255, null=True, blank=True, help_text="Select the client_app model name.",verbose_name="Client App Model Name")
    client_app_model_pk = models.CharField(max_length=255, null=True, blank=True, help_text="Select the client_app model primary key name.",verbose_name="Client App Model Primary Key Name")
    client_app_model_pk_uuid_value = models.CharField(max_length=255, null=True, blank=True, help_text="Enter the UUID value for the CSV column.",verbose_name="UUID Value")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")
    
    def __str__(self):
        return f"{self.client_app_model_name}: {self.client_app_model_pk_uuid_value}" if self.client_app_model_name else f"FileImportUUIDValues {self.id}"
    
    class Meta:
        verbose_name = "File UUID Value"
        verbose_name_plural = "File UUID Values"

class FileImportJSON(models.Model):
    '''
    This is a model to store information about the JSON data for the import session.
    '''
    id = models.AutoField(primary_key=True)
    file_import_session = models.ForeignKey(FileImportSession, on_delete=models.CASCADE, related_name='file_import_json')
    json_data = models.JSONField(null=True, blank=True, help_text="Enter the JSON data for the import session.",verbose_name="JSON Data")
    created_at = models.DateTimeField(auto_now_add=True, help_text="The date and time when this import session was created.",verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, help_text="The date and time when this import session was last updated.",verbose_name="Updated At")
    
    def __str__(self):
        return f"FileImportJSON for session {self.file_import_session.import_session_name if self.file_import_session else self.id}"
    
    class Meta:
        verbose_name = "File Import JSON"
        verbose_name_plural = "File Import JSONs"