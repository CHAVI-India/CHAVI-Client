"""
Step 3: Manual Field Matching View
"""
from django.views.generic import FormView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, DataFieldConfiguration
from data_import.services.field_introspection import FieldIntrospectionService
from data_import.forms import FieldMappingForm
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)


class Step3ManualMatchView(WizardStepMixin, FormView):
    """
    Step 3: Manually match remaining fields that couldn't be auto-matched.
    """
    
    step_number = 3
    step_title = "Manual Field Matching"
    step_status = ImportStatus.FIELD_MAPPING
    template_name = 'data_import/step3_manual_match.html'
    next_step_url_name = 'import_step4_mapping_review'
    previous_step_url_name = 'import_step2_auto_match'
    form_class = FieldMappingForm
    
    def get_form_kwargs(self):
        """Add custom kwargs for form initialization."""
        kwargs = super().get_form_kwargs()
        
        import_id = self.kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        # Get fields that still need mapping
        match_results = self.request.session.get(f'match_results_{import_id}', {})
        manual_needed = match_results.get('manual_needed', [])
        
        # Get all CHAVI fields
        field_service = FieldIntrospectionService()
        chavi_fields = field_service.get_all_fields()
        
        kwargs['source_fields'] = manual_needed
        kwargs['chavi_fields'] = chavi_fields
        
        return kwargs
    
    def form_valid(self, form):
        """
        Save manual field mappings.
        """
        import_id = self.kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        try:
            # Get field service for metadata
            field_service = FieldIntrospectionService()
            
            # Process each mapping
            mappings_created = 0
            
            for field_name, field_value in form.cleaned_data.items():
                if field_name.startswith('mapping_') and field_value:
                    # Extract source field name
                    source_field = field_name.replace('mapping_', '')
                    
                    # Parse CHAVI field (format: "ModelName.field_name")
                    table_name, chavi_field_name = field_value.split('.')
                    
                    # Get field metadata
                    field_metadata = field_service.get_field(table_name, chavi_field_name)
                    
                    if field_metadata:
                        # Create or update mapping
                        DataFieldConfiguration.objects.update_or_create(
                            import_data=import_data,
                            file_field_name=source_field,
                            defaults={
                                'field_data_type': field_metadata['data_type'],
                                'client_app_table_name': field_metadata['table_name'],
                                'client_app_field_name': field_metadata['field_name'],
                                'client_app_field_type': (
                                    'Foreign Key' if field_metadata['is_foreign_key']
                                    else 'Many to Many' if field_metadata['is_many_to_many']
                                    else 'Standard'
                                ),
                                'client_app_lookup_table_name': (
                                    field_metadata.get('related_table') 
                                    if field_metadata.get('is_lookup') else None
                                ),
                                'client_app_lookup_field_name': (
                                    field_metadata.get('lookup_model')
                                    if field_metadata.get('is_lookup') else None
                                ),
                            }
                        )
                        mappings_created += 1
            
            if mappings_created > 0:
                messages.success(
                    self.request,
                    f'Successfully mapped {mappings_created} fields.'
                )
            else:
                messages.info(
                    self.request,
                    'No additional fields were mapped. Proceeding to review.'
                )
            
            # Redirect to next step
            return redirect(f'data_import:{self.next_step_url_name}', import_id=import_id)
            
        except Exception as e:
            logger.error(f"Error saving manual mappings: {e}", exc_info=True)
            messages.error(self.request, f'Error saving mappings: {str(e)}')
            return self.form_invalid(form)
    
    def get_context_data(self, **kwargs):
        """Add context for manual matching."""
        context = super().get_context_data(**kwargs)
        
        import_id = self.kwargs.get('import_id')
        match_results = self.request.session.get(f'match_results_{import_id}', {})
        
        context['manual_needed'] = match_results.get('manual_needed', [])
        context['total_unmapped'] = len(match_results.get('manual_needed', []))
        
        return context
    
    def validate_step_access(self, import_data):
        """Validate that auto-matching has been completed."""
        return import_data.status == ImportStatus.FIELD_MAPPING
