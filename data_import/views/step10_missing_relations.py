"""
Step 9: Handle missing FK relationships.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..models import (
    FileMappedModel, FileMappedField, FileMissingRelations, 
    FileParentRecordMapping, FileImportSessionStep, FilePatientID
)
from ..services import ModelHierarchyService, FieldIntrospectionService
from django.apps import apps


class Step10MissingRelationsView(BaseImportView):
    """
    Step 10: Handle missing FK relationships.
    - Auto-handles Patient FK (uses patient_id from CSV)
    - For other FKs, shows existing parent records to link to
    - Allows creating new parent records if needed
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
        
        # Get patient IDs from CSV to query existing records
        if not session.patient_id_column:
            messages.error(request, "Patient ID column not configured.")
            return redirect('data_import:step2', session_id=session.id)
        
        headers, rows, error = self.get_csv_data(session)
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Get unique patient IDs from CSV
        patient_ids = set()
        patient_id_col = session.patient_id_column
        if patient_id_col in headers:
            col_index = headers.index(patient_id_col)
            for row in rows:
                if isinstance(row, dict):
                    pid = row.get(patient_id_col, '').strip()
                else:
                    pid = row[col_index].strip() if col_index < len(row) else ''
                if pid:
                    patient_ids.add(pid)
        
        # Get mapped fields
        mapped_fields = FileMappedField.objects.filter(file_import_session=session)
        mapped_field_names = set()
        for mapping in mapped_fields:
            if '.' in mapping.mapped_client_app_field_name:
                model_name, field_name = mapping.mapped_client_app_field_name.split('.', 1)
                mapped_field_names.add((model_name, field_name))
        
        # Get existing parent record mappings
        existing_mappings = FileParentRecordMapping.objects.filter(file_import_session=session)
        existing_mappings_dict = {
            (m.child_model_name, m.parent_fk_field): m
            for m in existing_mappings
        }
        
        # Detect missing FK relationships
        missing_fk_relations = []
        for model_name in selected_models:
            # Get parent models (FK relationships)
            parent_models = ModelHierarchyService.get_parent_models(model_name)
            
            # Check if FK fields are mapped
            for fk_field_name, parent_model_name in parent_models.items():
                if (model_name, fk_field_name) not in mapped_field_names:
                    # This FK field is not mapped
                    field_info = FieldIntrospectionService.get_model_fields(model_name).get(fk_field_name)
                    
                    # Skip if field has a default value
                    if field_info and field_info.get('default') is not None:
                        from django.db.models.fields import NOT_PROVIDED
                        if field_info.get('default') != NOT_PROVIDED:
                            continue
                    
                    # Skip Patient FK - will be auto-handled
                    if parent_model_name == 'Patient':
                        continue
                    
                    # Query existing parent records for these patients
                    existing_parents = []
                    try:
                        parent_model_class = apps.get_model('client_app', parent_model_name)
                        # Query parent records for the patients in CSV
                        existing_parents = list(parent_model_class.objects.filter(
                            patient_id__in=patient_ids
                        ).values('id', 'patient_id')[:100])  # Limit to 100 records
                        
                        # Add display fields if available
                        display_fields = self._get_display_fields(parent_model_name)
                        if display_fields:
                            existing_parents = list(parent_model_class.objects.filter(
                                patient_id__in=patient_ids
                            ).values('id', 'patient_id', *display_fields)[:100])
                    except Exception as e:
                        print(f"Error querying {parent_model_name}: {e}")
                    
                    # Get existing mapping if any
                    existing_mapping = existing_mappings_dict.get((model_name, fk_field_name))
                    
                    # Get required fields for creating new parent
                    parent_required_fields = self._get_required_fields(parent_model_name)
                    
                    missing_fk_relations.append({
                        'child_model': model_name,
                        'fk_field': fk_field_name,
                        'parent_model': parent_model_name,
                        'existing_parents': existing_parents,
                        'existing_mapping': existing_mapping,
                        'parent_required_fields': parent_required_fields,
                    })
        
        # If no missing FK relationships, skip to next step
        if not missing_fk_relations:
            self.update_session_step(session, FileImportSessionStep.REVIEW)
            messages.info(request, "No missing FK relationships detected.")
            return redirect('data_import:step11', session_id=session.id)
        
        context = self.get_context_data(
            session=session,
            missing_fk_relations=missing_fk_relations,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        
        # Clear existing parent record mappings
        FileParentRecordMapping.objects.filter(file_import_session=session).delete()
        
        # Process parent record mappings
        # Format: fk_<child_model>_<fk_field>_action = link_existing | create_new
        mappings_created = 0
        
        for key, value in request.POST.items():
            if key.startswith('fk_') and key.endswith('_action'):
                # Parse: fk_<child_model>_<fk_field>_action
                parts = key[3:-7].rsplit('_', 1)  # Remove 'fk_' and '_action'
                if len(parts) == 2:
                    child_model, fk_field = parts
                    action = value  # 'link_existing' or 'create_new'
                    
                    # Get parent model name
                    parent_model = request.POST.get(f'fk_{child_model}_{fk_field}_parent_model', '')
                    
                    if action == 'link_existing':
                        # Get selected existing record ID
                        existing_id = request.POST.get(f'fk_{child_model}_{fk_field}_existing', '')
                        if existing_id:
                            FileParentRecordMapping.objects.create(
                                file_import_session=session,
                                child_model_name=child_model,
                                parent_fk_field=fk_field,
                                parent_model_name=parent_model,
                                link_to_existing=True,
                                existing_record_id=existing_id,
                            )
                            mappings_created += 1
                    
                    elif action == 'create_new':
                        # Collect field values for new parent
                        parent_fields = {}
                        for post_key in request.POST.keys():
                            if post_key.startswith(f'fk_{child_model}_{fk_field}_new_'):
                                field_name = post_key.replace(f'fk_{child_model}_{fk_field}_new_', '')
                                field_value = request.POST.get(post_key, '').strip()
                                if field_value:
                                    parent_fields[field_name] = field_value
                        
                        if parent_fields:
                            FileParentRecordMapping.objects.create(
                                file_import_session=session,
                                child_model_name=child_model,
                                parent_fk_field=fk_field,
                                parent_model_name=parent_model,
                                create_new_parent=True,
                                parent_field_values=parent_fields,
                            )
                            mappings_created += 1
        
        # Update session step to next step
        self.update_session_step(session, FileImportSessionStep.REVIEW)
        
        if mappings_created > 0:
            messages.success(request, f"Configured {mappings_created} parent relationship(s).")
        else:
            messages.warning(request, "No parent relationships configured.")
        
        # Redirect to Step 11
        return redirect('data_import:step11', session_id=session.id)
    
    def _get_display_fields(self, model_name):
        """Get fields to display for a model (e.g., date, site, etc.)"""
        display_map = {
            'Diagnosis': ['date_of_diagnosis', 'site'],
            'Pathology': ['date_of_pathology', 'histology'],
            'Surgery': ['date_of_surgery', 'procedure'],
            'Radiotherapy': ['start_date', 'end_date'],
            'Chemotherapy': ['start_date', 'end_date'],
        }
        return display_map.get(model_name, [])
    
    def _get_required_fields(self, model_name):
        """Get required fields for creating a new parent record"""
        fields = FieldIntrospectionService.get_model_fields(model_name)
        required_fields = []
        
        for field_name, field_info in fields.items():
            # Skip auto fields, PKs, FKs to Patient (auto-handled), timestamps
            if field_info.get('is_pk') or field_info.get('auto_created'):
                continue
            if field_name in ['id', 'patient', 'patient_id', 'created_at', 'updated_at']:
                continue
            
            # Include if required (no default and not nullable)
            if field_info.get('required') and not field_info.get('null'):
                required_fields.append({
                    'name': field_name,
                    'type': field_info.get('type'),
                    'is_lookup': field_info.get('is_lookup', False),
                    'related_model': field_info.get('related_model'),
                })
        
        return required_fields
