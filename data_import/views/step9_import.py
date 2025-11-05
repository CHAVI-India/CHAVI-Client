"""Step 9: JSON Preview View"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse
from data_import.models import ImportData, ImportStatus, ImportDataJSON
from data_import.services.json_generator import JSONGeneratorService
from .base import WizardStepMixin
import json
import logging

logger = logging.getLogger(__name__)

class Step9ImportView(WizardStepMixin, TemplateView):
    """
    Step 9: Generate and preview the import JSON.
    This step shows the user what will be imported before executing.
    """
    
    step_number = 9
    step_title = "JSON Preview"
    step_status = ImportStatus.JSON_PREVIEW
    template_name = 'data_import/step9_json_preview.html'
    next_step_url_name = 'import_step10_execute'
    previous_step_url_name = 'import_step8_uuid_mapping'
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.JSON_PREVIEW)
        
        try:
            # Check if JSON already exists
            existing_json = ImportDataJSON.objects.filter(import_data=import_data).first()
            
            if not existing_json:
                # Generate JSON
                logger.info(f"Generating JSON for import {import_data.id}")
                generator = JSONGeneratorService(import_data)
                json_data = generator.generate_json()
                messages.success(request, f'Import JSON generated successfully! Generated {len(json_data.get("patients", []))} patient records.')
            else:
                logger.info(f"Using existing JSON for import {import_data.id}")
                patient_count = len(existing_json.json_data.get('patients', []))
                messages.info(request, f'Displaying previously generated JSON with {patient_count} patient records.')
            
        except Exception as e:
            logger.error(f"JSON generation error: {e}", exc_info=True)
            messages.error(request, f'Error generating JSON: {str(e)}. Check the logs for details.')
            import traceback
            logger.error(traceback.format_exc())
        
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        """Regenerate JSON if requested"""
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            logger.info(f"Regenerating JSON for import {import_data.id}")
            generator = JSONGeneratorService(import_data)
            json_data = generator.generate_json()
            
            messages.success(request, 'Import JSON regenerated successfully!')
            return redirect(request.path)
            
        except Exception as e:
            logger.error(f"JSON regeneration error: {e}", exc_info=True)
            messages.error(request, f'Error regenerating JSON: {str(e)}')
            return redirect(request.path)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import_data = self.get_import_data(self.kwargs['import_id'])
        
        # Get the generated JSON
        json_obj = ImportDataJSON.objects.filter(import_data=import_data).first()
        
        logger.info(f"Getting context for import {import_data.id}, json_obj exists: {json_obj is not None}")
        
        if json_obj:
            context['json_data'] = json.dumps(json_obj.json_data, indent=2)
            context['json_preview'] = json_obj.json_data
            context['has_json'] = True
            
            logger.info(f"JSON data length: {len(context['json_data'])}")
            
            # Calculate statistics
            if 'patients' in json_obj.json_data:
                context['total_patients'] = len(json_obj.json_data['patients'])
                
                # Count records by table
                table_counts = {}
                for patient in json_obj.json_data['patients']:
                    for key, value in patient.items():
                        if isinstance(value, list) and key != 'patient_id':
                            table_counts[key] = table_counts.get(key, 0) + len(value)
                
                context['table_counts'] = table_counts
                context['total_records'] = sum(table_counts.values()) if table_counts else 0
                
                logger.info(f"Statistics: {context['total_patients']} patients, {context['total_records']} records")
        else:
            context['has_json'] = False
            logger.warning(f"No JSON object found for import {import_data.id}")
        
        logger.info(f"Context has_json: {context.get('has_json')}")
        return context
