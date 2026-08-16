# Deidentification Integration Plan

Port the full DICOM + clinical-data deidentification pipeline from `chavi-deidentification-app` into a new, self-contained Django app inside `chavi_client` that operates directly on already-imported DICOM files and live Django models (no zip export/import round-trip), and one-time-migrate the legacy mapping DB (patient/study/series/instance ID+date-shift mappings only) so re-running deidentification reproduces identical results for already-processed patients.

## Confirmed decisions
- **Source of truth**: `/mnt/share/chavi-deidentification-app` (PyQt6 desktop app, `dicomutils/` + `app/database/`). `/mnt/share/deidentifcation-app` (Django prototype) is legacy and ignored.
- **Scope**: Full re-implementation of the deidentification algorithms natively in Django (new app), not a wrapper/bridge around the desktop app. Desktop app becomes deprecated once parity is reached.
- **No zip round-trip (NEW)**:
  - **DICOM**: triggered from the new frontend UI (per-study button on the patient dashboard), reads files directly from `study.folder_path` on disk (already populated by `client_app`'s existing DICOM import pipeline). Deidentified copies are written to a separate output location; originals untouched.
  - **Clinical data**: triggered from the same patient dashboard, computes deidentified JSON **in-memory** from live Django models (reusing `client_app.serializers` / the `patient_data_export.py` structure) + the mapping tables below, and returns it as a downloadable zip on-demand. Nothing extra is persisted.
- **Migration (production scope)**: One-time management command imports existing `patients`, `dicom_studies`, `dicom_series`, `dicom_instances` mapping rows from the desktop app's live DB (`data/app.db` + `data/encryption.key` — see Code Map A.1). This is the **only** production migration step — the goal is purely to seed the ID/date-shift mapping tables so that re-running deidentification on the DICOM data already sitting in `chavi_client` reproduces the *exact same* deidentified IDs/dates as before, not to move any files.
- **Deidentified DICOM output migration (`Archive.zip`) is dev-only, NOT part of production**: useful for local testing/parity-checking, but the production runbook never touches it. In production, `deidentify_dicom_studies` regenerates the deidentified DICOM output itself from the (already-imported) originals + migrated mappings.
- **NOT porting old deidentified clinical JSON**: `chavi-deidentification-app/deidentified_json/*.json` will **not** be reused — deidentified clinical JSON is always regenerated fresh via the new deidentify action once mapping data is migrated.
- **Execution**: Long-running DICOM deidentification jobs run as Celery tasks (Celery already configured in `chavi_client`); clinical-data deidentification is fast enough to run synchronously in the triggering view.
- **UI (NEW)**: dedicated frontend pages (Django views + templates, following the `data_import` app's convention), **not Django admin actions**. Single combined per-patient dashboard (studies + clinical data together) per confirmed preference — see "UI/Views" section below.

## Data model rethink: reuse `client_app`'s existing plaintext identifiers (IMPORTANT)
`client_app.Patient.patient_id` and `client_app.DICOMStudy.study_instance_uid` are **already plain, unencrypted `CharField(primary_key=True)`** in the same database (`client_app/models.py:122-126, 224-229`) — they are the canonical, already-accessible original identifiers. There is no need to duplicate or encrypt "original ID" data at the new app's layer; the new app should **foreign-key directly to these existing models** instead of re-storing/encrypting original patient_id/study_instance_uid (as the legacy standalone desktop app had to, since it had no other DB to defer to).

- **Encryption target flips**: encrypt the **deidentified_* columns**, not the original IDs. The actual DICOM file / original record always has the real ID in plain form (via the FK to `client_app`); the database stores the deidentified ID encrypted at rest.
- **Lookup mechanics**: the normal workflow always starts from a plaintext original ID (read from a DICOM file being processed, or from `client_app.Patient`/`DICOMStudy`'s own PK) and looks up the mapping row via a fast, native FK/plain-field query — **never** via the encrypted column. Once the row is located, its one encrypted `deidentified_*` value is decrypted for use. No hash columns or deterministic-encryption tricks needed anywhere.
- **Series/instance level**: new `client_app.DICOMSeries` and `client_app.DICOMInstance` models store original series/instance UIDs, dates, modality, and FoR UIDs as plain fields. The deidentification app's `DeidSeries`/`DeidInstance` FK to these (OneToOne), same pattern as `DeidPatient`→`Patient` and `DeidStudy`→`DICOMStudy`. Only `deidentified_*` fields are encrypted.
- **Collision-check dropped**: legacy code re-verifies each newly-generated `deidentified_*_uid` is DB-unique before saving (defensive, since DICOM UIDs must be globally unique). Given each level is nested under its own already-random parent UID (e.g. `deidentified_series_uid = "<deidentified_study_uid>.<n>"`), true collisions are astronomically unlikely — same trust level already implicitly given to patient UUID4s (no check today). **Decision: skip this check**, no extra hash/lookup columns anywhere in the design.

## New Django app: `deidentification`

### Location & wiring
- New app dir `chavi_client/deidentification/`, added to `INSTALLED_APPS` in `chavi_client/chavi_client/settings.py`.
- New URLs mounted in root `chavi_client/chavi_client/urls.py` via `path('deidentification/', include('deidentification.urls'))`, matching how `data_import` is mounted.

### New `client_app` models: `DICOMSeries` and `DICOMInstance`
The existing `client_app` DB only has `Patient` and `DICOMStudy` — no series or instance models. The deidentification process needs original series/instance UIDs, dates, modality, and frame-of-reference UIDs stored in DB (not just read from files) so that:
1. Referenced SOP instance UID replacement can build complete UID mappings (nested referenced UIDs in DICOM sequences won't be deidentified properly if mappings are incomplete)
2. Referenced frame-of-reference replacement has all FoR UIDs available
3. The deidentification two-pass flow has all metadata fully extracted before deidentification begins

**`client_app.DICOMSeries`** (new model):
- `study` = `ForeignKey(DICOMStudy, on_delete=CASCADE, related_name='series')`
- `series_instance_uid` = `CharField(max_length=128, unique=True)` — DICOM tag (0020,000E)
- `series_date` = `DateField(null=True, blank=True)` — DICOM tag (0008,0021)
- `modality` = `CharField(max_length=16)` — DICOM tag (0008,0060)
- `frame_of_reference_uid` = `CharField(max_length=128, null=True, blank=True)` — DICOM tag (0020,0052)
- `created_at` / `updated_at` = auto timestamps

**`client_app.DICOMInstance`** (new model):
- `series` = `ForeignKey(DICOMSeries, on_delete=CASCADE, related_name='instances')`
- `sop_instance_uid` = `CharField(max_length=128, unique=True)` — DICOM tag (0008,0018)
- `created_at` / `updated_at` = auto timestamps

**Populated by a separate extraction step in the deidentification UI** (not by modifying existing DICOM import pipelines). See "DICOM metadata extraction step" below.

### Deidentification app models (reuse `client_app` FKs for original IDs; encrypt only `deidentified_*` fields via `django-encrypted-model-fields`)
- `DeidPatient`: `OneToOneField(client_app.Patient)` (reuses plaintext `patient_id` PK) + `deidentified_patient_id` (encrypted, plain-text lookup not needed) + `date_shift_value` (**encrypted** `EncryptedIntegerField` — always read after the row is located via the `patient` FK, never queried by its own value, so no lookup/hash-column implications) + `deidentified_date_of_birth` (encrypted). Original `date_of_birth` read via `patient.date_of_birth` FK traversal, not duplicated. **DOB back-fill**: `Patient.date_of_birth` may be NULL (DICOM import doesn't populate it); the deidentification service back-fills it from DICOM `PatientBirthDate` (or `PatientAge`+`StudyDate` fallback) when NULL, and the migration command back-fills it from the legacy `encrypted_date_of_birth`. Clinical DB value always takes priority — never overwritten if already set.
- `DeidStudy`: `OneToOneField(client_app.DICOMStudy)` (reuses plaintext `study_instance_uid` PK) + FK to `DeidPatient` + `deidentified_study_instance_uid` (encrypted) + `deidentified_study_date` (encrypted).
- `DeidSeries`: `OneToOneField(client_app.DICOMSeries)` (reuses plaintext `series_instance_uid` PK) + FK to `DeidStudy` + `deidentified_series_instance_uid` (encrypted) + `deidentified_series_date` (encrypted) + `deidentified_frame_of_reference_uid` (encrypted). Original `frame_of_reference_uid`, `modality`, `series_date` read via `series` FK traversal to `client_app.DICOMSeries`.
- `DeidInstance`: `OneToOneField(client_app.DICOMInstance)` (reuses plaintext `sop_instance_uid` PK) + FK to `DeidSeries` + `deidentified_sop_instance_uid` (encrypted).
- `DeidentificationJob`: tracks a Celery job (source `DICOMStudy` FK, status, progress, output path, error log, counts) — replaces desktop app's `deidentification_history` table.

### Ported logic (from `dicomutils/`)
Reimplement as plain Python services under `deidentification/services/`, replacing `PyQt6.QtSql` calls with Django ORM:
- `patient_deidentification.py` → UUID-based deidentified patient ID, birth-date shift (-100..+100 days), age-fallback logic. **DOB resolution priority**: (1) `Patient.date_of_birth` (clinical DB) → use directly; (2) if NULL, read `PatientBirthDate` from DICOM file → back-fill `Patient.date_of_birth` + use for shift; (3) if no DICOM DOB, use `PatientAge`+`StudyDate` → calculate approximate DOB → back-fill if still NULL + use for shift; (4) last resort: `StudyDate` alone (same as legacy line 192). The service receives the `client_app.Patient` instance and performs `patient.save(update_fields=['date_of_birth'])` when back-filling.
- `study_deidentification.py`, `series_deidentification.py`, `instance_deidentification.py` → UID generation/reuse rules (org-prefix based), date shifting propagated from patient's `date_shift_value`.
- `date_replacement.py`, `name_replacement.py`, `address_phone_replacement.py`, `referenced_sop_instance_replacement.py`, `referenced_frame_of_reference_replacement.py` → ported nearly as-is (pure `pydicom` logic, no DB-driver dependency).
- `dicom_deidentification_flow.py` → orchestrator, refactored into a Celery task (`deidentification/tasks.py`) that: enumerates DICOM files from `study.folder_path` using `Path.rglob('*')`, **sorts them alphabetically** (matching `import_utils.py:83` `valid_files.sort()` — order matters because series numbering is sequential `count + 1` per study, so a different file order would produce different deidentified series UIDs), then processes files in that sorted order (legacy code has no modality-based sorting or deferred processing) → writes output to `deidentification/output/` → updates `DeidentificationJob`. No zip extraction needed — files are already on disk.
- `clinical_data_deidentification.py` → core JSON-walking logic (find/get/set nested value, date shift) ported as-is; driving logic rewritten to operate on an in-memory dict built directly from Django querysets/serializers rather than an uploaded JSON file. `import_clinical_data.py` (zip extraction) is **not needed/ported** — there's no upload step anymore.

### Deidentification Logic Specification (ported from `dicomutils/`)

The following documents the exact deidentification algorithms from each utility file, to be re-implemented natively as Django services. Each section maps the legacy source file to its new Django service equivalent and specifies the logic to port.

---

#### 1. Patient Deidentification (`patient_deidentification.py` → `deidentification/services/patient_deidentification.py`)

**`generate_deidentified_patient_id()`** — *legacy: lines 9-15*
- Generate a UUID4 string, split on `-`, rejoin with `.` → e.g. `a1b2c3d4.e5f6.7890.abcd.ef1234567890`
- No DB collision check (per confirmed decision — UUID4 uniqueness is sufficient)

**`calculate_shifted_date(original_date: str) -> (shifted_date, days_shift)`** — *legacy: lines 17-39*
- Input: date in DICOM `YYYYMMDD` format
- Generate `days_shift = random.randint(-100, 100)` (inclusive range)
- Return `(shifted_date_str, days_shift)` where shifted_date = original ± days_shift, formatted `YYYYMMDD`

**`parse_dicom_age(age_string: str) -> int`** — *legacy: lines 125-151*
- Parse DICOM `AS` VR string: `nnnD` (days), `nnnW` (weeks ×7), `nnnM` (months ×30), `nnnY` (years ×365)
- Returns age in days (approximate)

**`deidentify_patient_data(patient, birth_date, study_date, age) -> (deid_id, deid_dob, days_shift)`** — *legacy: lines 153-206*
- **Django port**: receives `client_app.Patient` instance instead of `db_manager`
- **Lookup**: `DeidPatient.objects.filter(patient=patient).first()` — if exists, return stored values (reuse)
- **DOB resolution priority** (with back-fill per confirmed decision):
  1. If `patient.date_of_birth` is not NULL → use it (convert to `YYYYMMDD` DICOM format)
  2. Else if `birth_date` (from DICOM `PatientBirthDate`) is non-empty → use it, **back-fill** `patient.date_of_birth` via `patient.save(update_fields=['date_of_birth'])`
  3. Else if `age` (from DICOM `PatientAge`) is non-empty → `parse_dicom_age(age)` → `study_date - timedelta(days=age_in_days)` → use calculated DOB; **back-fill** `patient.date_of_birth` if still NULL
  4. Else → use `study_date` as last resort (no back-fill — study date is not a DOB)
- Once DOB is resolved: `calculate_shifted_date(dob)` → `(deidentified_dob, days_shift)`
- Generate `deidentified_patient_id = generate_deidentified_patient_id()`
- Create `DeidPatient` row: `patient=patient`, `deidentified_patient_id`, `date_shift_value=days_shift`, `deidentified_date_of_birth=deid_dob`
- Return `(deidentified_patient_id, deidentified_dob, days_shift)`

---

#### 2. Study Deidentification (`study_deidentification.py` → `deidentification/services/study_deidentification.py`)

**`generate_deidentified_study_uid(deidentified_patient_id) -> str`** — *legacy: lines 7-12*
- Format: `1.2.826.0.1.3680043.10.1561.<3-digit>.<4-digit>.<3-digit>` (hardcoded org root, 3 random parts)
- Note: `deidentified_patient_id` parameter is accepted but **not used** in the UID generation (legacy passes it but doesn't incorporate it)

**`deidentify_study_data(deid_patient, study, study_date, days_shift) -> (deid_study_uid, deid_study_date)`** — *legacy: lines 152-195*
- **Django port**: receives `DeidPatient` and `client_app.DICOMStudy` instances
- **Lookup**: `DeidStudy.objects.filter(study=study).first()` — if exists, return stored values
- Generate new `deidentified_study_uid = generate_deidentified_study_uid()`
- Shift study date: `datetime.strptime(study_date, "%Y%m%d") + timedelta(days=days_shift)` → `YYYYMMDD`
- Create `DeidStudy` row: `study=study`, `deid_patient=deid_patient`, `deidentified_study_instance_uid`, `deidentified_study_date`
- Return `(deidentified_study_uid, deidentified_study_date)`

---

#### 3. Series Deidentification (`series_deidentification.py` → `deidentification/services/series_deidentification.py`)

**`validate_and_correct_uid(uid: str) -> str`** — *legacy: lines 31-51*
- Strip non-digit/non-`.` characters
- Truncate to 64 chars
- Ensure even byte length (pad with trailing `0` if odd)

**`generate_deidentified_series_uid(deid_study_uid, series_number) -> str`** — *legacy: lines 53-59*
- Format: `<deid_study_uid>.<series_number>` (nested under study UID)
- Apply `validate_and_correct_uid()`

**`generate_deidentified_frame_of_reference_uid(deid_series_uid) -> str`** — *legacy: lines 61-68*
- Format: `<deid_series_uid>.<4-digit-random>` (nested under series UID)
- Apply `validate_and_correct_uid()`

**`deidentify_series_data(deid_study, dicom_series, days_shift) -> (deid_series_uid, deid_series_date, deid_frame_uid)`** — *legacy: lines 211-308*
- **Django port**: receives `DeidStudy` instance and `client_app.DICOMSeries` instance (original UIDs/dates/modality read via FK traversal, not passed as loose strings)
- **Lookup**: `DeidSeries.objects.filter(series=dicom_series).first()` — if exists, return stored values (reuse)
- **Series number**: count existing `DeidSeries` for this study → `new_series_number = count + 1`
- Generate `deid_series_uid = generate_deidentified_series_uid(deid_study_uid, new_series_number)`
- **Collision retry loop** (legacy lines 244-261): increment `new_series_number` and regenerate if `deid_series_uid` already exists in DB — **skip per confirmed decision** (nested random-ID uniqueness is sufficient; series-number sequencing via `count + 1` is still preserved)
- **Frame of Reference reuse** (legacy lines 263-285): if `dicom_series.frame_of_reference_uid` is not None:
  - Query all `DeidSeries` rows where `series__frame_of_reference_uid` matches and `deidentified_frame_of_reference_uid` is not NULL → reuse it (same original FoR UID → same deidentified FoR UID across series)
  - If no existing mapping → generate new `deid_frame_uid = generate_deidentified_frame_of_reference_uid(deid_series_uid)`
- Shift series date: `dicom_series.series_date + timedelta(days=days_shift)` → `YYYYMMDD`
- Create `DeidSeries` row: `series=dicom_series`, `study=deid_study`, `deidentified_series_instance_uid`, `deidentified_series_date`, `deidentified_frame_of_reference_uid`
- Return `(deid_series_uid, deid_series_date, deid_frame_uid)`

---

#### 4. Instance Deidentification (`instance_deidentification.py` → `deidentification/services/instance_deidentification.py`)

**`generate_deidentified_sop_instance_uid(deid_series_uid) -> str`** — *legacy: lines 6-10*
- Format: `<deid_series_uid>.<7-digit-random>.<3-digit-random>` (nested under series UID)

**`deidentify_instance_data(deid_series, dicom_instance) -> deid_sop_uid`** — *legacy: lines 125-158*
- **Django port**: receives `DeidSeries` instance and `client_app.DICOMInstance` instance
- **Lookup**: `DeidInstance.objects.filter(instance=dicom_instance).first()` — if exists, return stored value
- Generate `deid_sop_uid = generate_deidentified_sop_instance_uid(deid_series_uid)`
- **Collision retry** (legacy lines 90-102): recursive retry if `deidentified_sop_instance_uid` already exists — **skip per confirmed decision** (nested random-ID uniqueness is sufficient)
- Create `DeidInstance` row: `instance=dicom_instance`, `series=deid_series`, `deidentified_sop_instance_uid=deid_sop_uid`
- Return `deid_sop_uid`

**Additional instance-level tag replacements** (from tag audit Categories 5, 6 & 7 — applied during Pass 2 per-file processing):
- **Device identifiers** (Category 5) → replace with `"#"`:
  - `DeviceSerialNumber` (0018,1000)
  - `PlateID` (0018,1004)
  - `GeneratorID` (0018,1005)
  - `CassetteID` (0018,1007)
  - `GantryID` (0018,1008)
- **Procedure/Order identifiers** (Category 6, excluding `AccessionNumber` and `StudyID` which are already handled in direct overwrites) → replace with `"#"`:
  - `RequestedProcedureID` (0040,1001)
  - `ScheduledProcedureStepID` (0040,0009)
  - `FillerOrderNumberImagingServiceRequest` (0040,2017)
  - `PlacerOrderNumberImagingServiceRequest` (0040,2016)
- **Free-text fields** (Category 7) → replace with `"#"`:
  - `StudyDescription` (0008,1030)
  - `SeriesDescription` (0008,103E)
  - `ImageComments` (0020,4000)
  - `AdditionalPatientHistory` (0010,21B0)
  - `StudyComments` (0032,4000)
  - `PatientComments` (0010,4000)
  - `RequestedProcedureDescription` (0032,1060)
  - `PerformedProcedureStepDescription` (0040,0254)
  - `ProtocolName` (0018,1030)
  - `AcquisitionProtocolDescription` (0018,9424)

---

#### 5. Date Replacement (`date_replacement.py` → `deidentification/services/date_replacement.py`)

**`date_callback_factory(days_shifted: int) -> callback`** — *legacy: lines 68-149*
- Returns a `pydicom` walk callback that shifts dates in DICOM elements
- **Trigger condition**: element name contains `"date"` (case-insensitive)
- **VR handling**:
  - `DA` (Date, `YYYYMMDD`): `datetime.strptime(value, "%Y%m%d") + timedelta(days=shift)` → reformat `YYYYMMDD`
  - `DT` (DateTime, `YYYYMMDDHHMMSS.FFFFFF`): shift only the date portion (first 8 chars), preserve time portion
- **Multi-valued fields**: handles `pydicom.multival.MultiValue` / lists — shifts each value individually
- **Empty values**: skipped (no error)
- **Parse errors**: logged but not raised (processing continues)

**`deidentify_dates(dcm, days_shifted) -> bool`** — *legacy: lines 151-180*
- **Django port**: receives `days_shifted` directly (from `DeidPatient.date_shift_value`) instead of looking it up via `db_manager`
- Calls `dcm.walk(date_callback_factory(days_shifted))`
- Returns `True` on success

---

#### 6. Name Replacement (`name_replacement.py` → `deidentification/services/name_replacement.py`)

**`name_callback_factory() -> callback`** — *legacy: lines 9-59*
- Returns a `pydicom` walk callback that replaces specific name fields with `"Anonymous"`
- **Target fields** (by DICOM keyword), all replaced with `"Anonymous"` via walk callback:
  - `PatientName` (0010,0010)
  - `ReferringPhysicianName` (0008,0090)
  - `InstitutionName` (0008,0080)
  - `PerformingPhysicianName` (0008,1050)
  - `OperatorsName` (0008,1070)
  - `StationName` (0008,1010)
  - `InstitutionalDepartmentName` (0008,1040)
  - `PhysiciansOfRecord` (0008,1048)
  - `RequestingPhysician` (0032,1032)
  - `ReferringPhysicianIdentificationSequence` (0008,0096)
  - `ConsultingPhysicianName` (0008,009C)
  - `ResponsiblePerson` (0010,2297)
  - `ReviewerName` (300E,0008)
  - `InstitutionCodeSequence` (0008,0082) — *new, from tag audit Category 2*
  - `PhysiciansReadingStudyIdentificationSequence` (0008,1062) — *new, from tag audit Category 2*
  - `OperatorIdentificationSequence` (0008,1072) — *new, from tag audit Category 2*
- **Additional fields handled in this service** (from tag audit Category 4, different replacement values):
  - `OtherPatientIDs` (0010,1000) → `"#"` — *new, from tag audit Category 4*
  - `OtherPatientIDsSequence` (0010,1002) → `"#"` — *new, from tag audit Category 4*
  - `MedicalRecordLocator` (0010,1090) → `"#"` — *new, from tag audit Category 4*
  - `PatientInsurancePlanCodeSequence` (0010,0050) → `"#"` — *new, from tag audit Category 4*
- **Note**: Category 3 address/phone fields (`ReferringPhysicianAddress`, `PatientTelephoneNumbers`) are handled in `address_phone_replacement.py` (Section 7), not here
- **Empty values**: skipped

**`deidentify_names(dcm) -> bool`** — *legacy: lines 61-98*
- Calls `dcm.walk(name_callback_factory())`
- **Post-walk direct override** (legacy lines 83-88): force-set `PatientName` and `ReferringPhysicianName` to `"Anonymous {FieldName}"` if present — this is a **belt-and-suspenders** fix because `walk()` may miss top-level fields in some `pydicom` versions
  - `PatientName` → `"Anonymous PatientName"`
  - `ReferringPhysicianName` → `"Anonymous ReferringPhysicianName"`
- **Port as-is**: pure `pydicom` logic, no DB dependency

---

#### 7. Address & Phone Replacement (`address_phone_replacement.py` → `deidentification/services/address_phone_replacement.py`)

**Three separate walk callbacks** — *legacy: lines 9-49*
- **Person's Address** (tag `0040,1102`) → `"Anonymous Address"`
- **Institution Address** (tag `0008,0081`) → `"Anonymous Address"`
- **Person's Phone Numbers** (tag `0040,1103`) → `"1234567890"`

**`deidentify_address_phone(dcm) -> bool`** — *legacy: lines 51-92*
- Runs `dcm.walk()` calls for each callback
- **Legacy fields** (3 callbacks):
  - Person's Address (tag `0040,1102`) → `"Anonymous Address"`
  - Institution Address (tag `0008,0081`) → `"Anonymous Address"`
  - Person's Phone Numbers (tag `0040,1103`) → `"1234567890"`
- **Additional fields from tag audit Category 3** (integrated into this service, not name_replacement):
  - `ReferringPhysicianAddress` (0008,0092) → `"Anonymous Address"`
  - `PatientTelephoneNumbers` (0010,2154) → `"1234567890"`
- **Port as-is + additions**: pure `pydicom` logic, no DB dependency

---

#### 7a. PHI Pattern Scrubbing (new — from tag audit Category 8)

**Port location**: `deidentification/utils/phi_scrubbing.py` — separate utility in the `deidentification/utils/` folder (already created by user)

**`scrub_phi_patterns(text: str) -> str`** — *new function, no legacy equivalent*
- Applies regex-based scrubbing to free-text DICOM fields to remove embedded PHI patterns
- **Patterns and replacements**:
  - Email addresses: `r'[\w\.-]+@[\w\.-]+\.\w+'` → `EMAIL_REMOVED`
  - URLs: `r'https?://\S+'` → `URL_REMOVED`
  - IP addresses (IPv4): `r'\b(?:\d{1,3}\.){3}\d{1,3}\b'` → `IP_REMOVED`
  - SSN (XXX-XX-XXXX): `r'\b\d{3}-\d{2}-\d{4}\b'` → `SSN_REMOVED`
  - SSN (9-digit): `r'\b\d{9}\b'` → `SSN_REMOVED`
  - Phone numbers: `r'\(?\d{3}\)?[-\.\s]?\d{3}[-\.\s]?\d{4}'` → `PHONE_REMOVED`
- **Applied after** free-text `#` replacement (Category 7) as a safety net — catches PHI in fields not in the replacement list
- Returns `"#"` if input is empty or already `"#"`

---

#### 8. Referenced SOP Instance Replacement (`referenced_sop_instance_replacement.py` → `deidentification/services/referenced_sop_instance_replacement.py`)

**`get_sop_instance_mapping(deid_patient) -> Dict[str, str]`** — *legacy: lines 44-174*
- **Django port**: receives `DeidPatient` instance; builds a combined UID mapping dict
- **Builds mapping in 3 tiers** (using FK traversals through `client_app` models):
  1. **Studies**: all `DeidStudy` rows for this patient → `deid_study.study.study_instance_uid` (via `client_app.DICOMStudy` FK) → `deid_study.deidentified_study_instance_uid`
  2. **Series**: all `DeidSeries` rows under those studies → `deid_series.series.series_instance_uid` (via `client_app.DICOMSeries` FK) → `deid_series.deidentified_series_instance_uid`
  3. **Instances**: all `DeidInstance` rows under those series → `deid_instance.instance.sop_instance_uid` (via `client_app.DICOMInstance` FK) → `deid_instance.deidentified_sop_instance_uid`
- Returns combined `{original_uid: deidentified_uid}` dict covering study, series, and SOP instance UIDs
- **Critical**: all series and instance metadata must be fully extracted into `client_app.DICOMSeries`/`DICOMInstance` before this mapping is built — incomplete extraction means nested referenced UIDs in DICOM sequences won't be deidentified

**`referenced_sop_callback(ds, elem, uid_mapping)`** — *legacy: lines 17-42*
- **Target tags**:
  - `(0008,1155)` — Referenced SOP Instance UID
  - `(300A,0013)` — Referenced RT Plan Sequence Referenced SOP Instance UID
  - `(0020,000E)` — Frame of Reference UID (within sequences)
  - `(0020,000D)` — Study Instance UID (within sequences; note: legacy comment says this replaces all StudyInstanceUID occurrences, but the direct overwrite in `perform_deidentification` later sets the correct value on the top-level tag)
- **If original UID is in mapping**: replace with deidentified value
- **If not in mapping**: replace with `DEFAULT_UID = "1.2.826.0.1.3680043.10.1561.999.99.999"` — **confirmed acceptable**: this occurs when an image references a series that is not part of the exported dataset (e.g., a scannogram referenced by a CT series). The placeholder UID preserves the structural reference without exposing the original UID. Keep as-is.

**`replace_referenced_sop_instances(dcm, uid_mapping) -> bool`** — *legacy: lines 176-207*
- **Django port**: receives `uid_mapping` dict directly (built by caller) instead of looking it up via `db_manager`
- Calls `dcm.walk(lambda ds, elem: referenced_sop_callback(ds, elem, uid_mapping))`

---

#### 9. Referenced Frame of Reference Replacement (`referenced_frame_of_reference_replacement.py` → `deidentification/services/referenced_frame_of_reference_replacement.py`)

**`get_frame_of_reference_mapping(deid_patient) -> Dict[str, str]`** — *legacy: lines 41-154*
- **Django port**: receives `DeidPatient` instance
- Queries all `DeidSeries` rows for this patient where `series__frame_of_reference_uid` (via `client_app.DICOMSeries` FK) is not NULL and `deidentified_frame_of_reference_uid` is not NULL
- Returns `{original_frame_uid: deidentified_frame_uid}` dict

**`referenced_frame_of_reference_callback(ds, elem, uid_mapping)`** — *legacy: lines 20-39*
- **Target tags**:
  - `(0020,0052)` — Frame of Reference UID
  - `(3006,0024)` — Referenced Frame of Reference UID
- **If original UID is in mapping**: replace with deidentified value
- **If not in mapping**: leave unchanged (no default replacement — unlike SOP instance replacement)

**`replace_referenced_frame_of_reference(dcm, uid_mapping) -> bool`** — *legacy: lines 156-185*
- **Django port**: receives `uid_mapping` dict directly
- Calls `dcm.walk(lambda ds, elem: referenced_frame_of_reference_callback(ds, elem, uid_mapping))`

---

#### 10. Private Tag Removal (via `pydicom`)

**Not a separate utility file** — performed inline in `dicom_deidentification_flow.py:293`:
```python
dcm.remove_private_tags()
```
- Uses `pydicom`'s built-in `Dataset.remove_private_tags()` method
- Removes all DICOM elements with odd group numbers (private tags)
- **Placed first** in the pipeline (legacy comment: "reduces further processing time and also because some private tags may have errors")
- **Port as-is**: single `pydicom` API call, no custom logic

---

#### 11. Orchestrator: DICOM Deidentification Flow (`dicom_deidentification_flow.py` → `deidentification/services/dicom_deidentification_flow.py` + `deidentification/tasks.py`)

The legacy orchestrator runs in **two passes** over all DICOM files. The Django port adds a **Pass 0** (metadata extraction) that must complete before deidentification begins.

**Pass 0: Extract DICOM metadata into `client_app.DICOMSeries`/`DICOMInstance`** — *new step, no legacy equivalent (legacy stored metadata in its own encrypted SQLite tables)*
- **Triggered from the deidentification UI** — integrated into the same "Deidentify" button as Pass 1/2 (single user action). The button triggers Pass 0 → Pass 1 → Pass 2 sequentially within the same Celery task. See "UI/Views" section below.
- Enumerates files from `study.folder_path` using `sorted(Path(study.folder_path).rglob('*'))` (alphabetically sorted, same ordering rule as Pass 1).
- For each DICOM file:
  1. Read with `pydicom.dcmread(file_path, stop_before_pixels=True)` (fallback: `force=True`)
  2. Extract: `StudyInstanceUID`, `SeriesInstanceUID`, `SeriesDate` (defaults to `StudyDate` if absent), `Modality`, `FrameOfReferenceUID`, `SOPInstanceUID`
  3. `get_or_create` `client_app.DICOMSeries` (matched by `study` FK + `series_instance_uid`) — stores `series_date`, `modality`, `frame_of_reference_uid`
  4. `get_or_create` `client_app.DICOMInstance` (matched by `series` FK + `sop_instance_uid`)
- **Idempotent**: safe to re-run (uses `get_or_create`, skips existing rows)
- **Critical**: this step MUST complete fully before Pass 1/2 run — incomplete series/instance data means referenced UID mappings will be incomplete and nested UIDs in DICOM sequences won't be deidentified.

**Pass 1: `process_dicom_metadata()`** — *legacy: lines 51-170*
- **Prerequisite**: Pass 0 must have completed for this study — `client_app.DICOMSeries`/`DICOMInstance` rows must exist.
- **File enumeration** (Django port): `sorted(Path(study.folder_path).rglob('*'))` — alphabetically sorted, matching legacy `import_utils.py:83` `valid_files.sort()`. Order is critical because series numbering is sequential (`count + 1` per study).
- For each DICOM file (in sorted order):
  1. Read with `pydicom.dcmread(file_path, stop_before_pixels=True)` (fallback: `force=True`)
  2. Validate required attributes: `PatientID`, `StudyInstanceUID`, `SeriesInstanceUID` (must all be present)
  3. Extract metadata: `patient_id`, `birth_date`, `age`, `study_instance_uid`, `study_date`, `series_instance_uid`, `series_date` (defaults to `study_date` if absent), `frame_of_reference_uid`, `sop_instance_uid`, `modality`
  4. Validate: `patient_id`, `study_instance_uid`, `series_instance_uid`, `sop_instance_uid` must all be non-empty
  5. Look up `client_app.DICOMSeries` by `study + series_instance_uid` and `client_app.DICOMInstance` by `series + sop_instance_uid` (created in Pass 0)
  6. Call `deidentify_patient_data()` → get `(deid_patient_id, deid_dob, days_shift)`
  7. Call `deidentify_study_data()` → get `(deid_study_uid, deid_study_date)`
  8. Call `deidentify_series_data(deid_study, dicom_series, days_shift)` → get `(deid_series_uid, deid_series_date, deid_frame_uid)`
  9. Call `deidentify_instance_data(deid_series, dicom_instance)` → get `deid_sop_uid`
  10. All mappings now stored in DB (Django ORM)
- **Django port**: reads files from `study.folder_path` (already on disk), no zip extraction

**Pass 2: `perform_deidentification()`** — *legacy: lines 172-419*
- **Per-series atomic processing**: files are grouped by `SeriesInstanceUID` and processed as a unit. All files in a series are deidentified in memory first; only if every file in the series succeeds are they written to disk. If any file in a series fails, the **entire series is skipped** — no files from that series are written.
- **Processing flow**:
  1. Group all DICOM files in the study by `SeriesInstanceUID` (preserving sorted order within each series)
  2. For each series:
     a. Initialize an empty list `deidentified_files = []` to collect successfully deidentified datasets
     b. For each file in the series:
        1. Read with `pydicom.dcmread(file_path)` (full read, including pixels; fallback: `force=True`)
        2. Validate required attributes
        3. Extract original IDs: `patient_id`, `study_instance_uid`, `series_instance_uid`, `sop_instance_uid`, `modality`
        4. **Look up deidentified values from DB** (Django ORM: `DeidPatient`/`DeidStudy`/`DeidSeries`/`DeidInstance` via FK/plain-field queries)
        5. **Apply deidentification steps in order**:
           - **(i) Burnt-in pixel scrubbing** (new feature — see "Burnt-in pixel scrubbing" section below) — **MUST run first**, before any tag modification, so Presidio can use DICOM metadata (patient name, ID, DOB) to identify PHI strings burnt into the image:
             - `dcm = scrub_burnt_in_pixels(dcm)` — returns a new `pydicom` dataset with redacted pixel data
             - Uses `DicomImageRedactorEngine.redact(dcm, use_metadata=True, fill="contrast")`
             - Modality-aware: skip for modalities where burnt-in text is uncommon (configurable skip list, default: MR)
           - **(ii)** `dcm.remove_private_tags()` — remove all private tags
           - **(iii)** `replace_referenced_sop_instances(dcm, uid_mapping)` — replace referenced UIDs in sequences
           - **(iv)** `replace_referenced_frame_of_reference(dcm, for_mapping)` — replace referenced FoR UIDs
           - **(v)** `deidentify_dates(dcm, days_shifted)` — shift all date elements
           - **(vi)** `deidentify_names(dcm)` — anonymize name, institution, and patient identifier fields (includes tag audit Categories 1–2, 4)
           - **(vii)** `deidentify_address_phone(dcm)` — anonymize address/phone fields (legacy set + tag audit Category 3)
           - **(viii) Device/procedure/free-text tag replacements** (tag audit Categories 5, 6 & 7 — see Section 4 above):
             - Device identifiers (`DeviceSerialNumber`, `PlateID`, `GeneratorID`, `CassetteID`, `GantryID`) → `"#"`
             - Procedure/Order IDs (`RequestedProcedureID`, `ScheduledProcedureStepID`, `FillerOrderNumberImagingServiceRequest`, `PlacerOrderNumberImagingServiceRequest`) → `"#"`
             - Free-text fields (`StudyDescription`, `SeriesDescription`, `ImageComments`, `AdditionalPatientHistory`, `StudyComments`, `PatientComments`, `RequestedProcedureDescription`, `PerformedProcedureStepDescription`, `ProtocolName`, `AcquisitionProtocolDescription`) → `"#"`
           - **(ix) PHI pattern scrubbing** (tag audit Category 8 — see Section 7a below):
             - Apply `scrub_phi_patterns()` to any remaining free-text fields after `#` replacement (catches PHI embedded in fields not in the replacement list)
           - **(x) Direct core field overwrites**:
             - `dcm.PatientID = deid_patient_id`
             - `dcm.PatientBirthDate = deid_birth_date`
             - `dcm.StudyInstanceUID = deid_study_uid`
             - `dcm.StudyDate = deid_study_date`
             - `dcm.SeriesInstanceUID = deid_series_uid`
             - `dcm.SeriesDate = deid_series_date`
             - `dcm.SOPInstanceUID = deid_sop_uid`
             - `dcm.file_meta.MediaStorageSOPInstanceUID = deid_sop_uid`
             - `dcm.StudyID = "123456789"` (if present)
             - `dcm.AccessionNumber = "123456789101112"`
             - `dcm.FrameOfReferenceUID = deid_frame_uid` (if present and deid_frame_uid exists)
           - **(xi) Transfer syntax safety**: if `dcm.file_meta` has no `TransferSyntaxUID`, set it to `1.2.840.10008.1.2` (Implicit VR Endian — DICOM default)
           - **(xii) Update `BurnedInAnnotation` tag**: set `dcm.BurnedInAnnotation = 'NO'` if present (tag 0028,0301) — reflects that burnt-in text has been removed
        6. Append the deidentified dataset to `deidentified_files` list (kept in memory, **not yet written to disk**)
     c. **Series-level atomic write**: if all files in the series succeeded (no exceptions):
        - Write each file in `deidentified_files` to disk: `dcm.save_as(output_path, enforce_file_format=True)` to `output_dir/<deid_patient>/<deid_study>/<deid_sop>-<modality>.dcm`
        - Record the series as completed in the manifest checkpoint
     d. **Series-level fail-fast**: if ANY file in the series fails at ANY step:
        - **Discard all deidentified datasets** for this series (nothing is written to disk)
        - Log the error with file path, series UID, and step that failed
        - Increment `failed_count` and `failed_series_count` on the `DeidentificationJob`
        - Mark the series as failed in the manifest (so it is not retried on resume unless explicitly re-triggered)
        - Move to the next series
- **Critical safety guarantee**: a series is either fully deidentified and written to disk, or entirely skipped — no partially-deidentified series or files are ever written. This prevents incomplete deidentification from reaching the output directory.

**`deidentify_dicom_files()` (entry point)** — *legacy: lines 421-636*
- Calls Pass 0 → Pass 1 → Pass 2 → gathers results → stores `DeidentificationJob` row
- **Django port**: becomes a Celery task (`deidentification/tasks.py`) with **resumption support** matching the `client_app` pattern (see "Celery task resumption" section below); `deidentification_history` → `DeidentificationJob` model; no temp file cleanup (files are read in-place from `folder_path`)
- **DICOM files written using `pydicom`**: `dcm.save_as(output_path, enforce_file_format=True)` ensures valid DICOM output with proper file meta information
- **Bulk operation support**: the Celery task accepts a list of study IDs (multiple studies/patients), processing them sequentially with per-study manifest checkpointing for resumption
- **Ordering rule**: DICOM data is deidentified **before** patient (clinical) data deidentification — the UI enforces this by disabling the "Deidentify Clinical Data" button until DICOM deidentification is complete for that patient

---

#### 12. DICOM Tag Coverage Audit: Legacy `dicomutils/` vs. `task3_deidentify_series.py`

A comparison was performed between the tag coverage in the legacy `chavi-deidentification-app/dicomutils/` code and a newer `task3_deidentify_series.py` implementation. The following categories list tags that are **in the newer code but NOT in the legacy code**, plus tags **in the legacy code but MISSING from the newer code**. Each category needs a decision on replacement strategy before implementation.

**Category 1: Additional Name Fields** *(not in legacy; pasted code replaces with `#`)*

| # | DICOM keyword | Tag ID | Legacy | Pasted code |
|---|---|---|---|---|
| 1 | `PerformingPhysicianName` | (0008,1050) | Replace with `Anonymous` | `#` |
| 2 | `OperatorsName` | (0008,1070) | Replace with `Anonymous` | `#` |
| 3 | `StationName` | (0008,1010) | Replace with `Anonymous` | `#` |
| 4 | `InstitutionalDepartmentName` | (0008,1040) | Replace with `Anonymous` | `#` |
| 5 | `PhysiciansOfRecord` | (0008,1048) | Replace with `Anonymous` | `#` |
| 6 | `RequestingPhysician` | (0032,1032) | Replace with `Anonymous` | `#` |
| 7 | `ReferringPhysicianIdentificationSequence` | (0008,0096) | Replace with `Anonymous` | `#` |
| 8 | `ConsultingPhysicianName` | (0008,009C) | Replace with `Anonymous` | `#` |
| 9 | `ResponsiblePerson` | (0010,2297) | Replace with `Anonymous` | `#` |
| 10 | `ReviewerName` | (300E,0008) | Replace with `Anonymous` | `#` |

> Legacy handles `PatientName` and `ReferringPhysicianName` with `"Anonymous"` / `"Anonymous <FieldName>"`. Pasted code replaces all name fields with `#`. The code for this deidentification needs to be in the name_replacement.

**Category 2: Institution Information** *(partially in legacy; pasted code replaces with `#`)*

| # | DICOM keyword | Tag ID | Legacy | Pasted code |
|---|---|---|---|---|
| 1 | `InstitutionName` | (0008,0080) |  Replace with `Anonymous`| `#` |
| 2 | `InstitutionAddress` | (0008,0081) | `"Anonymous Address"` | `#` |
| 3 | `InstitutionCodeSequence` | (0008,0082) |  Replace with `Anonymous` | `#` |
| 4 | `PhysiciansReadingStudyIdentificationSequence` | (0008,1062) |  Replace with `Anonymous` | `#` |
| 5 | `OperatorIdentificationSequence` | (0008,1072) |  Replace with `Anonymous` | `#` |

**Category 3: Additional Address/Phone Fields** *(partially in legacy; pasted code replaces with `#`)* Handle in name replacement. 

| # | DICOM keyword | Tag ID | Legacy | Pasted code |
|---|---|---|---|---|
| 1 | `ReferringPhysicianAddress` | (0008,0092) |`"Anonymous Address"` | `#` |
| 2 | `PersonAddress` | (0040,1102) | `"Anonymous Address"` | `#` |
| 3 | `TelephoneNumbers` | (0040,1103) | `"1234567890"` | `#` |
| 4 | `PatientTelephoneNumbers` | (0010,2154) | `"1234567890"` | `#` |

**Category 4: Additional Patient Identifiers** *(not in legacy; pasted code replaces with `#`)* Handle in name replacement.

| # | DICOM keyword | Tag ID | Legacy | Pasted code |
|---|---|---|---|---|
| 1 | `OtherPatientIDs` | (0010,1000) | Replace with `#` | `#` |
| 2 | `OtherPatientIDsSequence` | (0010,1002) | Replace with `#` | `#` |
| 3 | `MedicalRecordLocator` | (0010,1090) | Replace with `#` | `#` |
| 4 | `PatientInsurancePlanCodeSequence` | (0010,0050) | Replace with `#` | `#` |

**Category 5: Device Identifiers** *(not in legacy; pasted code replaces with `#`)* keep this logic in instance deidentification logic

| # | DICOM keyword | Tag ID | Legacy | Pasted code |
|---|---|---|---|---|
| 1 | `DeviceSerialNumber` | (0018,1000) | Replace with `#` | `#` |
| 2 | `PlateID` | (0018,1004) | Replace with `#` | `#` |
| 3 | `GeneratorID` | (0018,1005) | Replace with `#` | `#` |
| 4 | `CassetteID` | (0018,1007) | Replace with `#` | `#` |
| 5 | `GantryID` | (0018,1008) | Replace with `#` | `#` |

**Category 6: Procedure/Order Identifiers** *(partially in legacy; pasted code replaces with `#`)* Handle in instance deidentification logic

| # | DICOM keyword | Tag ID | Legacy | Pasted code |
|---|---|---|---|---|
| 1 | `AccessionNumber` | (0008,0050) | `"123456789101112"` | `#` |
| 2 | `StudyID` | (0020,0010) | `"123456789"` | `#` |
| 3 | `RequestedProcedureID` | (0040,1001) | Replace with `#` | `#` |
| 4 | `ScheduledProcedureStepID` | (0040,0009) |Replace with `#` | `#` |
| 5 | `FillerOrderNumberImagingServiceRequest` | (0040,2017) | Replace with `#` | `#` |
| 6 | `PlacerOrderNumberImagingServiceRequest` | (0040,2016) | Replace with `#` | `#` |

**Category 7: Free-Text Fields** *(not in legacy; pasted code replaces with `#`)* Add in instance deidentification logic.

| # | DICOM keyword | Tag ID | Legacy | Pasted code |
|---|---|---|---|---|
| 1 | `StudyDescription` | (0008,1030) | Replace with `#` | `#` |
| 2 | `SeriesDescription` | (0008,103E) | Replace with `#` | `#` |
| 3 | `ImageComments` | (0020,4000) | Replace with `#` | `#` |
| 4 | `AdditionalPatientHistory` | (0010,21B0) | Replace with `#` | `#` |
| 5 | `StudyComments` | (0032,4000) | Replace with `#` | `#` |
| 6 | `PatientComments` | (0010,4000) | Replace with `#` | `#` |
| 7 | `RequestedProcedureDescription` | (0032,1060) | Replace with `#` | `#` |
| 8 | `PerformedProcedureStepDescription` | (0040,0254) | Replace with `#` | `#` |
| 9 | `ProtocolName` | (0018,1030) | Replace with `#` | `#` |
| 10 | `AcquisitionProtocolDescription` | (0018,9424) | Replace with `#` | `#` |

**Category 8: PHI Pattern Scrubbing** *(not in legacy; pasted code applies regex on free-text fields)* Implement these as new functions

| # | Pattern | Regex | Replacement |
|---|---|---|---|
| 1 | Email addresses | `[\w\.-]+@[\w\.-]+\.\w+` | `EMAIL_REMOVED` |
| 2 | URLs | `https?://\S+` | `URL_REMOVED` |
| 3 | IP addresses (IPv4) | `\b(?:\d{1,3}\.){3}\d{1,3}\b` | `IP_REMOVED` |
| 4 | SSN (XXX-XX-XXXX) | `\b\d{3}-\d{2}-\d{4}\b` | `SSN_REMOVED` |
| 5 | SSN (9-digit) | `\b\d{9}\b` | `SSN_REMOVED` |
| 6 | Phone numbers | `\(?\d{3}\)?[-\.\s]?\d{3}[-\.\s]?\d{4}` | `PHONE_REMOVED` |

**Category 9: Tags in Legacy but MISSING from Pasted Code** *(CRITICAL — nested referenced UID replacement)* Keep these as it is

| # | DICOM keyword | Tag ID | Legacy behavior | Pasted code |
|---|---|---|---|---|
| 1 | Referenced SOP Instance UID (in sequences) | (0008,1155) | Replaced with mapped deid UID or `DEFAULT_UID` | **Not handled** |
| 2 | Referenced RT Plan SOP Instance UID (in sequences) | (300A,0013) | Replaced with mapped deid UID or `DEFAULT_UID` | **Not handled** |
| 3 | Frame of Reference UID (in sequences) | (0020,000E) | Replaced with mapped deid UID | **Not handled** |
| 4 | Study Instance UID (in sequences) | (0020,000D) | Replaced with mapped deid UID | **Not handled** |
| 5 | Frame of Reference UID (top-level + sequences) | (0020,0052) | Replaced with mapped deid UID | **Not handled** |
| 6 | Referenced Frame of Reference UID (in sequences) | (3006,0024) | Replaced with mapped deid UID | **Not handled** |



**Replacement Value Differences (legacy vs. pasted code)**

| Field type | Legacy value | Pasted code value |
|---|---|---|
| Name fields | `"Anonymous"` / `"Anonymous <FieldName>"` | `#` |
| Address fields | `"Anonymous Address"` | `#` |
| Phone fields | `"1234567890"` | `#` |
| `StudyID` | `"123456789"` | `#` |
| `AccessionNumber` | `"123456789101112"` | `#` |
| Dates | Shifted ±100 days from DOB | Random date 2000–2020 |
| `PatientBirthDate` | Shifted from DOB | Random date |

> **Decisions applied** (see consolidated logic in sections 4, 6, 7, 7a, and Pass 2 above):
> - **Categories 1–2**: handled in `name_replacement.py` (Section 6). Name/institution fields → `"Anonymous"`.
> - **Category 3**: handled in `address_phone_replacement.py` (Section 7). Address fields → `"Anonymous Address"`, phone fields → `"1234567890"`.
> - **Category 4**: handled in `name_replacement.py` (Section 6). Patient identifier fields → `"#"`.
> - **Categories 5–7**: handled in instance deidentification logic (Section 4 + Pass 2 step g). Device IDs, procedure/order IDs, and free-text fields → `"#"`.
> - **Category 8**: new `phi_scrubbing.py` utility (Section 7a, in `deidentification/utils/`). Applied as Pass 2 step h.
> - **Category 9**: already in plan sections 8 & 9 (referenced SOP/FoR replacement). Keep as-is. DEFAULT_UID for unmapped UIDs confirmed acceptable (scannogram references).
> - **Dates**: legacy date-shifting approach (DOB-based ±100 days) — confirmed design, not random dates.

---

#### 13. Clinical Data Deidentification (`clinical_data_deidentification.py` → `deidentification/services/clinical_data_deidentification.py`)

**JSON walker functions** (port as-is — pure Python, no DB/pydicom dependency):
- `find_patient_id_keys(data) -> List[str]`: recursively finds all keys containing `"patient_id"` or exactly `"patient"` → returns dot-notation paths
- `find_study_uid_keys(data) -> List[str]`: recursively finds all keys containing `"study_instance_uid"` → returns dot-notation paths
- `find_date_fields(data) -> List[str]`: recursively finds all keys containing `"date"` OR values matching `YYYY-MM-DD` format → returns dot-notation paths
- `get_nested_value(data, path) -> Any`: traverses dict/list using dot-notation path (handles `[i]` index notation)
- `set_nested_value(data, path, value)`: sets value at dot-notation path (creates intermediate dicts/lists as needed)
- `shift_date(date_str, shift_days) -> str`: shifts `YYYY-MM-DD` date by N days, returns `YYYY-MM-DD`; passes through `null`/empty unchanged
- `is_date_format(value) -> bool`: checks if string matches `YYYY-MM-DD`

**`deidentify_clinical_data(patient) -> dict`** — *legacy: lines 169-401, rewritten for Django*
- **Django port**: receives a `client_app.Patient` instance; builds the JSON dict in-memory from Django querysets (reusing `client_app.serializers` / `patient_data_export.py` structure) instead of reading from an uploaded JSON file
- **Step 1 — Patient ID mapping**: look up `DeidPatient.objects.get(patient=patient)` → get `deidentified_patient_id`. If not found, error (patient must be DICOM-deidentified first).
- **Step 2 — Study UID mapping**: for each `DeidStudy` under this patient → build `{original_study_uid: deid_study_uid}` map (original via `study.study_instance_uid` FK)
- **Step 3 — Replace patient IDs**: walk JSON, for every key matching `patient_id`/`patient`, replace value with `deidentified_patient_id`
- **Step 4 — Replace study UIDs**: walk JSON, for every key matching `study_instance_uid` (string or list of strings), replace with deidentified UID from map. If any study UID is not found in map → error, skip file (legacy behavior).
- **Step 5 — Shift dates**: get `days_shift = DeidPatient.date_shift_value`; walk JSON, for every date field (key contains `"date"` or value matches `YYYY-MM-DD`), apply `shift_date(value, days_shift)`
- Return deidentified dict (caller wraps in zip for download)

### UI/Views (dedicated frontend, NOT Django admin)
`chavi_client` already has an established pattern for custom (non-admin) workflows in the `data_import` app: Django class-based views (`django.views.generic.View`/`ListView`) + server-rendered templates extending `templates/base.html` (TailwindCSS, FontAwesome, `LoginRequiredMixin`, Django `messages`). The new `deidentification` UI follows this same convention — **no Django admin actions, no SPA**.

**Single combined per-patient dashboard** (confirmed over a separate job-list page):
- `deidentification/views.py`: a patient-search/list landing page (analogous to `data_import`'s `ImportSessionListView`) linking into a `PatientDeidentificationDetailView` — one page per patient listing all `client_app.DICOMStudy` records with an inline "Deidentify" button/status badge (not-yet-processed / processing / done + download link) per study, plus a "Deidentify Clinical Data" button returning the JSON zip as a direct download.
- **Single "Deidentify" button per study**: triggers a single Celery task that runs Pass 0 (metadata extraction) → Pass 1 (process metadata) → Pass 2 (perform deidentification) sequentially. The user does not need to separately trigger metadata extraction — it is integrated into the deidentification flow.
- **Bulk deidentification**: a "Deidentify All" button on the patient detail page (or patient list page) dispatches a single Celery task processing all studies for a patient (or multiple selected patients) in one job, with per-study manifest checkpointing for resumption.
- **DICOM before clinical data**: the "Deidentify Clinical Data" button is disabled until all DICOM studies for that patient have been deidentified. This enforces the rule that DICOM data is deidentified before patient data deidentification.
- **Post-deidentification download**: once deidentification is complete, a "Download" button appears per study (and per patient for bulk) that packages the deidentified DICOM files into a ZIP for download — matching the legacy app's `download_deidentified_files` / `create_zip_from_directory` behavior. The ZIP is created on-demand from the output directory `deidentification/output/<deid_patient>/<deid_study>/`.
- `templates/deidentification/`: `patient_list.html`, `patient_detail.html` extending `base.html`, matching `data_import`'s Tailwind/FontAwesome styling.
- Nav wiring: add a "Deidentification" entry to `templates/base.html`'s dropdown nav (desktop dropdown ~line 55-66, mobile section ~line 212-218), following the same markup as the existing "Data Import"/"DICOM Upload" links.
- Per-study deidentify button triggers a POST view that dispatches the Celery task; status badge updates via simple periodic refresh/polling against a lightweight status endpoint (same pattern as `client_app`'s `task_progress` view).

### Core deidentification logic (invoked from views, not admin actions)
- **`deidentify_dicom_study(study: DICOMStudy)`** (service function, called from a view + Celery task): reads DICOM files straight from `study.folder_path`, runs Pass 0 (metadata extraction) → Pass 1 (process metadata) → Pass 2 (per-file pipeline: burnt-in pixel scrubbing (Presidio, using metadata for detection) → private-tag removal → referenced UID/FoR replacement → date shift → name/institution/address-phone/patient-ID anonymization → device/procedure/free-text `#` replacement → PHI pattern scrubbing → core UID/date overwrite), writes output to `deidentification/output/<deid_patient>/<deid_study>/<deid_sop>-<modality>.dcm` using `pydicom.dcm.save_as(path, enforce_file_format=True)` to ensure valid DICOM files, updates `DeidentificationJob`.
- **`deidentify_dicom_studies_bulk(study_ids: List[int])`** (service function for bulk operation): iterates over multiple study IDs, calling `deidentify_dicom_study` per study with manifest checkpointing per study for resumption support.
- **`deidentify_clinical_data(patient: Patient)`** (service function, called synchronously from a view): builds the same nested structure as `patient_data_export.export_patient_data` directly from querysets (reusing `client_app.serializers`), then walks the resulting dict applying the ported `clinical_data_deidentification.py` logic (patient-ID swap, study-UID swap, date shift) using `DeidPatient`/`DeidStudy` lookups, returned as a downloadable JSON zip via `HttpResponse`.

## Integration points with existing chavi_client apps
- **`client_app.services.bulk_dicom_data_import` / `dicom_data_import_per_patient`**: establish the on-disk convention (`DICOMStudy.folder_path`, sanitized patient/study/SOP naming) that the new DICOM deidentification action reads from directly.
- **`client_app.services.patient_data_export`** / **`client_app.serializers`**: reused as the in-memory data-shaping layer for the clinical deidentify action — no separate export step needed first.
- **`client_app.models.Patient` / `DICOMStudy`**: not modified directly; the deidentification app's models reference original IDs independently (mapping table pattern), preserving `client_app` as the canonical clinical record store.
- **`client_app.models.DICOMSeries` / `DICOMInstance`** (new): added to `client_app` to store series/instance-level DICOM metadata extracted by the deidentification app's Pass 0 step. Not populated by existing import pipelines — populated on-demand from the deidentification UI.
- **Celery**: reuse existing `chavi_client` Celery config (`celery.py`, `django_celery_results`) for the DICOM deidentification task queue; no new infra needed.
- **`client_app.services.task_checkpoint`**: reuse the existing JSONL manifest checkpoint service (`manifest_path_for_task`, `write_manifest_entry`, `read_manifest`, `cleanup_manifest`) for per-study resumption in the deidentification Celery task.
- **`client_app.tasks._auto_continue_task` / `_create_task_run` / `_update_task_run` / `_complete_task_run` / `_fail_task_run`**: reuse the existing task lifecycle helpers and `TaskRun` model for progress tracking, soft-time-limit auto-continue, and resume support. The deidentification task follows the same pattern as `task_export_dicom_data_parallel`: manifest-based skip of completed items, `SoftTimeLimitExceeded` → `_auto_continue_task` redispatch, `TaskRun` progress updates via `ProgressRecorder`.

## Legacy mapping import (UI feature, not a management command)
Instead of a Django management command, the legacy mapping import is exposed as a **UI feature** in the deidentification frontend. A dedicated view/template allows an admin user to upload the legacy `app.db` and `encryption.key` files through the browser, triggering a Celery task that seeds the `DeidPatient`/`DeidStudy`/`DeidSeries`/`DeidInstance` mapping tables.

**UI flow** (`deidentification/views.py` + `templates/deidentification/legacy_import.html`):
1. Admin user navigates to the "Import Legacy Mappings" page (linked from the deidentification nav section).
2. Upload form: two file inputs — `app.db` (SQLite) and `encryption.key` (AES key file). Both required.
3. On submit, files are saved to a temporary location, and a Celery task (`import_legacy_mappings_task`) is dispatched.
4. The task processes the legacy DB and reports progress via `DeidentificationJob` (or a dedicated `LegacyImportJob` model with status/counts).
5. On completion, the UI shows a summary: created/skipped/unmatched counts, plus a **table of all unmatched legacy patients/studies** for manual review. Each unmatched row shows the decrypted legacy patient ID, study UID, and available metadata (DOB, study date, etc.).
6. **Manual reconciliation**: for each unmatched legacy patient, the admin user can:
   - **Create a new `client_app.Patient` entry** directly from the UI (pre-filled with decrypted legacy data: patient_id, date_of_birth) — this creates the `client_app` record that the legacy mapping can then link to.
   - **Create a new `client_app.DICOMStudy` entry** if the patient exists but the study doesn't (pre-filled with decrypted study UID, study date).
   - **Skip** the unmatched row — it will be treated as a new patient on the next deidentification run (fresh mapping generated, no legacy continuity).
   After creating the missing `client_app` records, the admin can re-run the legacy import to link the previously unmatched rows.

**Celery task logic** (`deidentification/tasks.py` → `import_legacy_mappings_task`):
1. Open the uploaded legacy SQLite DB read-only (raw `sqlite3` module, not Django ORM — different DB).
2. Replicate the legacy AES-CBC decryption (deterministic IV = SHA-256(value)[:16]) to decrypt every `encrypted_*` column (patient_id, date_of_birth, date_shift_value, study_uid, study_date, series_uid, series_date, frame_of_reference_uid, sop_instance_uid) to plaintext.
3. **Match decrypted plaintext `patient_id` against `client_app.Patient.pk`** and decrypted `study_uid` against `client_app.DICOMStudy.pk` — collect any legacy row whose original ID has no corresponding `client_app` record into an **unmatched list** (data drift between the two systems). These are reported in the UI summary for manual reconciliation. The admin can create new `client_app.Patient`/`DICOMStudy` entries from the UI for each unmatched row, then re-run the import to link them.
4. **Back-fill `Patient.date_of_birth` from legacy DOB** (confirmed acceptable): decrypt `encrypted_date_of_birth`; if `client_app.Patient.date_of_birth` is NULL, set it to the decrypted value and `patient.save(update_fields=['date_of_birth'])` (within the same transaction). If already set, do not overwrite — log a warning if the values differ. This preserves the DOB used for the original date shift calculation.
5. For matched rows, `get_or_create` `DeidPatient`/`DeidStudy` (OneToOne to the matched `client_app` record) and `DeidSeries`/`DeidInstance` (OneToOne to `client_app.DICOMSeries`/`DICOMInstance` if they exist, or created as part of the import if the legacy DB has series/instance data that hasn't been extracted yet + newly-encrypted deidentified value, using `django-encrypted-model-fields` on save).
6. Wrap in a single transaction; report counts of created/skipped/unmatched rows back to the UI.
7. Idempotent: safe to re-run (matches on `client_app` FK / plain original UID, not on encrypted ciphertext).
8. Clean up uploaded temporary files after processing.

**Dev-only aid (not production)**: a throwaway script may extract `chavi-deidentification-app/deidentified_dicom/Archive.zip` to spot-check that re-running `deidentify_dicom_studies` after import reproduces byte-identical UIDs/dates to the legacy output — useful for validating the import logic in dev, but not part of the production runbook.

## Celery task resumption (matching `client_app` pattern)
The deidentification Celery task (`deidentification/tasks.py`) must support resumption for long-running jobs, following the established `client_app` pattern:

- **`TaskRun` model**: reuse `client_app.TaskRun` (add a new `TaskType.DEIDENTIFICATION` choice) for progress tracking, status, resume count, and manifest path storage.
- **Manifest checkpointing**: use `client_app.services.task_checkpoint` (`manifest_path_for_task`, `write_manifest_entry`, `read_manifest`, `cleanup_manifest`) to track per-series completion within each study. Each completed series (series UID) is written to the JSONL manifest; on resume, completed series are skipped and failed series are not retried unless explicitly re-triggered. This aligns with the per-series atomic write policy in Pass 2.
- **Soft time limit auto-continue**: catch `SoftTimeLimitExceeded` and call `_auto_continue_task(task_run, task_func, self.request.args, self.request.kwargs)` to redispatch with a new Celery task ID while reusing the same `TaskRun` row (updated `task_id`, incremented `resume_count`). Max 20 auto-continue attempts (`MAX_AUTO_CONTINUE_ATTEMPTS`).
- **Progress reporting**: use `celery_progress.ProgressRecorder` (same as existing tasks) for real-time progress percentages.
- **Stable task_id**: pass a stable `task_id` parameter (persisted across redispatches) so the manifest file path is consistent across resume attempts — same pattern as `task_export_dicom_data`.
- **Notifications**: reuse `client_app.Notification` model for task status notifications (started, resumed, completed, failed) — same pattern as existing tasks.

## Post-deidentification download
Deidentified files are made available for download as ZIP archives, matching the legacy app's behavior:
- **Per-study download**: a view (`deidentification/views.py`) that zips the output directory `deidentification/output/<deid_patient>/<deid_study>/` into a ZIP file and returns it as an `HttpResponse` with `Content-Type: application/zip`.
- **Per-patient download** (bulk): zips all deidentified study directories for a patient into a single ZIP, organized as `<deid_patient>/<deid_study>/<deid_sop>-<modality>.dcm`.
- **ZIP creation**: use `zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)` with `allowZip64=True` for large datasets — same pattern as `client_app`'s `task_export_dicom_data`.
- **Download trigger**: "Download" button appears on the patient detail page per study (and per patient for bulk) once `DeidentificationJob.status == SUCCESS`.
- **Output path stored on `DeidentificationJob`**: the `output_path` field records where deidentified files for this job are located, enabling the download view to locate files without re-scanning.
- **Output location**: deidentified files live inside Django's `media/` directory at `media/deidentification/output/<deid_patient>/<deid_study>/<deid_sop>-<modality>.dcm`. Subject to `.gitignore` and backup policy. The `output_path` on `DeidentificationJob` stores the relative path from `MEDIA_ROOT`.

## Burnt-in pixel scrubbing (new feature — using Microsoft Presidio)
Removes burnt-in PHI text from DICOM pixel data using Microsoft Presidio's `DicomImageRedactorEngine` — not present in the legacy `dicomutils/` code.

**Why Presidio**: purpose-built for DICOM, works directly on `pydicom` datasets (no format conversion, no image quality loss), uses DICOM metadata to build a custom recognizer per image (reads patient name, ID, DOB from tags and searches for those specific strings in the image — significantly higher recall than generic OCR alone). Microsoft-backed, actively maintained, pip-installable.

**Port location**: `deidentification/utils/burnt_in_pixel_scrubbing.py`

**`scrub_burnt_in_pixels(dcm, modality=None) -> pydicom.Dataset`** — *new function*
- **Input**: a `pydicom` Dataset (loaded with full pixel data via `dcmread`, not `stop_before_pixels`)
- **Output**: a new `pydicom` Dataset with redacted pixel data (original dataset is not modified)
- **Implementation**:
  ```python
  from presidio_image_redactor import DicomImageRedactorEngine

  _engine = None  # singleton, lazily initialized

  def _get_engine():
      global _engine
      if _engine is None:
          _engine = DicomImageRedactorEngine()
      return _engine

  SKIP_MODALITIES = {'MR', 'RTPLAN', 'RTDOSE', 'RTSTRUCT', 'REG'}  # modalities with no pixel data or no burnt-in text

  def scrub_burnt_in_pixels(dcm, modality=None):
      if modality and modality in SKIP_MODALITIES:
          return dcm
      engine = _get_engine()
      redacted = engine.redact(dcm, use_metadata=True, fill="contrast")
      return redacted
  ```
- **`use_metadata=True`** (default): Presidio reads DICOM tags (PatientName, PatientID, PatientBirthDate, etc.) and builds a custom NER recognizer to find those specific strings in the image. This is why pixel scrubbing **must run before** tag-level deidentification.
- **`fill="contrast"`** (confirmed): fills redacted regions with a contrast color (black on most images). Confirmed acceptable per user decision.
- **Bounding box output**: optionally use `engine.redact_and_return_bbox(dcm)` to get bounding box coordinates for audit logging — can be stored on `DeidentificationJob` or a separate `PixelRedactionLog` model for compliance.
- **Modality awareness**: skip modalities that have no pixel data or no burnt-in text. Default skip list: `MR`, `RTPLAN`, `RTDOSE`, `RTSTRUCT`, `REG`. All other modalities (including `XA`, `RF`, `US`, `CT`, `CR`, `DX`, `MG`) are always scrubbed. Configurable via Django setting `DEID_SKIP_PIXEL_SCRUB_MODALITIES`.
- **Performance**: OCR is CPU-intensive. Based on Tesseract v5 benchmarks (240ms–350ms per 300 DPI document) plus spaCy NER and redaction overhead, expect **~5–10s per DICOM image** (conservative). For a 100-instance series: ~700–1200s (12–20 min). For a 500-instance series: ~3500–6000s (58–100 min). Large series are split into **sub-batches** for checkpointing — default batch size **50 files** (≈500s per batch at 10s/image, well within the 3600s soft time limit). Manifest checkpoint is written after each sub-batch completes. On resume, completed sub-batches are skipped. The series-level atomic write policy still applies: if any file in a sub-batch fails, the entire series is discarded (including already-written sub-batches — those files are deleted from the output directory).
- **Error handling (series-level fail-fast)**: if Presidio fails on a specific file (e.g., unsupported transfer syntax, corrupted pixel data), the **entire series is skipped** — all deidentified datasets for that series are discarded and nothing is written to disk. Log the error with file path, series UID, and step, increment `failed_count` and `failed_series_count` on `DeidentificationJob`, and move to the next series. This is consistent with the overall Pass 2 series-level atomic write policy.
- **Prerequisite**: `pydicom.dcmread(file_path)` must read with full pixel data (not `stop_before_pixels=True`). Pass 2 step 1 already does this. Pass 0 and Pass 1 use `stop_before_pixels=True` for speed.
- **System dependency**: requires Tesseract OCR installed on the system (`tesseract-ocr` package on Debian/Ubuntu). Presidio was tested with Tesseract v5.2.0+.
- **spaCy model**: requires `python -m spacy download en_core_web_lg` for the NER component that classifies detected text as PHI vs. non-PHI.

**Audit logging** (enabled by default):
- Store bounding box coordinates per file in a `PixelRedactionLog` model: `job` (FK to `DeidentificationJob`), `file_path`, `bboxes` (JSONField), `created_at`.
- Enables post-hoc verification that pixel scrubbing was performed and what regions were redacted.
- Can be disabled via Django setting `DEID_LOG_PIXEL_REDACTION_BBOXES = False` (default `True`, disable if storage becomes a concern).

## Dependencies to add to `chavi_client/requirements.txt`
- `pydicom` — already present.
- `pycryptodome` — needed only transiently inside the legacy import Celery task to decrypt the legacy DB (can also implement AES-CBC via `cryptography`, already present, to avoid a new dependency).
- `presidio-image-redactor` — for burnt-in pixel scrubbing (installs `presidio-analyzer`, `presidio-anonymizer`, `pytesseract`, `spacy`, `Pillow` as transitive dependencies).
- `spacy` model `en_core_web_lg` — install via `python -m spacy download en_core_web_lg` (post-install step, not pip).
- System package: `tesseract-ocr` (Debian/Ubuntu) — required by `pytesseract`, install via `apt-get install tesseract-ocr`.
- `Pillow` — already present for image handling.
- No PyQt6 dependency needed (headless Django service).

## Dockerfile changes (`chavi_client/Dockerfile`)
Two changes needed to support Presidio's `DicomImageRedactorEngine`:

**1. Builder stage** — add spaCy model download after pip install (line 16-17):
```dockerfile
# Current:
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# Updated:
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt && \
    python -m spacy download en_core_web_lg
```
Downloads the ~560MB `en_core_web_lg` NER model used by Presidio to classify detected text as PHI. Installed in builder stage for Docker layer caching.

**2. Production stage** — add `tesseract-ocr` system package before `USER appuser` (before line 27):
```dockerfile
# Add before "COPY --from=builder /install /usr/local":
RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*
```
Installs Tesseract OCR engine required by `pytesseract`. Runs as root before the `USER appuser` switch. `--no-install-recommends` keeps image small; `rm -rf /var/lib/apt/lists/*` cleans apt cache.

## Work breakdown (implementation order)
1. Add `DICOMSeries` and `DICOMInstance` models to `client_app` + create migrations.
2. Scaffold `deidentification` app (models, migrations, views, urls, apps.py) and register in settings + root URLconf.
3. Build the DICOM metadata extraction service (Pass 0) + UI button — scans `study.folder_path`, populates `client_app.DICOMSeries`/`DICOMInstance`.
4. Port DICOM deidentification services (patient/study/series/instance + date/name/address/referenced-UID replacement + device/procedure/free-text tag replacement + PHI pattern scrubbing + burnt-in pixel scrubbing) as pure functions in `deidentification/utils/`, with unit tests against `test_data/` sample DICOMs.
5. Build `deidentify_dicom_study` + `deidentify_dicom_studies_bulk` service + Celery task wiring (Pass 0 → Pass 1 → Pass 2), reading from `folder_path`, writing to output storage using `pydicom.save_as(enforce_file_format=True)`; job status tracked via `TaskRun` + `DeidentificationJob`; manifest checkpointing + auto-continue for resumption.
6. Port clinical JSON deidentification helpers; build the `deidentify_clinical_data` service reusing `client_app.serializers`/`patient_data_export` structure in-memory.
7. Build the frontend: `patient_list.html`/`patient_detail.html` views + templates, nav wiring in `base.html`, single "Deidentify" button per study (Pass 0+1+2 in one action), bulk "Deidentify All" button, "Download" button for completed jobs, "Deidentify Clinical Data" button (disabled until DICOM deidentification is complete).
8. Build the legacy mapping import UI (upload form + Celery task) and test against `data/app.db`, including the unmatched-row reporting (legacy patient/study IDs with no corresponding `client_app` record).
9. Regression test: run the legacy import, then trigger extraction + deidentification from the new UI on already-imported patients and confirm existing mappings are reused (identical deidentified IDs/date-shifts, no duplicates) rather than freshly generated.
10. (Dev-only, optional) Spot-check reused IDs against `chavi-deidentification-app/deidentified_dicom/Archive.zip` contents for a few imported patients to validate import correctness end-to-end.

## Resolved decisions
- **Output file location**: inside `media/deidentification/output/` — subject to `.gitignore` and backup policy. `DeidentificationJob.output_path` stores the relative path from `MEDIA_ROOT`.
- **Legacy unmatched rows**: all unmatched legacy patients/studies are shown in the UI summary table. Admin users can create new `client_app.Patient`/`DICOMStudy` entries from the UI for each unmatched row (pre-filled with decrypted legacy data), then re-run the import to link them. Alternatively, skip unmatched rows — they will be treated as new patients on the next deidentification run.
- **Cross-app write (`Patient.date_of_birth` back-fill)**: confirmed acceptable. The deidentification service and legacy import task both modify `client_app.Patient.date_of_birth` (back-fill when NULL only).
- **Presidio `fill="contrast"`**: confirmed acceptable (black boxes).
- **Presidio modality skip list**: default skip = `MR`, `RTPLAN`, `RTDOSE`, `RTSTRUCT`, `REG` (no pixel data or no burnt-in text). All other modalities (`CT`, `XA`, `RF`, `US`, `CR`, `DX`, `MG`, etc.) are always scrubbed. Configurable via `DEID_SKIP_PIXEL_SCRUB_MODALITIES` setting.
- **Presidio large series**: sub-batch checkpointing within series. Default batch size **50 files** (≈500s per batch at conservative 10s/image, well within 3600s soft time limit). A 500-instance series needs ~10 sub-batches across ~2 Celery auto-continue invocations. Manifest written after each sub-batch. Series-level atomic write still applies — if any file fails, already-written sub-batches for that series are deleted from output.

- **Presidio bounding box audit logging**: enabled by default. `PixelRedactionLog` model stores bounding box coordinates per file (`job` FK to `DeidentificationJob`, `file_path`, `bboxes` JSONField, `created_at`). Can be disabled via `DEID_LOG_PIXEL_REDACTION_BBOXES = False` setting if storage becomes a concern.

- **Encrypted model fields**: `django-encrypted-model-fields==0.6.5` already installed and configured. `FIELD_ENCRYPTION_KEY` set in `settings.py:713` via `DJANGO_FIELD_ENCRYPTION_KEY` env var. Already in use by `extractor` app (`EncryptedCharField`, `EncryptedTextField`). Deidentification models will use `EncryptedCharField` for all `deidentified_*` columns — no additional setup needed.

## Open items to confirm during implementation
- None — all design decisions resolved.

---

# Complete Code Map

## A. `chavi-deidentification-app` (source, PyQt6 desktop app)

### A.1 Database schema (6 SQLite tables — all confirmed via `app/database/db_initialization.py` + `db_manager.py:769-812`)
| Table | Key columns | Notes |
|---|---|---|
| `users` | id, username, password (sha256), email, registration_date, last_login_date, user_type(admin/user), user_status, security_question, security_answer, force_password_change, reset_token, reset_token_expiry, reset_token_used | Auth only — **not migrated**; `chavi_client` has its own Django auth (`django-allauth`). |
| `patients` | id, encrypted_patient_id (AES, UNIQUE), deidentified_patient_id (UNIQUE), encrypted_date_of_birth, deidentified_date_of_birth, encrypted_date_shift_value | Core mapping table — **migrated**. |
| `dicom_studies` | id, study_uid (plaintext, legacy/unused), encrypted_study_uid (UNIQUE), encrypted_patient_id (FK), deidentified_study_uid (UNIQUE), encrypted_study_date, deidentified_study_date | **migrated**. |
| `dicom_series` | id, series_uid, encrypted_series_uid (UNIQUE), encrypted_study_uid (FK), deidentified_series_uid (UNIQUE), encrypted_series_date, deidentified_series_date, encrypted_frame_of_reference_uid, deidentified_frame_of_reference_uid, modality, referenced_series_uid | **migrated**. Unique constraint on (encrypted_series_uid, encrypted_study_uid, modality). |
| `dicom_instances` | id, sop_instance_uid, encrypted_sop_instance_uid (UNIQUE), encrypted_series_uid (FK), deidentified_sop_instance_uid (UNIQUE) | **migrated**. |
| `deidentification_history` | id, deidentified_patient_id, date_of_processing, processing_time, file_count, processed_count, deidentified_count, output_path | Job/audit log — mapped to new `DeidentificationJob` model (created fresh going forward, not migrated since no original-ID linkage). |

**Encryption**: AES-256-CBC, deterministic IV = `SHA256(plaintext)[:16]`, key = 32 random bytes stored in `data/encryption.key` (`db_encryption.py`, `db_manager.py:136-199`).

**Live DB location** (confirmed by inspecting all DB files present): `main.py` hardcodes `db_path = "data/app.db"` → **`data/app.db` + `data/encryption.key` is the authoritative live pair** (20 patients). Other DB files found are stale/backups and should be ignored for migration:
- `db.sqlite3` (repo root) — empty, no tables.
- `dbbackupapp.db` (repo root) — 9 patients, stale backup.
- `deidentification_db_backup_20250222_094340.sqlite` — 5 patients, older snapshot.
- `deidentification_db_backup_20250224_210028.sqlite` — 6 patients, older snapshot.

### A.2 `app/database/` (DB layer — NOT ported; replaced by Django ORM + `django-encrypted-model-fields`)
| File | Purpose |
|---|---|
| `db_manager.py` | `DatabaseManager` — combines all mixins; `encrypt_value`/`decrypt_value` (AES); `_setup_database`; also duplicates users CRUD + creates `deidentification_history` table in `initialize_database()`. |
| `db_encryption.py` | `EncryptionMixin` — key load/generate (`data/encryption.key`), AES encrypt/decrypt. **Logic reused (read-only) by the legacy import Celery task to decrypt legacy data.** |
| `db_initialization.py` | `InitializationMixin` — `CREATE TABLE` DDL for all 6 tables + indexes, default admin user creation. Source of truth for schema replicated in new Django models. |
| `db_auth.py` | `AuthenticationMixin` — login, password validation/change. Not ported (Django auth). |
| `db_security.py` | `SecurityMixin` — security question/answer hashing, password-reset token flow. Not ported. |
| `db_user_management.py` | `UserManagementMixin` — user CRUD. Not ported. |
| `constants.py` | Table/column name constants — mirrored into new Django model field names for traceability. |

### A.3 `dicomutils/` (deidentification algorithms — PORTED to `deidentification/services/`)
| File | Function(s) | Ported behavior |
|---|---|---|
| `patient_deidentification.py` | `generate_deidentified_patient_id`, `calculate_shifted_date`, `parse_dicom_age`, `deidentify_patient_data` | UUID-dot-separated deidentified ID; birth-date ±100-day shift; age→birthdate fallback via `PatientAge`+`StudyDate`. |
| `study_deidentification.py` | `generate_deidentified_study_uid`, `deidentify_study_data` | UID format `1.2.826.0.1.3680043.10.1561.<3>.<4>.<3>` (org root hardcoded); reuses shift from patient. |
| `series_deidentification.py` | `get_series_count`, `validate_and_correct_uid`, `generate_deidentified_series_uid`, `generate_deidentified_frame_of_reference_uid`, `deidentify_series_data` | Series UID = `<deid_study_uid>.<n>`; FoR UID reused across series sharing same original FoR UID; UID validation (digits+dots, ≤64 chars, even byte length). |
| `instance_deidentification.py` | `generate_deidentified_sop_instance_uid`, `deidentify_instance_data` | SOP UID = `<deid_series_uid>.<7-digit>.<3-digit>`; collision retry loop. |
| `date_replacement.py` | `get_days_shifted`, `deidentify_dates` | Walks dataset for VR `DA`/`DT` elements with "date" in name, shifts by patient's stored day-shift (handles multi-valued too). |
| `name_replacement.py` | `deidentify_names` | Walk-based callback anonymizing `PatientName`, `ReferringPhysicianName`, `InstitutionName`, `PerformingPhysicianName`, `OperatorsName`, `StationName`, `InstitutionalDepartmentName`, `PhysiciansOfRecord`, `RequestingPhysician`, `ReferringPhysicianIdentificationSequence`, `ConsultingPhysicianName`, `ResponsiblePerson`, `ReviewerName` → `"Anonymous"`. |
| `address_phone_replacement.py` | `deidentify_address_phone` | Tag-specific callbacks: Person's Address (0040,1102), Institution Address (0008,0081) → `"Anonymous Address"`; Phone Number (0040,1103) → `"1234567890"`. |
| `referenced_frame_of_reference_replacement.py` | `get_frame_of_reference_mapping`, `replace_referenced_frame_of_reference` | Builds per-patient FoR UID map from DB, replaces tags (0020,0052) and (3006,0024). |
| `referenced_sop_instance_replacement.py` | `get_sop_instance_mapping`, `replace_referenced_sop_instances` | Builds combined study+series+instance UID map per patient; replaces (0008,1155), (300A,0013), (0020,000E), (0020,000D); unmapped UIDs replaced with a hardcoded default UID (`1.2.826...999.99.999`) — **flagged as a possible bug/data-loss point to review during porting**. |
| `unzip_file.py` | `process_dicom_zip` | Simple extract-all + `pydicom.dcmread` validity scan (no progress callback). |
| `import_utils.py` | `process_dicom_zip` (progress-aware), `import_dicom_zip` | Preferred version used by the live flow (extracts with progress, validates `StudyInstanceUID`+`PatientID` present). **Note: `backup/deidentify_dicom.py` imports a non-existent `DEFERRED_MODALITIES` from this file — that script is stale/broken and NOT part of the live flow.** |
| `dicom_deidentification_flow.py` | `process_dicom_metadata`, `perform_deidentification`, `deidentify_dicom_files`, `cleanup_temp_files` | Orchestrator: (1) pass 1 stores metadata/mappings for every file; (2) pass 2 re-reads each file, removes private tags, replaces referenced UIDs/FoR/dates/names/address-phone, overwrites core UIDs+dates, sets `StudyID="123456789"`, `AccessionNumber="123456789101112"`, ensures `TransferSyntaxUID`, saves to `deidentified_dicom/<deid_patient>/<deid_study>/<deid_sop>-<modality>.dcm`; (3) writes `deidentification_history` row per patient. **No explicit deferred-modality ordering (RTSTRUCT/RTPLAN/etc.) despite `deidentification_workflow.md` describing one — current code processes all files in a single flat loop.** |
| `clinical_data_deidentification.py` | `find_patient_id_keys`, `find_date_fields`, `find_study_uid_keys`, `get/set_nested_value`, `shift_date`, `deidentify_clinical_data` | Generic recursive JSON walker; replaces any key matching `patient_id`/`patient`, any `*study_instance_uid*` key (str or list), and shifts any `date`-named or `YYYY-MM-DD`-formatted field using patient's stored day-shift. Errors if a patient/study isn't already in DB (no DICOM deidentification done first) — file skipped. |
| `import_clinical_data.py` | `import_clinical_zip`, `cleanup_temp_files` | Extracts `*.json` from a zip to a temp dir. |
| `dicomutils/__init__.py` | empty | — |

### A.4 `app/` top-level & GUI (NOT ported — replaced by Django views/Celery/admin)
| File | Purpose |
|---|---|
| `app/main.py` | App entrypoint: inits `DatabaseManager("data/app.db")`, shows `LoginDialog`, then `MainWindow`. |
| `app/gui/login_dialog.py` | Username/password login UI. |
| `app/gui/main_window.py` (66KB, ~1900+ lines) | Central UI: DICOM import/deidentify tab (`deidentify_dicom`), Clinical Data tab (`deidentify_clinical_data`), Patient Management tab (`load_patients`, `delete_selected_patients`, search/filter), Deidentification History table (`load_deidentification_history`, date filter), menu bar incl. backup/restore trigger, admin panel launcher, progress bar wiring (`update_progress`). |
| `app/gui/admin_panel.py` | User management UI for admins. |
| `app/gui/register_dialog.py` | New user registration. |
| `app/gui/password_change_dialog.py` / `password_reset_dialog.py` / `security_question_dialog.py` | Auth/password flows. |
| `app/gui/profile_settings_dialog.py` | User profile editing. |
| `app/gui/database_backup_dialog.py` | SQLite file-level backup/restore via `sqlite3` `.backup()` API — equivalent for Django would be a `dumpdata`/DB-level backup strategy (out of scope for this integration; standard Django/Postgres backup practices apply). |
| `app/commands/` | Empty (only `__pycache__`). |
| `backup/deidentify_dicom.py` | Stale/older duplicate of the DICOM flow with a broken import (`DEFERRED_MODALITIES` not defined anywhere) — **dead code, exclude from reference entirely.** |
| `run.py`, `*.spec`, `CHAVI DICOM Deidentification.exe` | PyInstaller packaging — not relevant to Django port. |

### A.5 Root-level docs/data (reference only)
`README.md`, `deidentification_workflow.md` (original design spec — note it describes deferred-modality ordering and organization-prefix UIDs that are **not fully reflected in the current code**, e.g. no deferred processing, hardcoded UID root instead of a configurable org prefix), `notes.md`-equivalent, `test_data.zip`, `dicom/`, `processed_dicom/`, `deidentified_dicom/`, `deidentified_json/`, `logs/`.

## B. `chavi_client` (target integration points)

| Area | File(s) | Relevance |
|---|---|---|
| Patient/DICOM models | `client_app/models.py`: `Patient` (105-174), `PatientDicomFile` (177-199), `DICOMStudy` (216-273) | Canonical clinical records; **not modified** by new app — new app's models reference original IDs independently. |
| Clinical JSON export | `client_app/services/patient_data_export.py` | `export_patient_data` admin action — produces per-patient JSON (patients, dicom_studies, diagnoses, outcomes, lesions, pathologies, etc.) zipped — this is the exact input format the ported `clinical_data_deidentification.py` logic must consume. |
| DICOM export | `client_app/services/dicom_data_export.py` | `export_dicom_data` — zips DICOM files per study from `DICOMStudy.folder_path`, arcname `<patient_id>/<study_uid>/...` — input for ported DICOM deidentification flow. |
| Other DICOM-related services (context, not directly reused) | `client_app/services/{bulk_dicom_data_import.py, dicom_data_import_per_patient.py, frontend_bulk_dicom_import.py, parallel_dicom_export.py, process_unprocessed_dicom.py, associate_dicom_files_to_project.py, task_checkpoint.py}` | Existing DICOM import pipeline (separate from deidentification) — establishes existing Celery task patterns (`task_checkpoint.py`) to follow for the new `deidentification` Celery tasks. |
| Existing Celery tasks | `client_app/tasks.py` (78KB) | Reference for task patterns/conventions to match. |
| Import framework (design reference only) | `data_import/` app (`models.py`, `services/{csv_processor,date_parser,field_introspection,import_executor,json_generator,model_hierarchy}.py`) | Not reused directly, but demonstrates the project's convention for a self-contained sub-app with its own `services/` — template for structuring the new `deidentification` app. |
| Encryption capability already available | `requirements.txt`: `django-encrypted-model-fields==0.6.5`, `cryptography==50.0.0` | Confirms no new dependency needed for re-encryption approach chosen. |
| Settings | `chavi_client/chavi_client/settings.py` (`INSTALLED_APPS` at line 51) | Where new `deidentification` app gets registered. |

## C. Legacy prototype (ignored per confirmation)
`/mnt/share/deidentifcation-app` — Django prototype (`deidapp/models.py`: `Patient`, `DicomStudy`, `DicomSeries`, `DicomInstance`, `RTStructFile` — **unencrypted** plaintext fields, no `deidentification_history` equivalent). Superseded by `chavi-deidentification-app`; not used as a reference for the port.

---

# Legacy-to-Django Column-Level Model Mapping

Full column-by-column comparison of every legacy SQLite table (`app/database/db_initialization.py` + `db_manager.py:769-812`) against the new `deidentification` app's models, reflecting the finalized design (FK-reuse of `client_app`'s existing plaintext PKs, encryption only on `deidentified_*` columns).

## 1. `users` → **NOT MIGRATED** (entire table)
| Legacy column | Type | Mapping |
|---|---|---|
| `id`, `username`, `password`, `email`, `registration_date`, `last_login_date`, `user_type`, `user_status`, `security_question`, `security_answer`, `force_password_change` | — | **Not migrated.** `chavi_client` has its own Django auth (`django-allauth` + Django auth permissions); the new deidentification UI views use `LoginRequiredMixin`, not a separate user table. |

## 2. `patients` → `deidentification.DeidPatient`
| Legacy column | Type | New Django mapping |
|---|---|---|
| `id` (PK) | INTEGER | Not migrated — Django auto `id` PK on `DeidPatient` |
| `encrypted_patient_id` (AES, UNIQUE) | TEXT | **FK-reuse.** Decrypted during migration, matched against `client_app.Patient.pk` (already plaintext). `DeidPatient.patient` = `OneToOneField(client_app.Patient)` |
| `deidentified_patient_id` (UNIQUE) | TEXT | `DeidPatient.deidentified_patient_id` — **Encrypted** (`EncryptedCharField`) |
| `encrypted_date_of_birth` | TEXT | Decrypted during migration. If `client_app.Patient.date_of_birth` is NULL, **back-fills** it (clinical DB value takes priority if already set; log discrepancy if values differ). Not stored separately on `DeidPatient` — original DOB accessed via `patient.date_of_birth` FK traversal. |
| `deidentified_date_of_birth` | TEXT | `DeidPatient.deidentified_date_of_birth` — **Encrypted** (`EncryptedDateField`) |
| `encrypted_date_shift_value` (AES) | TEXT (AES) | `DeidPatient.date_shift_value` — **Encrypted** `EncryptedIntegerField` (corrected decision — must remain encrypted at rest, matching legacy behavior) |

## 3. `dicom_studies` → `deidentification.DeidStudy`
| Legacy column | Type | New Django mapping |
|---|---|---|
| `id` (PK) | INTEGER | Not migrated — Django auto `id` PK |
| `study_uid` (plaintext, legacy/unused) | TEXT | Not migrated — dead/duplicate column in legacy schema, superseded by `encrypted_study_uid` |
| `encrypted_study_uid` (UNIQUE) | TEXT | **FK-reuse.** Decrypted, matched against `client_app.DICOMStudy.pk`. `DeidStudy.study` = `OneToOneField(client_app.DICOMStudy)` |
| `encrypted_patient_id` (FK) | TEXT | Not migrated — relationship now derived via `DeidStudy.study.patient` (through `client_app.DICOMStudy.patient` FK) or explicit `DeidStudy.patient = ForeignKey(DeidPatient)` set during migration |
| `deidentified_study_uid` (UNIQUE) | TEXT | `DeidStudy.deidentified_study_instance_uid` — **Encrypted** |
| `encrypted_study_date` | TEXT | Not duplicated — original available via `study.study_date` (plain field on `client_app.DICOMStudy`) |
| `deidentified_study_date` | TEXT | `DeidStudy.deidentified_study_date` — **Encrypted** |

## 4. `dicom_series` → `deidentification.DeidSeries`
| Legacy column | Type | New Django mapping |
|---|---|---|
| `id` (PK) | INTEGER | Not migrated — Django auto `id` PK |
| `series_uid` | TEXT | Not migrated — dead/duplicate column (same pattern as `dicom_studies.study_uid`) |
| `encrypted_series_uid` (UNIQUE) | TEXT | Decrypted → matched against `client_app.DICOMSeries.series_instance_uid`. `DeidSeries.series` = `OneToOneField(client_app.DICOMSeries)` |
| `encrypted_study_uid` (FK) | TEXT | Not migrated — relationship via `DeidSeries.study = ForeignKey(DeidStudy)` |
| `deidentified_series_uid` (UNIQUE) | TEXT | `DeidSeries.deidentified_series_instance_uid` — **Encrypted** |
| `encrypted_series_date` | TEXT | Not duplicated — original available via `series.series_date` (plain field on `client_app.DICOMSeries`) |
| `deidentified_series_date` | TEXT | `DeidSeries.deidentified_series_date` — **Encrypted** |
| `encrypted_frame_of_reference_uid` | TEXT | Not duplicated — original available via `series.frame_of_reference_uid` (plain field on `client_app.DICOMSeries`) |
| `deidentified_frame_of_reference_uid` | TEXT | `DeidSeries.deidentified_frame_of_reference_uid` — **Encrypted** |
| `modality` | TEXT | Not duplicated — available via `series.modality` (plain field on `client_app.DICOMSeries`) |
| `referenced_series_uid` | TEXT | Not migrated — legacy field unused by the deidentification algorithms being ported |
| `UNIQUE(encrypted_series_uid, encrypted_study_uid, modality)` constraint | — | Replaced by `OneToOneField(client_app.DICOMSeries)` (series_instance_uid is unique on DICOMSeries) |

## 5. `dicom_instances` → `deidentification.DeidInstance`
| Legacy column | Type | New Django mapping |
|---|---|---|
| `id` (PK) | INTEGER | Not migrated — Django auto `id` PK |
| `sop_instance_uid` | TEXT | Not migrated — dead/duplicate column (same pattern as above) |
| `encrypted_sop_instance_uid` (UNIQUE) | TEXT | Decrypted → matched against `client_app.DICOMInstance.sop_instance_uid`. `DeidInstance.instance` = `OneToOneField(client_app.DICOMInstance)` |
| `encrypted_series_uid` (FK) | TEXT | Not migrated — relationship via `DeidInstance.series = ForeignKey(DeidSeries)` |
| `deidentified_sop_instance_uid` (UNIQUE) | TEXT | `DeidInstance.deidentified_sop_instance_uid` — **Encrypted** |

## 6. `deidentification_history` (created in `db_manager.py:769-812`, separate from `db_initialization.py`) → `deidentification.DeidentificationJob`
| Legacy column | Type | New Django mapping |
|---|---|---|
| `id` (PK) | INTEGER | Not migrated — Django auto `id` PK |
| `deidentified_patient_id` | TEXT | `DeidentificationJob.deid_study` — **FK** to `DeidStudy` (job now scoped per-study, matching the new `deidentify_dicom_studies` action's granularity, rather than per-patient) |
| `date_of_processing` | TEXT | `DeidentificationJob.created_at` — **Plain** `DateTimeField` (Django `auto_now_add`) |
| `processing_time` | REAL | `DeidentificationJob.processing_time_seconds` — **Plain** `FloatField` |
| `file_count` | INTEGER | `DeidentificationJob.file_count` — **Plain** |
| `processed_count` | INTEGER | `DeidentificationJob.processed_count` — **Plain** |
| `deidentified_count` | INTEGER | `DeidentificationJob.deidentified_count` — **Plain** |
| `output_path` | TEXT | `DeidentificationJob.output_path` — **Plain** |
| *(no equivalent in legacy)* | — | `DeidentificationJob.status` (pending/running/success/failed), `error_log` — **new fields**, needed for Celery task tracking (legacy app ran synchronously in the GUI thread, no status tracking needed) |

**Note**: this table is **not migrated** (no historical job records ported) — only the mapping tables (2–5 above) are migrated, per the confirmed production scope. `DeidentificationJob` rows are created fresh as new deidentification actions run.

## Summary
| Legacy table | Migrated? | New model | Key design shift |
|---|---|---|---|
| `users` | No | — | Superseded by Django auth |
| `patients` | Yes | `DeidPatient` | Original ID via FK to `client_app.Patient`, not duplicated/encrypted |
| `dicom_studies` | Yes | `DeidStudy` | Original UID via FK to `client_app.DICOMStudy` |
| `dicom_series` | Yes | `DeidSeries` | Original UID via FK to `client_app.DICOMSeries` (new model) |
| `dicom_instances` | Yes | `DeidInstance` | Original UID via FK to `client_app.DICOMInstance` (new model) |
| `deidentification_history` | No (schema ported, data not) | `DeidentificationJob` | Rebuilt for Celery job tracking, scoped per-study |
