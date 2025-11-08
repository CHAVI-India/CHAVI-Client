"""
Step 6: Set date formats for date fields.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..models import FileMappedModel, FileMappedField, FileDateFieldMapping, DateFormat, FileImportSessionStep
from ..services import FieldIntrospectionService, DateFormatParser


class Step6DateFormatView(BaseImportView):
    """
    Step 6: Set date formats for mapped date fields.
    """
    step_identifier = FileImportSessionStep.DATE_FORMAT
    step_name = "Set Date Formats"
    template_name = 'data_import/step6_date_format.html'
    
    def get(self, request, session_id):
        session = self.get_session(session_id)
        if not self.validate_step_access(session):
            return redirect('data_import:step5', session_id=session.id)
        
        # Get selected models
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model:
            messages.error(request, "No models selected.")
            return redirect('data_import:step3', session_id=session.id)
        
        # Get complete model list including parent models
        user_selected_models = mapped_model.client_app_model_name
        selected_models = ModelHierarchyService.get_complete_model_list(user_selected_models)
        
        # Get CSV data for sample values
        headers, rows, error = self.get_csv_data(session)
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Get mapped fields from Step 4
        mapped_fields = FileMappedField.objects.filter(file_import_session=session)
        
        # Identify date fields
        date_fields_info = []
        for mapping in mapped_fields:
            # Parse model.field format
            if '.' in mapping.mapped_client_app_field_name:
                model_name, field_name = mapping.mapped_client_app_field_name.split('.', 1)
                
                # Check if this is a date field
                fields = FieldIntrospectionService.get_model_fields(model_name)
                field_info = fields.get(field_name)
                
                if field_info and field_info.get('type') in ['DateField', 'DateTimeField']:
                    # Get sample values from CSV
                    csv_columns = mapping.csv_field_names
                    sample_values = []
                    if csv_columns and rows:
                        # Get sample from first non-empty row for each CSV column
                        for col in csv_columns:
                            if col in headers:
                                col_index = headers.index(col)
                                # Find first non-empty value
                                for row in rows[:10]:  # Check first 10 rows
                                    if isinstance(row, dict):
                                        value = row.get(col, '').strip()
                                    else:
                                        value = row[col_index].strip() if col_index < len(row) else ''
                                    
                                    if value:
                                        sample_values.append(value)
                                        break
                    
                    date_fields_info.append({
                        'mapping': mapping,
                        'model_name': model_name,
                        'field_name': field_name,
                        'csv_columns': csv_columns,
                        'sample_values': sample_values,
                    })
        
        # Get existing date format mappings
        existing_formats = FileDateFieldMapping.objects.filter(file_import_session=session)
        existing_formats_dict = {fmt.csv_column_name: fmt.date_format for fmt in existing_formats}
        
        # Get date format choices
        date_format_choices = DateFormat.choices
        format_examples = {choice[0]: DateFormatParser.get_format_example(choice[0]) for choice in date_format_choices}
        
        context = self.get_context_data(
            session=session,
            date_fields_info=date_fields_info,
            date_format_choices=date_format_choices,
            format_examples=format_examples,
            existing_formats_dict=existing_formats_dict,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        
        # Check if user wants to skip this step
        if 'skip_step' in request.POST:
            self.update_session_step(session, FileImportSessionStep.DURATION_DATE)
            messages.info(request, "Skipped date format configuration.")
            return redirect('data_import:step7', session_id=session.id)
        
        # Clear existing date format mappings
        FileDateFieldMapping.objects.filter(file_import_session=session).delete()
        
        # Process date format selections
        # Format: date_format_<csv_column> = format_choice
        mappings_created = 0
        
        for key, value in request.POST.items():
            if key.startswith('date_format_'):
                csv_column = key[12:]  # Remove 'date_format_' prefix
                date_format = value
                
                if date_format:
                    FileDateFieldMapping.objects.create(
                        file_import_session=session,
                        csv_column_name=csv_column,
                        date_format=date_format
                    )
                    mappings_created += 1
        
        # Update session step to next step
        self.update_session_step(session, FileImportSessionStep.DURATION_DATE)
        
        if mappings_created > 0:
            messages.success(request, f"Set date format for {mappings_created} field(s).")
        else:
            messages.info(request, "No date formats configured.")
        
        # Redirect to Step 7
        return redirect('data_import:step7', session_id=session.id)
