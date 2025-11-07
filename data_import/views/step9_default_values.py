"""
Step 9: Set default values for unmapped fields.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..models import FileMappedModel, FileMappedField, FileDefaultValues, FileImportSessionStep
from ..services import FieldIntrospectionService, ModelHierarchyService


class Step9DefaultValuesView(BaseImportView):
    """
    Step 9: Set default values for unmapped client_app model fields.
    These values will apply to all patients in the import session.
    """
    step_identifier = FileImportSessionStep.DEFAULT_VALUES
    step_name = "Set Default Values"
    template_name = 'data_import/step9_default_values.html'
    
    def get(self, request, session_id):
        session = self.get_session(session_id)
        if not self.validate_step_access(session):
            return redirect('data_import:step8', session_id=session.id)
        
        # Get selected models
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model:
            messages.error(request, "No models selected.")
            return redirect('data_import:step3', session_id=session.id)
        
        selected_models = mapped_model.client_app_model_name
        
        # Get existing default values first
        existing_defaults = {}
        for default in FileDefaultValues.objects.filter(file_import_session=session):
            key = f"{default.client_app_model_name}.{default.client_app_field_name}"
            existing_defaults[key] = default.client_app_field_value
        
        # Get mapped fields
        mapped_fields = FileMappedField.objects.filter(file_import_session=session)
        mapped_field_names = set()
        for mf in mapped_fields:
            if '.' in mf.mapped_client_app_field_name:
                mapped_field_names.add(mf.mapped_client_app_field_name)
        
        # Find unmapped fields that might need default values
        unmapped_fields = []
        for model_name in selected_models:
            fields = FieldIntrospectionService.get_model_fields(model_name)
            for field_name, field_info in fields.items():
                full_field_name = f"{model_name}.{field_name}"
                
                # Skip if already mapped
                if full_field_name in mapped_field_names:
                    continue
                
                # Skip auto fields, PKs, timestamps
                if field_info.get('is_pk') or field_info.get('auto_created'):
                    continue
                if field_name in ['created_at', 'updated_at', 'id']:
                    continue
                
                # Skip fields that are already handled elsewhere
                if model_name == 'Patient':
                    # patient_id handled in Step 2, center auto-linked, project handled in Step 1
                    if field_name in ['patient_id', 'center', 'patient_project']:
                        continue
                
                # Skip FK and M2M fields pointing to selected models or system/excluded models
                if field_info.get('is_fk') or field_info.get('type') == 'ManyToManyField':
                    related_model = field_info.get('related_model')
                    if related_model:
                        # Skip if points to a selected model (handled in Step 10)
                        if related_model in selected_models:
                            continue
                        # Skip if points to an excluded model (DICOM, system models)
                        if related_model in ModelHierarchyService.EXCLUDED_MODELS:
                            continue
                        # Skip common system models that shouldn't be in default values
                        system_models = ['User', 'Group', 'Permission', 'ContentType', 'Session']
                        if related_model in system_models:
                            continue
                
                # Skip if field has a default value or is nullable
                if field_info.get('has_default') or field_info.get('null'):
                    continue
                
                # Get lookup values if applicable
                lookup_values = None
                if field_info.get('is_lookup') and field_info.get('related_model'):
                    lookup_model = field_info['related_model']
                    try:
                        from django.apps import apps
                        model_class = apps.get_model('lookup', lookup_model)
                        lookup_values = list(model_class.objects.all().values('code', 'label'))
                    except:
                        pass
                
                # Add to unmapped fields
                unmapped_fields.append({
                    'model': model_name,
                    'field': field_name,
                    'full_name': full_field_name,
                    'field_info': field_info,
                    'lookup_values': lookup_values,
                    'existing_value': existing_defaults.get(full_field_name, ''),
                })
        
        context = self.get_context_data(
            session=session,
            unmapped_fields=unmapped_fields,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        
        # Check if user wants to skip this step
        if 'skip_step' in request.POST:
            self.update_session_step(session, FileImportSessionStep.MISSING_RELATIONS)
            messages.info(request, "Skipped default values configuration.")
            return redirect('data_import:step10', session_id=session.id)
        
        # Clear existing default values
        FileDefaultValues.objects.filter(file_import_session=session).delete()
        
        # Process default values
        # Format: default_<model>_<field> = value
        defaults_created = 0
        
        for key, value in request.POST.items():
            if key.startswith('default_'):
                # Parse: default_<model>_<field>
                parts = key[8:].split('_', 1)
                if len(parts) == 2:
                    model_name, field_name = parts
                    field_value = value
                    
                    if field_value:
                        FileDefaultValues.objects.create(
                            file_import_session=session,
                            client_app_model_name=model_name,
                            client_app_field_name=field_name,
                            client_app_field_value=field_value
                        )
                        defaults_created += 1
        
        # Update session step to next step
        self.update_session_step(session, FileImportSessionStep.MISSING_RELATIONS)
        
        if defaults_created > 0:
            messages.success(request, f"Configured {defaults_created} default value(s).")
        else:
            messages.info(request, "No default values configured.")
        
        # Redirect to Step 10
        return redirect('data_import:step10', session_id=session.id)
