"""
Step 3: Select models to import data into with hierarchy validation.
"""

import json
from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..forms import Step3ModelSelectionForm
from ..models import FileMappedModel, FileImportSessionStep
from ..services import ModelHierarchyService, FieldIntrospectionService


class Step3ModelSelectionView(BaseImportView):
    """
    Step 3: Select models to import data into.
    Validates that selected models are at the same hierarchy level.
    """
    step_identifier = FileImportSessionStep.MODEL_SELECTION
    step_name = "Select Models"
    template_name = 'data_import/step3_model_selection.html'
    
    def get(self, request, session_id):
        """
        Display model selection form with hierarchy information.
        """
        session = self.get_session(session_id)
        
        # Validate step access
        if not self.validate_step_access(session):
            current_step = self.get_step_number_from_choice(session.import_session_step)
            if current_step == 1:
                return redirect('data_import:step1_edit', session_id=session.id)
            else:
                return redirect('data_import:step2', session_id=session.id)
        
        # Get model hierarchy
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        
        # Organize models by level
        models_by_level = {}
        for model_name, level in sorted(hierarchy.items(), key=lambda x: (x[1], x[0])):
            if level not in models_by_level:
                models_by_level[level] = []
            
            # Get model display info
            model_info = FieldIntrospectionService.get_model_display_info(model_name)
            if model_info:
                # Add parent relationships
                parent_models = ModelHierarchyService.get_parent_models(model_name)
                model_info['parent_models'] = parent_models
                model_info['level'] = level
                
                # Get hierarchy path for this model and convert to JSON string
                hierarchy_path = ModelHierarchyService.get_hierarchy_path(model_name)
                model_info['hierarchy_path'] = hierarchy_path
                model_info['hierarchy_path_json'] = json.dumps(hierarchy_path)
                
                # Filter out created_at and updated_at from fields
                fields = model_info.get('fields', {})
                filtered_fields = {k: v for k, v in fields.items() 
                                 if k not in ['created_at', 'updated_at']}
                model_info['fields'] = filtered_fields
                model_info['field_count'] = len(filtered_fields)
                
                # Add docstring
                model_info['docstring'] = model_info.get('doc', '').strip() if model_info.get('doc') else None
                
                models_by_level[level].append(model_info)
        
        # Check if models already selected
        existing_mapping = FileMappedModel.objects.filter(file_import_session=session).first()
        selected_models = []
        auto_included_models = []
        
        if existing_mapping and existing_mapping.client_app_model_name:
            # Get user-selected models (stored in DB)
            selected_models = existing_mapping.client_app_model_name
            # Calculate auto-included parent models
            complete_info = ModelHierarchyService.get_models_with_parent_chain(selected_models)
            auto_included_models = complete_info['auto_included']
        
        # Create form choices (all models)
        model_choices = [
            (model_name, f"{model_name} (Level {level})")
            for model_name, level in sorted(hierarchy.items(), key=lambda x: (x[1], x[0]))
        ]
        
        form = Step3ModelSelectionForm(
            model_choices=model_choices,
            initial={'selected_models': selected_models} if selected_models else None
        )
        
        # Get CSV headers for display
        csv_headers = []
        headers, rows, error = self.get_csv_data(session)
        if not error and headers:
            csv_headers = headers
        
        context = self.get_context_data(
            session=session,
            form=form,
            models_by_level=models_by_level,
            hierarchy=hierarchy,
            selected_models=selected_models,
            auto_included_models=auto_included_models,
            csv_headers=csv_headers,
        )
        
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        """
        Handle model selection and validate hierarchy.
        """
        session = self.get_session(session_id)
        
        # Get model hierarchy for form choices
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        model_choices = [
            (model_name, f"{model_name} (Level {level})")
            for model_name, level in sorted(hierarchy.items(), key=lambda x: (x[1], x[0]))
        ]
        
        form = Step3ModelSelectionForm(model_choices=model_choices, data=request.POST)
        
        if form.is_valid():
            selected_models = form.cleaned_data['selected_models']
            
            # Always ensure Patient model is included
            if 'Patient' not in selected_models:
                selected_models.insert(0, 'Patient')
            
            # Validate model selection using new hierarchy service method
            is_valid, error_message, level, complete_info = ModelHierarchyService.validate_model_selection_with_hierarchy(selected_models)
            
            if not is_valid:
                messages.error(request, f"Invalid model selection: {error_message}")
                
                # Re-render with error
                models_by_level = {}
                for model_name, lvl in sorted(hierarchy.items(), key=lambda x: (x[1], x[0])):
                    if lvl not in models_by_level:
                        models_by_level[lvl] = []
                    model_info = FieldIntrospectionService.get_model_display_info(model_name)
                    if model_info:
                        model_info['level'] = lvl
                        hierarchy_path = ModelHierarchyService.get_hierarchy_path(model_name)
                        model_info['hierarchy_path'] = hierarchy_path
                        models_by_level[lvl].append(model_info)
                
                context = self.get_context_data(
                    session=session,
                    form=form,
                    models_by_level=models_by_level,
                    hierarchy=hierarchy,
                    selected_models=selected_models,
                    auto_included_models=[],
                )
                return render(request, self.template_name, context)
            
            # Save only the user-selected models (not the auto-included parents)
            # The complete list with parents will be computed when needed
            FileMappedModel.objects.filter(file_import_session=session).delete()
            
            FileMappedModel.objects.create(
                file_import_session=session,
                client_app_model_name=selected_models  # Store user-selected models
            )
            
            # Update session step to 4 (next step) to allow access
            self.update_session_step(session, FileImportSessionStep.FIELD_MAPPING)
            
            # Show message with auto-included parent models
            auto_included = complete_info['auto_included']
            if auto_included:
                messages.success(
                    request,
                    f"Selected {len(selected_models)} model(s) at hierarchy level {level}. "
                    f"Parent models auto-included: {', '.join(auto_included)}"
                )
            else:
                messages.success(
                    request,
                    f"Selected {len(selected_models)} model(s) at hierarchy level {level}."
                )
            
            # Redirect to Step 4
            return redirect('data_import:step4', session_id=session.id)
        
        # Form is invalid
        models_by_level = {}
        for model_name, lvl in sorted(hierarchy.items(), key=lambda x: (x[1], x[0])):
            if lvl not in models_by_level:
                models_by_level[lvl] = []
            model_info = FieldIntrospectionService.get_model_display_info(model_name)
            if model_info:
                model_info['level'] = lvl
                hierarchy_path = ModelHierarchyService.get_hierarchy_path(model_name)
                model_info['hierarchy_path'] = hierarchy_path
                models_by_level[lvl].append(model_info)
        
        context = self.get_context_data(
            session=session,
            form=form,
            models_by_level=models_by_level,
            hierarchy=hierarchy,
            selected_models=[],
            auto_included_models=[],
        )
        return render(request, self.template_name, context)
