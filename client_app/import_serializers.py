"""
Nested serializers for data import.
These serializers accept nested JSON and create related objects.
"""

from rest_framework import serializers
from .models import *


class ComorbidityImportSerializer(serializers.ModelSerializer):
    """Import serializer for Comorbidity (nested under Patient)."""
    class Meta:
        model = Comorbidity
        exclude = ['chavi_comorbidity_id', 'patient', 'created_at', 'updated_at']


class SymptomImportSerializer(serializers.ModelSerializer):
    """Import serializer for Symptom (nested under Patient)."""
    class Meta:
        model = Symptom
        exclude = ['chavi_symptom_id', 'patient', 'created_at', 'updated_at']


class GermlineGenomicAlterationsImportSerializer(serializers.ModelSerializer):
    """Import serializer for GermlineGenomicAlterations (nested under Patient)."""
    class Meta:
        model = GermlineGenomicAlterations
        exclude = ['chavi_germline_genomic_id', 'patient', 'created_at', 'updated_at']


class PatientOutcomeImportSerializer(serializers.ModelSerializer):
    """Import serializer for PatientOutcome (nested under Patient)."""
    class Meta:
        model = PatientOutcome
        exclude = ['chavi_patient_outcome_id', 'patient', 'created_at', 'updated_at']


class PatientAssessmentImportSerializer(serializers.ModelSerializer):
    """Import serializer for PatientAssessment (nested under Patient)."""
    class Meta:
        model = PatientAssessment
        exclude = ['chavi_patient_assessment_id', 'patient', 'created_at', 'updated_at']


class LaboratoryResultsImportSerializer(serializers.ModelSerializer):
    """Import serializer for LaboratoryResults (nested under Patient)."""
    class Meta:
        model = LaboratoryResults
        exclude = ['chavi_laboratory_results_id', 'patient', 'created_at', 'updated_at']


class PatientReportedOutcomeImportSerializer(serializers.ModelSerializer):
    """Import serializer for PatientReportedOutcome (nested under Patient)."""
    class Meta:
        model = PatientReportedOutcome
        exclude = ['chavi_pro_id', 'patient', 'created_at', 'updated_at']


# Level 2 serializers (nested under Diagnosis)

class ImmunohistochemistryImportSerializer(serializers.ModelSerializer):
    """Import serializer for Immunohistochemistry (nested under Pathology)."""
    class Meta:
        model = Immunohistochemistry
        exclude = ['chavi_ihc_id', 'pathology', 'created_at', 'updated_at']


class CytogeneticsImportSerializer(serializers.ModelSerializer):
    """Import serializer for Cytogenetics (nested under Pathology)."""
    class Meta:
        model = Cytogenetics
        exclude = ['chavi_cytogenetics_id', 'pathology', 'created_at', 'updated_at']


class SomaticGenomicAlterationsImportSerializer(serializers.ModelSerializer):
    """Import serializer for SomaticGenomicAlterations (nested under Pathology)."""
    class Meta:
        model = SomaticGenomicAlterations
        exclude = ['chavi_somatic_genomic_id', 'pathology', 'created_at', 'updated_at']


class GeneExpressionDataImportSerializer(serializers.ModelSerializer):
    """Import serializer for GeneExpressionData (nested under Pathology)."""
    class Meta:
        model = GeneExpressionData
        exclude = ['chavi_gene_expression_id', 'pathology', 'created_at', 'updated_at']


class EpigeneticDataImportSerializer(serializers.ModelSerializer):
    """Import serializer for EpigeneticData (nested under Pathology)."""
    class Meta:
        model = EpigeneticData
        exclude = ['chavi_epigenetic_id', 'pathology', 'created_at', 'updated_at']


class PathologyImportSerializer(serializers.ModelSerializer):
    """Import serializer for Pathology (nested under Diagnosis)."""
    immunohistochemistry_set = ImmunohistochemistryImportSerializer(many=True, required=False)
    cytogenetics_set = CytogeneticsImportSerializer(many=True, required=False)
    somaticgenomicalterations_set = SomaticGenomicAlterationsImportSerializer(many=True, required=False)
    geneexpressiondata_set = GeneExpressionDataImportSerializer(many=True, required=False)
    epigeneticdata_set = EpigeneticDataImportSerializer(many=True, required=False)
    
    class Meta:
        model = Pathology
        exclude = ['chavi_pathology_id', 'diagnosis', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        # Extract nested data
        ihc_data = validated_data.pop('immunohistochemistry_set', [])
        cyto_data = validated_data.pop('cytogenetics_set', [])
        somatic_data = validated_data.pop('somaticgenomicalterations_set', [])
        gene_exp_data = validated_data.pop('geneexpressiondata_set', [])
        epigenetic_data = validated_data.pop('epigeneticdata_set', [])
        
        # Create Pathology
        pathology = Pathology.objects.create(**validated_data)
        
        # Create nested objects
        for ihc in ihc_data:
            Immunohistochemistry.objects.create(pathology=pathology, **ihc)
        for cyto in cyto_data:
            Cytogenetics.objects.create(pathology=pathology, **cyto)
        for somatic in somatic_data:
            SomaticGenomicAlterations.objects.create(pathology=pathology, **somatic)
        for gene_exp in gene_exp_data:
            GeneExpressionData.objects.create(pathology=pathology, **gene_exp)
        for epigenetic in epigenetic_data:
            EpigeneticData.objects.create(pathology=pathology, **epigenetic)
        
        return pathology


class LesionResponseImportSerializer(serializers.ModelSerializer):
    """Import serializer for LesionResponse (nested under Lesion)."""
    class Meta:
        model = LesionResponse
        exclude = ['chavi_lesion_response_id', 'lesion', 'created_at', 'updated_at']


class LesionImportSerializer(serializers.ModelSerializer):
    """Import serializer for Lesion (nested under Diagnosis)."""
    lesionresponse_set = LesionResponseImportSerializer(many=True, required=False)
    
    class Meta:
        model = Lesion
        exclude = ['chavi_lesion_id', 'diagnosis', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        responses_data = validated_data.pop('lesionresponse_set', [])
        lesion = Lesion.objects.create(**validated_data)
        
        for response in responses_data:
            LesionResponse.objects.create(lesion=lesion, **response)
        
        return lesion


class SurgeryImportSerializer(serializers.ModelSerializer):
    """Import serializer for Surgery (nested under Diagnosis)."""
    class Meta:
        model = Surgery
        exclude = ['chavi_surgery_id', 'diagnosis', 'created_at', 'updated_at']


class RadiotherapyImportSerializer(serializers.ModelSerializer):
    """Import serializer for Radiotherapy (nested under Diagnosis)."""
    class Meta:
        model = Radiotherapy
        exclude = ['chavi_radiotherapy_id', 'diagnosis', 'created_at', 'updated_at']


class SystemicTherapyImportSerializer(serializers.ModelSerializer):
    """Import serializer for SystemicTherapy (nested under Diagnosis)."""
    class Meta:
        model = SystemicTherapy
        exclude = ['chavi_systemic_therapy_id', 'diagnosis', 'created_at', 'updated_at']


class OtherTreatmentImportSerializer(serializers.ModelSerializer):
    """Import serializer for OtherTreatment (nested under Diagnosis)."""
    class Meta:
        model = OtherTreatment
        exclude = ['chavi_treatment_id', 'diagnosis', 'created_at', 'updated_at']


class OutcomeImportSerializer(serializers.ModelSerializer):
    """Import serializer for Outcome (nested under Diagnosis)."""
    class Meta:
        model = Outcome
        exclude = ['chavi_outcome_id', 'diagnosis', 'created_at', 'updated_at']


class AdverseEffectImportSerializer(serializers.ModelSerializer):
    """Import serializer for AdverseEffects (nested under Diagnosis)."""
    class Meta:
        model = AdverseEffects
        exclude = ['chavi_adverse_effect_id', 'diagnosis', 'created_at', 'updated_at']


class DiagnosisImportSerializer(serializers.ModelSerializer):
    """Import serializer for Diagnosis (nested under Patient)."""
    pathology_set = PathologyImportSerializer(many=True, required=False)
    lesion_set = LesionImportSerializer(many=True, required=False)
    surgery_set = SurgeryImportSerializer(many=True, required=False)
    radiotherapy_set = RadiotherapyImportSerializer(many=True, required=False)
    systemictherapy_set = SystemicTherapyImportSerializer(many=True, required=False)
    othertreatment_set = OtherTreatmentImportSerializer(many=True, required=False)
    outcome_set = OutcomeImportSerializer(many=True, required=False)
    adverseeffect_set = AdverseEffectImportSerializer(many=True, required=False)
    
    class Meta:
        model = Diagnosis
        exclude = ['chavi_diagnosis_id', 'patient', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        # Extract all nested data
        pathology_data = validated_data.pop('pathology_set', [])
        lesion_data = validated_data.pop('lesion_set', [])
        surgery_data = validated_data.pop('surgery_set', [])
        radiotherapy_data = validated_data.pop('radiotherapy_set', [])
        systemic_data = validated_data.pop('systemictherapy_set', [])
        other_treatment_data = validated_data.pop('othertreatment_set', [])
        outcome_data = validated_data.pop('outcome_set', [])
        adverse_data = validated_data.pop('adverseeffect_set', [])
        
        # Create Diagnosis
        diagnosis = Diagnosis.objects.create(**validated_data)
        
        # Create nested Pathology objects (with their nested objects)
        for path_data in pathology_data:
            path_serializer = PathologyImportSerializer(data=path_data)
            if path_serializer.is_valid(raise_exception=True):
                path_serializer.save(diagnosis=diagnosis)
        
        # Create nested Lesion objects (with their nested objects)
        for lesion_data_item in lesion_data:
            lesion_serializer = LesionImportSerializer(data=lesion_data_item)
            if lesion_serializer.is_valid(raise_exception=True):
                lesion_serializer.save(diagnosis=diagnosis)
        
        # Create other nested objects
        for surgery in surgery_data:
            Surgery.objects.create(diagnosis=diagnosis, **surgery)
        for radio in radiotherapy_data:
            Radiotherapy.objects.create(diagnosis=diagnosis, **radio)
        for systemic in systemic_data:
            SystemicTherapy.objects.create(diagnosis=diagnosis, **systemic)
        for other in other_treatment_data:
            OtherTreatment.objects.create(diagnosis=diagnosis, **other)
        for outcome in outcome_data:
            Outcome.objects.create(diagnosis=diagnosis, **outcome)
        for adverse in adverse_data:
            AdverseEffect.objects.create(diagnosis=diagnosis, **adverse)
        
        return diagnosis


class PatientImportSerializer(serializers.ModelSerializer):
    """
    Main import serializer for Patient with all nested relationships.
    Accepts nested JSON and creates Patient with all related objects.
    """
    diagnosis_set = DiagnosisImportSerializer(many=True, required=False)
    comorbidity_set = ComorbidityImportSerializer(many=True, required=False)
    symptom_set = SymptomImportSerializer(many=True, required=False)
    germlinegenomicalterations_set = GermlineGenomicAlterationsImportSerializer(many=True, required=False)
    patientoutcome_set = PatientOutcomeImportSerializer(many=True, required=False)
    patientassessment_set = PatientAssessmentImportSerializer(many=True, required=False)
    laboratoryresults_set = LaboratoryResultsImportSerializer(many=True, required=False)
    patientreportedoutcome_set = PatientReportedOutcomeImportSerializer(many=True, required=False)
    
    class Meta:
        model = Patient
        exclude = ['created_at', 'updated_at', 'chavi_consent', 'date_chavi_consent']
    
    def create(self, validated_data):
        # Extract all nested data
        diagnosis_data = validated_data.pop('diagnosis_set', [])
        comorbidity_data = validated_data.pop('comorbidity_set', [])
        symptom_data = validated_data.pop('symptom_set', [])
        germline_data = validated_data.pop('germlinegenomicalterations_set', [])
        patient_outcome_data = validated_data.pop('patientoutcome_set', [])
        assessment_data = validated_data.pop('patientassessment_set', [])
        lab_data = validated_data.pop('laboratoryresults_set', [])
        pro_data = validated_data.pop('patientreportedoutcome_set', [])
        
        # Extract ManyToMany fields (must be set after object creation)
        patient_project_data = validated_data.pop('patient_project', [])
        
        # Create Patient
        patient = Patient.objects.create(**validated_data)
        
        # Set ManyToMany relationships
        if patient_project_data:
            patient.patient_project.set(patient_project_data)
        
        # Create nested Diagnosis objects (with all their nested objects)
        for diag_data in diagnosis_data:
            diag_serializer = DiagnosisImportSerializer(data=diag_data)
            if diag_serializer.is_valid(raise_exception=True):
                diag_serializer.save(patient=patient)
        
        # Create other Level 1 nested objects
        for comorbidity in comorbidity_data:
            Comorbidity.objects.create(patient=patient, **comorbidity)
        for symptom in symptom_data:
            Symptom.objects.create(patient=patient, **symptom)
        for germline in germline_data:
            GermlineGenomicAlterations.objects.create(patient=patient, **germline)
        for outcome in patient_outcome_data:
            PatientOutcome.objects.create(patient=patient, **outcome)
        for assessment in assessment_data:
            PatientAssessment.objects.create(patient=patient, **assessment)
        for lab in lab_data:
            LaboratoryResults.objects.create(patient=patient, **lab)
        for pro in pro_data:
            PatientReportedOutcome.objects.create(patient=patient, **pro)
        
        return patient
