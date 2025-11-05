# CHAVI Data Import Wizard

## **Overview**

A comprehensive 8-step wizard for importing clinical data from CSV/JSON files into the CHAVI client_app database with intelligent field mapping, validation, and UUID management.

---

## **✅ Completed Features**

### **Phase 1: Core Services Layer** ✅ COMPLETE

Six independent, testable services that handle all business logic:

1. **`field_introspection.py`** - Extracts metadata from Django models
2. **`fuzzy_matcher.py`** - Matches imported fields to CHAVI fields using RapidFuzz
3. **`data_validator.py`** - Validates data against Django model constraints
4. **`file_processor.py`** - Parses CSV/JSON files with auto-detection
5. **`lookup_matcher.py`** - Matches string values to lookup table entries
6. **`uuid_manager.py`** - Manages UUID generation and persistence

**Key Features**:
- ✅ Format-agnostic (works with CSV and JSON)
- ✅ Comprehensive error handling and logging
- ✅ Type hints for better IDE support
- ✅ Full documentation with docstrings
- ✅ Caching for performance

---

### **Phase 2: Model Enhancements** ✅ COMPLETE

Enhanced database models with status tracking and performance optimizations:

**New Features**:
- ✅ `ImportStatus` enum for workflow tracking
- ✅ Status field in `ImportData` model
- ✅ Row count and processed rows tracking
- ✅ JSON fields for validation errors and import summary
- ✅ Helper methods (`get_progress_percentage()`, `is_complete()`, `has_errors()`)
- ✅ Performance indexes on frequently queried fields
- ✅ Unique constraints for data integrity
- ✅ Fixed `UUIDMappings.__str__()` bug
- ✅ Improved `__str__()` methods for all models

---

### **Phase 2.5: Select2 Configuration** ✅ COMPLETE

Configured django-select2 for enhanced field selection UI:

- ✅ Added to `INSTALLED_APPS`
- ✅ URL patterns configured
- ✅ Settings configured for caching
- ✅ Ready for use in forms and templates

---

## **📋 8-Step Wizard Workflow**

### **Step 1: File Upload**
- Upload CSV/JSON file
- Select project(s)
- Validate file format
- Display data preview

### **Step 2: Auto Field Matching**
- Fuzzy match imported fields to CHAVI fields
- Auto-select high-confidence matches (>90%)
- Show suggestions for medium-confidence matches (70-90%)
- Flag fields needing manual selection

### **Step 3: Manual Field Matching**
- Select2-powered searchable dropdown
- Filter by model/table
- Show field metadata on hover
- Allow field deselection

### **Step 4: Mapping Review**
- Review complete field mapping
- Edit/remove mappings
- Finalize selections

### **Step 5: Data Validation**
- Validate all data types
- Check required fields
- Validate constraints (length, range, regex)
- Display errors by row and field
- Allow field deselection for problematic data

### **Step 6: Lookup Matching**
- Identify lookup fields
- Extract unique values
- Fuzzy match to lookup tables
- Manual selection for unmatched values
- Warn about unmapped values

### **Step 7: UUID Mapping**
- Identify related tables (FK/M2M)
- Group rows by patient_id
- Generate composite keys
- Display UUID generation strategy
- Show existing vs. new UUIDs

### **Step 8: Import Execution**
- Display import summary
- Execute import with progress tracking
- Handle errors gracefully
- Save UUID mappings for future imports
- Display results and statistics

---

## **🏗️ Architecture**

```
┌─────────────────────────────────────────────────────────┐
│  User Uploads File (CSV / JSON)                         │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  file_processor.py                                       │
│  • Detects encoding & delimiter                          │
│  • Parses to List[Dict]                                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
              List[Dict[str, Any]]
                     │
         ┌───────────┼───────────┐
         │           │           │
         ▼           ▼           ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ fuzzy_       │ │ data_        │ │ lookup_      │
│ matcher      │ │ validator    │ │ matcher      │
└──────────────┘ └──────────────┘ └──────────────┘
         │           │           │
         └───────────┼───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  uuid_manager         │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  import_executor      │
         │  (To be implemented)  │
         └───────────────────────┘
```

---

## **📁 Project Structure**

```
data_import/
├── services/
│   ├── __init__.py
│   ├── field_introspection.py    ✅ Complete
│   ├── fuzzy_matcher.py           ✅ Complete
│   ├── data_validator.py          ✅ Complete
│   ├── file_processor.py          ✅ Complete
│   ├── lookup_matcher.py          ✅ Complete
│   └── uuid_manager.py            ✅ Complete
│
├── views/                         ⏳ Pending
│   ├── __init__.py
│   ├── step1_upload.py
│   ├── step2_auto_match.py
│   ├── step3_manual_match.py
│   ├── step4_mapping_review.py
│   ├── step5_validation.py
│   ├── step6_lookup_matching.py
│   ├── step7_uuid_mapping.py
│   └── step8_import.py
│
├── templates/                     ⏳ Pending
│   └── data_import/
│       ├── base_wizard.html
│       ├── step1_upload.html
│       ├── step2_auto_match.html
│       ├── step3_manual_match.html
│       ├── step4_mapping_review.html
│       ├── step5_validation.html
│       ├── step6_lookup_matching.html
│       ├── step7_uuid_mapping.html
│       └── step8_import.html
│
├── models.py                      ✅ Enhanced
├── admin.py                       ⏳ Pending
├── urls.py                        ⏳ Pending
├── forms.py                       ⏳ Pending
│
├── IMPLEMENTATION_PLAN.md         ✅ Complete
├── PROGRESS_SUMMARY.md            ✅ Complete
├── REFACTORING_SUMMARY.md         ✅ Complete
├── MODEL_ENHANCEMENTS.md          ✅ Complete
└── README.md                      📄 This file
```

---

## **🔧 Technologies Used**

- **Django 5.1.4** - Web framework
- **RapidFuzz** - Fast fuzzy string matching
- **chardet** - Character encoding detection
- **django-select2** - Enhanced select widgets
- **PostgreSQL** - Database (assumed)
- **Django REST Framework** - API endpoints

---

## **📊 Database Models**

### **ImportData**
Tracks the import process and stores results.

**Key Fields**:
- `status` - Current workflow step
- `row_count` - Total rows in file
- `processed_rows` - Successfully processed rows
- `validation_errors` - JSON field for errors
- `import_summary` - JSON field for statistics

### **DataFieldConfiguration**
Maps imported fields to CHAVI database fields.

**Key Fields**:
- `file_field_name` - Field name in imported file
- `client_app_table_name` - Target table
- `client_app_field_name` - Target field
- `client_app_field_type` - Standard/FK/M2M

### **UUIDMappings**
Stores UUID mappings for consistent imports.

**Key Fields**:
- `client_app_table_name` - Table name
- `client_app_primary_key_value` - UUID value
- `data_field_configuration_fields` - Composite key fields

### **FieldLookupConfiguration**
Maps imported values to lookup table entries.

**Key Fields**:
- `field_value` - Value in imported file
- `lookup_value` - Mapped lookup table value

---

## **🚀 Getting Started**

### **Prerequisites**
```bash
# Install dependencies
pip install rapidfuzz chardet django-select2

# Or from requirements.txt
pip install -r requirements.txt
```

### **Run Migrations**
```bash
python manage.py makemigrations data_import
python manage.py migrate
```

### **Configuration**
Select2 is configured in `settings.py`:
```python
INSTALLED_APPS = [
    ...
    'django_select2',
]

SELECT2_CACHE_BACKEND = 'default'
```

---

## **📖 Usage Examples**

### **Field Introspection**
```python
from data_import.services.field_introspection import FieldIntrospectionService

service = FieldIntrospectionService()
all_fields = service.get_all_fields()
lookup_fields = service.get_lookup_fields()
```

### **Fuzzy Matching**
```python
from data_import.services.fuzzy_matcher import FuzzyMatcherService

matcher = FuzzyMatcherService(field_service)
results = matcher.match_source_fields(['patient_name', 'date_of_birth'])
```

### **Data Validation**
```python
from data_import.services.data_validator import DataValidatorService

validator = DataValidatorService()
result = validator.validate_data(data_rows, field_mappings)
```

### **File Processing**
```python
from data_import.services.file_processor import FileProcessorService

processor = FileProcessorService('/path/to/file.csv', 'CSV')
headers, data_rows = processor.parse()
preview = processor.get_preview(num_rows=10)
```

---

## **🎯 Current Status**

**Overall Progress**: ~40% Complete

### **Completed** ✅
- ✅ Core services layer (6 services)
- ✅ Model enhancements with status tracking
- ✅ Select2 configuration
- ✅ Format-agnostic refactoring
- ✅ Comprehensive documentation

### **In Progress** ⏳
- Creating comprehensive summary

### **Pending** 📋
- Views for 8-step wizard
- URL configuration
- Templates with Select2 integration
- Admin interface
- Forms
- Testing

---

## **📝 Next Steps**

1. **Phase 3**: Create views for 8-step wizard
2. **Phase 4**: Create URL configuration
3. **Phase 5**: Create templates with Select2
4. **Phase 6**: Admin interface integration
5. **Phase 7**: Testing and documentation

---

## **🤝 Contributing**

This is part of the CHAVI (Cancer Health AI Visualization Initiative) project.

---

## **📄 License**

See LICENSE file in the root directory.

---

## **📚 Additional Documentation**

- **IMPLEMENTATION_PLAN.md** - Complete implementation roadmap
- **PROGRESS_SUMMARY.md** - Detailed progress tracking
- **REFACTORING_SUMMARY.md** - Format-agnostic refactoring details
- **MODEL_ENHANCEMENTS.md** - Database model improvements

---

**Last Updated**: November 3, 2025  
**Status**: Phase 2 Complete, Ready for Phase 3
