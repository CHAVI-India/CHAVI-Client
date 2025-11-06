"""Step 6: Lookup Matching View"""
from django.views.generic import FormView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, FieldLookupConfiguration
from data_import.services.file_processor import FileProcessorService
from data_import.services.field_introspection import FieldIntrospectionService
from data_import.services.lookup_matcher import LookupMatcherService
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)

class Step6LookupMatchingView(WizardStepMixin, FormView):
    step_number = 6
    step_title = "Lookup Matching"
    step_status = ImportStatus.LOOKUP_MATCHING
    template_name = 'data_import/step6_lookup_matching.html'
    next_step_url_name = 'import_step7_static_mapping'
    previous_step_url_name = 'import_step5_validation'
    
    def get_form_class(self):
        from data_import.forms import LookupMappingForm
        return LookupMappingForm
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.LOOKUP_MATCHING)
        
        # Process lookup matching
        try:
            processor = FileProcessorService(import_data.file.path, import_data.data_type)
            headers, data_rows = processor.parse()
            
            field_service = FieldIntrospectionService()
            lookup_matcher = LookupMatcherService(field_service)
            
            # Build field mappings
            print(f"[DEBUG LOOKUP] Import ID: {import_data.id}")
            print(f"[DEBUG LOOKUP] Import status: {import_data.status}")
            
            all_mappings = import_data.data_fields.all()
            print(f"[DEBUG LOOKUP] Found {all_mappings.count()} DataFieldConfiguration records")
            
            field_mappings = {}
            for mapping in all_mappings:
                print(f"[DEBUG LOOKUP] Processing mapping: {mapping.file_field_name} -> {mapping.client_app_table_name}.{mapping.client_app_field_name}")
                
                # Skip excluded fields
                if not mapping.client_app_field_name or not mapping.client_app_table_name:
                    print(f"  - SKIPPED (excluded field)")
                    continue
                    
                field_meta = field_service.get_field(
                    mapping.client_app_table_name, mapping.client_app_field_name
                )
                if field_meta:
                    field_mappings[mapping.file_field_name] = field_meta
                    print(f"  - Added to field_mappings, is_lookup: {field_meta.get('is_lookup', False)}")
                else:
                    print(f"  - WARNING: Could not find field metadata for {mapping.client_app_table_name}.{mapping.client_app_field_name}")
            
            print(f"[DEBUG LOOKUP] Total field mappings: {len(field_mappings)}")
            print(f"[DEBUG LOOKUP] Lookup fields: {[k for k, v in field_mappings.items() if v.get('is_lookup')]}")
            
            lookup_results = lookup_matcher.process_all_lookup_fields(data_rows, field_mappings)
            print(f"[DEBUG LOOKUP] Lookup results: {len(lookup_results)} fields")
            
            request.session[f'lookup_results_{import_data.id}'] = lookup_results
            
            messages.info(request, f'Found {len(lookup_results)} lookup fields to match.')
        except Exception as e:
            logger.error(f"Lookup matching error: {e}")
            messages.error(request, f'Error: {str(e)}')
        
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        logger.info(f"Step 6 POST - Import ID: {import_data.id}")
        logger.info(f"POST data keys: {list(request.POST.keys())[:20]}")
        
        # Clear existing lookup mappings
        deleted = FieldLookupConfiguration.objects.filter(
            data_field_configuration__import_data=import_data
        ).delete()
        logger.info(f"Deleted {deleted[0]} existing lookup configurations")
        
        saved_count = 0
        
        # Get lookup results from session to map field names
        lookup_results = request.session.get(f'lookup_results_{import_data.id}', {})
        logger.info(f"Lookup results from session: {list(lookup_results.keys())}")
        
        # Save lookup mappings
        # Format: lookup_{source_field}_{source_value} = lookup_pk
        lookup_fields_found = [k for k in request.POST.keys() if k.startswith('lookup_')]
        logger.info(f"Found {len(lookup_fields_found)} lookup fields in POST")
        if lookup_fields_found:
            logger.info(f"Sample lookup fields: {lookup_fields_found[:3]}")
        
        for key, value in request.POST.items():
            if key.startswith('lookup_') and value:
                logger.debug(f"Processing: {key} = {value}")
                try:
                    # Remove 'lookup_' prefix
                    key_without_prefix = key[7:]  # Remove 'lookup_'
                    
                    # Find which source_field this belongs to by checking lookup_results
                    source_field = None
                    source_value = None
                    
                    for field_name, result_data in lookup_results.items():
                        # Check if key starts with this field name
                        if key_without_prefix.startswith(field_name + '_'):
                            source_field = field_name
                            # Everything after field_name_ is the source_value
                            source_value = key_without_prefix[len(field_name) + 1:]
                            break
                    
                    if source_field and source_value:
                        lookup_pk = value
                        
                        # Find the data field configuration
                        field_config = import_data.data_fields.filter(
                            file_field_name=source_field
                        ).first()
                        
                        if field_config:
                            FieldLookupConfiguration.objects.create(
                                data_field_configuration=field_config,
                                field_value=source_value,
                                lookup_value=lookup_pk
                            )
                            saved_count += 1
                            logger.info(f"Saved lookup mapping: {source_field} '{source_value}' -> '{lookup_pk}'")
                        else:
                            logger.warning(f"No field config found for: {source_field}")
                    else:
                        logger.warning(f"Could not parse field name from: {key}")
                except Exception as e:
                    logger.error(f"Error saving lookup mapping for {key}: {e}", exc_info=True)
        
        messages.success(request, f'Saved {saved_count} lookup mappings.')
        return redirect(f'data_import:{self.next_step_url_name}', import_id=import_data.id)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import_data = self.get_import_data(self.kwargs['import_id'])
        context['lookup_results'] = self.request.session.get(f'lookup_results_{import_data.id}', {})
        return context
