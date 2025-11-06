"""
Step 11: Execute the import.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from .base import BaseImportView
from ..models import FileImportJSON, FileImportSessionStep
import traceback


class Step12ExecuteImportView(BaseImportView):
    """
    Step 12: Execute the import using DRF serializers.
    Wraps import in database transaction for atomicity.
    """
    step_identifier = FileImportSessionStep.EXECUTE
    step_name = "Execute Import"
    template_name = 'data_import/step12_complete.html'
    
    def get(self, request, session_id):
        session = self.get_session(session_id)
        if not self.validate_step_access(session):
            return redirect('data_import:step11', session_id=session.id)
        
        # Check if already imported
        import_status = getattr(session, 'data_imported', False)
        
        context = self.get_context_data(
            session=session,
            import_status=import_status,
        )
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        session = self.get_session(session_id)
        
        # Execute import in transaction
        import_successful = False
        error_message = None
        records_created = 0
        
        try:
            with transaction.atomic():
                from ..services import ImportExecutorService
                
                # Execute the actual import
                import_successful, records_created, error_message = ImportExecutorService.execute_import(session)
                
                if import_successful:
                    # Mark session as completed
                    session.data_imported = True
                    session.save()
                else:
                    # Rollback transaction on error
                    raise Exception(error_message or "Import failed")
                
        except Exception as e:
            error_message = str(e)
            error_traceback = traceback.format_exc()
            messages.error(
                request,
                f"Import failed: {error_message}"
            )
            
            # Log error for debugging
            print(f"Import error: {error_traceback}")
        
        if import_successful:
            messages.success(
                request,
                f"Import completed successfully! Created {records_created} patient record(s)."
            )
        
        context = self.get_context_data(
            session=session,
            import_successful=import_successful,
            error_message=error_message,
            records_created=records_created,
        )
        return render(request, self.template_name, context)
