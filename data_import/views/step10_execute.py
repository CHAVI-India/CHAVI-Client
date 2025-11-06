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
                logger.error(f"No JSON data found for import {import_data.id}")
                messages.error(request, 'No JSON data found. Please generate JSON in Step 9 first.')
                return redirect(request.path)
            
            logger.info(f"Starting import execution for import {import_data.id}")
            logger.info(f"JSON data structure: {list(json_obj.json_data.keys())}")
            
            if 'patients' in json_obj.json_data:
                logger.info(f"Found {len(json_obj.json_data['patients'])} patients in JSON")
            else:
                logger.error("No 'patients' key in JSON data")
                messages.error(request, 'Invalid JSON structure: missing "patients" key')
                return redirect(request.path)
            
            # Execute import using serializers
            from data_import.services.import_executor import ImportExecutorService
            
            executor = ImportExecutorService(import_data)
            results = executor.execute_import(json_obj.json_data)
            
            logger.info(f"Import results: {results}")
            
            # Update import status
            self.update_import_status(import_data, ImportStatus.COMPLETED)
            
            # Store results in import_data
            import_data.import_summary = results
            import_data.save()
            
            # Show results
            messages.success(
                request,
                f'Import completed! {results["successful_records"]} records imported successfully.'
            )
            
            if results.get('failed_records', 0) > 0:
                messages.warning(
                    request,
                    f'{results["failed_records"]} records failed. Errors: {results.get("errors", [])[:3]}'
                )
            
            return redirect(request.path)
            
        except Exception as e:
            logger.error(f"Import execution error: {e}", exc_info=True)
            self.update_import_status(import_data, ImportStatus.FAILED)
            messages.error(request, f'Import failed: {str(e)}. Check logs for details.')
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
