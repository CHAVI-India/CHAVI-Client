"""
Step 4: Mapping Review View
"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse
from data_import.models import ImportData, ImportStatus, DataFieldConfiguration
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)


class Step4MappingReviewView(WizardStepMixin, TemplateView):
    """
    Step 4: Review and finalize all field mappings.
    """
    
    step_number = 4
    step_title = "Review Field Mappings"
    step_status = ImportStatus.FIELD_MAPPING
    template_name = 'data_import/step4_mapping_review.html'
    next_step_url_name = 'import_step5_validation'
    previous_step_url_name = 'import_step3_manual_match'
    
    def get(self, request, *args, **kwargs):
        """Display all field mappings for review."""
        import_id = kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        # Get all field mappings
        mappings = DataFieldConfiguration.objects.filter(
            import_data=import_data
        ).order_by('client_app_table_name', 'file_field_name')
        
        # Check if we have any mappings
        if not mappings.exists():
            messages.warning(
                request,
                'No field mappings found. Please go back and map at least one field.'
            )
        
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        """
        Handle mapping finalization or deletion.
        """
        import_id = kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        action = request.POST.get('action')
        
        if action == 'delete_mapping':
            # Delete a specific mapping
            mapping_id = request.POST.get('mapping_id')
            try:
                mapping = DataFieldConfiguration.objects.get(
                    id=mapping_id,
                    import_data=import_data
                )
                field_name = mapping.file_field_name
                mapping.delete()
                
                messages.success(
                    request,
                    f'Removed mapping for field "{field_name}".'
                )
            except DataFieldConfiguration.DoesNotExist:
                messages.error(request, 'Mapping not found.')
            except Exception as e:
                logger.error(f"Error deleting mapping: {e}", exc_info=True)
                messages.error(request, f'Error deleting mapping: {str(e)}')
            
            return redirect(request.path)
        
        elif action == 'finalize':
            # Finalize mappings and proceed to validation
            mappings_count = DataFieldConfiguration.objects.filter(
                import_data=import_data
            ).count()
            
            if mappings_count == 0:
                messages.error(
                    request,
                    'Cannot proceed without any field mappings. Please map at least one field.'
                )
                return redirect(request.path)
            
            messages.success(
                request,
                f'Field mappings finalized. {mappings_count} fields will be imported.'
            )
            
            # Proceed to validation step
            return redirect(f'data_import:{self.next_step_url_name}', import_id=import_id)
        
        return redirect(request.path)
    
    def get_context_data(self, **kwargs):
        """Add mappings to context."""
        context = super().get_context_data(**kwargs)
        
        import_id = self.kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        # Get all mappings grouped by table
        mappings = DataFieldConfiguration.objects.filter(
            import_data=import_data
        ).order_by('client_app_table_name', 'file_field_name')
        
        # Group by table
        mappings_by_table = {}
        for mapping in mappings:
            table = mapping.client_app_table_name
            if table not in mappings_by_table:
                mappings_by_table[table] = []
            mappings_by_table[table].append(mapping)
        
        context.update({
            'mappings': mappings,
            'mappings_by_table': mappings_by_table,
            'total_mappings': mappings.count(),
        })
        
        return context
    
    def validate_step_access(self, import_data):
        """Validate that field mapping has been started."""
        return import_data.status == ImportStatus.FIELD_MAPPING
