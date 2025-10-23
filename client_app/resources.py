"""
Django Import-Export Resources for CHAVI Client Application

This module provides import resources for importing clinical data from CSV files
exported from statistical packages. It handles:
- Patient, Diagnosis, and downstream models
- UUID-based relationships for downstream models
- Repeated data (e.g., multiple pathologies/treatments per patient)
- Lookup model relationships
- Skipping rows where required downstream model PKs are not available
"""

from import_export import resources, fields, widgets
from import_export.instance_loaders import ModelInstanceLoader
from django.core.exceptions import ObjectDoesNotExist
import uuid
from decimal import Decimal
from datetime import datetime

from .models import (
    Patient, Diagnosis, Pathology, Immunohistochemistry, Cytogenetics,
    SomaticGenomicAlterations, GeneExpressionData, EpigeneticData,
    Radiotherapy, RadiotherapyVolume, Surgery, SystemicTherapy, 
    SystemicTherapySchedule, OtherTreatment, Lesion, LesionResponse,
    Outcome, StageInformation, AdverseEffects, Comorbidity, Symptom,
    GermlineGenomicAlterations, ConcomitantMedications, PatientOutcome,
    PatientReportedOutcome, LaboratoryResults, PatientAssessment,
    SiteConfiguration, StudyTypeChoices, ModalityChoices, 
    TumorFocalityChoices, SpecimenTypeChoices, RadiationCourseTypeChoices,
    QualitativeLaboratoryResult
)

from lookup.models import (
    LookupLaterality, LookupICDCode, LookupFMACode, LookupPresentation,
    LookupMajorCancerCategory, LookupDiagnosticModality, LookupPathology,
    LookupGrade, LookupPathologyDescriptors, LookupSizeUnits, LookupVolumeUnits,
    LookupDoseUnits, LookupMarginStatus, LookupTreatmentEffect, LookupIHCAntibody,
    LookupIHCResult, LookupIHCStainingIntensity, LookupGene, LookupCytogeneticAbnormality,
    LookupClinicalSignificance, LookupExpressionUnits, LookupEpigeneticAbnormalityType,
    LookupTreatmentIntent, LookupRadiotherapyModality, LookupRadiotherapyType,
    LookupRadiotherapyTechnique, LookupRadiotherapyVolumeType, LookupRTLocation,
    LookupNodalAssessmentType, LookupSurgicalProcedures, LookupSystemicTherapyType,
    LookupSystemicTherapyRegimen, LookupSystemicAgent, LookupTreatmentSequence,
    LookupDrugRoute, LookupMassUnits, LookupOutcomeType, LookupLesionType,
    LookupResponseType, LookupStagingSystem, LookupStagingType, LookupAJCCStagePrefix,
    LookupAJCCStageSuffix, LookupAJCCTStageDescriptor, LookupAJCCNStageDescriptor,
    LookupAJCCMStageDescriptor, LookupStageDescriptor, LookupCTCAEGrade,
    LookupComorbidity, LookupSymptoms, LookupSeverity, LookupOutcome,
    LookupPerformanceStatus, LookupLaboratoryTest, LookupLabResultsUnits
)


# Comprehensive Combined Resource for importing all data from a single CSV
class UnifiedClinicalDataResource(resources.ModelResource):
    """
    UNIFIED IMPORT RESOURCE - Import ALL clinical data from a SINGLE CSV file
    
    This resource handles importing Patient, Diagnosis, and ALL downstream models
    from one CSV file. Each row can contain data for multiple models simultaneously.
    
    USAGE:
    This resource is registered in admin.py as part of PatientAdmin.resource_classes.
    When importing via Django admin, select "Unified Clinical Data Resource" from the dropdown.
    
    HOW IT WORKS:
    1. Each row must have a patient_id
    2. If diagnosis fields are present, chavi_diagnosis_id MUST be provided (creates/updates Diagnosis)
    3. If downstream model fields are present, their UUIDs MUST be provided (creates/updates those models)
    4. Handles repeated data: multiple rows for same patient with different downstream UUIDs
    5. UUIDs must be explicitly provided to prevent duplicate records on re-import
    
    CSV STRUCTURE:
    - One row can have: Patient + Diagnosis + Pathology + Radiotherapy + Surgery + SystemicTherapy + etc.
    - Multiple rows for same patient: different UUIDs for repeated data (multiple pathologies, treatments)
    
    EXAMPLE - Single row with multiple models:
    patient_id,gender,chavi_diagnosis_id,cancer_system,chavi_pathology_id,specimen_type,chavi_radiotherapy_id,total_dose
    P001,Female,diag-uuid-1,BREAST,path-uuid-1,Core Biopsy,rt-uuid-1,50.00
    
    EXAMPLE - Multiple rows for repeated data:
    patient_id,gender,chavi_diagnosis_id,cancer_system,chavi_pathology_id,specimen_type
    P001,Female,diag-uuid-1,BREAST,path-uuid-1,Core Biopsy
    P001,Female,diag-uuid-1,BREAST,path-uuid-2,Surgical Resection
    
    This creates: 1 Patient, 1 Diagnosis, 2 Pathologies
    """
    
    # This is a special resource that doesn't map to a single model
    # It orchestrates imports across multiple models
    
    class Meta:
        model = Patient  # Base model for the resource
        import_id_fields = ('patient_id',)
        skip_unchanged = False  # Always process to check downstream models
        report_skipped = True
    
    def before_import_row(self, row, **kwargs):
        """Validate that required UUIDs are provided"""
        if not row.get('patient_id'):
            raise ValueError("patient_id is required")
        
        # Validate that UUIDs are provided when downstream model data is present
        
        # Diagnosis
        if any(row.get(f) for f in ['cancer_system', 'diagnosis_code', 'diagnosis_date']) and not row.get('chavi_diagnosis_id'):
            raise ValueError("chavi_diagnosis_id is required when diagnosis data is provided")
        
        # Pathology
        if any(row.get(f) for f in ['date_pathology', 'specimen_type', 'tumor_site']) and not row.get('chavi_pathology_id'):
            raise ValueError("chavi_pathology_id is required when pathology data is provided")
        
        # Radiotherapy
        if any(row.get(f) for f in ['radiotherapy_course_type', 'total_dose']) and not row.get('chavi_radiotherapy_id'):
            raise ValueError("chavi_radiotherapy_id is required when radiotherapy data is provided")
        
        # Surgery
        if any(row.get(f) for f in ['surgery_date', 'surgery_side']) and not row.get('chavi_surgery_id'):
            raise ValueError("chavi_surgery_id is required when surgery data is provided")
        
        # Systemic Therapy
        if any(row.get(f) for f in ['systemic_therapy_type', 'systemic_therapy_regimen']) and not row.get('chavi_systemic_therapy_id'):
            raise ValueError("chavi_systemic_therapy_id is required when systemic therapy data is provided")
        
        # Outcome
        if any(row.get(f) for f in ['date_outcome_assessed', 'outcome_type']) and not row.get('chavi_outcome_id'):
            raise ValueError("chavi_outcome_id is required when outcome data is provided")
        
        # Lesion
        if any(row.get(f) for f in ['date_lesion_assessed', 'lesion_site', 'lesion_type']) and not row.get('chavi_lesion_id'):
            raise ValueError("chavi_lesion_id is required when lesion data is provided")
        
        # Stage Information
        if any(row.get(f) for f in ['staging_system', 't_stage', 'n_stage', 'm_stage', 'overall_stage']) and not row.get('chavi_stage_information_id'):
            raise ValueError("chavi_stage_information_id is required when stage information data is provided")
        
        # Adverse Effects
        if any(row.get(f) for f in ['ctcae_grade_lookup', 'adverse_effect_start_date']) and not row.get('chavi_adverse_effects_id'):
            raise ValueError("chavi_adverse_effects_id is required when adverse effects data is provided")
        
        # Other Treatment
        if any(row.get(f) for f in ['treatment', 'treatment_start_date']) and not row.get('chavi_treatment_id'):
            raise ValueError("chavi_treatment_id is required when other treatment data is provided")
        
        # Comorbidity
        if any(row.get(f) for f in ['comorbidity_type', 'date_of_comorbidity_assessment']) and not row.get('chavi_comorbidity_id'):
            raise ValueError("chavi_comorbidity_id is required when comorbidity data is provided")
        
        # Symptom
        if any(row.get(f) for f in ['symptom', 'date_symptom_assessment']) and not row.get('chavi_symptom_id'):
            raise ValueError("chavi_symptom_id is required when symptom data is provided")
        
        # Patient Outcome
        if any(row.get(f) for f in ['patient_status', 'date_of_death', 'last_date_of_follow_up']) and not row.get('chavi_patient_outcome_id'):
            raise ValueError("chavi_patient_outcome_id is required when patient outcome data is provided")
        
        # Laboratory Results
        if any(row.get(f) for f in ['laboratory_test', 'result_date']) and not row.get('chavi_laboratory_result_id'):
            raise ValueError("chavi_laboratory_result_id is required when laboratory result data is provided")
        
        # Patient Assessment
        if any(row.get(f) for f in ['date_assessment', 'height', 'weight']) and not row.get('chavi_patient_assessment_id'):
            raise ValueError("chavi_patient_assessment_id is required when patient assessment data is provided")
        
        # Immunohistochemistry (linked to Pathology)
        if any(row.get(f) for f in ['protein_name', 'ihc_result', 'date_ihc']) and not row.get('chavi_ihc_id'):
            raise ValueError("chavi_ihc_id is required when immunohistochemistry data is provided")
        
        # Cytogenetics (linked to Pathology)
        if any(row.get(f) for f in ['gene', 'cytogenetic_abnormality', 'date_cytogenetics']) and not row.get('chavi_cytogenetics_id'):
            raise ValueError("chavi_cytogenetics_id is required when cytogenetics data is provided")
        
        # Somatic Genomic Alterations (linked to Pathology)
        if any(row.get(f) for f in ['cosmic_gene_name', 'variant_type', 'date_test']) and not row.get('chavi_somatic_genomic_id'):
            raise ValueError("chavi_somatic_genomic_id is required when somatic genomic alterations data is provided")
        
        # Gene Expression Data (linked to Pathology)
        if any(row.get(f) for f in ['gene_expression_gene', 'expression_value']) and not row.get('chavi_gene_expression_id'):
            raise ValueError("chavi_gene_expression_id is required when gene expression data is provided")
        
        # Epigenetic Data (linked to Pathology)
        if any(row.get(f) for f in ['epigenetic_gene', 'epigenetic_abnormality_type']) and not row.get('chavi_epigenetic_id'):
            raise ValueError("chavi_epigenetic_id is required when epigenetic data is provided")
        
        # Lesion Response (linked to Lesion)
        if any(row.get(f) for f in ['lesion_response', 'lesion_response_date']) and not row.get('chavi_lesion_response_id'):
            raise ValueError("chavi_lesion_response_id is required when lesion response data is provided")
        
        # Germline Genomic Alterations (linked to Patient)
        if any(row.get(f) for f in ['germline_gene', 'germline_variant']) and not row.get('chavi_germline_genomic_id'):
            raise ValueError("chavi_germline_genomic_id is required when germline genomic alterations data is provided")
        
        # Radiotherapy Volume (linked to Radiotherapy)
        if any(row.get(f) for f in ['volume_name', 'volume_type', 'volume_dose_prescribed']) and not row.get('radiotherapy_volume_id'):
            raise ValueError("radiotherapy_volume_id is required when radiotherapy volume data is provided")
        
        # Concomitant Medications (linked to Diagnosis)
        if any(row.get(f) for f in ['concomitant_medication_name', 'concomitant_medication_start_date']) and not row.get('chavi_concomitant_medication_id'):
            raise ValueError("chavi_concomitant_medication_id is required when concomitant medications data is provided")
        
        # Systemic Therapy Schedule (linked to Systemic Therapy)
        if any(row.get(f) for f in ['systemic_therapy_agent', 'systemic_therapy_agent_start_date']) and not row.get('chavi_systemic_therapy_schedule_id'):
            raise ValueError("chavi_systemic_therapy_schedule_id is required when systemic therapy schedule data is provided")
        
        # Patient Reported Outcome (linked to Patient)
        if any(row.get(f) for f in ['pro_date', 'pro_score']) and not row.get('chavi_pro_id'):
            raise ValueError("chavi_pro_id is required when patient reported outcome data is provided")
    
    def import_row(self, row, instance_loader, **kwargs):
        """
        Custom import logic to handle multiple models from a single row
        """
        # Import Patient first
        patient_id = row.get('patient_id')
        if not patient_id:
            return
        
        # Get or create Patient
        patient, created = Patient.objects.get_or_create(
            patient_id=patient_id,
            defaults={
                'gender': self._get_choice_value(Patient.Gender, row.get('gender')),
                'date_of_birth': self._parse_date(row.get('date_of_birth')),
                'date_of_registration': self._parse_date(row.get('date_of_registration')),
                'chavi_consent': self._parse_boolean(row.get('chavi_consent')),
                'date_chavi_consent': self._parse_date(row.get('date_chavi_consent')),
            }
        )
        
        # Update patient if not created and data provided
        if not created:
            if row.get('gender'):
                patient.gender = self._get_choice_value(Patient.Gender, row.get('gender'))
            if row.get('date_of_birth'):
                patient.date_of_birth = self._parse_date(row.get('date_of_birth'))
            if row.get('date_of_registration'):
                patient.date_of_registration = self._parse_date(row.get('date_of_registration'))
            if row.get('chavi_consent') is not None:
                patient.chavi_consent = self._parse_boolean(row.get('chavi_consent'))
            if row.get('date_chavi_consent'):
                patient.date_chavi_consent = self._parse_date(row.get('date_chavi_consent'))
            patient.save()
        
        # Import Diagnosis if data present
        diagnosis = None
        if row.get('chavi_diagnosis_id'):
            diagnosis = self._import_diagnosis(row, patient)
        
        # Import downstream models if diagnosis exists
        if diagnosis:
            # Pathology and its sub-models
            pathology = None
            if row.get('chavi_pathology_id'):
                pathology = self._import_pathology(row, diagnosis)
            
            # Pathology-linked models
            if pathology:
                if row.get('chavi_ihc_id'):
                    self._import_immunohistochemistry(row, pathology)
                
                if row.get('chavi_cytogenetics_id'):
                    self._import_cytogenetics(row, pathology)
                
                if row.get('chavi_somatic_genomic_id'):
                    self._import_somatic_genomic_alterations(row, pathology)
                
                if row.get('chavi_gene_expression_id'):
                    self._import_gene_expression_data(row, pathology)
                
                if row.get('chavi_epigenetic_id'):
                    self._import_epigenetic_data(row, pathology)
            
            # Radiotherapy and its sub-models
            radiotherapy = None
            if row.get('chavi_radiotherapy_id'):
                radiotherapy = self._import_radiotherapy(row, diagnosis)
            
            if radiotherapy and row.get('radiotherapy_volume_id'):
                self._import_radiotherapy_volume(row, radiotherapy)
            
            # Surgery
            if row.get('chavi_surgery_id'):
                self._import_surgery(row, diagnosis)
            
            # Systemic Therapy and its sub-models
            systemic_therapy = None
            if row.get('chavi_systemic_therapy_id'):
                systemic_therapy = self._import_systemic_therapy(row, diagnosis)
            
            if systemic_therapy and row.get('chavi_systemic_therapy_schedule_id'):
                self._import_systemic_therapy_schedule(row, systemic_therapy)
            
            # Other diagnosis-linked models
            if row.get('chavi_outcome_id'):
                self._import_outcome(row, diagnosis)
            
            # Lesion and its sub-models
            lesion = None
            if row.get('chavi_lesion_id'):
                lesion = self._import_lesion(row, diagnosis)
            
            if lesion and row.get('chavi_lesion_response_id'):
                self._import_lesion_response(row, lesion)
            
            if row.get('chavi_stage_information_id'):
                self._import_stage_information(row, diagnosis)
            
            if row.get('chavi_adverse_effects_id'):
                self._import_adverse_effects(row, diagnosis)
            
            if row.get('chavi_treatment_id'):
                self._import_other_treatment(row, diagnosis)
            
            if row.get('chavi_concomitant_medication_id'):
                self._import_concomitant_medications(row, diagnosis)
        
        # Import patient-level models
        if row.get('chavi_comorbidity_id'):
            self._import_comorbidity(row, patient)
        
        if row.get('chavi_symptom_id'):
            self._import_symptom(row, patient)
        
        if row.get('chavi_patient_outcome_id'):
            self._import_patient_outcome(row, patient)
        
        if row.get('chavi_laboratory_result_id'):
            self._import_laboratory_result(row, patient)
        
        if row.get('chavi_patient_assessment_id'):
            self._import_patient_assessment(row, patient)
        
        if row.get('chavi_germline_genomic_id'):
            self._import_germline_genomic_alterations(row, patient)
        
        if row.get('chavi_pro_id'):
            self._import_patient_reported_outcome(row, patient)
    
    def _parse_date(self, value):
        """Parse date from various formats"""
        if not value or value == '':
            return None
        
        # Try multiple date formats
        formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%Y']
        for fmt in formats:
            try:
                return datetime.strptime(str(value), fmt).date()
            except (ValueError, TypeError):
                continue
        return None
    
    def _parse_boolean(self, value):
        """Parse boolean values"""
        if value in ('', None):
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            value = value.lower().strip()
            if value in ('true', 't', 'yes', 'y', '1'):
                return True
            elif value in ('false', 'f', 'no', 'n', '0'):
                return False
        return None
    
    def _parse_decimal(self, value):
        """Parse decimal values"""
        if not value or value == '':
            return None
        try:
            return Decimal(str(value))
        except (ValueError, TypeError):
            return None
    
    def _get_lookup(self, model, label):
        """Get lookup model instance by label"""
        if not label:
            return None
        try:
            return model.objects.get(label=label)
        except model.DoesNotExist:
            return None
    
    def _get_choice_value(self, choices_class, value):
        """
        Get the database value for a TextChoices field.
        Accepts both the database value (e.g., 'PRETREATMENT_DIAGNOSTIC_IMAGE') 
        and the human-readable label (e.g., 'Pre-treatment Diagnostic Image').
        
        Args:
            choices_class: The TextChoices class (e.g., StudyTypeChoices)
            value: The value from CSV (can be database value or label)
        
        Returns:
            The database value if found, otherwise the original value
        """
        if not value:
            return None
        
        # First, check if it's already a valid database value
        if hasattr(choices_class, value.upper().replace(' ', '_').replace('-', '_')):
            return value
        
        # Try to find by exact database value match
        for choice in choices_class.choices:
            if choice[0] == value:
                return choice[0]
        
        # Try to find by human-readable label (case-insensitive)
        value_lower = value.lower().strip()
        for choice in choices_class.choices:
            if choice[1].lower() == value_lower:
                return choice[0]
        
        # If not found, return the original value (will fail validation if invalid)
        return value
    
    def _import_diagnosis(self, row, patient):
        """Import or update Diagnosis"""
        diagnosis_id = row.get('chavi_diagnosis_id')
        if not diagnosis_id:
            return None
        
        diagnosis, created = Diagnosis.objects.update_or_create(
            chavi_diagnosis_id=diagnosis_id,
            defaults={
                'patient': patient,
                'cancer_system': self._get_lookup(LookupMajorCancerCategory, row.get('cancer_system')),
                'diagnosis': self._get_lookup(LookupICDCode, row.get('diagnosis_code')),
                'diagnosis_date': self._parse_date(row.get('diagnosis_date')),
                'presentation_type': self._get_lookup(LookupPresentation, row.get('presentation_type')),
                'cancer_site': self._get_lookup(LookupFMACode, row.get('cancer_site')),
                'cancer_side': self._get_lookup(LookupLaterality, row.get('cancer_side')),
                'diagnostic_modality': self._get_lookup(LookupDiagnosticModality, row.get('diagnostic_modality')),
            }
        )
        return diagnosis
    
    def _import_pathology(self, row, diagnosis):
        """Import or update Pathology"""
        pathology_id = row.get('chavi_pathology_id')
        if not pathology_id:
            return None
        
        pathology, created = Pathology.objects.update_or_create(
            chavi_pathology_id=pathology_id,
            defaults={
                'diagnosis': diagnosis,
                'date_pathology': self._parse_date(row.get('date_pathology')),
                'specimen_type': self._get_choice_value(SpecimenTypeChoices, row.get('specimen_type')),
                'tumor_site': self._get_lookup(LookupFMACode, row.get('tumor_site')),
                'tumor_side': self._get_lookup(LookupLaterality, row.get('tumor_side')),
                'histological_type': self._get_lookup(LookupPathology, row.get('histological_type')),
                'histological_grade': self._get_lookup(LookupGrade, row.get('histological_grade')),
                'tumor_focality': self._get_choice_value(TumorFocalityChoices, row.get('tumor_focality')),
                'greatest_dimension_of_tumor': self._parse_decimal(row.get('greatest_dimension_of_tumor')),
                'lymph_nodes_removed': self._parse_boolean(row.get('lymph_nodes_removed')),
                'lymph_nodes_in_specimen': row.get('lymph_nodes_in_specimen'),
                'number_of_nodes_with_macrometastases': row.get('number_of_nodes_with_macrometastases'),
            }
        )
        return pathology
    
    def _import_radiotherapy(self, row, diagnosis):
        """Import or update Radiotherapy"""
        rt_id = row.get('chavi_radiotherapy_id')
        if not rt_id:
            return None
        
        radiotherapy, created = Radiotherapy.objects.update_or_create(
            chavi_radiotherapy_id=rt_id,
            defaults={
                'diagnosis': diagnosis,
                'radiotherapy_course_type': self._get_choice_value(RadiationCourseTypeChoices, row.get('radiotherapy_course_type')),
                'radiotherapy_modality': self._get_lookup(LookupRadiotherapyModality, row.get('radiotherapy_modality')),
                'total_dose': self._parse_decimal(row.get('total_dose')),
                'total_fractions': row.get('total_fractions'),
                'radiotherapy_intent': self._get_lookup(LookupTreatmentIntent, row.get('radiotherapy_intent')),
                'radiotherapy_type': self._get_lookup(LookupRadiotherapyType, row.get('radiotherapy_type')),
                'radiotherapy_technique': self._get_lookup(LookupRadiotherapyTechnique, row.get('radiotherapy_technique')),
                'radiotherapy_side': self._get_lookup(LookupLaterality, row.get('radiotherapy_side')),
                'radiotherapy_start_date': self._parse_date(row.get('radiotherapy_start_date')),
                'radiotherapy_end_date': self._parse_date(row.get('radiotherapy_end_date')),
            }
        )
        return radiotherapy
    
    def _import_surgery(self, row, diagnosis):
        """Import or update Surgery"""
        surgery_id = row.get('chavi_surgery_id')
        if not surgery_id:
            return None
        
        surgery, created = Surgery.objects.update_or_create(
            chavi_surgery_id=surgery_id,
            defaults={
                'diagnosis': diagnosis,
                'surgery_date': self._parse_date(row.get('surgery_date')),
                'surgery_side': self._get_lookup(LookupLaterality, row.get('surgery_side')),
                'surgery_intent': self._get_lookup(LookupTreatmentIntent, row.get('surgery_intent')),
                'nodal_assessment': self._parse_boolean(row.get('nodal_assessment')),
                'nodal_assessment_type': self._get_lookup(LookupNodalAssessmentType, row.get('nodal_assessment_type')),
                'reconstruction': self._parse_boolean(row.get('reconstruction')),
            }
        )
        return surgery
    
    def _import_systemic_therapy(self, row, diagnosis):
        """Import or update Systemic Therapy"""
        st_id = row.get('chavi_systemic_therapy_id')
        if not st_id:
            return None
        
        systemic_therapy, created = SystemicTherapy.objects.update_or_create(
            chavi_systemic_therapy_id=st_id,
            defaults={
                'diagnosis': diagnosis,
                'systemic_therapy_type': self._get_lookup(LookupSystemicTherapyType, row.get('systemic_therapy_type')),
                'systemic_therapy_intent': self._get_lookup(LookupTreatmentIntent, row.get('systemic_therapy_intent')),
                'systemic_therapy_sequence': self._get_lookup(LookupTreatmentSequence, row.get('systemic_therapy_sequence')),
                'systemic_therapy_regimen': self._get_lookup(LookupSystemicTherapyRegimen, row.get('systemic_therapy_regimen')),
                'systemic_therapy_start_date': self._parse_date(row.get('systemic_therapy_start_date')),
                'systemic_therapy_end_date': self._parse_date(row.get('systemic_therapy_end_date')),
                'cycles_delivered': row.get('cycles_delivered'),
            }
        )
        return systemic_therapy
    
    def _import_outcome(self, row, diagnosis):
        """Import or update Outcome"""
        outcome_id = row.get('chavi_outcome_id')
        if not outcome_id:
            return None
        
        outcome, created = Outcome.objects.update_or_create(
            chavi_outcome_id=outcome_id,
            defaults={
                'diagnosis': diagnosis,
                'date_outcome_assessed': self._parse_date(row.get('date_outcome_assessed')),
                'outcome_type': self._get_lookup(LookupOutcomeType, row.get('outcome_type')),
            }
        )
        return outcome
    
    def _import_lesion(self, row, diagnosis):
        """Import or update Lesion"""
        lesion_id = row.get('chavi_lesion_id')
        if not lesion_id:
            return None
        
        lesion, created = Lesion.objects.update_or_create(
            chavi_lesion_id=lesion_id,
            defaults={
                'diagnosis': diagnosis,
                'date_lesion_assessed': self._parse_date(row.get('date_lesion_assessed')),
                'lesion_site': self._get_lookup(LookupFMACode, row.get('lesion_site')),
                'lesion_type': self._get_lookup(LookupLesionType, row.get('lesion_type')),
                'lesion_laterality': self._get_lookup(LookupLaterality, row.get('lesion_laterality')),
                'lesion_detection_modality': self._get_choice_value(ModalityChoices, row.get('lesion_detection_modality')),
                'lesion_size_x_axis': self._parse_decimal(row.get('lesion_size_x_axis')),
                'lesion_size_y_axis': self._parse_decimal(row.get('lesion_size_y_axis')),
                'lesion_size_z_axis': self._parse_decimal(row.get('lesion_size_z_axis')),
            }
        )
        return lesion
    
    def _import_stage_information(self, row, diagnosis):
        """Import or update Stage Information"""
        stage_id = row.get('chavi_stage_information_id')
        if not stage_id:
            return None
        
        stage, created = StageInformation.objects.update_or_create(
            chavi_stage_information_id=stage_id,
            defaults={
                'diagnosis': diagnosis,
                'staging_system': self._get_lookup(LookupStagingSystem, row.get('staging_system')),
                'stage_type': self._get_lookup(LookupStagingType, row.get('stage_type')),
                't_stage': self._get_lookup(LookupAJCCTStageDescriptor, row.get('t_stage')),
                'n_stage': self._get_lookup(LookupAJCCNStageDescriptor, row.get('n_stage')),
                'm_stage': self._get_lookup(LookupAJCCMStageDescriptor, row.get('m_stage')),
                'overall_stage': self._get_lookup(LookupStageDescriptor, row.get('overall_stage')),
            }
        )
        return stage
    
    def _import_adverse_effects(self, row, diagnosis):
        """Import or update Adverse Effects"""
        ae_id = row.get('chavi_adverse_effects_id')
        if not ae_id:
            return None
        
        adverse_effect, created = AdverseEffects.objects.update_or_create(
            chavi_adverse_effects_id=ae_id,
            defaults={
                'diagnosis': diagnosis,
                'ctcae_grade_lookup': self._get_lookup(LookupCTCAEGrade, row.get('ctcae_grade_lookup')),
                'adverse_effect_start_date': self._parse_date(row.get('adverse_effect_start_date')),
                'adverse_effect_end_date': self._parse_date(row.get('adverse_effect_end_date')),
            }
        )
        return adverse_effect
    
    def _import_other_treatment(self, row, diagnosis):
        """Import or update Other Treatment"""
        treatment_id = row.get('chavi_treatment_id')
        if not treatment_id:
            return None
        
        treatment, created = OtherTreatment.objects.update_or_create(
            chavi_treatment_id=treatment_id,
            defaults={
                'diagnosis': diagnosis,
                'treatment_intent': self._get_lookup(LookupTreatmentIntent, row.get('treatment_intent')),
                'treatment': row.get('treatment'),
                'treatment_start_date': self._parse_date(row.get('treatment_start_date')),
                'treatment_end_date': self._parse_date(row.get('treatment_end_date')),
            }
        )
        return treatment
    
    def _import_comorbidity(self, row, patient):
        """Import or update Comorbidity"""
        comorbidity_id = row.get('chavi_comorbidity_id')
        if not comorbidity_id:
            return None
        
        comorbidity, created = Comorbidity.objects.update_or_create(
            chavi_comorbidity_id=comorbidity_id,
            defaults={
                'patient': patient,
                'comorbidity_type': self._get_lookup(LookupComorbidity, row.get('comorbidity_type')),
                'date_of_comorbidity_assessment': self._parse_date(row.get('date_of_comorbidity_assessment')),
                'duration_of_comorbidity': row.get('duration_of_comorbidity'),
                'comorbidity_resolved': self._parse_boolean(row.get('comorbidity_resolved')),
            }
        )
        return comorbidity
    
    def _import_symptom(self, row, patient):
        """Import or update Symptom"""
        symptom_id = row.get('chavi_symptom_id')
        if not symptom_id:
            return None
        
        symptom, created = Symptom.objects.update_or_create(
            chavi_symptom_id=symptom_id,
            defaults={
                'patient': patient,
                'symptom': self._get_lookup(LookupSymptoms, row.get('symptom')),
                'date_symptom_assessment': self._parse_date(row.get('date_symptom_assessment')),
                'duration_of_symptom': row.get('duration_of_symptom'),
                'severity': self._get_lookup(LookupSeverity, row.get('severity')),
            }
        )
        return symptom
    
    def _import_patient_outcome(self, row, patient):
        """Import or update Patient Outcome"""
        outcome_id = row.get('chavi_patient_outcome_id')
        if not outcome_id:
            return None
        
        patient_outcome, created = PatientOutcome.objects.update_or_create(
            chavi_patient_outcome_id=outcome_id,
            defaults={
                'patient': patient,
                'patient_status': self._get_lookup(LookupOutcome, row.get('patient_status')),
                'date_of_death': self._parse_date(row.get('date_of_death')),
                'last_date_of_follow_up': self._parse_date(row.get('last_date_of_follow_up')),
                'death_related_to_cancer_progression': self._parse_boolean(row.get('death_related_to_cancer_progression')),
            }
        )
        return patient_outcome
    
    def _import_laboratory_result(self, row, patient):
        """Import or update Laboratory Result"""
        lab_id = row.get('chavi_laboratory_result_id')
        if not lab_id:
            return None
        
        lab_result, created = LaboratoryResults.objects.update_or_create(
            chavi_laboratory_result_id=lab_id,
            defaults={
                'patient': patient,
                'laboratory_test': self._get_lookup(LookupLaboratoryTest, row.get('laboratory_test')),
                'result_date': self._parse_date(row.get('result_date')),
                'quantitative_result_value': self._parse_decimal(row.get('quantitative_result_value')),
                'quantitative_result_unit': self._get_lookup(LookupLabResultsUnits, row.get('quantitative_result_unit')),
                'qualitative_laboratory_result': self._get_choice_value(QualitativeLaboratoryResult, row.get('qualitative_laboratory_result')),
            }
        )
        return lab_result
    
    def _import_patient_assessment(self, row, patient):
        """Import or update Patient Assessment"""
        assessment_id = row.get('chavi_patient_assessment_id')
        if not assessment_id:
            return None
        
        assessment, created = PatientAssessment.objects.update_or_create(
            chavi_patient_assessment_id=assessment_id,
            defaults={
                'patient': patient,
                'date_assessment': self._parse_date(row.get('date_assessment')),
                'height': self._parse_decimal(row.get('height')),
                'weight': self._parse_decimal(row.get('weight')),
                'systolic_blood_pressure': self._parse_decimal(row.get('systolic_blood_pressure')),
                'diastolic_blood_pressure': self._parse_decimal(row.get('diastolic_blood_pressure')),
                'performance_status': self._get_lookup(LookupPerformanceStatus, row.get('performance_status')),
            }
        )
        return assessment
    
    def _import_immunohistochemistry(self, row, pathology):
        """Import or update Immunohistochemistry"""
        ihc_id = row.get('chavi_ihc_id')
        if not ihc_id:
            return None
        
        ihc, created = Immunohistochemistry.objects.update_or_create(
            chavi_ihc_id=ihc_id,
            defaults={
                'pathology': pathology,
                'date_ihc': self._parse_date(row.get('date_ihc')),
                'protein_name': self._get_lookup(LookupIHCAntibody, row.get('protein_name')),
                'ihc_result': self._get_lookup(LookupIHCResult, row.get('ihc_result')),
                'percentage_positive_tumor_cells': self._parse_decimal(row.get('percentage_positive_tumor_cells')),
                'tumor_cell_staining_intensity': self._get_lookup(LookupIHCStainingIntensity, row.get('tumor_cell_staining_intensity')),
            }
        )
        return ihc
    
    def _import_cytogenetics(self, row, pathology):
        """Import or update Cytogenetics"""
        cyto_id = row.get('chavi_cytogenetics_id')
        if not cyto_id:
            return None
        
        cyto, created = Cytogenetics.objects.update_or_create(
            chavi_cytogenetics_id=cyto_id,
            defaults={
                'pathology': pathology,
                'date_cytogenetics': self._parse_date(row.get('date_cytogenetics')),
                'gene': self._get_lookup(LookupGene, row.get('gene')),
                'cytogenetic_abnormality': self._get_lookup(LookupCytogeneticAbnormality, row.get('cytogenetic_abnormality')),
            }
        )
        return cyto
    
    def _import_somatic_genomic_alterations(self, row, pathology):
        """Import or update Somatic Genomic Alterations"""
        somatic_id = row.get('chavi_somatic_genomic_id')
        if not somatic_id:
            return None
        
        somatic, created = SomaticGenomicAlterations.objects.update_or_create(
            chavi_somatic_genomic_id=somatic_id,
            defaults={
                'pathology': pathology,
                'date_test': self._parse_date(row.get('date_test')),
                'cosmic_gene_name': self._get_lookup(LookupGene, row.get('cosmic_gene_name')),
                'reference_sequence': row.get('reference_sequence'),
                'protein_modification': row.get('protein_modification'),
                'variant_type': row.get('variant_type'),
                'allele_frequency': self._parse_decimal(row.get('allele_frequency')),
                'clinical_significance': self._get_lookup(LookupClinicalSignificance, row.get('clinical_significance')),
            }
        )
        return somatic
    
    def _import_gene_expression_data(self, row, pathology):
        """Import or update Gene Expression Data"""
        gene_exp_id = row.get('chavi_gene_expression_id')
        if not gene_exp_id:
            return None
        
        gene_exp, created = GeneExpressionData.objects.update_or_create(
            chavi_gene_expression_id=gene_exp_id,
            defaults={
                'pathology': pathology,
                'gene': self._get_lookup(LookupGene, row.get('gene_expression_gene')),
                'expression_value': self._parse_decimal(row.get('expression_value')),
                'expression_units': self._get_lookup(LookupExpressionUnits, row.get('expression_units')),
            }
        )
        return gene_exp
    
    def _import_epigenetic_data(self, row, pathology):
        """Import or update Epigenetic Data"""
        epi_id = row.get('chavi_epigenetic_id')
        if not epi_id:
            return None
        
        epi, created = EpigeneticData.objects.update_or_create(
            chavi_epigenetic_id=epi_id,
            defaults={
                'pathology': pathology,
                'gene': self._get_lookup(LookupGene, row.get('epigenetic_gene')),
                'epigenetic_abnormality_type': self._get_lookup(LookupEpigeneticAbnormalityType, row.get('epigenetic_abnormality_type')),
            }
        )
        return epi
    
    def _import_lesion_response(self, row, lesion):
        """Import or update Lesion Response"""
        response_id = row.get('chavi_lesion_response_id')
        if not response_id:
            return None
        
        response, created = LesionResponse.objects.update_or_create(
            chavi_lesion_response_id=response_id,
            defaults={
                'lesion': lesion,
                'lesion_response_date': self._parse_date(row.get('lesion_response_date')),
                'lesion_response': self._get_lookup(LookupResponseType, row.get('lesion_response')),
                'lesion_response_modality': self._get_choice_value(ModalityChoices, row.get('lesion_response_modality')),
                'residual_lesion_size_x_axis': self._parse_decimal(row.get('residual_lesion_size_x_axis')),
                'residual_lesion_size_y_axis': self._parse_decimal(row.get('residual_lesion_size_y_axis')),
                'residual_lesion_size_z_axis': self._parse_decimal(row.get('residual_lesion_size_z_axis')),
                'residual_lesion_volume': self._parse_decimal(row.get('residual_lesion_volume')),
            }
        )
        return response
    
    def _import_germline_genomic_alterations(self, row, patient):
        """Import or update Germline Genomic Alterations"""
        germline_id = row.get('chavi_germline_genomic_id')
        if not germline_id:
            return None
        
        germline, created = GermlineGenomicAlterations.objects.update_or_create(
            chavi_germline_genomic_id=germline_id,
            defaults={
                'patient': patient,
                'gene': self._get_lookup(LookupGene, row.get('germline_gene')),
                'variant': row.get('germline_variant'),
                'clinical_significance': self._get_lookup(LookupClinicalSignificance, row.get('germline_clinical_significance')),
            }
        )
        return germline
    
    def _import_radiotherapy_volume(self, row, radiotherapy):
        """Import or update Radiotherapy Volume"""
        volume_id = row.get('radiotherapy_volume_id')
        if not volume_id:
            return None
        
        volume, created = RadiotherapyVolume.objects.update_or_create(
            radiotherapy_volume_id=volume_id,
            defaults={
                'radiotherapy': radiotherapy,
                'volume_name': row.get('volume_name'),
                'volume_type': self._get_lookup(LookupRadiotherapyVolumeType, row.get('volume_type')),
                'volume_dose_prescribed': self._parse_decimal(row.get('volume_dose_prescribed')),
                'volume_fractions': row.get('volume_fractions'),
                'volume_radiotherapy_start_date': self._parse_date(row.get('volume_radiotherapy_start_date')),
                'volume_radiotherapy_end_date': self._parse_date(row.get('volume_radiotherapy_end_date')),
            }
        )
        return volume
    
    def _import_concomitant_medications(self, row, diagnosis):
        """Import or update Concomitant Medications"""
        med_id = row.get('chavi_concomitant_medication_id')
        if not med_id:
            return None
        
        med, created = ConcomitantMedications.objects.update_or_create(
            chavi_concomitant_medication_id=med_id,
            defaults={
                'diagnosis': diagnosis,
                'concomitant_medication_name': row.get('concomitant_medication_name'),
                'concomitant_medication_start_date': self._parse_date(row.get('concomitant_medication_start_date')),
                'concomitant_medication_end_date': self._parse_date(row.get('concomitant_medication_end_date')),
            }
        )
        return med
    
    def _import_systemic_therapy_schedule(self, row, systemic_therapy):
        """Import or update Systemic Therapy Schedule"""
        schedule_id = row.get('chavi_systemic_therapy_schedule_id')
        if not schedule_id:
            return None
        
        schedule, created = SystemicTherapySchedule.objects.update_or_create(
            chavi_systemic_therapy_schedule_id=schedule_id,
            defaults={
                'systemic_therapy': systemic_therapy,
                'systemic_therapy_agent': self._get_lookup(LookupSystemicAgent, row.get('systemic_therapy_agent')),
                'systemic_therapy_agent_start_date': self._parse_date(row.get('systemic_therapy_agent_start_date')),
                'systemic_therapy_agent_end_date': self._parse_date(row.get('systemic_therapy_agent_end_date')),
                'systemic_therapy_agent_route': self._get_lookup(LookupDrugRoute, row.get('systemic_therapy_agent_route')),
                'systemic_therapy_dose_planned': self._parse_decimal(row.get('systemic_therapy_dose_planned')),
                'systemic_therapy_dose_administered': self._parse_decimal(row.get('systemic_therapy_dose_administered')),
            }
        )
        return schedule
    
    def _import_patient_reported_outcome(self, row, patient):
        """Import or update Patient Reported Outcome"""
        pro_id = row.get('chavi_pro_id')
        if not pro_id:
            return None
        
        pro, created = PatientReportedOutcome.objects.update_or_create(
            chavi_pro_id=pro_id,
            defaults={
                'patient': patient,
                'pro_date': self._parse_date(row.get('pro_date')),
                'pro_score': self._parse_decimal(row.get('pro_score')),
            }
        )
        return pro
