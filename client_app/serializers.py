from rest_framework import serializers
from client_app.models import *


class StageInformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = StageInformation
        exclude = ['created_at', 'updated_at']

class ComorbiditySerializer(serializers.ModelSerializer):
    class Meta:
        model = Comorbidity
        exclude = ['created_at', 'updated_at']

class PatientOutcomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientOutcome
        exclude = ['created_at', 'updated_at']

class PatientReportedOutcomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientReportedOutcome
        exclude = ['created_at', 'updated_at']

class ProQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProQuestion
        exclude = ['created_at', 'updated_at']

class ProDomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProDomain
        exclude = ['created_at', 'updated_at']

class ProInstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProInstrument
        exclude = ['created_at', 'updated_at']


class AdverseEffectSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdverseEffects
        exclude = ['created_at', 'updated_at']

class SystemicTherapyScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemicTherapySchedule
        exclude = ['created_at', 'updated_at']

class SystemicTherapySerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemicTherapy
        exclude = ['created_at', 'updated_at']

class ConcomitantMedicationsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConcomitantMedications
        exclude = ['created_at', 'updated_at']

class SurgerySerializer(serializers.ModelSerializer):
    class Meta:
        model = Surgery
        exclude = ['created_at', 'updated_at']  

class RadiotherapyDoseVolumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RadiotherapyDoseVolumeData
        exclude = ['created_at', 'updated_at']  

class RadiotherapyVolumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RadiotherapyVolume
        exclude = ['created_at', 'updated_at']

class RadiotherapyCourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = RadiotherapyCourse
        exclude = ['created_at', 'updated_at']

class OtherTreatmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OtherTreatment
        exclude = ['created_at', 'updated_at']


class SomaticGenomicAlterationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SomaticGenomicAlteration
        exclude = ['created_at', 'updated_at']


class CytogeneticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cytogenetics
        exclude = ['created_at', 'updated_at']

class ImmunohistochemistrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Immunohistochemistry
        exclude = ['created_at', 'updated_at']  

class PathologySerializer(serializers.ModelSerializer):
    class Meta:
        model = Pathology
        exclude = ['created_at', 'updated_at']

class LesionResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = LesionResponse
        exclude = ['created_at', 'updated_at']

class LesionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesion
        exclude = ['created_at', 'updated_at']

class OutcomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Outcome
        exclude = ['created_at', 'updated_at']  

class DiagnosisSerializer(serializers.ModelSerializer):
    class Meta:
        model = Diagnosis
        exclude = ['created_at', 'updated_at']

class DICOMStudySerializer(serializers.ModelSerializer):
    class Meta:
        model = DICOMStudy
        exclude = ['created_at', 'updated_at']

class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        exclude = ['created_at', 'updated_at']

class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        exclude = ['created_at', 'updated_at']




