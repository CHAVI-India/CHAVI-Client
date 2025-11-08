"""
Step 7: Calculate dates from duration fields.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..models import FileMappedModel, FileMappedField, FileDurationDateMapping, FileImportSessionStep, DateFormat, ReferenceDateType, DurationUnits
from ..services import FieldIntrospectionService, ModelHierarchyService
from ..forms import Step7DurationDateForm
import json


class Step7DurationDateView(BaseImportView):
    """
    Step 7: Calculate dates from duration and reference date.
    """
    step_identifier = FileImportSessionStep.DURATION_DATE
    step_name = "Calculate Dates from Duration"
    template_name = 'data_import/step7_duration_date.html'
    
    def get(self, request, session_id):
        session = self.get_session(session_id)
        if not self.validate_step_access(session):
            return redirect('data_import:step6', session_id=session.id)
        
        # Get selected models
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        if not mapped_model:
            messages.error(request, "No models selected.")
            return redirect('data_import:step3', session_id=session.id)
        
        # Get complete model list including parent models
        user_selected_models = mapped_model.client_app_model_name
        selected_models = ModelHierarchyService.get_complete_model_list(user_selected_models)
        
        # Get CSV headers
        headers, rows, error = self.get_csv_data(session)
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Get ALL date fields from selected models (not just unmapped)
        all_date_fields = []
        for model_name in selected_models:
            date_fields = FieldIntrospectionService.get_date_fields(model_name)
            for field in date_fields:
                all_date_fields.append(f"{model_name}.{field}")
        
        # Get existing duration mappings
        existing_mappings = FileDurationDateMapping.objects.filter(file_import_session=session)
        
        # Prepare data for JavaScript
        import json
        from ..models import DurationUnits, ReferenceDateType, DateFormat
        
        context = self.get_context_data(
            session=session,
            csv_headers=json.dumps(headers),
            all_date_fields=json.dumps(all_date_fields),
            duration_units=json.dumps(DurationUnits.choices),
            reference_date_types=json.dumps(ReferenceDateType.choices),
            date_formats=json.dumps(DateFormat.choices),
            existing_mappings=existing_mappings,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        
        # Check if user wants to skip this step
        if 'skip_step' in request.POST:
            self.update_session_step(session, FileImportSessionStep.LOOKUP_MAPPING)
            messages.info(request, "Skipped duration date calculation.")
            return redirect('data_import:step8', session_id=session.id)
        
        # Clear existing mappings
        FileDurationDateMapping.objects.filter(file_import_session=session).delete()
        
        # Process multiple duration mappings
        # Format: duration_0_csv_field, duration_0_unit, etc.
        mappings_created = 0
        mapping_indices = set()
        
        # Find all mapping indices
        for key in request.POST.keys():
            if key.startswith('duration_') and '_csv_field' in key:
                # Extract index from key like "duration_0_csv_field"
                index = key.split('_')[1]
                mapping_indices.add(index)
        
        # Create mappings for each index
        for index in mapping_indices:
            csv_field = request.POST.get(f'duration_{index}_csv_field')
            unit = request.POST.get(f'duration_{index}_unit')
            ref_value = request.POST.get(f'duration_{index}_ref_value')
            ref_type = request.POST.get(f'duration_{index}_ref_type')
            ref_format = request.POST.get(f'duration_{index}_ref_format', '')
            target_field = request.POST.get(f'duration_{index}_target_field')
            
            # Validate required fields
            if csv_field and unit and ref_value and ref_type and target_field:
                FileDurationDateMapping.objects.create(
                    file_import_session=session,
                    csv_duration_field=csv_field,
                    duration_unit=unit,
                    reference_date=ref_value,
                    reference_date_type=ref_type,
                    reference_date_format=ref_format,
                    client_app_date_field=target_field,
                )
                mappings_created += 1
        
        if mappings_created > 0:
            messages.success(request, f"Created {mappings_created} duration date calculation(s) successfully!")
        else:
            messages.info(request, "No duration calculations configured.")
        
        self.update_session_step(session, FileImportSessionStep.LOOKUP_MAPPING)
        return redirect('data_import:step8', session_id=session.id)
