"""
UUID Matching Service

Matches generated UUIDs from Step 8 with existing records in the database.
Helps users decide whether to reuse existing records or create new ones.
"""
import logging
from typing import Dict, List
from client_app.models import Patient
from data_import.services.model_hierarchy import ModelHierarchyService

logger = logging.getLogger(__name__)


class UUIDMatcherService:
    """
    Service to match generated UUIDs with existing records in the database.
    """
    
    def __init__(self):
        self.patient_model = Patient
        self.hierarchy_service = ModelHierarchyService()
    
    def match_records_for_import(self, json_data: dict) -> Dict[str, Dict]:
        """
        Match all generated records in the JSON with existing records in the database.
        
        Args:
            json_data: The generated JSON from Step 8 with UUIDs
            
        Returns:
            Dictionary organized by patient_id with match results
        """
        results = {}
        
        # Process each patient in the import
        for patient_data in json_data.get('patients', []):
            patient_id = patient_data.get('patient_id')
            
            if not patient_id:
                continue
            
            # Check if patient exists
            existing_patient = self._get_existing_patient(patient_id)
            
            patient_result = {
                'patient_id': patient_id,
                'patient_exists': existing_patient is not None,
                'patient_data': {
                    'gender': patient_data.get('gender'),
                    'date_of_birth': patient_data.get('date_of_birth'),
                    'date_of_registration': patient_data.get('date_of_registration')
                },
                'matches': {}
            }
            
            if existing_patient:
                # Match nested records for each table
                patient_result['matches'] = self._match_nested_records(
                    patient_data, 
                    existing_patient
                )
            
            results[patient_id] = patient_result
        
        return results
    
    def _get_existing_patient(self, patient_id: str):
        """Get existing patient from database with all related records"""
        try:
            # Build prefetch paths dynamically using model hierarchy
            prefetch_paths = self._build_prefetch_paths()
            
            return self.patient_model.objects.prefetch_related(
                *prefetch_paths
            ).get(patient_id=patient_id)
        except self.patient_model.DoesNotExist:
            return None
    
    def _build_prefetch_paths(self) -> List[str]:
        """
        Build prefetch_related paths dynamically using ModelHierarchyService.
        
        Returns:
            List of prefetch paths like ['diagnosis_set__pathology_set', ...]
        """
        prefetch_paths = []
        
        # Get all models and their relationships
        for model_name, model in self.hierarchy_service.client_app_models.items():
            # Skip Patient itself
            if model_name == 'Patient':
                continue
            
            # Get dependency chain from Patient to this model
            chain = self.hierarchy_service.get_dependency_chain(model_name)
            
            if not chain or chain[0] != 'Patient':
                continue
            
            # Build prefetch path from the chain
            # Example: ['Patient', 'Diagnosis', 'Pathology'] -> 'diagnosis_set__pathology_set'
            if len(chain) > 1:
                path_parts = []
                for i in range(1, len(chain)):
                    table_name = self.hierarchy_service._model_to_table_map.get(chain[i])
                    if table_name:
                        path_parts.append(f"{table_name}_set")
                
                if path_parts:
                    prefetch_path = '__'.join(path_parts)
                    prefetch_paths.append(prefetch_path)
        
        # Remove duplicates and sort
        prefetch_paths = sorted(set(prefetch_paths))
        
        logger.debug(f"Built prefetch paths: {prefetch_paths}")
        return prefetch_paths
    
    def _match_nested_records(self, import_data: dict, existing_patient) -> Dict[str, List]:
        """
        Match nested records dynamically using ModelHierarchyService.
        """
        matches = {}
        
        # Get all direct children of Patient model
        patient_children = self.hierarchy_service.get_child_models('Patient')
        
        for table_name, pk_field in patient_children.items():
            if table_name in import_data:
                # Get existing records for this table
                existing_records = getattr(existing_patient, f"{table_name}_set", None)
                if existing_records:
                    existing_list = list(existing_records.all())
                    
                    # Check if this table has children (for recursive matching)
                    model_name = self.hierarchy_service._table_to_model_name(table_name)
                    has_children = bool(self.hierarchy_service.get_child_models(model_name))
                    
                    matches[table_name] = self._match_table_records(
                        table_name=table_name,
                        import_records=import_data[table_name],
                        existing_records=existing_list,
                        pk_field=pk_field,
                        parent_records=existing_list if has_children else None
                    )
        
        return matches
    
    def _match_table_records(self, table_name: str, import_records: List[dict], 
                            existing_records: List, pk_field: str, 
                            parent_records=None) -> List[Dict]:
        """
        Generic method to match records for any table.
        
        Args:
            table_name: Name of the table (e.g., 'diagnosis', 'pathology')
            import_records: List of import record dicts
            existing_records: List of existing model instances
            pk_field: Primary key field name (e.g., 'diagnosis_id')
            parent_records: Parent records for nested matching (optional)
        """
        matches = []
        
        # Serialize all existing records
        serialized_existing = [
            {
                'uuid': str(getattr(record, pk_field)),
                'data': self._serialize_model_instance(record)
            }
            for record in existing_records
        ]
        
        for import_record in import_records:
            generated_uuid = import_record.get(pk_field)
            
            match_entry = {
                'table_name': table_name,
                'generated_uuid': generated_uuid,
                'import_data': import_record,
                'existing_records': serialized_existing,
                'nested_matches': {}
            }
            
            # Handle nested records if parent_records provided
            if parent_records:
                # Use ModelHierarchyService to get child models dynamically
                model_name = self.hierarchy_service._table_to_model_name(table_name)
                nested_tables = self.hierarchy_service.get_child_models(model_name)
                
                for nested_table, nested_pk in nested_tables.items():
                    if nested_table in import_record:
                        # Get all existing nested records from parent records
                        existing_nested = []
                        for parent in parent_records:
                            nested_set = getattr(parent, f"{nested_table}_set", None)
                            if nested_set:
                                existing_nested.extend(list(nested_set.all()))
                        
                        # Determine if this nested table has its own children
                        nested_model_name = self.hierarchy_service._table_to_model_name(nested_table)
                        has_children = bool(self.hierarchy_service.get_child_models(nested_model_name))
                        
                        match_entry['nested_matches'][nested_table] = self._match_table_records(
                            table_name=nested_table,
                            import_records=import_record[nested_table],
                            existing_records=existing_nested,
                            pk_field=nested_pk,
                            parent_records=existing_nested if has_children else None
                        )
            
            matches.append(match_entry)
        
        return matches
    
    def _serialize_model_instance(self, instance) -> dict:
        """
        Generic method to serialize any model instance to dict for display.
        """
        return {
            field.name: str(getattr(instance, field.name, None)) if getattr(instance, field.name, None) is not None else None
            for field in instance._meta.fields
        }
