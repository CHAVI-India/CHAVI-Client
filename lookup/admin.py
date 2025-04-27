from django.contrib import admin
from lookup.models import *
from unfold.admin import ModelAdmin
from django.contrib import messages
from unfold.decorators import action
from lookup.services.sync_service import sync_model_from_api
from lookup.api_mappings import get_api_mapping


# Register all Lookup Models.

# Base ModelAdmin class with disabled add permissions
class ReadOnlyLookupAdmin(ModelAdmin):
    def has_add_permission(self, request):
        return False
        
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    @action(description="Sync selected models with external API")
    def sync_with_api(self, request, queryset):
        """
        Sync the model data with the external API.
        """
        model = self.model
        model_name = model._meta.verbose_name_plural.title()
        model_name_lower = model._meta.model_name.lower()
        
        # Get API mapping for this model
        api_mapping = get_api_mapping(model_name_lower)
        api_endpoint = api_mapping['endpoint']
        pk_field = api_mapping['pk_field']
        
        # Perform synchronization with API
        created, updated, errors = sync_model_from_api(
            model_class=model,
            endpoint=api_endpoint,
            pk_field=pk_field
        )
        
        # Show results to user
        if errors:
            messages.error(
                request, 
                f"Sync completed with errors: {created} created, {updated} updated. "
                f"Errors: {'; '.join(errors[:5])}{' ...' if len(errors) > 5 else ''}"
            )
        else:
            messages.success(
                request,
                f"Successfully synced {model_name} with API: {created} created, {updated} updated."
            )


@admin.register(LookupLaterality)
class LookupLateralityAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']


@admin.register(LookupICDCode)
class LookupICDCodeAdmin (ReadOnlyLookupAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label','icd_version']
    actions = ['sync_with_api']
    list_display = ['code','label','icd_version']


@admin.register(LookupFMACode)
class LookupFMACodeAdmin (ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']


@admin.register(LookupPresentation)
class LookupPresentationAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupOutcomeType)
class LookupOutcomeTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupLesionType)
class LookupLesionTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupResponseType)
class LookupResponseTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']
@admin.register(LookupProtein)
class LookupProteinAdmin(ReadOnlyLookupAdmin):
    search_fields = ['protein_name']
    readonly_fields = ['code','gene_name','protein_name','all_gene_names','uniport_id']
    actions = ['sync_with_api']
    list_display = ['code','gene_name','protein_name','all_gene_names','uniport_id']


@admin.register(LookupGene)
class LookupGeneAdmin(ReadOnlyLookupAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupTreatmentIntent)
class LookupTreatmentIntentAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupTreatmentSequence)
class LookupTreatmentSequenceAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupSystemicAgent)
class LookupSystemicAgentAdmin(ReadOnlyLookupAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupVolumeUnits)
class LookupVolumeUnitsAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupSizeUnits)
class LookupSizeUnitsAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupDoseUnits)
class LookupDoseUnitsAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupLabResultsUnits)
class LookupLabResultsUnitsAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupMassUnits)
class LookupMassUnitsAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupDrugRoute)
class LookupDrugRouteAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupCTCAEGrade)
class LookupCTCAEGradeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['ctcae_term','ctcae_grade']
    readonly_fields = ['code','ctcae_term','ctcae_grade','meddra_code','description']
    actions = ['sync_with_api']
    list_display = ['code','ctcae_term','ctcae_grade','meddra_code','description']

@admin.register(LookupOutcome)
class LookupOutcomeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupStagingSystem)
class LookupStagingSystemAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupAJCCStagePrefix)
class LookupAJCCStagePrefixAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']


@admin.register(LookupAJCCStageSuffix)
class LookupAJCCStageSuffixAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupAJCCTStageDescriptor)
class LookupAJCCTStageDescriptorAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupAJCCNStageDescriptor)
class LookupAJCCNStageDescriptorAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupAJCCMStageDescriptor)
class LookupAJCCMStageDescriptorAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupStageDescriptor)
class LookupStageDescriptorAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupDiagnosticModality)
class LookupDiagnosticModalityAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupSystemicTherapyType)
class LookupSystemicTherapyTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupRadiotherapyVolumeType)
class LookupRadiotherapyVolumeTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupPathology)
class LookupPathologyAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupGrade)
class LookupGradeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupPathologyDescriptors)
class LookupPathologyDescriptorsAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api'] 
    list_display = ['code','label']

@admin.register(LookupMajorCancerCategory)
class LookupMajorCancerCategoryAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupRadiotherapyModality)
class LookupRadiotherapyModalityAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupRadiotherapyType)
class LookupRadiotherapyTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupRadiotherapyTechnique)
class LookupRadiotherapyTechniqueAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupClinicalSignificance)
class LookupClinicalSignificanceAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']
    

@admin.register(LookupIHCResult)
class LookupIHCResultAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupIHCStainingIntensity)
class LookupIHCStainingIntensityAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupMarginStatus)
class LookupMarginStatusAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupTreatmentEffect)
class LookupTreatmentEffectAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupStagingType)
class LookupStagingTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupSystemicTherapyRegimen)
class LookupSystemicTherapyRegimenAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupRTLocation)
class LookupRTLocationAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api'] 
    list_display = ['code','label']

@admin.register(LookupLaboratoryTest)
class LookupLaboratoryTestAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupSymptoms)
class LookupSymptomsAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label'] 


@admin.register(LookupSeverity)
class LookupSeverityAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupIHCAntibody)
class LookupIHCAntibodyAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupComorbidity)
class LookupComorbidityAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupPerformanceStatus)
class LookupPerformanceStatusAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupExpressionUnits)
class LookupExpressionUnitsAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']


@admin.register(LookupCytogeneticAbnormality)
class LookupCytogeneticAbnormalityAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupEpigeneticAbnormalityType)
class LookupEpigeneticAbnormalityTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupSurgicalProcedures)
class LookupSurgicalProceduresAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label']

@admin.register(LookupNodalAssessmentType)
class LookupNodalAssessmentTypeAdmin(ReadOnlyLookupAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']
    actions = ['sync_with_api']
    list_display = ['code','label'] 





