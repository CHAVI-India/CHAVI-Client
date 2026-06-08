# File Upload & Processing System

## Overview

The file upload system allows users to upload documents (PDF, CSV, Excel) for data extraction. Files are automatically processed into usable formats before being sent to the LLM for extraction.

---

## Features

### Supported File Types

1. **PDF Files** (`.pdf`)
   - Converted to Markdown using `markitdown`
   - Preserves document structure and formatting
   - Output: Single `.md` file

2. **CSV Files** (`.csv`)
   - Used directly without conversion
   - No processing required
   - Ready for immediate extraction

3. **Excel Files** (`.xlsx`)
   - Each sheet converted to a separate CSV file
   - Uses `pandas` for conversion
   - Output: Multiple `.csv` files (one per sheet)

---

## Installation Requirements

### Required Python Packages

```bash
# For PDF processing
pip install markitdown

# For Excel processing
pip install pandas openpyxl
```

Add to `requirements.txt`:
```
markitdown
pandas
openpyxl
```

---

## File Processing Flow

```
1. Upload File
   ↓
2. File Saved to media/uploads/
   ↓
3. FileUpload record created (status: PENDING)
   ↓
4. User clicks "Process File"
   ↓
5. File processed based on type:
   - PDF → Markdown (media/processed/pdf/)
   - CSV → Direct use
   - Excel → CSV files (media/processed/excel/)
   ↓
6. ProcessedText record(s) created
   ↓
7. Status updated to COMPLETED
   ↓
8. Ready for extraction
```

---

## URL Structure

```
/extractor/files/                          # List all uploaded files
/extractor/files/upload/                   # Upload new file
/extractor/files/<id>/                     # View file details
/extractor/files/<id>/process/             # Process file (POST)
/extractor/files/<id>/delete/              # Delete file (POST)
/extractor/processed/<id>/                 # View processed content
```

---

## Models

### FileUpload

Stores information about uploaded files.

**Fields:**
- `file` - FileField (uploaded file)
- `file_type` - Auto-detected from extension
- `patient_id` - Optional FK to Patient
- `processing_status` - PENDING/PROCESSING/COMPLETED/FAILED
- `created_at`, `updated_at` - Timestamps

**Processing Status:**
- `PENDING` - Uploaded but not processed
- `PROCESSING` - Currently being processed
- `COMPLETED` - Successfully processed
- `FAILED` - Processing failed

### ProcessedText

Stores information about processed files.

**Fields:**
- `file_upload` - FK to FileUpload
- `processed_file_path` - Path to processed file
- `processed_by_user` - User who processed the file
- `created_at`, `updated_at` - Timestamps

---

## FileProcessorService

Service class for file processing operations.

### Methods

#### `process_file(file_upload, user=None)`
Main processing method that routes to specific processors.

**Returns:**
```python
{
    'success': bool,
    'message': str,
    'processed_files': [
        {
            'id': int,
            'path': str,
            'type': str,
            'sheet_name': str  # Excel only
        }
    ],
    'errors': [str]
}
```

#### `_process_pdf(file_upload, user=None)`
Converts PDF to Markdown using markitdown.

**Output Location:** `media/processed/pdf/{basename}_{id}.md`

#### `_process_csv(file_upload, user=None)`
Registers CSV file without conversion.

**Output:** Uses original file path

#### `_process_excel(file_upload, user=None)`
Converts each Excel sheet to a separate CSV file.

**Output Location:** `media/processed/excel/{basename}_{id}_{sheetname}.csv`

#### `get_processed_content(processed_text)`
Reads and returns the content of a processed file.

#### `delete_processed_files(file_upload)`
Deletes all processed files associated with a FileUpload.

---

## UI Components

### File Upload List
- Table view of all uploaded files
- Status indicators with color coding
- File type icons
- Patient linkage display
- Quick actions (view, process, delete)

### File Upload Form
- Drag-and-drop file upload
- Patient selection dropdown
- File type validation
- File size display
- Supported formats info

### File Detail Page
- File information cards
- Processing status
- Process button (if pending/failed)
- List of processed files
- Delete confirmation modal

### Processed Text Viewer
- Full content display
- Copy to clipboard button
- File metadata
- Patient linkage info

---

## Permissions

All views require appropriate permissions:

- `extractor.view_fileupload` - View uploaded files
- `extractor.add_fileupload` - Upload new files
- `extractor.change_fileupload` - Process files
- `extractor.delete_fileupload` - Delete files
- `extractor.view_processedtext` - View processed content

---

## Error Handling

### Common Errors

1. **Missing Dependencies**
   ```
   Error: markitdown library not installed
   Solution: pip install markitdown
   ```

2. **Missing Dependencies (Excel)**
   ```
   Error: pandas library not installed
   Solution: pip install pandas openpyxl
   ```

3. **File Not Found**
   - Processed file path incorrect
   - File deleted from filesystem
   - Check media directory permissions

4. **Processing Failed**
   - Check logs for specific error
   - Verify file is not corrupted
   - Ensure sufficient disk space

---

## File Storage Structure

```
media/
├── uploads/                    # Original uploaded files
│   ├── file1.pdf
│   ├── file2.csv
│   └── file3.xlsx
└── processed/                  # Processed files
    ├── pdf/                    # Converted PDFs
    │   └── file1_123.md
    └── excel/                  # Converted Excel sheets
        ├── file3_456_Sheet1.csv
        └── file3_456_Sheet2.csv
```

---

## Usage Example

### 1. Upload a File

```python
# Via UI: Navigate to /extractor/files/upload/
# Select file and optionally link to patient
# Click "Upload File"
```

### 2. Process the File

```python
# Via UI: Navigate to file detail page
# Click "Process File" button
# Wait for processing to complete
```

### 3. View Processed Content

```python
# Via UI: Click "View" on processed file
# Content displayed in browser
# Copy to clipboard if needed
```

### 4. Use in Extraction

```python
# Processed content is now ready
# Link to ResponseModel for extraction
# LLM will receive the processed text
```

---

## Integration with Extraction Pipeline

The processed files are designed to integrate with the extraction pipeline:

1. **File Upload** - User uploads document
2. **Processing** - Convert to usable format
3. **ResponseModel Selection** - Choose extraction schema
4. **LLM Extraction** - Send processed content to LLM
5. **Data Validation** - Validate against Pydantic model
6. **Database Storage** - Save extracted data to client_app models

---

## Testing Checklist

- [ ] Upload PDF file
- [ ] Process PDF to Markdown
- [ ] View Markdown content
- [ ] Upload CSV file
- [ ] Process CSV (no conversion)
- [ ] Upload Excel file
- [ ] Process Excel to multiple CSVs
- [ ] View each CSV sheet
- [ ] Link file to patient
- [ ] Delete file with processed versions
- [ ] Test drag-and-drop upload
- [ ] Test file size validation
- [ ] Test unsupported file type
- [ ] Test processing error handling

---

## Future Enhancements

- [ ] Support for DOCX files
- [ ] Support for images (OCR)
- [ ] Batch file upload
- [ ] Progress bar for large files
- [ ] File preview before processing
- [ ] Automatic patient detection from filename
- [ ] File versioning
- [ ] Processing queue for large files
- [ ] Email notification on completion
- [ ] Export processed files

---

## Troubleshooting

### PDF Processing Issues

**Problem:** PDF conversion fails
**Solutions:**
- Ensure markitdown is installed
- Check PDF is not password-protected
- Verify PDF is not corrupted
- Check file size (very large PDFs may timeout)

### Excel Processing Issues

**Problem:** Excel conversion fails
**Solutions:**
- Ensure pandas and openpyxl are installed
- Check Excel file is not corrupted
- Verify Excel file format (.xlsx not .xls)
- Check for special characters in sheet names

### Permission Issues

**Problem:** Cannot upload/process files
**Solutions:**
- Check user has required permissions
- Verify media directory is writable
- Check Django file upload settings
- Ensure MEDIA_ROOT is configured

---

## Configuration

### Django Settings

```python
# settings.py

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50MB
```

### Create Media Directories

```bash
mkdir -p media/uploads
mkdir -p media/processed/pdf
mkdir -p media/processed/excel
```

---

## Logging

All file processing operations are logged to `logs/debug.log`:

```
INFO: File uploaded: file.pdf
INFO: Processing PDF: /path/to/file.pdf
INFO: Converted PDF to Markdown: /path/to/output.md
INFO: Successfully processed file: file.pdf
```

Error logs include full traceback for debugging.
