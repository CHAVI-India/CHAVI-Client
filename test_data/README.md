# CHAVI Data Import Test Files

This directory contains synthetic CSV test files for testing the CHAVI data import wizard with various scenarios.

## Test Files Overview

### 1. `test_single_row_per_patient.csv`
**Purpose**: Test basic import with one row per patient
**Characteristics**:
- 5 patients (P001-P005)
- Single diagnosis per patient
- Single pathology record per patient
- Clean data with all required fields populated
- Tests: Patient → Diagnosis → Pathology hierarchy

**Use Case**: Baseline test for simple data structure

---

### 2. `test_multiple_rows_per_patient.csv`
**Purpose**: Test repeating data where one patient has multiple lesions
**Characteristics**:
- 3 patients (P001-P003)
- Multiple rows per patient (P001: 3 rows, P002: 3 rows, P003: 3 rows)
- Each row represents a different lesion for the same diagnosis
- Tests UUID generation and grouping by patient
- Tests: Patient → Diagnosis → Multiple Lesions

**Use Case**: Tests how the system handles repeating child records

**Expected Behavior**:
- Should create 1 patient record per patient_id
- Should create 1 diagnosis record per patient
- Should create multiple lesion records per diagnosis

---

### 3. `test_missing_data_inconsistencies.csv`
**Purpose**: Test data validation and error handling
**Characteristics**:
- 10 patients with various data quality issues:
  - **P002**: Missing date_of_birth
  - **P003**: Missing diagnosis_date
  - **P004**: Missing pathology_date and specimen_type
  - **P005**: Missing histological_type
  - **P006**: Missing histological_grade
  - **P007**: Missing gender and lymph_nodes_in_specimen
  - **P008**: Invalid date_of_birth (future date: 2025-01-01)
  - **P009**: Invalid necrosis_percentage (150.0 - exceeds 100%)
  - **P009**: diagnosis_date before registration_date
  - **P010**: Negative tumor dimension (-2.5)

**Use Case**: Tests Step 5 validation and error reporting

**Expected Errors**:
- Date validation errors
- Range validation errors (percentage > 100, negative dimensions)
- Missing required field errors
- Invalid choice field values

---

### 4. `test_deep_nested_relationships.csv`
**Purpose**: Test complex hierarchical relationships across multiple levels
**Characteristics**:
- 3 patients with deep nesting:
  - Patient → Diagnosis → Pathology → Immunohistochemistry
  - Patient → Diagnosis → Pathology → Somatic Genomic Alterations
  - Patient → Diagnosis → Lesion → Lesion Response
  - Patient → Diagnosis → Outcome
- Multiple IHC tests per pathology
- Multiple genomic alterations per pathology
- Multiple lesions with responses per diagnosis
- Tests 4-5 levels of nesting

**Use Case**: Tests the most complex data structure the system can handle

**Expected JSON Structure**:
```json
{
  "patients": [
    {
      "patient_id": "P001",
      "diagnosis": [
        {
          "pathology": [
            {
              "immunohistochemistry": [...],
              "somatic_genomic_alterations": [...]
            }
          ],
          "lesion": [
            {
              "lesion_response": [...]
            }
          ],
          "outcome": [...]
        }
      ]
    }
  ]
}
```

---

### 5. `test_validation_errors.csv`
**Purpose**: Test custom validators and constraint violations
**Characteristics**:
- 10 patients with specific validation errors:
  - **P002**: Invalid gender value ("InvalidGender")
  - **P003**: necrosis_percentage = 150.0 (exceeds 100%)
  - **P003**: percentage_positive_tumor_cells = 120.5 (exceeds 100%)
  - **P003**: allred_score = 9 (exceeds max of 8)
  - **P004**: Negative necrosis_percentage (-5.0)
  - **P004**: allred_score = 10 (exceeds max of 8)
  - **P005**: Negative percentage_positive_tumor_cells (-10.0)
  - **P005**: tps_score = 105.0 (exceeds 100%)
  - **P006**: Future date_of_birth (2025-06-01)
  - **P006**: allred_score = 15 (exceeds max of 8)
  - **P007**: diagnosis_date after registration_date
  - **P007**: tps_score = 200.0 (exceeds 100%)
  - **P008**: diagnosis_date before registration_date
  - **P008**: Negative allred_score (-2)
  - **P009**: Negative tumor dimension (-3.5)

**Use Case**: Tests all custom validators from models.py:
- `percentage_validator` (0-100 range)
- `positive_decimal_validator` (>= 0)
- `allred_score_validator` (0-8 range)
- Date validation (start before end)

**Expected Behavior**: Step 5 should catch all these errors and display them

---

### 6. `test_complex_hierarchical.csv`
**Purpose**: Simplified version for quick hierarchical testing
**Characteristics**:
- 2 patients with multiple related records
- Fewer fields for easier debugging
- Tests Patient → Diagnosis → Pathology → IHC + Lesion + Outcome

---

## Testing Workflow

### Step-by-Step Testing Process:

1. **Upload File** (Step 1)
   - Upload one of the test CSV files
   - Verify file is parsed correctly
   - Check row count and preview

2. **Field Mapping** (Step 2)
   - Map CSV columns to CHAVI fields
   - Verify fuzzy matching suggestions
   - Test manual field selection

3. **Date Format Config** (Step 3)
   - Configure date formats for date fields
   - Test different separators and formats

4. **Date Interval Config** (Step 4)
   - Skip if no interval fields needed

5. **Validation** (Step 5)
   - **Critical**: Check for validation errors
   - Verify custom validators are working
   - Test error reporting UI

6. **Lookup Matching** (Step 6)
   - Match lookup field values
   - Test fuzzy matching for lookup tables

7. **Static Mapping** (Step 7)
   - Add any static values if needed

8. **UUID Mapping** (Step 8)
   - Configure UUID generation fields
   - Test hierarchical model dependencies

9. **JSON Preview** (Step 9)
   - **Critical**: Verify JSON structure
   - Check patient grouping
   - Verify nested relationships
   - Download and inspect JSON

10. **Execute Import** (Step 10)
    - Run the import
    - Check success/failure counts
    - Verify data in database

---

## Expected Results by File

### test_single_row_per_patient.csv
- **Patients**: 5
- **Diagnoses**: 5
- **Pathology Records**: 5
- **Errors**: 0

### test_multiple_rows_per_patient.csv
- **Patients**: 3
- **Diagnoses**: 3
- **Lesions**: 9 (3 per patient)
- **Errors**: 0

### test_missing_data_inconsistencies.csv
- **Patients**: 10
- **Expected Validation Errors**: ~8-10 errors
- **Should Proceed**: Yes (with warnings)

### test_deep_nested_relationships.csv
- **Patients**: 3
- **Diagnoses**: 3
- **Pathology Records**: 3
- **IHC Records**: 6-9
- **Somatic Alterations**: 6
- **Lesions**: 9
- **Lesion Responses**: 9
- **Outcomes**: 3-4
- **Total Records**: ~40-50

### test_validation_errors.csv
- **Patients**: 10
- **Expected Validation Errors**: 15-20 errors
- **Should Fail**: Some records should fail validation

---

## Key Testing Scenarios

### Scenario 1: UUID Generation and Grouping
**File**: `test_multiple_rows_per_patient.csv`
**Test**: Verify that multiple rows with same patient_id are grouped correctly
**Expected**: One patient record with multiple child records

### Scenario 2: Missing Data Handling
**File**: `test_missing_data_inconsistencies.csv`
**Test**: Verify system handles missing optional fields gracefully
**Expected**: Import succeeds with warnings for missing optional fields

### Scenario 3: Validation Error Detection
**File**: `test_validation_errors.csv`
**Test**: Verify all custom validators catch errors in Step 5
**Expected**: Clear error messages for each validation failure

### Scenario 4: Deep Nesting
**File**: `test_deep_nested_relationships.csv`
**Test**: Verify JSON generator handles 4-5 levels of nesting
**Expected**: Properly structured hierarchical JSON

---

## Notes

- All test files use realistic field names from client_app models
- Dates are in YYYY-MM-DD format (can be changed in Step 3)
- Lookup field values may need to be matched in Step 6
- UUID fields are auto-generated and should not be in CSV
- Foreign key relationships are handled via UUID mapping in Step 8
