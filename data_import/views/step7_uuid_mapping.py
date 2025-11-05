"""Step 7: UUID Mapping View"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus
from data_import.services.file_processor import FileProcessorService
from data_import.services.uuid_manager import UUIDManagerService
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)

class Step7UUIDMappingView(WizardStepMixin, TemplateView):
    step_number = 5
    step_title = "UUID Mapping"
    step_status = ImportStatus.UUID_MAPPING
    template_name = 'data_import/step7_uuid_mapping.html'
    next_step_url_name = 'import_step6_import'
    previous_step_url_name = 'import_step4_lookup_matching'
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.UUID_MAPPING)
        
        try:
            # Build field mappings grouped by table
            from data_import.services.field_introspection import FieldIntrospectionService
            from collections import defaultdict
            
            field_service = FieldIntrospectionService()
            tables_needing_uuids = defaultdict(lambda: {'fields': [], 'mapped_fields': []})
            
            # Get all mapped fields (only those that were actually mapped, not excluded)
            for mapping in import_data.data_fields.all():
                # Skip if this field doesn't have a CHAVI field mapped (was excluded)
                if not mapping.client_app_field_name or not mapping.client_app_table_name:
                    continue
                    
                table_name = mapping.client_app_table_name
                
                # Add to table's field list
                tables_needing_uuids[table_name]['mapped_fields'].append({
                    'file_field': mapping.file_field_name,
                    'chavi_field': mapping.client_app_field_name,
                    'field_type': mapping.client_app_field_type,
                })
            
            # For each table, get all available fields that could be used for uniqueness
            for table_name in tables_needing_uuids.keys():
                # Get all fields for this table from the mapped fields
                available_fields = []
                for mapping in import_data.data_fields.filter(client_app_table_name=table_name):
                    # Skip excluded fields
                    if not mapping.client_app_field_name or not mapping.client_app_table_name:
                        continue
                    
                    # Only include standard fields (not FK/M2M) for uniqueness
                    if mapping.client_app_field_type == 'Standard':
                        available_fields.append({
                            'file_field': mapping.file_field_name,
                            'chavi_field': mapping.client_app_field_name,
                        })
                
                tables_needing_uuids[table_name]['fields'] = available_fields
                
                # Get default uniqueness fields from session or use all fields
                session_key = f'uuid_config_{import_data.id}_{table_name}'
                default_fields = request.session.get(session_key, [f['file_field'] for f in available_fields])
                tables_needing_uuids[table_name]['uniqueness_fields'] = default_fields
            
            # Store in context
            context = self.get_context_data(**kwargs)
            context['tables_needing_uuids'] = dict(tables_needing_uuids)
            context['total_tables'] = len(tables_needing_uuids)
            
            return self.render_to_response(context)
            
        except Exception as e:
            logger.error(f"UUID mapping error: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            # Save UUID configuration for each table
            uuid_config = {}
            
            for key, value in request.POST.items():
                if key.startswith('uuid_fields_'):
                    table_name = key.replace('uuid_fields_', '')
                    # Get selected fields (checkboxes return multiple values)
                    selected_fields = request.POST.getlist(key)
                    
                    if not selected_fields:
                        messages.error(request, f'Please select at least one field for {table_name} to determine uniqueness.')
                        return redirect(request.path)
                    
                    uuid_config[table_name] = selected_fields
                    
                    # Store in session for later use during import
                    session_key = f'uuid_config_{import_data.id}_{table_name}'
                    request.session[session_key] = selected_fields
            
            # Store overall config
            request.session[f'uuid_config_{import_data.id}'] = uuid_config
            request.session.modified = True
            
            messages.success(request, f'UUID configuration saved for {len(uuid_config)} tables.')
            return redirect(f'data_import:{self.next_step_url_name}', import_id=import_data.id)
            
        except Exception as e:
            logger.error(f"Error saving UUID config: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return redirect(request.path)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import_data = self.get_import_data(self.kwargs['import_id'])
        context['uuid_results'] = self.request.session.get(f'uuid_results_{import_data.id}', {})
        return context
