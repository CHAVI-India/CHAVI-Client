"""
Step 8: Map CSV values to lookup table values.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from django.apps import apps
from .base import BaseImportView
from ..models import FileMappedModel, FileMappedField, FieldLookupValues, FileImportSessionStep
from ..services import FieldIntrospectionService, CSVProcessorService


class Step8LookupMappingView(BaseImportView):
    """
    Step 8: Map CSV values to lookup table values.
    """
    step_identifier = FileImportSessionStep.LOOKUP_MAPPING
    step_name = "Map Lookup Values"
    template_name = 'data_import/step8_lookup_mapping.html'
    
    def get(self, request, session_id):
        session = self.get_session(session_id)
        if not self.validate_step_access(session):
            return redirect('data_import:step7', session_id=session.id)
        
        # Get selected models
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model:
            messages.error(request, "No models selected.")
            return redirect('data_import:step3', session_id=session.id)
        
        selected_models = mapped_model.client_app_model_name
        
        # Get CSV data
        headers, rows, error = self.get_csv_data(session)
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Get mapped fields from Step 4
        mapped_fields = FileMappedField.objects.filter(file_import_session=session)
        
        # Identify fields that reference lookup tables
        lookup_fields_info = []
        for mapping in mapped_fields:
            if '.' in mapping.mapped_client_app_field_name:
                model_name, field_name = mapping.mapped_client_app_field_name.split('.', 1)
                
                # Get field info
                fields = FieldIntrospectionService.get_model_fields(model_name)
                field_info = fields.get(field_name)
                
                # Check if this field references a lookup table
                if field_info and field_info.get('is_lookup'):
                    # Get unique values from CSV for this field
                    csv_columns = mapping.csv_field_names
                    unique_values = set()
                    for col in csv_columns:
                        values = CSVProcessorService.get_unique_values(rows, col, headers)
                        unique_values.update(values)
                    
                    # Get lookup model and its values
                    lookup_model_name = field_info.get('related_model')
                    lookup_model = apps.get_model('lookup', lookup_model_name)
                    lookup_values = list(lookup_model.objects.all().values('code', 'label'))
                    
                    lookup_fields_info.append({
                        'mapping': mapping,
                        'model_name': model_name,
                        'field_name': field_name,
                        'csv_columns': csv_columns,
                        'unique_csv_values': sorted(unique_values),
                        'lookup_model': lookup_model_name,
                        'lookup_values': lookup_values,
                    })
        
        # Get existing lookup mappings
        existing_mappings = FieldLookupValues.objects.filter(file_import_session=session)
        existing_mappings_dict = {(m.csv_column_name, m.lookup_value): True for m in existing_mappings}
        
        context = self.get_context_data(
            session=session,
            lookup_fields_info=lookup_fields_info,
            existing_mappings_dict=existing_mappings_dict,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        
        # Check if user wants to skip this step
        if 'skip_step' in request.POST:
            self.update_session_step(session, FileImportSessionStep.DEFAULT_VALUES)
            messages.info(request, "Skipped lookup value mapping.")
            return redirect('data_import:step9', session_id=session.id)
        
        # Clear existing lookup mappings
        FieldLookupValues.objects.filter(file_import_session=session).delete()
        
        # Process lookup mappings
        # Format: lookup_<csv_column>_<csv_value> = lookup_code
        mappings_created = 0
        
        for key, value in request.POST.items():
            if key.startswith('lookup_'):
                # Parse: lookup_<column>_<csv_value>
                parts = key[7:].rsplit('_', 1)
                if len(parts) == 2:
                    csv_column, csv_value = parts
                    lookup_code = value
                    
                    if lookup_code:
                        FieldLookupValues.objects.create(
                            file_import_session=session,
                            csv_column_name=csv_column,
                            csv_value=csv_value,  # Store the CSV value
                            lookup_value=lookup_code
                        )
                        mappings_created += 1
        
        # Update session step to next step
        self.update_session_step(session, FileImportSessionStep.DEFAULT_VALUES)
        
        if mappings_created > 0:
            messages.success(request, f"Created {mappings_created} lookup value mapping(s).")
        else:
            messages.info(request, "No lookup value mappings created.")
        
        # Redirect to new Step 9 (Default Values)
        return redirect('data_import:step9', session_id=session.id)
