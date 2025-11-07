# Step 10: Missing FK Relationships - Interface Explanation

## Overview
Step 10 now groups FK relationships by **parent model** instead of by child model. This prevents duplicate parent creation when multiple child models need the same parent.

## Interface Design

### Scenario 1: No Existing Parent Records in Database

**Example:** Importing Surgery and SystemicTherapy, both need Diagnosis, but no Diagnosis records exist for the patients in CSV.

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 Diagnosis                                                │
│ Required by: [Surgery] [SystemicTherapy]                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ ⚠️ No Existing Diagnosis Records                            │
│ No Diagnosis records found for the patients in your CSV.    │
│ A new Diagnosis will be created during import.              │
│                                                              │
│ ○ Create New Diagnosis (CHECKED)                            │
│   Provide values to create a new Diagnosis record           │
│   (will be shared by all child models)                      │
│                                                              │
│   ┌──────────────────────────────────────┐                 │
│   │ Diagnosis Date *                     │                 │
│   │ [Date Input Field]                   │                 │
│   │                                       │                 │
│   │ Primary Site *                        │                 │
│   │ [Lookup Dropdown with Select2]       │                 │
│   │                                       │                 │
│   │ Stage *                               │                 │
│   │ [Lookup Dropdown with Select2]       │                 │
│   └──────────────────────────────────────┘                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Key Points:**
- Only "Create New" option shown (no radio button needed)
- Amber info box explains why
- One Diagnosis will be created and shared by Surgery AND SystemicTherapy
- User fills in required fields once

---

### Scenario 2: Existing Parent Records Found in Database

**Example:** Importing Surgery and SystemicTherapy, both need Diagnosis, and Diagnosis records exist for some patients.

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 Diagnosis                                                │
│ Required by: [Surgery] [SystemicTherapy]                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ ● Link to Existing Diagnosis (CHECKED)                      │
│   Select from existing Diagnosis records in the database    │
│                                                              │
│   ┌──────────────────────────────────────┐                 │
│   │ [Dropdown with Select2]              │                 │
│   │ -- Select existing Diagnosis --      │                 │
│   │ ID: abc123... (Patient: P001) - Lung │                 │
│   │ ID: def456... (Patient: P002) - Breast│                │
│   │ ID: ghi789... (Patient: P003) - Colon│                 │
│   └──────────────────────────────────────┘                 │
│   15 existing record(s) found for patients in CSV          │
│                                                              │
│ ○ Create New Diagnosis                                      │
│   Provide values to create a new Diagnosis record           │
│   (will be shared by all child models)                      │
│                                                              │
│   [Hidden until radio selected]                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Key Points:**
- Two radio options: "Link to Existing" (default) and "Create New"
- Dropdown shows existing Diagnosis records with patient info
- Select2 makes it searchable
- Shows count of existing records
- If user selects "Create New", form fields appear (same as Scenario 1)

---

### Scenario 3: Multiple Parent Models Needed

**Example:** Importing Surgery, SystemicTherapy, and Radiotherapy. Surgery needs Diagnosis, all three need Pathology.

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 Diagnosis                                                │
│ Required by: [Surgery]                                      │
├─────────────────────────────────────────────────────────────┤
│ [Options for Diagnosis...]                                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 📊 Pathology                                                │
│ Required by: [Surgery] [SystemicTherapy] [Radiotherapy]     │
├─────────────────────────────────────────────────────────────┤
│ [Options for Pathology...]                                  │
└─────────────────────────────────────────────────────────────┘
```

**Key Points:**
- Each parent model gets its own card
- Shows which child models need it
- One decision per parent model
- All children share the same parent instance

---

## User Workflow

### If Existing Records Found:
1. User sees parent model card (e.g., "Diagnosis")
2. Sees which child models need it (e.g., "Surgery, SystemicTherapy")
3. **Option A:** Select "Link to Existing" (default)
   - Choose from dropdown of existing records
   - Records filtered to patients in CSV
   - Searchable with Select2
4. **Option B:** Select "Create New"
   - Fill in required fields
   - One record created for all children

### If No Existing Records:
1. User sees parent model card
2. Sees amber info box: "No existing records found"
3. Only "Create New" option available (auto-selected)
4. Fills in required fields
5. One record created for all children

---

## Benefits of This Design

✅ **No Duplicate Parents:** One Diagnosis serves both Surgery and SystemicTherapy
✅ **Clear Grouping:** User sees which children need which parent
✅ **Smart Defaults:** 
   - If records exist → defaults to "Link to Existing"
   - If no records → defaults to "Create New"
✅ **Informative:** Shows count of existing records and patient info
✅ **Efficient:** User makes one decision per parent model, not per child
✅ **Searchable:** Select2 on dropdowns for easy finding

---

## Technical Implementation

### View Changes:
- Groups FK relationships by `parent_model` instead of `(child_model, fk_field)`
- Structure: `{parent_model: {children: [...], existing_parents: [...], has_existing_parents: bool}}`
- Queries existing parents once per parent model

### Template Changes:
- Loops through parent models (not child FKs)
- Shows children as badges
- Conditionally shows "Link to Existing" only if records exist
- Field names: `parent_{{ parent_model }}_action`, `parent_{{ parent_model }}_existing`, etc.

### POST Handler:
- Processes by parent model
- Creates one `FileParentRecordMapping` per parent model
- All children reference the same parent mapping

---

## Example Data Flow

**CSV:**
```
PatientCode,DiagnosisDate,TumorSite,SurgeryDate,SurgeryType,ChemoStartDate,ChemoDrug
P001,2020-05-10,Lung,2020-06-15,Lobectomy,2020-07-01,Cisplatin
```

**Selected Models:** Patient, Diagnosis, Surgery, Chemotherapy

**Step 10 Shows:**
```
Diagnosis
Required by: [Surgery] [Chemotherapy]

○ Link to Existing Diagnosis (if any exist)
○ Create New Diagnosis
  - Diagnosis Date: [from DiagnosisDate]
  - Primary Site: [from TumorSite]
```

**Result:**
- One Diagnosis created/linked
- Surgery.diagnosis → points to that Diagnosis
- Chemotherapy.diagnosis → points to that same Diagnosis
