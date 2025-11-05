"""
Step 2: Auto Field Matching View
"""
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from data_import.models import ImportData, ImportStatus, DataFieldConfiguration
from data_import.services.field_introspection import FieldIntrospectionService
from data_import.services.fuzzy_matcher import FuzzyMatcherService
from data_import.services.file_processor import FileProcessorService
from .base import WizardStepMixin
import logging
import json

logger = logging.getLogger(__name__)


class Step2AutoMatchView(WizardStepMixin, TemplateView):
    """
    Step 2: Automatically match imported fields to CHAVI fields using fuzzy matching.
    """
    
    step_number = 2
    step_title = "Auto Match Fields"
    step_status = ImportStatus.FIELD_MAPPING
    template_name = 'data_import/step2_auto_match.html'
    next_step_url_name = 'import_step3_manual_match'
    previous_step_url_name = None  # Can't go back to Step 1 (would need to start new import)
    
    def get(self, request, *args, **kwargs):
        """
        Perform auto-matching and display results.
        """
        import_id = kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        # Update status
        self.update_import_status(import_data, ImportStatus.FIELD_MAPPING)
        
        try:
            # Get headers from import summary
            headers = import_data.import_summary.get('headers', [])
            
            if not headers:
                # Need to parse file again
                processor = FileProcessorService(
                    import_data.file.path,
                    import_data.data_type
                )
                headers, _ = processor.parse()
            
            # Initialize services
            field_service = FieldIntrospectionService()
            matcher = FuzzyMatcherService(field_service)
            
            # Perform fuzzy matching
            match_results = matcher.match_source_fields(headers)
            
            # Categorize results
            auto_matched = {}
            suggestions = {}
            manual_needed = {}
            
            for source_field, result in match_results.items():
                if result['match_type'] == 'auto':
                    auto_matched[source_field] = result['auto_match']
                elif result['match_type'] == 'suggestions':
                    suggestions[source_field] = result['suggestions']
                else:
                    manual_needed[source_field] = result
            
            # Store results in session for next step
            request.session[f'match_results_{import_id}'] = {
                'auto_matched': self._serialize_matches(auto_matched),
                'suggestions': self._serialize_matches(suggestions),
                'manual_needed': list(manual_needed.keys()),
            }
            
            # Store auto-matched fields in database
            for source_field, match in auto_matched.items():
                DataFieldConfiguration.objects.create(
                    import_data=import_data,
                    file_field_name=source_field,
                    field_data_type=match['field']['data_type'],
                    client_app_table_name=match['field']['table_name'],
                    client_app_field_name=match['field']['field_name'],
                    client_app_field_type='Foreign Key' if match['field']['is_foreign_key'] 
                                         else 'Many to Many' if match['field']['is_many_to_many']
                                         else 'Standard',
                    client_app_lookup_table_name=match['field'].get('related_table') if match['field'].get('is_lookup') else None,
                    client_app_lookup_field_name=match['field'].get('lookup_model') if match['field'].get('is_lookup') else None,
                )
            
            messages.success(
                request,
                f'Auto-matched {len(auto_matched)} fields. '
                f'{len(suggestions)} fields have suggestions. '
                f'{len(manual_needed)} fields need manual selection.'
            )
            
        except Exception as e:
            logger.error(f"Error in auto-matching: {e}", exc_info=True)
            messages.error(request, f'Error during auto-matching: {str(e)}')
        
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        """
        Handle user acceptance/rejection of auto-matches and suggestions.
        """
        import_id = kwargs.get('import_id')
        import_data = self.get_import_data(import_id)
        
        # Get user selections from form
        accepted_suggestions = request.POST.getlist('accept_suggestion')
        rejected_auto = request.POST.getlist('reject_auto')
        
        # Update database based on user selections
        try:
            # Remove rejected auto-matches
            if rejected_auto:
                DataFieldConfiguration.objects.filter(
                    import_data=import_data,
                    file_field_name__in=rejected_auto
                ).delete()
            
            # Add accepted suggestions
            match_results = request.session.get(f'match_results_{import_id}', {})
            suggestions = match_results.get('suggestions', {})
            
            for source_field in accepted_suggestions:
                selected_match_index = request.POST.get(f'suggestion_choice_{source_field}')
                if selected_match_index and source_field in suggestions:
                    match = suggestions[source_field][int(selected_match_index)]
                    
                    DataFieldConfiguration.objects.create(
                        import_data=import_data,
                        file_field_name=source_field,
                        field_data_type=match['data_type'],
                        client_app_table_name=match['table_name'],
                        client_app_field_name=match['field_name'],
                        client_app_field_type='Foreign Key' if match['is_foreign_key']
                                             else 'Many to Many' if match['is_many_to_many']
                                             else 'Standard',
                        client_app_lookup_table_name=match.get('related_table') if match.get('is_lookup') else None,
                        client_app_lookup_field_name=match.get('lookup_model') if match.get('is_lookup') else None,
                    )
            
            messages.success(request, 'Field mappings updated successfully.')
            
            # Redirect to next step
            return redirect(f'data_import:{self.next_step_url_name}', import_id=import_id)
            
        except Exception as e:
            logger.error(f"Error updating field mappings: {e}", exc_info=True)
            messages.error(request, f'Error updating mappings: {str(e)}')
            return self.get(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        """Add matching results to context."""
        context = super().get_context_data(**kwargs)
        
        import_id = self.kwargs.get('import_id')
        match_results = self.request.session.get(f'match_results_{import_id}', {})
        
        context.update({
            'auto_matched': match_results.get('auto_matched', {}),
            'suggestions': match_results.get('suggestions', {}),
            'manual_needed': match_results.get('manual_needed', []),
        })
        
        return context
    
    def _serialize_matches(self, matches):
        """
        Serialize match results for session storage.
        
        Args:
            matches: Dictionary of matches
            
        Returns:
            JSON-serializable dictionary
        """
        serialized = {}
        
        for key, value in matches.items():
            if isinstance(value, dict):
                # Single match
                serialized[key] = self._serialize_match(value)
            elif isinstance(value, list):
                # Multiple matches
                serialized[key] = [self._serialize_match(m) for m in value]
        
        return serialized
    
    def _serialize_match(self, match):
        """Serialize a single match."""
        if 'field' in match:
            # Extract only serializable data from field
            return {
                'score': match.get('score'),
                'model_name': match.get('model_name'),
                'table_name': match.get('table_name'),
                'field_name': match.get('field_name'),
                'verbose_name': match.get('verbose_name'),
                'help_text': match.get('help_text'),
                'data_type': match.get('data_type'),
                'is_required': match.get('is_required'),
                'is_foreign_key': match.get('is_foreign_key'),
                'is_many_to_many': match.get('is_many_to_many'),
                'is_lookup': match.get('is_lookup'),
            }
        return match
    
    def validate_step_access(self, import_data):
        """Validate that file has been uploaded."""
        return import_data.status in [
            ImportStatus.UPLOADED,
            ImportStatus.FIELD_MAPPING,
        ]
