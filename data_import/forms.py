"""
Forms for the data import wizard.
"""
from django import forms
from django.core.validators import FileExtensionValidator
from data_import.models import DataType, ImportData, DataFieldConfiguration
from client_app.models import Project


class FileUploadForm(forms.Form):
    """
    Form for uploading CSV/JSON files in Step 1.
    """
    
    file = forms.FileField(
        label="Select File",
        help_text="Upload a CSV or JSON file containing your data.",
        validators=[FileExtensionValidator(allowed_extensions=['csv', 'json'])],
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.json',
        })
    )
    
    data_type = forms.ChoiceField(
        label="File Type",
        choices=DataType.choices,
        initial=DataType.CSV,
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )
    
    projects = forms.ModelMultipleChoiceField(
        queryset=Project.objects.all(),
        label="Project(s)",
        help_text="Select one or more projects this data belongs to.",
        widget=forms.CheckboxSelectMultiple(),
        required=True
    )
    
    def clean_file(self):
        """Validate uploaded file."""
        file = self.cleaned_data.get('file')
        
        if file:
            # Check file size (max 50MB)
            if file.size > 50 * 1024 * 1024:
                raise forms.ValidationError(
                    'File size exceeds 50MB limit. Please upload a smaller file.'
                )
            
            # Check file extension
            file_extension = file.name.split('.')[-1].lower()
            if file_extension not in ['csv', 'json']:
                raise forms.ValidationError(
                    'Invalid file type. Please upload a CSV or JSON file.'
                )
        
        return file


class FieldMappingForm(forms.Form):
    """
    Form for manual field mapping in Step 3.
    """
    
    def __init__(self, *args, source_fields=None, chavi_fields=None, **kwargs):
        """
        Initialize form with dynamic fields.
        
        Args:
            source_fields: List of field names from imported file
            chavi_fields: List of CHAVI field metadata dictionaries
        """
        super().__init__(*args, **kwargs)
        
        if source_fields and chavi_fields:
            # Create choices for CHAVI fields grouped by model
            choices = [('', '-- Select Field --')]
            
            # Group fields by model
            fields_by_model = {}
            for field in chavi_fields:
                model_name = field['model_name']
                if model_name not in fields_by_model:
                    fields_by_model[model_name] = []
                fields_by_model[model_name].append(field)
            
            # Create optgroups
            for model_name, fields in sorted(fields_by_model.items()):
                model_choices = [
                    (
                        f"{field['model_name']}.{field['field_name']}",
                        f"{field['field_name']} ({field['verbose_name']})"
                    )
                    for field in fields
                ]
                choices.append((model_name, model_choices))
            
            # Create a field for each source field
            for source_field in source_fields:
                field_name = f'mapping_{source_field}'
                self.fields[field_name] = forms.ChoiceField(
                    label=source_field,
                    choices=choices,
                    required=False,
                    widget=forms.Select(attrs={
                        'class': 'form-select field-mapping-select',
                        'data-source-field': source_field,
                    })
                )


class LookupMappingForm(forms.Form):
    """
    Form for mapping lookup values in Step 6.
    """
    
    def __init__(self, *args, lookup_values=None, **kwargs):
        """
        Initialize form with dynamic fields for lookup mappings.
        
        Args:
            lookup_values: Dictionary of source values to lookup options
        """
        super().__init__(*args, **kwargs)
        
        if lookup_values:
            for source_value, options in lookup_values.items():
                field_name = f'lookup_{source_value}'
                
                # Create choices from lookup options
                choices = [('', '-- Select Value --')]
                choices.extend([
                    (opt['pk'], opt.get('str', opt['pk']))
                    for opt in options
                ])
                
                self.fields[field_name] = forms.ChoiceField(
                    label=source_value,
                    choices=choices,
                    required=False,
                    widget=forms.Select(attrs={
                        'class': 'form-select lookup-mapping-select',
                        'data-source-value': source_value,
                    })
                )


class ValidationReviewForm(forms.Form):
    """
    Form for reviewing validation errors in Step 5.
    """
    
    deselect_fields = forms.MultipleChoiceField(
        label="Deselect Fields with Errors",
        help_text="Select fields to exclude from import due to validation errors.",
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input',
        })
    )
    
    def __init__(self, *args, fields_with_errors=None, **kwargs):
        """
        Initialize form with fields that have errors.
        
        Args:
            fields_with_errors: List of field names with validation errors
        """
        super().__init__(*args, **kwargs)
        
        if fields_with_errors:
            choices = [(field, field) for field in fields_with_errors]
            self.fields['deselect_fields'].choices = choices
