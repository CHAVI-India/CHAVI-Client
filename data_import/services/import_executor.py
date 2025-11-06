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
        
        # Process each patient
        for idx, patient_data in enumerate(patients_data):
            try:
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
