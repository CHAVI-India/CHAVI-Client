from rest_framework import generics
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
from .serializers import (
    LookupLateralitySerializer, LookupICDCodeSerializer, LookupFMACodeSerializer,
    LookupPresentationSerializer, LookupOutcomeTypeSerializer, LookupLesionTypeSerializer,
    LookupResponseTypeSerializer, LookupProteinSerializer, LookupGeneSerializer,
    LookupTreatmentIntentSerializer, LookupTreatmentSequenceSerializer, LookupSystemicAgentSerializer,
    LookupVolumeUnitsSerializer, LookupSizeUnitsSerializer, LookupDoseUnitsSerializer,
    LookupLabResultsUnitsSerializer, LookupMassUnitsSerializer, LookupDrugRouteSerializer,
    LookupCTCAEGradeSerializer, LookupOutcomeSerializer, LookupStagingSystemSerializer,
    LookupAJCCStagePrefixSerializer, LookupAJCCStageSuffixSerializer,
    LookupAJCCTStageDescriptorSerializer, LookupAJCCNStageDescriptorSerializer,
    LookupAJCCMStageDescriptorSerializer, LookupStageDescriptorSerializer,
    LookupDiagnosticModalitySerializer, LookupSystemicTherapyTypeSerializer,
    LookupRadiotherapyVolumeTypeSerializer, LookupPathologySerializer, LookupGradeSerializer,
    LookupPathologyDescriptorsSerializer, LookupMajorCancerCategorySerializer,
    LookupRadiotherapyModalitySerializer, LookupRadiotherapyTypeSerializer,
    LookupRadiotherapyTechniqueSerializer, LookupClinicalSignificanceSerializer,
    LookupIHCResultSerializer, LookupIHCStainingIntensitySerializer, LookupMarginStatusSerializer,
    LookupTreatmentEffectSerializer, LookupStagingTypeSerializer, LookupSystemicTherapyRegimenSerializer,
    LookupRTLocationSerializer, LookupLaboratoryTestSerializer, LookupSymptomsSerializer,
    LookupSeveritySerializer, LookupIHCAntibodySerializer, LookupComorbiditySerializer,
    LookupPerformanceStatusSerializer, LookupExpressionUnitsSerializer,
    LookupCytogeneticAbnormalitySerializer, LookupEpigeneticAbnormalityTypeSerializer,
    LookupSurgicalProceduresSerializer, LookupNodalAssessmentTypeSerializer
)


# Read-only list views for all lookup tables
class LookupLateralityListView(generics.ListAPIView):
    queryset = LookupLaterality.objects.all()
    serializer_class = LookupLateralitySerializer


class LookupICDCodeListView(generics.ListAPIView):
    queryset = LookupICDCode.objects.all()
    serializer_class = LookupICDCodeSerializer


class LookupFMACodeListView(generics.ListAPIView):
    queryset = LookupFMACode.objects.all()
    serializer_class = LookupFMACodeSerializer


class LookupPresentationListView(generics.ListAPIView):
    queryset = LookupPresentation.objects.all()
    serializer_class = LookupPresentationSerializer


class LookupOutcomeTypeListView(generics.ListAPIView):
    queryset = LookupOutcomeType.objects.all()
    serializer_class = LookupOutcomeTypeSerializer


class LookupLesionTypeListView(generics.ListAPIView):
    queryset = LookupLesionType.objects.all()
    serializer_class = LookupLesionTypeSerializer


class LookupResponseTypeListView(generics.ListAPIView):
    queryset = LookupResponseType.objects.all()
    serializer_class = LookupResponseTypeSerializer


class LookupProteinListView(generics.ListAPIView):
    queryset = LookupProtein.objects.all()
    serializer_class = LookupProteinSerializer


class LookupGeneListView(generics.ListAPIView):
    queryset = LookupGene.objects.all()
    serializer_class = LookupGeneSerializer


class LookupTreatmentIntentListView(generics.ListAPIView):
    queryset = LookupTreatmentIntent.objects.all()
    serializer_class = LookupTreatmentIntentSerializer


class LookupTreatmentSequenceListView(generics.ListAPIView):
    queryset = LookupTreatmentSequence.objects.all()
    serializer_class = LookupTreatmentSequenceSerializer


class LookupSystemicAgentListView(generics.ListAPIView):
    queryset = LookupSystemicAgent.objects.all()
    serializer_class = LookupSystemicAgentSerializer


class LookupVolumeUnitsListView(generics.ListAPIView):
    queryset = LookupVolumeUnits.objects.all()
    serializer_class = LookupVolumeUnitsSerializer


class LookupSizeUnitsListView(generics.ListAPIView):
    queryset = LookupSizeUnits.objects.all()
    serializer_class = LookupSizeUnitsSerializer


class LookupDoseUnitsListView(generics.ListAPIView):
    queryset = LookupDoseUnits.objects.all()
    serializer_class = LookupDoseUnitsSerializer


class LookupLabResultsUnitsListView(generics.ListAPIView):
    queryset = LookupLabResultsUnits.objects.all()
    serializer_class = LookupLabResultsUnitsSerializer


class LookupMassUnitsListView(generics.ListAPIView):
    queryset = LookupMassUnits.objects.all()
    serializer_class = LookupMassUnitsSerializer


class LookupDrugRouteListView(generics.ListAPIView):
    queryset = LookupDrugRoute.objects.all()
    serializer_class = LookupDrugRouteSerializer


class LookupCTCAEGradeListView(generics.ListAPIView):
    queryset = LookupCTCAEGrade.objects.all()
    serializer_class = LookupCTCAEGradeSerializer


class LookupOutcomeListView(generics.ListAPIView):
    queryset = LookupOutcome.objects.all()
    serializer_class = LookupOutcomeSerializer


class LookupStagingSystemListView(generics.ListAPIView):
    queryset = LookupStagingSystem.objects.all()
    serializer_class = LookupStagingSystemSerializer


class LookupAJCCStagePrefixListView(generics.ListAPIView):
    queryset = LookupAJCCStagePrefix.objects.all()
    serializer_class = LookupAJCCStagePrefixSerializer


class LookupAJCCStageSuffixListView(generics.ListAPIView):
    queryset = LookupAJCCStageSuffix.objects.all()
    serializer_class = LookupAJCCStageSuffixSerializer


class LookupAJCCTStageDescriptorListView(generics.ListAPIView):
    queryset = LookupAJCCTStageDescriptor.objects.all()
    serializer_class = LookupAJCCTStageDescriptorSerializer


class LookupAJCCNStageDescriptorListView(generics.ListAPIView):
    queryset = LookupAJCCNStageDescriptor.objects.all()
    serializer_class = LookupAJCCNStageDescriptorSerializer


class LookupAJCCMStageDescriptorListView(generics.ListAPIView):
    queryset = LookupAJCCMStageDescriptor.objects.all()
    serializer_class = LookupAJCCMStageDescriptorSerializer


class LookupStageDescriptorListView(generics.ListAPIView):
    queryset = LookupStageDescriptor.objects.all()
    serializer_class = LookupStageDescriptorSerializer


class LookupDiagnosticModalityListView(generics.ListAPIView):
    queryset = LookupDiagnosticModality.objects.all()
    serializer_class = LookupDiagnosticModalitySerializer


class LookupSystemicTherapyTypeListView(generics.ListAPIView):
    queryset = LookupSystemicTherapyType.objects.all()
    serializer_class = LookupSystemicTherapyTypeSerializer


class LookupRadiotherapyVolumeTypeListView(generics.ListAPIView):
    queryset = LookupRadiotherapyVolumeType.objects.all()
    serializer_class = LookupRadiotherapyVolumeTypeSerializer


class LookupPathologyListView(generics.ListAPIView):
    queryset = LookupPathology.objects.all()
    serializer_class = LookupPathologySerializer


class LookupGradeListView(generics.ListAPIView):
    queryset = LookupGrade.objects.all()
    serializer_class = LookupGradeSerializer


class LookupPathologyDescriptorsListView(generics.ListAPIView):
    queryset = LookupPathologyDescriptors.objects.all()
    serializer_class = LookupPathologyDescriptorsSerializer


class LookupMajorCancerCategoryListView(generics.ListAPIView):
    queryset = LookupMajorCancerCategory.objects.all()
    serializer_class = LookupMajorCancerCategorySerializer


class LookupRadiotherapyModalityListView(generics.ListAPIView):
    queryset = LookupRadiotherapyModality.objects.all()
    serializer_class = LookupRadiotherapyModalitySerializer


class LookupRadiotherapyTypeListView(generics.ListAPIView):
    queryset = LookupRadiotherapyType.objects.all()
    serializer_class = LookupRadiotherapyTypeSerializer


class LookupRadiotherapyTechniqueListView(generics.ListAPIView):
    queryset = LookupRadiotherapyTechnique.objects.all()
    serializer_class = LookupRadiotherapyTechniqueSerializer


class LookupClinicalSignificanceListView(generics.ListAPIView):
    queryset = LookupClinicalSignificance.objects.all()
    serializer_class = LookupClinicalSignificanceSerializer


class LookupIHCResultListView(generics.ListAPIView):
    queryset = LookupIHCResult.objects.all()
    serializer_class = LookupIHCResultSerializer


class LookupIHCStainingIntensityListView(generics.ListAPIView):
    queryset = LookupIHCStainingIntensity.objects.all()
    serializer_class = LookupIHCStainingIntensitySerializer


class LookupMarginStatusListView(generics.ListAPIView):
    queryset = LookupMarginStatus.objects.all()
    serializer_class = LookupMarginStatusSerializer


class LookupTreatmentEffectListView(generics.ListAPIView):
    queryset = LookupTreatmentEffect.objects.all()
    serializer_class = LookupTreatmentEffectSerializer


class LookupStagingTypeListView(generics.ListAPIView):
    queryset = LookupStagingType.objects.all()
    serializer_class = LookupStagingTypeSerializer


class LookupSystemicTherapyRegimenListView(generics.ListAPIView):
    queryset = LookupSystemicTherapyRegimen.objects.all()
    serializer_class = LookupSystemicTherapyRegimenSerializer


class LookupRTLocationListView(generics.ListAPIView):
    queryset = LookupRTLocation.objects.all()
    serializer_class = LookupRTLocationSerializer


class LookupLaboratoryTestListView(generics.ListAPIView):
    queryset = LookupLaboratoryTest.objects.all()
    serializer_class = LookupLaboratoryTestSerializer


class LookupSymptomsListView(generics.ListAPIView):
    queryset = LookupSymptoms.objects.all()
    serializer_class = LookupSymptomsSerializer


class LookupSeverityListView(generics.ListAPIView):
    queryset = LookupSeverity.objects.all()
    serializer_class = LookupSeveritySerializer


class LookupIHCAntibodyListView(generics.ListAPIView):
    queryset = LookupIHCAntibody.objects.all()
    serializer_class = LookupIHCAntibodySerializer


class LookupComorbidityListView(generics.ListAPIView):
    queryset = LookupComorbidity.objects.all()
    serializer_class = LookupComorbiditySerializer


class LookupPerformanceStatusListView(generics.ListAPIView):
    queryset = LookupPerformanceStatus.objects.all()
    serializer_class = LookupPerformanceStatusSerializer


class LookupExpressionUnitsListView(generics.ListAPIView):
    queryset = LookupExpressionUnits.objects.all()
    serializer_class = LookupExpressionUnitsSerializer


class LookupCytogeneticAbnormalityListView(generics.ListAPIView):
    queryset = LookupCytogeneticAbnormality.objects.all()
    serializer_class = LookupCytogeneticAbnormalitySerializer


class LookupEpigeneticAbnormalityTypeListView(generics.ListAPIView):
    queryset = LookupEpigeneticAbnormalityType.objects.all()
    serializer_class = LookupEpigeneticAbnormalityTypeSerializer


class LookupSurgicalProceduresListView(generics.ListAPIView):
    queryset = LookupSurgicalProcedures.objects.all()
    serializer_class = LookupSurgicalProceduresSerializer


class LookupNodalAssessmentTypeListView(generics.ListAPIView):
    queryset = LookupNodalAssessmentType.objects.all()
    serializer_class = LookupNodalAssessmentTypeSerializer
