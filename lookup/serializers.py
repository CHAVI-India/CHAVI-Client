from rest_framework import serializers
from .models import (
    LookupLaterality, LookupICDCode, LookupFMACode, LookupPresentation,
    LookupOutcomeType, LookupLesionType, LookupResponseType, LookupProtein,
    LookupGene, LookupTreatmentIntent, LookupTreatmentSequence, LookupSystemicAgent,
    LookupVolumeUnits, LookupSizeUnits, LookupDoseUnits, LookupLabResultsUnits,
    LookupMassUnits, LookupDrugRoute, LookupCTCAEGrade, LookupOutcome,
    LookupStagingSystem, LookupAJCCStagePrefix, LookupAJCCStageSuffix,
    LookupAJCCTStageDescriptor, LookupAJCCNStageDescriptor, LookupAJCCMStageDescriptor,
    LookupStageDescriptor, LookupDiagnosticModality, LookupSystemicTherapyType,
    LookupRadiotherapyVolumeType, LookupPathology, LookupGrade, LookupPathologyDescriptors,
    LookupMajorCancerCategory, LookupRadiotherapyModality, LookupRadiotherapyType,
    LookupRadiotherapyTechnique, LookupClinicalSignificance, LookupIHCResult,
    LookupIHCStainingIntensity, LookupMarginStatus, LookupTreatmentEffect,
    LookupStagingType, LookupSystemicTherapyRegimen, LookupRTLocation,
    LookupLaboratoryTest, LookupSymptoms, LookupSeverity, LookupIHCAntibody,
    LookupComorbidity, LookupPerformanceStatus, LookupExpressionUnits,
    LookupCytogeneticAbnormality, LookupEpigeneticAbnormalityType, LookupSurgicalProcedures,
    LookupNodalAssessmentType
)


class LookupLateralitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupLaterality
        exclude = ['created_at', 'updated_at']


class LookupICDCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupICDCode
        exclude = ['created_at', 'updated_at']


class LookupFMACodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupFMACode
        exclude = ['created_at', 'updated_at']


class LookupPresentationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupPresentation
        exclude = ['created_at', 'updated_at']


class LookupOutcomeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupOutcomeType
        exclude = ['created_at', 'updated_at']


class LookupLesionTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupLesionType
        exclude = ['created_at', 'updated_at']


class LookupResponseTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupResponseType
        exclude = ['created_at', 'updated_at']


class LookupProteinSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupProtein
        fields = '__all__'


class LookupGeneSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupGene
        exclude = ['created_at', 'updated_at']


class LookupTreatmentIntentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupTreatmentIntent
        exclude = ['created_at', 'updated_at']


class LookupTreatmentSequenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupTreatmentSequence
        exclude = ['created_at', 'updated_at']


class LookupSystemicAgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupSystemicAgent
        exclude = ['created_at', 'updated_at']


class LookupVolumeUnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupVolumeUnits
        exclude = ['created_at', 'updated_at']


class LookupSizeUnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupSizeUnits
        exclude = ['created_at', 'updated_at']


class LookupDoseUnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupDoseUnits
        exclude = ['created_at', 'updated_at']


class LookupLabResultsUnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupLabResultsUnits
        exclude = ['created_at', 'updated_at']


class LookupMassUnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupMassUnits
        exclude = ['created_at', 'updated_at']


class LookupDrugRouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupDrugRoute
        exclude = ['created_at', 'updated_at']


class LookupCTCAEGradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupCTCAEGrade
        exclude = ['created_at', 'updated_at']


class LookupOutcomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupOutcome
        exclude = ['created_at', 'updated_at']


class LookupStagingSystemSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupStagingSystem
        exclude = ['created_at', 'updated_at']


class LookupAJCCStagePrefixSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupAJCCStagePrefix
        exclude = ['created_at', 'updated_at']


class LookupAJCCStageSuffixSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupAJCCStageSuffix
        exclude = ['created_at', 'updated_at']


class LookupAJCCTStageDescriptorSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupAJCCTStageDescriptor
        exclude = ['created_at', 'updated_at']


class LookupAJCCNStageDescriptorSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupAJCCNStageDescriptor
        exclude = ['created_at', 'updated_at']


class LookupAJCCMStageDescriptorSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupAJCCMStageDescriptor
        exclude = ['created_at', 'updated_at']


class LookupStageDescriptorSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupStageDescriptor
        exclude = ['created_at', 'updated_at']


class LookupDiagnosticModalitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupDiagnosticModality
        exclude = ['created_at', 'updated_at']


class LookupSystemicTherapyTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupSystemicTherapyType
        exclude = ['created_at', 'updated_at']


class LookupRadiotherapyVolumeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupRadiotherapyVolumeType
        exclude = ['created_at', 'updated_at']


class LookupPathologySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupPathology
        exclude = ['created_at', 'updated_at']


class LookupGradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupGrade
        exclude = ['created_at', 'updated_at']


class LookupPathologyDescriptorsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupPathologyDescriptors
        exclude = ['created_at', 'updated_at']


class LookupMajorCancerCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupMajorCancerCategory
        exclude = ['created_at', 'updated_at']


class LookupRadiotherapyModalitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupRadiotherapyModality
        exclude = ['created_at', 'updated_at']


class LookupRadiotherapyTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupRadiotherapyType
        exclude = ['created_at', 'updated_at']


class LookupRadiotherapyTechniqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupRadiotherapyTechnique
        exclude = ['created_at', 'updated_at']


class LookupClinicalSignificanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupClinicalSignificance
        exclude = ['created_at', 'updated_at']


class LookupIHCResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupIHCResult
        exclude = ['created_at', 'updated_at']


class LookupIHCStainingIntensitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupIHCStainingIntensity
        exclude = ['created_at', 'updated_at']


class LookupMarginStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupMarginStatus
        exclude = ['created_at', 'updated_at']


class LookupTreatmentEffectSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupTreatmentEffect
        exclude = ['created_at', 'updated_at']


class LookupStagingTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupStagingType
        exclude = ['created_at', 'updated_at']


class LookupSystemicTherapyRegimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupSystemicTherapyRegimen
        exclude = ['created_at', 'updated_at']


class LookupRTLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupRTLocation
        exclude = ['created_at', 'updated_at']


class LookupLaboratoryTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupLaboratoryTest
        exclude = ['created_at', 'updated_at']


class LookupSymptomsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupSymptoms
        exclude = ['created_at', 'updated_at']


class LookupSeveritySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupSeverity
        exclude = ['created_at', 'updated_at']


class LookupIHCAntibodySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupIHCAntibody
        exclude = ['created_at', 'updated_at']


class LookupComorbiditySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupComorbidity
        exclude = ['created_at', 'updated_at']


class LookupPerformanceStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupPerformanceStatus
        exclude = ['created_at', 'updated_at']


class LookupExpressionUnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupExpressionUnits
        exclude = ['created_at', 'updated_at']


class LookupCytogeneticAbnormalitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupCytogeneticAbnormality
        exclude = ['created_at', 'updated_at']


class LookupEpigeneticAbnormalityTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupEpigeneticAbnormalityType
        exclude = ['created_at', 'updated_at']


class LookupSurgicalProceduresSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupSurgicalProcedures
        exclude = ['created_at', 'updated_at']


class LookupNodalAssessmentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupNodalAssessmentType
        exclude = ['created_at', 'updated_at']
