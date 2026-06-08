# Extractor App - Development Progress

**Last Updated:** June 8, 2026  
**Session Summary:** Schema Discovery, FK Relationship Tracking, API Connection Testing, and Pydantic Model Validation

---

## Overview

The extractor app provides a wizard-based interface for configuring LLM-powered data extraction from the CHAVI clinical database. This document tracks the implementation progress and key features.

---

## Completed Features

### 1. File Upload & Processing System

**Purpose:** Upload and process documents (PDF, CSV, Excel) for LLM-powered data extraction.

**Supported File Types:**
- ✅ **PDF** - Converted to Markdown using `markitdown`
- ✅ **CSV** - Used directly without conversion
- ✅ **Excel** - Each sheet converted to separate CSV files using `pandas`

**Features:**
- ✅ Drag-and-drop file upload interface
- ✅ Patient linkage (optional)
- ✅ Automatic file type detection
- ✅ Processing status tracking (PENDING/PROCESSING/COMPLETED/FAILED)
- ✅ Processed file management and viewing
- ✅ Copy to clipboard functionality
- ✅ Delete with confirmation modal

**File Processing Service** (`extractor/services/file_processor.py`):
- PDF → Markdown conversion (output: `media/processed/pdf/{name}_{id}.md`)
- CSV → Direct use (no conversion needed)
- Excel → Multiple CSV files (output: `media/processed/excel/{name}_{id}_{sheet}.csv`)
- Content retrieval and deletion utilities

**Views:**
- `file_upload_list` - List all uploaded files with status
- `file_upload_create` - Upload form with drag-and-drop
- `file_upload_detail` - File details and processed files
- `file_upload_process` - Process file (POST)
- `file_upload_delete` - Delete file and processed versions
- `processed_text_view` - View processed content

**Templates:**
- `file_upload_list.html` - Table view with color-coded status badges
- `file_upload_create.html` - Upload form with patient selection
- `file_upload_detail.html` - File info, processing button, processed files list
- `processed_text_view.html` - Content viewer with copy button

**Required Dependencies:**
```bash
pip install markitdown pandas openpyxl
```

---

### 2. Schema Discovery Service (`extractor/services/schema_discovery.py`)

**Purpose:** Automatically discover and populate `DatabaseTable` and `DatabaseField` models from `client_app` Django models.

**Key Features:**
- ✅ Automatic model introspection using Django's `_meta` API
- ✅ Type mapping from Django field types to Pydantic-compatible types
- ✅ File field type support (FileField, ImageField)
- ✅ Dynamic FK type detection based on related model's PK type
- ✅ Transaction handling with retry logic for SQLite database locks
- ✅ Progress callback support for real-time UI updates
- ✅ **Enhanced FK relationship tracking** (see below)

**FK Relationship Tracking:**
```python
clientapp_table_fk_fields = {
    'forward_fks': {
        'diagnosis': {
            'related_model': 'client_app.diagnosis',
            'related_field': 'chavi_diagnosis_id',
            'field_type': 'ForeignKey',
            'is_lookup': false
        }
    },
    'reverse_fks': {},  # Placeholder for future use
    'patient_path': [
        {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'chavi_diagnosis_id'},
        {'field': 'patient', 'model': 'client_app.patient', 'pk_field': 'patient_id'}
    ]
}
```

**Benefits:**
- Differentiates FK direction (forward vs reverse)
- Traces complete path from any table to Patient table
- Identifies lookup table relationships
- Avoids circular references with visited set
- Enables hierarchical data model visualization

---

### 2. Hierarchical Table Structure

**Purpose:** Display tables organized by their relationship depth to the Patient table.

**Implementation:**
- Patient table at depth 0 (root)
- Direct children at depth 1 (tables with direct FK to Patient)
- Indirect children at depth 2+ (tables linked through intermediate tables)
- Unrelated tables shown last

**Visual Indicators:**
- 🔵 Patient - Blue background, "Root" badge
- 🟢 Direct children - Green arrow, "Direct" badge
- 🟡 Depth 2 - Yellow arrows, "Level 2" badge
- 🟠 Depth 3+ - Orange indicators, "Level X" badge
- ⚪ Unrelated - Gray indicator, "Unlinked" badge

**Path Display:**
Shows FK chain to Patient (e.g., `radiotherapy → diagnosis → patient`)

---

### 3. LLM Client Configuration Management

**Models:**
- `ClientConfiguration` - Stores LLM API credentials and settings
- Fields: model name, provider, base URL, API key, expiry settings

**Views:**
- ✅ List all configurations
- ✅ Create new configuration
- ✅ View configuration details
- ✅ Edit configuration
- ✅ Delete configuration (with usage check)
- ✅ **Test API connection** (see below)

---

### 4. API Connection Testing

**Purpose:** Validate LLM API credentials and connectivity before use.

**Endpoint:** `/extractor/client-configurations/<id>/test-connection/`

**Supported Providers:**
- **OpenAI / Azure OpenAI** - `/v1/chat/completions`
- **Anthropic (Claude)** - `/v1/messages` with proper headers
- **Google (Gemini)** - `/v1/models/{model}:generateContent`
- **Ollama / Local** - `/api/chat` (no authentication)
- **Generic** - OpenAI-compatible endpoints

**Features:**
- ✅ Auto-adds `http://` scheme if missing
- ✅ Provider-specific endpoint routing
- ✅ Adaptive timeout (120s for local, 30s for remote)
- ✅ Response time measurement
- ✅ Detailed error messages with troubleshooting hints
- ✅ Modal UI with real-time feedback

**Ollama Support:**
- Handles slow model loading (60+ seconds for first inference)
- Uses correct `/api/chat` endpoint
- Includes `stream: false` parameter
- No authentication required

**Error Handling:**
- Connection timeout with troubleshooting steps
- Connection errors with diagnostic info
- API errors with status codes and response details

---

### 5. Pydantic Model Generation & Validation

**Purpose:** Generate type-safe Pydantic models from configured extraction schemas.

**PydanticModelBuilder Service:**

**Code Generation:**
- ✅ Generates Pydantic BaseModel classes from ResponseModel configuration
- ✅ Type mapping from Django to Pydantic types
- ✅ Optional field handling
- ✅ Field validators for choices and ranges
- ✅ Nested model support
- ✅ Root model with all table models

**Validation System:**

**1. Configuration Validation** (`validate_model_configuration`)
```python
{
    'valid': True/False,
    'errors': ['No tables configured', ...],
    'warnings': ['Lookup field missing config', ...]
}
```

**2. Code Validation** (`validate_generated_code`)
```python
{
    'valid': True/False,
    'syntax_valid': True/False,
    'runtime_valid': True/False,
    'errors': [...],
    'warnings': [...],
    'test_results': {
        'empty_instantiation': 'success',
        'sample_instantiation': 'success',
        'sample_data': {...}
    }
}
```

**Validation Steps:**
1. **Syntax Check** - AST parsing to catch syntax errors
2. **Runtime Check** - Execute code in isolated namespace
3. **Instantiation Test** - Test with empty data
4. **Sample Data Test** - Test with generated sample data

**3. Data Testing** (`test_model_with_data`)
- Validates actual data against generated model
- Returns validated/transformed data
- Catches validation errors with details

**Integration:**
- Automatic validation in wizard Step 4
- Success/warning messages in UI
- Detailed logging to `logs/debug.log`

---

### 6. Wizard Flow

**Step 1:** Select LLM client configuration
**Step 2:** Select database tables (hierarchical display)
**Step 3:** Select fields for each table
**Step 4:** Review and validate generated Pydantic model

**Features:**
- ✅ Session-based state management
- ✅ Progress bar visualization
- ✅ Real-time schema refresh with AJAX
- ✅ Permission-based access control
- ✅ Automatic validation at each step

---

## Logging Configuration

**Log Files:**
- `/home/santam/chavi_client/logs/debug.log` - Main application log
- `/home/santam/chavi_client/logs/dicom_import.log` - DICOM-specific log

**Loggers:**
- `django` - INFO level (framework logs)
- `client_app` - DEBUG level (client app logs)
- `extractor` - DEBUG level (extractor app logs) ✅ **Added**
- `client_app.services.bulk_dicom_data_import` - DEBUG level (DICOM import)

**Format:**
```
{levelname} {timestamp} {module} {process} {thread} {message} [File: {path}:{line}]
```

---

### 7. Navigation & User Interface

**Homepage Integration:**
- ✅ Comprehensive "LLM-Powered Data Extraction" section on homepage
- ✅ Three-card layout: Upload Files, Configure Models, Extraction Wizard
- ✅ Direct links to all major features
- ✅ Color-coded icons for visual distinction
- ✅ Login-gated access with disabled state for unauthenticated users

**Navigation Bar:**
- ✅ "LLM Extraction" dropdown menu in main navigation
- ✅ Quick access to:
  - Upload Files
  - LLM Clients
  - Response Models
  - Start Wizard (highlighted)
- ✅ Consistent with existing Data Import/Export dropdowns
- ✅ Color-coded icons matching homepage

**URL Structure:**
```
/extractor/files/                          # File upload list
/extractor/files/upload/                   # Upload form
/extractor/files/<id>/                     # File details
/extractor/files/<id>/process/             # Process file
/extractor/files/<id>/delete/              # Delete file
/extractor/processed/<id>/                 # View processed content
/extractor/client-configurations/          # LLM client list
/extractor/response-models/                # Response model list
/extractor/wizard/start/                   # Start wizard
```

---

## Technical Improvements

### Database Schema
- Enhanced `DatabaseTable.clientapp_table_fk_fields` JSONField structure
- Added `patient_path` tracking for hierarchical relationships
- Differentiated forward vs reverse FK relationships

### Code Quality
- Comprehensive error handling
- Detailed logging at all levels
- Transaction safety with retry logic
- Type hints throughout
- Docstrings for all public methods

### UI/UX
- Modern Tailwind CSS styling
- Real-time progress indicators
- Modal dialogs for actions
- Color-coded status badges
- Responsive design

---

## Known Issues & Limitations

1. **CSS Linter Warnings** - False positives in `wizard_step2.html` line 45 (Django template syntax in inline styles - can be ignored)

2. **Reverse FK Population** - `reverse_fks` structure prepared but not yet populated

3. **Lookup Table Handling** - Lookup tables are skipped in patient path tracing (by design)

---

## Next Steps / Future Enhancements

### High Priority
- [ ] Implement actual LLM extraction logic
- [ ] Add extraction job queue/scheduling
- [ ] Store extraction results
- [ ] Add result validation and review UI

### Medium Priority
- [ ] Populate `reverse_fks` in FK relationship tracking
- [ ] Add batch testing for Pydantic models
- [ ] Export/import ResponseModel configurations
- [ ] Add model versioning

### Low Priority
- [ ] Add more LLM provider support (Cohere, etc.)
- [ ] Custom field validators in UI
- [ ] Extraction performance metrics
- [ ] A/B testing different prompts

---

## File Structure

```
extractor/
├── models.py                           # Core data models
├── views.py                            # Wizard views and API endpoints
├── urls.py                             # URL routing
├── admin.py                            # Django admin configuration
├── services/
│   ├── schema_discovery.py            # Schema introspection service
│   └── pydantic_builder.py            # Pydantic model generation
├── templates/extractor/
│   ├── wizard_start.html              # Schema refresh page
│   ├── wizard_step1.html              # Client selection
│   ├── wizard_step2.html              # Table selection (hierarchical)
│   ├── wizard_step3.html              # Field selection
│   ├── wizard_step4.html              # Review and validation
│   ├── wizard_complete.html           # Completion page
│   ├── response_model_list.html       # List all models
│   ├── response_model_detail.html     # Model details
│   ├── client_configuration_*.html    # Client config CRUD
│   └── ...
└── PROGRESS.md                         # This file
```

---

## Testing Checklist

### Schema Discovery
- [x] Discovers all client_app models
- [x] Correctly maps Django field types
- [x] Handles FK relationships
- [x] Traces paths to Patient table
- [x] Identifies lookup tables
- [x] Progress callback works

### API Connection Testing
- [x] OpenAI endpoint works
- [x] Ollama endpoint works (with 120s timeout)
- [x] Error messages are helpful
- [x] Troubleshooting hints appear
- [x] Modal UI functions correctly

### Pydantic Model Generation
- [x] Generates valid Python syntax
- [x] Code executes without errors
- [x] Models can be instantiated
- [x] Validators work correctly
- [x] Validation results logged

### Wizard Flow
- [x] All steps accessible
- [x] Session state persists
- [x] Hierarchical table display works
- [x] Field selection saves correctly
- [x] Final validation runs

---

## Performance Notes

- Schema discovery: ~2-5 seconds for full client_app introspection
- API connection test: 1-5s (remote), 60-90s (Ollama first call), 5-10s (Ollama subsequent)
- Pydantic generation: <1 second
- Pydantic validation: <1 second

---

## Dependencies

**Python Packages:**
- Django 6.0.6
- Pydantic (for model generation)
- requests (for API testing)

**Frontend:**
- Tailwind CSS
- Font Awesome icons
- Alpine.js (minimal usage)

---

## Contributors

- Development Session: June 8, 2026
- Focus: Schema discovery refinement, API testing, validation system

---

## References

- Django Model Meta API: https://docs.djangoproject.com/en/6.0/ref/models/meta/
- Pydantic Documentation: https://docs.pydantic.dev/
- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
