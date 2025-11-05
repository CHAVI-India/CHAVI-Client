"""Step 4: Date Interval Configuration View"""
from django.views.generic import FormView
from django.shortcuts import redirect
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, ImportDateIntervalFieldConfiguration, DataFieldConfiguration
from data_import.services.file_processor import FileProcessorService
from data_import.services.field_introspection import FieldIntrospectionService
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)


class Step4DateIntervalConfigView(WizardStepMixin, FormView):
    """
    Step 4: Configure conversion of intervals/durations (like age, overall survival) to dates.
    """
    
    step_number = 4
    step_title = "Date Interval Configuration"
    step_status = ImportStatus.DATE_INTERVAL_CONFIG
    template_name = 'data_import/step4_date_interval_config.html'
    next_step_url_name = 'import_step5_validation'
    previous_step_url_name = 'import_step3_date_format_config'
    
    def get_form_class(self):
        # Dynamic form will be created in template
        from django import forms
        return forms.Form
    
    def get(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        self.update_import_status(import_data, ImportStatus.DATE_INTERVAL_CONFIG)
        
        # Get file headers and sample data to identify numeric fields
        try:
            processor = FileProcessorService(import_data.file.path, import_data.data_type)
            headers, data_rows = processor.parse()
            # Get first few rows to check data types
            sample_rows = data_rows[:10] if len(data_rows) > 10 else data_rows
        except Exception as e:
            logger.error(f"Error parsing file: {e}")
            headers = []
            sample_rows = []
        
        # Get all numeric/interval fields that could be converted to dates
        field_service = FieldIntrospectionService()
        interval_fields = []
        date_fields_from_file = []
        all_chavi_date_fields = []
        
        # Get all available CHAVI date fields from field introspection
        all_fields = field_service.get_all_fields()
        for field in all_fields:
            if field.get('data_type') in ['Date', 'DateTime']:
                all_chavi_date_fields.append({
                    'table_name': field['table_name'],
                    'field_name': field['field_name'],
                    'verbose_name': field.get('verbose_name', field['field_name']),
                    'help_text': field.get('help_text', ''),
                    'full_name': f"{field['table_name']}.{field['field_name']}"
                })
        
        # Collect ALL date fields from the file (not just mapped ones)
        # We'll identify them by checking if they look like dates in the sample data
        date_field_candidates = set()
        
        # First add any fields that are already mapped to date fields
        for mapping in import_data.data_fields.all():
            if not mapping.client_app_field_name:
                continue
                
            field_meta = field_service.get_field(
                mapping.client_app_table_name,
                mapping.client_app_field_name
            )
            
            if field_meta and field_meta.get('data_type') in ['Date', 'DateTime']:
                date_field_candidates.add(mapping.file_field_name)
        
        # Now check all headers in the file to find potential date fields
        # by looking at the sample data
        for header in headers:
            if header in date_field_candidates:
                continue  # Already identified
                
            # Check if this field looks like a date by sampling data
            looks_like_date = False
            for row in sample_rows[:5]:
                value = row.get(header)
                if value and str(value).strip():
                    value_str = str(value).strip()
                    
                    # Heuristic 1: Contains date separators and has numbers
                    if any(sep in value_str for sep in ['-', '/', '.', ' ']) and any(c.isdigit() for c in value_str):
                        # Check if it has date-like structure (e.g., 2-3 parts separated by delimiter)
                        parts = [p for p in value_str.replace('/', '-').replace('.', '-').replace(' ', '-').split('-') if p]
                        if 2 <= len(parts) <= 3:
                            looks_like_date = True
                            break
                    
                    # Heuristic 2: All digits with length typical of date formats (YYMMDD=6, YYYYMMDD=8)
                    if value_str.isdigit() and len(value_str) in [6, 8]:
                        looks_like_date = True
                        break
                    
                    # Heuristic 3: ISO format datetime (YYYY-MM-DDTHH:MM:SS or similar)
                    if 'T' in value_str and any(c.isdigit() for c in value_str):
                        looks_like_date = True
                        break
            
            if looks_like_date:
                date_field_candidates.add(header)
        
        # Build the date_fields_from_file list
        for field_name in sorted(date_field_candidates):
            date_fields_from_file.append({
                'file_field_name': field_name
            })
        
        # Now, identify ALL numeric fields from the file (not just mapped ones)
        # This allows users to convert any numeric field to a date
        for header in headers:
            # Check if this field looks numeric by sampling data
            is_numeric = False
            sample_values = []
            
            for row in sample_rows:
                value = row.get(header)
                if value is not None and str(value).strip():
                    sample_values.append(str(value))
                    # Try to convert to number
                    try:
                        float(str(value).strip())
                        is_numeric = True
                    except (ValueError, TypeError):
                        pass
                
                if len(sample_values) >= 3:
                    break
            
            if is_numeric:
                # Check if configuration already exists
                existing_config = ImportDateIntervalFieldConfiguration.objects.filter(
                    import_data=import_data,
                    interval_field=header
                ).first()
                
                # Check if this field is already mapped to something
                mapped_to = None
                for mapping in import_data.data_fields.all():
                    if mapping.file_field_name == header and mapping.client_app_field_name:
                        mapped_to = f"{mapping.client_app_table_name}.{mapping.client_app_field_name}"
                        break
                
                interval_fields.append({
                    'file_field_name': header,
                    'mapped_to': mapped_to,
                    'sample_values': sample_values,
                    'existing_config': existing_config
                })
        
        context = self.get_context_data(**kwargs)
        context['interval_fields'] = interval_fields
        context['date_fields_from_file'] = date_fields_from_file
        context['all_chavi_date_fields'] = all_chavi_date_fields
        context['file_headers'] = headers
        context['import_data'] = import_data
        
        return self.render_to_response(context)
    
    def post(self, request, *args, **kwargs):
        import_data = self.get_import_data(kwargs['import_id'])
        
        try:
            # Process date interval configurations
            from data_import.models import CalculatiopnDateFieldType
            
            logger.info(f"Step 4 POST data: {dict(request.POST)}")
            
            # Clear existing configurations for this import
            ImportDateIntervalFieldConfiguration.objects.filter(import_data=import_data).delete()
            
            saved_count = 0
            for key, value in request.POST.items():
                if key.startswith('interval_field_') and value:
                    # Extract the interval field name
                    interval_field = value
                    
                    logger.info(f"Found interval field checkbox: {key} = {value}")
                    
                    # Get corresponding configuration fields
                    interval_units_key = f'interval_units_{interval_field}'
                    target_date_key = f'target_date_field_{interval_field}'
                    calc_date_key = f'calculation_date_{interval_field}'
                    calc_type_key = f'calculation_date_type_{interval_field}'
                    
                    interval_units = request.POST.get(interval_units_key)
                    target_date_field = request.POST.get(target_date_key)
                    calculation_date = request.POST.get(calc_date_key)
                    calculation_date_type = request.POST.get(calc_type_key)
                    
                    logger.info(f"Field: {interval_field}, Units: {interval_units}, Target: {target_date_field}, CalcDate: {calculation_date}, CalcType: {calculation_date_type}")
                    
                    if interval_units and target_date_field and calculation_date and calculation_date_type:
                        ImportDateIntervalFieldConfiguration.objects.create(
                            import_data=import_data,
                            interval_field=interval_field,
                            interval_units=interval_units,
                            target_date_field=target_date_field,
                            calculation_date=calculation_date,
                            calculation_date_type=calculation_date_type
                        )
                        saved_count += 1
                        logger.info(f"Successfully saved interval configuration for {interval_field}")
                    else:
                        logger.warning(f"Skipping {interval_field} - missing required fields: units={bool(interval_units)}, target={bool(target_date_field)}, calc_date={bool(calculation_date)}, calc_type={bool(calculation_date_type)}")
            
            if saved_count > 0:
                messages.success(request, f'Date interval configured for {saved_count} field(s).')
            else:
                messages.info(request, 'No interval fields configured. Proceeding to validation.')
            
            # Redirect to validation step
            return redirect('data_import:import_step5_validation', import_id=import_data.id)
            
        except Exception as e:
            logger.error(f"Error saving date interval configuration: {e}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return redirect(request.path)
