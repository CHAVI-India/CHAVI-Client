"""
JSON Generator Service for Data Import.
Generates JSON that matches nested DRF serializer format for import.
"""

from django.apps import apps
from .csv_processor import CSVProcessorService
from .field_introspection import FieldIntrospectionService
from .model_hierarchy import ModelHierarchyService
from ..models import (
    FileMappedModel, FileMappedField, FilePatientID,
    FileColumnFieldValueMapping, FileDateFieldMapping,
    FileDurationDateMapping, FieldLookupValues, FileMissingRelations,
    FileDefaultValues, FileParentRecordMapping, FileImportUUIDValues
)
from datetime import datetime, timedelta
from dateutil import parser as date_parser
import uuid


class UUIDManager:
    """Manage UUIDs for import records."""
    
    def __init__(self, session):
        self.session = session
        self.uuid_cache = {}
        self._load_existing_uuids()
    
    def _load_existing_uuids(self):
        """Load existing UUIDs from database."""
        existing = FileImportUUIDValues.objects.filter(file_import_session=self.session)
        for uuid_obj in existing:
            key = (uuid_obj.client_app_model_name, uuid_obj.client_app_model_pk)
            self.uuid_cache[key] = uuid_obj.client_app_model_pk_uuid_value
    
    def get_uuid(self, model_name, pk_field_name, record_key):
        """Get or create UUID for a record."""
        cache_key = (model_name, pk_field_name, record_key)
        
        if cache_key not in self.uuid_cache:
            # Generate new UUID
            new_uuid = str(uuid.uuid4())
            self.uuid_cache[cache_key] = new_uuid
            
            # Store in database
            FileImportUUIDValues.objects.create(
                file_import_session=self.session,
                client_app_model_name=model_name,
                client_app_model_pk=pk_field_name,
                client_app_model_pk_uuid_value=new_uuid
            )
        
        return self.uuid_cache[cache_key]


class JSONGeneratorService:
    """Generate import JSON from CSV data and mappings."""
    
    @staticmethod
    def generate_import_json(session, sample_only=False, sample_size=3):
        """
        Generate complete JSON for import based on all mappings.
        
        Args:
            session: FileImportSession instance
            sample_only: If True, only generate sample records for preview
            sample_size: Number of sample records to generate
            
        Returns:
            list: List of patient records with nested relationships
        """
        # Get CSV data
        from ..views.base import BaseImportView
        base_view = BaseImportView()
        headers, rows, error = base_view.get_csv_data(session)
        
        if error or not rows:
            return []
        
        # Get all mappings
        mappings = JSONGeneratorService._get_all_mappings(session)
        
        if not session.patient_id_column:
            return []
        
        # Initialize UUID manager
        uuid_manager = UUIDManager(session)
        
        # Group rows by patient_id
        patient_id_col = session.patient_id_column
        patient_groups = JSONGeneratorService._group_by_patient(rows, headers, patient_id_col)
        
        # Limit to sample if requested
        if sample_only:
            patient_groups = dict(list(patient_groups.items())[:sample_size])
        
        # Generate patient records
        patient_records = []
        for patient_id, patient_rows in patient_groups.items():
            try:
                patient_record = JSONGeneratorService._generate_patient_record(
                    patient_id, patient_rows, headers, mappings, session, uuid_manager
                )
                if patient_record:
                    patient_records.append(patient_record)
            except Exception as e:
                print(f"Error generating record for patient {patient_id}: {str(e)}")
                continue
        
        return patient_records
    
    @staticmethod
    def _get_all_mappings(session):
        """Get all mapping configurations."""
        mapped_model = FileMappedModel.objects.filter(file_import_session=session).first()
        
        # Build lookup mappings: {csv_column: {csv_value: lookup_code}}
        lookup_mappings = {}
        for lookup in FieldLookupValues.objects.filter(file_import_session=session):
            if lookup.csv_column_name not in lookup_mappings:
                lookup_mappings[lookup.csv_column_name] = {}
            if lookup.csv_value:
                lookup_mappings[lookup.csv_column_name][lookup.csv_value] = lookup.lookup_value
        
        # Combine default values (Step 9) and missing relations (Step 10 - deprecated)
        default_and_missing = {}
        # Add default values
        for dv in FileDefaultValues.objects.filter(file_import_session=session):
            default_and_missing[(dv.client_app_model_name, dv.client_app_field_name)] = dv.client_app_field_value
        # Add missing relations (these can override defaults if needed)
        for mr in FileMissingRelations.objects.filter(file_import_session=session):
            default_and_missing[(mr.client_app_model_name, mr.client_app_field_name)] = mr.client_app_field_value
        
        # Get parent record mappings (Step 10 - new system)
        parent_mappings = {}
        for pm in FileParentRecordMapping.objects.filter(file_import_session=session):
            parent_mappings[(pm.child_model_name, pm.parent_fk_field)] = {
                'parent_model': pm.parent_model_name,
                'link_to_existing': pm.link_to_existing,
                'existing_record_id': pm.existing_record_id,
                'create_new_parent': pm.create_new_parent,
                'parent_field_values': pm.parent_field_values or {},
            }
        
        return {
            'selected_models': mapped_model.client_app_model_name if mapped_model else [],
            'field_mappings': list(FileMappedField.objects.filter(file_import_session=session)),
            'column_value_mappings': list(FileColumnFieldValueMapping.objects.filter(file_import_session=session)),
            'date_formats': {m.csv_column_name: m.date_format 
                           for m in FileDateFieldMapping.objects.filter(file_import_session=session)},
            'duration_mappings': list(FileDurationDateMapping.objects.filter(file_import_session=session)),
            'lookup_mappings': lookup_mappings,
            'missing_relations': default_and_missing,  # Combined default values and missing relations
            'parent_mappings': parent_mappings,  # Parent record mappings from Step 10
        }
    
    @staticmethod
    def _group_by_patient(rows, headers, patient_id_col):
        """Group CSV rows by patient ID."""
        patient_groups = {}
        
        if patient_id_col not in headers:
            return patient_groups
        
        col_index = headers.index(patient_id_col)
        
        for row in rows:
            if isinstance(row, dict):
                patient_id = str(row.get(patient_id_col, '')).strip()
            else:
                patient_id = str(row[col_index]).strip() if col_index < len(row) else ''
            
            if patient_id:
                if patient_id not in patient_groups:
                    patient_groups[patient_id] = []
                patient_groups[patient_id].append(row)
        
        return patient_groups
    
    @staticmethod
    def _generate_patient_record(patient_id, patient_rows, headers, mappings, session, uuid_manager):
        """Generate a single patient record with nested relationships."""
        patient_data = {'patient_id': patient_id}
        record_counter = {'count': 0}  # Counter for generating unique record keys
        
        # Get model hierarchy
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        selected_models = list(mappings['selected_models'])
        
        # Add parent models from parent_mappings if not already selected
        # This ensures models created via Step 10 are included in the JSON
        parent_models_to_add = set()
        for parent_mapping in mappings.get('parent_mappings', {}).values():
            parent_model = parent_mapping.get('parent_model')
            if parent_model and parent_model not in selected_models:
                parent_models_to_add.add(parent_model)
                selected_models.append(parent_model)
        
        # Separate models by level and adjust for auto-created parents
        # Models whose parents are auto-created should be treated as direct children of Patient
        adjusted_hierarchy = {}
        
        for model in selected_models:
            original_level = hierarchy.get(model, 0)
            
            # Check if any parent is auto-created
            parent_models_dict = ModelHierarchyService.get_parent_models(model)
            has_auto_created_parent = False
            
            for fk_field, parent_model in parent_models_dict.items():
                if parent_model in parent_models_to_add:
                    # Parent is auto-created, treat this model as Level 1 (direct child of Patient)
                    has_auto_created_parent = True
                    break
            
            if has_auto_created_parent:
                adjusted_hierarchy[model] = 1  # Promote to Level 1
            else:
                adjusted_hierarchy[model] = original_level
        
        # Separate models by adjusted level
        level_0_models = [m for m in selected_models if adjusted_hierarchy.get(m) == 0]  # Patient
        level_1_plus_models = [m for m in selected_models if adjusted_hierarchy.get(m, 0) >= 1]  # All non-Patient models
        
        # Track UUIDs of auto-created parent records so children can reference them
        parent_uuids = {}  # {parent_model_name: uuid}
        
        # Process Patient fields (Level 0)
        for mapping in mappings['field_mappings']:
            if '.' not in mapping.mapped_client_app_field_name:
                continue
            
            model_name, field_name = mapping.mapped_client_app_field_name.split('.', 1)
            
            if model_name == 'Patient':
                # Get value from first row (Patient fields should be same across rows)
                value = JSONGeneratorService._get_field_value(
                    patient_rows[0], headers, mapping, mappings
                )
                if value is not None:
                    patient_data[field_name] = value
        
        # Add missing relations for Patient
        for (model_name, field_name), value in mappings['missing_relations'].items():
            if model_name == 'Patient':
                patient_data[field_name] = JSONGeneratorService._resolve_relation_value(value, headers, patient_rows[0])
        
        # Process all child models of Patient recursively
        JSONGeneratorService._add_child_models(
            patient_data, 'Patient', level_1_plus_models, patient_rows, headers, 
            mappings, uuid_manager, patient_id, record_counter, parent_uuids, parent_models_to_add
        )
        
        return patient_data
    
    @staticmethod
    def _add_child_models(parent_record, parent_model_name, all_models, patient_rows, headers, 
                         mappings, uuid_manager, patient_id, record_counter, parent_uuids, parent_models_to_add):
        """Recursively add child models to a parent record."""
        # Find direct children of this parent
        for model_name in all_models:
            parent_models_dict = ModelHierarchyService.get_parent_models(model_name)
            
            # Check if this model is a direct child of the parent
            if parent_model_name not in parent_models_dict.values():
                continue
            
            set_name = f"{model_name.lower()}_set"
            parent_record[set_name] = []
            
            # Check if this model is only created via parent mapping (no CSV fields mapped)
            has_csv_mappings = any(
                m.mapped_client_app_field_name.startswith(f"{model_name}.")
                for m in mappings['field_mappings']
            )
            
            # If model is created via parent mapping only, create one record with parent field values
            if not has_csv_mappings and model_name in parent_models_to_add:
                # Find parent mapping that creates this model
                for (child_model, fk_field), parent_mapping in mappings.get('parent_mappings', {}).items():
                    if parent_mapping.get('parent_model') == model_name and parent_mapping.get('create_new_parent'):
                        # Create parent record with field values from Step 10
                        auto_created_record = {}
                        
                        # Add UUID for primary key
                        pk_field = JSONGeneratorService._get_pk_field_name(model_name)
                        model_uuid = None
                        if pk_field:
                            record_counter['count'] += 1
                            record_key = f"{patient_id}_{model_name}_parent_{record_counter['count']}"
                            model_uuid = uuid_manager.get_uuid(model_name, pk_field, record_key)
                            auto_created_record[pk_field] = model_uuid
                        
                        # Store UUID for children to reference
                        if model_uuid:
                            parent_uuids[model_name] = model_uuid
                        
                        # Add patient FK if this is a Level 1 model
                        if parent_model_name == 'Patient':
                            auto_created_record['patient_id'] = patient_id
                        
                        # Add field values from parent mapping
                        for field_name, field_value in parent_mapping.get('parent_field_values', {}).items():
                            auto_created_record[field_name] = field_value
                        
                        # Recursively add children of this auto-created model
                        remaining_models = [m for m in all_models if m != model_name]
                        JSONGeneratorService._add_child_models(
                            auto_created_record, model_name, remaining_models, patient_rows, headers,
                            mappings, uuid_manager, patient_id, record_counter, parent_uuids, parent_models_to_add
                        )
                        
                        parent_record[set_name].append(auto_created_record)
                        break  # Only create one parent record
            else:
                # Model has CSV mappings - process normally
                # Check if this is wide-format data
                column_value_records = JSONGeneratorService._get_column_value_records(
                    model_name, patient_rows[0], headers, mappings, uuid_manager, patient_id, record_counter
                )
                
                if column_value_records:
                    # Wide format
                    parent_record[set_name].extend(column_value_records)
                else:
                    # Long format - process each row
                    # Get children of this model for recursive processing
                    children = [m for m in all_models if m != model_name and 
                               model_name in ModelHierarchyService.get_parent_models(m).values()]
                    
                    for row in patient_rows:
                        record = JSONGeneratorService._generate_model_record(
                            model_name, row, headers, mappings, children, uuid_manager, patient_id, record_counter, parent_uuids
                        )
                        if record and record not in parent_record[set_name]:
                            parent_record[set_name].append(record)
    
    @staticmethod
    def _get_field_value(row, headers, mapping, mappings):
        """Get field value from CSV row with transformations."""
        csv_columns = mapping.csv_field_names
        if not csv_columns:
            return None
        
        # Get raw value(s)
        values = []
        for col in csv_columns:
            if col in headers:
                col_index = headers.index(col)
                if isinstance(row, dict):
                    val = row.get(col, '')
                else:
                    val = row[col_index] if col_index < len(row) else ''
                values.append(str(val).strip())
        
        if not values or not any(values):
            return None
        
        # Get field info
        model_name, field_name = mapping.mapped_client_app_field_name.split('.', 1)
        field_info = FieldIntrospectionService.get_model_fields(model_name).get(field_name, {})
        field_type = field_info.get('type', '')
        
        # Apply transformations based on field type
        if field_type in ['DateField', 'DateTimeField']:
            return JSONGeneratorService._parse_date(values[0], csv_columns[0], mappings)
        elif field_type == 'BooleanField':
            return JSONGeneratorService._parse_boolean(values[0])
        elif field_type in ['IntegerField', 'PositiveIntegerField']:
            try:
                return int(float(values[0])) if values[0] else None
            except:
                return None
        elif field_type in ['FloatField', 'DecimalField']:
            try:
                return float(values[0]) if values[0] else None
            except:
                return None
        elif field_info.get('is_fk') or field_info.get('is_lookup'):
            # Foreign key or lookup - apply lookup mapping if available
            csv_value = values[0] if values[0] else None
            if csv_value and csv_columns:
                # Check if there's a lookup mapping for this column
                csv_column = csv_columns[0]
                if csv_column in mappings.get('lookup_mappings', {}):
                    # Map CSV value to lookup code
                    return mappings['lookup_mappings'][csv_column].get(csv_value, csv_value)
            return csv_value
        else:
            # CharField, TextField, etc - combine if multiple columns
            return ' '.join(values) if len(values) > 1 else values[0]
    
    @staticmethod
    def _parse_date(value, column_name, mappings):
        """Parse date value using configured format."""
        if not value:
            return None
        
        date_format = mappings['date_formats'].get(column_name)
        
        if date_format:
            # Use configured format
            format_map = {
                'YYYY-MM-DD': '%Y-%m-%d',
                'DD-MM-YYYY': '%d-%m-%Y',
                'MM-DD-YYYY': '%m-%d-%Y',
                'YYYY/MM/DD': '%Y/%m/%d',
                'DD/MM/YYYY': '%d/%m/%Y',
                'MM/DD/YYYY': '%m/%d/%Y',
            }
            py_format = format_map.get(date_format)
            if py_format:
                try:
                    return datetime.strptime(value, py_format).date().isoformat()
                except:
                    pass
        
        # Try auto-parse
        try:
            return date_parser.parse(value).date().isoformat()
        except:
            return None
    
    @staticmethod
    def _parse_boolean(value):
        """Parse boolean value."""
        if not value:
            return None
        value_lower = str(value).lower().strip()
        if value_lower in ['true', 'yes', '1', 'y']:
            return True
        elif value_lower in ['false', 'no', '0', 'n']:
            return False
        return None
    
    @staticmethod
    def _get_column_value_records(model_name, row, headers, mappings, uuid_manager, patient_id, record_counter):
        """Get records from column-value mappings (wide format)."""
        records = []
        
        for mapping in mappings['column_value_mappings']:
            if '.' not in mapping.mapped_client_app_field_name:
                continue
            
            map_model, map_field = mapping.mapped_client_app_field_name.split('.', 1)
            
            if map_model == model_name:
                # Check if this column has a positive value
                csv_col = mapping.csv_column_name
                if csv_col in headers:
                    col_index = headers.index(csv_col)
                    if isinstance(row, dict):
                        csv_value = str(row.get(csv_col, '')).strip()
                    else:
                        csv_value = str(row[col_index]).strip() if col_index < len(row) else ''
                    
                    # Check if value indicates presence
                    if csv_value.lower() in ['yes', 'true', '1', 'y']:
                        record = {}
                        
                        # Add UUID for primary key
                        pk_field = JSONGeneratorService._get_pk_field_name(model_name)
                        if pk_field:
                            record_counter['count'] += 1
                            record_key = f"{patient_id}_{model_name}_{record_counter['count']}"
                            record[pk_field] = uuid_manager.get_uuid(model_name, pk_field, record_key)
                        
                        # Add the mapped field value
                        record[map_field] = mapping.client_app_field_value
                        
                        # Add missing relations for this model
                        for (rel_model, rel_field), rel_value in mappings['missing_relations'].items():
                            if rel_model == model_name:
                                record[rel_field] = JSONGeneratorService._resolve_relation_value(rel_value, headers, row)
                        
                        records.append(record)
        
        return records
    
    @staticmethod
    def _generate_model_record(model_name, row, headers, mappings, child_models, uuid_manager, patient_id, record_counter, parent_uuids=None):
        """Generate a record for a specific model."""
        if parent_uuids is None:
            parent_uuids = {}
        record = {}
        has_data = False
        
        # Add UUID for primary key (except Patient which uses patient_id)
        if model_name != 'Patient':
            pk_field = JSONGeneratorService._get_pk_field_name(model_name)
            if pk_field:
                record_counter['count'] += 1
                record_key = f"{patient_id}_{model_name}_{record_counter['count']}"
                record[pk_field] = uuid_manager.get_uuid(model_name, pk_field, record_key)
        
        # Get field mappings for this model
        for mapping in mappings['field_mappings']:
            if '.' not in mapping.mapped_client_app_field_name:
                continue
            
            map_model, map_field = mapping.mapped_client_app_field_name.split('.', 1)
            
            if map_model == model_name:
                value = JSONGeneratorService._get_field_value(row, headers, mapping, mappings)
                if value is not None:
                    # Check if field is ManyToMany - wrap value in list
                    field_info = FieldIntrospectionService.get_model_fields(model_name).get(map_field, {})
                    if field_info.get('type') == 'ManyToManyField':
                        # Ensure value is a list
                        if not isinstance(value, list):
                            record[map_field] = [value] if value else []
                        else:
                            record[map_field] = value
                    else:
                        record[map_field] = value
                    has_data = True
        
        # Add missing relations (default values from Step 9 and missing relations from Step 10)
        for (rel_model, rel_field), rel_value in mappings['missing_relations'].items():
            if rel_model == model_name:
                record[rel_field] = JSONGeneratorService._resolve_relation_value(rel_value, headers, row)
                has_data = True  # Default values count as data
        
        # Handle parent FK relationships (Step 10 - new system)
        for (child_model, fk_field), parent_mapping in mappings.get('parent_mappings', {}).items():
            if child_model == model_name:
                parent_model = parent_mapping['parent_model']
                
                # Auto-handle Patient FK
                if parent_model == 'Patient':
                    record[fk_field] = patient_id
                    has_data = True
                
                # Link to existing parent record
                elif parent_mapping['link_to_existing'] and parent_mapping['existing_record_id']:
                    record[fk_field] = parent_mapping['existing_record_id']
                    has_data = True
                
                # Create new parent record - use stored UUID if parent was already created
                elif parent_mapping['create_new_parent']:
                    # Check if parent UUID was already created in Level 1 loop
                    if parent_model in parent_uuids:
                        # Reuse existing parent UUID
                        record[fk_field] = parent_uuids[parent_model]
                        has_data = True
                    else:
                        # Parent not yet created (shouldn't happen with new logic, but keep as fallback)
                        parent_pk_field = JSONGeneratorService._get_pk_field_name(parent_model)
                        if parent_pk_field:
                            record_counter['count'] += 1
                            parent_record_key = f"{patient_id}_{parent_model}_new_{record_counter['count']}"
                            parent_uuid = uuid_manager.get_uuid(parent_model, parent_pk_field, parent_record_key)
                            record[fk_field] = parent_uuid
                            
                            # Store parent creation info in a special field for import executor
                            if '_parent_records_to_create' not in record:
                                record['_parent_records_to_create'] = []
                            
                            parent_record_data = {
                                'model': parent_model,
                                'id': parent_uuid,
                                'patient_id': patient_id,
                                **parent_mapping['parent_field_values']
                            }
                            record['_parent_records_to_create'].append(parent_record_data)
                            has_data = True
        
        if not has_data and model_name != 'Patient':
            return None
        
        # Add child models (Level 2)
        for child_model in child_models:
            parent_models = ModelHierarchyService.get_parent_models(child_model)
            if model_name in parent_models.values():
                set_name = f"{child_model.lower()}_set"
                record[set_name] = []
                
                child_record = JSONGeneratorService._generate_model_record(
                    child_model, row, headers, mappings, [], uuid_manager, patient_id, record_counter
                )
                if child_record:
                    record[set_name].append(child_record)
        
        return record
    
    @staticmethod
    def _resolve_relation_value(value, headers, row):
        """Resolve relation value - could be CSV column or fixed value."""
        if not value:
            return None
        
        # Check if it's a CSV column reference
        if value.startswith('CSV:'):
            col_name = value[4:]
            if col_name in headers:
                col_index = headers.index(col_name)
                if isinstance(row, dict):
                    return str(row.get(col_name, '')).strip()
                else:
                    return str(row[col_index]).strip() if col_index < len(row) else ''
        
        # Fixed value
        return value
    
    @staticmethod
    def _get_pk_field_name(model_name):
        """Get the primary key field name for a model."""
        pk_map = {
            'Diagnosis': 'chavi_diagnosis_id',
            'Comorbidity': 'chavi_comorbidity_id',
            'Symptom': 'chavi_symptom_id',
            'Pathology': 'chavi_pathology_id',
            'Immunohistochemistry': 'chavi_ihc_id',
            'Cytogenetics': 'chavi_cytogenetics_id',
            'SomaticGenomicAlterations': 'chavi_somatic_genomic_id',
            'GeneExpressionData': 'chavi_gene_expression_id',
            'EpigeneticData': 'chavi_epigenetic_id',
            'Lesion': 'chavi_lesion_id',
            'LesionResponse': 'chavi_lesion_response_id',
            'Surgery': 'chavi_surgery_id',
            'Radiotherapy': 'chavi_radiotherapy_id',
            'SystemicTherapy': 'chavi_systemic_therapy_id',
            'OtherTreatment': 'chavi_treatment_id',
            'Outcome': 'chavi_outcome_id',
            'AdverseEffect': 'chavi_adverse_effect_id',
            'GermlineGenomicAlterations': 'chavi_germline_genomic_id',
            'PatientOutcome': 'chavi_patient_outcome_id',
            'PatientAssessment': 'chavi_patient_assessment_id',
            'LaboratoryResults': 'chavi_laboratory_results_id',
            'PatientReportedOutcome': 'chavi_pro_id',
        }
        return pk_map.get(model_name)
