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
    UUIDFieldConfiguration, ImportDataJSON
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
        
        # Build hierarchical JSON structure
        json_data = self._build_hierarchical_json(
            field_mappings, static_mappings, date_formats, 
            date_intervals, uuid_configs
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
    
    def _build_hierarchical_json(self, field_mappings, static_mappings, 
                                  date_formats, date_intervals, uuid_configs) -> dict:
        """Build the hierarchical JSON structure"""
        
        # Group data by Patient first
        patient_data = defaultdict(lambda: defaultdict(list))
        
        for index, row in self.df.iterrows():
            # Generate/get patient UUID
            patient_uuid = self._generate_uuid('patient', row, uuid_configs.get('patient', []))
            
            # Process each table's data for this row
            for table_name, mappings in field_mappings.items():
                record = self._build_record(
                    table_name, row, mappings, 
                    static_mappings.get(table_name, []),
                    date_formats, date_intervals, uuid_configs
                )
                
                if record:
                    patient_data[patient_uuid][table_name].append(record)
        
        # Convert to final structure
        result = {
            'patients': []
        }
        
        for patient_uuid, tables in patient_data.items():
            patient_record = {
                'patient_id': patient_uuid,
                **tables
            }
            result['patients'].append(patient_record)
        
        return result
    
    def _build_record(self, table_name, row, field_mappings, static_mappings,
                     date_formats, date_intervals, uuid_configs) -> dict:
        """Build a single record for a table"""
        record = {}
        
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
        
        return record if record else None
    
    def _parse_date(self, value, date_config) -> str:
        """Parse date value according to configuration"""
        if pd.isna(value) or value == '':
            return None
        
        try:
            # Build format string
            date_format = date_config['format']
            separator = date_config['separator']
            
            # Convert to datetime
            dt = pd.to_datetime(value, format=f"{date_format}")
            return dt.strftime('%Y-%m-%d')
        except Exception as e:
            logger.warning(f"Failed to parse date '{value}': {e}")
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
        ImportDataJSON.objects.filter(import_data=self.import_data).delete()
        
        # Save new JSON
        ImportDataJSON.objects.create(
            import_data=self.import_data,
            json_data=json_data
        )
        
        logger.info(f"Saved JSON to database for import {self.import_data.id}")
