"""Step 8: UUID Mapping View"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, UUIDFieldConfiguration
from data_import.services.field_introspection import FieldIntrospectionService
from data_import.services.model_hierarchy import ModelHierarchyService
from .base import WizardStepMixin
from collections import defaultdict
import json
import logging

logger = logging.getLogger(__name__)

class Step8UUIDMappingView(WizardStepMixin, TemplateView):
    """
    Step 8: Configure UUID field mappings with hierarchical model dependencies.
    
    This step analyzes which models are involved in the import and ensures that
    all transitive dependencies are satisfied. For example, if importing
    Immunohistochemistry data, it ensures Patient, Diagnosis, and Pathology
    are all configured.
    """
    
    step_number = 8
    step_title = "UUID Mapping"
    step_status = ImportStatus.UUID_MAPPING
    template_name = 'data_import/step8_uuid_mapping.html'
    next_step_url_name = 'import_step9_json_preview'
    previous_step_url_name = 'import_step7_static_mapping'
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.UUID_MAPPING)
        
        try:
            field_service = FieldIntrospectionService()
            hierarchy_service = ModelHierarchyService()
            
            # Get all tables that have mapped fields (from Step 2)
            mapped_tables = set()
            table_field_mappings = defaultdict(list)
            
            for mapping in import_data.data_fields.all():
                if not mapping.client_app_field_name or not mapping.client_app_table_name:
                    continue
                
                table_name = mapping.client_app_table_name
                mapped_tables.add(table_name)
                
                # Include ALL field types for UUID generation (Standard, FK, M2M)
                # FK/M2M fields are important as they establish relationships
                field_meta = field_service.get_field(table_name, mapping.client_app_field_name)
                table_field_mappings[table_name].append({
                    'file_field': mapping.file_field_name,
                    'chavi_field': mapping.client_app_field_name,
                    'data_type': field_meta.get('data_type', 'String') if field_meta else 'String',
                    'field_type': mapping.client_app_field_type
                })
            
            # Also include tables from static field mappings (from Step 7)
            for static_mapping in import_data.static_field_mappings.all():
                if static_mapping.chavi_field:
                    # Parse table.field format
                    parts = static_mapping.chavi_field.split('.')
                    if len(parts) == 2:
                        table_name = parts[0]
                        mapped_tables.add(table_name)
                        logger.info(f"Step 8: Added table from static mapping: {table_name}")
            
            logger.info(f"Step 8: Mapped tables (including static): {mapped_tables}")
            
            # Analyze required models and dependencies
            required_info = hierarchy_service.get_required_models_for_import(mapped_tables)
            required_models = required_info['required']
            dependency_chains = required_info['dependency_chains']
            missing_models = required_info['missing']
            
            logger.info(f"Step 8: Required models: {required_models}")
            logger.info(f"Step 8: Missing models: {missing_models}")
            logger.info(f"Step 8: Dependency chains: {dependency_chains}")
            
            # Build hierarchical structure for UI
            hierarchical_structure = hierarchy_service.build_hierarchical_structure(required_models)
            
            # For each required model, get available fields and existing UUID config
            model_configs = []
            for model_info in hierarchical_structure:
                model_name = model_info['model_name']
                table_name = model_info['table_name']
                
                # Get available fields for this table from field mappings
                available_fields = list(table_field_mappings.get(table_name, []))
                
                # Add static field mappings (from Step 7)
                for static_mapping in import_data.static_field_mappings.all():
                    if static_mapping.chavi_field:
                        parts = static_mapping.chavi_field.split('.')
                        if len(parts) == 2 and parts[0] == table_name:
                            field_name = parts[1]
                            # Add as a virtual field with static value indicator
                            available_fields.append({
                                'file_field': f'{field_name} (static)',
                                'chavi_field': field_name,
                                'data_type': 'Static',
                                'field_type': 'Static',
                                'static_value': static_mapping.static_value
                            })
                
                # Add date interval fields (from Step 4)
                from data_import.models import ImportDateIntervalFieldConfiguration
                for interval_config in ImportDateIntervalFieldConfiguration.objects.filter(
                    import_data=import_data
                ):
                    # target_date_field is in format "table.field"
                    if interval_config.target_date_field:
                        parts = interval_config.target_date_field.split('.')
                        if len(parts) == 2 and parts[0] == table_name:
                            field_name = parts[1]
                            available_fields.append({
                                'file_field': f'{interval_config.interval_field} (computed)',
                                'chavi_field': field_name,
                                'data_type': 'Date',
                                'field_type': 'Computed',
                                'interval_units': interval_config.interval_units
                            })
                
                # Get existing UUID configuration
                existing_config = UUIDFieldConfiguration.objects.filter(
                    import_data=import_data,
                    table_name=table_name
                ).first()
                
                selected_fields = []
                if existing_config:
                    selected_fields = json.loads(existing_config.uuid_fields) if existing_config.uuid_fields else []
                
                model_configs.append({
                    **model_info,
                    'available_fields': available_fields,
                    'selected_fields': selected_fields,
                    'has_fields': len(available_fields) > 0,
                    'is_missing': model_name in missing_models,
                    'dependency_chain': dependency_chains.get(model_name, [])
                })
            
            context = self.get_context_data(**kwargs)
            context['model_configs'] = model_configs
            context['missing_models'] = missing_models
            context['has_missing_models'] = len(missing_models) > 0
            context['total_required_models'] = len(required_models)
            
            return self.render_to_response(context)
            
        except Exception as e:
            logger.error(f"UUID mapping error: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            hierarchy_service = ModelHierarchyService()
            
            # Get all tables that have mapped fields (from Step 2)
            mapped_tables = set()
            for mapping in import_data.data_fields.all():
                if mapping.client_app_field_name and mapping.client_app_table_name:
                    mapped_tables.add(mapping.client_app_table_name)
            
            # Also include tables from static field mappings (from Step 7)
            for static_mapping in import_data.static_field_mappings.all():
                if static_mapping.chavi_field:
                    parts = static_mapping.chavi_field.split('.')
                    if len(parts) == 2:
                        mapped_tables.add(parts[0])
            
            # Get required models
            required_info = hierarchy_service.get_required_models_for_import(mapped_tables)
            required_models = required_info['required']
            
            # Clear existing UUID configurations
            UUIDFieldConfiguration.objects.filter(import_data=import_data).delete()
            
            saved_count = 0
            errors = []
            
            # Process each table's UUID configuration
            for key in request.POST.keys():
                if key.startswith('uuid_fields_'):
                    table_name = key.replace('uuid_fields_', '')
                    selected_fields = request.POST.getlist(key)
                    
                    if not selected_fields:
                        # Get model name for better error message
                        model_name = hierarchy_service._table_to_model_name(table_name)
                        errors.append(f'Please select at least one field for {model_name} ({table_name}) to determine uniqueness.')
                        continue
                    
                    # Save UUID field configuration
                    UUIDFieldConfiguration.objects.create(
                        import_data=import_data,
                        table_name=table_name,
                        uuid_fields=json.dumps(selected_fields)
                    )
                    saved_count += 1
                    logger.info(f"Saved UUID config for {table_name}: {selected_fields}")
            
            # Validate that all required models have UUID configurations
            configured_tables = set(UUIDFieldConfiguration.objects.filter(
                import_data=import_data
            ).values_list('table_name', flat=True))
            
            missing_configs = []
            for model_name in required_models:
                table_name = hierarchy_service._model_to_table_name(model_name)
                if table_name not in configured_tables:
                    # Check if this table has any mapped fields
                    if table_name in mapped_tables:
                        missing_configs.append(f'{model_name} ({table_name})')
            
            if errors:
                for error in errors:
                    messages.error(request, error)
                return redirect(request.path)
            
            if missing_configs:
                messages.warning(
                    request,
                    f'Missing UUID configuration for: {", ".join(missing_configs)}. '
                    f'Please configure all required models.'
                )
                return redirect(request.path)
            
            if saved_count > 0:
                messages.success(request, f'UUID configuration saved for {saved_count} model(s).')
            else:
                messages.info(request, 'No UUID configurations to save.')
            
            return redirect(f'data_import:{self.next_step_url_name}', import_id=import_data.id)
            
        except Exception as e:
            logger.error(f"Error saving UUID config: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return redirect(request.path)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context
