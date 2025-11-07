# Test Data for Import Workflow

This directory contains comprehensive test CSV files to validate all features of the 12-step import workflow.

## Test Files Overview

### 1. `test_import_basic.csv` - Basic Import with Missing Relationships
**Purpose:** Test basic field mapping and missing FK relationships (Step 10)

**Features:**
- Patient data with different field names than model (e.g., `PatientCode` → `patient_id`)
- Diagnosis data (requires FK to Patient - auto-handled)
- Surgery data (requires FK to Diagnosis - will prompt in Step 10)
- Chemotherapy data (requires FK to Diagnosis - will prompt in Step 10)
- Some records have surgery, some have chemo, some have both, some have neither
- Missing values in various fields

**Models Covered:**
- Patient (Level 0)
- Diagnosis (Level 1 - FK to Patient)
- Surgery (Level 2 - FK to Diagnosis)
- Chemotherapy (Level 2 - FK to Diagnosis)

**Expected Workflow:**
1. Map `PatientCode` → `patient_id`
2. Select Patient, Diagnosis, Surgery, Chemotherapy models
3. Map fields (DOB, Gender, VitalStatus, etc.)
4. Map lookup values (Gender: Male→M, Female→F; VitalStatus: Alive→01, Deceased→02)
5. **Step 9:** Set default values for unmapped required fields (e.g., `center`, `project`)
6. **Step 10:** Handle missing relationships:
   - Surgery.diagnosis → Create new Diagnosis OR link to existing
   - Chemotherapy.diagnosis → Create new Diagnosis OR link to existing

---

### 2. `test_import_duration.csv` - Duration Field Testing
**Purpose:** Test duration-based date calculations (Step 7)

**Features:**
- Age at diagnosis in years (calculate DOB or diagnosis date)
- Survival in months (calculate death date from diagnosis date)
- Disease-free survival in days (calculate recurrence date)
- Time to recurrence in days
- Various date formats

**Duration Mappings:**
- `AgeAtDx` (years) + `DiagDate` → `date_of_birth` (subtract)
- `SurvivalMonths` (months) + `DiagDate` → `date_of_death` (add)
- `DiseaseFreeSurvivalDays` (days) + `DiagDate` → `date_of_recurrence` (add)
- `TimeToRecurrence` (days) + `DiagDate` → `recurrence_date` (add)

**Expected Workflow:**
1. Map patient ID
2. Select Patient, Diagnosis models
3. Map fields
4. **Step 7:** Configure duration mappings
   - Reference date: `DiagDate`
   - Duration field: `AgeAtDx`, unit: years, operation: subtract → `date_of_birth`
   - Duration field: `SurvivalMonths`, unit: months, operation: add → `date_of_death`

---

### 3. `test_import_wide_format.csv` - Column-Value Mapping (Wide Format)
**Purpose:** Test wide-format data where column names contain field information (Step 5)

**Features:**
- Immunohistochemistry markers as columns (ER_Status, ER_Value, PR_Status, PR_Value, etc.)
- Each marker has status and value columns
- Need to map column patterns to Immunohistochemistry records

**Column-Value Mappings:**
- Column pattern: `*_Status` → `marker` field (column name before underscore)
- Column pattern: `*_Value` → `percentage` field
- Creates multiple Immunohistochemistry records per patient

**Expected Workflow:**
1. Map patient ID
2. Select Patient, Diagnosis, Pathology, Immunohistochemistry models
3. Map basic fields
4. **Step 5:** Configure column-value mappings
   - CSV columns matching `*_Status` → Immunohistochemistry.marker (extract marker name)
   - CSV columns matching `*_Value` → Immunohistochemistry.percentage
5. **Step 10:** Handle Pathology → Diagnosis relationship

---

### 4. `test_import_long_format.csv` - Repeating Rows (Long Format)
**Purpose:** Test long-format data where each row represents a treatment event

**Features:**
- Same patient appears in multiple rows
- Each row represents a different treatment (Surgery, Chemotherapy, Radiotherapy)
- Patient and Diagnosis data repeated across rows
- Treatment-specific fields vary by treatment type

**Expected Workflow:**
1. Map patient ID
2. Select Patient, Diagnosis, Surgery, Chemotherapy, Radiotherapy models
3. Map fields conditionally based on TreatmentType
4. System should:
   - Create one Patient record per unique PatientCode
   - Create one Diagnosis record per patient
   - Create multiple treatment records (Surgery, Chemo, Radiation) per patient
5. **Step 10:** All treatments link to same Diagnosis

---

### 5. `test_import_hierarchy.csv` - Deep Hierarchy Testing
**Purpose:** Test complex 3-level hierarchy with multiple child records

**Features:**
- Patient → Diagnosis → Pathology → Immunohistochemistry (4 levels)
- Patient → Diagnosis → Surgery (3 levels)
- Patient → Diagnosis → Radiotherapy (3 levels)
- Multiple IHC markers per pathology
- Some patients have multiple diagnoses

**Hierarchy:**
```
Patient (Level 0)
└── Diagnosis (Level 1)
    ├── Pathology (Level 2)
    │   └── Immunohistochemistry (Level 3)
    ├── Surgery (Level 2)
    └── Radiotherapy (Level 2)
```

**Expected Workflow:**
1. Map patient ID
2. Select all models: Patient, Diagnosis, Pathology, Immunohistochemistry, Surgery, Radiotherapy
3. Map fields for each model
4. **Step 10:** Handle relationships:
   - Pathology.diagnosis → Create new or link existing
   - Immunohistochemistry.pathology → Create new or link existing
   - Surgery.diagnosis → Link to same diagnosis as pathology
   - Radiotherapy.diagnosis → Link to same diagnosis

---

### 6. `test_import_missing_values.csv` - Missing Values & Default Values
**Purpose:** Test handling of missing/empty values and default value assignment (Step 9)

**Features:**
- Many empty cells (missing values)
- Some required fields are missing entirely (no column in CSV)
- Tests nullable vs required fields
- Tests default value assignment

**Missing Data Scenarios:**
- Missing `Status` for some patients
- Missing `Stage` for some diagnoses
- Missing `BirthDate` for one patient
- Missing `Gender` for one patient
- Missing `DiagnosisDate` for one patient
- Missing `Height` or `Weight` for several patients
- Missing `PerformanceStatus` for one patient

**Expected Workflow:**
1. Map patient ID
2. Select Patient, Diagnosis models
3. Map available fields
4. **Step 9:** Set default values for unmapped required fields:
   - If `center` is required but not in CSV → set default center
   - If `project` is required but not in CSV → set default project
   - If `vital_status` is missing → set default value (e.g., "01" for Alive)
5. System should handle nullable fields gracefully (leave as NULL)

---

## Testing Checklist

### Step 1: Upload CSV
- ✅ Upload each test file
- ✅ Verify CSV preview shows correct data

### Step 2: Patient ID Mapping
- ✅ Map different patient ID column names (PatientCode, PatientID, ID, SubjectID)
- ✅ Verify patient existence check

### Step 3: Model Selection
- ✅ Select appropriate models for each test file
- ✅ Verify hierarchy display

### Step 4: Field Mapping
- ✅ Map CSV columns to model fields
- ✅ Verify FK fields to selected models are hidden
- ✅ Verify lookup FK fields are still shown
- ✅ Test multi-column mapping (wide format)

### Step 5: Column-Value Mapping
- ✅ Test with `test_import_wide_format.csv`
- ✅ Map column patterns to create multiple records

### Step 6: Date Format
- ✅ Configure date formats for date columns
- ✅ Test various formats (YYYY-MM-DD, MM/DD/YYYY, etc.)

### Step 7: Duration Date
- ✅ Test with `test_import_duration.csv`
- ✅ Configure duration calculations
- ✅ Verify calculated dates in preview

### Step 8: Lookup Mapping
- ✅ Map CSV values to lookup codes
- ✅ Test: Male→M, Female→F, Alive→01, Deceased→02
- ✅ Use Select2 for easy searching

### Step 9: Default Values (NEW)
- ✅ Test with `test_import_missing_values.csv`
- ✅ Set default values for unmapped required fields
- ✅ Test different field types (lookup, date, boolean, text)
- ✅ Verify Select2 works for lookup fields

### Step 10: Missing Relationships (REDESIGNED)
- ✅ Test auto-handling of Patient FK
- ✅ Test linking to existing parent records
- ✅ Test creating new parent records
- ✅ Verify UI shows existing records with patient info
- ✅ Test with all hierarchy levels

### Step 11: Review
- ✅ Verify all mappings are displayed:
  - Field mappings
  - Default values
  - Parent record mappings
  - Lookup mappings
  - Duration mappings
  - Date formats
- ✅ Review JSON preview
- ✅ Verify UUIDs are generated

### Step 12: Execute Import
- ✅ Import each test file
- ✅ Verify records are created correctly
- ✅ Verify parent records are created before children
- ✅ Verify relationships are linked correctly
- ✅ Check database for correct data

---

## Expected Results

### test_import_basic.csv
- 5 Patient records
- 5 Diagnosis records (one per patient)
- 3 Surgery records (P001, P002, P003)
- 2 Chemotherapy records (P001, P002, P004)

### test_import_duration.csv
- 5 Patient records with calculated birth dates
- 5 Diagnosis records
- Calculated death dates for deceased patients
- Calculated recurrence dates where applicable

### test_import_wide_format.csv
- 5 Patient records
- 5 Diagnosis records
- 5 Pathology records
- ~20 Immunohistochemistry records (4 markers × 5 patients, minus missing data)

### test_import_long_format.csv
- 5 unique Patient records (despite 11 rows)
- 5 Diagnosis records
- 5 Surgery records
- 2 Chemotherapy records
- 3 Radiotherapy records

### test_import_hierarchy.csv
- 5 Patient records
- 5 Diagnosis records
- 5 Pathology records
- ~15 Immunohistochemistry records
- 5 Surgery records (where applicable)
- 3 Radiotherapy records

### test_import_missing_values.csv
- 10 Patient records (with defaults for missing required fields)
- 9 Diagnosis records (one patient missing diagnosis date)
- NULL values for optional missing fields
- Default values for required missing fields

---

## Notes

1. **Lookup Values:** Ensure lookup tables are populated before import:
   - Gender: M (Male), F (Female)
   - VitalStatus: 01 (Alive), 02 (Deceased)
   - Site: Various ICD-O-3 codes (C34.1, C50.9, C18.7, C56.9, C61.9)
   - Stage: Stage I, Stage II, Stage III, Stage IIIA, Stage IV

2. **Date Formats:** Test files use YYYY-MM-DD format. Test with other formats as needed.

3. **Performance:** Long format file (11 rows) should create 5 patients, demonstrating proper deduplication.

4. **Error Handling:** Missing values file tests system's ability to handle incomplete data gracefully.

5. **Relationships:** Hierarchy file tests the most complex scenario with 4-level deep relationships.
