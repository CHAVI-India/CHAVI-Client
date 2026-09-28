"""
Step 1: Upload CSV file and select projects.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse
from .base import BaseImportView
from ..forms import Step1UploadCSVForm
from ..services import CSVProcessorService
from ..models import FileImportSessionStep


class Step1UploadCSVView(BaseImportView):
    """
    Step 1: Upload CSV file and select projects.
    """
    step_identifier = FileImportSessionStep.UPLOAD
    step_name = "Upload CSV File"
    template_name = 'data_import/step1_upload.html'

    def get_required_permission(self):
        # Creating a brand-new session (no session_id) needs add; editing
        # an existing session falls back to the base view/change rules.
        if self.kwargs.get('session_id') is None:
            return 'data_import.add_fileimportsession'
        return super().get_required_permission()

    def get(self, request, session_id=None):
        """
        Display the upload form.
        If session_id is provided, allow editing.
        """
        session = None
        form = None
        
        if session_id:
            # Editing existing session
            session = self.get_session(session_id)
            form = Step1UploadCSVForm(instance=session)
        else:
            # New session
            form = Step1UploadCSVForm()
        
        context = self.get_context_data(
            session=session,
            form=form,
        )
        
        return render(request, self.template_name, context)
    
    def post(self, request, session_id=None):
        """
        Handle form submission.
        """
        session = None
        
        if session_id:
            # Editing existing session
            session = self.get_session(session_id)
            form = Step1UploadCSVForm(request.POST, request.FILES, instance=session)
        else:
            # New session
            form = Step1UploadCSVForm(request.POST, request.FILES)
        
        if form.is_valid():
            # Save the session
            session = form.save(commit=False)
            
            # Validate CSV file
            if 'csv_file' in request.FILES or session.csv_file:
                csv_file = request.FILES.get('csv_file', session.csv_file)
                headers, rows, error = CSVProcessorService.read_csv_file(csv_file)
                
                if error:
                    messages.error(request, f"Error reading CSV file: {error}")
                    context = self.get_context_data(session=session, form=form)
                    return render(request, self.template_name, context)
                
                if not headers or not rows:
                    messages.error(request, "CSV file is empty or has no data rows.")
                    context = self.get_context_data(session=session, form=form)
                    return render(request, self.template_name, context)
                
                # Validate CSV structure
                is_valid, validation_error = CSVProcessorService.validate_csv_structure(headers)
                if not is_valid:
                    messages.error(request, f"CSV validation error: {validation_error}")
                    context = self.get_context_data(session=session, form=form)
                    return render(request, self.template_name, context)
                
                # Store row count for display
                row_count = CSVProcessorService.get_row_count(rows)
                messages.success(
                    request,
                    f"CSV file uploaded successfully! Found {len(headers)} columns and {row_count} data rows."
                )
            
            # Save session
            session.save()
            form.save_m2m()  # Save many-to-many relationships (projects)
            
            # Update session step to 2 (next step) to allow access
            self.update_session_step(session, FileImportSessionStep.PATIENT_ID)
            
            messages.success(request, "Step 1 completed successfully!")
            
            # Redirect to Step 2
            return redirect('data_import:step2', session_id=session.id)
        
        # Form is invalid
        context = self.get_context_data(
            session=session,
            form=form,
        )
        return render(request, self.template_name, context)
