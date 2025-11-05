"""Step 3: Date Format Configuration View"""
from django.views.generic import FormView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, ImportDateFormatConfiguration, DataFieldConfiguration
from data_import.services.field_introspection import FieldIntrospectionService
from data_import.services.file_processor import FileProcessorService
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)


class Step3DateFormatConfigView(WizardStepMixin, FormView):
    """
    Step 3: Configure date formats for date fields in the imported data.
    """
    
    step_number = 3
    step_title = "Date Format Configuration"
    step_status = ImportStatus.DATE_FORMAT_CONFIG
    template_name = 'data_import/step3_date_format_config.html'
    next_step_url_name = 'import_step4_date_interval_config'
    previous_step_url_name = 'import_step2_field_mapping'
    
    def get_form_class(self):
        # Dynamic form will be created in template
        from django import forms
        return forms.Form
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.DATE_FORMAT_CONFIG)
        
        # Parse file to get sample data
        try:
            processor = FileProcessorService(import_data.file.path, import_data.data_type)
            headers, data_rows = processor.parse()
            # Get first 5 rows for samples
            sample_rows = data_rows[:5] if len(data_rows) > 5 else data_rows
        except Exception as e:
            logger.error(f"Error parsing file for samples: {e}")
            sample_rows = []
        
        # Get all date fields from field mappings
        field_service = FieldIntrospectionService()
        date_fields = []
        
        for mapping in import_data.data_fields.all():
            if not mapping.client_app_field_name:
                continue
                
            field_meta = field_service.get_field(
                mapping.client_app_table_name,
                mapping.client_app_field_name
            )
            
            if field_meta and field_meta.get('data_type') in ['Date', 'DateTime']:
                # Check if configuration already exists
                existing_config = ImportDateFormatConfiguration.objects.filter(
                    data_field_configuration=mapping
                ).first()
                
                # Get sample values from the file
                sample_values = []
                logger.info(f"Looking for samples in field: {mapping.file_field_name}")
                logger.info(f"Sample rows count: {len(sample_rows)}")
                
                for idx, row in enumerate(sample_rows):
                    logger.info(f"Row {idx} keys: {list(row.keys())[:5]}")  # Show first 5 keys
                    value = row.get(mapping.file_field_name)
                    logger.info(f"Row {idx} value for {mapping.file_field_name}: {value}")
                    
                    if value and str(value).strip() and value not in sample_values:
                        sample_values.append(str(value))
                    if len(sample_values) >= 3:  # Show max 3 unique samples
                        break
                
                logger.info(f"Final sample_values for {mapping.file_field_name}: {sample_values}")
                
                date_fields.append({
                    'mapping': mapping,
                    'field_meta': field_meta,
                    'existing_config': existing_config,
                    'sample_values': sample_values
                })
        
        logger.info(f"Step 3 GET: Found {len(date_fields)} date fields to configure")
        for df in date_fields:
            logger.info(f"  - {df['mapping'].file_field_name} -> {df['mapping'].client_app_table_name}.{df['mapping'].client_app_field_name} (ID: {df['mapping'].id})")
        
        context = self.get_context_data(**kwargs)
        context['date_fields'] = date_fields
        context['import_data'] = import_data
        
        return self.render_to_response(context)
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            # Process date format configurations
            from data_import.models import DateFormatType, DateSeparatorType
            
            logger.info(f"Step 3 POST data: {dict(request.POST)}")
            
            saved_count = 0
            for key, value in request.POST.items():
                if key.startswith('date_format_'):
                    # Extract field configuration ID
                    field_config_id = key.replace('date_format_', '')
                    separator_key = f'date_separator_{field_config_id}'
                    
                    date_format = value
                    date_separator = request.POST.get(separator_key)
                    
                    logger.info(f"Processing date format: field_config_id={field_config_id}, format={date_format}, separator={date_separator}")
                    
                    if date_format and date_separator:
                        try:
                            field_config = DataFieldConfiguration.objects.get(id=field_config_id)
                            
                            # Update or create configuration
                            config, created = ImportDateFormatConfiguration.objects.update_or_create(
                                data_field_configuration=field_config,
                                defaults={
                                    'date_format': date_format,
                                    'date_separator': date_separator
                                }
                            )
                            action = "Created" if created else "Updated"
                            logger.info(f"{action} date format config for {field_config.file_field_name}: format={date_format}, separator={date_separator}")
                            saved_count += 1
                        except DataFieldConfiguration.DoesNotExist:
                            logger.warning(f"Field configuration {field_config_id} not found")
            
            if saved_count > 0:
                messages.success(request, f'Date format configured for {saved_count} field(s).')
            else:
                messages.info(request, 'No date fields to configure. Proceeding to next step.')
            
            # Redirect to next step
            return redirect('data_import:import_step4_date_interval_config', import_id=import_data.id)
            
        except Exception as e:
            logger.error(f"Error saving date format configuration: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return redirect(request.path)
