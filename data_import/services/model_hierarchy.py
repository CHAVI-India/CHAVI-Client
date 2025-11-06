"""Service to analyze and manage model hierarchy for UUID mapping"""
from typing import Dict, List, Set, Tuple
from django.apps import apps
from django.db import models
import logging

logger = logging.getLogger(__name__)


class ModelHierarchyService:
    """
    Service to analyze model relationships and determine required transitive dependencies.
    
    For example, if importing Immunohistochemistry data, the service will identify that
    Patient → Diagnosis → Pathology are all required.
    """
    
    # Root model for the hierarchy
    ROOT_MODEL = 'Patient'
    
    def __init__(self):
        # Import here to avoid circular imports
        from .field_introspection import FieldIntrospectionService
        self.field_service = FieldIntrospectionService()
        self.excluded_models = set(self.field_service.EXCLUDED_MODELS)
        
        self.client_app_models = self._get_client_app_models()
        self.model_relationships = self._build_relationship_map()
        
        # Build dynamic table <-> model name mappings
        self._table_to_model_map = {}
        self._model_to_table_map = {}
        for model_name, model in self.client_app_models.items():
            table_name = model._meta.db_table
            self._table_to_model_map[table_name] = model_name
            self._model_to_table_map[model_name] = table_name
    
    def _get_client_app_models(self) -> Dict[str, models.Model]:
        """Get all client_app models excluding the ones we don't import."""
        app_models = {}
        try:
            app_config = apps.get_app_config('client_app')
            for model in app_config.get_models():
                if model.__name__ not in self.excluded_models:
                    app_models[model.__name__] = model
        except Exception as e:
            logger.error(f"Error getting client_app models: {e}")
        return app_models
    
    def _build_relationship_map(self) -> Dict[str, List[str]]:
        """
        Build a map of model relationships (parent -> children).
        
        Returns:
            Dict mapping model names to their direct parent models via ForeignKey
        """
        relationships = {}
        
        for model_name, model in self.client_app_models.items():
            parent_models = []
            
            # Check all fields for ForeignKey relationships to other client_app models
            for field in model._meta.get_fields():
                if isinstance(field, models.ForeignKey):
                    related_model = field.related_model
                    
                    # Only consider relationships to client_app models (not lookup tables)
                    if (related_model._meta.app_label == 'client_app' and
                        related_model.__name__ in self.client_app_models):
                        parent_models.append(related_model.__name__)
            
            relationships[model_name] = parent_models
        
        return relationships
    
    def get_dependency_chain(self, model_name: str) -> List[str]:
        """
        Get the complete dependency chain for a model from root to the model.
        
        Args:
            model_name: Name of the model to get dependencies for
            
        Returns:
            List of model names in order from root (Patient) to the target model
            
        Example:
            get_dependency_chain('Immunohistochemistry') 
            -> ['Patient', 'Diagnosis', 'Pathology', 'Immunohistochemistry']
        """
        if model_name not in self.model_relationships:
            return []
        
        # Build path from model back to root
        path = [model_name]
        current = model_name
        visited = set()
        
        while current != self.ROOT_MODEL:
            if current in visited:
                logger.warning(f"Circular dependency detected for {model_name}")
                break
            visited.add(current)
            
            parents = self.model_relationships.get(current, [])
            if not parents:
                # No parent found, this might be a root-level model
                break
            
            # For models with multiple parents, prefer the primary path
            # (e.g., Pathology -> Diagnosis over other relationships)
            parent = self._select_primary_parent(current, parents)
            path.insert(0, parent)
            current = parent
        
        # Ensure Patient is at the root if not already
        if path and path[0] != self.ROOT_MODEL:
            path.insert(0, self.ROOT_MODEL)
        
        return path
    
    def _select_primary_parent(self, model_name: str, parents: List[str]) -> str:
        """
        Select the primary parent when a model has multiple ForeignKeys.
        
        Prioritizes the main hierarchical relationship (e.g., Diagnosis over others).
        """
        # Priority order for parent selection
        priority_parents = ['Patient', 'Diagnosis', 'Pathology', 'Lesion', 
                          'Radiotherapy', 'SystemicTherapy']
        
        for priority in priority_parents:
            if priority in parents:
                return priority
        
        # Default to first parent
        return parents[0]
    
    def get_required_models_for_import(self, mapped_tables: Set[str]) -> Dict[str, List[str]]:
        """
        Determine which models are required based on what tables have mapped fields.
        
        Args:
            mapped_tables: Set of table names that have fields mapped
            
        Returns:
            Dict with:
                - 'required': List of models that must have UUID mappings
                - 'dependency_chains': Dict mapping each required model to its dependency chain
                - 'missing': List of models in dependency chains that don't have mappings
        """
        required_models = set()
        dependency_chains = {}
        
        # For each mapped table, get its full dependency chain
        for table_name in mapped_tables:
            # Convert table name to model name (e.g., 'diagnosis' -> 'Diagnosis')
            model_name = self._table_to_model_name(table_name)
            
            if model_name in self.client_app_models:
                chain = self.get_dependency_chain(model_name)
                dependency_chains[model_name] = chain
                required_models.update(chain)
        
        # Determine which required models don't have mappings yet
        missing_models = []
        for model in required_models:
            table_name = self._model_to_table_name(model)
            if table_name not in mapped_tables:
                missing_models.append(model)
        
        return {
            'required': sorted(list(required_models)),
            'dependency_chains': dependency_chains,
            'missing': sorted(missing_models)
        }
    
    def _table_to_model_name(self, table_name: str) -> str:
        """Convert database table name to model name using dynamic mapping."""
        return self._table_to_model_map.get(table_name, '')
    
    def _model_to_table_name(self, model_name: str) -> str:
        """Convert model name to database table name using dynamic mapping."""
        return self._model_to_table_map.get(model_name, '')
    
    def get_model_display_info(self, model_name: str) -> Dict:
        """
        Get display information for a model.
        
        Returns:
            Dict with verbose_name, help_text, and primary_key_field
        """
        if model_name not in self.client_app_models:
            return {}
        
        model = self.client_app_models[model_name]
        pk_field = model._meta.pk
        
        return {
            'model_name': model_name,
            'verbose_name': model._meta.verbose_name,
            'verbose_name_plural': model._meta.verbose_name_plural,
            'table_name': model._meta.db_table,
            'pk_field_name': pk_field.name,
            'pk_field_type': pk_field.get_internal_type(),
            'help_text': model.__doc__ or ''
        }
    
    def build_hierarchical_structure(self, required_models: List[str]) -> List[Dict]:
        """
        Build a hierarchical tree structure for display in the UI.
        
        Args:
            required_models: List of model names that are required
            
        Returns:
            List of dicts representing the tree structure with levels
        """
        tree = []
        processed = set()
        
        def add_model_and_children(model_name: str, level: int = 0, parent_chain: List[str] = None):
            if parent_chain is None:
                parent_chain = []
            
            if model_name in processed:
                return
            
            processed.add(model_name)
            
            # Add this model to the tree
            model_info = self.get_model_display_info(model_name)
            model_info['level'] = level
            model_info['parent_chain'] = parent_chain.copy()
            model_info['is_required'] = model_name in required_models
            tree.append(model_info)
            
            # Find and add children
            children = [m for m, parents in self.model_relationships.items() 
                       if model_name in parents and m in required_models]
            
            for child in sorted(children):
                new_chain = parent_chain + [model_name]
                add_model_and_children(child, level + 1, new_chain)
        
        # Start from Patient (root)
        if self.ROOT_MODEL in required_models:
            add_model_and_children(self.ROOT_MODEL)
        
        return tree
    
    def get_child_models(self, model_name: str) -> Dict[str, str]:
        """
        Get direct child models for a given parent model.
        
        Args:
            model_name: Name of the parent model
            
        Returns:
            Dict mapping child table_name -> pk_field_name
            Example: {'pathology': 'pathology_id', 'treatment': 'treatment_id'}
        """
        children = {}
        
        # Find all models that have this model as a parent
        for child_model_name, parents in self.model_relationships.items():
            if model_name in parents:
                child_model = self.client_app_models.get(child_model_name)
                if child_model:
                    table_name = child_model._meta.db_table
                    pk_field_name = child_model._meta.pk.name
                    children[table_name] = pk_field_name
        
        return children
