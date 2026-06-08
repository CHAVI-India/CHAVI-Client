# LLM Extraction - Navigation Guide

## Overview

The LLM Extraction features are now fully integrated into the CHAVI Client interface with multiple access points for easy navigation.

---

## Access Points

### 1. Homepage - Main Section

When you visit the homepage (`/`), you'll see a dedicated **"LLM-Powered Data Extraction"** section with three cards:

#### 📤 Upload Files Card
- **Upload New File** - Direct upload form
- **View All Files** - List of all uploaded files
- Supports: PDF, CSV, Excel files
- Optional patient linkage

#### ⚙️ Configure Models Card
- **LLM Clients** - Manage API connections (OpenAI, Ollama, etc.)
- **Response Models** - Define extraction schemas
- Test API connections
- Configure extraction pipelines

#### 🧙 Extraction Wizard Card
- **Start Wizard** - Step-by-step extraction setup
- Select tables and fields
- Generate Pydantic models
- Validate configurations

---

### 2. Navigation Bar - Dropdown Menu

The main navigation bar includes an **"LLM Extraction"** dropdown with quick access to:

```
┌─────────────────────────────────┐
│ 📤 Upload Files                 │
│ 🖥️  LLM Clients                 │
│ 🔗 Response Models              │
├─────────────────────────────────┤
│ 🧙 Start Wizard (highlighted)   │
└─────────────────────────────────┘
```

**Location:** Between "Data Import" and "Data Export" dropdowns

---

## Complete Navigation Map

### File Upload Workflow

```
Homepage → Upload Files
    ↓
Upload Form (/extractor/files/upload/)
    ↓
File Detail Page (/extractor/files/<id>/)
    ↓
Process File (click button)
    ↓
View Processed Content (/extractor/processed/<id>/)
```

### Configuration Workflow

```
Homepage → Configure Models
    ↓
LLM Clients (/extractor/client-configurations/)
    ├─ Create New Client
    ├─ Test Connection
    └─ Edit/Delete
    
Response Models (/extractor/response-models/)
    ├─ View Details
    └─ Edit Configuration
```

### Wizard Workflow

```
Homepage → Start Wizard
    ↓
Step 1: Select LLM Client (/extractor/wizard/step1/)
    ↓
Step 2: Select Tables (/extractor/wizard/step2/)
    ↓
Step 3: Select Fields (/extractor/wizard/step3/)
    ↓
Step 4: Review & Validate (/extractor/wizard/step4/)
    ↓
Complete (/extractor/wizard/complete/<id>/)
```

---

## URL Reference

### File Upload URLs
| URL | Purpose |
|-----|---------|
| `/extractor/files/` | List all uploaded files |
| `/extractor/files/upload/` | Upload new file |
| `/extractor/files/<id>/` | View file details |
| `/extractor/files/<id>/process/` | Process file (POST) |
| `/extractor/files/<id>/delete/` | Delete file (POST) |
| `/extractor/processed/<id>/` | View processed content |

### Configuration URLs
| URL | Purpose |
|-----|---------|
| `/extractor/client-configurations/` | List LLM clients |
| `/extractor/client-configurations/create/` | Create new client |
| `/extractor/client-configurations/<id>/` | View client details |
| `/extractor/client-configurations/<id>/edit/` | Edit client |
| `/extractor/client-configurations/<id>/delete/` | Delete client |
| `/extractor/client-configurations/<id>/test-connection/` | Test API connection |
| `/extractor/response-models/` | List response models |
| `/extractor/response-models/<id>/` | View model details |

### Wizard URLs
| URL | Purpose |
|-----|---------|
| `/extractor/wizard/start/` | Start wizard & refresh schema |
| `/extractor/wizard/step1/` | Select LLM client |
| `/extractor/wizard/step2/` | Select tables |
| `/extractor/wizard/step3/` | Select fields |
| `/extractor/wizard/step4/` | Review & validate |
| `/extractor/wizard/complete/<id>/` | Completion page |

---

## Visual Guide

### Homepage Layout

```
┌─────────────────────────────────────────────────────────────┐
│                    CHAVI Client Homepage                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  📊 Data Import                                              │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ CSV Import   │  │ DICOM Upload │                        │
│  └──────────────┘  └──────────────┘                        │
│                                                              │
│  🔮 LLM-Powered Data Extraction                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ 📤 Upload    │  │ ⚙️ Configure │  │ 🧙 Wizard    │     │
│  │    Files     │  │    Models    │  │              │     │
│  │              │  │              │  │              │     │
│  │ • Upload New │  │ • LLM Clients│  │ • Start      │     │
│  │ • View All   │  │ • Response   │  │   Wizard     │     │
│  │              │  │   Models     │  │              │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
│  📤 Data Export                                              │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ Patient Data │  │ DICOM Export │                        │
│  └──────────────┘  └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

### Navigation Bar

```
┌─────────────────────────────────────────────────────────────┐
│ CHAVI  [Home] [Data Import ▼] [LLM Extraction ▼] [Data...  │
│                                                              │
│                     ┌─────────────────────────┐             │
│                     │ 📤 Upload Files         │             │
│                     │ 🖥️  LLM Clients         │             │
│                     │ 🔗 Response Models      │             │
│                     ├─────────────────────────┤             │
│                     │ 🧙 Start Wizard         │             │
│                     └─────────────────────────┘             │
└─────────────────────────────────────────────────────────────┘
```

---

## Feature Highlights

### 🎨 Visual Design
- **Color-coded icons** for easy identification
  - 🔵 Blue - File Upload
  - 🟣 Purple - Configuration
  - 🟢 Green - Wizard
- **Status badges** with colors
  - 🟡 Yellow - Pending
  - 🔵 Blue - Processing
  - 🟢 Green - Completed
  - 🔴 Red - Failed
- **Hover effects** on all interactive elements
- **Responsive design** for mobile and desktop

### 🔒 Security
- All pages require authentication
- Permission-based access control
- Disabled state for unauthenticated users
- Login prompts on restricted pages

### 📱 User Experience
- **Drag-and-drop** file upload
- **Real-time** processing status
- **Copy to clipboard** for processed content
- **Confirmation modals** for destructive actions
- **Breadcrumb navigation** in wizard
- **Progress indicators** throughout

---

## Quick Start Guide

### For New Users

1. **Login** to your CHAVI account
2. Navigate to **Homepage**
3. Find the **"LLM-Powered Data Extraction"** section
4. Choose your starting point:
   - **Upload Files** if you have documents to process
   - **Configure Models** if you need to set up LLM clients
   - **Start Wizard** for guided extraction setup

### For Returning Users

- Use the **Navigation Bar** dropdown for quick access
- **Upload Files** is always one click away
- **Recent files** appear at the top of the list
- **Wizard** can be restarted anytime

---

## Tips & Best Practices

### File Upload
- ✅ Link files to patients for organized extraction
- ✅ Process files immediately after upload
- ✅ Check processed content before extraction
- ✅ Use descriptive filenames

### Configuration
- ✅ Test API connections before use
- ✅ Keep API keys secure
- ✅ Set expiry dates for rotating keys
- ✅ Document your response models

### Wizard
- ✅ Refresh schema before starting
- ✅ Select tables in hierarchical order
- ✅ Choose only necessary fields
- ✅ Validate generated models

---

## Troubleshooting

### Can't see LLM Extraction menu?
- Ensure you're logged in
- Check user permissions
- Refresh the page

### Upload button disabled?
- Login required
- Check file size (max 50MB)
- Verify file type (PDF, CSV, XLSX only)

### Processing failed?
- Check dependencies installed (`markitdown`, `pandas`, `openpyxl`)
- Verify file is not corrupted
- Check logs for detailed errors

---

## Support

For issues or questions:
- Check the **Documentation** (Docs link in navbar)
- Review **logs/debug.log** for errors
- Contact system administrator
- Refer to **FILE_UPLOAD_README.md** for detailed file processing info
- Refer to **PROGRESS.md** for feature documentation
