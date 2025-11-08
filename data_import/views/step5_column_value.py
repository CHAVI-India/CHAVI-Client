"""
Step 5: Map column names to field values.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..models import FileMappedModel, FileMappedField, FileColumnFieldValueMapping, FileImportSessionStep
from ..services import FieldIntrospectionService, CSVProcessorService


class Step5ColumnValueMappingView(BaseImportView):
    """
    Step 5: Map column names to field values (e.g., 'Diabetes' column -> comorbidity_type field).
    This is for cases where CSV column names represent data values.
    """
    step_identifier = FileImportSessionStep.COLUMN_VALUE
    step_name = "Map Column Values"
    template_name = 'data_import/step5_column_value.html'
    
    def get(self, request, session_id):
        session = self.get_session(session_id)
        if not self.validate_step_access(session):
            return redirect('data_import:step4', session_id=session.id)
        
        # Get selected models
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model:
            messages.error(request, "No models selected.")
            return redirect('data_import:step3', session_id=session.id)
        
        # Get complete model list including parent models
        user_selected_models = mapped_model.client_app_model_name
        selected_models = ModelHierarchyService.get_complete_model_list(user_selected_models)
        
        # Get CSV headers
        headers, rows, error = self.get_csv_data(session)
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Get already mapped fields from Step 4 (exclude these columns)
        mapped_fields = FileMappedField.objects.filter(file_import_session=session)
        mapped_csv_columns = set()
        for mapping in mapped_fields:
            if mapping.csv_field_names:
                mapped_csv_columns.update(mapping.csv_field_names)
        
        # Available columns for value mapping (not yet mapped in Step 4)
        available_columns = [h for h in headers if h not in mapped_csv_columns]
        
        # Get fields for selected models that could be value fields
        models_fields = {}
        lookup_data = {}  # Store lookup table data
        
        for model_name in selected_models:
            fields = FieldIntrospectionService.get_model_fields(model_name)
            # Filter to fields that make sense for value mapping (FK, choices, etc.)
            value_fields = {}
            for name, info in fields.items():
                if info.get('is_fk') or info.get('choices') or info.get('type') in ['CharField', 'TextField', 'DateField', 'DateTimeField', 'BooleanField']:
                    value_fields[name] = info
                    
                    # If it's a lookup field, fetch the lookup data
                    if info.get('is_lookup') and info.get('related_model'):
                        lookup_model_name = info.get('related_model')
                        lookup_key = f"{model_name}.{name}"
                        
                        try:
                            from django.apps import apps
                            lookup_model = apps.get_model('lookup', lookup_model_name)
                            # Get all lookup values
                            lookup_values = list(lookup_model.objects.all().values('code', 'label'))
                            lookup_data[lookup_key] = lookup_values
                        except:
                            pass
            
            if value_fields:
                models_fields[model_name] = value_fields
        
        # Get existing column value mappings
        existing_mappings = FileColumnFieldValueMapping.objects.filter(file_import_session=session)
        
        context = self.get_context_data(
            session=session,
            available_columns=available_columns,
            models_fields=models_fields,
            selected_models=selected_models,
            existing_mappings=existing_mappings,
            lookup_data=lookup_data,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        
        # Check if user wants to skip this step
        if 'skip_step' in request.POST:
            self.update_session_step(session, FileImportSessionStep.DATE_FORMAT)
            messages.info(request, "Skipped column value mapping.")
            return redirect('data_import:step6', session_id=session.id)
        
        # Clear existing mappings
        FileColumnFieldValueMapping.objects.filter(file_import_session=session).delete()
        
        # Process column value mappings
        # Format: column_<csv_column_name>_field = model.field_name
        #         column_<csv_column_name>_value = field_value
        #         column_<csv_column_name>_additional_fields = JSON
        #         column_<csv_column_name>_additional_values = JSON
        
        mappings_created = 0
        processed_columns = set()
        
        for key in request.POST.keys():
            if key.startswith('column_') and key.endswith('_field'):
                # Extract column name
                column_name = key[7:-6]  # Remove 'column_' prefix and '_field' suffix
                
                if column_name in processed_columns:
                    continue
                
                field_name = request.POST.get(f'column_{column_name}_field')
                field_value = request.POST.get(f'column_{column_name}_value')
                
                if field_name and field_value:
                    # Get additional fields if any
                    additional_fields_str = request.POST.get(f'column_{column_name}_additional_fields', '[]')
                    additional_values_str = request.POST.get(f'column_{column_name}_additional_values', '[]')
                    
                    import json
                    try:
                        additional_fields = json.loads(additional_fields_str) if additional_fields_str else []
                        additional_values = json.loads(additional_values_str) if additional_values_str else []
                    except json.JSONDecodeError:
                        additional_fields = []
                        additional_values = []
                    
                    # Create mapping
                    FileColumnFieldValueMapping.objects.create(
                        file_import_session=session,
                        csv_column_name=column_name,
                        mapped_client_app_field_name=field_name,
                        mapped_client_app_field_value=field_value,
                        mapped_client_app_additional_field_names=additional_fields,
                        mapped_client_app_additional_field_values=additional_values
                    )
                    mappings_created += 1
                    processed_columns.add(column_name)
        
        # Update session step to next step
        self.update_session_step(session, FileImportSessionStep.DATE_FORMAT)
        
        if mappings_created > 0:
            messages.success(request, f"Created {mappings_created} column value mapping(s).")
        else:
            messages.info(request, "No column value mappings created.")
        
        # Redirect to Step 6
        return redirect('data_import:step6', session_id=session.id)
