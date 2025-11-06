"""
Service for introspecting model fields and metadata.
"""

from django.apps import apps
from django.db.models import (
    ForeignKey, ManyToManyField, CharField, TextField,
    IntegerField, DecimalField, DateField, DateTimeField,
    BooleanField, UUIDField, AutoField
)


class FieldIntrospectionService:
    """
    Provides field metadata for client_app models.
    """
    
    @staticmethod
    def get_model_fields(model_name, exclude_auto=True):
        """
        Returns dict of field metadata for a model.
        
        Args:
            model_name (str): Name of the model
            exclude_auto (bool): Exclude auto-generated fields
            
        Returns:
            dict: Field metadata
        """
        try:
            model = apps.get_model('client_app', model_name)
        except LookupError:
            return {}
        
        fields_info = {}
        exclude_fields = ['created_at', 'updated_at'] if exclude_auto else []
        
        for field in model._meta.get_fields():
            # Skip reverse relations (OneToOneRel, ManyToOneRel, ManyToManyRel)
            if field.auto_created and not field.concrete:
                continue
            
            if field.name in exclude_fields:
                continue
            
            # Skip auto fields if requested
            if exclude_auto and isinstance(field, (AutoField, UUIDField)) and field.primary_key:
                continue
                
            field_info = {
                'name': field.name,
                'type': field.get_internal_type(),
                'verbose_name': getattr(field, 'verbose_name', field.name),
                'help_text': getattr(field, 'help_text', ''),
                'required': not getattr(field, 'blank', True),
                'null': getattr(field, 'null', False),
                'max_length': getattr(field, 'max_length', None),
                'choices': getattr(field, 'choices', None),
                'default': getattr(field, 'default', None),
            }
            
            # Handle relationships
            if isinstance(field, ForeignKey):
                field_info['related_model'] = field.related_model.__name__
                field_info['related_app'] = field.related_model._meta.app_label
                field_info['is_lookup'] = field.related_model._meta.app_label == 'lookup'
                field_info['is_fk'] = True
            elif isinstance(field, ManyToManyField):
                field_info['related_model'] = field.related_model.__name__
                field_info['related_app'] = field.related_model._meta.app_label
                field_info['is_m2m'] = True
            
            fields_info[field.name] = field_info
        
        return fields_info
    
    @staticmethod
    def get_date_fields(model_name):
        """
        Returns list of date/datetime field names for a model.
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            list: Date field names
        """
        try:
            model = apps.get_model('client_app', model_name)
            return [f.name for f in model._meta.get_fields() 
                    if isinstance(f, (DateField, DateTimeField)) and 
                    f.name not in ['created_at', 'updated_at']]
        except LookupError:
            return []
    
    @staticmethod
    def get_fk_fields(model_name):
        """
        Returns dict of FK field names and their related models.
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            dict: {field_name: related_model_name}
        """
        try:
            model = apps.get_model('client_app', model_name)
            return {f.name: f.related_model.__name__ 
                    for f in model._meta.get_fields() 
                    if isinstance(f, ForeignKey)}
        except LookupError:
            return {}
    
    @staticmethod
    def get_lookup_fields(model_name):
        """
        Returns dict of fields that reference lookup tables.
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            dict: {field_name: lookup_model_name}
        """
        try:
            model = apps.get_model('client_app', model_name)
            lookup_fields = {}
            
            for field in model._meta.get_fields():
                if isinstance(field, (ForeignKey, ManyToManyField)):
                    if field.related_model._meta.app_label == 'lookup':
                        lookup_fields[field.name] = field.related_model.__name__
            
            return lookup_fields
        except LookupError:
            return {}
    
    @staticmethod
    def get_required_fields(model_name):
        """
        Returns list of required field names (not blank, not null).
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            list: Required field names
        """
        try:
            model = apps.get_model('client_app', model_name)
            required = []
            
            for field in model._meta.get_fields():
                # Skip reverse relations
                if hasattr(field, 'related_name') and field.related_name and not isinstance(field, (ForeignKey, ManyToManyField)):
                    continue
                
                # Skip auto fields
                if isinstance(field, (AutoField, UUIDField)) and field.primary_key:
                    continue
                
                if not getattr(field, 'blank', True) or not getattr(field, 'null', True):
                    required.append(field.name)
            
            return required
        except LookupError:
            return []
    
    @staticmethod
    def get_field_widget_type(field_info):
        """
        Determine appropriate HTML widget type for a field.
        
        Args:
            field_info (dict): Field metadata
            
        Returns:
            str: Widget type (e.g., 'text', 'select', 'date', 'checkbox')
        """
        field_type = field_info.get('type')
        
        if field_info.get('choices'):
            return 'select'
        elif field_info.get('is_fk') or field_info.get('is_m2m'):
            return 'select'
        elif field_type in ['DateField', 'DateTimeField']:
            return 'date'
        elif field_type == 'BooleanField':
            return 'checkbox'
        elif field_type in ['IntegerField', 'PositiveIntegerField', 'BigIntegerField']:
            return 'number'
        elif field_type == 'DecimalField':
            return 'number'
        elif field_type == 'TextField':
            return 'textarea'
        else:
            return 'text'
    
    @staticmethod
    def get_model_display_info(model_name):
        """
        Get display information for a model including name, verbose name, and field count.
        
        Args:
            model_name (str): Name of the model
            
        Returns:
            dict: Display information
        """
        try:
            model = apps.get_model('client_app', model_name)
            fields = FieldIntrospectionService.get_model_fields(model_name)
            
            return {
                'name': model_name,
                'verbose_name': model._meta.verbose_name,
                'verbose_name_plural': model._meta.verbose_name_plural,
                'doc': model.__doc__,
                'field_count': len(fields),
                'fields': fields,
            }
        except LookupError:
            return {}
