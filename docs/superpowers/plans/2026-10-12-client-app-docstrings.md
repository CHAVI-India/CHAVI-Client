# Client-App Model Docstrings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every extraction-capable model in `client_app/models.py` a proper docstring that the stage-2 extraction pathway injects directly into the per-table LLM prompt as table context.

**Architecture:** Docstrings are the single source of table-level extraction semantics (what the table records, record-granularity rules, conventions). They are read at extraction time via `DatabaseTable.clientapp_content_type.model_class().__doc__` — no new database fields, no `client_app` schema changes. Each docstring is its own task with its own commit so the user can review and amend them one by one. A final lint test pins the standard.

**Tech Stack:** Django (existing codebase), Python docstrings, Django test runner.

**Spec:** This plan. Docstring standard (below) is the contract.

## Global Constraints

- **No client_app schema changes** — docstrings are Python source only; zero migrations.
- **Docstring standard** (every extraction-capable model):
  1. Line 1: what the table records and what it is keyed to (per patient / per diagnosis / per pathology).
  2. Line 2+: **record granularity** — when the extraction returns ONE record vs MULTIPLE records for this table from one document. This line is the load-bearing one; it must always appear.
  3. Optional: unit/specimen/convention notes (e.g. specimens of one report are parts of the same record).
  - Instructional tone (it is read by an LLM as instructions), ≤ 6 lines, no markdown, no code.
- **Extraction-capable list** (27 models): `Patient, Diagnosis, Pathology, Immunohistochemistry, Cytogenetics, SomaticGenomicAlterations, GeneExpressionData, EpigeneticData, StageInformation, Surgery, Lesion, LesionResponse, Symptom, Comorbidity, ConcomitantMedications, SystemicTherapy, SystemicTherapySchedule, Radiotherapy, RadiotherapyVolume, RadiotherapyDoseVolumeData, AdverseEffects, OtherTreatment, Outcome, PatientReportedOutcome, PatientOutcome, LaboratoryResults, PatientAssessment`.
- **Non-extraction (out of scope, no docstring required):** `SiteConfiguration, Project, PatientDicomFile, DICOMStudy, DICOMStudyProject, DICOMSeries, DICOMInstance, UnprocessedDICOMStudies, StudyTypeRule, BulkDICOMUpload, BulkDICOMUploadSession, BulkDICOMStudyMatch, TaskRun, Notification`.
- **Test command:** `venv/bin/python manage.py test client_app` (run from repo root).
- **Branch:** continue on the current branch — do NOT create a new branch.

---

### Task 1: Docstring standard + lint test (failing first)

**Files:**
- Modify: `client_app/tests.py`

**Interfaces:**
- Produces: `EXTRACTION_CAPABLE_MODELS` — `dict[str, type[models.Model]]` mapping model name to class, used by the lint test and (later, in the prompt-redesign plan) as the authoritative extraction-capable list.

- [ ] **Step 1: Write the failing test**

Append to `client_app/tests.py`:

```python
EXTRACTION_CAPABLE_MODELS = {
    name: getattr(models, cls) for name, cls in {
        'Patient': 'Patient',
        'Diagnosis': 'Diagnosis',
        'Pathology': 'Pathology',
        'Immunohistochemistry': 'Immunohistochemistry',
        'Cytogenetics': 'Cytogenetics',
        'SomaticGenomicAlterations': 'SomaticGenomicAlterations',
        'GeneExpressionData': 'GeneExpressionData',
        'EpigeneticData': 'EpigeneticData',
        'StageInformation': 'StageInformation',
        'Surgery': 'Surgery',
        'Lesion': 'Lesion',
        'LesionResponse': 'LesionResponse',
        'Symptom': 'Symptom',
        'Comorbidity': 'Comorbidity',
        'ConcomitantMedications': 'ConcomitantMedications',
        'SystemicTherapy': 'SystemicTherapy',
        'SystemicTherapySchedule': 'SystemicTherapySchedule',
        'Radiotherapy': 'Radiotherapy',
        'RadiotherapyVolume': 'RadiotherapyVolume',
        'RadiotherapyDoseVolumeData': 'RadiotherapyDoseVolumeData',
        'AdverseEffects': 'AdverseEffects',
        'OtherTreatment': 'OtherTreatment',
        'Outcome': 'Outcome',
        'PatientReportedOutcome': 'PatientReportedOutcome',
        'PatientOutcome': 'PatientOutcome',
        'LaboratoryResults': 'LaboratoryResults',
        'PatientAssessment': 'PatientAssessment',
    }.items()
}


class ModelDocstringTests(TestCase):
    def test_extraction_capable_models_carry_a_record_granularity_docstring(self):
        for name, model in EXTRACTION_CAPABLE_MODELS.items():
            doc = (model.__doc__ or '').strip()
            with self.subTest(model=name):
                self.assertGreaterEqual(len(doc), 80, f"{name} docstring too short")
                self.assertRegex(
                    doc, r'record',
                    f"{name} docstring must state record granularity")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python manage.py test client_app.tests.ModelDocstringTests`
Expected: FAIL — current docstrings are one-liners without a "record" line (e.g. Pathology: "This a table which stores the pathology information related to a diagnosis.")

- [ ] **Step 3: (No implementation yet)** — the docstrings are written in Tasks 2–28; this task only lands the standard and the failing test. Commit the test alone with a `test:` prefix so review is clean.

- [ ] **Step 4: Commit**

```bash
git add client_app/tests.py
git commit -m "test: require record-granularity docstrings on extraction-capable models"
```

---

### Tasks 2–28: One docstring per model

**Format per task (same shape, one model each):**

**Files:** Modify `client_app/models.py` (the model's docstring only — no field changes).

Each task below contains the exact docstring to install. Review each one independently; amend wording before approving — the text goes verbatim into LLM prompts.

- [ ] **Task 2: Patient**

```python
class Patient(models.Model):
    '''
    A patient in the study: demographics and patient-level data reported in
    the clinical document. Record granularity: one record per patient; when
    the document covers more than one patient, return one record per patient
    in the order the patients appear.
    '''
```

- [ ] **Task 3: Diagnosis**

```python
class Diagnosis(models.Model):
    '''
    The clinical diagnosis of a patient's disease: site, side, modality,
    dates and related diagnosis-level data. Record granularity: one record
    per distinct diagnosis the document describes; most reports describe
    exactly one, so add further records only when the document clearly lists
    additional diagnoses.
    '''
```

- [ ] **Task 4: Pathology**

```python
class Pathology(models.Model):
    '''
    Histopathology findings for a diagnosis: gross and microscopic
    description, tumor dimensions, margins, lymph-node findings. Record
    granularity: one record per pathology report. The specimens listed in a
    report (for example a primary resection specimen plus lymph-node
    specimens from the same case) are parts of the SAME record, not
    separate records - combine every finding of the report into that one
    record. Microscopic descriptions such as histology, invasion and
    margins describe the report as a whole.
    '''
```

- [ ] **Task 5: Immunohistochemistry**

```python
class Immunohistochemistry(models.Model):
    '''
    Immunohistochemistry (IHC) staining results for a pathology specimen:
    marker, staining pattern and scoring. Record granularity: one record
    per marker (protein) reported; when one report covers several markers,
    each marker gets its own record and all of them belong to the same
    pathology record.
    '''
```

- [ ] **Task 6: Cytogenetics**

```python
class Cytogenetics(models.Model):
    '''
    Cytogenetic findings for a pathology specimen: gene and cytogenetic
    abnormality with result. Record granularity: one record per
    gene/abnormality the document describes.
    '''
```

- [ ] **Task 7: SomaticGenomicAlterations**

```python
class SomaticGenomicAlterations(models.Model):
    '''
    Somatic genomic alterations found in a pathology specimen: gene,
    alteration type and result. Record granularity: one record per
    alteration (gene/variant) the document describes.
    '''
```

- [ ] **Task 8: GeneExpressionData**

```python
class GeneExpressionData(models.Model):
    '''
    Gene expression measurements for a pathology specimen: gene, expression
    value and units. Record granularity: one record per gene measured.
    '''
```

- [ ] **Task 9: EpigeneticData**

```python
class EpigeneticData(models.Model):
    '''
    Epigenetic findings for a pathology specimen: gene/locus, abnormality
    type and result. Record granularity: one record per gene/locus the
    document describes.
    '''
```

- [ ] **Task 10: StageInformation**

```python
class StageInformation(models.Model):
    '''
    Cancer staging for a diagnosis: TNM descriptors, overall stage group and
    the staging system used. Record granularity: one record per diagnosis; a
    report's staging line (e.g. "pT3 pN3b, AJCC 8th edition") is ONE stage
    assessment, so split it across the fields of a single record.
    '''
```

- [ ] **Task 11: Surgery**

```python
class Surgery(models.Model):
    '''
    Surgical procedures performed for a diagnosis: type, side, date, nodal
    assessment and reconstruction. Record granularity: one record per
    distinct surgical procedure/event the document describes; separate
    procedures reported in the same document are separate records.
    '''
```

- [ ] **Task 12: Lesion**

```python
class Lesion(models.Model):
    '''
    Anatomical lesions of a diagnosis: site, type, laterality, size and
    volume. Record granularity: one record per distinct lesion described; a
    document may describe several lesions and each gets its own record.
    '''
```

- [ ] **Task 13: LesionResponse**

```python
class LesionResponse(models.Model):
    '''
    Assessment of a lesion's response to treatment, including residual size
    and volume. Record granularity: one record per distinct response
    assessment described for a lesion; a baseline assessment and a
    post-treatment assessment of the same lesion are separate records.
    '''
```

- [ ] **Task 14: Symptom**

```python
class Symptom(models.Model):
    '''
    Symptoms experienced by a patient, with severity where stated. Record
    granularity: one record per distinct symptom described.
    '''
```

- [ ] **Task 15: Comorbidity**

```python
class Comorbidity(models.Model):
    '''
    Co-existing diseases or conditions (comorbidities) of a patient. Record
    granularity: one record per distinct comorbidity described.
    '''
```

- [ ] **Task 16: ConcomitantMedications**

```python
class ConcomitantMedications(models.Model):
    '''
    Medications a patient takes alongside their cancer treatment: drug,
    dose, route. Record granularity: one record per distinct medication
    described.
    '''
```

- [ ] **Task 17: SystemicTherapy**

```python
class SystemicTherapy(models.Model):
    '''
    A systemic (pharmacological) treatment course for a diagnosis: type,
    regimen, sequence, intent and dosing. Record granularity: one record per
    distinct therapy course described; separate courses in the same document
    are separate records.
    '''
```

- [ ] **Task 18: SystemicTherapySchedule**

```python
class SystemicTherapySchedule(models.Model):
    '''
    The drug schedule of a systemic therapy course: agents, routes, doses
    and units per line of the schedule. Record granularity: one record per
    scheduled drug/line; all lines of one course belong to the same
    SystemicTherapy record.
    '''
```

- [ ] **Task 19: Radiotherapy**

```python
class Radiotherapy(models.Model):
    '''
    A radiotherapy course for a diagnosis: modality, dose, technique, side,
    intent and fractions. Record granularity: one record per distinct
    radiotherapy course the document describes.
    '''
```

- [ ] **Task 20: RadiotherapyVolume**

```python
class RadiotherapyVolume(models.Model):
    '''
    Target volumes treated as part of a radiotherapy course. Record
    granularity: one record per distinct volume/structure described.
    '''
```

- [ ] **Task 21: RadiotherapyDoseVolumeData**

```python
class RadiotherapyDoseVolumeData(models.Model):
    '''
    Dose-volume metrics for a structure treated in a radiotherapy course.
    Record granularity: one record per distinct structure with reported dose
    metrics.
    '''
```

- [ ] **Task 22: AdverseEffects**

```python
class AdverseEffects(models.Model):
    '''
    Treatment adverse effects for a diagnosis, graded per CTCAE. Record
    granularity: one record per distinct adverse effect described.
    '''
```

- [ ] **Task 23: OtherTreatment**

```python
class OtherTreatment(models.Model):
    '''
    Treatment other than systemic therapy or radiotherapy (for example
    interventional or local treatments), with its intent. Record granularity:
    one record per distinct other-treatment event described.
    '''
```

- [ ] **Task 24: Outcome**

```python
class Outcome(models.Model):
    '''
    Outcome events of a diagnosis: outcome type, date and status. Record
    granularity: one record per distinct outcome event described.
    '''
```

- [ ] **Task 25: PatientReportedOutcome**

```python
class PatientReportedOutcome(models.Model):
    '''
    Patient-reported outcome measurements for a patient (prognostic and
    outcome scores). Record granularity: one record per distinct reported
    outcome measurement described.
    '''
```

- [ ] **Task 26: PatientOutcome**

```python
class PatientOutcome(models.Model):
    '''
    Overall outcome status of a patient (for example alive/dead status).
    Record granularity: one record per patient.
    '''
```

- [ ] **Task 27: LaboratoryResults**

```python
class LaboratoryResults(models.Model):
    '''
    Laboratory test results for a patient: test, quantitative or qualitative
    value, units. Record granularity: one record per distinct test result
    described; different values of the same test (for example on different
    dates) are separate records.
    '''
```

- [ ] **Task 28: PatientAssessment**

```python
class PatientAssessment(models.Model):
    '''
    Clinical assessments of a patient (for example performance status).
    Record granularity: one record per distinct assessment described.
    '''
```

**Execution note:** implement docstring tasks in any order; each is an independent review gate. After all 27 land:

- [ ] **Step: Run the lint test to verify it passes**

Run: `venv/bin/python manage.py test client_app.tests.ModelDocstringTests`
Expected: PASS

- [ ] **Step: Full client_app regression + commit any stragglers**

Run: `venv/bin/python manage.py test client_app`
Expected: PASS (no new failures vs `main`)

```bash
git add client_app/models.py
git commit -m "docs: record-granularity docstrings for extraction-capable models"
```

---

## Self-Review

- **Spec coverage:** "proper docstrings for each table … directly used as prompts" → Tasks 2–28 draft the exact texts; the prompt-redesign plan consumes them via `__doc__`. "Draft a separate plan so each docstring can be reviewed separately" → one task + one commit per model. "No client_app model changes" → Global Constraint 1 (docstrings only, zero migrations).
- **Placeholder scan:** every docstring is written out verbatim; no TBDs.
- **Type consistency:** `EXTRACTION_CAPABLE_MODELS` (Task 1) is the single name the lint test and the prompt-redesign plan's docstring-lookup helper will reference.
- **Known limitations (accepted):** docstrings are static Python source; a model edited without its docstring drifting risks stale prompt context — the lint test catches missing granularity text but not stale semantics (human review duty).
