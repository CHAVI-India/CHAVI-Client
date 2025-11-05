"""Service to execute import using DRF serializers"""
import logging
from django.db import transaction
from django.apps import apps
from data_import.models import ImportData, ImportStatus
from client_app.serializers import PatientSerializer, DiagnosisSerializer

logger = logging.getLogger(__name__)


class ImportExecutorService:
    """
    Executes the import using Django REST Framework serializers.
    Imports data from the generated JSON into the database.
    """
    
    def __init__(self, import_data: ImportData):
        self.import_data = import_data
        self.successful_records = 0
        self.failed_records = 0
        self.errors = []
        
        # Map table names to serializers
        self.serializer_map = self._build_serializer_map()
    
    def _build_serializer_map(self):
        """Build mapping of table names to DRF serializers"""
        from client_app import serializers as client_serializers
        
        serializer_map = {}
        
        # Get all serializer classes from client_app.serializers
        for name in dir(client_serializers):
            if name.endswith('Serializer') and name != 'BaseSerializer':
                serializer_class = getattr(client_serializers, name)
                if hasattr(serializer_class, 'Meta') and hasattr(serializer_class.Meta, 'model'):
                    model = serializer_class.Meta.model
                    table_name = model._meta.db_table
                    serializer_map[table_name] = serializer_class
        
        return serializer_map
    
    def execute_import(self, json_data: dict) -> dict:
        """
        Execute the import from JSON data using DRF serializers.
        
        Args:
            json_data: The JSON data to import
            
        Returns:
            Dictionary with import statistics
        """
        logger.info(f"Starting import execution for import {self.import_data.id}")
        
        try:
            with transaction.atomic():
                # Process patients
                if 'patients' in json_data:
                    for patient_data in json_data['patients']:
                        self._import_patient(patient_data)
            
            logger.info(f"Import completed: {self.successful_records} successful, {self.failed_records} failed")
            
            return {
                'successful_records': self.successful_records,
                'failed_records': self.failed_records,
                'errors': self.errors
            }
            
        except Exception as e:
            logger.error(f"Import execution failed: {e}", exc_info=True)
            raise
    
    def _import_patient(self, patient_data: dict):
        """
        Import a single patient and all related records.
        
        Args:
            patient_data: Patient data including nested records
        """
        try:
            # Extract patient fields
            patient_fields = {
                'patient_id': patient_data.get('patient_id'),
                'gender': patient_data.get('gender'),
                'date_of_birth': patient_data.get('date_of_birth'),
                'date_of_registration': patient_data.get('date_of_registration'),
            }
            
            # Remove None values
            patient_fields = {k: v for k, v in patient_fields.items() if v is not None}
            
            # Create or update patient using serializer
            patient_serializer = PatientSerializer(data=patient_fields)
            
            if patient_serializer.is_valid():
                patient = patient_serializer.save()
                self.successful_records += 1
                logger.info(f"Created/updated patient: {patient.patient_id}")
                
                # Import related records
                self._import_related_records(patient, patient_data)
            else:
                self.failed_records += 1
                self.errors.append({
                    'record_type': 'patient',
                    'record_id': patient_data.get('patient_id'),
                    'errors': patient_serializer.errors
                })
                logger.error(f"Patient validation failed: {patient_serializer.errors}")
                
        except Exception as e:
            self.failed_records += 1
            self.errors.append({
                'record_type': 'patient',
                'record_id': patient_data.get('patient_id'),
                'error': str(e)
            })
            logger.error(f"Error importing patient: {e}", exc_info=True)
    
    def _import_related_records(self, patient, patient_data: dict):
        """
        Import all records related to a patient.
        
        Args:
            patient: The patient instance
            patient_data: Full patient data including nested records
        """
        # Process each table's records
        for table_name, records in patient_data.items():
            if table_name == 'patient_id' or not isinstance(records, list):
                continue
            
            serializer_class = self.serializer_map.get(table_name)
            if not serializer_class:
                logger.warning(f"No serializer found for table: {table_name}")
                continue
            
            for record_data in records:
                self._import_record(
                    serializer_class,
                    record_data,
                    table_name,
                    patient
                )
    
    def _import_record(self, serializer_class, record_data: dict, 
                      table_name: str, patient=None):
        """
        Import a single record using its serializer.
        
        Args:
            serializer_class: DRF serializer class
            record_data: Record data
            table_name: Table name
            patient: Parent patient instance (if applicable)
        """
        try:
            # Add patient reference if needed
            if patient and 'patient' not in record_data:
                # Check if model has patient field
                model = serializer_class.Meta.model
                if hasattr(model, 'patient'):
                    record_data['patient'] = patient.patient_id
            
            # Create record using serializer
            serializer = serializer_class(data=record_data)
            
            if serializer.is_valid():
                instance = serializer.save()
                self.successful_records += 1
                logger.debug(f"Created {table_name} record: {instance.pk}")
                
                # Handle nested records (e.g., Pathology -> Immunohistochemistry)
                self._import_nested_records(instance, record_data, table_name)
            else:
                self.failed_records += 1
                self.errors.append({
                    'record_type': table_name,
                    'record_data': record_data,
                    'errors': serializer.errors
                })
                logger.error(f"{table_name} validation failed: {serializer.errors}")
                
        except Exception as e:
            self.failed_records += 1
            self.errors.append({
                'record_type': table_name,
                'record_data': record_data,
                'error': str(e)
            })
            logger.error(f"Error importing {table_name} record: {e}", exc_info=True)
    
    def _import_nested_records(self, parent_instance, parent_data: dict, parent_table: str):
        """
        Import nested records (e.g., Immunohistochemistry under Pathology).
        
        Args:
            parent_instance: Parent model instance
            parent_data: Parent data that may contain nested records
            parent_table: Parent table name
        """
        # Define nested relationships
        nested_relationships = {
            'diagnosis': ['pathology', 'outcome', 'lesion', 'other_treatment', 
                         'radiotherapy', 'surgery', 'concomitant_medications',
                         'systemic_therapy', 'adverse_effects', 'stage_information'],
            'pathology': ['immunohistochemistry', 'cytogenetics', 
                         'somatic_genomic_alterations', 'gene_expression_data',
                         'epigenetic_data'],
            'lesion': ['lesion_response'],
            'radiotherapy': ['radiotherapy_volume', 'radiotherapy_dose_volume_data'],
            'systemic_therapy': ['systemic_therapy_schedule'],
        }
        
        # Check if this table has nested relationships
        if parent_table not in nested_relationships:
            return
        
        # Process each nested table
        for nested_table in nested_relationships[parent_table]:
            if nested_table in parent_data and isinstance(parent_data[nested_table], list):
                serializer_class = self.serializer_map.get(nested_table)
                
                if serializer_class:
                    for nested_record in parent_data[nested_table]:
                        # Add parent reference
                        parent_field_name = parent_table  # e.g., 'diagnosis', 'pathology'
                        if parent_field_name not in nested_record:
                            nested_record[parent_field_name] = parent_instance.pk
                        
                        self._import_record(
                            serializer_class,
                            nested_record,
                            nested_table
                        )
