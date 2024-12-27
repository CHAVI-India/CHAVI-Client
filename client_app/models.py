from django.db import models
import uuid

# Lookup Models

class LookupLaterality(models.Model):
    icd_laterality_code = models.CharField(max_length=20)
    side_description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.side_description

class LookupICDCode(models.Model):
    icd_version = models.DecimalField(max_digits=5, decimal_places=2)
    icd_code = models.CharField(max_length=255)
    icd_description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.icd_code} - {self.icd_description}"

class LookupFMACode(models.Model):
    fmaid = models.DecimalField(max_digits=10, decimal_places=2)
    label = models.CharField(max_length=255)
    preferred_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.preferred_name

class LookupPresentation(models.Model):
    presentation_type = models.CharField(max_length=255)

    def __str__(self):
        return self.presentation_type

class LookupOutcomeType(models.Model):
    outcome_type = models.CharField(max_length=255)

    def __str__(self):
        return self.outcome_type

class LookupLesionType(models.Model):
    lesion_location_type = models.CharField(max_length=255)

    def __str__(self):
        return self.lesion_location_type

class LookupResponseType(models.Model):
    response_type = models.CharField(max_length=255)
    response_measurement_criteria = models.CharField(max_length=255)

    def __str__(self):
        return self.response_type

class LookupUniProt(models.Model):
    protein_name = models.CharField(max_length=500)
    uniprot_id = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.protein_name

class LookupCosmic(models.Model):
    cosmic_gene_id = models.CharField(max_length=255, unique=True)
    cosmic_gene_name = models.CharField(max_length=500)

    def __str__(self):
        return self.cosmic_gene_name

class LookupTreatmentIntent(models.Model):
    treatment_intent = models.CharField(max_length=255)

    def __str__(self):
        return self.treatment_intent

class LookupTreatmentSequence(models.Model):
    treatment_sequence = models.CharField(max_length=255)

    def __str__(self):
        return self.treatment_sequence

class LookupSystemicAgent(models.Model):
    systemic_agent_name = models.CharField(max_length=255)
    systemic_agent_type = models.CharField(max_length=255)

    def __str__(self):
        return self.systemic_agent_name

class LookupDoseUnits(models.Model):
    unit = models.CharField(max_length=255)
    unit_abbreviation = models.CharField(max_length=255)

    def __str__(self):
        return self.unit_abbreviation

class LookupDrugRoute(models.Model):
    route = models.CharField(max_length=255)

    def __str__(self):
        return self.route

class LookupCTCAEGrade(models.Model):
    ctcae_id = models.CharField(max_length=255, unique=True)
    ctcae_term = models.CharField(max_length=255)
    definition = models.TextField()
    meddra_code = models.CharField(max_length=255)
    meddra_soc = models.CharField(max_length=255)
    ctcae_grade = models.BigIntegerField()
    ctcae_grade_description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('ctcae_term', 'ctcae_grade')

class LookupOutcome(models.Model):
    outcome = models.CharField(max_length=255)

    def __str__(self):
        return self.outcome

class LookupStagingSystem(models.Model):
    staging_system = models.CharField(max_length=255)
    staging_system_version = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.staging_system} v{self.staging_system_version}"




# Center Model
class Center(models.Model):
    chavi_center_id = models.CharField(max_length=255, unique=True)
    center_address = models.TextField()
    center_city = models.TextField()
    center_state = models.TextField()
    center_country = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.chavi_center_id

# Core Patient Models
class Patient(models.Model):
    center = models.ForeignKey(Center, on_delete=models.PROTECT, related_name='patients')
    patient_id = models.CharField(max_length=255, unique=True)
    gender = models.CharField(max_length=50)
    date_of_birth = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.patient_id

# Project Model
class Project(models.Model):
    chavi_project_id = models.CharField(max_length=255, unique=True)
    start_date = models.DateField()
    completion_date = models.DateField(null=True, blank=True)
    description = models.TextField()
    license = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    patients = models.ManyToManyField(Patient, through='PatientProject',related_name='Projects')

    def __str__(self):
        return self.chavi_project_id



# DICOM Related Models
class DICOMStudy(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    frame_of_reference_uid = models.CharField(max_length=255)
    sop_instance_uid = models.CharField(max_length=255, unique=True)
    modality = models.CharField(max_length=50)
    study_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.sop_instance_uid

class DICOMSeries(models.Model):
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    sop_instance_uid = models.CharField(max_length=255, unique=True)
    frame_of_reference_uid = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class DICOMStudyFiles(models.Model):
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    file_name = models.TextField()
    upload_timestamp = models.DateTimeField(auto_now_add=True)
    number_of_files = models.IntegerField()
    file_size = models.DecimalField(max_digits=10, decimal_places=2)


# Clinical Data Models

class Diagnosis(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(LookupICDCode, on_delete=models.PROTECT)
    diagnosis_date = models.DateField()
    presentation_type = models.ForeignKey(LookupPresentation, on_delete=models.PROTECT)
    cancer_site = models.ForeignKey(LookupFMACode, on_delete=models.PROTECT)
    cancer_side = models.ForeignKey(LookupLaterality, on_delete=models.PROTECT)
    diagnostic_modality = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient.patient_id} - {self.diagnosis_date}"

class Outcome(models.Model):
    chavi_outcome_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE)
    date_outcome_assessed = models.DateField()
    outcome_type = models.ForeignKey(LookupOutcomeType, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Lesion(models.Model):
    chavi_lesion_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE)
    date_lesion_assessed = models.DateField()
    lesion_site = models.ForeignKey(LookupFMACode, on_delete=models.CASCADE)
    lesion_type = models.ForeignKey(LookupLesionType, on_delete=models.CASCADE)
    lesion_laterality = models.ForeignKey(LookupLaterality, on_delete=models.CASCADE)
    lesion_size_x_axis = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    lesion_size_y_axis = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    lesion_size_z_axis = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    lesion_volume = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class LesionResponse(models.Model):
    chavi_lesion_response_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesion = models.ForeignKey(Lesion, on_delete=models.CASCADE)
    lesion_response_date = models.DateField()
    lesion_response = models.ForeignKey(LookupResponseType, on_delete=models.CASCADE)
    residual_lesion_size_x_axis = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    residual_lesion_size_y_axis = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    residual_lesion_size_z_axis = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    residual_lesion_volume = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Pathology(models.Model):
    chavi_pathology_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE)
    date_pathology = models.DateField()
    specimen_type = models.CharField(max_length=255)
    tumor_site = models.ForeignKey(LookupFMACode, on_delete=models.CASCADE)
    tumor_side = models.ForeignKey(LookupLaterality, on_delete=models.CASCADE)
    histological_type = models.CharField(max_length=255)
    histological_subtype = models.CharField(max_length=255)
    histological_grade = models.CharField(max_length=50)
    histological_grading_schema = models.CharField(max_length=255)
    greatest_tumor_size = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    greatest_dimension_of_tumor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    additional_tumor_dimension_1 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    additional_tumor_dimension_2 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tumor_focality = models.CharField(max_length=50)
    lymphatic_vascular_invasion = models.CharField(max_length=255)
    perineural_invasion = models.CharField(max_length=255)
    dermal_lymphatic_vascular_invasion = models.CharField(max_length=255)
    count_lymph_nodes_in_specimen = models.BigIntegerField(null=True, blank=True)
    count_lymph_nodes_uninvolved = models.BigIntegerField(null=True, blank=True)
    count_lymph_nodes_macroscopic = models.BigIntegerField(null=True, blank=True)
    count_lymph_nodes_micrometastasis = models.BigIntegerField(null=True, blank=True)
    count_lymph_node_isolated_tumor_cells = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Immunohistochemistry(models.Model):
    chavi_ihc_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pathology = models.ForeignKey(Pathology, on_delete=models.CASCADE)
    date_ihc = models.DateField()
    protein_name = models.ForeignKey(LookupUniProt, on_delete=models.CASCADE)
    ihc_result = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Cytogenetics(models.Model):
    chavi_cytogenetics_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pathology = models.ForeignKey(Pathology, on_delete=models.CASCADE)
    date_cytogenetics = models.DateField()
    gene = models.ForeignKey(LookupCosmic, on_delete=models.CASCADE)
    cytogenetic_result = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class SomaticGenomicAlterations(models.Model):
    chavi_somatic_genomic_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pathology = models.ForeignKey(Pathology, on_delete=models.CASCADE)
    date_test = models.DateField()
    cosmic_gene_name = models.ForeignKey(LookupCosmic, on_delete=models.CASCADE)
    reference_sequence = models.CharField(max_length=255)
    protein_modification = models.CharField(max_length=255)
    variant_type = models.CharField(max_length=50)
    allele_frequency = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    read_depth = models.IntegerField(null=True, blank=True)
    clinical_significance = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Treatment(models.Model):
    chavi_treatment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE)
    treatment_start_date = models.DateField()
    treatment_end_date = models.DateField(null=True, blank=True)
    treatment_sequence = models.ForeignKey(LookupTreatmentSequence, on_delete=models.CASCADE)
    treatment_intent = models.ForeignKey(LookupTreatmentIntent, on_delete=models.CASCADE)
    treatment = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Radiotherapy(models.Model):
    chavi_radiotherapy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    treatment = models.ForeignKey('Treatment', on_delete=models.CASCADE)
    radiotherapy_modality = models.CharField(max_length=255)
    total_dose = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_fractions = models.BigIntegerField(null=True, blank=True)
    radiotherapy_type = models.CharField(max_length=255)
    radiotherapy_sequence = models.ForeignKey('LookupTreatmentSequence', on_delete=models.PROTECT)
    radiotherapy_technique = models.CharField(max_length=255)
    fractions_per_day = models.BigIntegerField(null=True, blank=True)
    radiotherapy_site = models.ForeignKey('LookupFMACode', on_delete=models.PROTECT)
    radiotherapy_side = models.ForeignKey('LookupLaterality', on_delete=models.PROTECT)
    treatment_volume = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Surgery(models.Model):
    chavi_surgery_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    treatment = models.ForeignKey(Treatment, on_delete=models.CASCADE)
    surgery_date = models.DateField()
    surgery_site = models.ForeignKey(LookupFMACode, on_delete=models.CASCADE)
    surgery_type = models.CharField(max_length=255)
    nodal_dissection = models.BooleanField()
    type_nodal_dissection = models.CharField(max_length=255)
    reconstruction = models.BooleanField()
    type_reconstruction = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class ConcomitantMedications(models.Model):
    chavi_medication_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    treatment = models.ForeignKey(Treatment, on_delete=models.CASCADE)
    medication_name = models.CharField(max_length=255)
    medication_dose = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    date_medication_start_date = models.DateField()
    date_medication_end_date = models.DateField(null=True, blank=True)
    medication_route = models.ForeignKey(LookupDrugRoute, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class SystemicTherapy(models.Model):
    chavi_systemic_therapy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    treatment = models.ForeignKey(Treatment, on_delete=models.CASCADE)
    type_systemic_therapy = models.CharField(max_length=255)
    systemic_therapy_sequence = models.ForeignKey(LookupTreatmentSequence, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class SystemicTherapySchedule(models.Model):
    chavi_systemic_therapy_schedule_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    systemic_therapy = models.ForeignKey('SystemicTherapy', on_delete=models.CASCADE)
    systemic_therapy_agent_route = models.ForeignKey('LookupDrugRoute', on_delete=models.PROTECT)
    systemic_therapy_agent_start_date = models.DateField()
    systemic_therapy_agent_end_date = models.DateField(null=True, blank=True)
    systemic_therapy_agent = models.ForeignKey('LookupSystemicAgent', on_delete=models.PROTECT)
    systemic_therapy_dose_planned = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    systemic_therapy_dose_administered = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    systemic_therapy_dose_units = models.ForeignKey('LookupDoseUnits', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class AdverseEffects(models.Model):
    chavi_adverse_effects_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey('Diagnosis', on_delete=models.CASCADE)
    treatment = models.ForeignKey('Treatment', on_delete=models.CASCADE, null=True, blank=True)
    ctcae_grade = models.ForeignKey('LookupCTCAEGrade', on_delete=models.PROTECT, null=True, blank=True)
    adverse_effect_type = models.CharField(max_length=255)
    adverse_effect_grade = models.BigIntegerField()
    adverse_effect_start_date = models.DateField()
    adverse_effect_end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('adverse_effect_type', 'adverse_effect_grade')

class ProInstrument(models.Model):
    pro_instrument = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.pro_instrument

class ProDomain(models.Model):
    instrument = models.ForeignKey(ProInstrument, on_delete=models.CASCADE)
    pro_domain = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('instrument', 'pro_domain')]

    def __str__(self):
        return f"{self.instrument.pro_instrument} - {self.pro_domain}"

class ProQuestion(models.Model):
    domain = models.ForeignKey(ProDomain, on_delete=models.CASCADE)
    pro_question = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('domain', 'pro_question')]

class PatientReportedOutcome(models.Model):
    chavi_pro_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    instrument = models.ForeignKey(ProInstrument, on_delete=models.CASCADE)
    domain = models.ForeignKey(ProDomain, on_delete=models.CASCADE)
    question = models.ForeignKey(ProQuestion, on_delete=models.CASCADE)
    pro_date = models.DateField()
    pro_answer = models.TextField()
    pro_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class PatientOutcome(models.Model):
    chavi_pt_outcome_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE)
    patient_status = models.ForeignKey('LookupOutcome', on_delete=models.PROTECT)
    date_of_death = models.DateField(null=True, blank=True)
    primary_cause_of_death = models.ForeignKey('LookupICDCode', on_delete=models.PROTECT, 
                                             related_name='primary_cause', null=True, blank=True)
    secondary_cause_of_death = models.ForeignKey('LookupICDCode', on_delete=models.PROTECT,
                                               related_name='secondary_cause', null=True, blank=True)
    tertiary_cause_of_death = models.ForeignKey('LookupICDCode', on_delete=models.PROTECT,
                                              related_name='tertiary_cause', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Comorbidity(models.Model):
    chavi_comorbidity_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    comorbidity_type = models.ForeignKey(LookupICDCode, on_delete=models.CASCADE)
    date_of_comorbidity_diagnosis = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class StageInformation(models.Model):
    chavi_stage_information_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey('Diagnosis', on_delete=models.CASCADE)
    staging_system = models.ForeignKey('LookupStagingSystem', on_delete=models.PROTECT)
    stage_type = models.CharField(max_length=255)
    t_stage_prefix = models.CharField(max_length=255, null=True, blank=True)
    t_stage = models.CharField(max_length=255)
    t_stage_suffix = models.CharField(max_length=255, null=True, blank=True)
    n_stage_prefix = models.CharField(max_length=255, null=True, blank=True)
    n_stage = models.CharField(max_length=255)
    n_stage_suffix = models.CharField(max_length=255, null=True, blank=True)
    m_stage_prefix = models.CharField(max_length=255, null=True, blank=True)
    m_stage_suffix = models.CharField(max_length=255)
    overall_stage = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

# Junction Tables
class PatientProject(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('patient', 'project')

class DiagnosisDICOMStudy(models.Model):
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE)
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('diagnosis', 'dicom_study')

class LesionDICOMStudy(models.Model):
    lesion = models.ForeignKey(Lesion, on_delete=models.CASCADE)
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('lesion', 'dicom_study')

class LesionResponseDICOMStudy(models.Model):
    lesion_response = models.ForeignKey(LesionResponse, on_delete=models.CASCADE)
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('lesion_response', 'dicom_study')

class DiagnosisProject(models.Model):
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('diagnosis', 'project')

class DICOMStudyProject(models.Model):
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('dicom_study', 'project')

class RadiotherapyDICOMStudy(models.Model):
    radiotherapy = models.ForeignKey(Radiotherapy, on_delete=models.CASCADE)
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('radiotherapy', 'dicom_study')

class OutcomeDICOMStudy(models.Model):
    outcome = models.ForeignKey(Outcome, on_delete=models.CASCADE)
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('outcome', 'dicom_study')





