"""
Base view class for import workflow.
"""

from django.views.generic import View
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from ..models import FileImportSession, FileImportSessionStep


class BaseImportView(LoginRequiredMixin, View):
    """
    Base view for all import workflow steps.
    Provides common functionality for session management and navigation.
    """

    # Override in subclasses
    step_identifier = None  # e.g., FileImportSessionStep.UPLOAD
    step_name = None  # Display name
    template_name = None

    def get_required_permission(self):
        """Permission required for the current request.

        Reads (GET/HEAD) need ``view_fileimportsession``; writes (POST)
        need ``change_fileimportsession``. Subclasses may override.
        """
        if self.request.method == 'POST':
            return 'data_import.change_fileimportsession'
        return 'data_import.view_fileimportsession'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            # Let LoginRequiredMixin produce the login redirect.
            return super().dispatch(request, *args, **kwargs)
        perm = self.get_required_permission()
        if perm and not request.user.has_perm(perm):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    
    # Step order - defines the sequence of steps
    STEP_ORDER = [
        FileImportSessionStep.UPLOAD,
        FileImportSessionStep.PATIENT_ID,
        FileImportSessionStep.MODEL_SELECTION,
        FileImportSessionStep.FIELD_MAPPING,
        FileImportSessionStep.COLUMN_VALUE,
        FileImportSessionStep.DATE_FORMAT,
        FileImportSessionStep.DURATION_DATE,
        FileImportSessionStep.LOOKUP_MAPPING,
        FileImportSessionStep.DEFAULT_VALUES,  # New step 9
        FileImportSessionStep.MISSING_RELATIONS,  # Now step 10
        FileImportSessionStep.REVIEW,  # Now step 11
        FileImportSessionStep.EXECUTE,  # Now step 12
    ]
    
    def get_session(self, session_id):
        """
        Get the import session or return 404.
        """
        return get_object_or_404(FileImportSession, id=session_id)
    
    def validate_step_access(self, session):
        """
        Validate that the user can access this step.
        Users can only access the current step or previous steps.
        """
        if not self.step_identifier:
            return True
        
        current_step = session.import_session_step
        current_step_index = self._get_step_index(current_step)
        requested_step_index = self._get_step_index(self.step_identifier)
        
        # Allow access to current step or any previous step
        if requested_step_index <= current_step_index:
            return True
        
        # Cannot skip ahead
        messages.error(
            self.request,
            f"Please complete {self._get_step_display_name(current_step)} before proceeding."
        )
        return False
    
    def _get_step_index(self, step_identifier):
        """Get the index of a step in the step order."""
        try:
            return self.STEP_ORDER.index(step_identifier)
        except ValueError:
            return 0
    
    def _get_step_display_name(self, step_identifier):
        """Get display name for a step."""
        step_names = {
            FileImportSessionStep.UPLOAD: 'Upload CSV',
            FileImportSessionStep.PATIENT_ID: 'Patient ID Mapping',
            FileImportSessionStep.MODEL_SELECTION: 'Model Selection',
            FileImportSessionStep.FIELD_MAPPING: 'Field Mapping',
            FileImportSessionStep.COLUMN_VALUE: 'Column Value Mapping',
            FileImportSessionStep.DATE_FORMAT: 'Date Format',
            FileImportSessionStep.DURATION_DATE: 'Duration Date',
            FileImportSessionStep.LOOKUP_MAPPING: 'Lookup Mapping',
            FileImportSessionStep.DEFAULT_VALUES: 'Default Values',  # New step 9
            FileImportSessionStep.MISSING_RELATIONS: 'Missing Relations',  # Now step 10
            FileImportSessionStep.REVIEW: 'Review',  # Now step 11
            FileImportSessionStep.EXECUTE: 'Execute Import',  # Now step 12
        }
        return step_names.get(step_identifier, 'Unknown Step')
    
    def update_session_step(self, session, next_step_identifier):
        """
        Update the session's current step.
        Only update if moving forward or equal (to mark completion).
        """
        current_step_index = self._get_step_index(session.import_session_step)
        next_step_index = self._get_step_index(next_step_identifier)
        
        # Only update if moving forward
        if next_step_index >= current_step_index:
            session.import_session_step = next_step_identifier
            session.save()
    
    def get_context_data(self, session=None, **kwargs):
        """
        Get common context data for all steps.
        """
        current_step_index = self._get_step_index(self.step_identifier) if self.step_identifier else 0
        
        context = {
            'session': session,
            'step_number': current_step_index + 1,  # Display number (1-based)
            'step_name': self.step_name,
            'total_steps': len(self.STEP_ORDER),
            'step_identifier': self.step_identifier,
        }
        
        context.update(kwargs)
        return context
    
    def get_csv_data(self, session):
        """
        Get CSV data from the session.
        Returns (headers, rows, error).
        """
        from ..services import CSVProcessorService
        
        if not session.csv_file:
            return None, None, "No CSV file uploaded"
        
        return CSVProcessorService.read_csv_file(session.csv_file)
