# Lookup API Documentation

## Overview

The Lookup API provides **read-only GET endpoints** for all lookup tables in the CHAVI system. These endpoints allow users to query reference data for clinical coding, anatomical sites, treatment types, and other standardized terminology.

## Base URL

```
/api/lookup/
```

## Authentication

- **Public Access**: No authentication required
- **Read-Only**: Only GET requests are supported

## Available Endpoints

All endpoints follow the pattern: `/api/lookup/{table-name}/`

### Core Lookup Tables

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/laterality/` | Left, Right, Bilateral, etc. |
| `/api/lookup/icd-code/` | ICD-11 diagnosis codes |
| `/api/lookup/fma-code/` | Foundational Model of Anatomy codes |
| `/api/lookup/presentation/` | Presentation types |
| `/api/lookup/outcome-type/` | Outcome types (recurrence, progression, etc.) |
| `/api/lookup/lesion-type/` | Lesion location types (local, nodal, distant) |
| `/api/lookup/response-type/` | Treatment response types (CR, PR, SD, PD) |

### Genomic & Molecular

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/protein/` | Protein names and UniProt IDs |
| `/api/lookup/gene/` | Gene names |
| `/api/lookup/clinical-significance/` | Clinical significance of mutations |
| `/api/lookup/cytogenetic-abnormality/` | Cytogenetic abnormalities |
| `/api/lookup/epigenetic-abnormality-type/` | Epigenetic abnormality types |
| `/api/lookup/expression-units/` | Gene expression units |

### Treatment Related

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/treatment-intent/` | Curative, Palliative, etc. |
| `/api/lookup/treatment-sequence/` | Neoadjuvant, Adjuvant, etc. |
| `/api/lookup/systemic-agent/` | Chemotherapy and targeted therapy agents |
| `/api/lookup/systemic-therapy-type/` | Types of systemic therapy |
| `/api/lookup/systemic-therapy-regimen/` | Treatment regimens |
| `/api/lookup/drug-route/` | Routes of drug administration |

### Radiotherapy

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/radiotherapy-modality/` | EBRT, Brachytherapy, etc. |
| `/api/lookup/radiotherapy-type/` | 2D, 3D-CRT, IMRT, etc. |
| `/api/lookup/radiotherapy-technique/` | Treatment techniques |
| `/api/lookup/radiotherapy-volume-type/` | GTV, CTV, PTV, etc. |
| `/api/lookup/rt-location/` | Anatomical locations for RT volumes |

### Pathology

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/pathology/` | Histological types |
| `/api/lookup/grade/` | Tumor grades |
| `/api/lookup/pathology-descriptors/` | Pathology descriptors |
| `/api/lookup/major-cancer-category/` | Major cancer categories |
| `/api/lookup/diagnostic-modality/` | Biopsy, Cytology, etc. |
| `/api/lookup/margin-status/` | Surgical margin status |
| `/api/lookup/treatment-effect/` | Treatment effect grading |

### Immunohistochemistry

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/ihc-antibody/` | IHC antibodies |
| `/api/lookup/ihc-result/` | IHC results (Positive, Negative, etc.) |
| `/api/lookup/ihc-staining-intensity/` | Staining intensity levels |

### Surgery

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/surgical-procedures/` | Surgical procedure types |
| `/api/lookup/nodal-assessment-type/` | Types of nodal assessment |

### Staging

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/staging-system/` | TNM, FIGO, etc. |
| `/api/lookup/staging-type/` | Clinical, Pathological, etc. |
| `/api/lookup/ajcc-stage-prefix/` | AJCC stage prefixes |
| `/api/lookup/ajcc-stage-suffix/` | AJCC stage suffixes |
| `/api/lookup/ajcc-t-stage-descriptor/` | T stage descriptors |
| `/api/lookup/ajcc-n-stage-descriptor/` | N stage descriptors |
| `/api/lookup/ajcc-m-stage-descriptor/` | M stage descriptors |
| `/api/lookup/stage-descriptor/` | General stage descriptors |

### Clinical Assessment

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/laboratory-test/` | Laboratory test types |
| `/api/lookup/symptoms/` | Symptom types |
| `/api/lookup/severity/` | Severity levels |
| `/api/lookup/comorbidity/` | Comorbidity types |
| `/api/lookup/performance-status/` | ECOG, Karnofsky, etc. |
| `/api/lookup/ctcae-grade/` | CTCAE adverse event grades |
| `/api/lookup/outcome/` | Patient outcome types |

### Units of Measurement

| Endpoint | Description |
|----------|-------------|
| `/api/lookup/volume-units/` | Volume measurement units |
| `/api/lookup/size-units/` | Size measurement units |
| `/api/lookup/dose-units/` | Radiation dose units |
| `/api/lookup/mass-units/` | Mass measurement units |
| `/api/lookup/lab-results-units/` | Laboratory result units |

## Request Examples

### List All Records

```bash
# Get all laterality options
GET /api/lookup/laterality/

# Response
{
  "count": 5,
  "next": null,
  "previous": null,
  "results": [
    {
      "code": "LEFT",
      "label": "Left",
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
    },
    {
      "code": "RIGHT",
      "label": "Right",
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

### Get Single Record

```bash
# Get specific record by code
GET /api/lookup/laterality/LEFT/

# Response
{
  "code": "LEFT",
  "label": "Left",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### Search Records

```bash
# Search by code or label
GET /api/lookup/pathology/?search=carcinoma

# Response
{
  "count": 15,
  "next": null,
  "previous": null,
  "results": [
    {
      "code": "IDC",
      "label": "Invasive Ductal Carcinoma",
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

### Ordering

```bash
# Order by label (ascending)
GET /api/lookup/gene/?ordering=label

# Order by label (descending)
GET /api/lookup/gene/?ordering=-label
```

### Pagination

```bash
# Get page 2 with 50 results per page
GET /api/lookup/icd-code/?page=2&page_size=50
```

## Response Format

### Standard Lookup Table Response

```json
{
  "code": "string",           // Primary key
  "label": "string",          // Human-readable label
  "created_at": "datetime",   // Creation timestamp
  "updated_at": "datetime"    // Last update timestamp
}
```

### Extended Fields

Some lookup tables have additional fields:

**ICD Code:**
```json
{
  "code": "string",
  "label": "string",
  "icd_version": "decimal",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

**Protein:**
```json
{
  "code": "string",
  "gene_name": "string",
  "uniport_id": "string",
  "protein_name": "string",
  "all_gene_names": "string"
}
```

**CTCAE Grade:**
```json
{
  "code": "string",
  "ctcae_term": "string",
  "meddra_code": "string",
  "ctcae_grade": "integer",
  "description": "string",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

**Units (Volume, Size, Dose, Mass, Lab Results):**
```json
{
  "code": "string",
  "label": "string",
  "unit_abbreviation": "string",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

**Surgical Procedures:**
```json
{
  "code": "string",
  "label": "string",
  "description": "string",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

**Staging System:**
```json
{
  "code": "string",
  "label": "string",
  "staging_system_version": "string",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

## Query Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `search` | Search in code and label fields | `?search=breast` |
| `ordering` | Order results by field (prefix with `-` for descending) | `?ordering=-label` |
| `page` | Page number for pagination | `?page=2` |
| `page_size` | Number of results per page (max 100) | `?page_size=50` |

## Error Responses

### 404 Not Found
```json
{
  "detail": "Not found."
}
```

### 400 Bad Request
```json
{
  "detail": "Invalid page."
}
```

## Usage in CSV Import

When importing clinical data via CSV, use the `label` field values from these lookup tables. The import system will automatically match labels to their corresponding codes.

Example:
```csv
patient_id,tumor_side,histological_type
P001,Left,Invasive Ductal Carcinoma
```

The system will look up:
- `tumor_side`: "Left" → `LookupLaterality` with code "LEFT"
- `histological_type`: "Invasive Ductal Carcinoma" → `LookupPathology` with code "IDC"

## Notes

- All endpoints are **read-only** (GET only)
- No authentication required for public access
- Results are paginated (100 records per page by default)
- Search is case-insensitive
- Primary key is `code` field for all lookup tables
