"""
Step 9: Handle missing FK relationships.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..models import FileMappedModel, FileMappedField, FileMissingRelations, FileImportSessionStep
from ..services import ModelHierarchyService, FieldIntrospectionService


class Step10MissingRelationsView(BaseImportView):
    """
    Step 10: Handle missing FK relationships by prompting user for values.
    Detects when importing child models without parent FK fields mapped.
    """
    step_identifier = FileImportSessionStep.MISSING_RELATIONS
    step_name = "Handle Missing Relationships"
    template_name = 'data_import/step10_missing_relations.html'
    
    def get(self, request, session_id):
        session = self.get_session(session_id)
        if not self.validate_step_access(session):
            return redirect('data_import:step9', session_id=session.id)
        
        # Get selected models
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model:
            messages.error(request, "No models selected.")
            return redirect('data_import:step3', session_id=session.id)
        
        selected_models = mapped_model.client_app_model_name
        
        # Get CSV headers and sample values for dropdown options
        headers, rows, error = self.get_csv_data(session)
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Get sample values for each CSV column
        csv_samples = {}
        if headers and rows:
            for col in headers:
                if col in headers:
                    col_index = headers.index(col)
                    # Find first non-empty value
                    for row in rows[:10]:
                        if isinstance(row, dict):
                            value = row.get(col, '').strip()
                        else:
                            value = row[col_index].strip() if col_index < len(row) else ''
                        
                        if value:
                            csv_samples[col] = value
                            break
        
        # Get mapped fields
        mapped_fields = FileMappedField.objects.filter(file_import_session=session)
        mapped_field_names = set()
        for mapping in mapped_fields:
            if '.' in mapping.mapped_client_app_field_name:
                model_name, field_name = mapping.mapped_client_app_field_name.split('.', 1)
                mapped_field_names.add((model_name, field_name))
        
        # Get existing missing relation values first
        existing_relations = FileMissingRelations.objects.filter(file_import_session=session)
        existing_relations_dict = {
            (r.client_app_model_name, r.client_app_field_name): r.client_app_field_value
            for r in existing_relations
        }
        
        # Detect missing FK relationships
        missing_relations = []
        for model_name in selected_models:
            # Get parent models (FK relationships)
            parent_models = ModelHierarchyService.get_parent_models(model_name)
            
            # Check if FK fields are mapped
            for fk_field_name, parent_model_name in parent_models.items():
                if (model_name, fk_field_name) not in mapped_field_names:
                    # This FK field is not mapped - check if it needs user input
                    field_info = FieldIntrospectionService.get_model_fields(model_name).get(fk_field_name)
                    
                    # Skip if field has a default value (like center with get_default_site)
                    if field_info and field_info.get('default') is not None:
                        # Check if default is not NOT_PROVIDED
                        from django.db.models.fields import NOT_PROVIDED
                        if field_info.get('default') != NOT_PROVIDED:
                            continue  # Skip this field, it has a default value
                    
                    # Get existing value if any
                    existing_value = existing_relations_dict.get((model_name, fk_field_name), '')
                    
                    # Check if this is a lookup field
                    is_lookup = field_info.get('is_lookup', False) if field_info else False
                    lookup_values = []
                    
                    if is_lookup and field_info:
                        # Fetch lookup table values
                        related_model = field_info.get('related_model')
                        if related_model:
                            try:
                                from django.apps import apps
                                lookup_model = apps.get_model('lookup', related_model)
                                lookup_values = list(lookup_model.objects.all().values('code', 'label'))
                            except:
                                pass
                    
                    missing_relations.append({
                        'model_name': model_name,
                        'field_name': fk_field_name,
                        'parent_model': parent_model_name,
                        'field_info': field_info,
                        'required': field_info.get('required', False) if field_info else False,
                        'existing_value': existing_value,
                        'is_lookup': is_lookup,
                        'lookup_values': lookup_values,
                    })
        
        context = self.get_context_data(
            session=session,
            missing_relations=missing_relations,
            existing_relations_dict=existing_relations_dict,
            csv_headers=headers,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        
        # Check if user wants to skip this step
        if 'skip_step' in request.POST:
            self.update_session_step(session, FileImportSessionStep.REVIEW)
            messages.info(request, "Skipped missing relationships handling.")
            return redirect('data_import:step11', session_id=session.id)
        
        # Clear existing missing relations
        FileMissingRelations.objects.filter(file_import_session=session).delete()
        
        # Process missing relation values
        # Format: relation_<model>_<field> = value
        relations_created = 0
        
        for key, value in request.POST.items():
            if key.startswith('relation_') and not key.endswith('_custom'):
                # Parse: relation_<model>_<field>
                parts = key[9:].split('_', 1)
                if len(parts) == 2:
                    model_name, field_name = parts
                    field_value = value
                    
                    # Check if custom value was provided instead
                    custom_key = f"{key}_custom"
                    custom_value = request.POST.get(custom_key, '').strip()
                    
                    # Use custom value if provided and dropdown is empty
                    if custom_value and not field_value:
                        field_value = custom_value
                    
                    if field_value:
                        FileMissingRelations.objects.create(
                            file_import_session=session,
                            client_app_model_name=model_name,
                            client_app_field_name=field_name,
                            client_app_field_value=field_value
                        )
                        relations_created += 1
        
        # Update session step to next step
        self.update_session_step(session, FileImportSessionStep.REVIEW)
        
        if relations_created > 0:
            messages.success(request, f"Configured {relations_created} missing relationship(s).")
        else:
            messages.info(request, "No missing relationships configured.")
        
        # Redirect to Step 11
        return redirect('data_import:step11', session_id=session.id)
