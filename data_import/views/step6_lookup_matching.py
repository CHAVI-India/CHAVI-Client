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
        
        # Save lookup mappings
        for key, value in request.POST.items():
            if key.startswith('lookup_') and value:
                # Parse and save mapping
                pass  # Implementation details
        
        return redirect(f'data_import:{self.next_step_url_name}', import_id=import_data.id)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import_data = self.get_import_data(self.kwargs['import_id'])
        context['lookup_results'] = self.request.session.get(f'lookup_results_{import_data.id}', {})
        return context
