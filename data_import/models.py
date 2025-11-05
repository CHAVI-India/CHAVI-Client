from django.db import models
from client_app.models import Project
from django.core.validators import FileExtensionValidator
# Create your models here.

class DataType(models.TextChoices):
    '''
    This is a choice field for the type of file being uploaded.
    '''
    JSON = 'JSON', 'JSON'
    CSV = 'CSV', 'CSV'

class ImportStatus(models.TextChoices):
    '''
    Status choices for the import process.
    '''
    UPLOADED = 'uploaded', 'Uploaded'
    FIELD_MAPPING = 'field_mapping', 'Field Mapping'
    VALIDATING = 'validating', 'Validating'
    LOOKUP_MATCHING = 'lookup_matching', 'Lookup Matching'
    UUID_MAPPING = 'uuid_mapping', 'UUID Mapping'
    IMPORTING = 'importing', 'Importing'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'

class ImportData(models.Model):
    '''
    This is a model to store information about the file being uploaded and track import progress.
    '''
    id = models.AutoField(primary_key=True)
    data_type = models.CharField(
        max_length=10, 
        choices=DataType.choices,
        help_text="The type of file to be imported."
    )
    file = models.FileField(
        upload_to='import_data/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["json","csv"])],
        help_text="The file to be imported."
    )
    project = models.ManyToManyField(
        'client_app.Project',
        help_text="The project(s) to which the data belongs."
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=ImportStatus.choices,
        default=ImportStatus.UPLOADED,
        help_text="Current status of the import process."
    )
    
    # Data statistics
    row_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Total number of rows in the imported file."
    )
    processed_rows = models.PositiveIntegerField(
        default=0,
        help_text="Number of rows successfully processed."
    )
    
    # Validation and error tracking
    validation_errors = models.JSONField(
        null=True,
        blank=True,
        help_text="Validation errors encountered during import (JSON format)."
    )
    
    # Import summary
    import_summary = models.JSONField(
        null=True,
        blank=True,
        help_text="Summary of the import process including statistics and results (JSON format)."
    )
    
    # Error log
    error_log = models.TextField(
        null=True,
        blank=True,
        help_text="Detailed error log if import fails."
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Import Data"
        verbose_name_plural = "Import Data"
        db_table = "import_data"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['data_type', 'status']),
        ]

    def __str__(self):
        if self.file:
            return f"{self.file.name} ({self.get_status_display()})"
        return f"Import #{self.id} ({self.get_status_display()})"
    
    def get_progress_percentage(self):
        """Calculate import progress percentage."""
        if self.row_count and self.row_count > 0:
            return int((self.processed_rows / self.row_count) * 100)
        return 0
    
    def is_complete(self):
        """Check if import is complete."""
        return self.status == ImportStatus.COMPLETED
    
    def has_errors(self):
        """Check if import has errors."""
        return self.status == ImportStatus.FAILED or bool(self.validation_errors)

class FieldDataType(models.TextChoices):
    '''
    This is a choice field for the type of data.
    '''
    STRING = 'String', 'String'
    INTEGER = 'Integer', 'Integer'
    FLOAT = 'Float', 'Float'
    BOOLEAN = 'Boolean', 'Boolean'
    DATE = 'Date', 'Date'
    DATETIME = 'DateTime', 'DateTime'
    TIME = 'Time', 'Time'
    JSON = 'JSON', 'JSON'

class FieldType(models.TextChoices):
    '''
    This is a choice field for the type of field.
    '''
    STANDARD = 'Standard', 'Standard'
    FOREIGN_KEY = 'Foreign Key', 'Foreign Key'
    MANY_TO_MANY = 'Many to Many', 'Many to Many'

class DataFieldConfiguration(models.Model):
    '''
    This is a model to store information about the field in the datafile uploaded and link it to the corresponding field name from the client_app models.
    '''
    id = models.AutoField(primary_key=True)
    import_data = models.ForeignKey('ImportData', on_delete=models.CASCADE, related_name='data_fields',help_text="The import data to which the field belongs.")
    file_field_name = models.CharField(max_length=255,null=True,blank=True,
    help_text="The field name in the file.")
    field_data_type = models.CharField(max_length=50, choices=FieldDataType.choices,
    help_text="The data type of the field.")
    client_app_table_name = models.CharField(max_length=255,null=True,blank=True,help_text="The table name in the client_app models.")
    client_app_field_name = models.CharField(max_length=255,null=True,blank=True,help_text="The field name in the client_app models.")
    client_app_field_type = models.CharField(max_length=50, choices=FieldType.choices,
    help_text="The type of the field in the client_app models.A standard field will be a field that is storing data in the same table. A foreign key field type is used when there is a one-to-one or one-to-many relationship. A many-to-many field type is used when there is a many-to-many relationship.")
    client_app_lookup_table_name = models.CharField(max_length=255,null=True,blank=True,help_text="The lookup table name if the field in the client app has a FK relationship to the lookup app.")
    client_app_lookup_field_name = models.CharField(max_length=255,null=True,blank=True,help_text="The lookup field name if the field in the client app has a FK relationship to the lookup app.")
    

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Data Field"
        verbose_name_plural = "Data Fields"
        db_table = "data_field"
        indexes = [
            models.Index(fields=['import_data', 'file_field_name']),
            models.Index(fields=['client_app_table_name', 'client_app_field_name']),
        ] 

    def __str__(self):
        if self.file_field_name and self.client_app_field_name:
            return f"{self.file_field_name} → {self.client_app_table_name}.{self.client_app_field_name}"
        return self.file_field_name or f"Field Mapping #{self.id}"

class UUIDMappings(models.Model):
    '''
    This is a model to store information about the UUID mappings for a given file upload such that the same UUID is used when the data in the file is uploaded again. A combination of field values are used to identify the primary key for the client app tables. The unique combination of fields is customizable.
    '''
    id = models.AutoField(primary_key=True)
    import_data = models.ForeignKey('ImportData', on_delete=models.CASCADE, related_name='uuid_mappings',help_text="The import data to which the UUID mapping belongs.")
    client_app_table_name = models.CharField(max_length=255,null=True,blank=True,help_text="The table name in the client_app models.")
    client_app_primary_key_name = models.CharField(max_length=255,null=True,blank=True,help_text="The primary key name in the client_app models.")
    client_app_primary_key_value = models.CharField(max_length=255,null=True,blank=True,help_text="The primary key value in the client_app models.")
    data_field_configuration_fields = models.ManyToManyField('DataFieldConfiguration', related_name='data_field_configuration_fields',help_text="The combination of fields in the data file that are used to create or link the existing UUID in the client_app models.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "UUID Mapping"
        verbose_name_plural = "UUID Mappings"
        db_table = "uuid_mapping"
        indexes = [
            models.Index(fields=['import_data', 'client_app_table_name']),
            models.Index(fields=['client_app_primary_key_value']),
        ]
        unique_together = [['import_data', 'client_app_table_name', 'client_app_primary_key_value']] 

    def __str__(self):
        return f"{self.client_app_table_name}: {self.client_app_primary_key_value}"

class FieldLookupConfiguration(models.Model):
    '''
    This is a model to store information about the lookup data for a given field in the data file allowing one to one mapping of a given value in the file to a correspoding value in the lookup table.
    '''
    id = models.AutoField(primary_key=True)
    data_field_configuration = models.ForeignKey('DataFieldConfiguration', on_delete=models.CASCADE, related_name='field_lookup_configurations',help_text="The data field to which the lookup configuration belongs.")
    field_value = models.CharField(max_length=255,null=True,blank=True,help_text="The value of the string in the field.")
    lookup_value = models.CharField(max_length=255,null=True,blank=True,help_text="The lookup value mapped to the string in the data file")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Field Lookup Configuration"
        verbose_name_plural = "Field Lookup Configurations"
        db_table = "field_lookup_configuration"
        indexes = [
            models.Index(fields=['data_field_configuration', 'field_value']),
        ]
        unique_together = [['data_field_configuration', 'field_value']] 

    def __str__(self):
        return f"{self.data_field_configuration.file_field_name}: {self.field_value} → {self.lookup_value}"

class CalculatiopnDateFieldType(models.TextChoices):
    START_DATE = 'Start Date', 'Start Date'
    END_DATE = 'End Date', 'End Date'
    

class DateFormatType(models.TextChoices):
    YearMonthDay = 'YearMonthDay', 'YearMonthDay'
    MonthDayYear = 'MonthDayYear', 'MonthDayYear'
    DayMonthYear = 'DayMonthYear', 'DayMonthYear'

class DateSeparatorType(models.TextChoices):
    Hyphen = 'Hyphen', 'Hyphen'
    ForwardSlash = 'ForwardSlash', 'ForwardSlash'
    Dash = 'Dash', 'Dash'
    Space = 'Space', 'Space'
    Comma = 'Comma', 'Comma'
    Dot = 'Dot', 'Dot'
    

class ImportDateFormatConfiguration(models.Model):
    '''
    This is a model to store information about the date format fields of the data file.
    '''
    id = models.AutoField(primary_key=True)
    data_field_configuration = models.ForeignKey('DataFieldConfiguration', on_delete=models.CASCADE, related_name='date_format_configurations',help_text="The data field to which the date format configuration belongs.")
    date_format = models.CharField(max_length=255,null=True,blank=True,choices=DateFormatType.choices,help_text="The date format of the date in the data file.")
    date_separator = models.CharField(max_length=255,null=True,blank=True,choices=DateSeparatorType.choices,help_text="The separator used in the date in the data file.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Date Format Configuration"
        verbose_name_plural = "Date Format Configurations"
        db_table = "date_format_configuration"
        indexes = [
            models.Index(fields=['import_data', 'date_format']),
        ]
        unique_together = [['import_data', 'date_format']] 
    
    def __str__(self):
        return f"{self.import_data}: {self.date_format}"
    



class ImportDateIntervalFieldConfiguration(models.Model):
    '''
    This is a model to store information about the conversion of intervals and duration to dates. For example if age is available in the data file, it will convert the age into the date of birth. For computing the date from the duration / interval we will need a start or end date which may be available from a field in the data file or may be provided by the user.
    '''
    id = models.AutoField(primary_key=True)
    import_data = models.ForeignKey('ImportData', on_delete=models.CASCADE, related_name='date_interval_field_configurations',help_text="The import data to which the date interval field configuration belongs.")
    interval_field = models.CharField(max_length=255,null=True,blank=True,help_text="The interval field in the data file.")
    calculation_date = models.CharField(max_length=255,null=True,blank=True,help_text="The date used for calculating the other date from the interval provided in the file. This can be a field in th data file or a user provided date.")
    calculation_date_type = models.CharField(max_length=50, choices=CalculatiopnDateFieldType.choices,
    help_text="The type of the calculation date. If start date then then the interval will be added to the start date to get the end date. If end date then the interval will be subtracted from the end date to get the start date.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Date Interval Field Configuration"
        verbose_name_plural = "Date Interval Field Configurations"
