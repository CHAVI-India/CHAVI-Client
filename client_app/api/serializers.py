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
        exclude = ['created_at', 'updated_at', 'radiotherapy_dose_volume_data_id']

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
    schedules = SystemicTherapyScheduleSerializer(source='systemictherapyschedule_set', many=True)
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

class PathologySerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()

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

class DiagnosisSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    patient = serializers.PrimaryKeyRelatedField(read_only=True)  # Keep patient ID unchanged
    diagnosis_dicom_study = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    stage_information = StageInformationSerializer(source='stageinformation_set', many=True)
    pathology = PathologySerializer(source='pathology_set', many=True)
    surgeries = SurgerySerializer(source='surgery_set', many=True)
    radiotherapy_courses = RadiotherapyCourseSerializer(source='radiotherapy_set', many=True)
    systemic_therapies = SystemicTherapySerializer(source='systemictherapy_set', many=True)

    def get_id(self, obj):
        return hash_id(obj.chavi_diagnosis_id)

    class Meta:
        model = Diagnosis
        exclude = ['created_at', 'updated_at', 'chavi_diagnosis_id']

class ComorbiditySerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    patient = serializers.PrimaryKeyRelatedField(read_only=True)  # Keep patient ID unchanged

    def get_id(self, obj):
        return hash_id(obj.chavi_comorbidity_id)

    class Meta:
        model = Comorbidity
        exclude = ['created_at', 'updated_at', 'chavi_comorbidity_id']

class PatientOutcomeSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    patient = serializers.PrimaryKeyRelatedField(read_only=True)  # Keep patient ID unchanged

    def get_id(self, obj):
        return hash_id(obj.chavi_pt_outcome_id)

    class Meta:
        model = PatientOutcome
        exclude = ['created_at', 'updated_at', 'chavi_pt_outcome_id']

class PatientSerializer(serializers.ModelSerializer):
    diagnoses = DiagnosisSerializer(source='diagnosis_set', many=True)
    comorbidities = ComorbiditySerializer(source='comorbidity_set', many=True)
    patient_outcomes = PatientOutcomeSerializer(source='patientoutcome_set', many=True)
    patient_dicom_files = serializers.PrimaryKeyRelatedField(read_only=True, many=True)

    class Meta:
        model = Patient
        exclude = ['created_at', 'updated_at']

class ProjectSerializer(serializers.ModelSerializer):
    patients = PatientSerializer(source='patient_project', many=True)

    class Meta:
        model = Project
        exclude = ['created_at', 'updated_at']