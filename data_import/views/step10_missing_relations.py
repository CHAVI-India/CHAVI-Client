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
        
        # Detect missing FK relationships and group by parent model
        parent_relationships = {}  # {parent_model: {children: [...], existing_parents: [...], ...}}
        
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
                    
                    # Initialize parent model entry if not exists
                    if parent_model_name not in parent_relationships:
                        # Query existing parent records for these patients
                        existing_parents = []
                        try:
                            parent_model_class = apps.get_model('client_app', parent_model_name)
                            # Get the primary key field name
                            pk_field = parent_model_class._meta.pk.name
                            
                            # Query parent records for the patients in CSV
                            display_fields = self._get_display_fields(parent_model_name)
                            if display_fields:
                                existing_parents = list(parent_model_class.objects.filter(
                                    patient_id__in=patient_ids
                                ).values(pk_field, 'patient_id', *display_fields)[:100])
                            else:
                                existing_parents = list(parent_model_class.objects.filter(
                                    patient_id__in=patient_ids
                                ).values(pk_field, 'patient_id')[:100])
                            
                            # Normalize to use 'id' key for template consistency
                            for parent in existing_parents:
                                if pk_field != 'id':
                                    parent['id'] = parent[pk_field]
                        except Exception as e:
                            print(f"Error querying {parent_model_name}: {e}")
                        
                        # Get required fields for creating new parent
                        parent_required_fields_raw = self._get_required_fields(parent_model_name)
                        
                        # Check if there's an existing mapping for this parent (to pre-populate form)
                        existing_parent_mapping = None
                        saved_field_values = {}
                        for mapping in existing_mappings:
                            if mapping.parent_model_name == parent_model_name and mapping.create_new_parent:
                                existing_parent_mapping = mapping
                                saved_field_values = mapping.parent_field_values or {}
                                break
                        
                        # Add saved values to each field
                        parent_required_fields = []
                        for field in parent_required_fields_raw:
                            field_with_value = field.copy()
                            field_with_value['saved_value'] = saved_field_values.get(field['name'], '')
                            parent_required_fields.append(field_with_value)
                        
                        parent_relationships[parent_model_name] = {
                            'parent_model': parent_model_name,
                            'existing_parents': existing_parents,
                            'has_existing_parents': len(existing_parents) > 0,
                            'parent_required_fields': parent_required_fields,
                            'children': [],
                            'existing_mapping': existing_parent_mapping,
                            'selected_action': 'create_new' if existing_parent_mapping and existing_parent_mapping.create_new_parent else ('link_existing' if existing_parent_mapping and existing_parent_mapping.link_to_existing else ''),
                            'selected_existing_id': existing_parent_mapping.existing_record_id if existing_parent_mapping and existing_parent_mapping.link_to_existing else '',
                        }
                    
                    # Add child model to this parent's children list
                    parent_relationships[parent_model_name]['children'].append({
                        'child_model': model_name,
                        'fk_field': fk_field_name,
                        'existing_mapping': existing_mappings_dict.get((model_name, fk_field_name))
                    })
        
        # Convert to list for template
        missing_fk_relations = list(parent_relationships.values())
        
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
        
        # Get selected models to rebuild parent-child relationships
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model:
            messages.error(request, "No models selected.")
            return redirect('data_import:step3', session_id=session.id)
        
        selected_models = mapped_model.client_app_model_name
        
        # Get mapped fields
        mapped_fields = FileMappedField.objects.filter(file_import_session=session)
        mapped_field_names = set()
        for mapping in mapped_fields:
            if '.' in mapping.mapped_client_app_field_name:
                model_name, field_name = mapping.mapped_client_app_field_name.split('.', 1)
                mapped_field_names.add((model_name, field_name))
        
        # Build parent-child relationship map
        parent_children_map = {}  # {parent_model: [(child_model, fk_field), ...]}
        
        for model_name in selected_models:
            parent_models = ModelHierarchyService.get_parent_models(model_name)
            for fk_field_name, parent_model_name in parent_models.items():
                if (model_name, fk_field_name) not in mapped_field_names and parent_model_name != 'Patient':
                    if parent_model_name not in parent_children_map:
                        parent_children_map[parent_model_name] = []
                    parent_children_map[parent_model_name].append((model_name, fk_field_name))
        
        # Process parent record mappings by parent model
        # Format: parent_<parent_model>_action = link_existing | create_new
        mappings_created = 0
        
        for parent_model in parent_children_map.keys():
            action_key = f'parent_{parent_model}_action'
            action = request.POST.get(action_key, '')
            
            if action == 'link_existing':
                # Get selected existing record ID
                existing_id = request.POST.get(f'parent_{parent_model}_existing', '')
                if existing_id:
                    # Create mapping for each child that needs this parent
                    for child_model, fk_field in parent_children_map[parent_model]:
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
                    if post_key.startswith(f'parent_{parent_model}_new_'):
                        field_name = post_key.replace(f'parent_{parent_model}_new_', '')
                        field_value = request.POST.get(post_key, '').strip()
                        if field_value:
                            parent_fields[field_name] = field_value
                
                # Create mapping for each child that needs this parent (with same parent_fields)
                for child_model, fk_field in parent_children_map[parent_model]:
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
        """Get fields to display in existing record dropdown (limit to first few non-FK fields)"""
        fields = FieldIntrospectionService.get_model_fields(model_name)
        display_fields = []
        
        for field_name, field_info in fields.items():
            # Skip PKs, FKs, M2M, timestamps, and patient field
            if field_info.get('is_pk') or field_info.get('is_fk'):
                continue
            if field_info.get('type') == 'ManyToManyField':
                continue
            if field_name in ['patient', 'patient_id', 'created_at', 'updated_at']:
                continue
            
            # Add field for display
            display_fields.append(field_name)
            if len(display_fields) >= 2:  # Limit to 2 fields for dropdown display
                break
        
        return display_fields
    
    def _get_required_fields(self, model_name):
        """Get ALL fields for creating a new parent record (excluding auto/system fields)"""
        fields = FieldIntrospectionService.get_model_fields(model_name)
        field_list = []
        
        for field_name, field_info in fields.items():
            # Skip auto fields, PKs, timestamps
            if field_info.get('is_pk') or field_info.get('auto_created'):
                continue
            if field_name in ['patient', 'patient_id', 'created_at', 'updated_at']:
                continue
            
            # Skip FK and M2M fields pointing to excluded models
            if field_info.get('is_fk') or field_info.get('type') == 'ManyToManyField':
                related_model = field_info.get('related_model')
                if related_model:
                    # Skip if points to excluded model
                    if related_model in ModelHierarchyService.EXCLUDED_MODELS:
                        continue
                    # Skip common system models
                    system_models = ['User', 'Group', 'Permission', 'ContentType', 'Session']
                    if related_model in system_models:
                        continue
            
            # Determine if truly required (no default, not nullable, not blank)
            is_required = (
                not field_info.get('null', False) and 
                not field_info.get('has_default', False) and
                not field_info.get('blank', False)
            )
            
            # Get lookup values if this is a lookup field
            lookup_values = []
            if field_info.get('is_lookup') and field_info.get('related_model'):
                lookup_model = field_info['related_model']
                try:
                    from django.apps import apps
                    model_class = apps.get_model('lookup', lookup_model)
                    lookup_values = list(model_class.objects.all().values('code', 'label'))
                except Exception as e:
                    print(f"Error loading lookup values for {lookup_model}: {e}")
            
            field_list.append({
                'name': field_name,
                'type': field_info.get('type'),
                'is_lookup': field_info.get('is_lookup', False),
                'related_model': field_info.get('related_model'),
                'required': is_required,
                'lookup_values': lookup_values,
            })
        
        return field_list
