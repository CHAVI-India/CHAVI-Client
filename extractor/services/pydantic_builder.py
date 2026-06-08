from typing import Dict, List, Any, Optional
from extractor.models import ResponseModel, ResponseModelTable, ResponseModelTableField, DatabaseField, EntityTypeChoices
from logging import getLogger
import ast
import sys
from io import StringIO
import traceback

log = getLogger(__name__)


class PydanticModelBuilder:
    """
    Service to build Pydantic model code from ResponseModel configuration.
    """
    
    TYPE_MAPPING = {
        EntityTypeChoices.STRING: 'str',
        EntityTypeChoices.BOOLEAN: 'bool',
        EntityTypeChoices.FLOAT: 'float',
        EntityTypeChoices.INTEGER: 'int',
        EntityTypeChoices.DICTIONARY: 'Dict[str, Any]',
        EntityTypeChoices.TUPLE: 'Tuple',
        EntityTypeChoices.LIST: 'List[str]',
        EntityTypeChoices.DATE: 'date',
        EntityTypeChoices.DATETIME: 'datetime',
        EntityTypeChoices.TIMEDELTA: 'timedelta',
        EntityTypeChoices.TIME: 'time',
    }
    
    @classmethod
    def build_pydantic_model(cls, response_model: ResponseModel) -> str:
        """
        Generates Pydantic model code from a ResponseModel configuration.
        """
        model_tables = ResponseModelTable.objects.filter(
            response_model=response_model
        ).select_related('database_table__clientapp_content_type')
        
        if not model_tables.exists():
            raise ValueError("No tables configured for this response model")
        
        imports = cls._generate_imports()
        models_code = []
        
        for model_table in model_tables:
            model_code = cls._build_table_model(model_table)
            models_code.append(model_code)
        
        root_model = cls._build_root_model(response_model, model_tables)
        models_code.append(root_model)
        
        full_code = imports + "\n\n" + "\n\n".join(models_code)
        
        return full_code
    
    @classmethod
    def _generate_imports(cls) -> str:
        """
        Generates necessary imports for the Pydantic model.
        """
        return """from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Tuple
from datetime import date, datetime, time, timedelta
from enum import Enum"""
    
    @classmethod
    def _build_table_model(cls, model_table: ResponseModelTable) -> str:
        """
        Builds a Pydantic model for a single database table.
        """
        table_name = model_table.database_table.clientapp_content_type.model
        class_name = cls._to_class_name(table_name)
        
        fields = ResponseModelTableField.objects.filter(
            response_model_table=model_table
        ).select_related('field').order_by('order')
        
        if not fields.exists():
            raise ValueError(f"No fields configured for table {table_name}")
        
        field_definitions = []
        validators = []
        
        for field_config in fields:
            field_def, field_validator = cls._build_field_definition(field_config)
            field_definitions.append(field_def)
            if field_validator:
                validators.append(field_validator)
        
        fields_code = "\n    ".join(field_definitions)
        validators_code = "\n\n    ".join(validators) if validators else ""
        
        model_code = f"""class {class_name}(BaseModel):
    \"\"\"
    Extracted data for {table_name} table.
    \"\"\"
    {fields_code}"""
        
        if validators_code:
            model_code += f"\n\n    {validators_code}"
        
        return model_code
    
    @classmethod
    def _build_field_definition(cls, field_config: ResponseModelTableField) -> tuple:
        """
        Builds a field definition for Pydantic model.
        Returns (field_definition_str, validator_str)
        """
        db_field = field_config.field
        field_name = db_field.clientapp_field_name
        field_type = cls.TYPE_MAPPING.get(db_field.field_type, 'str')
        
        validation = db_field.field_validation or {}
        is_optional = validation.get('optional', False) or validation.get('nullable', False)
        
        if is_optional:
            field_type = f"Optional[{field_type}]"
        
        description = f"Field: {field_name}"
        if db_field.lookup_field:
            description += f" (Lookup: {db_field.lookup_content_type.model if db_field.lookup_content_type else 'Unknown'})"
        
        field_params = [f'description="{description}"']
        
        if 'max_length' in validation:
            field_params.append(f'max_length={validation["max_length"]}')
        
        default_value = "None" if is_optional else "..."
        
        field_def = f'{field_name}: {field_type} = Field({default_value}, {", ".join(field_params)})'
        
        validator_code = None
        if 'choices' in validation and validation['choices']:
            validator_code = cls._build_choice_validator(field_name, validation['choices'])
        elif 'min_value' in validation or 'max_value' in validation:
            validator_code = cls._build_range_validator(field_name, validation)
        
        return field_def, validator_code
    
    @classmethod
    def _build_choice_validator(cls, field_name: str, choices: List[str]) -> str:
        """
        Builds a validator for choice fields.
        """
        choices_str = ", ".join([f'"{choice}"' for choice in choices])
        return f"""@validator('{field_name}')
    def validate_{field_name}(cls, v):
        if v is not None and v not in [{choices_str}]:
            raise ValueError(f'{{v}} is not a valid choice for {field_name}')
        return v"""
    
    @classmethod
    def _build_range_validator(cls, field_name: str, validation: Dict) -> str:
        """
        Builds a validator for numeric range fields.
        """
        checks = []
        if 'min_value' in validation:
            checks.append(f"v < {validation['min_value']}")
        if 'max_value' in validation:
            checks.append(f"v > {validation['max_value']}")
        
        if not checks:
            return None
        
        condition = " or ".join(checks)
        return f"""@validator('{field_name}')
    def validate_{field_name}(cls, v):
        if v is not None and ({condition}):
            raise ValueError(f'{{v}} is out of valid range for {field_name}')
        return v"""
    
    @classmethod
    def _build_root_model(cls, response_model: ResponseModel, model_tables) -> str:
        """
        Builds the root Pydantic model that contains all table models.
        """
        root_class_name = cls._to_class_name(response_model.name)
        
        field_definitions = []
        for model_table in model_tables:
            table_name = model_table.database_table.clientapp_content_type.model
            class_name = cls._to_class_name(table_name)
            field_name = cls._to_field_name(table_name)
            
            field_def = f'{field_name}: Optional[List[{class_name}]] = Field(None, description="Extracted {table_name} records")'
            field_definitions.append(field_def)
        
        fields_code = "\n    ".join(field_definitions)
        
        return f"""class {root_class_name}(BaseModel):
    \"\"\"
    Root model for extraction: {response_model.name}
    \"\"\"
    {fields_code}"""
    
    @classmethod
    def _to_class_name(cls, name: str) -> str:
        """
        Converts a string to PascalCase class name.
        """
        return ''.join(word.capitalize() for word in name.replace('_', ' ').split())
    
    @classmethod
    def _to_field_name(cls, name: str) -> str:
        """
        Converts a string to snake_case field name.
        """
        return name.lower().replace(' ', '_')
    
    @classmethod
    def validate_model_configuration(cls, response_model: ResponseModel) -> Dict[str, Any]:
        """
        Validates that a ResponseModel configuration is complete and valid.
        """
        errors = []
        warnings = []
        
        model_tables = ResponseModelTable.objects.filter(response_model=response_model)
        
        if not model_tables.exists():
            errors.append("No tables configured for this response model")
            return {'valid': False, 'errors': errors, 'warnings': warnings}
        
        for model_table in model_tables:
            fields = ResponseModelTableField.objects.filter(response_model_table=model_table)
            
            if not fields.exists():
                errors.append(f"No fields configured for table {model_table.database_table}")
            
            for field in fields:
                if field.field.lookup_field:
                    if not field.field.lookup_content_type:
                        warnings.append(f"Lookup field {field.field.clientapp_field_name} missing lookup table configuration")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
    
    @classmethod
    def validate_generated_code(cls, code: str) -> Dict[str, Any]:
        """
        Validates that the generated Pydantic model code is syntactically correct
        and can be executed without errors.
        
        Returns:
            dict with keys: valid, errors, warnings, syntax_valid, runtime_valid
        """
        result = {
            'valid': False,
            'syntax_valid': False,
            'runtime_valid': False,
            'errors': [],
            'warnings': [],
            'test_results': {}
        }
        
        # Step 1: Syntax validation using AST
        try:
            ast.parse(code)
            result['syntax_valid'] = True
            log.info("Generated code passed syntax validation")
        except SyntaxError as e:
            result['errors'].append(f"Syntax error at line {e.lineno}: {e.msg}")
            log.error(f"Syntax validation failed: {e}")
            return result
        
        # Step 2: Runtime validation - try to execute the code
        try:
            # Create a clean namespace for execution
            namespace = {}
            exec(code, namespace)
            result['runtime_valid'] = True
            log.info("Generated code executed successfully")
            
            # Step 3: Find and test the root model class
            root_model_class = None
            for name, obj in namespace.items():
                if isinstance(obj, type) and hasattr(obj, '__mro__'):
                    # Check if it's a Pydantic BaseModel
                    if any('BaseModel' in str(base) for base in obj.__mro__):
                        # Assume the last defined model is the root
                        root_model_class = obj
            
            if root_model_class:
                # Step 4: Test instantiation with empty data
                try:
                    instance = root_model_class()
                    result['test_results']['empty_instantiation'] = 'success'
                    log.info(f"Successfully instantiated {root_model_class.__name__} with empty data")
                except Exception as e:
                    result['warnings'].append(f"Could not instantiate with empty data: {str(e)}")
                    result['test_results']['empty_instantiation'] = f'failed: {str(e)}'
                
                # Step 5: Test with sample data
                try:
                    sample_data = cls._generate_sample_data(root_model_class)
                    instance = root_model_class(**sample_data)
                    result['test_results']['sample_instantiation'] = 'success'
                    result['test_results']['sample_data'] = sample_data
                    log.info(f"Successfully instantiated {root_model_class.__name__} with sample data")
                except Exception as e:
                    result['warnings'].append(f"Could not instantiate with sample data: {str(e)}")
                    result['test_results']['sample_instantiation'] = f'failed: {str(e)}'
            else:
                result['warnings'].append("No Pydantic model class found in generated code")
                
        except Exception as e:
            result['errors'].append(f"Runtime error: {str(e)}")
            result['errors'].append(f"Traceback: {traceback.format_exc()}")
            log.error(f"Runtime validation failed: {e}")
            return result
        
        # Overall validation
        result['valid'] = result['syntax_valid'] and result['runtime_valid'] and len(result['errors']) == 0
        
        return result
    
    @classmethod
    def _generate_sample_data(cls, model_class) -> Dict[str, Any]:
        """
        Generates sample data for testing a Pydantic model.
        """
        sample_data = {}
        
        # Get model fields
        if hasattr(model_class, '__fields__'):
            for field_name, field_info in model_class.__fields__.items():
                # Generate sample value based on field type
                field_type = field_info.annotation
                
                # Handle Optional types
                if hasattr(field_type, '__origin__') and field_type.__origin__ is type(Optional[int]).__origin__:
                    # It's Optional, we can skip it or provide None
                    sample_data[field_name] = None
                    continue
                
                # Handle List types
                if hasattr(field_type, '__origin__'):
                    if field_type.__origin__ is list:
                        sample_data[field_name] = []
                    elif field_type.__origin__ is dict:
                        sample_data[field_name] = {}
                    else:
                        sample_data[field_name] = None
                else:
                    # Simple types
                    sample_data[field_name] = None
        
        return sample_data
    
    @classmethod
    def test_model_with_data(cls, code: str, test_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tests the generated Pydantic model with actual data.
        
        Args:
            code: Generated Pydantic model code
            test_data: Dictionary of test data to validate
            
        Returns:
            dict with validation results
        """
        result = {
            'valid': False,
            'errors': [],
            'warnings': [],
            'validated_data': None
        }
        
        try:
            # Execute the code to get the model class
            namespace = {}
            exec(code, namespace)
            
            # Find the root model class
            root_model_class = None
            for name, obj in namespace.items():
                if isinstance(obj, type) and hasattr(obj, '__mro__'):
                    if any('BaseModel' in str(base) for base in obj.__mro__):
                        root_model_class = obj
            
            if not root_model_class:
                result['errors'].append("No Pydantic model class found")
                return result
            
            # Try to validate the data
            try:
                instance = root_model_class(**test_data)
                result['valid'] = True
                result['validated_data'] = instance.dict()
                log.info(f"Successfully validated test data with {root_model_class.__name__}")
            except Exception as e:
                result['errors'].append(f"Validation failed: {str(e)}")
                log.error(f"Data validation failed: {e}")
                
        except Exception as e:
            result['errors'].append(f"Failed to execute model code: {str(e)}")
            log.error(f"Model execution failed: {e}")
        
        return result
