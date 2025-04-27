from django.contrib import admin
from lookup.models import *
from unfold.admin import ModelAdmin


# Register all Lookup Models.



@admin.register(LookupLaterality)
class LookupLateralityAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupICDCode)
class LookupICDCodeAdmin (ModelAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label','icd_version']


@admin.register(LookupFMACode)
class LookupFMACodeAdmin (ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupPresentation)
class LookupPresentationAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupOutcomeType)
class LookupOutcomeTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupLesionType)
class LookupLesionTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupResponseType)
class LookupResponseTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']

@admin.register(LookupProtein)
class LookupProteinAdmin(ModelAdmin):
    search_fields = ['protein_name']
    readonly_fields = ['code','gene_name','protein_name','all_gene_names','uniport_id']


@admin.register(LookupGene)
class LookupGeneAdmin(ModelAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label']


@admin.register(LookupTreatmentIntent)
class LookupTreatmentIntentAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupTreatmentSequence)
class LookupTreatmentSequenceAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupSystemicAgent)
class LookupSystemicAgentAdmin(ModelAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label']


@admin.register(LookupVolumeUnits)
class LookupVolumeUnitsAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupSizeUnits)
class LookupSizeUnitsAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupDoseUnits)
class LookupDoseUnitsAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupLabResultsUnits)
class LookupLabResultsUnitsAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupMassUnits)
class LookupMassUnitsAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupDrugRoute)
class LookupDrugRouteAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupCTCAEGrade)
class LookupCTCAEGradeAdmin(ModelAdmin):
    search_fields = ['ctcae_term','ctcae_grade']
    readonly_fields = ['code','ctcae_term','ctcae_grade','meddra_code','description']


@admin.register(LookupOutcome)
class LookupOutcomeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupStagingSystem)
class LookupStagingSystemAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupAJCCStagePrefix)
class LookupAJCCStagePrefixAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    


@admin.register(LookupAJCCStageSuffix)
class LookupAJCCStageSuffixAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupAJCCTStageDescriptor)
class LookupAJCCTStageDescriptorAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupAJCCNStageDescriptor)
class LookupAJCCNStageDescriptorAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupAJCCMStageDescriptor)
class LookupAJCCMStageDescriptorAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupStageDescriptor)
class LookupStageDescriptorAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupDiagnosticModality)
class LookupDiagnosticModalityAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupSystemicTherapyType)
class LookupSystemicTherapyTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupRadiotherapyVolumeType)
class LookupRadiotherapyVolumeTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupPathology)
class LookupPathologyAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupGrade)
class LookupGradeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupPathologyDescriptors)
class LookupPathologyDescriptorsAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupMajorCancerCategory)
class LookupMajorCancerCategoryAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupRadiotherapyModality)
class LookupRadiotherapyModalityAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupRadiotherapyType)
class LookupRadiotherapyTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupRadiotherapyTechnique)
class LookupRadiotherapyTechniqueAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupClinicalSignificance)
class LookupClinicalSignificanceAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupIHCResult)
class LookupIHCResultAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupIHCStainingIntensity)
class LookupIHCStainingIntensityAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupMarginStatus)
class LookupMarginStatusAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupTreatmentEffect)
class LookupTreatmentEffectAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    

@admin.register(LookupStagingType)
class LookupStagingTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupSystemicTherapyRegimen)
class LookupSystemicTherapyRegimenAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupRTLocation)
class LookupRTLocationAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupLaboratoryTest)
class LookupLaboratoryTestAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupSymptoms)
class LookupSymptomsAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']



@admin.register(LookupSeverity)
class LookupSeverityAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupIHCAntibody)
class LookupIHCAntibodyAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupComorbidity)
class LookupComorbidityAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupPerformanceStatus)
class LookupPerformanceStatusAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupExpressionUnits)
class LookupExpressionUnitsAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']



@admin.register(LookupCytogeneticAbnormality)
class LookupCytogeneticAbnormalityAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupEpigeneticAbnormalityType)
class LookupEpigeneticAbnormalityTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupSurgicalProcedures)
class LookupSurgicalProceduresAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupNodalAssessmentType)
class LookupNodalAssessmentTypeAdmin(ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']






