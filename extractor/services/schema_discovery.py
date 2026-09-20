from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models as django_models, transaction
from django.db.utils import OperationalError
from extractor.models import DatabaseTable, DatabaseField, EntityTypeChoices
from logging import getLogger
import time

log = getLogger(__name__)


class SchemaDiscoveryService:
    
    PYTHON_TYPE_TO_ENTITY_TYPE = {
        'CharField': EntityTypeChoices.STRING,
        'TextField': EntityTypeChoices.STRING,
        'EmailField': EntityTypeChoices.STRING,
        'URLField': EntityTypeChoices.STRING,
        'SlugField': EntityTypeChoices.STRING,
        'UUIDField': EntityTypeChoices.STRING,
        'FileField': EntityTypeChoices.STRING,
        'ImageField': EntityTypeChoices.STRING,
        'FilePathField': EntityTypeChoices.STRING,
        'BooleanField': EntityTypeChoices.BOOLEAN,
        'NullBooleanField': EntityTypeChoices.BOOLEAN,
        'IntegerField': EntityTypeChoices.INTEGER,
        'PositiveIntegerField': EntityTypeChoices.INTEGER,
        'SmallIntegerField': EntityTypeChoices.INTEGER,
        'BigIntegerField': EntityTypeChoices.INTEGER,
        'AutoField': EntityTypeChoices.INTEGER,
        'BigAutoField': EntityTypeChoices.INTEGER,
        'SmallAutoField': EntityTypeChoices.INTEGER,
        'FloatField': EntityTypeChoices.FLOAT,
        'DecimalField': EntityTypeChoices.FLOAT,
        'DateField': EntityTypeChoices.DATE,
        'DateTimeField': EntityTypeChoices.DATETIME,
        'TimeField': EntityTypeChoices.TIME,
        'DurationField': EntityTypeChoices.TIMEDELTA,
        'JSONField': EntityTypeChoices.DICTIONARY,
    }
    
    @classmethod
    def discover_and_populate_schema(cls, max_retries=3, progress_callback=None):
        """
        Discovers all client_app models and populates DatabaseTable and DatabaseField models.
        This should be called when the wizard is initiated to refresh the schema.
        Uses transaction handling and retry logic for database lock issues.
        
        Args:
            max_retries: Maximum number of retry attempts for database locks
            progress_callback: Optional callback function(status, message, progress) for progress updates
        """
        log.info("Starting schema discovery for client_app models...")
        
        if progress_callback:
            progress_callback('started', 'Initializing schema discovery...', 0)
        
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    client_app_content_types = ContentType.objects.filter(app_label='client_app')
                    total_models = client_app_content_types.count()
                    
                    tables_created = 0
                    fields_created = 0
                    processed_models = 0
                    
                    for content_type in client_app_content_types:
                        model_class = content_type.model_class()
                        
                        if not model_class:
                            continue
                        
                        model_name = model_class.__name__
                        log.info(f"Processing model: {model_name}")
                        
                        if progress_callback:
                            progress = int((processed_models / total_models) * 100)
                            progress_callback('processing_table', f'Processing table: {model_name}', progress)
                        
                        db_table, created = cls._create_or_update_database_table(content_type, model_class)
                        if created:
                            tables_created += 1
                        
                        if progress_callback:
                            progress_callback('processing_fields', f'Discovering fields for: {model_name}', progress)
                        
                        field_count = cls._create_or_update_database_fields(db_table, model_class, progress_callback)
                        fields_created += field_count
                        
                        processed_models += 1
                    
                    log.info(f"Schema discovery complete. Tables: {tables_created}, Fields: {fields_created}")
                    
                    if progress_callback:
                        progress_callback('completed', f'Schema discovery complete! Tables: {tables_created}, Fields: {fields_created}', 100)
                    
                    return {
                        'tables_created': tables_created,
                        'fields_created': fields_created
                    }
                    
            except OperationalError as e:
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 0.5
                    log.warning(f"Database locked, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    
                    if progress_callback:
                        progress_callback('retrying', f'Database locked, retrying in {wait_time}s...', 0)
                    
                    time.sleep(wait_time)
                else:
                    log.error(f"Schema discovery failed after {attempt + 1} attempts: {e}")
                    
                    if progress_callback:
                        progress_callback('error', f'Schema discovery failed: {str(e)}', 0)
                    
                    raise
    
    @classmethod
    def _create_or_update_database_table(cls, content_type, model_class):
        """
        Creates or updates a DatabaseTable entry for the given model.
        """
        pk_field = model_class._meta.pk
        pk_field_name = pk_field.name if pk_field else 'id'
        
        fk_fields = cls._extract_fk_relationships(model_class)

        # Date-ordering rules declared on the source model (DateValidationMixin)
        date_pairs = getattr(model_class, 'date_validation_pairs', None) or []
        date_pairs = [list(pair) for pair in date_pairs]

        db_table, created = DatabaseTable.objects.update_or_create(
            clientapp_content_type=content_type,
            defaults={
                'clientapp_table_pk_field_name': pk_field_name,
                'clientapp_table_fk_fields': fk_fields,
                'date_validation_pairs': date_pairs or None
            }
        )
        
        return db_table, created
    
    @classmethod
    def _extract_fk_relationships(cls, model_class):
        """
        Extracts foreign key relationships from the model, tracking the path to the Patient model.
        Differentiates between forward FKs (this model -> related) and reverse FKs (related -> this).
        Returns a dict with FK chains showing how to reach Patient table.
        """
        fk_relationships = {
            'forward_fks': {},  # FKs from this model to other models
            'reverse_fks': {},  # FKs from other models to this model
            'patient_path': None  # Path to reach Patient model
        }
        
        # Extract forward FK relationships (this model points to another)
        for field in model_class._meta.get_fields():
            if isinstance(field, (django_models.ForeignKey, django_models.OneToOneField)):
                if hasattr(field, 'related_model') and field.related_model:
                    related_model = field.related_model
                    fk_relationships['forward_fks'][field.name] = {
                        'related_model': f"{related_model._meta.app_label}.{related_model._meta.model_name}",
                        'related_field': related_model._meta.pk.name if related_model._meta.pk else 'id',
                        'field_type': 'ForeignKey',
                        'is_lookup': related_model._meta.app_label == 'lookup'
                    }
        
        # Find path to Patient model
        patient_path = cls._find_patient_path(model_class)
        if patient_path:
            fk_relationships['patient_path'] = patient_path
        
        return fk_relationships
    
    @classmethod
    def _find_patient_path(cls, model_class, visited=None, path=None):
        """
        Recursively finds the FK path from this model to the Patient model.
        Returns a list of field names that form the path, or None if no path exists.
        """
        if visited is None:
            visited = set()
        if path is None:
            path = []
        
        # Avoid circular references
        model_key = f"{model_class._meta.app_label}.{model_class._meta.model_name}"
        if model_key in visited:
            return None
        visited.add(model_key)
        
        # Check if this is the Patient model
        if model_class._meta.model_name == 'patient' and model_class._meta.app_label == 'client_app':
            return path
        
        # Look through forward FKs for a path to Patient
        for field in model_class._meta.get_fields():
            if isinstance(field, (django_models.ForeignKey, django_models.OneToOneField)):
                if hasattr(field, 'related_model') and field.related_model:
                    related_model = field.related_model
                    
                    # Skip lookup tables in the path
                    if related_model._meta.app_label == 'lookup':
                        continue
                    
                    # Recursively search for Patient through this FK
                    new_path = path + [{
                        'field': field.name,
                        'model': f"{related_model._meta.app_label}.{related_model._meta.model_name}",
                        'pk_field': related_model._meta.pk.name if related_model._meta.pk else 'id'
                    }]
                    
                    result = cls._find_patient_path(related_model, visited.copy(), new_path)
                    if result is not None:
                        return result
        
        return None
    
    @classmethod
    def _create_or_update_database_fields(cls, db_table, model_class, progress_callback=None):
        """
        Creates or updates DatabaseField entries for all fields in the model.
        """
        fields_created = 0
        all_fields = [f for f in model_class._meta.get_fields() if not cls._should_skip_field(f)]
        total_fields = len(all_fields)
        seen_names = set()

        for idx, field in enumerate(all_fields):
            field_type = cls._determine_field_type(field)

            if not field_type:
                log.warning(f"Could not determine type for field {field.name} in {model_class.__name__}")
                continue

            seen_names.add(field.name)

            if progress_callback:
                progress_callback('processing_field', f'  → Field: {field.name} ({field_type})', 0)

            is_lookup = cls._is_lookup_field(field)
            lookup_ct = None
            lookup_value_field = None
            lookup_pk_field = None

            if is_lookup:
                lookup_info = cls._extract_lookup_info(field)
                lookup_ct = lookup_info.get('content_type')
                lookup_value_field = lookup_info.get('value_field')
                lookup_pk_field = lookup_info.get('pk_field')

            validation_rules = cls._extract_validation_rules(field) or {}
            # Internal relationship (FK to a non-lookup table): record the flag
            # so the wizard can hide it from the extractable field list.
            if isinstance(field, django_models.ForeignKey) and not is_lookup:
                validation_rules['is_relationship'] = True

            db_field, created = DatabaseField.objects.get_or_create(
                clientapp_database_table=db_table,
                clientapp_field_name=field.name,
                defaults={
                    'field_type': field_type,
                    'field_validation': validation_rules or None,
                    'lookup_field': is_lookup,
                    'lookup_content_type': lookup_ct,
                    'lookup_table_value_field_name': lookup_value_field,
                    'lookup_table_pk_field_name': lookup_pk_field,
                    'lookup_config_source': 'auto',
                    'help_text': str(field.help_text) if getattr(field, 'help_text', None) else '',
                    'is_active': True,
                }
            )

            if not created:
                # Always refresh non-lookup metadata. Lookup configuration is
                # only refreshed when it was auto-discovered — a 'manual' source
                # means a human chose the display/code fields and must not be
                # overwritten by the next discovery run.
                db_field.field_type = field_type
                db_field.field_validation = validation_rules or None
                db_field.help_text = str(field.help_text) if getattr(field, 'help_text', None) else ''
                db_field.is_active = True
                update_fields = ['field_type', 'field_validation', 'help_text', 'is_active']
                if db_field.lookup_config_source == 'auto':
                    db_field.lookup_field = is_lookup
                    db_field.lookup_content_type = lookup_ct
                    db_field.lookup_table_value_field_name = lookup_value_field
                    db_field.lookup_table_pk_field_name = lookup_pk_field
                    update_fields += ['lookup_field', 'lookup_content_type',
                                      'lookup_table_value_field_name', 'lookup_table_pk_field_name']
                db_field.save(update_fields=update_fields)
            else:
                fields_created += 1

        # Fields that disappeared from the source model are marked inactive,
        # not deleted — existing response models keep their selection history.
        DatabaseField.objects.filter(
            clientapp_database_table=db_table
        ).exclude(
            clientapp_field_name__in=seen_names
        ).update(is_active=False)

        return fields_created
    
    @classmethod
    def _should_skip_field(cls, field):
        """
        Determines if a field should be skipped during schema discovery.
        """
        if field.name in ['created_at', 'updated_at']:
            return True
        
        if isinstance(field, (django_models.ManyToManyField, django_models.ManyToManyRel, 
                             django_models.ManyToOneRel, django_models.OneToOneRel)):
            return True
        
        if hasattr(field, 'auto_created') and field.auto_created:
            return True
        
        return False
    
    @classmethod
    def _determine_field_type(cls, field):
        """
        Maps Django field types to EntityTypeChoices.
        For ForeignKey fields, determines the type based on the related model's primary key type.
        """
        field_class_name = field.__class__.__name__
        
        if isinstance(field, django_models.ForeignKey):
            related_model = field.related_model
            if related_model and related_model._meta.pk:
                pk_field = related_model._meta.pk
                pk_field_class_name = pk_field.__class__.__name__
                
                pk_type = cls.PYTHON_TYPE_TO_ENTITY_TYPE.get(pk_field_class_name)
                return pk_type
            
            return None
        
        return cls.PYTHON_TYPE_TO_ENTITY_TYPE.get(field_class_name)
    
    @classmethod
    def _is_lookup_field(cls, field):
        """
        Determines if a field is a lookup field (ForeignKey to lookup app).
        """
        if isinstance(field, django_models.ForeignKey):
            related_model = field.related_model
            if related_model and related_model._meta.app_label == 'lookup':
                return True
        return False
    
    @classmethod
    def _extract_lookup_info(cls, field):
        """
        Extracts lookup table information for a lookup field.
        """
        if not isinstance(field, django_models.ForeignKey):
            return {}
        
        related_model = field.related_model
        if not related_model or related_model._meta.app_label != 'lookup':
            return {}
        
        content_type = ContentType.objects.get_for_model(related_model)
        pk_field = related_model._meta.pk.name if related_model._meta.pk else 'id'
        
        value_field = cls._guess_lookup_value_field(related_model)
        
        return {
            'content_type': content_type,
            'pk_field': pk_field,
            'value_field': value_field
        }
    
    @classmethod
    def _guess_lookup_value_field(cls, model):
        """
        Determines the display field for a lookup table by parsing its __str__ method.
        Falls back to common field name patterns if __str__ parsing fails.
        """
        import re
        import inspect
        
        # Try to parse the __str__ method to find which field it uses
        try:
            str_method = inspect.getsource(model.__str__)
            # Look for patterns like: return f'{self.field_name}' or return self.field_name
            matches = re.findall(r'self\.(\w+)', str_method)
            
            if matches:
                # Get the first field referenced in __str__
                field_name = matches[0]
                
                # Verify this field actually exists
                field_names = [f.name for f in model._meta.get_fields() if not f.auto_created]
                if field_name in field_names:
                    log.info(f"Detected display field '{field_name}' from __str__ method for {model.__name__}")
                    return field_name
        except Exception as e:
            log.debug(f"Could not parse __str__ method for {model.__name__}: {e}")
        
        # Fallback: prioritize human-readable fields for semantic search
        field_names = [f.name for f in model._meta.get_fields() if not f.auto_created]
        
        for candidate in ['label', 'description', 'name', 'value', 'code']:
            if candidate in field_names:
                log.info(f"Using fallback field '{candidate}' for {model.__name__}")
                return candidate
        
        # Last resort: find any CharField/TextField
        for field in model._meta.get_fields():
            if isinstance(field, (django_models.CharField, django_models.TextField)):
                if field.name not in ['id', 'created_at', 'updated_at']:
                    return field.name
        
        return 'id'
    
    @classmethod
    def _extract_validation_rules(cls, field):
        """
        Extracts validation rules from Django field for Pydantic conversion.
        Reads the field's validator objects so Min/MaxValueValidator bounds
        and Decimal precision are actually captured.
        """
        validation = {}

        if hasattr(field, 'max_length') and field.max_length:
            validation['max_length'] = field.max_length

        if hasattr(field, 'null'):
            validation['nullable'] = field.null

        if hasattr(field, 'blank'):
            validation['optional'] = field.blank

        if hasattr(field, 'choices') and field.choices:
            validation['choices'] = [choice[0] for choice in field.choices]

        # Decimal precision
        if getattr(field, 'max_digits', None):
            validation['max_digits'] = field.max_digits
        if getattr(field, 'decimal_places', None) is not None and getattr(field, 'decimal_places', None):
            validation['decimal_places'] = field.decimal_places

        # Bounds live on the validators, not the field — read them
        for validator in getattr(field, 'validators', []) or []:
            try:
                limit = float(validator.limit_value)
            except (TypeError, ValueError, AttributeError):
                continue
            if isinstance(validator, MinValueValidator):
                validation['min_value'] = limit
            elif isinstance(validator, MaxValueValidator):
                validation['max_value'] = limit
        # FloatField/DecimalField also carry min_value/max_value attrs directly
        if getattr(field, 'min_value', None) is not None and 'min_value' not in validation:
            validation['min_value'] = float(field.min_value)
        if getattr(field, 'max_value', None) is not None and 'max_value' not in validation:
            validation['max_value'] = float(field.max_value)

        return validation if validation else None
    
    @classmethod
    def get_hierarchical_table_structure(cls):
        """
        Returns a hierarchical structure of tables organized by their relationship depth to Patient.
        Patient table is at level 0, direct children at level 1, etc.
        """
        tables = DatabaseTable.objects.all().select_related('clientapp_content_type')
        
        # Organize tables by relationship depth
        hierarchy = {
            'patient': None,  # The Patient table itself
            'direct': [],     # Tables with direct FK to Patient (depth 1)
            'indirect': {},   # Tables with indirect FK to Patient (depth 2+)
            'unrelated': []   # Tables with no relationship to Patient
        }
        
        for table in tables:
            model_class = table.clientapp_content_type.model_class()
            if not model_class:
                continue
            
            table_info = {
                'id': table.id,
                'name': table.clientapp_content_type.model,
                'display_name': model_class._meta.verbose_name,
                'app_label': table.clientapp_content_type.app_label,
                'fk_fields': table.clientapp_table_fk_fields or {},
                'patient_path': None,
                'depth': None
            }
            
            # Check if this is the Patient table
            if table.clientapp_content_type.model == 'patient':
                hierarchy['patient'] = table_info
                table_info['depth'] = 0
                continue
            
            # Get patient path if it exists
            fk_fields = table.clientapp_table_fk_fields or {}
            patient_path = fk_fields.get('patient_path')
            
            if patient_path:
                table_info['patient_path'] = patient_path
                depth = len(patient_path)
                table_info['depth'] = depth
                
                if depth == 1:
                    # Direct relationship to Patient
                    hierarchy['direct'].append(table_info)
                else:
                    # Indirect relationship (through other tables)
                    if depth not in hierarchy['indirect']:
                        hierarchy['indirect'][depth] = []
                    hierarchy['indirect'][depth].append(table_info)
            else:
                # No relationship to Patient
                hierarchy['unrelated'].append(table_info)
        
        # Build the final ordered structure
        structure = []
        
        # 1. Patient table first
        if hierarchy['patient']:
            structure.append(hierarchy['patient'])
        
        # 2. Direct children (depth 1) - sorted alphabetically
        hierarchy['direct'].sort(key=lambda x: x['display_name'])
        structure.extend(hierarchy['direct'])
        
        # 3. Indirect children (depth 2+) - sorted by depth, then alphabetically
        for depth in sorted(hierarchy['indirect'].keys()):
            hierarchy['indirect'][depth].sort(key=lambda x: x['display_name'])
            structure.extend(hierarchy['indirect'][depth])
        
        # 4. Unrelated tables last - sorted alphabetically
        hierarchy['unrelated'].sort(key=lambda x: x['display_name'])
        structure.extend(hierarchy['unrelated'])
        
        return structure
    
    @classmethod
    def _has_patient_relationship(cls, fk_fields):
        """
        Checks if the table has a direct or indirect relationship to Patient.
        """
        if not fk_fields:
            return False
        
        # Check if there's a patient_path
        if fk_fields.get('patient_path'):
            return True
        
        # Check forward FKs for direct patient reference
        forward_fks = fk_fields.get('forward_fks', {})
        for field_name, field_info in forward_fks.items():
            if 'patient' in field_name.lower() or 'patient' in field_info.get('related_model', '').lower():
                return True
        
        return False
