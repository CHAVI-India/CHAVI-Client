"""Step 8.5: UUID Matching View"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, UUIDMatchConfiguration, UUIDMatchAction
from data_import.services.json_generator import JSONGeneratorService
from data_import.services.uuid_matcher import UUIDMatcherService
from .base import WizardStepMixin
import logging
import json

logger = logging.getLogger(__name__)

class Step8_5UUIDMatchingView(WizardStepMixin, TemplateView):
    """
    Step 8.5: UUID Matching and Deduplication
    
    After UUID generation in Step 8, this step compares generated records with
    existing records in the database and lets users decide whether to reuse
    existing UUIDs or create new records.
    """
    
    step_number = 8.5
    step_title = "UUID Matching & Deduplication"
    step_status = ImportStatus.UUID_MAPPING  # Reuse UUID_MAPPING status
    template_name = 'data_import/step8_5_uuid_matching.html'
    next_step_url_name = 'import_step9_json_preview'
    previous_step_url_name = 'import_step8_uuid_mapping'
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            # Generate JSON with UUIDs (from Step 8 configuration)
            json_generator = JSONGeneratorService(import_data)
            json_data = json_generator.generate_json()
            
            # Match generated records with existing records
            uuid_matcher = UUIDMatcherService()
            match_results = uuid_matcher.match_records_for_import(json_data)
            
            # Save match results to database for persistence
            self._save_match_results(import_data, match_results)
            
            # Organize data for UI display
            context = self.get_context_data(**kwargs)
            context['match_results'] = match_results
            context['total_patients'] = len(match_results)
            context['patients_with_existing_records'] = sum(
                1 for r in match_results.values() if r['patient_exists']
            )
            
            return self.render_to_response(context)
            
        except Exception as e:
            logger.error(f"UUID matching error: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            # Clear existing UUID match configurations
            UUIDMatchConfiguration.objects.filter(import_data=import_data).delete()
            
            saved_count = 0
            
            # Process form data
            # Format: action_{table_name}_{generated_uuid} = 'use_existing' or 'use_new'
            # Format: existing_uuid_{table_name}_{generated_uuid} = 'existing-uuid-value'
            
            actions = {}
            existing_uuids = {}
            
            # First pass: collect all actions and existing UUIDs
            for key, value in request.POST.items():
                if key.startswith('action_'):
                    # Extract table_name and generated_uuid
                    parts = key.replace('action_', '').split('_', 1)
                    if len(parts) == 2:
                        table_name, generated_uuid = parts
                        actions[f"{table_name}_{generated_uuid}"] = value
                
                elif key.startswith('existing_uuid_'):
                    parts = key.replace('existing_uuid_', '').split('_', 1)
                    if len(parts) == 2:
                        table_name, generated_uuid = parts
                        existing_uuids[f"{table_name}_{generated_uuid}"] = value
            
            # Second pass: save configurations
            for composite_key, action in actions.items():
                table_name, generated_uuid = composite_key.split('_', 1)
                existing_uuid = existing_uuids.get(composite_key)
                
                # Get patient_id from hidden field
                patient_id_key = f"patient_id_{composite_key}"
                patient_id = request.POST.get(patient_id_key, '')
                
                # Get import and existing data from hidden fields
                import_data_key = f"import_data_{composite_key}"
                existing_data_key = f"existing_data_{composite_key}"
                
                import_record_data = request.POST.get(import_data_key, '{}')
                existing_record_data = request.POST.get(existing_data_key, '{}')
                
                try:
                    import_record_data = json.loads(import_record_data)
                    existing_record_data = json.loads(existing_record_data) if existing_record_data != '{}' else None
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse JSON for {composite_key}")
                    continue
                
                # Save configuration
                UUIDMatchConfiguration.objects.create(
                    import_data=import_data,
                    table_name=table_name,
                    patient_id=patient_id,
                    generated_uuid=generated_uuid,
                    existing_uuid=existing_uuid if action == UUIDMatchAction.USE_EXISTING else None,
                    match_action=action,
                    import_record_data=import_record_data,
                    existing_record_data=existing_record_data
                )
                saved_count += 1
                logger.info(f"Saved UUID match: {table_name} {generated_uuid} -> {action}")
            
            if saved_count > 0:
                messages.success(request, f'Saved UUID matching decisions for {saved_count} record(s).')
            else:
                messages.info(request, 'No UUID matching decisions to save.')
            
            return redirect(f'data_import:{self.next_step_url_name}', import_id=import_data.id)
            
        except Exception as e:
            logger.error(f"Error saving UUID matches: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return redirect(request.path)
    
    def _save_match_results(self, import_data, match_results):
        """
        Save match results to database for initial state.
        This provides default selections that users can modify.
        """
        # Clear existing configurations
        UUIDMatchConfiguration.objects.filter(import_data=import_data).delete()
        
        for patient_id, patient_result in match_results.items():
            for table_name, matches in patient_result.get('matches', {}).items():
                for match in matches:
                    self._save_match_recursive(
                        import_data,
                        patient_id,
                        table_name,
                        match
                    )
    
    def _save_match_recursive(self, import_data, patient_id, table_name, match):
        """Recursively save match configurations including nested records"""
        generated_uuid = match.get('generated_uuid')
        import_record_data = match.get('import_data', {})
        existing_records = match.get('existing_records', [])
        
        # Default to creating new records (user decides which to reuse)
        default_action = UUIDMatchAction.USE_NEW
        existing_uuid = None
        existing_record_data = None
        
        # If there are existing records, store the first one for reference
        if existing_records:
            existing_uuid = existing_records[0]['uuid']
            existing_record_data = existing_records[0].get('data')
        
        # Save configuration
        UUIDMatchConfiguration.objects.create(
            import_data=import_data,
            table_name=table_name,
            patient_id=patient_id,
            generated_uuid=generated_uuid,
            existing_uuid=existing_uuid,
            match_action=default_action,
            import_record_data=import_record_data,
            existing_record_data=existing_record_data
        )
        
        # Process nested matches
        for nested_table, nested_matches in match.get('nested_matches', {}).items():
            for nested_match in nested_matches:
                self._save_match_recursive(
                    import_data,
                    patient_id,
                    nested_table,
                    nested_match
                )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context
