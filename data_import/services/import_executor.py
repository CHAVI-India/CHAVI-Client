"""
Service to execute the actual data import using DRF serializers.
"""

from django.db import transaction
from client_app.import_serializers import PatientImportSerializer
from ..models import FileImportJSON


class ImportExecutorService:
    """
    Execute the import using the generated JSON and DRF serializers.
    """
    
    @staticmethod
    def execute_import(session):
        """
        Execute the import for a session.
        Returns (success, records_created, error_message)
        """
        # Get JSON data
        json_record = FileImportJSON.objects.filter(file_import_session=session).first()
        if not json_record or not json_record.json_data:
            return False, 0, "No JSON data found"
        
        json_data = json_record.json_data
        
        # Handle both list and dict formats
        if isinstance(json_data, list):
            patients_data = json_data
        elif isinstance(json_data, dict) and 'patients' in json_data:
            patients_data = json_data['patients']
        else:
            return False, 0, "Invalid JSON structure: expected list or dict with 'patients' key"
        
        if not isinstance(patients_data, list):
            return False, 0, "Invalid JSON structure: patients data must be a list"
        
        records_created = 0
        errors = []
        created_parent_records = {}  # Track created parent records by UUID
        
        # Process each patient
        for idx, patient_data in enumerate(patients_data):
            try:
                # Preprocess: Create parent records if needed
                ImportExecutorService._create_parent_records(patient_data, created_parent_records)
                
                # Use DRF serializer to validate and create
                serializer = PatientImportSerializer(data=patient_data)
                
                if serializer.is_valid():
                    # Create patient and all nested records
                    patient = serializer.save()
                    records_created += 1
                else:
                    # Collect validation errors
                    error_msg = f"Patient {idx + 1} validation failed: {serializer.errors}"
                    errors.append(error_msg)
                    
            except Exception as e:
                error_msg = f"Patient {idx + 1} import failed: {str(e)}"
                errors.append(error_msg)
        
        if errors:
            # If there were errors, return them
            error_message = "\n".join(errors[:5])  # Show first 5 errors
            if len(errors) > 5:
                error_message += f"\n... and {len(errors) - 5} more errors"
            return False, records_created, error_message
        
        return True, records_created, None
    
    @staticmethod
    def _create_parent_records(data, created_parent_records):
        """
        Recursively process data to create parent records before child records.
        Removes _parent_records_to_create fields after processing.
        """
        from django.apps import apps
        
        if isinstance(data, dict):
            # Check if this record needs parent records created
            if '_parent_records_to_create' in data:
                parent_records_info = data.pop('_parent_records_to_create')
                
                for parent_info in parent_records_info:
                    parent_model_name = parent_info.pop('model')
                    parent_uuid = parent_info.get('id')
                    
                    # Skip if already created
                    if parent_uuid in created_parent_records:
                        continue
                    
                    try:
                        # Get model class
                        parent_model_class = apps.get_model('client_app', parent_model_name)
                        
                        # Create parent record
                        parent_record = parent_model_class.objects.create(**parent_info)
                        created_parent_records[parent_uuid] = parent_record
                        
                    except Exception as e:
                        print(f"Error creating parent {parent_model_name}: {e}")
            
            # Recursively process nested dictionaries and lists
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    ImportExecutorService._create_parent_records(value, created_parent_records)
        
        elif isinstance(data, list):
            # Process each item in list
            for item in data:
                ImportExecutorService._create_parent_records(item, created_parent_records)
