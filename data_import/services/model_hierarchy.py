"""
Service for determining model hierarchy based on FK relationships.
"""

from django.apps import apps
from django.db.models import ForeignKey


class ModelHierarchyService:
    """
    Dynamically determines model hierarchy based on FK relationships.
    """
    
    EXCLUDED_MODELS = [
        'PatientDicomFile', 'DICOMStudy', 'DICOMStudyProject',
        'BulkDICOMUpload', 'UnprocessedDICOMStudies',
        'BulkDICOMUploadSession', 'BulkDICOMStudyMatch'
    ]
    
    @staticmethod
    def get_model_hierarchy():
        """
        Returns dict mapping models to their hierarchy level.
        Level 0: Patient
        Level 1: Models with FK to Patient
        Level 2: Models with FK to Level 1 models, etc.
        
        Returns:
            dict: {model_name: level}
        """
        client_app = apps.get_app_config('client_app')
        models = [m for m in client_app.get_models() 
                  if m.__name__ not in ModelHierarchyService.EXCLUDED_MODELS]
        
        hierarchy = {}
        # Start with Patient at level 0
        patient_model = apps.get_model('client_app', 'Patient')
        hierarchy[patient_model.__name__] = 0
        
        # Iteratively assign levels
        max_iterations = 10
        for iteration in range(max_iterations):
            made_progress = False
            for model in models:
                if model.__name__ in hierarchy:
                    continue
                    
                # Check FK relationships
                fk_fields = [f for f in model._meta.get_fields() 
                            if isinstance(f, ForeignKey) and 
                            f.related_model._meta.app_label == 'client_app']
                
                for fk in fk_fields:
                    related_model_name = fk.related_model.__name__
                    if related_model_name in hierarchy:
                        current_level = hierarchy.get(model.__name__, float('inf'))
                        new_level = hierarchy[related_model_name] + 1
                        hierarchy[model.__name__] = min(current_level, new_level)
                        made_progress = True
            
            if not made_progress:
                break
        
        return hierarchy
    
    @staticmethod
    def get_models_at_level(level):
        """
        Returns list of model names at specified hierarchy level.
        
        Args:
            level (int): Hierarchy level
            
        Returns:
            list: Model names at the specified level
        """
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        return sorted([name for name, lvl in hierarchy.items() if lvl == level])
    
    @staticmethod
    def get_model_level(model_name):
        """
        Get the hierarchy level of a specific model.
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            int or None: Level of the model, or None if not found
        """
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        return hierarchy.get(model_name)
    
    @staticmethod
    def validate_model_selection(model_names):
        """
        Validates that all selected models are at the same hierarchy level.
        Patient model (level 0) is always allowed and excluded from level checking.
        
        Args:
            model_names (list): List of model names to validate
            
        Returns:
            tuple: (is_valid, error_message, level)
        """
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        
        # Separate Patient from other models
        other_models = [name for name in model_names if name != 'Patient']
        
        if not other_models:
            # Only Patient selected - this is valid (level 0)
            return True, None, 0
        
        # Get levels for non-Patient models
        levels = [hierarchy.get(name) for name in other_models if name in hierarchy]
        
        if not levels:
            return False, "No valid models selected", None
        
        # Check if all non-Patient models are at the same level
        unique_levels = set(levels)
        if len(unique_levels) > 1:
            level_info = {name: hierarchy.get(name) for name in other_models}
            return False, f"Selected models (excluding Patient) are at different hierarchy levels: {level_info}", None
        
        # Return the level of the non-Patient models
        return True, None, levels[0]
    
    @staticmethod
    def get_parent_models(model_name):
        """
        Get all parent models (FK relationships) for a given model.
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            dict: {field_name: parent_model_name}
        """
        try:
            model = apps.get_model('client_app', model_name)
            parents = {}
            
            for field in model._meta.get_fields():
                if isinstance(field, ForeignKey) and field.related_model._meta.app_label == 'client_app':
                    parents[field.name] = field.related_model.__name__
            
            return parents
        except LookupError:
            return {}
    
    @staticmethod
    def get_hierarchy_path(model_name):
        """
        Get the full hierarchy path from Patient to the given model.
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            list: Path from Patient to model (e.g., ['Patient', 'Diagnosis', 'Pathology'])
        """
        if model_name == 'Patient':
            return ['Patient']
        
        parents = ModelHierarchyService.get_parent_models(model_name)
        if not parents:
            return [model_name]
        
        # Find the path through the lowest level parent
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        lowest_parent = min(parents.values(), key=lambda p: hierarchy.get(p, float('inf')))
        
        parent_path = ModelHierarchyService.get_hierarchy_path(lowest_parent)
        return parent_path + [model_name]
    
    @staticmethod
    def get_all_parent_models(model_name):
        """
        Get all parent models in the hierarchy chain from Patient to the given model.
        Excludes the model itself.
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            list: All parent models in order from Patient to immediate parent
        """
        path = ModelHierarchyService.get_hierarchy_path(model_name)
        # Return all except the last element (which is the model itself)
        return path[:-1] if len(path) > 1 else []
    
    @staticmethod
    def get_models_with_parent_chain(selected_models):
        """
        Given a list of selected models, return the complete set including all parent models.
        Patient is always included.
        
        Args:
            selected_models (list): List of model names selected by user
            
        Returns:
            dict: {
                'all_models': list of all models including parents,
                'user_selected': list of models explicitly selected by user,
                'auto_included': list of parent models auto-included
            }
        """
        all_models_set = set()
        user_selected = set(selected_models)
        
        for model_name in selected_models:
            # Add the model itself
            all_models_set.add(model_name)
            # Add all its parents
            parents = ModelHierarchyService.get_all_parent_models(model_name)
            all_models_set.update(parents)
        
        # Patient is always included
        all_models_set.add('Patient')
        
        auto_included = all_models_set - user_selected
        
        # Sort by hierarchy level
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        all_models_sorted = sorted(all_models_set, key=lambda m: hierarchy.get(m, float('inf')))
        
        return {
            'all_models': all_models_sorted,
            'user_selected': list(user_selected),
            'auto_included': sorted(auto_included, key=lambda m: hierarchy.get(m, float('inf')))
        }
    
    @staticmethod
    def validate_model_selection_with_hierarchy(model_names):
        """
        Validates that selected models are at the same hierarchy level.
        Returns the complete model set including parent models.
        
        Args:
            model_names (list): List of model names selected by user
            
        Returns:
            tuple: (is_valid, error_message, level, complete_model_info)
                where complete_model_info is the dict from get_models_with_parent_chain
        """
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        
        # Separate Patient from other models
        other_models = [name for name in model_names if name != 'Patient']
        
        if not other_models:
            # Only Patient selected - this is valid (level 0)
            return True, None, 0, {
                'all_models': ['Patient'],
                'user_selected': ['Patient'],
                'auto_included': []
            }
        
        # Get levels for non-Patient models
        levels = [hierarchy.get(name) for name in other_models if name in hierarchy]
        
        if not levels:
            return False, "No valid models selected", None, None
        
        # Check if all non-Patient models are at the same level
        unique_levels = set(levels)
        if len(unique_levels) > 1:
            level_info = {name: hierarchy.get(name) for name in other_models}
            return False, f"Selected models (excluding Patient) are at different hierarchy levels: {level_info}", None, None
        
        # Get complete model set with parent chain
        complete_info = ModelHierarchyService.get_models_with_parent_chain(model_names)
        
        # Return the level of the non-Patient models
        return True, None, levels[0], complete_info
    
    @staticmethod
    def get_complete_model_list(user_selected_models):
        """
        Given a list of user-selected models, return the complete list including all parent models.
        This is a convenience method for use in views that need the complete model set.
        
        Args:
            user_selected_models (list): List of model names selected by user
            
        Returns:
            list: Complete list of models including parents, sorted by hierarchy level
        """
        complete_info = ModelHierarchyService.get_models_with_parent_chain(user_selected_models)
        return complete_info['all_models']
