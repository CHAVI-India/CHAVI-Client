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
    
    def _copy_date_configs(self, source_import, target_import):
        """Copy date format configurations from source import to target import"""
        copied_count = 0
        
        for source_config in ImportDateFormatConfiguration.objects.filter(
            data_field_configuration__import_data=source_import
        ):
            # Find matching field in target import
            target_mapping = target_import.data_fields.filter(
                file_field_name=source_config.data_field_configuration.file_field_name,
                client_app_table_name=source_config.data_field_configuration.client_app_table_name,
                client_app_field_name=source_config.data_field_configuration.client_app_field_name
            ).first()
            
            if target_mapping:
                # Create config for target mapping
                ImportDateFormatConfiguration.objects.get_or_create(
                    data_field_configuration=target_mapping,
                    defaults={
                        'date_format': source_config.date_format,
                        'date_separator': source_config.date_separator
                    }
                )
                copied_count += 1
        
        logger.info(f"Copied {copied_count} date format configurations")
        return copied_count
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.DATE_FORMAT_CONFIG)
        
        # Check if we need to copy configs from a previous import
        existing_configs_count = ImportDateFormatConfiguration.objects.filter(
            data_field_configuration__import_data=import_data
        ).count()
        
        if existing_configs_count == 0:
            # Try to find the most recent import with date format configs
            # Need to go through data_fields -> date_format_configurations
            latest_import_with_configs = ImportData.objects.filter(
                data_fields__date_format_configurations__isnull=False
            ).distinct().order_by('-id').first()
            
            if latest_import_with_configs:
                logger.info(f"Copying date format configs from import {latest_import_with_configs.id} to {import_data.id}")
                self._copy_date_configs(latest_import_with_configs, import_data)
        
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
                # Check if configuration already exists - first by direct FK
                logger.info(f"Looking for config for mapping ID {mapping.id}: {mapping.file_field_name}")
                existing_config = ImportDateFormatConfiguration.objects.filter(
                    data_field_configuration=mapping
                ).first()
                
                # If not found by FK, try to find by matching field names in same import
                if not existing_config:
                    logger.info(f"  Not found by FK, trying by field names...")
                    all_configs = ImportDateFormatConfiguration.objects.filter(
                        data_field_configuration__import_data=import_data
                    )
                    logger.info(f"  Total configs for this import (ID {import_data.id}): {all_configs.count()}")
                    
                    # Check if ANY configs exist with this field name (any import)
                    any_config = ImportDateFormatConfiguration.objects.filter(
                        data_field_configuration__file_field_name=mapping.file_field_name
                    ).first()
                    if any_config:
                        logger.info(f"  Found config for this field name in import ID {any_config.data_field_configuration.import_data.id}")
                    
                    existing_config = ImportDateFormatConfiguration.objects.filter(
                        data_field_configuration__import_data=import_data,
                        data_field_configuration__file_field_name=mapping.file_field_name,
                        data_field_configuration__client_app_table_name=mapping.client_app_table_name,
                        data_field_configuration__client_app_field_name=mapping.client_app_field_name
                    ).first()
                    
                    if not existing_config:
                        # Log what configs DO exist for debugging
                        sample_config = all_configs.first()
                        if sample_config:
                            logger.info(f"  Sample existing config: FK to mapping ID {sample_config.data_field_configuration.id}, file_field={sample_config.data_field_configuration.file_field_name}")
                
                if existing_config:
                    logger.info(f"  ✓ Found config: format={existing_config.date_format}, separator={existing_config.date_separator}")
                else:
                    logger.info(f"  ✗ No config found")
                
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
                
                # Add debug info
                debug_info = {
                    'mapping_id': mapping.id,
                    'import_data_id': import_data.id,
                    'configs_for_import': ImportDateFormatConfiguration.objects.filter(
                        data_field_configuration__import_data=import_data
                    ).count(),
                    'any_config_with_name': ImportDateFormatConfiguration.objects.filter(
                        data_field_configuration__file_field_name=mapping.file_field_name
                    ).exists()
                }
                
                date_fields.append({
                    'mapping': mapping,
                    'field_meta': field_meta,
                    'existing_config': existing_config,
                    'sample_values': sample_values,
                    'debug': debug_info
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
