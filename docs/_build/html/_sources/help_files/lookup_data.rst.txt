Lookup Data
============

This section describes the key fields that reference data from the lookup tables. 


LookupLaterality
----------------

Laterality defines the side of the body where the lesion is located.

This is referenced by the following froms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Diagnosis                         cancer_side
Lesion                            lesion_laterality
Pathology                         tumor_side
RadiationTherapy                  radiotherapy_side
Surgery                           surgery_side
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all lateralities is: https://backend.chavi.ai/api/v1/lookup/laterality/
    The API endpoint to get the details of a specific laterality is: https://backend.chavi.ai/api/v1/lookup/laterality/{code}/

LookupICDCode
--------------

The ICD (International Classification of Diseases) code represents the standardized diagnosis codes for diseases.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Diagnosis                         diagnosis
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all ICD codes is: https://backend.chavi.ai/api/v1/lookup/icd-codes/
    The API endpoint to get the details of a specific ICD code is: https://backend.chavi.ai/api/v1/lookup/icd-codes/{code}/

LookupFMACode
----------------

The FMA (Foundational Model of Anatomy) code represents standardized anatomical site locations.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Diagnosis                         cancer_site
Lesion                            lesion_site
Pathology                         tumor_site
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all FMA codes is: https://backend.chavi.ai/api/v1/lookup/fma-codes/
    The API endpoint to get the details of a specific FMA code is: https://backend.chavi.ai/api/v1/lookup/fma-codes/{code}/

LookupPresentation
---------------------

Defines the type of clinical presentation of cancer.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Diagnosis                         presentation_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all presentations is: https://backend.chavi.ai/api/v1/lookup/presentations/
    The API endpoint to get the details of a specific presentation is: https://backend.chavi.ai/api/v1/lookup/presentations/{code}/

LookupOutcomeType
-----------------

Defines types of outcomes for cancer treatment.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Outcome                           outcome_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all outcome types is: https://backend.chavi.ai/api/v1/lookup/outcome-types/
    The API endpoint to get the details of a specific outcome type is: https://backend.chavi.ai/api/v1/lookup/outcome-types/{code}/

LookupLesionType
----------------

Defines the types or categories of lesions.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Lesion                            lesion_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all lesion types is: https://backend.chavi.ai/api/v1/lookup/lesion-types/
    The API endpoint to get the details of a specific lesion type is: https://backend.chavi.ai/api/v1/lookup/lesion-types/{code}/

LookupResponseType
------------------

Defines how a lesion has responded to treatment.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
LesionResponse                    lesion_response
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all response types is: https://backend.chavi.ai/api/v1/lookup/response-types/
    The API endpoint to get the details of a specific response type is: https://backend.chavi.ai/api/v1/lookup/response-types/{code}/

LookupProtein
----------------

Defines protein names and identifiers.

.. note::
    The API endpoint for this lookup to show the list of all proteins is: https://backend.chavi.ai/api/v1/lookup/proteins/
    The API endpoint to get the details of a specific protein is: https://backend.chavi.ai/api/v1/lookup/proteins/{code}/

LookupGene
-------------

Defines gene names and codes for genomic data.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
GermlineGenomicAlterations        cosmic_gene_name
Cytogenetics                      gene
SomaticGenomicAlterations         cosmic_gene_name
GeneExpressionData                gene
EpigeneticData                    gene
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all genes is: https://backend.chavi.ai/api/v1/lookup/genes/
    The API endpoint to get the details of a specific gene is: https://backend.chavi.ai/api/v1/lookup/genes/{code}/

LookupTreatmentIntent
---------------------

Defines the purpose or goal of a specific treatment.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
OtherTreatment                    treatment_intent
Radiotherapy                      radiotherapy_intent
Surgery                           surgery_intent
SystemicTherapy                   systemic_therapy_intent
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all treatment intents is: https://backend.chavi.ai/api/v1/lookup/treatment-intents/
    The API endpoint to get the details of a specific treatment intent is: https://backend.chavi.ai/api/v1/lookup/treatment-intents/{code}/

LookupTreatmentSequence
------------------------

Defines the sequence in which treatments are administered.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
SystemicTherapy                   systemic_therapy_sequence
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all treatment sequences is: https://backend.chavi.ai/api/v1/lookup/treatment-sequences/
    The API endpoint to get the details of a specific treatment sequence is: https://backend.chavi.ai/api/v1/lookup/treatment-sequences/{code}/

LookupSystemicAgent
--------------------

Defines specific medications or agents used in systemic treatments.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
SystemicTherapySchedule           systemic_therapy_agent
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all systemic agents is: https://backend.chavi.ai/api/v1/lookup/systemic-agents/
    The API endpoint to get the details of a specific systemic agent is: https://backend.chavi.ai/api/v1/lookup/systemic-agents/{code}/

LookupVolumeUnits
-------------------

Defines units for volume measurements.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Lesion                            lesion_volume_unit
LesionResponse                    residual_lesion_volume_unit
RadiotherapyDoseVolumeData        volume_units
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all volume units is: https://backend.chavi.ai/api/v1/lookup/volume-units/
    The API endpoint to get the details of a specific volume unit is: https://backend.chavi.ai/api/v1/lookup/volume-units/{code}/

LookupSizeUnits
---------------

Defines units for size or dimension measurements.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Lesion                            lesion_size_unit
LesionResponse                    residual_lesion_size_unit
Pathology                         tumor_dimesion_unit
Pathology                         closest_margin_distance_unit
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all size units is: https://backend.chavi.ai/api/v1/lookup/size-units/
    The API endpoint to get the details of a specific size unit is: https://backend.chavi.ai/api/v1/lookup/size-units/{code}/

LookupDoseUnits
----------------

Defines units for dose measurements in treatments.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Radiotherapy                      radiation_dose_units
RadiotherapyVolume                radiation_dose_units
RadiotherapyDoseVolumeData        radiation_dose_units
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all dose units is: https://backend.chavi.ai/api/v1/lookup/dose-units/
    The API endpoint to get the details of a specific dose unit is: https://backend.chavi.ai/api/v1/lookup/dose-units/{code}/

LookupLabResultsUnits
---------------------

Defines units for laboratory test results.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
LaboratoryResults                 quantitative_result_unit
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all lab results units is: https://backend.chavi.ai/api/v1/lookup/lab-results-units/
    The API endpoint to get the details of a specific lab results unit is: https://backend.chavi.ai/api/v1/lookup/lab-results-units/{code}/

LookupMassUnits
----------------

Defines units for mass or weight measurements.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
ConcomitantMedications            medication_dose_units
SystemicTherapySchedule           systemic_therapy_dose_units
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all mass units is: https://backend.chavi.ai/api/v1/lookup/mass-units/
    The API endpoint to get the details of a specific mass unit is: https://backend.chavi.ai/api/v1/lookup/mass-units/{code}/

LookupDrugRoute
---------------

Defines methods of drug administration.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
ConcomitantMedications            medication_route
SystemicTherapySchedule           systemic_therapy_agent_route
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all drug routes is: https://backend.chavi.ai/api/v1/lookup/drug-routes/
    The API endpoint to get the details of a specific drug route is: https://backend.chavi.ai/api/v1/lookup/drug-routes/{code}/

LookupCTCAEGrade
----------------

Defines standardized grades for adverse effects according to Common Terminology Criteria for Adverse Events.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
AdverseEffects                    ctcae_grade_lookup
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all CTCAE grades is: https://backend.chavi.ai/api/v1/lookup/ctcae-grades/
    The API endpoint to get the details of a specific CTCAE grade is: https://backend.chavi.ai/api/v1/lookup/ctcae-grades/{code}/

LookupOutcome
----------------

Defines possible patient outcomes.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
PatientOutcome                    patient_status
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all outcomes is: https://backend.chavi.ai/api/v1/lookup/outcomes/
    The API endpoint to get the details of a specific outcome is: https://backend.chavi.ai/api/v1/lookup/outcomes/{code}/

LookupStagingSystem
---------------------

Defines the various systems used for cancer staging.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
StageInformation                  staging_system
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all staging systems is: https://backend.chavi.ai/api/v1/lookup/staging-systems/
    The API endpoint to get the details of a specific staging system is: https://backend.chavi.ai/api/v1/lookup/staging-systems/{code}/

LookupAJCCStagePrefix
---------------------

Defines prefix modifiers for cancer staging according to the American Joint Committee on Cancer.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
StageInformation                  t_stage_prefix
StageInformation                  n_stage_prefix
StageInformation                  m_stage_prefix
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all AJCC stage prefixes is: https://backend.chavi.ai/api/v1/lookup/ajcc-stage-prefixes/
    The API endpoint to get the details of a specific AJCC stage prefix is: https://backend.chavi.ai/api/v1/lookup/ajcc-stage-prefixes/{code}/

LookupAJCCStageSuffix
---------------------

Defines suffix modifiers for cancer staging according to the American Joint Committee on Cancer.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
StageInformation                  t_stage_suffix
StageInformation                  n_stage_suffix
StageInformation                  m_stage_suffix
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all AJCC stage suffixes is: https://backend.chavi.ai/api/v1/lookup/ajcc-stage-suffixes/
    The API endpoint to get the details of a specific AJCC stage suffix is: https://backend.chavi.ai/api/v1/lookup/ajcc-stage-suffixes/{code}/

LookupAJCCTStageDescriptor
----------------------------

Defines T (tumor) stage descriptors according to the American Joint Committee on Cancer.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
StageInformation                  t_stage
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all AJCC T stage descriptors is: https://backend.chavi.ai/api/v1/lookup/ajcc-t-stage-descriptors/
    The API endpoint to get the details of a specific AJCC T stage descriptor is: https://backend.chavi.ai/api/v1/lookup/ajcc-t-stage-descriptors/{code}/

LookupAJCCNStageDescriptor
----------------------------

Defines N (node) stage descriptors according to the American Joint Committee on Cancer.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
StageInformation                  n_stage
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all AJCC N stage descriptors is: https://backend.chavi.ai/api/v1/lookup/ajcc-n-stage-descriptors/
    The API endpoint to get the details of a specific AJCC N stage descriptor is: https://backend.chavi.ai/api/v1/lookup/ajcc-n-stage-descriptors/{code}/

LookupAJCCMStageDescriptor
----------------------------

Defines M (metastasis) stage descriptors according to the American Joint Committee on Cancer.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
StageInformation                  m_stage
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all AJCC M stage descriptors is: https://backend.chavi.ai/api/v1/lookup/ajcc-m-stage-descriptors/
    The API endpoint to get the details of a specific AJCC M stage descriptor is: https://backend.chavi.ai/api/v1/lookup/ajcc-m-stage-descriptors/{code}/

LookupStageDescriptor
---------------------

Defines overall cancer stage descriptors.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
StageInformation                  overall_stage
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all stage descriptors is: https://backend.chavi.ai/api/v1/lookup/stage-descriptors/
    The API endpoint to get the details of a specific stage descriptor is: https://backend.chavi.ai/api/v1/lookup/stage-descriptors/{code}/

LookupDiagnosticModality
------------------------

Defines methods used to diagnose cancer.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Diagnosis                         diagnostic_modality
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all diagnostic modalities is: https://backend.chavi.ai/api/v1/lookup/diagnostic-modalities/
    The API endpoint to get the details of a specific diagnostic modality is: https://backend.chavi.ai/api/v1/lookup/diagnostic-modalities/{code}/

LookupSystemicTherapyType
-------------------------

Defines types of systemic therapies.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
SystemicTherapy                   systemic_therapy_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all systemic therapy types is: https://backend.chavi.ai/api/v1/lookup/systemic-therapy-types/
    The API endpoint to get the details of a specific systemic therapy type is: https://backend.chavi.ai/api/v1/lookup/systemic-therapy-types/{code}/

LookupRadiotherapyVolumeType
----------------------------

Defines types of volumes in radiotherapy.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
RadiotherapyVolume                volume_type
RadiotherapyDoseVolumeData        volume_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all radiotherapy volume types is: https://backend.chavi.ai/api/v1/lookup/radiotherapy-volume-types/
    The API endpoint to get the details of a specific radiotherapy volume type is: https://backend.chavi.ai/api/v1/lookup/radiotherapy-volume-types/{code}/

LookupPathology
---------------

Defines histological classifications of tumors.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Pathology                         histological_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all pathology types is: https://backend.chavi.ai/api/v1/lookup/pathologies/
    The API endpoint to get the details of a specific pathology type is: https://backend.chavi.ai/api/v1/lookup/pathologies/{code}/

LookupGrade
-----------

Defines the degree of differentiation of tumor cells.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Pathology                         histological_grade
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all grades is: https://backend.chavi.ai/api/v1/lookup/grades/
    The API endpoint to get the details of a specific grade is: https://backend.chavi.ai/api/v1/lookup/grades/{code}/

LookupPathologyDescriptors
--------------------------

Defines various pathological features.

This is referenced by the following forms:

================================= ==========================================
Form where this is used           Field where this is used
================================= ==========================================
Pathology                         lymphatic_vascular_invasion
Pathology                         perineural_invasion
Pathology                         dermal_lymphatic_vascular_invasion
Pathology                         necrosis
================================= ==========================================

.. note::
    The API endpoint for this lookup to show the list of all pathology descriptors is: https://backend.chavi.ai/api/v1/lookup/pathology-descriptors/
    The API endpoint to get the details of a specific pathology descriptor is: https://backend.chavi.ai/api/v1/lookup/pathology-descriptors/{code}/

LookupMajorCancerCategory
-------------------------

Defines broad categories of cancer.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Diagnosis                         cancer_system
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all major cancer categories is: https://backend.chavi.ai/api/v1/lookup/major-cancer-categories/
    The API endpoint to get the details of a specific major cancer category is: https://backend.chavi.ai/api/v1/lookup/major-cancer-categories/{code}/

LookupRadiotherapyModality
--------------------------

Defines modalities used in radiotherapy.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Radiotherapy                      radiotherapy_modality
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all radiotherapy modalities is: https://backend.chavi.ai/api/v1/lookup/radiotherapy-modalities/
    The API endpoint to get the details of a specific radiotherapy modality is: https://backend.chavi.ai/api/v1/lookup/radiotherapy-modalities/{code}/

LookupRadiotherapyType
----------------------

Defines types of radiotherapy treatments.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Radiotherapy                      radiotherapy_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all radiotherapy types is: https://backend.chavi.ai/api/v1/lookup/radiotherapy-types/
    The API endpoint to get the details of a specific radiotherapy type is: https://backend.chavi.ai/api/v1/lookup/radiotherapy-types/{code}/

LookupRadiotherapyTechnique
-----------------------------

Defines techniques used to deliver radiation.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Radiotherapy                      radiotherapy_technique
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all radiotherapy techniques is: https://backend.chavi.ai/api/v1/lookup/radiotherapy-techniques/
    The API endpoint to get the details of a specific radiotherapy technique is: https://backend.chavi.ai/api/v1/lookup/radiotherapy-techniques/{code}/

LookupClinicalSignificance
--------------------------

Defines the clinical significance of genetic variants.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
GermlineGenomicAlterations        clinical_significance
SomaticGenomicAlterations         clinical_significance
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all clinical significances is: https://backend.chavi.ai/api/v1/lookup/clinical-significances/
    The API endpoint to get the details of a specific clinical significance is: https://backend.chavi.ai/api/v1/lookup/clinical-significances/{code}/

LookupIHCResult
---------------

Defines results of immunohistochemistry tests.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Immunohistochemistry              ihc_result
Cytogenetics                      cytogenetic_result
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all IHC results is: https://backend.chavi.ai/api/v1/lookup/ihc-results/
    The API endpoint to get the details of a specific IHC result is: https://backend.chavi.ai/api/v1/lookup/ihc-results/{code}/

LookupIHCStainingIntensity
--------------------------

Defines intensity levels of immunohistochemical staining.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Immunohistochemistry              tumor_cell_staining_intensity
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all IHC staining intensities is: https://backend.chavi.ai/api/v1/lookup/ihc-staining-intensities/
    The API endpoint to get the details of a specific IHC staining intensity is: https://backend.chavi.ai/api/v1/lookup/ihc-staining-intensities/{code}/

LookupMarginStatus
------------------

Defines the status of surgical margins.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Pathology                         margin_status
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all margin statuses is: https://backend.chavi.ai/api/v1/lookup/margin-statuses/
    The API endpoint to get the details of a specific margin status is: https://backend.chavi.ai/api/v1/lookup/margin-statuses/{code}/

LookupTreatmentEffect
---------------------

Defines the effect of treatment on tumor cells.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Pathology                         treatment_effect
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all treatment effects is: https://backend.chavi.ai/api/v1/lookup/treatment-effects/
    The API endpoint to get the details of a specific treatment effect is: https://backend.chavi.ai/api/v1/lookup/treatment-effects/{code}/

LookupStagingType
-----------------

Defines types of cancer staging.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
StageInformation                  stage_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all staging types is: https://backend.chavi.ai/api/v1/lookup/staging-systems/
    The API endpoint to get the details of a specific staging type is: https://backend.chavi.ai/api/v1/lookup/staging-systems/{code}/

LookupSystemicTherapyRegimen
----------------------------

Defines specific regimens for systemic therapy.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
SystemicTherapy                   systemic_therapy_regimen
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all systemic therapy regimens is: https://backend.chavi.ai/api/v1/lookup/systemic-therapy-regimens/
    The API endpoint to get the details of a specific systemic therapy regimen is: https://backend.chavi.ai/api/v1/lookup/systemic-therapy-regimens/{code}/

LookupRTLocation
-----------------

Defines anatomical locations included in radiotherapy treatment volumes.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
RadiotherapyVolume                anatomical_locations
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all RT locations is: https://backend.chavi.ai/api/v1/lookup/rt-locations/
    The API endpoint to get the details of a specific RT location is: https://backend.chavi.ai/api/v1/lookup/rt-locations/{code}/

LookupLaboratoryTest
----------------------

Defines types of laboratory tests.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
LaboratoryResults                 laboratory_test
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all laboratory tests is: https://backend.chavi.ai/api/v1/lookup/laboratory-tests/
    The API endpoint to get the details of a specific laboratory test is: https://backend.chavi.ai/api/v1/lookup/laboratory-tests/{code}/

LookupSymptoms
--------------

Defines types of symptoms.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Symptom                           symptom
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all symptoms is: https://backend.chavi.ai/api/v1/lookup/symptoms/
    The API endpoint to get the details of a specific symptom is: https://backend.chavi.ai/api/v1/lookup/symptoms/{code}/

LookupSeverity
---------------

Defines levels of symptom severity.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Symptom                           severity
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all severity levels is: https://backend.chavi.ai/api/v1/lookup/severities/
    The API endpoint to get the details of a specific severity level is: https://backend.chavi.ai/api/v1/lookup/severities/{code}/

LookupIHCAntibody
------------------

Defines antibodies used in immunohistochemistry tests.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Immunohistochemistry              protein_name
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all IHC antibodies is: https://backend.chavi.ai/api/v1/lookup/ihc-antibodies/
    The API endpoint to get the details of a specific IHC antibody is: https://backend.chavi.ai/api/v1/lookup/ihc-antibodies/{code}/

LookupComorbidity
--------------------

Defines types of comorbidities.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Comorbidity                       comorbidity_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all comorbidities is: https://backend.chavi.ai/api/v1/lookup/comorbidities/
    The API endpoint to get the details of a specific comorbidity is: https://backend.chavi.ai/api/v1/lookup/comorbidities/{code}/

LookupPerformanceStatus
------------------------

Defines scales for assessing patient functional status.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
PatientAssessment                 performance_status
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all performance statuses is: https://backend.chavi.ai/api/v1/lookup/performance-statuses/
    The API endpoint to get the details of a specific performance status is: https://backend.chavi.ai/api/v1/lookup/performance-statuses/{code}/

LookupExpressionUnits
-----------------------

Defines units for gene expression data.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
GeneExpressionData                expression_units
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all expression units is: https://backend.chavi.ai/api/v1/lookup/expression-units/
    The API endpoint to get the details of a specific expression unit is: https://backend.chavi.ai/api/v1/lookup/expression-units/{code}/

LookupCytogeneticAbnormality
----------------------------

Defines types of cytogenetic abnormalities.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Cytogenetics                      cytogentic_abnormality
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all cytogenetic abnormalities is: https://backend.chavi.ai/api/v1/lookup/cytogenetic-abnormalities/
    The API endpoint to get the details of a specific cytogenetic abnormality is: https://backend.chavi.ai/api/v1/lookup/cytogenetic-abnormalities/{code}/

LookupEpigeneticAbnormalityType
-------------------------------

Defines types of epigenetic abnormalities.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
EpigeneticData                    epigenetic_abnormality_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all epigenetic abnormality types is: https://backend.chavi.ai/api/v1/lookup/epigenetic-abnormality-types/
    The API endpoint to get the details of a specific epigenetic abnormality type is: https://backend.chavi.ai/api/v1/lookup/epigenetic-abnormality-types/{code}/

LookupSurgicalProcedures
------------------------

Defines types of surgical procedures.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Surgery                           surgery_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all surgical procedures is: https://backend.chavi.ai/api/v1/lookup/surgical-procedures/
    The API endpoint to get the details of a specific surgical procedure is: https://backend.chavi.ai/api/v1/lookup/surgical-procedures/{code}/

LookupNodalAssessmentType
-------------------------

Defines types of nodal assessment procedures.

This is referenced by the following forms:

================================= ================================
Form where this is used           Field where this is used
================================= ================================
Surgery                           nodal_assessment_type
================================= ================================

.. note::
    The API endpoint for this lookup to show the list of all nodal assessment types is: https://backend.chavi.ai/api/v1/lookup/nodal-assessment-types/
    The API endpoint to get the details of a specific nodal assessment type is: https://backend.chavi.ai/api/v1/lookup/nodal-assessment-types/{code}/









