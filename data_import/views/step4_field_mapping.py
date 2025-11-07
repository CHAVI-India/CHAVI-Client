"""
Step 4: Map CSV columns to model fields (wide format support).
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from .base import BaseImportView
from ..models import FileMappedModel, FileMappedField, FileImportSessionStep
from ..services import FieldIntrospectionService, ModelHierarchyService


class Step4FieldMappingView(BaseImportView):
    """
    Step 4: Map CSV columns to model fields.
    Supports mapping multiple CSV columns to a single field (wide format).
    """
    step_identifier = FileImportSessionStep.FIELD_MAPPING
    step_name = "Map Fields"
    template_name = 'data_import/step4_field_mapping.html'
    
    def get(self, request, session_id):
        """
        Display field mapping form.
        """
        session = self.get_session(session_id)
        
        # Validate step access
        if not self.validate_step_access(session):
            return redirect('data_import:step3', session_id=session.id)
        
        # Get selected models
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model or not mapped_model.client_app_model_name:
            messages.error(request, "No models selected. Please complete Step 3 first.")
            return redirect('data_import:step3', session_id=session.id)
        
        selected_models = mapped_model.client_app_model_name
        
        # Get CSV headers
        headers, rows, error = self.get_csv_data(session)
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Get fields for each selected model and structure for template
        models_data = []
        for model_name in selected_models:
            fields = FieldIntrospectionService.get_model_fields(model_name)
            
            # Exclude fields that are already mapped in previous steps
            exclude_fields = set()
            if model_name == 'Patient':
                # Patient ID mapped in Step 2, Projects mapped in Step 1, Center auto-linked
                exclude_fields = {'patient_id', 'patient_project', 'center'}
            
            # Convert fields dict to list of tuples for template iteration
            fields_list = []
            for field_name, field_info in fields.items():
                if field_name in exclude_fields:
                    continue
                
                # Skip FK and M2M fields that point to selected models or excluded models
                if field_info.get('is_fk') or field_info.get('type') == 'ManyToManyField':
                    related_model = field_info.get('related_model')
                    if related_model:
                        # Skip if points to a selected model (will be handled in Step 10)
                        if related_model in selected_models:
                            continue
                        # Skip if points to an excluded model (DICOM, system models)
                        if related_model in ModelHierarchyService.EXCLUDED_MODELS:
                            continue
                        # Skip common system models
                        system_models = ['User', 'Group', 'Permission', 'ContentType', 'Session']
                        if related_model in system_models:
                            continue
                
                fields_list.append({
                    'name': field_name,
                    'info': field_info,
                })
            
            models_data.append({
                'name': model_name,
                'fields': fields_list,
            })
        
        # Get existing mappings
        existing_mappings = FileMappedField.objects.filter(file_import_session=session)
        
        # Build existing mappings dict for display
        existing_mappings_dict = {}
        for mapping in existing_mappings:
            existing_mappings_dict[mapping.mapped_client_app_field_name] = mapping.csv_field_names
        
        context = self.get_context_data(
            session=session,
            selected_models=selected_models,
            models_data=models_data,
            csv_headers=headers,
            existing_mappings=existing_mappings,
            existing_mappings_dict=existing_mappings_dict,
        )
        
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        """
        Handle field mapping submission.
        Process mappings in format: field_<model>_<field_name> = [csv_column1, csv_column2, ...]
        """
        session = self.get_session(session_id)
        
        # Get selected models
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model:
            messages.error(request, "No models selected.")
            return redirect('data_import:step3', session_id=session.id)
        
        selected_models = mapped_model.client_app_model_name
        
        # Clear existing mappings
        FileMappedField.objects.filter(file_import_session=session).delete()
        
        # Process form data
        mappings_created = 0
        for key, value in request.POST.items():
            if key.startswith('field_'):
                # Parse field name: field_<model>_<field_name>
                parts = key.split('_', 2)
                if len(parts) == 3:
                    _, model_name, field_name = parts
                    
                    # Get selected CSV columns (can be multiple for wide format)
                    csv_columns = request.POST.getlist(key)
                    
                    if csv_columns and any(csv_columns):
                        # Filter out empty values
                        csv_columns = [col for col in csv_columns if col]
                        
                        if csv_columns:
                            # Create mapping
                            FileMappedField.objects.create(
                                file_import_session=session,
                                csv_field_names=csv_columns,  # Store as JSON array
                                mapped_client_app_field_name=f"{model_name}.{field_name}"
                            )
                            mappings_created += 1
        
        if mappings_created == 0:
            messages.warning(request, "No field mappings created. Please map at least one field.")
            return redirect('data_import:step4', session_id=session.id)
        
        # Update session step to 5 (next step) to allow access
        self.update_session_step(session, FileImportSessionStep.COLUMN_VALUE)
        
        messages.success(request, f"Created {mappings_created} field mapping(s).")
        
        # Redirect to Step 5
        return redirect('data_import:step5', session_id=session.id)
