"""
Step 1: File Upload View
"""
from django.views.generic import FormView
from django.urls import reverse
from django.contrib import messages
from data_import.models import ImportData, ImportStatus, DataType
from data_import.services.file_processor import FileProcessorService
from .base import WizardStepMixin
import logging

logger = logging.getLogger(__name__)


class Step1UploadView(WizardStepMixin, FormView):
    """
    Step 1: Upload CSV/JSON file and select project(s).
    """
    
    step_number = 1
    step_title = "Upload File"
    step_status = ImportStatus.UPLOADED
    template_name = 'data_import/step1_upload.html'
    next_step_url_name = 'import_step2_field_mapping'
    
    def get_form_class(self):
        """Dynamically import form to avoid circular imports."""
        from data_import.forms import FileUploadForm
        return FileUploadForm
    
    def form_valid(self, form):
        """
        Process the uploaded file.
        
        Steps:
        1. Create ImportData record
        2. Parse file to get headers and row count
        3. Store file metadata
        4. Redirect to Step 2
        """
        try:
            # Get form data
            uploaded_file = form.cleaned_data['file']
            data_type = form.cleaned_data['data_type']
            projects = form.cleaned_data['projects']
            
            # Create ImportData record
            import_data = ImportData.objects.create(
                data_type=data_type,
                file=uploaded_file,
                status=ImportStatus.UPLOADED,
            )
            
            # Add projects (M2M relationship)
            import_data.project.set(projects)
            
            # Parse file to get metadata
            try:
                processor = FileProcessorService(
                    import_data.file.path,
                    data_type
                )
                
                # Validate file structure
                validation_result = processor.validate_file_structure()
                if not validation_result['is_valid']:
                    # File has errors
                    import_data.status = ImportStatus.FAILED
                    import_data.error_log = '\n'.join(validation_result['errors'])
                    import_data.save()
                    
                    for error in validation_result['errors']:
                        messages.error(self.request, error)
                    
                    return self.form_invalid(form)
                
                # Get file preview and stats
                preview = processor.get_preview(num_rows=10)
                headers, data_rows = processor.parse()
                
                # Update import_data with file metadata
                import_data.row_count = len(data_rows)
                import_data.import_summary = {
                    'headers': headers,
                    'preview': preview['preview_rows'],
                    'encoding': preview.get('encoding'),
                    'delimiter': preview.get('delimiter'),
                    'num_columns': len(headers),
                }
                import_data.save()
                
                messages.success(
                    self.request,
                    f'File uploaded successfully! Found {len(headers)} columns and {len(data_rows)} rows.'
                )
                
                # Store import_id in session for easy access
                self.request.session['current_import_id'] = import_data.id
                
                # Redirect to Step 2
                return self.get_success_url_redirect(import_data.id)
                
            except Exception as e:
                logger.error(f"Error processing file: {e}", exc_info=True)
                import_data.status = ImportStatus.FAILED
                import_data.error_log = str(e)
                import_data.save()
                
                messages.error(
                    self.request,
                    f'Error processing file: {str(e)}'
                )
                return self.form_invalid(form)
                
        except Exception as e:
            logger.error(f"Error in file upload: {e}", exc_info=True)
            messages.error(
                self.request,
                f'Error uploading file: {str(e)}'
            )
            return self.form_invalid(form)
    
    def get_success_url_redirect(self, import_id):
        """Get redirect response to next step."""
        from django.shortcuts import redirect
        return redirect(f'data_import:{self.next_step_url_name}', import_id=import_id)
    
    def get_context_data(self, **kwargs):
        """Add additional context."""
        context = super().get_context_data(**kwargs)
        
        # Add recent imports for reference
        recent_imports = ImportData.objects.filter(
            created_at__isnull=False
        ).order_by('-created_at')[:5]
        
        context['recent_imports'] = recent_imports
        
        return context
