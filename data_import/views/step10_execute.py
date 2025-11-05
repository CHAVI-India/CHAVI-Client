"""Step 10: Import Execution View"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from django.db import transaction
from data_import.models import ImportData, ImportStatus, ImportDataJSON
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)


class Step10ExecuteView(WizardStepMixin, TemplateView):
    """
    Step 10: Execute the actual import using DRF serializers.
    This step imports the JSON data into the database.
    """
    
    step_number = 10
    step_title = "Execute Import"
    step_status = ImportStatus.IMPORTING
    template_name = 'data_import/step10_execute.html'
    previous_step_url_name = 'import_step9_json_preview'
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.IMPORTING)
        
        # Check if JSON exists
        json_obj = ImportDataJSON.objects.filter(import_data=import_data).first()
        if not json_obj:
            messages.error(request, 'No JSON data found. Please go back and generate the JSON first.')
            return redirect('data_import:import_step9_json_preview', import_id=import_data.id)
        
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        """Execute the import"""
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            # Get the JSON data
            json_obj = ImportDataJSON.objects.filter(import_data=import_data).first()
            if not json_obj:
                messages.error(request, 'No JSON data found.')
                return redirect(request.path)
            
            # Execute import using serializers
            from data_import.services.import_executor import ImportExecutorService
            
            logger.info(f"Starting import execution for import {import_data.id}")
            executor = ImportExecutorService(import_data)
            results = executor.execute_import(json_obj.json_data)
            
            # Update import status
            self.update_import_status(import_data, ImportStatus.COMPLETED)
            
            # Show results
            messages.success(
                request,
                f'Import completed successfully! {results["successful_records"]} records imported.'
            )
            
            if results.get('failed_records', 0) > 0:
                messages.warning(
                    request,
                    f'{results["failed_records"]} records failed to import. Check the error log for details.'
                )
            
            return redirect(request.path)
            
        except Exception as e:
            logger.error(f"Import execution error: {e}", exc_info=True)
            self.update_import_status(import_data, ImportStatus.FAILED)
            messages.error(request, f'Import failed: {str(e)}')
            return redirect(request.path)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import_data = self.get_import_data(self.kwargs['import_id'])
        
        # Check if already imported
        context['is_completed'] = import_data.status == ImportStatus.COMPLETED
        context['is_failed'] = import_data.status == ImportStatus.FAILED
        context['ready_to_import'] = import_data.status == ImportStatus.IMPORTING
        
        # Get JSON stats
        json_obj = ImportDataJSON.objects.filter(import_data=import_data).first()
        if json_obj and 'patients' in json_obj.json_data:
            context['total_patients'] = len(json_obj.json_data['patients'])
        
        return context
