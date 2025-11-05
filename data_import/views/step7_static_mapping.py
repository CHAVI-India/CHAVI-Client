"""Step 7: Static Field Mapping View"""
from django.views.generic import FormView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, StaticFieldMapping
from data_import.services.field_introspection import FieldIntrospectionService
from .base import WizardStepMixin
import logging
import json

logger = logging.getLogger(__name__)


class Step7StaticMappingView(WizardStepMixin, FormView):
    """
    Step 7: Configure static field mappings for implicit data.
    Allows users to set static values for CHAVI fields not present in the data file.
    """
    
    step_number = 7
    step_title = "Static Field Mapping"
    step_status = ImportStatus.FIELD_MAPPING
    template_name = 'data_import/step7_static_mapping.html'
    next_step_url_name = 'import_step8_uuid_mapping'
    previous_step_url_name = 'import_step6_lookup_matching'
    
    def get_form_class(self):
        # Dynamic form will be created in template
        from django import forms
        return forms.Form
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.FIELD_MAPPING)
        
        return super().get(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import_data = self.get_import_data(self.kwargs['import_id'])
        field_service = FieldIntrospectionService()
        
        # Get all CHAVI fields
        all_fields = field_service.get_all_fields()
        
        # Get fields that are already mapped in previous steps
        excluded_fields = set()
        
        # 1. Fields mapped in Step 2 (Field Mapping)
        for mapping in import_data.data_fields.all():
            if mapping.client_app_field_name and mapping.client_app_table_name:
                excluded_fields.add(f"{mapping.client_app_table_name}.{mapping.client_app_field_name}")
        
        # 2. Fields used as targets in Step 4 (Date Interval Configuration)
        for interval_config in import_data.date_interval_field_configurations.all():
            if interval_config.target_date_field:
                excluded_fields.add(interval_config.target_date_field)
        
        # 3. Fields used in Step 6 (Lookup Matching)
        # Get lookup configurations from session
        lookup_config = self.request.session.get(f'lookup_config_{import_data.id}', {})
        for field_name in lookup_config.keys():
            # field_name is already in table.field format
            excluded_fields.add(field_name)
        
        logger.info(f"Excluded fields from static mapping: {excluded_fields}")
        
        # Filter available fields
        available_fields = []
        for field in all_fields:
            full_name = f"{field['table_name']}.{field['field_name']}"
            
            # Skip if already mapped/configured
            if full_name in excluded_fields:
                continue
            
            # Skip FK relationship fields (fields that point to other client_app models)
            # These will be handled in UUID mapping step
            if field.get('is_foreign_key', False):
                # Check if it's a relationship to another client_app model (not a lookup)
                related_model = field.get('related_model', '')
                if related_model and not field.get('is_lookup', False):
                    logger.info(f"Excluding FK relationship field: {full_name} -> {related_model}")
                    continue
            
            available_fields.append({
                'table_name': field['table_name'],
                'field_name': field['field_name'],
                'verbose_name': field.get('verbose_name', field['field_name']),
                'help_text': field.get('help_text', ''),
                'data_type': field.get('data_type', 'String'),
                'is_lookup': field.get('is_lookup', False),
                'lookup_model': field.get('lookup_model', ''),
                'is_required': field.get('is_required', False),
                'max_length': field.get('max_length', None),
                'has_choices': field.get('has_choices', False),
                'choices': field.get('choices', []),
                'full_name': full_name
            })
        
        # Get existing static mappings
        existing_mappings = []
        for mapping in import_data.static_field_mappings.all():
            # Get field metadata
            field_parts = mapping.chavi_field.split('.')
            if len(field_parts) == 2:
                field_meta = field_service.get_field(field_parts[0], field_parts[1])
                existing_mappings.append({
                    'id': mapping.id,
                    'chavi_field': mapping.chavi_field,
                    'static_value': mapping.static_value,
                    'field_meta': field_meta
                })
                logger.info(f"Loaded existing mapping: {mapping.chavi_field} = {mapping.static_value}")
        
        # Get lookup choices for lookup fields
        lookup_choices = {}
        for field in available_fields:
            if field['is_lookup'] and field['lookup_model']:
                try:
                    from django.apps import apps
                    # The lookup_model might be just the model name or app.Model format
                    lookup_model_name = field['lookup_model']
                    
                    # Try to get the model
                    if '.' in lookup_model_name:
                        # Format: app.Model
                        model = apps.get_model(lookup_model_name)
                    else:
                        # Lookup models are in the 'lookup' app, not 'client_app'
                        model = apps.get_model('lookup', lookup_model_name)
                    
                    # Get all instances
                    # Lookup models use 'code' as primary key, not 'id'
                    choices = []
                    for obj in model.objects.all():
                        # Use code (primary key) for lookup models
                        pk_value = obj.code if hasattr(obj, 'code') else obj.pk
                        choices.append({
                            'id': pk_value,
                            'name': str(obj)
                        })
                    
                    lookup_choices[field['full_name']] = choices
                    logger.info(f"Loaded {len(choices)} lookup choices for {field['full_name']} from lookup.{lookup_model_name}")
                    
                except Exception as e:
                    logger.error(f"Could not load lookup choices for {field['full_name']} (model: {field['lookup_model']}): {e}", exc_info=True)
                    lookup_choices[field['full_name']] = []
        
        # Build choices for CharField with choices and BooleanFields
        field_choices = {}
        for field in available_fields:
            if field['has_choices'] and field['choices']:
                # CharField with choices
                field_choices[field['full_name']] = field['choices']
            elif field['data_type'] == 'Boolean':
                # BooleanField - add True/False choices
                field_choices[field['full_name']] = [
                    {'value': 'True', 'display': 'Yes'},
                    {'value': 'False', 'display': 'No'}
                ]
        
        context.update({
            'available_fields': available_fields,
            'existing_mappings': existing_mappings,
            'lookup_choices_json': json.dumps(lookup_choices),
            'field_choices_json': json.dumps(field_choices),
            'import_data': import_data
        })
        
        return context
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            logger.info(f"Step 7 POST data: {dict(request.POST)}")
            
            # Clear existing static mappings
            StaticFieldMapping.objects.filter(import_data=import_data).delete()
            
            saved_count = 0
            field_service = FieldIntrospectionService()
            
            # Process static mappings
            # Format: static_field_0, static_value_0, static_field_1, static_value_1, etc.
            field_indices = set()
            for key in request.POST.keys():
                if key.startswith('static_field_'):
                    index = key.replace('static_field_', '')
                    field_indices.add(index)
            
            for index in field_indices:
                chavi_field = request.POST.get(f'static_field_{index}')
                static_value = request.POST.get(f'static_value_{index}')
                
                if chavi_field and static_value:
                    # Validate the field exists
                    field_parts = chavi_field.split('.')
                    if len(field_parts) == 2:
                        field_meta = field_service.get_field(field_parts[0], field_parts[1])
                        if field_meta:
                            # TODO: Add field-specific validation based on data_type
                            StaticFieldMapping.objects.create(
                                import_data=import_data,
                                chavi_field=chavi_field,
                                static_value=static_value
                            )
                            saved_count += 1
                            logger.info(f"Saved static mapping: {chavi_field} = {static_value}")
                        else:
                            logger.warning(f"Field {chavi_field} not found in field introspection")
                    else:
                        logger.warning(f"Invalid field format: {chavi_field}")
            
            if saved_count > 0:
                messages.success(request, f'Static mapping configured for {saved_count} field(s).')
            else:
                messages.info(request, 'No static fields configured. Proceeding to UUID mapping.')
            
            # Redirect to UUID mapping step
            return redirect('data_import:import_step8_uuid_mapping', import_id=import_data.id)
            
        except Exception as e:
            logger.error(f"Error saving static mappings: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return redirect(request.path)
