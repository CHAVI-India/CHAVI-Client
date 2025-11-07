"""
Step 10: Review generated JSON before import.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..models import (
    FileImportJSON, FileImportUUIDValues, FileImportSessionStep,
    FileMappedField, FileDefaultValues, FileMissingRelations,
    FileParentRecordMapping, FieldLookupValues, FileDateFieldMapping, FileDurationDateMapping
)
from ..forms import Step10ReviewForm
import json
import uuid


class Step11ReviewView(BaseImportView):
    """
    Step 11: Review generated JSON and confirm import.
    Generates UUIDs and displays preview of data to be imported.
    """
    step_identifier = FileImportSessionStep.REVIEW
    step_name = "Review & Confirm"
    template_name = 'data_import/step11_review.html'
    
    def get(self, request, session_id):
        session = self.get_session(session_id)
        if not self.validate_step_access(session):
            return redirect('data_import:step10', session_id=session.id)
        
        # Always regenerate JSON to reflect latest mappings
        json_data = self._generate_preview_json(session)
        json_preview = json.dumps(json_data, indent=2)
        
        # Save/update JSON
        existing_json = FileImportJSON.objects.filter(file_import_session=session).first()
        if existing_json:
            existing_json.json_data = json_data
            existing_json.save()
        else:
            FileImportJSON.objects.create(
                file_import_session=session,
                json_data=json_data
            )
        
        form = Step10ReviewForm()
        
        # Get field mappings summary
        field_mappings = FileMappedField.objects.filter(file_import_session=session).order_by('mapped_client_app_field_name')
        mapping_summary = []
        for mapping in field_mappings:
            # csv_field_names is a JSONField (list)
            csv_columns = mapping.csv_field_names if mapping.csv_field_names else []
            if isinstance(csv_columns, list):
                csv_columns_str = ', '.join(csv_columns)
            else:
                csv_columns_str = str(csv_columns)
            
            mapping_summary.append({
                'csv_columns': csv_columns_str,
                'field': mapping.mapped_client_app_field_name,
            })
        
        # Get default values
        default_values = FileDefaultValues.objects.filter(file_import_session=session).order_by('client_app_model_name', 'client_app_field_name')
        default_summary = []
        for dv in default_values:
            default_summary.append({
                'field': f"{dv.client_app_model_name}.{dv.client_app_field_name}",
                'value': dv.client_app_field_value,
            })
        
        # Get parent record mappings
        parent_mappings = FileParentRecordMapping.objects.filter(file_import_session=session).order_by('child_model_name', 'parent_fk_field')
        parent_mapping_summary = []
        for pm in parent_mappings:
            if pm.link_to_existing:
                action = f"Link to existing (ID: {pm.existing_record_id[:8]}...)"
            elif pm.create_new_parent:
                fields_str = ', '.join([f"{k}={v}" for k, v in pm.parent_field_values.items()]) if pm.parent_field_values else 'No fields'
                action = f"Create new ({fields_str})"
            else:
                action = "Not configured"
            
            parent_mapping_summary.append({
                'relationship': f"{pm.child_model_name}.{pm.parent_fk_field} → {pm.parent_model_name}",
                'action': action,
            })
        
        # Get missing relations (deprecated, but still used for non-FK fields)
        missing_relations = FileMissingRelations.objects.filter(file_import_session=session).order_by('client_app_model_name', 'client_app_field_name')
        missing_summary = []
        for mr in missing_relations:
            missing_summary.append({
                'field': f"{mr.client_app_model_name}.{mr.client_app_field_name}",
                'value': mr.client_app_field_value,
            })
        
        # Get lookup mappings
        lookup_mappings = FieldLookupValues.objects.filter(file_import_session=session).order_by('csv_column_name', 'csv_value')
        lookup_summary = []
        for lookup in lookup_mappings:
            lookup_summary.append({
                'csv_column': lookup.csv_column_name,
                'csv_value': lookup.csv_value,
                'lookup_code': lookup.lookup_value,
            })
        
        # Get date format mappings
        date_formats = FileDateFieldMapping.objects.filter(file_import_session=session).order_by('csv_column_name')
        date_format_summary = []
        for df in date_formats:
            date_format_summary.append({
                'csv_column': df.csv_column_name,
                'date_format': df.date_format,
            })
        
        # Get duration mappings
        duration_mappings = FileDurationDateMapping.objects.filter(file_import_session=session).order_by('client_app_date_field')
        duration_summary = []
        for dm in duration_mappings:
            # Determine operation based on reference_date_type
            operation = 'Add' if dm.reference_date_type == 'start' else 'Subtract'
            
            duration_summary.append({
                'csv_duration_field': dm.csv_duration_field,
                'duration_unit': dm.duration_unit,
                'reference_date': dm.reference_date,
                'reference_date_type': dm.reference_date_type,
                'target_field': dm.client_app_date_field,  # This is the model.field name
                'operation': operation,
            })
        
        context = self.get_context_data(
            session=session,
            json_data=json_data,
            json_preview=json_preview,
            form=form,
            mapping_summary=mapping_summary,
            default_summary=default_summary,
            parent_mapping_summary=parent_mapping_summary,
            missing_summary=missing_summary,
            lookup_summary=lookup_summary,
            date_format_summary=date_format_summary,
            duration_summary=duration_summary,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        form = Step10ReviewForm(request.POST)
        
        if form.is_valid():
            # User confirmed the import
            # Update session step to 11 (next step) to allow access
            self.update_session_step(session, FileImportSessionStep.EXECUTE)
            messages.success(request, "Data reviewed and confirmed. Proceeding to import...")
            return redirect('data_import:step12', session_id=session.id)
        
        # Form invalid
        existing_json = FileImportJSON.objects.filter(file_import_session=session).first()
        json_data = existing_json.json_data if existing_json else {}
        json_preview = json.dumps(json_data, indent=2)
        
        context = self.get_context_data(
            session=session,
            json_data=json_data,
            json_preview=json_preview,
            form=form,
        )
        return render(request, self.template_name, context)
    
    def _generate_preview_json(self, session):
        """
        Generate complete JSON for all records that will be imported.
        This is the actual JSON that will be used for import.
        """
        from ..services.json_generator import JSONGeneratorService
        
        # Generate complete JSON for ALL patients
        all_records = JSONGeneratorService.generate_import_json(
            session, 
            sample_only=False
        )
        
        return all_records
