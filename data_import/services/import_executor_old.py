"""
Service for executing the actual data import into the database.
"""
from django.db import transaction, IntegrityError
from django.apps import apps
from typing import Dict, List, Any, Tuple
from data_import.models import ImportData, ImportStatus, DataFieldConfiguration
from data_import.services.file_processor import FileProcessorService
from data_import.services.field_introspection import FieldIntrospectionService
import logging
import uuid

logger = logging.getLogger(__name__)


class ImportExecutorService:
    """
    Service to execute the final import of data into the database.
    Orchestrates all other services and handles database transactions.
    """
    
    def __init__(self, import_data_id: int):
        """
        Initialize the import executor.
        
        Args:
            import_data_id: ID of the ImportData instance
        """
        self.import_data_id = import_data_id
        self.import_data = ImportData.objects.get(id=import_data_id)
        self.field_service = FieldIntrospectionService()
        self.records_created = {}
        self.records_updated = {}
        self.errors = []
    
    def execute_import(self) -> Dict[str, Any]:
        """
        Execute the complete import process.
        
        Returns:
            Dictionary with import results and statistics
        """
        try:
            # Update status
            self.import_data.status = ImportStatus.IMPORTING
            self.import_data.save()
            
            # Parse file
            processor = FileProcessorService(
                self.import_data.file.path,
                self.import_data.data_type
            )
            headers, data_rows = processor.parse()
            
            # Get field mappings
            field_mappings = self._get_field_mappings()
            
            # Get lookup mappings
            lookup_mappings = self._get_lookup_mappings()
            
            # Get UUID mappings
            uuid_mappings = self._get_uuid_mappings()
            
            # Process rows
            results = self._process_rows(
                data_rows,
                field_mappings,
                lookup_mappings,
                uuid_mappings
            )
            
            # Update import data with results
            self.import_data.status = ImportStatus.COMPLETED
            self.import_data.processed_rows = results['successful_rows']
            self.import_data.import_summary = {
                'total_rows': results['total_rows'],
                'successful_rows': results['successful_rows'],
                'failed_rows': results['failed_rows'],
                'records_created': self.records_created,
                'records_updated': self.records_updated,
                'errors': self.errors[:100],  # Limit to first 100 errors
            }
            self.import_data.save()
            
            return results
            
        except Exception as e:
            logger.error(f"Import execution failed: {e}", exc_info=True)
            self.import_data.status = ImportStatus.FAILED
            self.import_data.error_log = str(e)
            self.import_data.save()
            raise
    
    def _get_field_mappings(self) -> Dict[str, Dict]:
        """
        Get field mappings from database.
        
        Returns:
            Dictionary mapping source fields to CHAVI field metadata
        """
        mappings = {}
        
        for mapping in self.import_data.data_fields.all():
            field_meta = self.field_service.get_field(
                mapping.client_app_table_name,
                mapping.client_app_field_name
            )
            
            if field_meta:
                mappings[mapping.file_field_name] = {
                    'field_metadata': field_meta,
                    'mapping': mapping,
                }
        
        return mappings
    
    def _get_lookup_mappings(self) -> Dict[str, Dict[str, str]]:
        """
        Get lookup value mappings from database.
        
        Returns:
            Dictionary mapping source fields to value mappings
        """
        lookup_mappings = {}
        
        for field_config in self.import_data.data_fields.all():
            if field_config.field_lookup_configurations.exists():
                field_mappings = {}
                for lookup_config in field_config.field_lookup_configurations.all():
                    field_mappings[lookup_config.field_value] = lookup_config.lookup_value
                
                lookup_mappings[field_config.file_field_name] = field_mappings
        
        return lookup_mappings
    
    def _get_uuid_mappings(self) -> Dict[str, Dict[str, str]]:
        """
        Get UUID mappings from database.
        
        Returns:
            Dictionary mapping composite keys to UUIDs
        """
        uuid_mappings = {}
        
        for uuid_mapping in self.import_data.uuid_mappings.all():
            table_name = uuid_mapping.client_app_table_name
            if table_name not in uuid_mappings:
                uuid_mappings[table_name] = {}
            
            # Use primary key value as the lookup key
            uuid_mappings[table_name][uuid_mapping.client_app_primary_key_value] = {
                'pk': uuid_mapping.client_app_primary_key_value,
                'pk_name': uuid_mapping.client_app_primary_key_name,
            }
        
        return uuid_mappings
    
    def _process_rows(
        self,
        data_rows: List[Dict],
        field_mappings: Dict,
        lookup_mappings: Dict,
        uuid_mappings: Dict
    ) -> Dict[str, Any]:
        """
        Process all data rows and import into database.
        
        Args:
            data_rows: List of data rows
            field_mappings: Field mappings
            lookup_mappings: Lookup value mappings
            uuid_mappings: UUID mappings
            
        Returns:
            Dictionary with import statistics
        """
        total_rows = len(data_rows)
        successful_rows = 0
        failed_rows = 0
        
        # Group fields by table
        fields_by_table = self._group_fields_by_table(field_mappings)
        
        # Process each row
        for row_num, row_data in enumerate(data_rows, start=1):
            try:
                with transaction.atomic():
                    # Process each table
                    for table_name, table_fields in fields_by_table.items():
                        self._process_table_row(
                            table_name,
                            table_fields,
                            row_data,
                            lookup_mappings,
                            uuid_mappings,
                            row_num
                        )
                
                successful_rows += 1
                
                # Update progress periodically
                if row_num % 10 == 0:
                    self.import_data.processed_rows = successful_rows
                    self.import_data.save(update_fields=['processed_rows'])
                
            except Exception as e:
                logger.error(f"Error processing row {row_num}: {e}")
                failed_rows += 1
                self.errors.append({
                    'row': row_num,
                    'error': str(e),
                })
                continue
        
        return {
            'total_rows': total_rows,
            'successful_rows': successful_rows,
            'failed_rows': failed_rows,
        }
    
    def _group_fields_by_table(self, field_mappings: Dict) -> Dict[str, List]:
        """
        Group field mappings by target table.
        
        Args:
            field_mappings: Field mappings
            
        Returns:
            Dictionary mapping table names to field lists
        """
        fields_by_table = {}
        
        for source_field, mapping_data in field_mappings.items():
            table_name = mapping_data['field_metadata']['table_name']
            
            if table_name not in fields_by_table:
                fields_by_table[table_name] = []
            
            fields_by_table[table_name].append({
                'source_field': source_field,
                'field_metadata': mapping_data['field_metadata'],
                'mapping': mapping_data['mapping'],
            })
        
        return fields_by_table
    
    def _process_table_row(
        self,
        table_name: str,
        table_fields: List[Dict],
        row_data: Dict,
        lookup_mappings: Dict,
        uuid_mappings: Dict,
        row_num: int
    ):
        """
        Process a single row for a specific table.
        
        Args:
            table_name: Name of the table
            table_fields: List of fields for this table
            row_data: Row data
            lookup_mappings: Lookup mappings
            uuid_mappings: UUID mappings
            row_num: Row number (for error reporting)
        """
        # Get the model
        model = self._get_model_from_table_name(table_name)
        if not model:
            raise ValueError(f"Model not found for table: {table_name}")
        
        # Prepare data for this table
        model_data = {}
        
        for field_info in table_fields:
            source_field = field_info['source_field']
            field_metadata = field_info['field_metadata']
            field_name = field_metadata['field_name']
            
            # Get raw value
            raw_value = row_data.get(source_field)
            
            # Skip if empty and not required
            if raw_value is None or raw_value == '':
                if not field_metadata.get('is_required'):
                    continue
            
            # Convert value based on field type
            converted_value = self._convert_value(
                raw_value,
                field_metadata,
                lookup_mappings.get(source_field, {}),
                row_num
            )
            
            # Handle foreign keys and many-to-many separately
            if field_metadata.get('is_foreign_key'):
                # Will be handled after record creation
                continue
            elif field_metadata.get('is_many_to_many'):
                # Will be handled after record creation
                continue
            else:
                model_data[field_name] = converted_value
        
        # Get or create the record
        record, created = self._get_or_create_record(
            model,
            table_name,
            model_data,
            uuid_mappings.get(table_name, {})
        )
        
        # Track statistics
        if created:
            if table_name not in self.records_created:
                self.records_created[table_name] = 0
            self.records_created[table_name] += 1
        else:
            if table_name not in self.records_updated:
                self.records_updated[table_name] = 0
            self.records_updated[table_name] += 1
        
        # Handle foreign keys and many-to-many
        self._handle_relationships(
            record,
            table_fields,
            row_data,
            lookup_mappings,
            uuid_mappings,
            row_num
        )
    
    def _get_model_from_table_name(self, table_name: str):
        """
        Get Django model from table name.
        
        Args:
            table_name: Database table name
            
        Returns:
            Django model class or None
        """
        # Try to find model in client_app
        for model in apps.get_app_config('client_app').get_models():
            if model._meta.db_table == table_name:
                return model
        
        # Try lookup app
        for model in apps.get_app_config('lookup').get_models():
            if model._meta.db_table == table_name:
                return model
        
        return None
    
    def _convert_value(
        self,
        raw_value: Any,
        field_metadata: Dict,
        lookup_mapping: Dict,
        row_num: int
    ) -> Any:
        """
        Convert raw value to appropriate Python type.
        
        Args:
            raw_value: Raw value from file
            field_metadata: Field metadata
            lookup_mapping: Lookup mappings for this field
            row_num: Row number
            
        Returns:
            Converted value
        """
        if raw_value is None or raw_value == '':
            return None
        
        data_type = field_metadata.get('data_type', 'String')
        
        # Handle lookup fields
        if field_metadata.get('is_lookup') and lookup_mapping:
            str_value = str(raw_value).strip()
            if str_value in lookup_mapping:
                return lookup_mapping[str_value]
        
        # Convert based on data type
        if data_type == 'Integer':
            return int(raw_value)
        elif data_type == 'Float':
            return float(raw_value)
        elif data_type == 'Boolean':
            if isinstance(raw_value, bool):
                return raw_value
            str_val = str(raw_value).lower().strip()
            return str_val in ['true', 't', 'yes', 'y', '1', 'on']
        elif data_type == 'Date':
            from datetime import datetime
            if isinstance(raw_value, str):
                # Try common formats
                for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
                    try:
                        return datetime.strptime(raw_value, fmt).date()
                    except ValueError:
                        continue
            return raw_value
        elif data_type == 'DateTime':
            from datetime import datetime
            if isinstance(raw_value, str):
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S']:
                    try:
                        return datetime.strptime(raw_value, fmt)
                    except ValueError:
                        continue
            return raw_value
        else:
            return str(raw_value).strip()
    
    def _get_or_create_record(
        self,
        model,
        table_name: str,
        model_data: Dict,
        uuid_mapping: Dict
    ) -> Tuple[Any, bool]:
        """
        Get existing record or create new one.
        
        Args:
            model: Django model class
            table_name: Table name
            model_data: Data for the record
            uuid_mapping: UUID mappings for this table
            
        Returns:
            Tuple of (record, created)
        """
        # Check if model has UUID primary key
        pk_field = model._meta.pk
        
        if pk_field.get_internal_type() == 'UUIDField':
            # Generate or retrieve UUID
            composite_key = self._generate_composite_key(model_data)
            
            if composite_key in uuid_mapping:
                # Use existing UUID
                uuid_value = uuid_mapping[composite_key]['pk']
                try:
                    record = model.objects.get(pk=uuid_value)
                    # Update existing record
                    for key, value in model_data.items():
                        setattr(record, key, value)
                    record.save()
                    return record, False
                except model.DoesNotExist:
                    # Create with specific UUID
                    model_data[pk_field.name] = uuid_value
                    record = model.objects.create(**model_data)
                    return record, True
            else:
                # Create with new UUID
                record = model.objects.create(**model_data)
                return record, True
        else:
            # Non-UUID primary key - use get_or_create with unique fields
            unique_fields = self._get_unique_fields(model, model_data)
            if unique_fields:
                record, created = model.objects.get_or_create(
                    **unique_fields,
                    defaults=model_data
                )
                if not created:
                    # Update existing
                    for key, value in model_data.items():
                        setattr(record, key, value)
                    record.save()
                return record, created
            else:
                # Just create
                record = model.objects.create(**model_data)
                return record, True
    
    def _generate_composite_key(self, data: Dict) -> str:
        """Generate composite key from data."""
        import hashlib
        key_string = '|'.join(str(v) for v in sorted(data.values()) if v is not None)
        return hashlib.sha256(key_string.encode()).hexdigest()
    
    def _get_unique_fields(self, model, data: Dict) -> Dict:
        """Get unique fields from data for get_or_create."""
        unique_fields = {}
        
        for field in model._meta.get_fields():
            if field.unique and field.name in data:
                unique_fields[field.name] = data[field.name]
        
        return unique_fields
    
    def _handle_relationships(
        self,
        record,
        table_fields: List[Dict],
        row_data: Dict,
        lookup_mappings: Dict,
        uuid_mappings: Dict,
        row_num: int
    ):
        """
        Handle foreign key and many-to-many relationships.
        
        Args:
            record: The created/updated record
            table_fields: Fields for this table
            row_data: Row data
            lookup_mappings: Lookup mappings
            uuid_mappings: UUID mappings
            row_num: Row number
        """
        for field_info in table_fields:
            source_field = field_info['source_field']
            field_metadata = field_info['field_metadata']
            field_name = field_metadata['field_name']
            
            raw_value = row_data.get(source_field)
            
            if field_metadata.get('is_foreign_key'):
                # Handle FK
                if raw_value:
                    related_model_name = field_metadata.get('related_model')
                    related_pk = self._convert_value(
                        raw_value,
                        field_metadata,
                        lookup_mappings.get(source_field, {}),
                        row_num
                    )
                    
                    if related_pk:
                        setattr(record, field_name + '_id', related_pk)
                        record.save()
            
            elif field_metadata.get('is_many_to_many'):
                # Handle M2M
                if raw_value:
                    # Assuming comma-separated values
                    values = [v.strip() for v in str(raw_value).split(',')]
                    related_pks = []
                    
                    for val in values:
                        related_pk = self._convert_value(
                            val,
                            field_metadata,
                            lookup_mappings.get(source_field, {}),
                            row_num
                        )
                        if related_pk:
                            related_pks.append(related_pk)
                    
                    if related_pks:
                        getattr(record, field_name).set(related_pks)
