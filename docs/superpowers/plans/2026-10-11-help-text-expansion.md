# Help Text Expansion Plan (client_app models)

> **For agentic workers:** Steps use checkbox (`- [x]`) syntax. Each task is one table (or table group) in `client_app/models.py`; after each task re-run schema discovery so `extractor.DatabaseField.help_text` picks up the new text.

**Goal:** Expand/rewrite the `help_text` on every clinical field in `client_app/models.py` so the same string serves two readers: (a) the human data-enterer in the Django admin form, and (b) the LLM in the extractor — where the help text is the *only* semantic description of the field it has.

**Architecture:** No code changes to the extractor are required. The help text already flows through:
1. `extractor/services/schema_discovery.py` (~L290) — copies `field.help_text` verbatim into `DatabaseField.help_text` on every discovery run.
2. `extractor/services/pydantic_builder.py` (~L256, ~L485) — appends it to the Pydantic field `description` as `"{table}.{field} — {help_text}"`.
3. `extractor/services/instructor_extractor.py` (~L269, ~L388, ~L420) — embeds it in the text schema line, the stage-1 mining prompt, and the recheck prompt, where it is the "short meaning" of the field.
4. Human side: Django admin renders `help_text` under each form field.

**Tech Stack:** Django models only; verification via `manage.py` schema discovery + prompt snapshot.

**Spec:** this document (§Expansion template, §Global issues, per-table tasks).

## Global Constraints

- Help text stays **under ~50 words** per field — it is injected per-field into LLM prompts; bloat costs tokens on every extraction and dilutes signal.
- One consistent date phrasing app-wide. Adopt: `Date (DD/MM/YYYY).` with the ISO storage noted once per table in the table docstring, not per field.
- Never state a nullable field is "required" (`Patient.chavi_consent` currently does).
- Lookup FKs: describe the concept + canonical terms + common synonyms/abbreviations. Do **not** enumerate choices — the extractor already injects "Valid Options (most relevant)" after the help text.
- Non-lookup relation FKs (`patient`, `diagnosis`, `pathology`) and auto fields (`created_at`, `updated_at`, UUID pks) are excluded from LLM prompts by `DatabaseField.is_extractable()`. Their help text is human-only: keep it short, no expansion effort.
- Fixes must be in `client_app/models.py` (source of truth). After a task, re-run schema discovery so `extractor.DatabaseField.help_text` refreshes (it auto-refreshes for non-manual fields; manual lookup config is untouched by discovery).

## Expansion template

Every extractable field's help text should answer, in order (omit parts that don't apply):

1. **Definition** — one declarative sentence of what the value is clinically (no "Select…" / "Enter…" imperatives).
2. **Source hint** — where it is typically found: "from the pathology report", "in the RT plan summary", "on the discharge summary", "DICOM metadata".
3. **Format / units / constraints** — unit, range, date format, decimal precision, e.g. "in mm", "0–100 %", "per 10 HPF".
4. **Synonyms & disambiguation** — abbreviations/phrasings seen in clinical text (e.g. "also called MRN / hospital number"), and which value to take when several candidates appear (e.g. "use pathological confirmation date over clinical diagnosis date when both are present").
5. **Omission rule** — "Leave blank if not documented." (only for optional fields).

### Do / Don't

- DO: state the unit in the value field's help text even when a separate unit FK exists — the LLM extracts value and unit independently and needs the default.
- DO: for booleans, state the clinical meaning of True and the default ("True if the patient is on medication for it; False otherwise").
- DO: for M2M-to-DICOMStudy fields, state what "associated" means clinically (e.g. "imaging on which this outcome was assessed").
- DON'T: UI verbs ("Select the patient", "check for Yes, leave unchecked for No") — meaningless to the LLM, redundant in admin (the widget already says it).
- DON'T: contradictions (e.g. `DICOMStudy.study_date` says "recorded as DD/MM/YYYY format (for example: 2023-12-25)").
- DON'T: copy-paste leftovers (two Pathology LVI fields currently say "perineural invasion").

## Global issues (fix wherever they occur)

- [x] Typo: `Diagnosis.diagnosis` — "Select the diagbnosis ICD code".
- [x] Copy-paste: `Pathology.lymphatic_vascular_invasion` and `Pathology.dermal_lymphatic_vascular_invasion` both say "Presence or absence of perineural invasion".
- [x] Contradictory format: `DICOMStudy.study_date` "(for example: 2023-12-25)" after "DD/MM/YYYY".
- [x] False "required" claim: `Patient.chavi_consent`.
- [x] Wrong unit examples: `LesionResponse.residual_lesion_volume_unit` lists "millimeters, centimeters" (length units on a volume field).
- [x] Inconsistent date phrasing: ~20 fields say "(format:DD/MM/YYYY)" inline; standardize.
- [x] ~30 fields have **no help text at all**; in the mining prompt they appear only as "as named". Highest-risk tables: `GermlineGenomicAlterations` (7 fields), `Cytogenetics` (partial), `Surgery`, `OtherTreatment`, `Outcome.diagnosis`, `Symptom.patient/symptom`.

---

## Task 1: Core tables — SiteConfiguration, Project, Patient, PatientDicomFile

Format below: `field — current → proposed`. Fields marked **(auto)** are not sent to the LLM; only fix human clarity.

### 1.1 SiteConfiguration

- [x] `chavi_center_id` — "Site ID. This will be provided to you at the time of installation." → keep (human-only, not extractable).
- [x] `center_name` — "Your Hospital" → "Full official name of the hospital/institution where this CHAVI client is installed."

### 1.2 Project

- [x] `chavi_project_id` — "A unique identifier for the project." → "CHAVI-assigned unique identifier for the project (provided by the CHAVI team; not derived from local documents)."
- [x] `project_name` — "The name of the project." → "Name of the research project/study, as named in the protocol or IRB approval."

### 1.3 Patient

- [x] `chavi_consent` — claims "required and must be set to True" but field is nullable → "True if the patient (or guardian) gave documented consent for CHAVI data use. Leave blank if consent is not documented."
- [x] `date_chavi_consent` — "…required if chavi_consent is True." → "Date written consent was obtained. Set when consent is True. (DD/MM/YYYY)"
- [x] `patient_id` — "This should be your institution's medical record number…" → "The patient's unique identifier at this institution — usually the Medical Record Number. In records it may appear as 'MRN', 'MR No', 'hospital number', or 'admission number'. Must match the identifier used on imaging and reports for the same patient."
- [x] `gender` — "The patient's gender" → "Patient's gender as documented (Male, Female, Transgender, Non-Binary). May be recorded as 'sex'. Leave blank only if unknown."
- [x] `date_of_birth` — "…in DD/MM/YYYY format." → "Patient's date of birth. Appears as 'DOB' in records. (DD/MM/YYYY)"
- [x] `date_of_registration` — "Date of registration in hospital." → "Date the patient was first registered/admitted at this institution; may appear as 'registration date' or 'first visit date'. Cannot be earlier than date of birth."
- [x] `patient_project` — fine; → "Project(s) the patient is enrolled in. A patient may be in more than one."
- [x] `canonical_patient_id`, `created_at`, `updated_at` **(auto)** — keep.

### 1.4 PatientDicomFile

- [x] `file` — "Please upload a single zip file having the DICOM studies for a single patients. You can choose to upload multiple studies at the same time." → "ZIP archive of DICOM studies belonging to ONE patient; multiple studies per archive are allowed. (.zip only)"
- [x] `processed`, `processing_log` **(auto/system)** — keep.

- [x] Verify: re-run schema discovery; confirm `DatabaseField.help_text` updated for `patient.*` rows (spot-check `patient_id`, `date_of_birth`).

## Task 2: DICOM tables — DICOMStudy, StudyTypeRule, DICOMSeries, DICOMInstance

### 2.1 DICOMStudy

Most fields here come from DICOM metadata, so the expansion is *tag citation + plain-language meaning*. That lets the LLM map report text ("CT neck performed on 25/12/2023, UID 1.2.3…") to the right field.

- [x] `patient` **(relation, not extractable)** — keep, simplify: "Patient this imaging study belongs to."
- [x] `study_instance_uid` — long human explanation → "DICOM tag (0020,000D) Study Instance UID — globally unique identifier of this imaging study. Copy it exactly as written; never invent or truncate it."
- [x] `study_date` — contradictory example → "Date the imaging study was performed (DICOM tag (0008,0020) Study Date). (DD/MM/YYYY)"
- [x] `study_description` — "Description Provided in the DICOM Data" → "Free-text study description from DICOM metadata (tag (0008,103E)); often names the body region and exam, e.g. 'CT NECK 3 PHASE'."
- [x] `study_type` — "a choice field that can be selected from the list" (meta, useless) → "Where the study sits in the treatment timeline: pre-treatment diagnostic, planning, on-treatment verification, planning for adaptive treatment, post-treatment response, therapy delivery, therapy QA, post-treatment diagnostic, or other."
- [x] `study_type_source` — keep (system-managed).
- [x] `study_modalities` — "The modalities inside the the study." → "DICOM modality codes contained in the study (e.g. CT, MR, PT, RTDOSE, US); comma-separated if several."
- [x] `series_descriptions` — fine; → "Descriptions of all series in the study (DICOM tag (0008,103E) per series), comma-separated."
- [x] `folder_path`, `created_at`, `updated_at` **(auto)** — keep.

### 2.2 StudyTypeRule (admin config — human-only, no LLM exposure)

- [x] `match_modality`, `match_study_description`, `match_series_description` — no help text → add one line each: "Study/modality/series-description text this rule matches."
- [x] `date_window_start_days` / `date_window_end_days` — no help text → "Days before/after the reference event for which the rule may fire (negative = before)."
- [x] `study_type`, `priority`, `enabled` — fine.

### 2.3 DICOMSeries / 2.4 DICOMInstance

Already tag-cited; LLM exposure low (metadata models).
- [x] `DICOMSeries.series_date` — "(0008,0021) — Series Date." fine; add "(DD/MM/YYYY)".
- [x] `DICOMSeries.study`, `DICOMInstance.series` — fine.
- [x] Rest — keep.

## Task 3: Diagnosis, Outcome

### 3.1 Diagnosis

- [x] `patient` **(relation)** — "Select the patient" → "Patient to whom this diagnosis belongs."
- [x] `cancer_system` — "Select the major cancer category" → "Major cancer system/organ the cancer belongs to (e.g. breast, lung, cervix)."
- [x] `diagnosis` — typo "diagbnosis" → "ICD-11 code for the diagnosed cancer. Create a separate Diagnosis record per distinct cancer."
- [x] `diagnosis_date` — "Select the data at which…" (typo "data") → "Date the diagnosis was made. Prefer the pathological confirmation (biopsy) date; if only a clinical diagnosis exists, use the first definitive clinical assessment. (DD/MM/YYYY)"
- [x] `presentation_type` — fine; → "How the disease presented: new primary, recurrence, or metastasis."
- [x] `cancer_site` — fine; → "Anatomical location of the cancer (FMA code) — first-diagnosis site, or recurrence/metastasis site."
- [x] `cancer_side` — "Select the side at which the cancer was present." → "Side of the body where the cancer is (left/right/bilateral/midline)."
- [x] `diagnostic_modality` — "…spelled correctly" (unneeded) → "Method used to establish the diagnosis (biopsy, cytology, FNA, imaging, endoscopy…)."
- [x] `study_instance_uid` — fine; → "Imaging studies that supported or confirmed this diagnosis."
- [x] `diagnosis_project` — fine; → "CHAVI project(s) this diagnosis belongs to."

### 3.2 Outcome

- [x] `diagnosis` **(relation)** — no help text → "Disease (diagnosis record) for which this treatment outcome was assessed."
- [x] `date_outcome_assessed` — fine; → "Date the outcome was assessed, documented, or confirmed (e.g. imaging review date). (DD/MM/YYYY)"
- [x] `outcome_type` — "…create another instance of the form" → "Outcome category observed for this disease. Add a new Outcome record for each later assessment."
- [x] `study_instance_uid` — fine; → "Imaging studies on which this outcome was assessed."

## Task 4: Lesion, LesionResponse

The x/y/z axis fields are the trickiest for the LLM: reports rarely say "x-axis". The expansion must state the mapping rule explicitly and the blank-when-absent rule.

### 4.1 Lesion

- [x] `diagnosis` **(relation)** — fine.
- [x] `date_lesion_assessed` — → "Date the lesion was assessed/measured (report date of the imaging or exam where it was described). (DD/MM/YYYY)"
- [x] `lesion_site` — fine; → "Anatomical location of the lesion (FMA code), e.g. left breast, right lung, liver."
- [x] `lesion_type` — → "Category of the lesion: primary/gross tumor, nodal disease, or distant metastasis."
- [x] `lesion_laterality` — fine.
- [x] `lesion_size_x_axis` — → "First dimension of the lesion as reported (when a report gives 'a × b × c' or 'L × W × H', take the first value). Numeric, in lesion_size_unit (usually mm). Blank if no size given."
- [x] `lesion_size_y_axis` — → "Second reported dimension (middle value of 'a × b × c'). Blank if the report gives fewer than two dimensions."
- [x] `lesion_size_z_axis` — → "Third reported dimension (last value of 'a × b × c'). Blank if not reported."
- [x] `lesion_size_unit` — fine; → "Unit of the three size fields (mm, cm). Reports usually use mm."
- [x] `lesion_volume` — "calculated from the 3D measurements" (over-promises auto-calc) → "Volume of the lesion if stated in the report (e.g. 'volume 12.3 cc'). In lesion_volume_unit. Blank if not stated."
- [x] `lesion_volume_unit` — fine; examples "mm³, cm³/cc".
- [x] `lesion_detection_modality` — → "Modality that detected or describes this lesion (CT, MRI, PET, US, endoscopy, clinical exam…)."
- [x] `lesion_suv_max` — fine; → "Maximum standardized uptake value (SUVmax) of the lesion on PET. Unitless."
- [x] `study_instance_uid` — fine; → "Imaging study/studies in which this lesion was detected or assessed."

### 4.2 LesionResponse

- [x] `lesion` **(relation)** — keep ("lesion being monitored").
- [x] `lesion_response_date` — add "(DD/MM/YYYY)".
- [x] `lesion_response` — → "Response category at this assessment (e.g. complete response, partial response, stable disease, progression)."
- [x] `residual_lesion_size_x_axis` — → "First dimension of the REMAINING disease at this assessment (first value of 'a × b × c'). In residual_lesion_size_unit. Blank if no residual disease or no size given."
- [x] `residual_lesion_size_y_axis` / `_z_axis` — same pattern, second/third value.
- [x] `residual_lesion_size_unit` — fine; → "Unit of the residual size fields (mm, cm)."
- [x] `residual_lesion_volume` — → "Volume of remaining disease at this assessment, in residual_lesion_volume_unit. Blank if none."
- [x] `residual_lesion_volume_unit` — WRONG unit examples ("millimeters, centimeters") → "Unit of the residual volume (mm³, cm³/cc)."
- [x] `lesion_response_suv_max` — **no help text** → "SUVmax of the residual lesion at the response assessment on PET. Blank if no residual uptake reported."
- [x] `lesion_response_modality` — → "Modality used to assess the response (CT, MRI, PET…)."
- [x] `study_instance_uid` — → "Imaging study used for this response assessment."

## Task 5: Symptom

- [x] `patient` **(relation)** — no help → "Patient who has this symptom."
- [x] `symptom` — no help → "The symptom recorded (from the symptom list), e.g. pain, dyspnoea, weight loss."
- [x] `date_onset` — → "Date the symptom first started. If not stated but assessment date + duration are given, it is derived as assessment date minus duration. (DD/MM/YYYY)"
- [x] `date_symptom_assessment` — → "Date the symptom was assessed/documented. (DD/MM/YYYY)"
- [x] `duration_of_symptom` — fine; → "How long the symptom had been present before assessment, in whole months."
- [x] `date_resolution` — fine; → "Date the symptom resolved or improved, if applicable."
- [x] `severity` — fine; → "Severity/grade of the symptom."

## Task 6: Pathology and pathology-linked lab tables

### 6.1 Pathology (largest table)

- [x] `diagnosis` **(relation)** — fine.
- [x] `date_pathology` — → "Date of the pathology report; prefer the date when the report was authorized or date of pathology report is provided and if not available then use the specimen collection date only if the report date is unavailable. (DD/MM/YYYY)"
- [x] `specimen_type`, `tumor_site`, `tumor_side`, `histological_type`, `histological_grade`, `tumor_focality` — already good; keep.
- [x] `greatest_dimension_of_tumor` — "in centimeters" contradicts separate unit FK → "Largest tumor dimension from the pathology report. Unit in tumor_dimesion_unit (usually cm)."
- [x] `additional_tumor_dimension_1` / `_2` — → "Second / third tumor dimension as reported. Unit in tumor_dimesion_unit."
- [x] `tumor_dimesion_unit` — → "Unit of the three tumor dimension fields (cm, mm)." (field-name typo `dimesion` stays; help text fixes it for readers)
- [x] `lymphatic_vascular_invasion` — copy-paste bug → "Presence or absence of lymphovascular or lymphovascular space invasion (LVI or LVSI)."
- [x] `perineural_invasion` — fine.
- [x] `dermal_lymphatic_vascular_invasion` — copy-paste bug → "Presence or absence of dermal lymphatic invasion."
- [x] `necrosis` — fine. `necrosis_percentage` — add "0–100, percent of the specimen that is necrotic. If a range is provided then enter the max value."
- [x] `mitotic_count` — fine; → "Mitotic count per 10 high-power fields (or per 2 mm², as reported)."
- [x] `margin_status`, `closest_margin_distance` → add "in closest_margin_distance_unit (usually mm)." `closest_margin_distance_unit` — fine.
- [x] `treatment_effect` — "Select the treatment effect" → "Treatment effect seen in the specimen (e.g. regression/necrosis after neoadjuvant therapy)."
- [x] `primary_gleason_grade` / `secondary_gleason_grade` — → "Primary / secondary Gleason pattern (1–5); prostate cancer only."
- [x] `lymph_nodes_removed` — → "Whether lymph nodes were examined in the specimen (True/False)."
- [x] `lymph_nodes_in_specimen` — fine; → "Total lymph nodes examined."
- [x] `lymph_node_extracapsular_extension` — typo "extracpsular" → "Whether any lymph node showed extracapsular extension."
- [x] `number_of_uninvolved_nodes` — → "Number of negative (tumor-free) or uninvolved lymph nodes. Sometimes written as lymph node show reactive hyperplasia or granulolomatous lymphadenitis."
- [x] `number_of_nodes_with_macrometastases` — → "Number of lymph nodes with macrometastases (>2 mm). If dimension of metastases is not available then count as macrometastases"
- [x] `number_of_nodes_with_micrometastases` — fine (>0.2–2 mm). -&gt; 
- [x] `number_of_nodes_with_isolated_tumor_cells` — fine (<0.2 mm).
- [x] `number_of_nodes_with_extracapsular_extension` — fine.

### 6.2 Immunohistochemistry

- [x] `date_ihc` — add "(DD/MM/YYYY)"; → "Date the IHC test was performed. This can be the date of pathology if the dates for IHC are not explicitly provided."
- [x] `protein_name` — → "Antibody/target marker tested (e.g. ER, PR, HER2, Ki-67, PD-L1, p53)."
- [x] `ihc_result` — typo "staning" → "Overall qualitative result of the stain (e.g. positive, negative, equivocal)."
- [x] `percentage_positive_tumor_cells` — fine; → "Percentage of tumor cells with positive staining (0–100)."
- [x] `percentage_positive_immune_cells` — → "Percentage of (tumor-infiltrating) immune cells with positive staining (0–100)."
- [x] `tumor_cell_staining_intensity` — → "Staining intensity grade of the tumor cells (e.g. 0–3)."
- [x] `allred_score` — → "Allred score (0–8): staining intensity score plus percentage-score category. "
- [x] `cps_score` — fine; → "Combined Positive Score (CPS): stained tumor and immune cells per 100 tumor cells."
- [x] `tps_score` — fine; → "Tumor Proportion Score (TPS): percent of tumor cells with positive membrane staining (0–100)."

### 6.3 Cytogenetics

- [x] `date_cytogenetics` — add "(DD/MM/YYYY)".
- [x] `gene` — fine; → "Gene tested."
- [x] `cytogenetic_abnormality` — → "Type of abnormality found (e.g. translocation, amplification, deletion, mutation)."
- [x] `cytogenetic_result` — fine; → "Result of the test (e.g. positive, negative, not detected)."

### 6.4 SomaticGenomicAlterations

- [x] `date_test` — add "(DD/MM/YYYY)". `cosmic_gene_name`, `reference_sequence`, `protein_modification`, `variant_type`, `clinical_significance` — already good; keep.
- [x] `allele_frequency` — fine; → "Variant allele frequency as a decimal (0.45 = 45%)."
- [x] `read_depth` — fine; → "Sequencing read depth (coverage) at the variant."

### 6.5 GeneExpressionData

- [x] `date_test` — add "(DD/MM/YYYY)". `gene` — fine.
- [x] `expression_value` — → "Measured expression level of the gene (e.g. mRNA amount, FISH count, score)."
- [x] `expression_units` — → "Unit of the expression value (e.g. fold-change, TPM, arbitrary units, % positive cells)."

### 6.6 EpigeneticData

- [x] `date_test` — add "(DD/MM/YYYY)". `gene` — fine.
- [x] `epigenetic_abnormality_type` — → "Type of epigenetic change (e.g. promoter hypermethylation, hypomethylation)."
- [x] `epigenetic_result` — → "Result of the epigenetic test (e.g. 'hypermethylated', positive/negative)."

## Task 7: GermlineGenomicAlterations (highest risk — 7 fields have NO help text)

- [x] `patient` **(relation)** — no help → "Patient who underwent this germline (inherited) genetic test."
- [x] `date_test` — no help → "Date the germline genetic test was performed. (DD/MM/YYYY)"
- [x] `cosmic_gene_name` — no help → "Gene in which the germline variant was found (COSMIC gene nomenclature), e.g. BRCA1, BRCA2."
- [x] `reference_sequence` — no help → "Reference transcript identifier (e.g. NM_007294.3)."
- [x] `protein_modification` — no help → "Protein-level change (e.g. p.R42Q, c.123G>A)."
- [x] `variant_type` — no help → "Variant type (e.g. missense, nonsense, frameshift, deletion, insertion, splice-site)."
- [x] `allele_frequency` — no help → "Variant allele frequency as a decimal (0.05 = 5%)."
- [x] `read_depth` — no help → "Sequencing read depth (coverage) at the variant."
- [x] `clinical_significance` — no help → "Clinical significance of the variant (e.g. pathogenic, VUS, benign)."

## Task 8: Treatment tables

### 8.1 OtherTreatment

- [x] `treatment` — → "Name or description of the treatment (e.g. drug name, 'immunotherapy', 'hormonal therapy')."
- [x] `treatment_intent` — fine.
- [x] `treatment_start_date` / `treatment_end_date` — add "(DD/MM/YYYY)"; end: "Blank if still ongoing."

### 8.2 Radiotherapy

- [x] `radiotherapy_course_type` — → "Primary course or boost course."
- [x] `radiotherapy_modality` — → "Radiation modality/technology (e.g. 3D-CRT, IMRT, VMAT, brachytherapy, proton)."
- [x] `reirradiation` — → "True if this is re-irradiation of a previously irradiated region."
- [x] `total_dose` — → "Total dose for the whole course. Unit in radiation_dose_units (Gy or cGy)."
- [x] `total_fractions` — fine; → "Total number of fractions in the course."
- [x] `simultaneous_integrated_boost` — → "True if a simultaneous integrated boost (SIB) was part of this course."
- [x] `simultaneous_integrated_boost_dose` — → "SIB dose. Unit in radiation_dose_units."
- [x] `radiation_dose_units`, `radiotherapy_intent`, `radiotherapy_type`, `radiotherapy_technique`, `fractions_per_day`, `radiotherapy_side` — fine; keep.
- [x] `radiotherapy_machine` — → "Manufacturer/model of the treatment machine (e.g. 'Varian TrueBeam')."
- [x] `radiotherapy_start_date` / `radiotherapy_end_date` — add "(DD/MM/YYYY)"; end: "Blank if ongoing."
- [x] `study_instance_uid` — → "Imaging studies for this course (planning CT, verification images)."

### 8.3 RadiotherapyVolume

- [x] `volume_name` — → "Name of the structure/volume as in the plan (e.g. 'PTV1', 'Lung', 'Brain stem')."
- [x] `volume_type` — fine (PTV/CTV/GTV/OAR).
- [x] `volume_dose_prescribed` — → "Dose prescribed to this volume. Unit in radiation_dose_units."
- [x] `volume_fractions` — fine; → "Number of fractions to this volume."
- [x] `volume_radiotherapy_start_date` / `_end_date` — add "(DD/MM/YYYY)"; end: "Blank if ongoing."
- [x] `anatomical_locations` — fine; → "Anatomical sites covered by this volume."

### 8.4 RadiotherapyDoseVolumeData

- [x] `volume_name` / `volume_type` — fine.
- [x] `absolute_volume` — → "Physical volume of the structure, in cc (volume_units)."
- [x] `relative_volume` — → "Volume as a percentage of the reference organ (e.g. lung, liver), 0–100."
- [x] `absolute_dose` — → "Absolute dose metric for this volume (e.g. Dmean, D95). Unit in radiation_dose_units."
- [x] `relative_dose` — → "Dose metric as a percentage, 0–100."
- [x] `volume_dose_prescribed`, `radiation_dose_units`, `volume_units` — fine; keep.

### 8.5 Surgery

- [x] `surgery_type` — example "Whole Breast Irradiation" is a radiotherapy term → "Surgical procedure(s) performed (e.g. mastectomy, lumpectomy, axillary dissection, biopsy)."
- [x] `surgery_date` — add "(DD/MM/YYYY)".
- [x] `surgery_side`, `surgery_intent`, `nodal_assessment`, `nodal_assessment_type`, `reconstruction`, `type_reconstruction` — fine; drop "check for Yes" phrasing, keep meanings.
- [x] `study_instance_uid` — → "Imaging studies related to the surgery (pre- or post-operative)."

### 8.6 ConcomitantMedications

- [x] `medication_name` — → "Medication name exactly as documented (generic name preferred)."
- [x] `medication_dose` — → "Dose per administration/cycle. Unit in medication_dose_units."
- [x] `medication_dose_units` — fine.
- [x] `date_medication_start_date` / `_end_date` — add "(DD/MM/YYYY)"; end: "Blank if still being taken."
- [x] `medication_route` — fine.

### 8.7 SystemicTherapy

- [x] `systemic_therapy_type` — → "Type of systemic therapy (e.g. chemotherapy, immunotherapy, hormonal, targeted, bispecific)."
- [x] `systemic_therapy_intent`, `systemic_therapy_regimen` — fine.
- [x] `systemic_therapy_sequence` — → "Sequence/line of therapy (e.g. first-line, second-line, induction, consolidation, adjuvant)."
- [x] `systemic_therapy_start_date` / `_end_date` — add "(DD/MM/YYYY)"; end: "Blank if ongoing."
- [x] `cycles_delivered` — → "Number of cycles actually delivered."
- [x] `study_instance_uid` — → "Imaging studies used to assess this course."

### 8.8 SystemicTherapySchedule

- [x] `systemic_therapy_agent` — → "Specific drug/agent in this course (e.g. 'paclitaxel')."
- [x] `systemic_therapy_agent_start_date` / `_end_date` — add "(DD/MM/YYYY)"; end: "Blank if ongoing."
- [x] `systemic_therapy_dose_planned` — → "Planned dose per cycle/administration. Unit in systemic_therapy_dose_units."
- [x] `systemic_therapy_dose_administered` — → "Dose actually administered. Unit in systemic_therapy_dose_units."
- [x] `systemic_therapy_dose_units`, `systemic_therapy_agent_route` — fine.

### 8.9 AdverseEffects

- [x] `ctcae_grade_lookup` — → "CTCAE term and grade (1–5) of the adverse event/toxicity."
- [x] `adverse_effect_start_date` — → "Date the adverse effect first occurred. (DD/MM/YYYY)"
- [x] `adverse_effect_end_date` — → "Date it resolved, if resolved. Blank if ongoing."

## Task 9: Outcome/assessment/lab/staging tables

### 9.1 PatientOutcome

- [x] `patient_status` — → "Patient's last known status (e.g. alive, dead, lost to follow-up)."
- [x] `date_of_death` — → "Date of death, if applicable. Blank if alive."
- [x] `last_date_of_follow_up` — add "(DD/MM/YYYY)"; → "Date of the most recent follow-up."
- [x] `death_related_to_cancer_progression` — drop "check for Yes" → "True if death was attributed to cancer progression."

### 9.2 Comorbidity

- [x] `comorbidity_type` — → "Non-cancer condition (e.g. diabetes, hypertension, COPD)."
- [x] `date_of_comorbidity_diagnosis` — currently "automatically calculated" (misleading; it can be entered) → "Date the comorbidity was diagnosed. If blank, derived as assessment date minus duration."
- [x] `date_of_comorbidity_assessment` / `duration_of_comorbidity` — fine; add "(DD/MM/YYYY)" to the date.
- [x] `comorbidity_resolved`, `medication_for_comorbidity` — → "Whether the comorbidity is resolved" / "Whether the patient is on medication for it."

### 9.3 StageInformation

- [x] `staging_system` — fine.
- [x] `stage_type` — → "Basis of staging (clinical / pathological / restaging)."
- [x] `t_stage_prefix`, `n_stage_prefix`, `m_stage_prefix` — consolidate phrasing → "Prefix showing basis: 'c' = clinical, 'p' = pathological."
- [x] `t_stage` — → "T descriptor for the primary tumor (T0–T4 with sub-scores)."
- [x] `n_stage` — → "N descriptor for lymph-node involvement (N0–N3)."
- [x] `m_stage` — → "M descriptor for distant metastasis (M0, M1, M1a/M1b/M1c)."
- [x] `t/n/m_stage_suffix` — fine; → "Sub-classification suffix (a/b/c)."
- [x] `overall_stage` — → "Overall stage grouping (I, II, III, IV)."

### 9.4 LaboratoryResults

- [x] `laboratory_test` — → "Test that was measured (e.g. haemoglobin, CA 125, LDH)."
- [x] `result_date` — add "(DD/MM/YYYY)".
- [x] `quantitative_result_value` — → "Numeric result. Leave blank when the result is qualitative."
- [x] `quantitative_result_unit` — fine.
- [x] `qualitative_laboratory_result` — → "Qualitative result (positive, negative, present, absent, detected…). Leave blank when the result is numeric."

### 9.5 PatientAssessment

Units are the whole point here — each numeric field must name its unit so the LLM can convert (e.g. "BP 120 over 80", "temp 37 C"):

- [x] `date_assessment` — add "(DD/MM/YYYY)".
- [x] `height` — → "Height in centimeters (cm)."
- [x] `weight` — → "Weight in kilograms (kg)."
- [x] `systolic_blood_pressure` / `diastolic_blood_pressure` — → "Systolic / diastolic blood pressure in mmHg (from '120/80', take 120 / 80)."
- [x] `pulse` — → "Heart rate in beats per minute."
- [x] `temperature` — → "Body temperature in degrees Celsius."
- [x] `respiratory_rate` — → "Respiratory rate in breaths per minute."
- [x] `performance_status` — → "Performance status score (ECOG/WHO 0–4)."

### 9.6 PatientReportedOutcome

- [x] `pro_assessment_date` — add "(DD/MM/YYYY)".
- [x] `pro_instrument` — → "Name of the PRO questionnaire (e.g. EORTC QLQ-C30, FACT)."
- [x] `pro_scale` — → "Domain/scale of the instrument the question belongs to."
- [x] `pro_question_id` — → "Question/item number or code from the instrument."
- [x] `pro_question` — → "Text of the question as asked."
- [x] `pro_answer` — → "Patient's answer exactly as recorded."
- [x] `pro_score` — → "Numeric score for the response, if applicable."

## Task 10: Operational tables — scope decision

`BulkDICOMUpload`, `BulkDICOMUploadSession`, `BulkDICOMStudyMatch`, `UnprocessedDICOMStudies`, `TaskRun`, `Notification`, `DICOMStudyProject` are system/ops tables.

- [x] Decision: **do not expand**. They are not part of any extraction response model (confirmed: no `ResponseModelTable` maps them). Existing help text stays; fix only obvious wording if touched.

## Task 11: Verification (after every task)

- [x] `grep -n "Select the\|Enter the\|check for Yes" client_app/models.py` — no UI-verb help text left on extractable fields.
- [x] `grep -n "format:DD/MM/YYYY" client_app/models.py` — phrasing standardized (date format stated, no colon format).
- [x] Re-run schema discovery; spot-check `DatabaseField.help_text` updated for the task's table (e.g. `extractor.DatabaseField.objects.get(clientapp_field_name='patient_id')`).
- [x] Prompt sanity: generate `InstructorExtractionService.build_field_schema_description(...)` and `build_mining_prompt(...)` for a response model covering the touched tables; confirm new text renders and no field line blows up in length (target < ~300 chars/field line).
- [ ] Extraction regression: run one extraction on a `test_data/` document through a model touching the changed tables; review `field_assessments`/confidence deltas vs the previous run (help text changes can shift behavior — this is expected, but watch for new nulls).
- [x] Docs sync: `docs/help_files/*.rst` per-table field descriptions now duplicate the model help text; update any RST row that contradicts the new wording (diagnosis.rst, pathology.rst, lesion.rst at minimum).

## Rollout order

Tasks 7 (Germline — no text at all) and 6.1 (Pathology bugs) first: biggest extraction-quality delta per hour of work. Then 4/5 (Lesion axes — hardest disambiguation), 8 (treatments, most fields per extraction), 1–3, 9, 10 (decision), 11 continuously.
