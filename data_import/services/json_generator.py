"""Service to generate import JSON from file data and all mappings"""
import pandas as pd
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from django.apps import apps
from data_import.models import (
    ImportData, DataFieldConfiguration, StaticFieldMapping,
    ImportDateFormatConfiguration, ImportDateIntervalFieldConfiguration,
    UUIDFieldConfiguration, ImportDataJSON, UUIDMatchConfiguration, UUIDMatchAction
)
from data_import.services.model_hierarchy import ModelHierarchyService

logger = logging.getLogger(__name__)


class JSONGeneratorService:
    """
    Generates import JSON from uploaded file and all configuration mappings.
    Handles field mappings, static values, date conversions, intervals, and UUID generation.
    """
    
    def __init__(self, import_data: ImportData):
        self.import_data = import_data
        self.hierarchy_service = ModelHierarchyService()
        self.df = None
        self.uuid_cache = {}  # Cache for generated UUIDs
        
    def generate_json(self) -> dict:
        """Main method to generate the complete import JSON"""
        logger.info(f"Starting JSON generation for import {self.import_data.id}")
        
        # Load the data file
        self._load_data_file()
        
        # Get all configurations
        field_mappings = self._get_field_mappings()
        static_mappings = self._get_static_mappings()
        date_formats = self._get_date_formats()
        date_intervals = self._get_date_intervals()
        uuid_configs = self._get_uuid_configurations()
        lookup_mappings = self._get_lookup_mappings()
        uuid_match_mappings = self._get_uuid_match_mappings()
        
        logger.info(f"Loaded {len(lookup_mappings)} lookup field mappings")
        logger.info(f"Loaded {len(uuid_match_mappings)} UUID match mappings")
        
        # Build hierarchical JSON structure
        json_data = self._build_hierarchical_json(
            field_mappings, static_mappings, date_formats, 
            date_intervals, uuid_configs, lookup_mappings, uuid_match_mappings
        )
        
        # Save to database
        self._save_json_to_db(json_data)
        
        logger.info(f"JSON generation complete for import {self.import_data.id}")
        return json_data
    
    def _load_data_file(self):
        """Load the uploaded data file into a pandas DataFrame"""
        file_path = self.import_data.file.path
        
        if self.import_data.data_type == 'CSV':
            self.df = pd.read_csv(file_path)
        elif self.import_data.data_type == 'Excel':
            self.df = pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file type: {self.import_data.data_type}")
        
        logger.info(f"Loaded {len(self.df)} rows from {file_path}")
    
    def _get_field_mappings(self) -> dict:
        """Get all field mappings grouped by table"""
        mappings = defaultdict(list)
        
        for mapping in self.import_data.data_fields.all():
            if mapping.client_app_field_name and mapping.client_app_table_name:
                mappings[mapping.client_app_table_name].append({
                    'file_field': mapping.file_field_name,
                    'chavi_field': mapping.client_app_field_name,
                    'field_type': mapping.client_app_field_type
                })
        
        return dict(mappings)
    
    def _get_static_mappings(self) -> dict:
        """Get all static field mappings grouped by table"""
        mappings = defaultdict(list)
        
        for static in self.import_data.static_field_mappings.all():
            if static.chavi_field:
                parts = static.chavi_field.split('.')
                if len(parts) == 2:
                    table_name, field_name = parts
                    mappings[table_name].append({
                        'chavi_field': field_name,
                        'static_value': static.static_value
                    })
        
        return dict(mappings)
    
    def _get_date_formats(self) -> dict:
        """Get date format configurations"""
        formats = {}
        
        for config in ImportDateFormatConfiguration.objects.filter(
            data_field_configuration__import_data=self.import_data
        ):
            field_config = config.data_field_configuration
            key = f"{field_config.client_app_table_name}.{field_config.client_app_field_name}"
            formats[key] = {
                'format': config.date_format,
                'separator': config.date_separator
            }
        
        return formats
    
    def _get_date_intervals(self) -> dict:
        """Get date interval configurations"""
        intervals = {}
        
        for config in ImportDateIntervalFieldConfiguration.objects.filter(
            import_data=self.import_data
        ):
            if config.target_date_field:
                intervals[config.target_date_field] = {
                    'interval_field': config.interval_field,
                    'interval_units': config.interval_units,
                    'calculation_date': config.calculation_date,
                    'calculation_date_type': config.calculation_date_type
                }
        
        return intervals
    
    def _get_uuid_configurations(self) -> dict:
        """Get UUID field configurations"""
        configs = {}
        
        for config in UUIDFieldConfiguration.objects.filter(
            import_data=self.import_data
        ):
            configs[config.table_name] = json.loads(config.uuid_fields)
        
        return configs
    
    def _get_lookup_mappings(self) -> dict:
        """Get lookup field mappings from Step 6"""
        from data_import.models import FieldLookupConfiguration
        
        mappings = defaultdict(dict)
        
        # Get all lookup configurations for this import
        lookup_configs = FieldLookupConfiguration.objects.filter(
            data_field_configuration__import_data=self.import_data
        ).select_related('data_field_configuration')
        
        for config in lookup_configs:
            field_name = config.data_field_configuration.file_field_name
            mappings[field_name][config.field_value] = config.lookup_value
        
        return dict(mappings)
    
    def _get_uuid_match_mappings(self) -> dict:
        """Get UUID match mappings from Step 8.5"""
        mappings = {}
        
        # Get all UUID match configurations where user chose to use existing UUID
        uuid_matches = UUIDMatchConfiguration.objects.filter(
            import_data=self.import_data,
            match_action=UUIDMatchAction.USE_EXISTING
        )
        
        for match in uuid_matches:
            # Map generated_uuid -> existing_uuid
            mappings[match.generated_uuid] = match.existing_uuid
            logger.debug(f"UUID mapping: {match.generated_uuid} -> {match.existing_uuid}")
        
        return mappings
    
    def _build_hierarchical_json(self, field_mappings, static_mappings, 
                                  date_formats, date_intervals, uuid_configs, lookup_mappings, uuid_match_mappings) -> dict:
        """Build the hierarchical JSON structure with proper nesting based on FK relationships"""
        
        # Collect all records indexed by table, patient_uuid, and record_uuid
        all_records = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
        
        for index, row in self.df.iterrows():
            # For patient table, use patient_id directly instead of generating UUID
            patient_uuid = row.get('patient_id', str(index)) if 'patient_id' in row else self._generate_uuid('patient', row, uuid_configs.get('patient', []))
            
            for table_name, mappings in field_mappings.items():
                record = self._build_record(
                    table_name, row, mappings, 
                    static_mappings.get(table_name, []),
                    date_formats, date_intervals, uuid_configs, lookup_mappings
                )
                
                if record:
                    # Get the record's UUID
                    pk_field = self._get_pk_field_name(table_name)
                    record_uuid = record.get(pk_field, str(index))
                    
                    # Apply UUID match mapping if user chose to use existing UUID
                    if record_uuid in uuid_match_mappings:
                        existing_uuid = uuid_match_mappings[record_uuid]
                        record[pk_field] = existing_uuid
                        record_uuid = existing_uuid
                        logger.info(f"Replaced UUID for {table_name}: {record_uuid} -> {existing_uuid}")
                    
                    # Store: all_records[table_name][patient_uuid][record_uuid] = record
                    all_records[table_name][patient_uuid][record_uuid] = record
        
        # Build hierarchical structure
        result = {'patients': []}
        
        # Get all patient UUIDs
        patient_uuids = set()
        for table_records in all_records.values():
            patient_uuids.update(table_records.keys())
        
        for patient_uuid in patient_uuids:
            patient_record = self._build_patient_hierarchy(
                patient_uuid, all_records, field_mappings
            )
            if patient_record:
                result['patients'].append(patient_record)
        
        return result
    
    def _build_patient_hierarchy(self, patient_uuid, all_records, field_mappings):
        """Build complete hierarchy for a single patient"""
        
        # Start with patient record
        patient_records = all_records.get('patient', {}).get(patient_uuid, {})
        if not patient_records:
            # Create minimal patient record if no patient table was mapped
            patient_record = {'patient_id': patient_uuid}
        else:
            # Get first (should be only) patient record
            patient_record = list(patient_records.values())[0].copy()
            patient_record['patient_id'] = patient_uuid
        
        # Add child tables that have Patient as parent
        patient_children = self._get_child_tables('Patient', field_mappings)
        
        for child_table in patient_children:
            child_records_dict = all_records.get(child_table, {}).get(patient_uuid, {})
            if child_records_dict:
                # Recursively build nested structure for each child
                nested_children = []
                for child_uuid, child_record in child_records_dict.items():
                    nested_child = self._nest_children(
                        child_table, child_uuid, child_record, 
                        patient_uuid, all_records, field_mappings
                    )
                    nested_children.append(nested_child)
                
                if nested_children:
                    patient_record[child_table] = nested_children
        
        return patient_record
    
    def _nest_children(self, table_name, record_uuid, record, patient_uuid, all_records, field_mappings):
        """Recursively nest children under their parent record"""
        
        record_copy = record.copy()
        
        # Get model name and find child tables
        model_name = self.hierarchy_service._table_to_model_name(table_name)
        child_tables = self._get_child_tables(model_name, field_mappings)
        
        # Add nested children
        for child_table in child_tables:
            child_records_dict = all_records.get(child_table, {}).get(patient_uuid, {})
            
            if child_records_dict:
                nested_children = []
                for child_uuid, child_record in child_records_dict.items():
                    # Recursively nest this child's children
                    nested_child = self._nest_children(
                        child_table, child_uuid, child_record,
                        patient_uuid, all_records, field_mappings
                    )
                    nested_children.append(nested_child)
                
                if nested_children:
                    record_copy[child_table] = nested_children
        
        return record_copy
    
    def _get_child_tables(self, model_name, field_mappings):
        """Get child tables that have FK to this model"""
        child_tables = []
        
        for table_name in field_mappings.keys():
            child_model_name = self.hierarchy_service._table_to_model_name(table_name)
            if child_model_name in self.hierarchy_service.model_relationships:
                parents = self.hierarchy_service.model_relationships[child_model_name]
                if model_name in parents:
                    child_tables.append(table_name)
        
        return child_tables
    
    def _get_pk_field_name(self, table_name):
        """Get primary key field name for a table"""
        model = self._get_model_for_table(table_name)
        if model:
            return model._meta.pk.name
        return None
    
    def _build_record(self, table_name, row, field_mappings, static_mappings,
                     date_formats, date_intervals, uuid_configs, lookup_mappings) -> dict:
        """Build a single record for a table"""
        record = {}
        skipped_required_fields = []
        
        # Add mapped fields from file
        for mapping in field_mappings:
            file_field = mapping['file_field']
            chavi_field = mapping['chavi_field']
            
            if file_field in row:
                value = row[file_field]
                
                # Handle date formatting
                date_key = f"{table_name}.{chavi_field}"
                if date_key in date_formats:
                    value = self._parse_date(value, date_formats[date_key])
                
                # Skip null/empty values
                if pd.notna(value) and value != '':
                    # Apply lookup mapping if this field has one
                    if file_field in lookup_mappings:
                        str_value = str(value).strip()
                        if str_value in lookup_mappings[file_field]:
                            value = lookup_mappings[file_field][str_value]
                            logger.debug(f"Applied lookup mapping: {file_field} '{str_value}' -> '{value}'")
                        else:
                            # Skip this field if no mapping exists - don't include unmapped lookup values
                            logger.warning(f"Skipping unmapped lookup value for {file_field}: '{str_value}'")
                            skipped_required_fields.append(file_field)
                            continue
                    
                    record[chavi_field] = value
        
        # Add static values
        for static in static_mappings:
            record[static['chavi_field']] = static['static_value']
        
        # Add computed date intervals
        for target_field, interval_config in date_intervals.items():
            parts = target_field.split('.')
            if len(parts) == 2 and parts[0] == table_name:
                field_name = parts[1]
                computed_date = self._compute_date_from_interval(row, interval_config)
                if computed_date:
                    record[field_name] = computed_date
        
        # Generate UUID for this record
        if table_name in uuid_configs:
            uuid_value = self._generate_uuid(table_name, row, uuid_configs[table_name])
            # Determine the UUID field name for this table
            model = self._get_model_for_table(table_name)
            if model:
                pk_field = model._meta.pk.name
                record[pk_field] = uuid_value
        
        # If required lookup fields were skipped, return None to exclude this record
        if skipped_required_fields:
            logger.info(f"Skipping {table_name} record due to unmapped lookup fields: {skipped_required_fields}")
            return None
        
        return record if record else None
    
    def _parse_date(self, value, date_config) -> str:
        """Parse date value according to configuration"""
        if pd.isna(value) or value == '':
            return None
        
        try:
            # Try to parse as ISO8601 first (most common format)
            dt = pd.to_datetime(value, format='ISO8601')
            return dt.strftime('%Y-%m-%d')
        except:
            try:
                # Fall back to configured format
                date_format = date_config.get('format', 'YearMonthDay')
                separator = date_config.get('separator', '-')
                
                # Map format names to pandas format strings
                format_map = {
                    'YearMonthDay': f'%Y{separator}%m{separator}%d',
                    'DayMonthYear': f'%d{separator}%m{separator}%Y',
                    'MonthDayYear': f'%m{separator}%d{separator}%Y',
                }
                
                pandas_format = format_map.get(date_format, f'%Y{separator}%m{separator}%d')
                dt = pd.to_datetime(value, format=pandas_format)
                return dt.strftime('%Y-%m-%d')
            except Exception as e:
                logger.warning(f"Failed to parse date '{value}': {e}")
                # Return the value as-is if it's already in YYYY-MM-DD format
                if isinstance(value, str) and len(value) == 10 and value[4] == '-' and value[7] == '-':
                    return value
                return None
    
    def _compute_date_from_interval(self, row, interval_config) -> str:
        """Compute date from interval configuration"""
        try:
            interval_field = interval_config['interval_field']
            interval_value = row.get(interval_field)
            
            if pd.isna(interval_value):
                return None
            
            interval_value = float(interval_value)
            interval_units = interval_config['interval_units']
            calculation_date = interval_config['calculation_date']
            calculation_type = interval_config['calculation_date_type']
            
            # Get the base date
            if calculation_date in row:
                base_date = pd.to_datetime(row[calculation_date])
            else:
                base_date = pd.to_datetime(calculation_date)
            
            # Calculate the target date
            if interval_units == 'Years':
                delta = relativedelta(years=int(interval_value))
            elif interval_units == 'Months':
                delta = relativedelta(months=int(interval_value))
            elif interval_units == 'Weeks':
                delta = timedelta(weeks=interval_value)
            elif interval_units == 'Days':
                delta = timedelta(days=interval_value)
            else:
                return None
            
            if calculation_type == 'Start':
                result_date = base_date + delta
            else:  # End date
                result_date = base_date - delta
            
            return result_date.strftime('%Y-%m-%d')
        
        except Exception as e:
            logger.warning(f"Failed to compute date from interval: {e}")
            return None
    
    def _generate_uuid(self, table_name, row, uuid_fields) -> str:
        """Generate UUID based on configured fields"""
        if not uuid_fields:
            return None
        
        # Build UUID key from field values
        uuid_parts = []
        for field in uuid_fields:
            # Remove suffixes like (static), (computed)
            clean_field = field.split(' (')[0]
            value = row.get(clean_field, '')
            uuid_parts.append(str(value))
        
        uuid_key = f"{table_name}:{'|'.join(uuid_parts)}"
        
        # Check cache
        if uuid_key not in self.uuid_cache:
            # Generate new UUID (you might want to use actual UUID generation here)
            import hashlib
            self.uuid_cache[uuid_key] = hashlib.sha256(uuid_key.encode()).hexdigest()[:32]
        
        return self.uuid_cache[uuid_key]
    
    def _get_model_for_table(self, table_name):
        """Get Django model for table name"""
        try:
            model_name = self.hierarchy_service._table_to_model_name(table_name)
            return apps.get_model('client_app', model_name)
        except Exception:
            return None
    
    def _save_json_to_db(self, json_data):
        """Save generated JSON to database"""
        # Clear existing JSON
        deleted_count = ImportDataJSON.objects.filter(import_data=self.import_data).delete()[0]
        logger.info(f"Deleted {deleted_count} existing JSON records for import {self.import_data.id}")
        
        # Save new JSON
        json_obj = ImportDataJSON.objects.create(
            import_data=self.import_data,
            json_data=json_data
        )
        
        logger.info(f"Saved new JSON to database for import {self.import_data.id}, ID: {json_obj.id}")
        
        # Log a sample of the JSON to verify lookup mappings were applied
        if 'patients' in json_data and len(json_data['patients']) > 0:
            first_patient = json_data['patients'][0]
            logger.info(f"Sample patient data: {list(first_patient.keys())}")
            if 'diagnosis' in first_patient and len(first_patient['diagnosis']) > 0:
                sample_diagnosis = first_patient['diagnosis'][0]
                logger.info(f"Sample diagnosis fields: {sample_diagnosis}")
