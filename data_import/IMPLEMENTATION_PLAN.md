# Data Import Wizard - Implementation Plan

## **Overview**
Create a comprehensive 8-step wizard for importing CSV/JSON data into the CHAVI client_app database with field mapping, validation, and UUID management.

---

## **Phase 1: Core Services Layer**

### **1.1 Field Introspection Service** (`services/field_introspection.py`)
**Purpose**: Extract metadata from client_app models programmatically

**Features**:
- Get all models from `client_app`
- Extract field information (name, type, help_text, validators)
- Identify FK and M2M relationships
- Detect lookup table relationships
- Cache results for performance
- Exclude auto-generated fields (created_at, updated_at, auto UUIDs)

**Output**: Structured field metadata dictionary

---

### **1.2 Fuzzy Matching Service** (`services/fuzzy_matcher.py`)
**Purpose**: Match CSV field names to CHAVI database fields

**Features**:
- Use RapidFuzz for fuzzy string matching
- Search against: field_name + help_text + verbose_name
- Case-insensitive matching
- Token-based matching (handles "date_of_birth" vs "Date of Birth")
- Categorize matches:
  - **Exact/Auto**: Score > 90 (auto-select)
  - **Strong**: Score 70-90 (show top 3 suggestions)
  - **Rest**: Allow manual selection of the field

**Output**: Ranked list of potential field matches

---

### **1.3 Data Validator Service** (`services/data_validator.py`)
**Purpose**: Validate CSV data against Django model constraints

**Features**:
- Data type validation (String, Integer, Float, Date, Boolean, etc.)
- Required field validation (null/blank constraints)
- Length validation (max_length, max_digits)
- Range validation (MinValueValidator, MaxValueValidator)
- Regex validation (RegexValidator)
- Custom validator support
- Choice validation
- Generate detailed error reports per row/field

**Output**: Validation results with row-level errors

---

### **1.4 Lookup Matcher Service** (`services/lookup_matcher.py`)
**Purpose**: Match string values in CSV to lookup table entries

**Features**:
- Identify fields with FK to lookup app
- Extract unique values from CSV for each lookup field
- Fuzzy match against lookup table values
- Support multiple match fields (code, description, etc.)
- Allow user to map unmapped values
- Store mappings in `FieldLookupConfiguration` model

**Output**: Lookup value mappings

---

### **1.5 UUID Manager Service** (`services/uuid_manager.py`)
**Purpose**: Manage UUID generation and persistence for FK/M2M relationships

**Features**:
- Identify related tables (FK/M2M) that need UUIDs
- Generate composite keys from field combinations
- Check existing UUID mappings in database
- Reuse existing UUIDs for matching records
- Generate new UUIDs for new records
- Store mappings in `UUIDMappings` model
- Handle patient_id as the primary linking field

**Output**: UUID mapping dictionary

---

### **1.6 CSV/JSON Processor Service** (`services/file_processor.py`)
**Purpose**: Parse and process uploaded files

**Features**:
- Parse CSV files (handle different encodings, delimiters)
- Parse JSON files
- Extract headers from first row
- Read data in chunks for large files
- Detect data types
- Handle missing values
- Preview data (first 10 rows)

**Output**: Parsed data structure

---

### **1.7 Import Executor Service** (`services/import_executor.py`)
**Purpose**: Execute the actual data import into database

**Features**:
- Transaction management (rollback on errors)
- Batch processing for performance
- Handle FK relationships (create parent records first)
- Handle M2M relationships (create after main records)
- Apply UUID mappings
- Apply lookup mappings
- Generate import summary report
- Log all operations

**Output**: Import results and statistics

---

## **Phase 2: Models Enhancement**

### **2.1 Update Existing Models** (`models.py`)
**Enhancements needed**:
- Add `status` field to `ImportData` (uploaded, mapping, validating, importing, completed, failed)
- Add `validation_errors` JSONField to `ImportData`
- Add `import_summary` JSONField to `ImportData`
- Add `row_count` to `ImportData`
- Add `processed_rows` to `ImportData`
- Fix `UUIDMappings.__str__()` method (currently references non-existent `self.uuid`)

---

## **Phase 3: Views (10-Step Wizard)** ✅ **IMPLEMENTED**

### **Step 1: File Upload** (`views/step1_upload.py`) ✅
- Upload CSV/Excel file
- Select project(s)
- Validate file format
- Store in `ImportData` model
- Extract and display headers
- Show data preview (first 10 rows)

**Template**: `data_import/step1_upload.html`

---

### **Step 2: Field Mapping** (`views/step2_field_mapping.py`) ✅
- Run fuzzy matching on all CSV fields
- Display auto-matched fields with confidence scores
- Display suggested matches with options
- Searchable dropdown for manual selection
- Show field metadata (type, help_text, required, FK/M2M)
- **Uses `update_or_create()` to preserve existing mappings and related configs**
- Save mappings to `DataFieldConfiguration`

**Template**: `data_import/step2_field_mapping.html`

**Critical Fix**: Changed from `delete()` + `create()` to `update_or_create()` to preserve mapping IDs and prevent orphaning of related configurations.

---

### **Step 3: Date Format Configuration** (`views/step3_date_format_config.py`) ✅
- Identify all date/datetime fields from mappings
- Display sample values from uploaded file
- Configure date format (YYYY-MM-DD, MM-DD-YYYY, DD-MM-YYYY)
- Configure date separator (Hyphen, Slash, Dot, Space, Comma)
- Save to `ImportDateFormatConfiguration`
- **Auto-copy configs from previous imports if none exist**

**Template**: `data_import/step3_date_format_config.html`

---

### **Step 4: Date Interval Configuration** (`views/step4_date_interval_config.py`) ✅
- Identify numeric fields that can be converted to dates
- Configure target date field and interval unit (Days, Weeks, Months, Years)
- Save to `ImportDateIntervalFieldConfiguration`

**Template**: `data_import/step4_date_interval_config.html`

---

### **Step 5: Data Validation** (`views/step5_validation.py`) ✅
- Run validation on all mapped fields
- Display validation errors by row and field
- Show error counts per field
- Allow user to:
  - Proceed with errors (skip invalid rows)
  - Deselect problematic fields
  - Go back and fix mappings

**Template**: `data_import/step5_validation.html`

---

### **Step 6: Lookup Matching** (`views/step6_lookup_matching.py`) ✅
- Identify all lookup fields (FK to lookup app)
- Extract unique values from CSV
- Run fuzzy matching against lookup tables
- Display matching interface with confidence scores
- Allow manual selection for unmatched values
- Save mappings to `FieldLookupConfiguration`

**Template**: `data_import/step6_lookup_matching.html`

---

### **Step 7: Static Field Mapping** (`views/step7_static_mapping.py`) ✅
- Allow mapping static values to CHAVI fields
- Useful for fields not in CSV but required in database
- Save to `StaticFieldMapping`

**Template**: `data_import/step7_static_mapping.html`

---

### **Step 8: UUID Field Configuration** (`views/step8_uuid_mapping.py`) ✅
- Uses `ModelHierarchyService` to identify model dependencies
- Display hierarchical model structure
- Configure UUID generation fields for each table
- Support for Standard, FK, M2M, Static, and Computed fields
- Validate that all parent models in hierarchy are configured
- **Excludes patient table** - uses patient_id as primary key instead of UUID
- Save to `UUIDFieldConfiguration`

**Template**: `data_import/step8_uuid_mapping.html`

---

### **Step 8.5: UUID Matching & Deduplication** (`views/step8_5_uuid_matching.py`) ✅ **NEW**
- **Purpose**: Compare generated UUIDs with existing records in database to prevent duplicates
- Generate JSON with UUIDs from Step 8 configuration
- Query existing patient records and all related data (diagnosis, pathology, treatment, etc.)
- Calculate similarity scores for matching records
- Display side-by-side comparison:
  - Import data (new records with generated UUIDs)
  - Existing data (database records with existing UUIDs)
- User decides for each record:
  - **Use Existing UUID**: Link to existing record (avoids duplicates)
  - **Use New UUID**: Create new record
- Auto-suggests high-similarity matches (>80% similarity)
- Handles nested record hierarchies (diagnosis → pathology → immunohistochemistry)
- Save decisions to `UUIDMatchConfiguration` model
- Apply UUID replacements in JSON generator

**Template**: `data_import/step8_5_uuid_matching.html`

**Services**: 
- `services/uuid_matcher.py` - Matches generated records with existing database records
- Similarity calculation for diagnosis and pathology records
- Nested record matching with full hierarchy preservation

**Model**: `UUIDMatchConfiguration`
- Stores user decisions: table_name, patient_id, generated_uuid, existing_uuid, match_action
- Actions: `USE_EXISTING` or `USE_NEW`

**Key Features**:
- Efficient for large datasets (expandable/collapsible patient cards)
- Shows complete record hierarchy with all UUIDs visible
- Prevents duplicate patient/diagnosis/pathology records
- User has full control over UUID reuse decisions

---

### **Step 9: JSON Preview** (`views/step9_import.py`) ✅ **NEW**
- Generate hierarchical JSON from all mappings using `JSONGeneratorService`
- Display JSON preview with syntax highlighting
- Show statistics (patient count, table counts, record counts)
- Allow copy/download of JSON
- Save to `ImportDataJSON` model
- Regenerate JSON on demand

**Template**: `data_import/step9_json_preview.html`

**Services**: `services/json_generator.py` - Generates import JSON from file data and all configured mappings

---

### **Step 10: Import Execution** (`views/step10_execute.py`) ✅ **NEW**
- Display import confirmation with warnings
- Execute import using DRF serializers via `ImportExecutorService`
- Handle nested model relationships (Patient → Diagnosis → Pathology, etc.)
- Show import results (success/failure counts)
- Display completion status

**Template**: `data_import/step10_execute.html`

**Services**: `services/import_executor.py` - Uses Django REST Framework serializers for validation and import

---

## **Phase 4: URL Configuration** ✅ **IMPLEMENTED**

### **4.1 URL Routes** (`urls.py`)
```python
urlpatterns = [
    path('', Step1UploadView.as_view(), name='import_step1_upload'),
    path('<int:import_id>/map-fields/', Step2FieldMappingView.as_view(), name='import_step2_field_mapping'),
    path('<int:import_id>/date-formats/', Step3DateFormatConfigView.as_view(), name='import_step3_date_format_config'),
    path('<int:import_id>/date-intervals/', Step4DateIntervalConfigView.as_view(), name='import_step4_date_interval_config'),
    path('<int:import_id>/validate/', Step5ValidationView.as_view(), name='import_step5_validation'),
    path('<int:import_id>/lookup-matching/', Step6LookupMatchingView.as_view(), name='import_step6_lookup_matching'),
    path('<int:import_id>/static-mapping/', Step7StaticMappingView.as_view(), name='import_step7_static_mapping'),
    path('<int:import_id>/uuid-mapping/', Step8UUIDMappingView.as_view(), name='import_step8_uuid_mapping'),
    path('<int:import_id>/uuid-matching/', Step8_5UUIDMatchingView.as_view(), name='import_step8_5_uuid_matching'),
    path('<int:import_id>/json-preview/', Step9ImportView.as_view(), name='import_step9_json_preview'),
    path('<int:import_id>/execute/', Step10ExecuteView.as_view(), name='import_step10_execute'),
]
```

---

## **Phase 5: Templates**

### **5.1 Base Template** (`templates/data_import/base_wizard.html`)
- Wizard progress indicator (8 steps)
- Navigation (Previous/Next/Cancel)
- Consistent styling with existing CHAVI UI
- Error/success message display

### **5.2 Individual Step Templates**
- One template per step (8 total)
- Use Django forms where applicable
- AJAX for dynamic interactions
- Data tables for displaying mappings/errors
- Use existing CHAVI components (buttons, cards, etc.)

---

## **Phase 6: Admin Integration**

### **6.1 Admin Interface** (`admin.py`)
- Register `ImportData` model
- Register `DataFieldConfiguration` model (inline)
- Register `UUIDMappings` model (inline)
- Register `FieldLookupConfiguration` model (inline)
- Add custom admin actions:
  - "Start Import Wizard" button
  - "View Import History"
  - "Download Import Log"
- Link to wizard from admin dashboard

---

## **Phase 7: Testing & Documentation**

### **7.1 Unit Tests**
- Test each service independently
- Test validators with edge cases
- Test fuzzy matching accuracy
- Test UUID generation logic

### **7.2 Integration Tests**
- Test complete wizard flow
- Test with sample CSV files
- Test error handling
- Test rollback on failures

### **7.3 Documentation**
- User guide for import wizard
- Field mapping guidelines
- CSV format requirements
- Troubleshooting guide

---

## **Phase 8: Critical Bug Fixes & Improvements** ✅ **COMPLETED**

### **8.1 Field Mapping Persistence Issue**
**Problem**: Step 2 was deleting all `DataFieldConfiguration` records before recreating them, causing mapping IDs to change and orphaning all related configurations (date formats, intervals, lookup mappings, etc.).

**Root Cause**:
- `DataFieldConfiguration.objects.filter(import_data=import_data).delete()` in Step 2 POST method
- Using `objects.create()` instead of `update_or_create()`

**Solution**:
- Removed the `.delete()` call
- Changed to `objects.update_or_create()` with proper lookup fields:
  - `import_data`, `file_field_name`, `client_app_table_name`, `client_app_field_name`
- Mapping IDs now remain stable throughout the import session
- All related configurations persist when navigating back through wizard steps

**Impact**: Date format configurations and other step configs now persist correctly when reloading imports.

---

### **8.2 Auto-Copy Previous Configurations**
**Feature**: Automatically copy configurations from the most recent import when starting a new import session.

**Implementation** (Step 3 - Date Format Config):
```python
def _copy_date_configs(self, source_import, target_import):
    """Copy date format configurations from source import to target import"""
    # Finds matching fields by name and copies format/separator settings
```

**Benefits**:
- Reduces repetitive configuration for similar imports
- Improves user experience
- Can be extended to other configuration steps

---

### **8.3 Template Block Name Fixes**
**Problem**: Step 9 template was using `{% block step_content %}` instead of `{% block wizard_content %}`, causing content not to render.

**Solution**: Updated all new templates to use correct block name matching `base_wizard.html`.

---

### **8.4 Model Attribute Fixes**
**Problem**: `JSONGeneratorService` was accessing `import_data.file_type` which doesn't exist.

**Solution**: Changed to use correct attribute `import_data.data_type`.

---

### **8.5 ImportStatus Enum Updates**
**Added new statuses**:
- `STATIC_MAPPING = 'static_mapping', 'Static Mapping'`
- `JSON_PREVIEW = 'json_preview', 'JSON Preview'`

These track progress through the new wizard steps.

---

### **8.6 Button Text Consistency**
**Updated all wizard step buttons** to correctly reflect the next step:
- Step 6: "Continue to Static Mapping" (was "Continue to UUID Mapping")
- Step 8: "Continue to JSON Preview" (was "Continue to Import")

---

### **8.7 URL Route Name Updates**
**Changed**:
- `import_step9_import` → `import_step9_json_preview`
- Added `import_step10_execute`

**Updated references** in:
- Step 8 view (`next_step_url_name`)
- All templates with navigation links

---

### **8.8 Custom Validator Support** ✅ **IMPLEMENTED**

**Problem**: Custom validators defined in `client_app/models.py` were not being validated in Step 5, causing errors to be caught late during import (Step 10).

**Custom Validators Implemented**:

1. **percentage_validator** (0-100 range)
   - Pattern: `MinValueValidator(0.0)` + `MaxValueValidator(100.0)`
   - Used in: `Pathology.percentage_necrosis`, `Immunohistochemistry.percentage_positive_tumor_cells`, etc.
   - Error: "Percentage must be between 0 and 100 (got {value})"

2. **positive_decimal_validator** (>= 0)
   - Pattern: `MinValueValidator(0.0)` only
   - Used in: `Lesion.lesion_size_*`, `Lesion.lesion_volume`, `Pathology.primary_tumor_dimension`, etc.
   - Error: "Value must be positive or zero (got {value})"

3. **allred_score_validator** (0-8 range)
   - Pattern: `MinValueValidator(0)` + `MaxValueValidator(8)`
   - Error: "Allred score must be between 0 and 8 (got {value})"

**Implementation**:
- **Field Introspection Service**: Added pattern detection methods (`_is_percentage_validator()`, `_is_positive_decimal_validator()`, `_is_allred_score_validator()`)
- **Data Validator Service**: Added validation logic in `_apply_validators()` method

**Benefits**:
- ✅ Early error detection in Step 5 (instead of Step 10)
- ✅ Clear error messages with row numbers and field names
- ✅ Automatic detection - no manual configuration needed
- ✅ Consistent with model definitions

**Not Yet Implemented**:
- ⚠️ `DateValidationMixin` - Cross-field date validation (e.g., date_of_birth before date_of_death)
- Requires more complex cross-field validation logic

---

## **Implementation Order**

1. ✅ **Phase 1**: Core services (field introspection, fuzzy matching, validation, lookup matcher, UUID manager, file processor, model hierarchy)
2. ✅ **Phase 2**: Model enhancements (ImportData, DataFieldConfiguration, ImportDateFormatConfiguration, ImportDateIntervalFieldConfiguration, FieldLookupConfiguration, StaticFieldMapping, UUIDFieldConfiguration, ImportDataJSON)
3. ✅ **Phase 3**: Views (10-step wizard fully implemented)
4. ✅ **Phase 4**: URL configuration (all routes configured)
5. ✅ **Phase 5**: Templates (all 10 step templates created with base_wizard.html)
6. ⏳ **Phase 6**: Admin integration (pending)
7. ⏳ **Phase 7**: Testing and documentation (pending)
8. ✅ **Phase 8**: Critical bug fixes and improvements

---

## **Key Design Decisions**

1. **Session-based wizard**: Store progress in session/database
2. **Incremental validation**: Validate at each step, not just at the end
3. **Reversible steps**: Allow going back and modifying earlier steps
4. **Batch processing**: Handle large CSV files efficiently
5. **Transaction safety**: Use database transactions with rollback
6. **Audit trail**: Log all operations for debugging
7. **Reusable mappings**: Store mappings for future imports

---

## **Technical Stack**

- **Django**: Web framework
- **RapidFuzz**: Fuzzy string matching
- **Pandas** (optional): CSV processing for large files
- **Django REST Framework**: API endpoints
- **AJAX/JavaScript**: Dynamic UI interactions
- **Bootstrap/Tailwind**: UI styling (match existing CHAVI theme)

---

## **Questions to Resolve**

1. ✅ Should we cache field introspection results? (Performance vs. freshness) - **No** - Always fetch fresh metadata
2. ✅ Should we exclude certain models/fields from import? (e.g., system fields) - **No** - Allow all fields except auto-generated
3. ✅ For lookup tables, should we also introspect the `lookup` app models? - **No** - Only client_app models
4. ⚠️ How should we handle custom validators defined in models? - **Partially Implemented**
   - **Standard Django validators**: ✅ Handled (MinValueValidator, MaxValueValidator, FileExtensionValidator)
   - **Custom validators**: ⚠️ Need implementation
     - `DateValidationMixin` - validates start/end date pairs (e.g., date_of_birth before date_of_death)
     - `percentage_validator` - validates 0-100 range
     - `positive_decimal_validator` - validates >= 0
     - `allred_score_validator` - validates 0-8 range
   - **Current status**: DRF serializers will handle these during import, but validation step (Step 5) doesn't pre-validate custom validators
   - **Recommendation**: Extract custom validators from model fields and apply in Step 5 validation
5. ✅ Should we support updating existing records or only creating new ones? - **Both** - Using DRF serializers with update_or_create logic
6. ✅ What should be the maximum file size limit for uploads? - **Based on nginx configuration** - Not separately validated in Django
7. ✅ Should we support incremental imports (append to existing data)? - **No** - Each import is independent
8. ⏳ Do we need role-based access control for the import wizard? - **Pending** - To be implemented in Phase 6 (Admin integration)

---

## **Future Enhancements**

- Import templates download
- Scheduled imports
- Import from external APIs
- Data transformation rules
- Duplicate detection and merging
- Import history and audit logs
- Rollback capability for completed imports

---

## **Current Status**: ✅ **CORE FUNCTIONALITY COMPLETE**

### **Completed**:
- ✅ All 10 wizard steps implemented and functional (including Step 8.5 UUID Matching)
- ✅ JSON preview and DRF-based import system
- ✅ Model hierarchy service for dependency management
- ✅ Field mapping persistence bug fixed
- ✅ Auto-copy configurations from previous imports
- ✅ All URL routes and templates created
- ✅ Comprehensive error handling and user feedback
- ✅ **UUID matching and deduplication system** (Step 8.5)
- ✅ **Lookup value mapping with skip unmapped values** (Step 6)
- ✅ **Patient table uses patient_id as PK** (no UUID generation)
- ✅ **Date parsing with ISO8601 support**
- ✅ **Form submission fixes** (Step 6 and Step 8 templates)

### **Recent Enhancements** (2025-11-06):

#### **Step 6: Lookup Matching Improvements**
- Fixed form submission issue (submit button was in separate form)
- Lookup mappings now properly saved to database
- Unmapped lookup values are skipped in JSON generation
- Records with unmapped required lookups are excluded from import
- Clear logging of skipped values and records

#### **Step 8.5: UUID Matching & Deduplication (NEW)**
- Complete UUID matching system for existing patient records
- Side-by-side comparison of import data vs existing database records
- Similarity scoring for diagnosis and pathology records
- User control over UUID reuse decisions
- Handles nested record hierarchies
- Efficient UI for large datasets (expandable patient cards)
- Auto-suggests high-similarity matches (>80%)
- Applies UUID replacements in JSON generator

#### **Date Parsing Enhancements**
- ISO8601 format support (YYYY-MM-DD)
- Fallback to configured format if ISO fails
- Returns value as-is if already in correct format
- Eliminates date parsing warnings

#### **Patient Table Handling**
- Patient table excluded from UUID generation (Step 8)
- Uses patient_id from CSV as primary key
- JSON generator uses patient_id directly instead of generating UUID

### **Pending**:

- ⏳ Comprehensive testing suite
- ⏳ User documentation
- ⏳ End-to-end import flow testing with real data

### **Known Issues**:
- Import executor service needs refinement for complex nested relationships
- Need to test with large datasets (performance optimization)
- Error recovery and rollback mechanisms need testing
- **Custom validators not fully handled in Step 5 validation**:
  - `DateValidationMixin` (start/end date pairs) not validated pre-import
  - Custom validators (percentage_validator, positive_decimal_validator, allred_score_validator) not extracted and applied
  - Currently relies on DRF serializers to catch these during import (Step 10)
  - **Recommendation**: Enhance Step 5 to extract and apply custom validators from model fields

**Next Steps**: 
1. Test complete import flow with sample data (including UUID matching)
2. Refine import executor for edge cases
3. Test UUID matching with large patient datasets
4. Add admin integration
5. Create user documentation
