# Data Import Models - Review Summary

## Date: November 6, 2025

## Issues Fixed ✅

### 1. **Critical Typo Fixed**
- **Line 59**: Changed `class FileMappedModel(model.Model)` to `models.Model`

### 2. **Improved `__str__` Methods**
All model `__str__` methods now properly handle:
- JSONField values (convert to readable strings)
- None/null values (fallback to model ID)
- Better readability in Django admin

**Models Updated:**
- `FileMappedModel` - Shows comma-separated model names or ID
- `FileMappedField` - Shows field name or ID
- `FileColumnFieldValueMapping` - Shows column name or ID
- `FileDateFieldMapping` - Shows column name or ID
- `FileDurationDateMapping` - Shows calculated date field or duration field
- `FieldLookupValues` - Shows "column: value" format
- `FileMissingRelations` - Shows "Model.field" format
- `FileImportUUIDValues` - Shows "Model: UUID" format
- `FileImportJSON` - Shows session name reference

### 3. **User Modifications Applied**
- `FilePatientID.patient_id` changed from JSONField to CharField
- Added `exists_in_client_app_database` boolean field to `FilePatientID`
- Added new `FileMissingRelations` model for Step 9
- Fixed `FileDurationDateMapping.__str__` to use correct field

---

## Model Structure Overview

### **Step-to-Model Mapping**

| Step | Model(s) | Purpose |
|------|----------|---------|
| Step 1 | `FileImportSession` | Upload CSV, select projects |
| Step 2 | `FilePatientID` | Map patient ID column, check existence |
| Step 3 | `FileMappedModel` | Select models to import (array of model names) |
| Step 4 | `FileMappedField` | Map CSV columns to model fields (many-to-one) |
| Step 5 | `FileColumnFieldValueMapping` | Map column names to field values |
| Step 6 | `FileDateFieldMapping` | Set date formats for date fields |
| Step 7 | `FileDurationDateMapping` | Calculate dates from durations |
| Step 8 | `FieldLookupValues` | Map CSV values to lookup table values |
| Step 9 | `FileMissingRelations` | Store missing FK relationship data |
| Step 10 | `FileImportUUIDValues` | Generate and store UUIDs |
| Step 11 | `FileImportJSON` | Store final nested JSON for import |

---

## Data Structure Clarifications

### 1. **FileMappedModel.client_app_model_name** (JSONField)
```json
["Diagnosis", "Pathology", "Immunohistochemistry"]
```
Stores array of model names at the same hierarchy level.

### 2. **FileMappedField** (Step 4 - Wide Format Support)
```json
{
  "csv_field_names": ["Hemoglobin_Day1", "Hemoglobin_Day7", "Hemoglobin_Day14"],
  "mapped_client_app_field_name": "quantitative_result_value"
}
```
Multiple CSV columns → single model field (will be expanded to long format in JSON).

### 3. **FileColumnFieldValueMapping** (Step 5)
```json
{
  "csv_column_name": "Diabetes",
  "mapped_client_app_field_name": "comorbidity_type",
  "mapped_client_app_field_value": "DIABETES_TYPE_2",
  "mapped_client_app_additional_field_names": ["date_of_comorbidity_assessment"],
  "mapped_client_app_additional_field_values": ["2024-01-15"]
}
```

### 4. **FileMissingRelations** (Step 9)
```json
{
  "client_app_model_name": "Diagnosis",
  "client_app_field_name": "diagnosis_date",
  "client_app_field_value": "2024-01-01"
}
```
Stores intermediate FK data when importing child models without parent data in CSV.

### 5. **FileImportJSON** (Step 11 - DRF Nested Format)
```json
{
  "patient_id": "P001",
  "gender": "Female",
  "patient_project": ["PROJ001"],
  "diagnosis_set": [
    {
      "chavi_diagnosis_id": "uuid-here",
      "diagnosis_date": "2024-01-01",
      "pathology_set": [
        {
          "chavi_pathology_id": "uuid-here",
          "date_pathology": "2024-01-05",
          "immunohistochemistry_set": [...]
        }
      ]
    }
  ]
}
```

---

## Recommendations for Implementation

### **1. Model Hierarchy Service** (Answer to Question 1)
Create a service to dynamically determine model relationships:

```python
# data_import/services/model_hierarchy.py

from django.apps import apps
from django.db.models import ForeignKey

class ModelHierarchyService:
    """
    Dynamically determines model hierarchy based on FK relationships.
    """
    
    EXCLUDED_MODELS = [
        'PatientDicomFile', 'DICOMStudy', 'DICOMStudyProject',
        'BulkDICOMUpload', 'UnprocessedDICOMStudies',
        'BulkDICOMUploadSession', 'BulkDICOMStudyMatch'
    ]
    
    @staticmethod
    def get_model_hierarchy():
        """
        Returns dict mapping models to their hierarchy level.
        Level 0: Patient
        Level 1: Models with FK to Patient
        Level 2: Models with FK to Level 1 models, etc.
        """
        client_app = apps.get_app_config('client_app')
        models = [m for m in client_app.get_models() 
                  if m.__name__ not in ModelHierarchyService.EXCLUDED_MODELS]
        
        hierarchy = {}
        # Start with Patient at level 0
        patient_model = apps.get_model('client_app', 'Patient')
        hierarchy[patient_model.__name__] = 0
        
        # Iteratively assign levels
        max_iterations = 10
        for iteration in range(max_iterations):
            for model in models:
                if model.__name__ in hierarchy:
                    continue
                    
                # Check FK relationships
                fk_fields = [f for f in model._meta.get_fields() 
                            if isinstance(f, ForeignKey)]
                
                for fk in fk_fields:
                    related_model_name = fk.related_model.__name__
                    if related_model_name in hierarchy:
                        current_level = hierarchy.get(model.__name__, float('inf'))
                        new_level = hierarchy[related_model_name] + 1
                        hierarchy[model.__name__] = min(current_level, new_level)
        
        return hierarchy
    
    @staticmethod
    def get_models_at_level(level):
        """Returns list of model names at specified hierarchy level."""
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        return [name for name, lvl in hierarchy.items() if lvl == level]
    
    @staticmethod
    def validate_model_selection(model_names):
        """
        Validates that all selected models are at the same hierarchy level.
        Returns (is_valid, error_message, level)
        """
        hierarchy = ModelHierarchyService.get_model_hierarchy()
        levels = [hierarchy.get(name) for name in model_names if name in hierarchy]
        
        if not levels:
            return False, "No valid models selected", None
        
        if len(set(levels)) > 1:
            return False, f"Selected models are at different hierarchy levels: {set(levels)}", None
        
        return True, None, levels[0]
```

### **2. Field Introspection Service**
Create service for dynamic field discovery:

```python
# data_import/services/field_introspection.py

from django.apps import apps
from django.db.models import ForeignKey, ManyToManyField

class FieldIntrospectionService:
    """
    Provides field metadata for client_app models.
    """
    
    @staticmethod
    def get_model_fields(model_name):
        """
        Returns dict of field metadata for a model.
        """
        model = apps.get_model('client_app', model_name)
        fields_info = {}
        
        for field in model._meta.get_fields():
            if field.name in ['created_at', 'updated_at']:
                continue
                
            field_info = {
                'name': field.name,
                'type': field.get_internal_type(),
                'help_text': getattr(field, 'help_text', ''),
                'required': not field.blank if hasattr(field, 'blank') else True,
                'choices': field.choices if hasattr(field, 'choices') else None,
            }
            
            # Handle relationships
            if isinstance(field, ForeignKey):
                field_info['related_model'] = field.related_model.__name__
                field_info['is_lookup'] = field.related_model._meta.app_label == 'lookup'
            elif isinstance(field, ManyToManyField):
                field_info['related_model'] = field.related_model.__name__
                field_info['is_m2m'] = True
            
            fields_info[field.name] = field_info
        
        return fields_info
    
    @staticmethod
    def get_date_fields(model_name):
        """Returns list of date/datetime field names for a model."""
        model = apps.get_model('client_app', model_name)
        return [f.name for f in model._meta.get_fields() 
                if f.get_internal_type() in ['DateField', 'DateTimeField']]
    
    @staticmethod
    def get_fk_fields(model_name):
        """Returns dict of FK field names and their related models."""
        model = apps.get_model('client_app', model_name)
        return {f.name: f.related_model.__name__ 
                for f in model._meta.get_fields() 
                if isinstance(f, ForeignKey)}
```

### **3. Date Format Parser**
Handle delimiters programmatically:

```python
# data_import/services/date_parser.py

from datetime import datetime
import re

class DateFormatParser:
    """
    Parses dates with various formats and delimiters.
    """
    
    DELIMITER_PATTERNS = ['-', '/', '.', ' ', '']
    
    FORMAT_MAPPINGS = {
        'iso_8601': '%Y-%m-%d',
        'ddmmyyyy': ['%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%d%m%Y'],
        'mmddyyyy': ['%m-%d-%Y', '%m/%d/%Y', '%m.%d.%Y', '%m%d%Y'],
        'yyyymmdd': ['%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d'],
        'dmy': ['%d-%m-%y', '%d/%m/%y', '%d.%m.%y', '%d%m%y'],
        'mdy': ['%m-%d-%y', '%m/%d/%y', '%m.%m.%y', '%m%d%y'],
        'ymd': ['%y-%m-%d', '%y/%m/%d', '%y.%m.%d', '%y%m%d'],
    }
    
    @staticmethod
    def parse_date(date_string, format_choice):
        """
        Attempts to parse date string with specified format.
        Tries multiple delimiter variations.
        """
        if not date_string:
            return None
        
        formats = DateFormatParser.FORMAT_MAPPINGS.get(format_choice, [])
        if isinstance(formats, str):
            formats = [formats]
        
        for fmt in formats:
            try:
                return datetime.strptime(str(date_string).strip(), fmt).date()
            except ValueError:
                continue
        
        raise ValueError(f"Could not parse '{date_string}' with format '{format_choice}'")
```

### **4. UUID Management**
Track UUID generation state:

```python
# Add to FileImportSession model:

class FileImportSession(models.Model):
    # ... existing fields ...
    
    uuids_generated = models.BooleanField(
        default=False,
        help_text="Indicates if UUIDs have been generated for this session"
    )
    data_imported = models.BooleanField(
        default=False,
        help_text="Indicates if data has been successfully imported"
    )
    
    def regenerate_uuids_allowed(self):
        """UUIDs can be regenerated only if data hasn't been imported yet."""
        return not self.data_imported
```

---

## Next Steps

### **Immediate Actions:**
1. ✅ Run migrations for the model changes
2. ✅ Test `__str__` methods in Django admin
3. ⚠️ Implement `ModelHierarchyService`
4. ⚠️ Implement `FieldIntrospectionService`
5. ⚠️ Create views for each step (Step 1-11)
6. ⚠️ Create DRF serializers for nested JSON generation
7. ⚠️ Implement date parsing with delimiter handling
8. ⚠️ Add UUID regeneration logic with state tracking

### **Testing Checklist:**
- [ ] Test model hierarchy detection with various FK chains
- [ ] Test wide-format CSV conversion to long format
- [ ] Test date parsing with different delimiters
- [ ] Test missing relationship detection and user prompts
- [ ] Test UUID generation and regeneration rules
- [ ] Test final JSON structure matches DRF serializer format
- [ ] Test import with nested relationships

---

## Additional Notes

### **Important Considerations:**

1. **Transaction Management**: Wrap Step 11 import in database transaction to ensure atomicity

2. **Validation**: Add validation at each step to prevent invalid state progression

3. **Error Handling**: Store detailed error logs in `FileImportSession` for debugging

4. **Performance**: Consider batch processing for large CSV files

5. **Security**: Validate CSV file size, content, and structure before processing

6. **Audit Trail**: All models have `created_at` and `updated_at` for tracking

---

## Model Relationships Diagram

```
FileImportSession (root)
├── FilePatientID (Step 2)
├── FileMappedModel (Step 3)
├── FileMappedField (Step 4)
├── FileColumnFieldValueMapping (Step 5)
├── FileDateFieldMapping (Step 6)
├── FileDurationDateMapping (Step 7)
├── FieldLookupValues (Step 8)
├── FileMissingRelations (Step 9)
├── FileImportUUIDValues (Step 10)
└── FileImportJSON (Step 11)
```

All child models have FK to `FileImportSession` with `CASCADE` delete behavior.

---

**Review Completed By:** Cascade AI Assistant  
**Status:** ✅ Models reviewed and fixed  
**Ready for:** Migration and implementation of services
