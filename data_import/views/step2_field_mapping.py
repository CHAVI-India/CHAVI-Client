"""
Step 2: Combined Field Mapping View (replaces steps 2, 3, 4)
"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, DataFieldConfiguration
from data_import.services.field_introspection import FieldIntrospectionService
from data_import.services.fuzzy_matcher import FuzzyMatcherService
from data_import.services.file_processor import FileProcessorService
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)


class Step2FieldMappingView(WizardStepMixin, TemplateView):
    """
    Step 2: Single-page field mapping with auto-suggestions.
    Shows all fields from the file with dropdown to select CHAVI field or exclude.
    """
    
    step_number = 2
    step_title = "Map Fields"
    step_status = ImportStatus.FIELD_MAPPING
    template_name = 'data_import/step2_field_mapping.html'
    next_step_url_name = 'import_step3_date_format_config'
    previous_step_url_name = None
    
    def get(self, request, *args, **kwargs):
        """Display all fields with auto-match suggestions."""
        import_id = kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        # Update status
        self.update_import_status(import_data, ImportStatus.FIELD_MAPPING)
        
        try:
            # Get headers from file
            processor = FileProcessorService(import_data.file.path, import_data.data_type)
            headers, data_rows = processor.parse()
            
            # Get sample data (first 5 rows)
            sample_data = data_rows[:5] if len(data_rows) > 5 else data_rows
            
            # Initialize services
            field_service = FieldIntrospectionService()
            matcher = FuzzyMatcherService(field_service)
            
            # Get all CHAVI fields for dropdown (use_cache=False to ensure exclusions are applied)
            all_chavi_fields = field_service.get_all_fields(use_cache=False)
            print(f"[DEBUG] Retrieved {len(all_chavi_fields)} CHAVI fields")
            
            # Debug: Log unique models
            unique_models = set(field['model_name'] for field in all_chavi_fields)
            print(f"[DEBUG] Unique models from get_all_fields: {sorted(unique_models)}")
            
            # Group fields by model for optgroups
            # Explicitly exclude certain models
            from data_import.services.field_introspection import FieldIntrospectionService as FIS
            excluded_models = FIS.EXCLUDED_MODELS
            print(f"[DEBUG] Excluded models list: {excluded_models}")
            
            fields_by_model = {}
            for field in all_chavi_fields:
                model = field['model_name']
                
                # Skip excluded models
                if model in excluded_models:
                    print(f"[DEBUG] Skipping excluded model: {model}")
                    continue
                
                if model not in fields_by_model:
                    fields_by_model[model] = []
                fields_by_model[model].append(field)
            
            print(f"[DEBUG] Grouped into {len(fields_by_model)} models: {list(fields_by_model.keys())}")
            
            # Check if mappings already exist
            existing_mappings = {}
            for mapping in import_data.data_fields.all():
                if mapping.client_app_field_name and mapping.client_app_table_name:
                    # Get the field metadata
                    field_meta = field_service.get_field(mapping.client_app_table_name, mapping.client_app_field_name)
                    if field_meta:
                        existing_mappings[mapping.file_field_name] = field_meta
            
            # Only run fuzzy matching if no existing mappings
            if not existing_mappings:
                match_results = matcher.match_source_fields(headers)
            else:
                match_results = {}
            
            # Build field mapping data
            field_mappings = []
            for header in headers:
                # Check if there's an existing mapping
                if header in existing_mappings:
                    best_match = existing_mappings[header]
                    confidence = 100  # Existing mapping
                else:
                    # Use fuzzy match results
                    match_result = match_results.get(header, {})
                    best_match = None
                    confidence = 0
                    
                    if match_result.get('match_type') == 'auto':
                        best_match = match_result.get('auto_match')
                        confidence = best_match.get('score', 0) if best_match else 0
                    elif match_result.get('match_type') == 'suggestions':
                        suggestions = match_result.get('suggestions', [])
                        if suggestions:
                            best_match = suggestions[0]
                            confidence = best_match.get('score', 0)
                
                # Get sample values
                sample_values = [row.get(header, '') for row in sample_data if row.get(header)]
                
                field_mappings.append({
                    'source_field': header,
                    'best_match': best_match,
                    'confidence': confidence,
                    'sample_values': sample_values[:3],  # Show first 3 samples
                })
            
            # Store in context (keep full metadata for template)
            request.session[f'field_mappings_{import_id}'] = {
                'headers': headers,
            }
            
            return self.render_to_response(self.get_context_data(
                field_mappings=field_mappings,
                fields_by_model=fields_by_model,  # This already has full metadata
                total_fields=len(headers)
            ))
            
        except Exception as e:
            logger.error(f"Error in field mapping: {e}", exc_info=True)
            messages.error(request, f'Error processing fields: {str(e)}')
            return redirect('data_import:import_step1_upload')
    
    def post(self, request, *args, **kwargs):
        """Save field mappings and proceed to validation."""
        import_id = kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        try:
            # Clear existing mappings
            DataFieldConfiguration.objects.filter(import_data=import_data).delete()
            
            # Clear validation errors (force re-validation with new mappings)
            import_data.validation_errors = None
            import_data.save(update_fields=['validation_errors'])
            
            # Get field service for metadata
            field_service = FieldIntrospectionService()
            
            # Process each field mapping
            mappings_created = 0
            
            for key, value in request.POST.items():
                if key.startswith('field_mapping_') and value and value != 'exclude':
                    # Extract source field name
                    source_field = key.replace('field_mapping_', '')
                    
                    # Parse CHAVI field (format: "table_name.field_name")
                    try:
                        table_name, chavi_field_name = value.split('.')
                        
                        # Get field metadata
                        field_metadata = field_service.get_field(table_name, chavi_field_name)
                        
                        if field_metadata:
                            # Create mapping
                            DataFieldConfiguration.objects.create(
                                import_data=import_data,
                                file_field_name=source_field,
                                field_data_type=field_metadata['data_type'],
                                client_app_table_name=field_metadata['table_name'],
                                client_app_field_name=field_metadata['field_name'],
                                client_app_field_type=(
                                    'Foreign Key' if field_metadata['is_foreign_key']
                                    else 'Many to Many' if field_metadata['is_many_to_many']
                                    else 'Standard'
                                ),
                                client_app_lookup_table_name=(
                                    field_metadata.get('related_table') 
                                    if field_metadata.get('is_lookup') else None
                                ),
                                client_app_lookup_field_name=(
                                    field_metadata.get('lookup_model')
                                    if field_metadata.get('is_lookup') else None
                                ),
                            )
                            mappings_created += 1
                    except ValueError:
                        logger.warning(f"Invalid field format: {value}")
                        continue
            
            if mappings_created == 0:
                messages.error(request, 'Please map at least one field before continuing.')
                return redirect(request.path)
            
            messages.success(request, f'Successfully mapped {mappings_created} fields.')
            
            # Redirect to validation
            return redirect(f'data_import:{self.next_step_url_name}', import_id=import_id)
            
        except Exception as e:
            logger.error(f"Error saving mappings: {e}", exc_info=True)
            messages.error(request, f'Error saving mappings: {str(e)}')
            return redirect(request.path)
