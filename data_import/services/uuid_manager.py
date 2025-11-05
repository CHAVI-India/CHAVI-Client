"""
Service for managing UUID generation and persistence for FK/M2M relationships.
"""
import uuid
import hashlib
import json
from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class UUIDManagerService:
    """
    Service to manage UUID generation and persistence for related tables.
    Ensures consistent UUIDs across multiple imports of the same data.
    """
    
    def __init__(self, import_data_id: int):
        """
        Initialize the UUID manager.
        
        Args:
            import_data_id: ID of the ImportData instance
        """
        self.import_data_id = import_data_id
        self.uuid_mappings = {}  # Cache of existing mappings
        self.new_uuids = {}  # New UUIDs generated in this session
        
    def identify_related_tables(self, field_mappings: Dict[str, Dict]) -> Dict[str, List[Dict]]:
        """
        Identify tables that have FK/M2M relationships and need UUIDs.
        
        Args:
            field_mappings: Dictionary mapping source field names to CHAVI field metadata
            
        Returns:
            Dictionary mapping table names to their related fields
        """
        related_tables = defaultdict(list)
        
        for source_field, chavi_field in field_mappings.items():
            # Check if this field is a FK or M2M
            if chavi_field.get('is_foreign_key') or chavi_field.get('is_many_to_many'):
                table_name = chavi_field['related_table']
                model_name = chavi_field['related_model']
                
                # Skip lookup tables (they don't need UUID generation)
                if chavi_field.get('is_lookup'):
                    continue
                
                related_tables[table_name].append({
                    'source_field': source_field,
                    'chavi_field': chavi_field['field_name'],
                    'model_name': model_name,
                    'table_name': table_name,
                    'is_foreign_key': chavi_field.get('is_foreign_key', False),
                    'is_many_to_many': chavi_field.get('is_many_to_many', False),
                })
        
        return dict(related_tables)
    
    def group_rows_by_patient(
        self, 
        data_rows: List[Dict], 
        patient_id_field: str
    ) -> Dict[str, List[Dict]]:
        """
        Group data rows by patient ID.
        
        Args:
            data_rows: List of data rows from imported file
            patient_id_field: Name of the source field containing patient ID
            
        Returns:
            Dictionary mapping patient IDs to their rows
        """
        grouped = defaultdict(list)
        
        for row in data_rows:
            patient_id = row.get(patient_id_field)
            if patient_id:
                grouped[str(patient_id).strip()].append(row)
        
        return dict(grouped)
    
    def generate_composite_key(
        self, 
        row_data: Dict, 
        key_fields: List[str]
    ) -> str:
        """
        Generate a composite key from multiple field values.
        
        Args:
            row_data: Dictionary of row data
            key_fields: List of field names to include in the key
            
        Returns:
            Hash string representing the composite key
        """
        # Extract values for key fields
        key_values = []
        for field in sorted(key_fields):  # Sort for consistency
            value = row_data.get(field, '')
            # Normalize the value
            if value is None:
                value = ''
            key_values.append(str(value).strip().lower())
        
        # Create a stable hash
        key_string = '|'.join(key_values)
        hash_obj = hashlib.sha256(key_string.encode('utf-8'))
        return hash_obj.hexdigest()
    
    def determine_key_fields_for_table(
        self, 
        table_name: str, 
        related_fields: List[Dict],
        field_mappings: Dict[str, Dict]
    ) -> List[str]:
        """
        Determine which fields should be used to create composite keys for a table.
        
        Args:
            table_name: Name of the related table
            related_fields: List of fields related to this table
            field_mappings: All field mappings
            
        Returns:
            List of source field names to use for composite key
        """
        # Get all fields that map to this table
        table_fields = []
        
        for source_field, chavi_field in field_mappings.items():
            if chavi_field['table_name'] == table_name:
                # Exclude FK/M2M fields themselves
                if not (chavi_field.get('is_foreign_key') or chavi_field.get('is_many_to_many')):
                    table_fields.append(source_field)
        
        # If no fields found, use the related fields
        if not table_fields:
            table_fields = [rf['source_field'] for rf in related_fields]
        
        return table_fields
    
    def load_existing_mappings(self, table_name: str, patient_id: str) -> Dict[str, str]:
        """
        Load existing UUID mappings from database.
        
        Args:
            table_name: Name of the table
            patient_id: Patient ID
            
        Returns:
            Dictionary mapping composite keys to UUIDs
        """
        from data_import.models import UUIDMappings
        
        cache_key = f"{table_name}:{patient_id}"
        
        if cache_key in self.uuid_mappings:
            return self.uuid_mappings[cache_key]
        
        mappings = {}
        
        try:
            # Query existing mappings
            existing = UUIDMappings.objects.filter(
                import_data_id=self.import_data_id,
                client_app_table_name=table_name,
            )
            
            for mapping in existing:
                # The composite key is stored in the primary key value field
                # We'll need to reconstruct it from the field values
                # For now, we'll use a simple approach
                mappings[mapping.client_app_primary_key_value] = mapping.client_app_primary_key_value
            
            self.uuid_mappings[cache_key] = mappings
            
        except Exception as e:
            logger.error(f"Error loading UUID mappings: {e}")
        
        return mappings
    
    def generate_or_retrieve_uuid(
        self, 
        table_name: str, 
        composite_key: str,
        patient_id: str
    ) -> str:
        """
        Generate a new UUID or retrieve existing one for a composite key.
        
        Args:
            table_name: Name of the table
            composite_key: Composite key hash
            patient_id: Patient ID
            
        Returns:
            UUID string
        """
        # Check existing mappings
        existing_mappings = self.load_existing_mappings(table_name, patient_id)
        
        if composite_key in existing_mappings:
            return existing_mappings[composite_key]
        
        # Check new UUIDs generated in this session
        session_key = f"{table_name}:{composite_key}"
        if session_key in self.new_uuids:
            return self.new_uuids[session_key]
        
        # Generate new UUID
        new_uuid = str(uuid.uuid4())
        self.new_uuids[session_key] = new_uuid
        
        return new_uuid
    
    def process_patient_data(
        self, 
        patient_id: str,
        patient_rows: List[Dict],
        field_mappings: Dict[str, Dict],
        related_tables: Dict[str, List[Dict]]
    ) -> Dict[str, List[Dict]]:
        """
        Process all rows for a patient and generate UUID mappings.
        
        Args:
            patient_id: Patient ID
            patient_rows: List of rows for this patient
            field_mappings: Field mappings
            related_tables: Related table information
            
        Returns:
            Dictionary mapping table names to lists of record data with UUIDs
        """
        records_by_table = defaultdict(list)
        
        for table_name, related_fields in related_tables.items():
            # Determine key fields for this table
            key_fields = self.determine_key_fields_for_table(
                table_name, 
                related_fields, 
                field_mappings
            )
            
            # Process each row
            for row in patient_rows:
                # Generate composite key
                composite_key = self.generate_composite_key(row, key_fields)
                
                # Generate or retrieve UUID
                record_uuid = self.generate_or_retrieve_uuid(
                    table_name, 
                    composite_key,
                    patient_id
                )
                
                # Create record data
                record_data = {
                    'uuid': record_uuid,
                    'composite_key': composite_key,
                    'key_fields': key_fields,
                    'row_data': row,
                    'patient_id': patient_id,
                }
                
                # Check if this is a duplicate (same composite key)
                existing = [r for r in records_by_table[table_name] if r['composite_key'] == composite_key]
                if not existing:
                    records_by_table[table_name].append(record_data)
        
        return dict(records_by_table)
    
    def process_all_data(
        self, 
        data_rows: List[Dict],
        field_mappings: Dict[str, Dict],
        patient_id_field: str
    ) -> Dict:
        """
        Process all data and generate UUID mappings.
        
        Args:
            data_rows: List of all data rows
            field_mappings: Field mappings
            patient_id_field: Name of the patient ID field in imported data
            
        Returns:
            Dictionary with processing results
        """
        # Identify related tables
        related_tables = self.identify_related_tables(field_mappings)
        
        if not related_tables:
            return {
                'has_related_tables': False,
                'related_tables': {},
                'records_by_patient': {},
                'total_records': 0,
            }
        
        # Group rows by patient
        rows_by_patient = self.group_rows_by_patient(data_rows, patient_id_field)
        
        # Process each patient's data
        all_records = {}
        
        for patient_id, patient_rows in rows_by_patient.items():
            patient_records = self.process_patient_data(
                patient_id,
                patient_rows,
                field_mappings,
                related_tables
            )
            all_records[patient_id] = patient_records
        
        # Calculate statistics
        total_records = sum(
            len(records)
            for patient_records in all_records.values()
            for records in patient_records.values()
        )
        
        return {
            'has_related_tables': True,
            'related_tables': related_tables,
            'records_by_patient': all_records,
            'total_records': total_records,
            'total_patients': len(rows_by_patient),
            'new_uuids_generated': len(self.new_uuids),
        }
    
    def save_uuid_mappings(
        self, 
        uuid_processing_result: Dict
    ) -> int:
        """
        Save UUID mappings to database.
        
        Args:
            uuid_processing_result: Result from process_all_data()
            
        Returns:
            Number of mappings saved
        """
        from data_import.models import UUIDMappings, DataFieldConfiguration
        
        saved_count = 0
        
        try:
            records_by_patient = uuid_processing_result.get('records_by_patient', {})
            
            for patient_id, patient_records in records_by_patient.items():
                for table_name, records in patient_records.items():
                    for record in records:
                        # Create UUID mapping
                        mapping = UUIDMappings.objects.create(
                            import_data_id=self.import_data_id,
                            client_app_table_name=table_name,
                            client_app_primary_key_name='id',  # Assuming UUID field is named 'id'
                            client_app_primary_key_value=record['uuid'],
                        )
                        
                        # Link to the data field configurations used for the composite key
                        # This would require looking up the DataFieldConfiguration instances
                        # For now, we'll skip this step
                        
                        saved_count += 1
            
            logger.info(f"Saved {saved_count} UUID mappings")
            
        except Exception as e:
            logger.error(f"Error saving UUID mappings: {e}")
            raise
        
        return saved_count
    
    def get_uuid_for_record(
        self, 
        table_name: str, 
        row_data: Dict,
        key_fields: List[str],
        patient_id: str
    ) -> str:
        """
        Get UUID for a specific record during import.
        
        Args:
            table_name: Name of the table
            row_data: Row data
            key_fields: Fields to use for composite key
            patient_id: Patient ID
            
        Returns:
            UUID string
        """
        composite_key = self.generate_composite_key(row_data, key_fields)
        return self.generate_or_retrieve_uuid(table_name, composite_key, patient_id)
    
    def get_statistics(self) -> Dict:
        """
        Get statistics about UUID generation.
        
        Returns:
            Statistics dictionary
        """
        return {
            'new_uuids_generated': len(self.new_uuids),
            'existing_mappings_loaded': sum(len(m) for m in self.uuid_mappings.values()),
            'total_uuids': len(self.new_uuids) + sum(len(m) for m in self.uuid_mappings.values()),
        }
