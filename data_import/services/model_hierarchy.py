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
