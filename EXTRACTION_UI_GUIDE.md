# Data Extraction UI - Implementation Guide

## Overview
A comprehensive UI system for extracting structured data from processed files using Instructor and LLMs.

## Components Created

### 1. Service Layer
**File:** `extractor/services/instructor_extractor.py`

**Key Features:**
- `InstructorExtractionService` - Main service class
- Dynamic Pydantic model generation from ResponseModel configuration
- Support for multiple LLM providers (OpenAI, Anthropic, Ollama, etc.)
- Bulk extraction capability
- Automatic saving of extraction results

**Methods:**
- `get_instructor_client()` - Creates Instructor-patched client based on provider
- `build_dynamic_pydantic_model()` - Builds Pydantic model from ResponseModel
- `get_messages()` - Prepares messages for LLM
- `extract_data()` - Performs extraction using Instructor
- `save_extraction_results()` - Saves results to ExtractionResult model
- `bulk_extract()` - Processes multiple files in batch

### 2. Views
**File:** `extractor/views.py`

**New Views Added:**
1. **`extraction_dashboard`** - Main dashboard showing:
   - Processed files grouped by patient
   - Files without patient link
   - Bulk selection interface
   - Response model selection
   - Statistics (patients, files, models)

2. **`extraction_start`** - Handles extraction initiation:
   - Validates selected files and response model
   - Triggers bulk extraction
   - Provides feedback on success/failure

3. **`extraction_results_list`** - Lists all extraction jobs:
   - Shows status, patient, model, field count
   - Sortable and filterable
   - Links to detailed view

4. **`extraction_job_detail`** - Detailed view of extraction job:
   - Shows all extracted fields grouped by table
   - Allows editing/verification of extracted data
   - Shows accuracy status
   - Displays source document
   - Timing and error information

5. **`extraction_result_update`** - Updates extraction results:
   - Edit extracted data
   - Change accuracy rating
   - Track verification

### 3. Templates

#### `extraction_dashboard.html`
- Patient-grouped file selection
- Collapsible patient sections
- Bulk select/deselect functionality
- Response model dropdown
- Real-time selection counter
- Visual indicators for already-extracted files

#### `extraction_results_list.html`
- Table view of all extraction jobs
- Status badges (pending, processing, completed, failed)
- Patient and model information
- Field count display
- Quick access to details

#### `extraction_job_detail.html`
- Comprehensive job information
- Results grouped by database table
- Inline editing forms for each field
- Accuracy badges (accurate, partial, inaccurate)
- Edit tracking
- Verification timestamps
- Source document viewer

### 4. URL Routes
**File:** `extractor/urls.py`

```python
path('extraction/', views.extraction_dashboard, name='extraction_dashboard')
path('extraction/start/', views.extraction_start, name='extraction_start')
path('extraction/results/', views.extraction_results_list, name='extraction_results_list')
path('extraction/results/<int:job_id>/', views.extraction_job_detail, name='extraction_job_detail')
path('extraction/results/<int:result_id>/update/', views.extraction_result_update, name='extraction_result_update')
```

## Workflow

### 1. Extraction Dashboard
1. User navigates to `/extractor/extraction/`
2. System displays:
   - All processed files grouped by patient
   - Files without patient assignment
   - Available response models
3. User selects:
   - Response model to use
   - Files to process (individual or bulk)
4. User clicks "Start Extraction"

### 2. Extraction Process
1. System creates ExtractionJob records
2. For each file:
   - Retrieves processed content
   - Builds dynamic Pydantic model
   - Calls Instructor with LLM
   - Saves extracted data as ExtractionResult records
3. Updates job status (pending → processing → completed/failed)

### 3. Results Review
1. User views extraction results list
2. Clicks on specific job to see details
3. Reviews extracted data grouped by table
4. Can edit/verify each field:
   - Correct extracted values
   - Set accuracy rating
   - Add verification timestamp

### 4. Data Verification
- Each field shows:
  - Original extracted value
  - Edited value (if modified)
  - Accuracy status
  - Verification info
- Inline editing forms
- Track who verified and when

## Features

### Bulk Processing
- Select multiple files across patients
- Process all in one operation
- Progress feedback
- Success/failure counts

### Patient Grouping
- Files organized by patient
- Collapsible sections
- Patient-level select all
- Unlinked files section

### Status Tracking
- Pending: Job created, not started
- Processing: Currently extracting
- Completed: Successfully extracted
- Failed: Error occurred

### Data Quality
- Accuracy ratings: Accurate, Partial, Inaccurate
- Edit tracking
- Verification workflow
- Audit trail

### Error Handling
- Captures extraction errors
- Displays error messages
- Allows retry
- Logs failures

## Database Models Used

### ExtractionJob
- Links to ResponseModel and ProcessedText
- Tracks status, timing, tokens
- Stores raw LLM response
- Records who performed extraction

### ExtractionResult
- One record per extracted field
- Stores extracted and edited data
- Tracks accuracy and verification
- Links to DatabaseField

## Next Steps (Not Implemented)

The following are mentioned in docstrings but not yet implemented:
1. **Record Creation/Update** - Creating actual records in client_app
2. **RecordCreation tracking** - Linking extractions to created records
3. **RecordCreationField** - Tracking which fields were used

## Usage Example

1. **Setup:**
   - Configure ClientConfiguration (LLM settings)
   - Create ResponseModel (define what to extract)
   - Upload and process files

2. **Extract:**
   ```
   Navigate to: /extractor/extraction/
   Select response model
   Select files to process
   Click "Start Extraction"
   ```

3. **Review:**
   ```
   Navigate to: /extractor/extraction/results/
   Click on job to view details
   Edit/verify extracted data
   Mark accuracy
   ```

4. **Verify:**
   - Review each field
   - Correct if needed
   - Set accuracy rating
   - Save changes

## Permissions Required

- `extractor.view_processedtext` - View dashboard
- `extractor.add_extractionjob` - Start extraction
- `extractor.view_extractionjob` - View results
- `extractor.change_extractionresult` - Edit/verify data

## Technical Notes

- Uses Instructor library for structured extraction
- Supports multiple LLM providers
- Dynamic Pydantic model generation
- Encrypted storage for sensitive data
- Audit trail for all changes
- Optimized queries with select_related

## UI/UX Features

- Modern, responsive design
- TailwindCSS styling
- Font Awesome icons
- Interactive JavaScript
- Real-time feedback
- Collapsible sections
- Inline editing
- Status badges
- Progress indicators
