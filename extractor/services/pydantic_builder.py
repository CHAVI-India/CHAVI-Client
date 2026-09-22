from typing import Annotated, Dict, List, Any, Optional, Literal
from inspect import getsource
from extractor.models import ResponseModel, ResponseModelTable, ResponseModelTableField, DatabaseField, EntityTypeChoices
from extractor.services.model_hierarchy import (
    build_table_tree, child_key, ancestor_tables, identity_field_names)
from logging import getLogger
from decimal import Decimal
import ast
import re
import sys
from io import StringIO
import traceback
from datetime import date as _date
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, create_model, field_validator, model_validator

log = getLogger(__name__)


class FieldAssessment(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    field: str
    basis: Literal['explicit', 'inferred', 'clinical_inference', 'calculated', 'unknown']
    quotes: List[Annotated[str, Field(min_length=1, max_length=400)]] = Field(max_length=3)
    rationale: str = Field(max_length=400)


def supports_field_assessment(db_field: DatabaseField) -> bool:
    return (db_field.is_active and db_field.is_extractable() and not db_field.lookup_field
            and db_field.field_type in (
                EntityTypeChoices.INTEGER, EntityTypeChoices.FLOAT, EntityTypeChoices.BOOLEAN))


def validate_field_assessments(values, assessments, field_types, source_text=None):
    names = [entry.field for entry in assessments]
    if len(names) != len(set(names)) or set(names) != set(field_types):
        raise ValueError('Provide exactly one field assessment for each configured numeric or boolean field.')
    for entry in assessments:
        value = values.get(entry.field)
        kind = field_types[entry.field]
        if entry.basis == 'unknown':
            if value is not None:
                raise ValueError(f'{entry.field}: unknown requires a null value.')
        elif value is None:
            raise ValueError(f'{entry.field}: unknown requires a null value.')
        if entry.basis != 'explicit' and not entry.rationale.strip():
            raise ValueError(f'{entry.field}: explain the inference briefly.')
        if (value is not None and entry.basis == 'explicit' and not entry.quotes) or \
                (value is None and entry.basis != 'unknown' and not (entry.quotes or entry.rationale.strip())):
            raise ValueError(f'{entry.field}: provide supporting evidence or a concise reason.')
        if entry.basis in ('inferred', 'clinical_inference'):
            valid = value is False if kind == 'bool' else value == 0 and not isinstance(value, bool)
            if not valid:
                raise ValueError(f'{entry.field}: inferred values must be numeric zero or boolean false.')
        if entry.basis == 'calculated' and kind == 'bool':
            raise ValueError(f'{entry.field}: calculated values must be numeric.')
        for quote in entry.quotes:
            if not quote.strip() or (source_text is not None and quote.strip() not in source_text):
                raise ValueError(f'{entry.field}: copy a supporting quotation verbatim from the document.')


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

    # Python types used for the live extraction model. Date/time stay str so
    # the LLM answers in a documented format rather than failing coercion.
    TYPE_TO_PYTHON = {
        EntityTypeChoices.STRING: str,
        EntityTypeChoices.BOOLEAN: bool,
        EntityTypeChoices.FLOAT: float,
        EntityTypeChoices.INTEGER: int,
        EntityTypeChoices.DICTIONARY: Dict[str, Any],
        EntityTypeChoices.TUPLE: List[str],
        EntityTypeChoices.LIST: List[str],
        EntityTypeChoices.DATE: str,
        EntityTypeChoices.DATETIME: str,
        EntityTypeChoices.TIMEDELTA: str,
        EntityTypeChoices.TIME: str,
    }

    # Key under which per-job lookup constraints are passed via instructor's
    # validation context (see InstructorExtractionService.build_lookup_rules).
    LOOKUP_CONTEXT_KEY = 'lookup_rules'

    @classmethod
    def _lookup_membership_validator(cls, rule_key: str):
        """
        Field-validator factory: reject extracted labels that are not known
        lookup options so instructor re-asks with the error. Allowed labels
        arrive per-job via validation context; without a matching rule the
        check is a no-op, keeping the wizard preview unconstrained.
        """
        def check(v, info: ValidationInfo):
            if v is None:
                return v
            rules = (info.context or {}).get(cls.LOOKUP_CONTEXT_KEY) or {}
            rule = rules.get(rule_key)
            if not rule:
                return v
            text = str(v).strip()
            if not text or text.lower() in rule['allowed']:
                return v
            hint = ''
            if rule.get('candidates'):
                hint = ' Closest valid options: ' + ', '.join(rule['candidates']) + '.'
            raise ValueError(
                f"'{text}' is not a known {rule_key} lookup option.{hint} "
                'Return one of the valid labels exactly, or null.')
        return check

    @staticmethod
    def _date_order_check(pairs, field_names):
        """
        Build a model-level validator enforcing start <= end for date pairs
        (the DateValidationMixin rule on the source models). Both fields must be
        among the extracted fields; unparseable dates are left for human review.
        """
        def check(self):
            for start_f, end_f in pairs:
                if start_f not in field_names or end_f not in field_names:
                    continue
                start_v = getattr(self, start_f, None)
                end_v = getattr(self, end_f, None)
                if not start_v or not end_v:
                    continue
                try:
                    start_d = _date.fromisoformat(str(start_v).strip())
                    end_d = _date.fromisoformat(str(end_v).strip())
                except ValueError:
                    continue
                if start_d > end_d:
                    raise ValueError(f"{start_f} '{start_v}' is after {end_f} '{end_v}'")
            return self
        return check

    @classmethod
    def _safe_identifier(cls, name: str, fallback: str = 'Model') -> str:
        """
        Make a valid Python/tool identifier: letters, digits, underscore,
        must start with a letter or underscore, max 60 chars.
        """
        cleaned = re.sub(r'[^0-9a-zA-Z_]', '_', str(name))
        cleaned = re.sub(r'^[^a-zA-Z_]+', '_', cleaned)
        return (cleaned or fallback)[:60]

    @classmethod
    def _field_annotation(cls, db_field: DatabaseField):
        """
        Resolve the annotation for a DatabaseField, honoring discovered
        validators (choices -> Literal, decimal -> Decimal, bounds -> Field
        constraints). Returns (annotation, field_info_kwargs).
        Raises ValueError for unknown field types.
        """
        field_type = db_field.field_type
        validation = db_field.field_validation or {}
        field_info = {}

        choices = validation.get('choices') or []
        if choices:
            annotation = Literal[tuple(choices)]
        elif validation.get('max_digits'):
            annotation = Decimal
            field_info['max_digits'] = validation['max_digits']
            if validation.get('decimal_places') is not None:
                field_info['decimal_places'] = validation['decimal_places']
        else:
            annotation = cls.TYPE_TO_PYTHON.get(field_type)
            if annotation is None:
                raise ValueError(
                    f"Unknown field type '{field_type}' for field "
                    f"'{db_field.clientapp_field_name}'"
                )

        if field_type in (EntityTypeChoices.INTEGER, EntityTypeChoices.FLOAT) or annotation is Decimal:
            if validation.get('min_value') is not None:
                field_info['ge'] = float(validation['min_value'])
            if validation.get('max_value') is not None:
                field_info['le'] = float(validation['max_value'])
        if validation.get('max_length') and annotation is str:
            field_info['max_length'] = validation['max_length']

        return annotation, field_info

    @staticmethod
    def _assessment_validator(field_types):
        def check(self, info: ValidationInfo):
            validate_field_assessments(
                {name: getattr(self, name) for name in field_types},
                self.field_assessments, field_types, (info.context or {}).get('source_text'))
            return self
        return check

    @staticmethod
    def _assessment_fields(fields, child_tables):
        names = {field.clientapp_field_name for field in fields}
        names.update(child_key(table.database_table) for table in child_tables)
        if 'field_assessments' in names:
            raise ValueError('field_assessments is reserved for extraction metadata.')
        return {field.clientapp_field_name: str(field.field_type)
                for field in fields if supports_field_assessment(field)}

    @classmethod
    def build_extraction_model(cls, response_model: ResponseModel, *, include_field_assessments=True):
        """
        Build the live Pydantic model used at extraction time — the single
        source of truth shared by the wizard preview and the runtime.

        Shape: { <table_snake>: [ {<field>: value, <child_table>: [ {...} ]}, ... ] }
        Child tables nest inside their parent record so the LLM reports which
        child records belong to which parent (e.g. pathology under its diagnosis).
        """
        if not ResponseModelTable.objects.filter(response_model=response_model).exists():
            raise ValueError("No tables configured for this response model")

        roots, children = build_table_tree(response_model)
        built = {}

        def build_node(model_table):
            if model_table.id in built:
                return built[model_table.id]
            table_name = model_table.database_table.clientapp_content_type.model
            table_fields = ResponseModelTableField.objects.filter(
                response_model_table=model_table,
                field__is_active=True,
            ).select_related('field', 'field__lookup_content_type').order_by('order')

            if not table_fields.exists():
                raise ValueError(f"No fields configured for table {table_name}")

            field_defs = {}
            validators = {}
            for table_field in table_fields:
                db_field = table_field.field
                if not db_field.is_extractable():
                    continue
                field_name = db_field.clientapp_field_name
                annotation, field_info = cls._field_annotation(db_field)

                description = f"{table_name}.{field_name}"
                if db_field.help_text:
                    description += f" — {db_field.help_text}"
                if db_field.lookup_field:
                    description += " (return the label of the closest matching option)"

                field_defs[field_name] = (
                    Optional[annotation],
                    Field(None, description=description, **field_info)
                )

                if db_field.lookup_field and db_field.lookup_content_type:
                    validators[f'check_lookup_{field_name}'] = field_validator(field_name)(
                        cls._lookup_membership_validator(
                            f'{table_name}.{field_name}'.lower()))

            for child_mt in children.get(model_table.id, []):
                child_cls = build_node(child_mt)
                child_name = child_mt.database_table.clientapp_content_type.model
                field_defs[child_key(child_mt.database_table)] = (
                    Optional[List[child_cls]],
                    Field(None, description=(
                        f"List of extracted {child_name} records belonging to this "
                        f"{table_name} record; [] if none"))
                )

            if include_field_assessments:
                assessment_fields = cls._assessment_fields(
                    [tf.field for tf in table_fields], children.get(model_table.id, []))
                if assessment_fields:
                    assessment_cls = create_model(
                        cls._safe_identifier(table_name) + 'FieldAssessment',
                        __base__=FieldAssessment,
                        field=(Literal[tuple(assessment_fields)], ...))
                    field_defs['field_assessments'] = (
                        List[assessment_cls], Field(description=(
                            'One evidence assessment for every configured numeric or boolean field, '
                            'including null values; belongs only to this record.')))
                    validators['check_field_assessments'] = model_validator(mode='after')(
                        cls._assessment_validator(assessment_fields))

            date_pairs = model_table.database_table.date_validation_pairs or []
            if date_pairs:
                validators['check_date_order'] = model_validator(mode='after')(
                    cls._date_order_check(date_pairs, set(field_defs.keys()))
                )

            table_cls = create_model(
                cls._safe_identifier(table_name, 'Table'),
                __validators__=validators,
                **field_defs
            )
            built[model_table.id] = table_cls
            return table_cls

        root_fields = {}
        for model_table in roots:
            table_cls = build_node(model_table)
            table_name = model_table.database_table.clientapp_content_type.model
            key = cls._to_field_name(table_name)
            root_fields[key] = (
                Optional[List[table_cls]],
                Field(None, description=f"List of extracted {table_name} records; one object per record, [] if none")
            )

        return create_model(
            cls._safe_identifier(response_model.name) + 'Model',
            **root_fields
        )

    @classmethod
    def build_pydantic_model(cls, response_model: ResponseModel, *, include_field_assessments=True) -> str:
        """
        Generates Pydantic model code from a ResponseModel configuration.
        """
        if not ResponseModelTable.objects.filter(response_model=response_model).exists():
            raise ValueError("No tables configured for this response model")

        roots, children = build_table_tree(response_model)

        imports = cls._generate_imports()
        if include_field_assessments:
            imports += '\n\n' + getsource(FieldAssessment) + '\n\n' + getsource(validate_field_assessments)
        models_code = []
        emitted = set()

        # Children are emitted before parents — parent classes reference the
        # child classes in their nested List[...] annotations.
        def emit(model_table):
            if model_table.id in emitted:
                return
            for child_mt in children.get(model_table.id, []):
                emit(child_mt)
            models_code.append(
                cls._build_table_model(model_table, children.get(model_table.id, []),
                                       include_field_assessments=include_field_assessments))
            emitted.add(model_table.id)

        for model_table in roots:
            emit(model_table)

        root_model = cls._build_root_model(response_model, roots)
        models_code.append(root_model)

        full_code = imports + "\n\n" + "\n\n".join(models_code)

        return full_code
    
    @classmethod
    def _generate_imports(cls) -> str:
        """
        Generates necessary imports for the Pydantic model.
        """
        return """from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator
from typing import Annotated, Optional, List, Dict, Any, Literal
from datetime import date
from decimal import Decimal"""
    
    @classmethod
    def _build_table_model(cls, model_table: ResponseModelTable, child_tables=None, *, include_field_assessments=True) -> str:
        """
        Builds a Pydantic model for a single database table.
        child_tables: ResponseModelTables nested inside each record.
        """
        table_name = model_table.database_table.clientapp_content_type.model
        # PascalCase: avoids field-name/class-name collisions in annotations
        class_name = cls._to_class_name(cls._safe_identifier(table_name, 'table'))

        fields = ResponseModelTableField.objects.filter(
            response_model_table=model_table,
            field__is_active=True,
        ).select_related('field', 'field__lookup_content_type').order_by('order')

        if not fields.exists():
            raise ValueError(f"No fields configured for table {table_name}")

        extractable = [fc for fc in fields if fc.field.is_extractable()]
        field_definitions = [cls._build_field_definition(fc) for fc in extractable]
        for child_mt in child_tables or []:
            child_name = child_mt.database_table.clientapp_content_type.model
            child_cls_name = cls._to_class_name(cls._safe_identifier(child_name, 'table'))
            field_definitions.append(
                f'{child_key(child_mt.database_table)}: Optional[List[{child_cls_name}]] = '
                f'Field(None, description="List of extracted {child_name} records '
                f'belonging to this {table_name} record; [] if none")'
            )
        assessment_fields = (cls._assessment_fields([fc.field for fc in fields], child_tables or [])
                             if include_field_assessments else {})
        assessment_code = ''
        if assessment_fields:
            field_literals = ', '.join(repr(name) for name in assessment_fields)
            assessment_code = (f'class {class_name}FieldAssessment(FieldAssessment):\n'
                               f'    field: Literal[{field_literals}]\n\n\n')
            field_definitions.append(f'field_assessments: List[{class_name}FieldAssessment]')
        fields_code = "\n    ".join(field_definitions)

        model_code = assessment_code + f"""class {class_name}(BaseModel):
    \"\"\"
    Extracted data for {table_name} table.
    \"\"\"
    {fields_code}"""

        if assessment_fields:
            model_code += f"""

    @model_validator(mode='after')
    def check_field_assessments(self, info: ValidationInfo):
        field_types = {assessment_fields!r}
        validate_field_assessments(
            {{name: getattr(self, name) for name in field_types}},
            self.field_assessments, field_types, (info.context or {{}}).get('source_text'))
        return self"""

        date_pairs = model_table.database_table.date_validation_pairs or []
        field_names = {fc.field.clientapp_field_name for fc in extractable}
        active_pairs = [(s, e) for s, e in date_pairs if s in field_names and e in field_names]
        if active_pairs:
            checks = "\n".join(
                f"        self._check_pair('{s}', '{e}')" for s, e in active_pairs
            )
            model_code += f"""

    @model_validator(mode='after')
    def check_date_order(self):
        from datetime import date as _date
{checks}
        return self

    @staticmethod
    def _check_pair(start_f, end_f):
        # raises ValueError if the parsed start date is after the end date
        pass  # implemented by the extraction service"""

        return model_code
    
    @classmethod
    def _build_field_definition(cls, field_config: ResponseModelTableField) -> str:
        """
        Builds a field definition line matching the live extraction model:
        choices -> Literal, decimal -> Decimal, bounds -> Field ge/le.
        """
        db_field = field_config.field
        field_name = db_field.clientapp_field_name
        validation = db_field.field_validation or {}
        field_params = []

        choices = validation.get('choices') or []
        if choices:
            type_str = "Literal[" + ", ".join(repr(c) for c in choices) + "]"
        elif validation.get('max_digits'):
            type_str = 'Decimal'
            field_params.append(f'max_digits={validation["max_digits"]}')
            if validation.get('decimal_places') is not None:
                field_params.append(f'decimal_places={validation["decimal_places"]}')
        else:
            type_str = cls.TYPE_MAPPING.get(db_field.field_type)
            if type_str is None:
                raise ValueError(
                    f"Unknown field type '{db_field.field_type}' for field '{field_name}'"
                )

        if db_field.field_type in (EntityTypeChoices.INTEGER, EntityTypeChoices.FLOAT) or type_str == 'Decimal':
            if validation.get('min_value') is not None:
                field_params.append(f'ge={validation["min_value"]}')
            if validation.get('max_value') is not None:
                field_params.append(f'le={validation["max_value"]}')
        if validation.get('max_length') and type_str == 'str':
            field_params.append(f'max_length={validation["max_length"]}')

        description = f"{db_field.clientapp_database_table.clientapp_content_type.model}.{field_name}"
        if db_field.help_text:
            description += f" — {db_field.help_text}"
        if db_field.lookup_field:
            description += " (return the label of the closest matching option)"
        field_params.insert(0, f'description={description!r}')

        return f'{field_name}: Optional[{type_str}] = Field(None, {", ".join(field_params)})'
    
    @classmethod
    def _build_root_model(cls, response_model: ResponseModel, root_tables) -> str:
        """
        Builds the root Pydantic model that contains all root table models.
        Nested tables appear inside their parent's records, not here.
        """
        root_class_name = cls._to_class_name(cls._safe_identifier(response_model.name)) + 'Model'

        field_definitions = []
        for model_table in root_tables:
            table_name = model_table.database_table.clientapp_content_type.model
            class_name = cls._to_class_name(cls._safe_identifier(table_name, 'table'))
            field_name = cls._to_field_name(table_name)
            
            field_def = f'{field_name}: Optional[List[{class_name}]] = Field(None, description="List of extracted {table_name} records; one object per record, [] if none")'
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
        
        model_tables = list(
            ResponseModelTable.objects.filter(response_model=response_model)
            .select_related('database_table__clientapp_content_type'))

        if not model_tables:
            errors.append("No tables configured for this response model")
            return {'valid': False, 'errors': errors, 'warnings': warnings}

        present_table_ids = {mt.database_table_id for mt in model_tables}

        for model_table in model_tables:
            table_label = model_table.database_table.clientapp_content_type.model

            # Every required ancestor must itself be in the response model —
            # write-back needs a record for each non-Patient parent.
            for anc in ancestor_tables(model_table.database_table):
                if anc.id not in present_table_ids:
                    errors.append(
                        f"Table '{table_label}' requires its parent "
                        f"'{anc.clientapp_content_type.model}' — select it in "
                        f"step 2 (required parents are auto-included).")

            if model_table.auto_added:
                selected_names = {
                    f.field.clientapp_field_name
                    for f in ResponseModelTableField.objects.filter(
                        response_model_table=model_table).select_related('field')
                }
                if not set(identity_field_names(model_table.database_table)) & selected_names:
                    warnings.append(
                        f"Auto-included parent '{table_label}' has none of its "
                        f"identity fields selected — existing parent records "
                        f"cannot be detected without them.")

            fields = ResponseModelTableField.objects.filter(response_model_table=model_table)

            if not fields.exists():
                errors.append(f"No fields configured for table {model_table.database_table}")

            for field in fields:
                db_field = field.field
                if not db_field.is_active:
                    errors.append(
                        f"Field '{db_field.clientapp_field_name}' no longer exists on the source model; "
                        f"remove it from the response model"
                    )
                if db_field.field_type not in cls.TYPE_TO_PYTHON:
                    errors.append(
                        f"Field '{db_field.clientapp_field_name}' has unknown type "
                        f"'{db_field.field_type}'"
                    )
                if db_field.lookup_field:
                    if not db_field.lookup_content_type:
                        warnings.append(f"Lookup field {db_field.clientapp_field_name} missing lookup table configuration")
        
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
        
        from typing import get_origin, Union

        # Get model fields
        if hasattr(model_class, 'model_fields'):
            for field_name, field_info in model_class.model_fields.items():
                # Generate sample value based on field type
                field_type = field_info.annotation
                origin = get_origin(field_type)

                if origin is Union:
                    # Optional[...] / Union — a None sample is always valid here
                    sample_data[field_name] = None
                elif origin is list:
                    sample_data[field_name] = []
                elif origin is dict:
                    sample_data[field_name] = {}
                else:
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
