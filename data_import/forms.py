"""
Forms for data import workflow.
"""

from django import forms
from django.core.validators import FileExtensionValidator
from .models import (
    FileImportSession, FilePatientID, FileMappedModel,
    FileMappedField, FileColumnFieldValueMapping,
    FileDateFieldMapping, FileDurationDateMapping,
    FieldLookupValues, FileMissingRelations,
    FileImportUUIDValues, FileImportJSON,
    DateFormat, DurationUnits, ReferenceDateType
)
from client_app.models import Project


class Step1UploadCSVForm(forms.ModelForm):
    """
    Step 1: Upload CSV file and select projects.
    """
    class Meta:
        model = FileImportSession
        fields = ['import_session_name', 'project_name', 'csv_file']
        widgets = {
            'import_session_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter a name for this import session'
            }),
            'project_name': forms.SelectMultiple(attrs={
                'class': 'form-control select2',
                'required': True
            }),
            'csv_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.csv'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project_name'].required = True
        
        # CSV file is only required for new sessions, not when editing
        if self.instance and self.instance.pk and self.instance.csv_file:
            self.fields['csv_file'].required = False
        else:
            self.fields['csv_file'].required = True
        
        self.fields['csv_file'].validators = [FileExtensionValidator(['csv'])]


class Step2PatientIDMappingForm(forms.Form):
    """
    Step 2: Map patient ID column from CSV.
    """
    patient_id_column = forms.ChoiceField(
        label="Select the column that contains Patient ID",
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True
    )
    
    def __init__(self, csv_headers=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if csv_headers:
            choices = [(header, header) for header in csv_headers]
            self.fields['patient_id_column'].choices = choices


class Step3ModelSelectionForm(forms.Form):
    """
    Step 3: Select models to import data into.
    """
    selected_models = forms.MultipleChoiceField(
        label="Select the models you want to import data into",
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'model-checkbox'}),
        required=True
    )
    
    def __init__(self, model_choices=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if model_choices:
            self.fields['selected_models'].choices = model_choices


class Step4FieldMappingForm(forms.Form):
    """
    Step 4: Map CSV columns to model fields.
    This form is dynamically generated based on selected models.
    """
    pass  # Will be dynamically created in the view


class Step5ColumnValueMappingForm(forms.Form):
    """
    Step 5: Map column names to field values.
    This form is dynamically generated.
    """
    pass  # Will be dynamically created in the view


class Step6DateFormatForm(forms.Form):
    """
    Step 6: Set date formats for date fields.
    This form is dynamically generated based on mapped date fields.
    """
    pass  # Will be dynamically created in the view


class Step7DurationDateForm(forms.Form):
    """
    Step 7: Calculate dates from duration fields.
    """
    csv_duration_field = forms.ChoiceField(
        label="Select duration field from CSV",
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=False
    )
    
    duration_unit = forms.ChoiceField(
        label="Duration unit",
        choices=DurationUnits.choices,
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=False
    )
    
    reference_date = forms.CharField(
        label="Reference date (field name or date value)",
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        required=False
    )
    
    reference_date_type = forms.ChoiceField(
        label="Reference date type",
        choices=ReferenceDateType.choices,
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=False
    )
    
    reference_date_format = forms.ChoiceField(
        label="Reference date format",
        choices=DateFormat.choices,
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=False
    )
    
    client_app_date_field = forms.ChoiceField(
        label="Target date field in model",
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=False
    )
    
    def __init__(self, csv_headers=None, date_fields=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if csv_headers:
            self.fields['csv_duration_field'].choices = [('', '---')] + [(h, h) for h in csv_headers]
        if date_fields:
            self.fields['client_app_date_field'].choices = [('', '---')] + [(f, f) for f in date_fields]


class Step8LookupMappingForm(forms.Form):
    """
    Step 8: Map CSV values to lookup table values.
    This form is dynamically generated.
    """
    pass  # Will be dynamically created in the view


class Step9MissingRelationsForm(forms.Form):
    """
    Step 9: Handle missing FK relationships.
    This form is dynamically generated based on missing relationships.
    """
    pass  # Will be dynamically created in the view


class Step10ReviewForm(forms.Form):
    """
    Step 10: Review generated JSON before import.
    """
    confirm_import = forms.BooleanField(
        label="I have reviewed the data and confirm the import",
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
