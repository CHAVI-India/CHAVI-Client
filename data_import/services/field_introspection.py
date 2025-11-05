"""
Service for introspecting Django models and extracting field information
for the data import wizard.
"""
from django.apps import apps
from django.db import models
from django.core import validators
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class FieldIntrospectionService:
    """
    Service to introspect client_app models and extract field metadata
    for matching with uploaded CSV/JSON files.
    """
    
    # Fields to exclude from import (auto-generated)
    EXCLUDED_FIELDS = ['created_at', 'updated_at', 'id']
    
    # Tables/Models to exclude from field selection
    EXCLUDED_MODELS = [
        'SiteConfiguration',
        'Project',  # Already selected in step 1
        'PatientDICOMFile',
        'DICOMStudy',
        'DICOMStudyProject',
        'BulkDICOMUpload',
        'UnprocessedDICOMStudies',
        'BulkDICOMUploadSession',
        'BulkDICOMStudyMatch',
    ]
    
    def __init__(self):
        self.client_app_models = self._get_client_app_models()
        self.lookup_app_models = self._get_lookup_app_models()
        self._field_cache = None
        
    def _get_client_app_models(self) -> Dict[str, models.Model]:
        """Get all models from client_app."""
        try:
            app_config = apps.get_app_config('client_app')
            return {model.__name__: model for model in app_config.get_models()}
        except Exception as e:
            logger.error(f"Error getting client_app models: {e}")
            return {}
    
    def _get_lookup_app_models(self) -> Dict[str, models.Model]:
        """Get all models from lookup app."""
        try:
            app_config = apps.get_app_config('lookup')
            return {model.__name__: model for model in app_config.get_models()}
        except Exception as e:
            logger.error(f"Error getting lookup app models: {e}")
            return {}
    
    def get_all_fields(self, use_cache: bool = True) -> List[Dict]:
        """
        Get all fields from all client_app models with metadata.
        
        Args:
            use_cache: Whether to use cached results
            
        Returns:
            List of dictionaries containing field information
        """
        if use_cache and self._field_cache:
            return self._field_cache
            
        all_fields = []
        
        for model_name, model in self.client_app_models.items():
            # Skip excluded models
            if model_name in self.EXCLUDED_MODELS:
                continue
            
            # Skip abstract models
            if model._meta.abstract:
                continue
                
            table_name = model._meta.db_table
            
            for field in model._meta.get_fields():
                # Skip reverse relations and excluded fields
                if field.auto_created and not field.concrete:
                    continue
                    
                if field.name in self.EXCLUDED_FIELDS:
                    continue
                    
                # Skip auto-generated UUID primary keys
                if isinstance(field, models.UUIDField) and field.primary_key:
                    continue
                    
                field_info = self._extract_field_info(model_name, table_name, field)
                if field_info:
                    all_fields.append(field_info)
        
        self._field_cache = all_fields
        return all_fields
    
    def _extract_field_info(self, model_name: str, table_name: str, field) -> Optional[Dict]:
        """
        Extract comprehensive metadata for a single field.
        
        Args:
            model_name: Name of the model
            table_name: Database table name
            field: Django field object
            
        Returns:
            Dictionary with field metadata or None if field should be skipped
        """
        try:
            field_info = {
                'model_name': model_name,
                'table_name': table_name,
                'field_name': field.name,
                'verbose_name': str(field.verbose_name) if hasattr(field, 'verbose_name') else field.name,
                'help_text': str(field.help_text) if hasattr(field, 'help_text') else '',
                'field_class': field.__class__.__name__,
                'internal_type': field.get_internal_type() if hasattr(field, 'get_internal_type') else 'Unknown',
                'data_type': self._get_field_data_type(field),
                
                # Constraints
                'is_required': self._is_field_required(field),
                'null': getattr(field, 'null', False),
                'blank': getattr(field, 'blank', False),
                'unique': getattr(field, 'unique', False),
                'primary_key': getattr(field, 'primary_key', False),
                
                # Size constraints
                'max_length': getattr(field, 'max_length', None),
                'max_digits': getattr(field, 'max_digits', None),
                'decimal_places': getattr(field, 'decimal_places', None),
                
                # Default value
                'has_default': field.has_default() if hasattr(field, 'has_default') else False,
                'default': self._get_default_value(field),
                
                # Relationship info
                'is_foreign_key': isinstance(field, models.ForeignKey),
                'is_many_to_many': isinstance(field, models.ManyToManyField),
                'related_model': None,
                'related_table': None,
                'related_app': None,
                'is_lookup': False,
                'lookup_model': None,
                
                # Choices
                'has_choices': False,
                'choices': [],
                
                # Validators
                'validators': self._extract_validators(field),
            }
            
            # Handle relationships
            if isinstance(field, (models.ForeignKey, models.ManyToManyField)):
                self._add_relationship_info(field_info, field)
            
            # Handle choices
            if hasattr(field, 'choices') and field.choices:
                field_info['has_choices'] = True
                field_info['choices'] = [
                    {'value': str(choice[0]), 'display': str(choice[1])} 
                    for choice in field.choices
                ]
            
            return field_info
            
        except Exception as e:
            logger.error(f"Error extracting field info for {model_name}.{field.name}: {e}")
            return None
    
    def _get_field_data_type(self, field) -> str:
        """Map Django field types to validation data types."""
        if isinstance(field, (models.CharField, models.TextField)):
            return 'String'
        elif isinstance(field, models.IntegerField):
            return 'Integer'
        elif isinstance(field, (models.DecimalField, models.FloatField)):
            return 'Float'
        elif isinstance(field, models.BooleanField):
            return 'Boolean'
        elif isinstance(field, models.DateField):
            return 'Date'
        elif isinstance(field, models.DateTimeField):
            return 'DateTime'
        elif isinstance(field, models.TimeField):
            return 'Time'
        elif isinstance(field, models.UUIDField):
            return 'UUID'
        elif isinstance(field, models.ForeignKey):
            return 'ForeignKey'
        elif isinstance(field, models.ManyToManyField):
            return 'ManyToMany'
        elif isinstance(field, models.JSONField):
            return 'JSON'
        else:
            return 'String'
    
    def _is_field_required(self, field) -> bool:
        """Determine if a field is required."""
        # Primary keys are not required for import (auto-generated)
        if getattr(field, 'primary_key', False):
            return False
        
        # Fields with defaults are not required
        if hasattr(field, 'has_default') and field.has_default():
            return False
            
        # Check null and blank
        null = getattr(field, 'null', False)
        blank = getattr(field, 'blank', False)
        
        return not (null or blank)
    
    def _get_default_value(self, field):
        """Get the default value for a field."""
        if not hasattr(field, 'has_default') or not field.has_default():
            return None
        
        default = field.default
        if callable(default):
            return None  # Don't try to call it
        
        return str(default) if default is not None else None
    
    def _add_relationship_info(self, field_info: Dict, field) -> None:
        """Add relationship information to field_info."""
        try:
            related_model = field.related_model
            field_info['related_model'] = related_model.__name__
            field_info['related_table'] = related_model._meta.db_table
            field_info['related_app'] = related_model._meta.app_label
            
            # Check if it's a lookup table
            if related_model._meta.app_label == 'lookup':
                field_info['is_lookup'] = True
                field_info['lookup_model'] = related_model.__name__
                
            # Add on_delete info for ForeignKey
            if isinstance(field, models.ForeignKey):
                field_info['on_delete'] = field.remote_field.on_delete.__name__
                
        except Exception as e:
            logger.error(f"Error adding relationship info: {e}")
    
    def _extract_validators(self, field) -> List[Dict]:
        """Extract validator information from a field."""
        field_validators = []
        
        if not hasattr(field, 'validators'):
            return field_validators
        
        # Detect custom validator patterns from client_app.models
        validator_list = field.validators
        
        # Check for percentage_validator pattern (MinValue 0, MaxValue 100)
        if self._is_percentage_validator(validator_list):
            field_validators.append({'type': 'percentage_validator'})
        
        # Check for positive_decimal_validator pattern (MinValue 0)
        elif self._is_positive_decimal_validator(validator_list):
            field_validators.append({'type': 'positive_decimal_validator'})
        
        # Check for allred_score_validator pattern (MinValue 0, MaxValue 8)
        elif self._is_allred_score_validator(validator_list):
            field_validators.append({'type': 'allred_score_validator'})
        
        # Extract standard validators
        for validator in validator_list:
            validator_info = {
                'type': validator.__class__.__name__,
            }
            
            try:
                if isinstance(validator, validators.MinValueValidator):
                    validator_info['min_value'] = str(validator.limit_value)
                elif isinstance(validator, validators.MaxValueValidator):
                    validator_info['max_value'] = str(validator.limit_value)
                elif isinstance(validator, validators.MinLengthValidator):
                    validator_info['min_length'] = validator.limit_value
                elif isinstance(validator, validators.MaxLengthValidator):
                    validator_info['max_length'] = validator.limit_value
                elif isinstance(validator, validators.RegexValidator):
                    validator_info['regex'] = validator.regex.pattern
                    validator_info['message'] = validator.message
                elif isinstance(validator, validators.EmailValidator):
                    validator_info['email'] = True
                elif isinstance(validator, validators.URLValidator):
                    validator_info['url'] = True
                elif isinstance(validator, validators.FileExtensionValidator):
                    validator_info['allowed_extensions'] = validator.allowed_extensions
                    
                field_validators.append(validator_info)
                
            except Exception as e:
                logger.error(f"Error extracting validator info: {e}")
                continue
        
        return field_validators
    
    def _is_percentage_validator(self, validator_list) -> bool:
        """Check if validator list matches percentage_validator pattern (0-100)."""
        from decimal import Decimal
        has_min_0 = False
        has_max_100 = False
        
        for v in validator_list:
            if isinstance(v, validators.MinValueValidator):
                if v.limit_value == Decimal('0.0') or v.limit_value == 0:
                    has_min_0 = True
            if isinstance(v, validators.MaxValueValidator):
                if v.limit_value == Decimal('100.0') or v.limit_value == 100:
                    has_max_100 = True
        
        return has_min_0 and has_max_100
    
    def _is_positive_decimal_validator(self, validator_list) -> bool:
        """Check if validator list matches positive_decimal_validator pattern (>= 0)."""
        from decimal import Decimal
        
        # Must have MinValue 0 and NOT have MaxValue 100 (to distinguish from percentage)
        has_min_0 = False
        has_max_100 = False
        
        for v in validator_list:
            if isinstance(v, validators.MinValueValidator):
                if v.limit_value == Decimal('0.0') or v.limit_value == 0:
                    has_min_0 = True
            if isinstance(v, validators.MaxValueValidator):
                if v.limit_value == Decimal('100.0') or v.limit_value == 100:
                    has_max_100 = True
        
        return has_min_0 and not has_max_100
    
    def _is_allred_score_validator(self, validator_list) -> bool:
        """Check if validator list matches allred_score_validator pattern (0-8)."""
        has_min_0 = False
        has_max_8 = False
        
        for v in validator_list:
            if isinstance(v, validators.MinValueValidator):
                if str(v.limit_value) == '0':
                    has_min_0 = True
            if isinstance(v, validators.MaxValueValidator):
                if str(v.limit_value) == '8':
                    has_max_8 = True
        
        return has_min_0 and has_max_8
    
    def get_fields_by_model(self, model_name: str) -> List[Dict]:
        """Get all fields for a specific model."""
        all_fields = self.get_all_fields()
        return [f for f in all_fields if f['model_name'] == model_name]
    
    def get_field(self, table_name: str, field_name: str) -> Optional[Dict]:
        """Get a specific field by table name and field name."""
        all_fields = self.get_all_fields()
        for field in all_fields:
            if field['table_name'] == table_name and field['field_name'] == field_name:
                return field
        return None
    
    def get_lookup_fields(self) -> List[Dict]:
        """Get all fields that reference lookup tables."""
        all_fields = self.get_all_fields()
        return [f for f in all_fields if f['is_lookup']]
    
    def get_relationship_fields(self) -> List[Dict]:
        """Get all FK and M2M fields."""
        all_fields = self.get_all_fields()
        return [f for f in all_fields if f['is_foreign_key'] or f['is_many_to_many']]
    
    def get_lookup_table_values(self, lookup_model_name: str) -> List[Dict]:
        """
        Get all values from a lookup table.
        
        Args:
            lookup_model_name: Name of the lookup model
            
        Returns:
            List of dictionaries with lookup values
        """
        if lookup_model_name not in self.lookup_app_models:
            return []
        
        model = self.lookup_app_models[lookup_model_name]
        values = []
        
        try:
            # Get all instances
            for instance in model.objects.all():
                value_dict = {
                    'pk': str(instance.pk),
                }
                
                # Try to get common fields
                for field_name in ['code', 'name', 'description', 'value']:
                    if hasattr(instance, field_name):
                        value_dict[field_name] = str(getattr(instance, field_name))
                
                # Get string representation
                value_dict['str'] = str(instance)
                
                values.append(value_dict)
                
        except Exception as e:
            logger.error(f"Error getting lookup values for {lookup_model_name}: {e}")
        
        return values
    
    def clear_cache(self):
        """Clear the field cache."""
        self._field_cache = None
