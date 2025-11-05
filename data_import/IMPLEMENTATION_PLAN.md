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

## **Phase 3: Views (8-Step Wizard)**

### **Step 1: File Upload** (`views/step1_upload.py`)
- Upload CSV/JSON file
- Select project(s)
- Validate file format
- Store in `ImportData` model
- Extract and display headers
- Show data preview (first 10 rows)

**Template**: `data_import/step1_upload.html`

---

### **Step 2: Field Mapping - Auto Match** (`views/step2_auto_match.py`)
- Run fuzzy matching on all CSV fields
- Display auto-matched fields (score > 90)
- Display suggested matches (score 70-90) with options
- Display unmatched fields for manual selection
- Show field metadata (type, help_text, required)
- Allow user to accept/reject suggestions

**Template**: `data_import/step2_auto_match.html`

---

### **Step 3: Field Mapping - Manual Match** (`views/step3_manual_match.py`)
- Searchable dropdown for unmatched fields
- Filter by model/table
- Show field details on hover
- Allow deselection of fields
- Save mappings to `DataFieldConfiguration`
- Display mapping summary

**Template**: `data_import/step3_manual_match.html`

---

### **Step 4: Field Mapping - Review** (`views/step4_mapping_review.py`)
- Display complete field mapping table
- Show: CSV Field → CHAVI Field (Model.field)
- Allow editing/removing mappings
- Finalize and save mappings
- Option to go back and modify

**Template**: `data_import/step4_mapping_review.html`

---

### **Step 5: Data Type Validation** (`views/step5_validation.py`)
- Run validation on all mapped fields
- Display validation errors by row and field
- Show error counts per field
- Allow user to:
  - Deselect problematic fields
  - Download error report (CSV)
  - Go back and fix mappings
- Only proceed when all selected fields pass validation

**Template**: `data_import/step5_validation.html`

---

### **Step 6: Lookup Matching** (`views/step6_lookup_matching.py`)
- Identify all lookup fields
- Extract unique values from CSV
- Run fuzzy matching against lookup tables
- Display matching interface:
  - CSV Value → Lookup Value (with confidence score)
  - Allow manual selection for unmatched
  - Show lookup table values in dropdown
- Save mappings to `FieldLookupConfiguration`
- Warn about unmapped values (won't be imported)

**Template**: `data_import/step6_lookup_matching.html`

---

### **Step 7: FK/M2M UUID Mapping** (`views/step7_uuid_mapping.py`)
- Identify related tables (FK/M2M)
- Group rows by patient_id
- Display UUID generation strategy:
  - Show which fields will be used for composite keys
  - Display existing UUID matches
  - Show new UUIDs to be generated
- Preview record structure with UUIDs
- Allow user to review and confirm

**Template**: `data_import/step7_uuid_mapping.html`

---

### **Step 8: Import Execution** (`views/step8_import.py`)
- Display import summary
- Show record counts by table
- Execute import with progress bar
- Handle errors gracefully
- Display import results:
  - Records created/updated
  - Errors encountered
  - Download detailed log
- Save UUID mappings for future imports

**Template**: `data_import/step8_import.html`

---

## **Phase 4: URL Configuration**

### **4.1 Create URL Routes** (`urls.py`)
```python
urlpatterns = [
    path('upload/', Step1UploadView.as_view(), name='import_step1_upload'),
    path('<int:import_id>/auto-match/', Step2AutoMatchView.as_view(), name='import_step2_auto_match'),
    path('<int:import_id>/manual-match/', Step3ManualMatchView.as_view(), name='import_step3_manual_match'),
    path('<int:import_id>/mapping-review/', Step4MappingReviewView.as_view(), name='import_step4_mapping_review'),
    path('<int:import_id>/validation/', Step5ValidationView.as_view(), name='import_step5_validation'),
    path('<int:import_id>/lookup-matching/', Step6LookupMatchingView.as_view(), name='import_step6_lookup_matching'),
    path('<int:import_id>/uuid-mapping/', Step7UUIDMappingView.as_view(), name='import_step7_uuid_mapping'),
    path('<int:import_id>/import/', Step8ImportView.as_view(), name='import_step8_import'),
    # API endpoints for AJAX operations
    path('api/fields/', FieldListAPIView.as_view(), name='api_field_list'),
    path('api/fuzzy-match/', FuzzyMatchAPIView.as_view(), name='api_fuzzy_match'),
    path('api/validate/', ValidateDataAPIView.as_view(), name='api_validate_data'),
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

## **Implementation Order**

1. ✅ **Phase 1.1-1.6**: Core services (field introspection, fuzzy matching, validation, etc.)
2. **Phase 2**: Model enhancements
3. **Phase 3**: Views (implement steps 1-8 sequentially)
4. **Phase 4**: URL configuration
5. **Phase 5**: Templates (parallel with views)
6. **Phase 6**: Admin integration
7. **Phase 7**: Testing and documentation

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

1. Should we cache field introspection results? (Performance vs. freshness) - No
2. Should we exclude certain models/fields from import? (e.g., system fields) - No
3. For lookup tables, should we also introspect the `lookup` app models? - No
4. How should we handle custom validators defined in models? (Like `DateValidationMixin`) - Yes
5. Should we support updating existing records or only creating new ones? - Both
6. What should be the maximum file size limit for uploads? - based in nginx configuration. Not seperately validated
7. Should we support incremental imports (append to existing data)? - No    
8. Do we need role-based access control for the import wizard?

---

## **Future Enhancements**

- Export functionality (reverse of import)
- Import templates download
- Scheduled imports
- Import from external APIs
- Data transformation rules
- Duplicate detection and merging
- Import history and audit logs
- Rollback capability for completed imports

---

**Status**: Ready for review and implementation

**Next Steps**: Review this plan, make edits as needed, then proceed with Phase 1 implementation.
