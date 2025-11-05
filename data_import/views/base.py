"""
Base view class for the import wizard.
"""
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404
from data_import.models import ImportData, ImportStatus
from typing import Dict, Any


class WizardStepMixin(LoginRequiredMixin):
    """
    Mixin for wizard step views.
    Provides common functionality for all wizard steps.
    """
    
    # Step configuration
    step_number = None
    step_title = None
    step_status = None
    template_name = None
    
    # Navigation (without namespace - will be added in templates)
    next_step_url_name = None
    previous_step_url_name = None
    
    def get_next_step_url(self):
        """Get namespaced next step URL name."""
        return f'data_import:{self.next_step_url_name}' if self.next_step_url_name else None
    
    def get_previous_step_url(self):
        """Get namespaced previous step URL name."""
        return f'data_import:{self.previous_step_url_name}' if self.previous_step_url_name else None
    
    def get_import_data(self, import_id: int) -> ImportData:
        """
        Get the ImportData instance for this wizard session.
        
        Args:
            import_id: ID of the ImportData instance
            
        Returns:
            ImportData instance
        """
        return get_object_or_404(ImportData, id=import_id)
    
    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """Add wizard context to template."""
        context = super().get_context_data(**kwargs)
        
        # Get import data if import_id is in kwargs
        import_id = self.kwargs.get('import_id')
        if import_id:
            import_data = self.get_import_data(import_id)
            context['import_data'] = import_data
            context['progress_percentage'] = import_data.get_progress_percentage()
        
        # Add wizard navigation context
        context.update({
            'step_number': self.step_number,
            'step_title': self.step_title,
            'total_steps': 9,
            'next_step_url_name': f'data_import:{self.next_step_url_name}' if self.next_step_url_name else None,
            'previous_step_url_name': f'data_import:{self.previous_step_url_name}' if self.previous_step_url_name else None,
            'wizard_steps': self.get_wizard_steps(),
        })
        
        return context
    
    def get_wizard_steps(self) -> list:
        """
        Get list of all wizard steps with their status.
        
        Returns:
            List of step dictionaries
        """
        steps = [
            {'number': 1, 'title': 'Upload File', 'status': ImportStatus.UPLOADED},
            {'number': 2, 'title': 'Map Fields', 'status': ImportStatus.FIELD_MAPPING},
            {'number': 3, 'title': 'Date Formats', 'status': ImportStatus.DATE_FORMAT_CONFIG},
            {'number': 4, 'title': 'Date Intervals', 'status': ImportStatus.DATE_INTERVAL_CONFIG},
            {'number': 5, 'title': 'Validate Data', 'status': ImportStatus.VALIDATING},
            {'number': 6, 'title': 'Lookup Matching', 'status': ImportStatus.LOOKUP_MATCHING},
            {'number': 7, 'title': 'Static Mapping', 'status': ImportStatus.FIELD_MAPPING},
            {'number': 8, 'title': 'UUID Mapping', 'status': ImportStatus.UUID_MAPPING},
            {'number': 9, 'title': 'Import', 'status': ImportStatus.IMPORTING},
        ]
        
        # Mark current step
        if self.step_number:
            for step in steps:
                if step['number'] == self.step_number:
                    step['is_current'] = True
                elif step['number'] < self.step_number:
                    step['is_completed'] = True
        
        return steps
    
    def update_import_status(self, import_data: ImportData, status: ImportStatus):
        """
        Update the status of the import.
        
        Args:
            import_data: ImportData instance
            status: New status
        """
        import_data.status = status
        import_data.save(update_fields=['status', 'updated_at'])
    
    def validate_step_access(self, import_data: ImportData) -> bool:
        """
        Validate that the user can access this step.
        Override in subclasses to add step-specific validation.
        
        Args:
            import_data: ImportData instance
            
        Returns:
            True if access is allowed, False otherwise
        """
        return True
    
    def dispatch(self, request, *args, **kwargs):
        """
        Validate step access before processing request.
        """
        import_id = kwargs.get('import_id')
        if import_id:
            import_data = self.get_import_data(import_id)
            if not self.validate_step_access(import_data):
                # Redirect to appropriate step based on current status
                return redirect('import_step1_upload')
        
        return super().dispatch(request, *args, **kwargs)
