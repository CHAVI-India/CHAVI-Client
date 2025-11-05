"""Step 8: Import Execution View"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)

class Step8ImportView(WizardStepMixin, TemplateView):
    step_number = 6
    step_title = "Execute Import"
    step_status = ImportStatus.IMPORTING
    template_name = 'data_import/step8_import.html'
    previous_step_url_name = 'import_step5_uuid_mapping'
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.IMPORTING)
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            # Execute import using import_executor service
            from data_import.services.import_executor import ImportExecutorService
            
            executor = ImportExecutorService(import_data.id)
            results = executor.execute_import()
            
            messages.success(
                request,
                f'Import completed! {results["successful_rows"]} of {results["total_rows"]} rows imported successfully.'
            )
            
            if results['failed_rows'] > 0:
                messages.warning(
                    request,
                    f'{results["failed_rows"]} rows failed to import. Check import summary for details.'
                )
            
            return redirect(request.path)  # Reload to show results
            
        except Exception as e:
            logger.error(f"Import error: {e}", exc_info=True)
            messages.error(request, f'Import failed: {str(e)}')
            return redirect(request.path)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import_data = self.get_import_data(self.kwargs['import_id'])
        context['ready_to_import'] = True
        context['import_summary'] = import_data.import_summary
        return context
