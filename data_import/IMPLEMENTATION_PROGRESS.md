# Data Import Workflow - Implementation Progress

## Date: November 6, 2025

---

## ✅ Completed Components

### 1. **Service Classes** (`/data_import/services/`)

#### **ModelHierarchyService** (`model_hierarchy.py`)
- ✅ Dynamically determines model hierarchy based on FK relationships
- ✅ Validates that selected models are at the same hierarchy level
- ✅ Gets parent models and hierarchy paths
- ✅ Excludes DICOM-related models as specified

**Key Methods:**
- `get_model_hierarchy()` - Returns dict of {model_name: level}
- `get_models_at_level(level)` - Returns models at specific level
- `validate_model_selection(model_names)` - Validates selection
- `get_parent_models(model_name)` - Gets FK relationships
- `get_hierarchy_path(model_name)` - Gets path from Patient to model

#### **FieldIntrospectionService** (`field_introspection.py`)
- ✅ Provides field metadata for client_app models
- ✅ Identifies date fields, FK fields, lookup fields
- ✅ Determines appropriate widget types
- ✅ Gets required fields

**Key Methods:**
- `get_model_fields(model_name)` - Returns field metadata
- `get_date_fields(model_name)` - Returns date field names
- `get_fk_fields(model_name)` - Returns FK relationships
- `get_lookup_fields(model_name)` - Returns lookup table references
- `get_field_widget_type(field_info)` - Determines HTML widget type

#### **DateFormatParser** (`date_parser.py`)
- ✅ Parses dates with various formats and delimiters
- ✅ Calculates dates from duration and reference date
- ✅ Validates date formats
- ✅ Provides format examples

**Key Methods:**
- `parse_date(date_string, format_choice)` - Parses date with format
- `calculate_date_from_duration()` - Calculates date from duration
- `validate_date_format()` - Validates date string
- `get_format_example(format_choice)` - Returns example format

#### **CSVProcessorService** (`csv_processor.py`)
- ✅ Reads and validates CSV files
- ✅ Gets unique values from columns
- ✅ Analyzes data types
- ✅ Filters rows by patient IDs

**Key Methods:**
- `read_csv_file(csv_file)` - Reads CSV and returns headers, rows
- `get_unique_values(rows, column_name)` - Gets unique column values
- `validate_csv_structure(headers)` - Validates CSV structure
- `get_column_data_types(rows, column_name)` - Analyzes data types
- `filter_rows_by_patient_ids()` - Filters rows

---

### 2. **Forms** (`/data_import/forms.py`)

- ✅ **Step1UploadCSVForm** - Upload CSV and select projects
- ✅ **Step2PatientIDMappingForm** - Map patient ID column
- ✅ **Step3ModelSelectionForm** - Select models to import
- ✅ **Step4FieldMappingForm** - Map CSV columns to fields (dynamic)
- ✅ **Step5ColumnValueMappingForm** - Map column names to values (dynamic)
- ✅ **Step6DateFormatForm** - Set date formats (dynamic)
- ✅ **Step7DurationDateForm** - Calculate dates from durations
- ✅ **Step8LookupMappingForm** - Map to lookup values (dynamic)
- ✅ **Step9MissingRelationsForm** - Handle missing FK relationships (dynamic)
- ✅ **Step10ReviewForm** - Review and confirm import

---

### 3. **URL Configuration** (`/data_import/urls.py`)

✅ All URL patterns configured:
```
/import/                          - List all import sessions
/import/step1/                    - Upload CSV
/import/step2/<session_id>/       - Patient ID mapping
/import/step3/<session_id>/       - Model selection
/import/step4/<session_id>/       - Field mapping
/import/step5/<session_id>/       - Column value mapping
/import/step6/<session_id>/       - Date format
/import/step7/<session_id>/       - Duration date calculation
/import/step8/<session_id>/       - Lookup mapping
/import/step9/<session_id>/       - Missing relations
/import/step10/<session_id>/      - Review JSON
/import/step11/<session_id>/      - Execute import
```

✅ Main project URLs updated to include data_import app

---

### 4. **Models** (`/data_import/models.py`)

✅ All models reviewed and fixed:
- `FileImportSession` - Main session model
- `FilePatientID` - Patient IDs from CSV
- `FileMappedModel` - Selected models (JSONField array)
- `FileMappedField` - Field mappings (wide format support)
- `FileColumnFieldValueMapping` - Column to value mappings
- `FileDateFieldMapping` - Date format mappings
- `FileDurationDateMapping` - Duration calculations
- `FieldLookupValues` - Lookup value mappings
- `FileMissingRelations` - Missing FK data
- `FileImportUUIDValues` - Generated UUIDs
- `FileImportJSON` - Final nested JSON

✅ All `__str__` methods fixed to handle JSONFields properly

---

## ⚠️ Pending Components

### 1. **Views** (`/data_import/views.py`) - IN PROGRESS

Need to implement:
- [ ] `ImportSessionListView` - List all sessions
- [ ] `Step1UploadCSVView` - Handle CSV upload
- [ ] `Step2PatientIDMappingView` - Handle patient ID mapping
- [ ] `Step3ModelSelectionView` - Handle model selection with hierarchy validation
- [ ] `Step4FieldMappingView` - Dynamic field mapping form
- [ ] `Step5ColumnValueMappingView` - Dynamic column value mapping
- [ ] `Step6DateFormatView` - Dynamic date format selection
- [ ] `Step7DurationDateView` - Duration date calculation
- [ ] `Step8LookupMappingView` - Dynamic lookup mapping
- [ ] `Step9MissingRelationsView` - Handle missing relationships
- [ ] `Step10ReviewView` - Generate and display JSON
- [ ] `Step11ExecuteImportView` - Execute import with DRF serializers

### 2. **Templates** (`/templates/data_import/`)

Need to create:
- [ ] `base_import.html` - Base template with step indicator
- [ ] `session_list.html` - List of import sessions
- [ ] `step1_upload.html` - CSV upload form
- [ ] `step2_patient_id.html` - Patient ID mapping with existence check
- [ ] `step3_model_selection.html` - Model selection with hierarchy display
- [ ] `step4_field_mapping.html` - Field mapping interface
- [ ] `step5_column_value.html` - Column value mapping interface
- [ ] `step6_date_format.html` - Date format selection
- [ ] `step7_duration_date.html` - Duration date calculation
- [ ] `step8_lookup_mapping.html` - Lookup value mapping with Select2
- [ ] `step9_missing_relations.html` - Missing relationship handling
- [ ] `step10_review.html` - JSON preview with syntax highlighting
- [ ] `step11_complete.html` - Import completion status

### 3. **Additional Services**

Need to create:
- [ ] **JSONGeneratorService** - Generate nested DRF-compatible JSON
- [ ] **DataValidatorService** - Validate data before import
- [ ] **ImportExecutorService** - Execute import using DRF serializers

---

## 📋 Next Steps

### **Immediate Priority:**

1. **Implement Base View Classes**
   - Create `BaseImportView` with common functionality
   - Session validation and step progression logic
   - Navigation between steps

2. **Implement Step 1 & 2 Views**
   - CSV upload and validation
   - Patient ID mapping with database check
   - Store data in session models

3. **Create Base Templates**
   - Base import template with step indicator
   - Session list template
   - Step 1 & 2 templates

### **Architecture Decisions:**

#### **Session State Management:**
- Use database models to store state (already implemented)
- Each step saves data before proceeding
- Allow backward navigation with data preservation
- Track current step in `FileImportSession.import_session_step`

#### **Dynamic Form Generation:**
- Steps 4, 5, 6, 8, 9 require dynamic forms
- Generate forms in view based on previous step data
- Use formsets for multiple mappings

#### **JSON Generation (Step 10):**
- Build nested structure following model hierarchy
- Use DRF serializer format
- Include project information
- Generate UUIDs for non-Patient models

#### **Import Execution (Step 11):**
- Use DRF serializers for validation and saving
- Wrap in database transaction
- Handle errors gracefully
- Mark session as completed

---

## 🎯 Implementation Strategy

### **Phase 1: Core Views (Steps 1-3)**
1. Implement `ImportSessionListView`
2. Implement `Step1UploadCSVView` with CSV validation
3. Implement `Step2PatientIDMappingView` with patient existence check
4. Implement `Step3ModelSelectionView` with hierarchy validation
5. Create corresponding templates

### **Phase 2: Mapping Views (Steps 4-6)**
1. Implement `Step4FieldMappingView` with dynamic form generation
2. Implement `Step5ColumnValueMappingView` with dynamic form
3. Implement `Step6DateFormatView` with date field detection
4. Create corresponding templates

### **Phase 3: Advanced Features (Steps 7-9)**
1. Implement `Step7DurationDateView` with date calculation
2. Implement `Step8LookupMappingView` with Select2 integration
3. Implement `Step9MissingRelationsView` with FK detection
4. Create corresponding templates

### **Phase 4: Execution (Steps 10-11)**
1. Create `JSONGeneratorService`
2. Implement `Step10ReviewView` with JSON preview
3. Implement `Step11ExecuteImportView` with DRF serializers
4. Create completion templates

---

## 📝 Notes

### **Key Design Principles:**
- **Dynamic over Static**: Forms and validations are generated dynamically
- **Fail Fast**: Validate at each step before proceeding
- **User Guidance**: Provide clear instructions and examples
- **Data Preservation**: Allow users to go back and modify
- **Atomic Operations**: Import is all-or-nothing (transaction)

### **Technical Considerations:**
- Use Select2 for lookup field selection
- Use JSON syntax highlighting for Step 10 review
- Implement AJAX for patient ID existence check
- Use formsets for multiple mappings
- Cache CSV data in session to avoid re-reading

### **Security Considerations:**
- Validate file size and type
- Sanitize CSV content
- Check user permissions
- Validate all user inputs
- Use CSRF protection

---

## 🔧 Development Environment

### **Dependencies:**
- Django 5.1+
- Django REST Framework (for serializers)
- django-select2 (for autocomplete)
- python-dateutil (for date parsing)
- pandas (optional, for CSV processing)

### **File Structure:**
```
data_import/
├── services/
│   ├── __init__.py
│   ├── model_hierarchy.py
│   ├── field_introspection.py
│   ├── date_parser.py
│   └── csv_processor.py
├── migrations/
├── templates/data_import/  (to be created)
├── __init__.py
├── admin.py
├── apps.py
├── forms.py
├── models.py
├── urls.py
├── views.py  (to be implemented)
├── Import Workflow.md
├── MODEL_REVIEW_SUMMARY.md
└── IMPLEMENTATION_PROGRESS.md (this file)
```

---

**Status:** 🟡 In Progress  
**Completion:** ~40% (Models, Services, Forms, URLs complete; Views and Templates pending)  
**Next Action:** Implement base view classes and Step 1-2 views
