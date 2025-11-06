"""
Step 10: Review generated JSON before import.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..models import FileImportJSON, FileImportUUIDValues, FileImportSessionStep
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
        
        context = self.get_context_data(
            session=session,
            json_data=json_data,
            json_preview=json_preview,
            form=form,
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
