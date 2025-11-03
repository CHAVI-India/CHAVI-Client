"""
DRF ViewSets for all Lookup models
"""
from rest_framework import viewsets, filters
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
    LookupAJCCStagePrefixSerializer, LookupAJCCStageSuffixSerializer, LookupAJCCTStageDescriptorSerializer,
    LookupAJCCNStageDescriptorSerializer, LookupAJCCMStageDescriptorSerializer, LookupStageDescriptorSerializer,
    LookupDiagnosticModalitySerializer, LookupSystemicTherapyTypeSerializer, LookupRadiotherapyVolumeTypeSerializer,
    LookupPathologySerializer, LookupGradeSerializer, LookupPathologyDescriptorsSerializer,
    LookupMajorCancerCategorySerializer, LookupRadiotherapyModalitySerializer, LookupRadiotherapyTypeSerializer,
    LookupRadiotherapyTechniqueSerializer, LookupClinicalSignificanceSerializer, LookupIHCResultSerializer,
    LookupIHCStainingIntensitySerializer, LookupMarginStatusSerializer, LookupTreatmentEffectSerializer,
    LookupStagingTypeSerializer, LookupSystemicTherapyRegimenSerializer, LookupRTLocationSerializer,
    LookupLaboratoryTestSerializer, LookupSymptomsSerializer, LookupSeveritySerializer,
    LookupIHCAntibodySerializer, LookupComorbiditySerializer, LookupPerformanceStatusSerializer,
    LookupExpressionUnitsSerializer, LookupCytogeneticAbnormalitySerializer, LookupEpigeneticAbnormalityTypeSerializer,
    LookupSurgicalProceduresSerializer, LookupNodalAssessmentTypeSerializer
)


class BaseLookupViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Base ViewSet for lookup tables with read-only access.
    Provides search and ordering capabilities.
    """
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'label']
    ordering_fields = ['code', 'label']
    ordering = ['code']


class LookupLateralityViewSet(BaseLookupViewSet):
    """API endpoint for Laterality lookup data"""
    queryset = LookupLaterality.objects.all()
    serializer_class = LookupLateralitySerializer


class LookupICDCodeViewSet(BaseLookupViewSet):
    """API endpoint for ICD Code lookup data"""
    queryset = LookupICDCode.objects.all()
    serializer_class = LookupICDCodeSerializer
    search_fields = ['code', 'label', 'icd_version']


class LookupFMACodeViewSet(BaseLookupViewSet):
    """API endpoint for FMA Code lookup data"""
    queryset = LookupFMACode.objects.all()
    serializer_class = LookupFMACodeSerializer


class LookupPresentationViewSet(BaseLookupViewSet):
    """API endpoint for Presentation lookup data"""
    queryset = LookupPresentation.objects.all()
    serializer_class = LookupPresentationSerializer


class LookupOutcomeTypeViewSet(BaseLookupViewSet):
    """API endpoint for Outcome Type lookup data"""
    queryset = LookupOutcomeType.objects.all()
    serializer_class = LookupOutcomeTypeSerializer


class LookupLesionTypeViewSet(BaseLookupViewSet):
    """API endpoint for Lesion Type lookup data"""
    queryset = LookupLesionType.objects.all()
    serializer_class = LookupLesionTypeSerializer


class LookupResponseTypeViewSet(BaseLookupViewSet):
    """API endpoint for Response Type lookup data"""
    queryset = LookupResponseType.objects.all()
    serializer_class = LookupResponseTypeSerializer


class LookupProteinViewSet(BaseLookupViewSet):
    """API endpoint for Protein lookup data"""
    queryset = LookupProtein.objects.all()
    serializer_class = LookupProteinSerializer
    search_fields = ['code', 'gene_name', 'protein_name', 'all_gene_names']


class LookupGeneViewSet(BaseLookupViewSet):
    """API endpoint for Gene lookup data"""
    queryset = LookupGene.objects.all()
    serializer_class = LookupGeneSerializer


class LookupTreatmentIntentViewSet(BaseLookupViewSet):
    """API endpoint for Treatment Intent lookup data"""
    queryset = LookupTreatmentIntent.objects.all()
    serializer_class = LookupTreatmentIntentSerializer


class LookupTreatmentSequenceViewSet(BaseLookupViewSet):
    """API endpoint for Treatment Sequence lookup data"""
    queryset = LookupTreatmentSequence.objects.all()
    serializer_class = LookupTreatmentSequenceSerializer


class LookupSystemicAgentViewSet(BaseLookupViewSet):
    """API endpoint for Systemic Agent lookup data"""
    queryset = LookupSystemicAgent.objects.all()
    serializer_class = LookupSystemicAgentSerializer


class LookupVolumeUnitsViewSet(BaseLookupViewSet):
    """API endpoint for Volume Units lookup data"""
    queryset = LookupVolumeUnits.objects.all()
    serializer_class = LookupVolumeUnitsSerializer
    search_fields = ['code', 'label', 'unit_abbreviation']


class LookupSizeUnitsViewSet(BaseLookupViewSet):
    """API endpoint for Size Units lookup data"""
    queryset = LookupSizeUnits.objects.all()
    serializer_class = LookupSizeUnitsSerializer
    search_fields = ['code', 'label', 'unit_abbreviation']


class LookupDoseUnitsViewSet(BaseLookupViewSet):
    """API endpoint for Dose Units lookup data"""
    queryset = LookupDoseUnits.objects.all()
    serializer_class = LookupDoseUnitsSerializer
    search_fields = ['code', 'label', 'unit_abbreviation']


class LookupLabResultsUnitsViewSet(BaseLookupViewSet):
    """API endpoint for Lab Results Units lookup data"""
    queryset = LookupLabResultsUnits.objects.all()
    serializer_class = LookupLabResultsUnitsSerializer
    search_fields = ['code', 'label', 'unit_abbreviation']


class LookupMassUnitsViewSet(BaseLookupViewSet):
    """API endpoint for Mass Units lookup data"""
    queryset = LookupMassUnits.objects.all()
    serializer_class = LookupMassUnitsSerializer
    search_fields = ['code', 'label', 'unit_abbreviation']


class LookupDrugRouteViewSet(BaseLookupViewSet):
    """API endpoint for Drug Route lookup data"""
    queryset = LookupDrugRoute.objects.all()
    serializer_class = LookupDrugRouteSerializer


class LookupCTCAEGradeViewSet(BaseLookupViewSet):
    """API endpoint for CTCAE Grade lookup data"""
    queryset = LookupCTCAEGrade.objects.all()
    serializer_class = LookupCTCAEGradeSerializer
    search_fields = ['code', 'ctcae_term', 'meddra_code', 'description']
    ordering_fields = ['code', 'ctcae_term', 'ctcae_grade']


class LookupOutcomeViewSet(BaseLookupViewSet):
    """API endpoint for Outcome lookup data"""
    queryset = LookupOutcome.objects.all()
    serializer_class = LookupOutcomeSerializer


class LookupStagingSystemViewSet(BaseLookupViewSet):
    """API endpoint for Staging System lookup data"""
    queryset = LookupStagingSystem.objects.all()
    serializer_class = LookupStagingSystemSerializer
    search_fields = ['code', 'label', 'staging_system_version']


class LookupAJCCStagePrefixViewSet(BaseLookupViewSet):
    """API endpoint for AJCC Stage Prefix lookup data"""
    queryset = LookupAJCCStagePrefix.objects.all()
    serializer_class = LookupAJCCStagePrefixSerializer


class LookupAJCCStageSuffixViewSet(BaseLookupViewSet):
    """API endpoint for AJCC Stage Suffix lookup data"""
    queryset = LookupAJCCStageSuffix.objects.all()
    serializer_class = LookupAJCCStageSuffixSerializer


class LookupAJCCTStageDescriptorViewSet(BaseLookupViewSet):
    """API endpoint for AJCC T Stage Descriptor lookup data"""
    queryset = LookupAJCCTStageDescriptor.objects.all()
    serializer_class = LookupAJCCTStageDescriptorSerializer


class LookupAJCCNStageDescriptorViewSet(BaseLookupViewSet):
    """API endpoint for AJCC N Stage Descriptor lookup data"""
    queryset = LookupAJCCNStageDescriptor.objects.all()
    serializer_class = LookupAJCCNStageDescriptorSerializer


class LookupAJCCMStageDescriptorViewSet(BaseLookupViewSet):
    """API endpoint for AJCC M Stage Descriptor lookup data"""
    queryset = LookupAJCCMStageDescriptor.objects.all()
    serializer_class = LookupAJCCMStageDescriptorSerializer


class LookupStageDescriptorViewSet(BaseLookupViewSet):
    """API endpoint for Stage Descriptor lookup data"""
    queryset = LookupStageDescriptor.objects.all()
    serializer_class = LookupStageDescriptorSerializer


class LookupDiagnosticModalityViewSet(BaseLookupViewSet):
    """API endpoint for Diagnostic Modality lookup data"""
    queryset = LookupDiagnosticModality.objects.all()
    serializer_class = LookupDiagnosticModalitySerializer


class LookupSystemicTherapyTypeViewSet(BaseLookupViewSet):
    """API endpoint for Systemic Therapy Type lookup data"""
    queryset = LookupSystemicTherapyType.objects.all()
    serializer_class = LookupSystemicTherapyTypeSerializer


class LookupRadiotherapyVolumeTypeViewSet(BaseLookupViewSet):
    """API endpoint for Radiotherapy Volume Type lookup data"""
    queryset = LookupRadiotherapyVolumeType.objects.all()
    serializer_class = LookupRadiotherapyVolumeTypeSerializer


class LookupPathologyViewSet(BaseLookupViewSet):
    """API endpoint for Pathology lookup data"""
    queryset = LookupPathology.objects.all()
    serializer_class = LookupPathologySerializer


class LookupGradeViewSet(BaseLookupViewSet):
    """API endpoint for Grade lookup data"""
    queryset = LookupGrade.objects.all()
    serializer_class = LookupGradeSerializer


class LookupPathologyDescriptorsViewSet(BaseLookupViewSet):
    """API endpoint for Pathology Descriptors lookup data"""
    queryset = LookupPathologyDescriptors.objects.all()
    serializer_class = LookupPathologyDescriptorsSerializer


class LookupMajorCancerCategoryViewSet(BaseLookupViewSet):
    """API endpoint for Major Cancer Category lookup data"""
    queryset = LookupMajorCancerCategory.objects.all()
    serializer_class = LookupMajorCancerCategorySerializer


class LookupRadiotherapyModalityViewSet(BaseLookupViewSet):
    """API endpoint for Radiotherapy Modality lookup data"""
    queryset = LookupRadiotherapyModality.objects.all()
    serializer_class = LookupRadiotherapyModalitySerializer


class LookupRadiotherapyTypeViewSet(BaseLookupViewSet):
    """API endpoint for Radiotherapy Type lookup data"""
    queryset = LookupRadiotherapyType.objects.all()
    serializer_class = LookupRadiotherapyTypeSerializer


class LookupRadiotherapyTechniqueViewSet(BaseLookupViewSet):
    """API endpoint for Radiotherapy Technique lookup data"""
    queryset = LookupRadiotherapyTechnique.objects.all()
    serializer_class = LookupRadiotherapyTechniqueSerializer


class LookupClinicalSignificanceViewSet(BaseLookupViewSet):
    """API endpoint for Clinical Significance lookup data"""
    queryset = LookupClinicalSignificance.objects.all()
    serializer_class = LookupClinicalSignificanceSerializer


class LookupIHCResultViewSet(BaseLookupViewSet):
    """API endpoint for IHC Result lookup data"""
    queryset = LookupIHCResult.objects.all()
    serializer_class = LookupIHCResultSerializer


class LookupIHCStainingIntensityViewSet(BaseLookupViewSet):
    """API endpoint for IHC Staining Intensity lookup data"""
    queryset = LookupIHCStainingIntensity.objects.all()
    serializer_class = LookupIHCStainingIntensitySerializer


class LookupMarginStatusViewSet(BaseLookupViewSet):
    """API endpoint for Margin Status lookup data"""
    queryset = LookupMarginStatus.objects.all()
    serializer_class = LookupMarginStatusSerializer


class LookupTreatmentEffectViewSet(BaseLookupViewSet):
    """API endpoint for Treatment Effect lookup data"""
    queryset = LookupTreatmentEffect.objects.all()
    serializer_class = LookupTreatmentEffectSerializer


class LookupStagingTypeViewSet(BaseLookupViewSet):
    """API endpoint for Staging Type lookup data"""
    queryset = LookupStagingType.objects.all()
    serializer_class = LookupStagingTypeSerializer


class LookupSystemicTherapyRegimenViewSet(BaseLookupViewSet):
    """API endpoint for Systemic Therapy Regimen lookup data"""
    queryset = LookupSystemicTherapyRegimen.objects.all()
    serializer_class = LookupSystemicTherapyRegimenSerializer


class LookupRTLocationViewSet(BaseLookupViewSet):
    """API endpoint for RT Location lookup data"""
    queryset = LookupRTLocation.objects.all()
    serializer_class = LookupRTLocationSerializer


class LookupLaboratoryTestViewSet(BaseLookupViewSet):
    """API endpoint for Laboratory Test lookup data"""
    queryset = LookupLaboratoryTest.objects.all()
    serializer_class = LookupLaboratoryTestSerializer


class LookupSymptomsViewSet(BaseLookupViewSet):
    """API endpoint for Symptoms lookup data"""
    queryset = LookupSymptoms.objects.all()
    serializer_class = LookupSymptomsSerializer


class LookupSeverityViewSet(BaseLookupViewSet):
    """API endpoint for Severity lookup data"""
    queryset = LookupSeverity.objects.all()
    serializer_class = LookupSeveritySerializer


class LookupIHCAntibodyViewSet(BaseLookupViewSet):
    """API endpoint for IHC Antibody lookup data"""
    queryset = LookupIHCAntibody.objects.all()
    serializer_class = LookupIHCAntibodySerializer


class LookupComorbidityViewSet(BaseLookupViewSet):
    """API endpoint for Comorbidity lookup data"""
    queryset = LookupComorbidity.objects.all()
    serializer_class = LookupComorbiditySerializer


class LookupPerformanceStatusViewSet(BaseLookupViewSet):
    """API endpoint for Performance Status lookup data"""
    queryset = LookupPerformanceStatus.objects.all()
    serializer_class = LookupPerformanceStatusSerializer


class LookupExpressionUnitsViewSet(BaseLookupViewSet):
    """API endpoint for Expression Units lookup data"""
    queryset = LookupExpressionUnits.objects.all()
    serializer_class = LookupExpressionUnitsSerializer


class LookupCytogeneticAbnormalityViewSet(BaseLookupViewSet):
    """API endpoint for Cytogenetic Abnormality lookup data"""
    queryset = LookupCytogeneticAbnormality.objects.all()
    serializer_class = LookupCytogeneticAbnormalitySerializer


class LookupEpigeneticAbnormalityTypeViewSet(BaseLookupViewSet):
    """API endpoint for Epigenetic Abnormality Type lookup data"""
    queryset = LookupEpigeneticAbnormalityType.objects.all()
    serializer_class = LookupEpigeneticAbnormalityTypeSerializer


class LookupSurgicalProceduresViewSet(BaseLookupViewSet):
    """API endpoint for Surgical Procedures lookup data"""
    queryset = LookupSurgicalProcedures.objects.all()
    serializer_class = LookupSurgicalProceduresSerializer
    search_fields = ['code', 'label', 'description']


class LookupNodalAssessmentTypeViewSet(BaseLookupViewSet):
    """API endpoint for Nodal Assessment Type lookup data"""
    queryset = LookupNodalAssessmentType.objects.all()
    serializer_class = LookupNodalAssessmentTypeSerializer
