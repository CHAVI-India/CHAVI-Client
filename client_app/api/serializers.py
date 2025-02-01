from rest_framework import serializers
from client_app.models import *
import hashlib

def hash_id(id_value):
    """Hash an ID value using SHA-256"""
    if id_value is None:
        return None
    id_str = str(id_value).encode('utf-8')
    return hashlib.sha256(id_str).hexdigest()

class RadiotherapyDoseVolumeSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    radiotherapy = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.radiotherapy_dose_volume_data_id)
    
    def get_radiotherapy(self, obj):
        return hash_id(obj.radiotherapy.chavi_radiotherapy_id) if obj.radiotherapy else None

    class Meta:
        model = RadiotherapyDoseVolumeData
        exclude = ['created_at','radiotherapy_dose_volume_data_id']

class RadiotherapyVolumeSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    radiotherapy = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.radiotherapy_volume_id)

    def get_radiotherapy(self, obj):
        return hash_id(obj.radiotherapy.chavi_radiotherapy_id) if obj.radiotherapy else None

    class Meta:
        model = RadiotherapyVolume
        exclude = ['created_at', 'updated_at', 'radiotherapy_volume_id']

class RadiotherapyCourseSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()
    radiotherapy_volumes = RadiotherapyVolumeSerializer(source='radiotherapyvolume_set', many=True)
    dose_volume_data = RadiotherapyDoseVolumeSerializer(source='radiotherapydosevolumedata_set', many=True)
    radiotherapy_dicom_study = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_radiotherapy_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = Radiotherapy
        exclude = ['created_at', 'updated_at', 'chavi_radiotherapy_id']

class SystemicTherapyScheduleSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    systemic_therapy = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_systemic_therapy_schedule_id)

    def get_systemic_therapy(self, obj):
        return hash_id(obj.systemic_therapy.chavi_systemic_therapy_id) if obj.systemic_therapy else None

    class Meta:
        model = SystemicTherapySchedule
        exclude = ['created_at', 'updated_at', 'chavi_systemic_therapy_schedule_id']

class SystemicTherapySerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()
    schedules = SystemicTherapyScheduleSerializer(source='systemic_therapy_schedule', many=True)
    systemic_therapy_dicom_study = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_systemic_therapy_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = SystemicTherapy
        exclude = ['created_at', 'updated_at', 'chavi_systemic_therapy_id']

class SurgerySerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()
    surgery_dicom_study = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_surgery_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = Surgery
        exclude = ['created_at', 'updated_at', 'chavi_surgery_id']

class LesionResponseSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    lesion = serializers.SerializerMethodField()
    lesion_response_dicom_study = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_lesion_response_id)

    def get_lesion(self, obj):
        return hash_id(obj.lesion.chavi_lesion_id) if obj.lesion else None

    class Meta:
        model = LesionResponse
        exclude = ['created_at', 'updated_at', 'chavi_lesion_response_id']

class LesionSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()
    lesion_dicom_study = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    responses = LesionResponseSerializer(source='lesionresponse_set', many=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_lesion_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = Lesion
        exclude = ['created_at', 'updated_at', 'chavi_lesion_id']

class ImmunochemistrySerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    pathology = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_ihc_id)

    def get_pathology(self, obj):
        return hash_id(obj.pathology.chavi_pathology_id) if obj.pathology else None

    class Meta:
        model = Immunohistochemistry
        exclude = ['created_at', 'updated_at', 'chavi_ihc_id']

class CytogeneticsSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    pathology = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_cytogenetics_id)

    def get_pathology(self, obj):
        return hash_id(obj.pathology.chavi_pathology_id) if obj.pathology else None

    class Meta:
        model = Cytogenetics
        exclude = ['created_at', 'updated_at', 'chavi_cytogenetics_id']

class SomaticGenomicAlterationsSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    pathology = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_somatic_genomic_id)

    def get_pathology(self, obj):
        return hash_id(obj.pathology.chavi_pathology_id) if obj.pathology else None

    class Meta:
        model = SomaticGenomicAlterations
        exclude = ['created_at', 'updated_at', 'chavi_somatic_genomic_id']

class PathologySerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()
    immunochemistry = ImmunochemistrySerializer(source='immunohistochemistry_set', many=True)
    cytogenetics = CytogeneticsSerializer(source='cytogenetics_set', many=True)
    somatic_genomic_alterations = SomaticGenomicAlterationsSerializer(source='somaticgenomicalterations_set', many=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_pathology_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = Pathology
        exclude = ['created_at', 'updated_at', 'chavi_pathology_id']

class StageInformationSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_stage_information_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = StageInformation
        exclude = ['created_at', 'updated_at', 'chavi_stage_information_id']

class OtherTreatmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_treatment_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = OtherTreatment
        exclude = ['created_at', 'updated_at', 'chavi_treatment_id']

class ConcomitantMedicationsSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_medication_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = ConcomitantMedications
        exclude = ['created_at', 'updated_at', 'chavi_medication_id']

class AdverseEffectsSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_adverse_effects_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = AdverseEffects
        exclude = ['created_at', 'updated_at', 'chavi_adverse_effects_id']

class ProInstrumentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()

    def get_id(self, obj):
        return hash_id(obj.chavi_pro_instrument_id)

    class Meta:
        model = ProInstrument
        exclude = ['created_at', 'updated_at', 'chavi_pro_instrument_id']

class ProDomainSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    instrument = ProInstrumentSerializer(source='proinstrument_set',many=True,read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_prodomain_id)

    def get_instrument(self, obj):
        return hash_id(obj.instrument.chavi_pro_instrument_id) if obj.instrument else None

    class Meta:
        model = ProDomain
        exclude = ['created_at', 'updated_at', 'chavi_prodomain_id']        
class ProQuestionSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    domain = ProDomainSerializer(source='prodomain_set',many=True,read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_pro_question_id)

    def get_domain(self, obj):
        return hash_id(obj.domain.chavi_prodomain_id) if obj.domain else None

    class Meta:
        model = ProQuestion
        exclude = ['created_at', 'updated_at', 'chavi_pro_question_id']





class PatientReportedOutcomeSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    patient = serializers.PrimaryKeyRelatedField(read_only=True)
    instrument = ProInstrumentSerializer(source='proinstrument_set',many=True,read_only=True)
    domain = ProDomainSerializer(source='prodomain_set',many=True,read_only=True)
    question = ProQuestionSerializer(source='proquestion_set',many=True,read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_pro_id)

    def get_instrument(self, obj):
        return hash_id(obj.instrument.chavi_pro_instrument_id) if obj.instrument else None

    def get_domain(self, obj):
        return hash_id(obj.domain.chavi_prodomain_id) if obj.domain else None

    def get_question(self, obj):
        return hash_id(obj.question.chavi_pro_question_id) if obj.question else None

    class Meta:
        model = PatientReportedOutcome
        exclude = ['created_at', 'updated_at', 'chavi_pro_id']

class OutcomeSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()
    outcome_dicom_study = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_outcome_id)

    def get_diagnosis(self, obj):
        return hash_id(obj.diagnosis.chavi_diagnosis_id) if obj.diagnosis else None

    class Meta:
        model = Outcome
        exclude = ['created_at', 'updated_at', 'chavi_outcome_id']

class DiagnosisSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    patient = serializers.PrimaryKeyRelatedField(read_only=True)
    diagnosis_dicom_study = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    stage_information = StageInformationSerializer(source='stageinformation_set', many=True)
    pathology = PathologySerializer(source='pathology_set', many=True)
    surgeries = SurgerySerializer(source='surgery_set', many=True)
    radiotherapy_courses = RadiotherapyCourseSerializer(source='radiotherapy_set', many=True)
    systemic_therapies = SystemicTherapySerializer(source='systemictherapy_set', many=True)
    other_treatments = OtherTreatmentSerializer(source='othertreatment_set', many=True)
    concomitant_medications = ConcomitantMedicationsSerializer(source='concomitantmedications_set', many=True)
    lesions = LesionSerializer(source='lesion_set', many=True)
    outcomes = OutcomeSerializer(source='outcome_set', many=True)
    adverse_effects = AdverseEffectsSerializer(source='adverseeffects_set', many=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_diagnosis_id)

    class Meta:
        model = Diagnosis
        exclude = ['created_at', 'updated_at', 'chavi_diagnosis_id']

class ComorbiditySerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    patient = serializers.PrimaryKeyRelatedField(read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_comorbidity_id)

    class Meta:
        model = Comorbidity
        exclude = ['created_at', 'updated_at', 'chavi_comorbidity_id']

class LaboratoryResultsSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    patient = serializers.PrimaryKeyRelatedField(read_only=True)
    laboratory_test = serializers.PrimaryKeyRelatedField(read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_laboratory_result_id)

    class Meta:
        model = LaboratoryResults
        exclude = ['created_at', 'updated_at', 'chavi_laboratory_result_id']

class PatientOutcomeSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    patient = serializers.PrimaryKeyRelatedField(read_only=True)
    diagnosis = serializers.PrimaryKeyRelatedField(read_only=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_pt_outcome_id)

    class Meta:
        model = PatientOutcome
        exclude = ['created_at', 'updated_at', 'chavi_pt_outcome_id']

class PatientSerializer(serializers.ModelSerializer):
    diagnoses = DiagnosisSerializer(source='diagnosis_set', many=True)
    comorbidities = ComorbiditySerializer(source='comorbidity_set', many=True)
    patient_outcomes = PatientOutcomeSerializer(source='patientoutcome_set', many=True)
    patient_dicom_files = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    patient_reported_outcomes = PatientReportedOutcomeSerializer(source='patientreportedoutcome_set', many=True)
    projects = serializers.PrimaryKeyRelatedField(source='patient_project', many=True, read_only=True)
    laboratory_results = LaboratoryResultsSerializer(source='laboratoryresults_set', many=True)

    class Meta:
        model = Patient
        ordering = ['patient_id']
        exclude = ['created_at', 'updated_at','chavi_consent','date_chavi_consent']

class ProjectSerializer(serializers.ModelSerializer):
    patients = PatientSerializer(source='patient_project', many=True, read_only=True)

    class Meta:
        model = Project
        ordering = ['project_id']
        exclude = ['created_at', 'updated_at']