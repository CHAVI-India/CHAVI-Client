"""Step 5: Data Validation View"""
from django.views.generic import FormView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus
from data_import.services.file_processor import FileProcessorService
from data_import.services.data_validator import DataValidatorService
from data_import.forms import ValidationReviewForm
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)

class Step5ValidationView(WizardStepMixin, FormView):
    step_number = 3
    step_title = "Validate Data"
    step_status = ImportStatus.VALIDATING
    template_name = 'data_import/step5_validation.html'
    next_step_url_name = 'import_step4_lookup_matching'
    previous_step_url_name = 'import_step2_field_mapping'
    form_class = ValidationReviewForm
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.VALIDATING)
        
        if not import_data.validation_errors:
            try:
                processor = FileProcessorService(import_data.file.path, import_data.data_type)
                headers, data_rows = processor.parse()
                
                # Get field mappings and validate
                from data_import.services.field_introspection import FieldIntrospectionService
                field_service = FieldIntrospectionService()
                validator = DataValidatorService()
                
                # Build field mappings dict (only for mapped fields)
                field_mappings = {}
                for mapping in import_data.data_fields.all():
                    # Skip unmapped fields
                    if not mapping.client_app_field_name or not mapping.client_app_table_name:
                        logger.info(f"Skipping unmapped field: {mapping.file_field_name}")
                        continue
                    
                    field_meta = field_service.get_field(
                        mapping.client_app_table_name, mapping.client_app_field_name
                    )
                    if field_meta:
                        field_mappings[mapping.file_field_name] = field_meta
                        logger.info(f"Added to validation: {mapping.file_field_name} -> {mapping.client_app_field_name}")
                
                logger.info(f"Validating {len(field_mappings)} mapped fields: {list(field_mappings.keys())}")
                validation_result = validator.validate_data(data_rows, field_mappings)
                logger.info(f"Validation complete. Errors by field: {validation_result.get('errors_by_field', {}).keys()}")
                import_data.validation_errors = validation_result
                import_data.save()
                
                if validation_result['is_valid']:
                    messages.success(request, f'All {validation_result["total_rows"]} rows passed!')
                else:
                    messages.warning(request, f'{validation_result["invalid_rows"]} rows have errors.')
            except Exception as e:
                logger.error(f"Validation error: {e}")
                messages.error(request, f'Error: {str(e)}')
        
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        action = request.POST.get('action')
        
        if action == 'proceed':
            return redirect(f'data_import:{self.next_step_url_name}', import_id=import_data.id)
        
        return redirect(request.path)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import_data = self.get_import_data(self.kwargs['import_id'])
        validation_result = import_data.validation_errors or {}
        
        context['validation_result'] = validation_result
        context['has_errors'] = not validation_result.get('is_valid', True) and validation_result.get('invalid_rows', 0) > 0
        
        # Add error details for template
        if context['has_errors']:
            errors_by_field = validation_result.get('errors_by_field', {})
            errors_by_row = validation_result.get('errors_by_row', {})
            
            # Create a lookup for field names
            field_name_lookup = {}
            for mapping in import_data.data_fields.all():
                if mapping.client_app_field_name:
                    field_name_lookup[mapping.file_field_name] = {
                        'chavi_field': mapping.client_app_field_name,
                        'model': mapping.client_app_table_name,
                    }
            
            # Enhance errors_by_field with CHAVI field names
            enhanced_errors = []
            for source_field, error_count in errors_by_field.items():
                chavi_info = field_name_lookup.get(source_field, {})
                enhanced_errors.append({
                    'source_field': source_field,
                    'chavi_field': chavi_info.get('chavi_field', 'Not Mapped'),
                    'model': chavi_info.get('model', ''),
                    'error_count': error_count,
                })
            
            context['errors_by_field'] = errors_by_field
            context['enhanced_errors_by_field'] = enhanced_errors
            context['errors_by_row'] = errors_by_row
        
        # Add field mappings summary
        from data_import.services.field_introspection import FieldIntrospectionService
        field_service = FieldIntrospectionService()
        
        field_mappings_summary = []
        for mapping in import_data.data_fields.all():
            if mapping.client_app_field_name and mapping.client_app_table_name:
                field_meta = field_service.get_field(mapping.client_app_table_name, mapping.client_app_field_name)
                if field_meta:
                    field_mappings_summary.append({
                        'file_field': mapping.file_field_name,
                        'chavi_field': mapping.client_app_field_name,
                        'model': field_meta['model_name'],
                        'table': field_meta['table_name'],
                        'data_type': field_meta['data_type'],
                        'is_required': field_meta.get('is_required', False),
                        'is_lookup': field_meta.get('is_lookup', False),
                        'field_type': mapping.client_app_field_type,
                    })
        
        context['field_mappings_summary'] = field_mappings_summary
        
        return context
