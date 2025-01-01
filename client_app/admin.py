from django.contrib import admin
from solo.admin import SingletonModelAdmin
from .models import *
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from unfold.contrib.inlines.admin import NonrelatedTabularInline
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget

#region inlinetables

# Define inlines for Many to Many relations
class PatientProjectInline(TabularInline):
    model = PatientProject
    extra = 1

class DiagnosisDICOMStudyInline(TabularInline):
    model = DiagnosisDICOMStudy
    extra = 1

class LesionDICOMStudyInline(TabularInline):
    model = LesionDICOMStudy
    extra = 1

class LesionResponseDICOMStudyInline(TabularInline):
    model = LesionResponseDICOMStudy
    extra = 1

class DiagnosisProjectInline(TabularInline):
    model = DiagnosisProject
    extra = 1

class RadiotherapyDICOMStudyInline(TabularInline):
    model = RadiotherapyDICOMStudy
    extra = 1

class OutcomeDICOMStudyInline(TabularInline):
    model = OutcomeDICOMStudy
    extra = 1

class DICOMStudyProjectInline(TabularInline):
    model = DICOMStudyProject
    extra = 1

#endregion

#region Inlines for Foreign Key relations.

class SystemicTherapyScheduleInline(StackedInline):
    model = SystemicTherapySchedule
    extra = 1
    fieldsets = (
        ('Schedule',{
            'fields': [('systemic_therapy_agent_start_date','systemic_therapy_agent_end_date')]

        }),
        ('Medication',{
            'fields': [('systemic_therapy_agent_route','systemic_therapy_agent'),('systemic_therapy_dose_planned','systemic_therapy_dose_administered','systemic_therapy_dose_units')]
        }),

    )   

class ImmunohistochemistryInline(StackedInline):
    model = Immunohistochemistry
    extra = 1
    tab = True

class CytogeneticsInline(StackedInline):
    model = Cytogenetics
    extra = 1
    tab = True

class SomaticGenomicAlterationsInline(StackedInline):
    model = SomaticGenomicAlterations
    extra = 1
    tab = True

#endregion

#region modelclasses

# Add Model classes

## Create the Patient Form Class
@admin.register(Patient)
class PatientAdmin (ModelAdmin):
    inlines = [PatientProjectInline]
    list_filter = ['gender','chavi_consent','created_at']
    search_fields =[ 'patient_id']
    list_display = ['patient_id','gender','date_of_birth','chavi_consent','date_chavi_consent','created_at']
    fieldsets = (
        ('Demographics',{
            'fields': ['patient_id',('gender','date_of_birth','center')]
        }),
        ('CHAVI Consent',{
            'fields': [('chavi_consent','date_chavi_consent')]
        }),
    )
    readonly_fields = ('center',)

## Create the Diagnosis Form Class
@admin.register(Diagnosis)
class DiagnosisAdmin (ModelAdmin):
    inlines = [DiagnosisDICOMStudyInline,DiagnosisProjectInline]
    search_fields = ['patient']
    list_filter = ['diagnosis','diagnostic_modality','cancer_site','cancer_side']
    list_fields = ['patient','diagnosis','diagnosis_date','diagnostic_modality','presentation_type','cancer_site','cancer_side']
    fieldsets = (
        ('Diagnosis',{
            'fields': ['patient',('diagnosis','diagnosis_date','diagnostic_modality')]
        }),
        ('Presentation',{
            "fields": [('presentation_type','cancer_site','cancer_side')]
        }),    
    )


## Create the Pathology Form Class
@admin.register(Pathology)
class PathologyAdmin (ModelAdmin):
    inlines = [ImmunohistochemistryInline,CytogeneticsInline,SomaticGenomicAlterationsInline]
    search_fields = ['diagnosis__patient_id']
    list_filter = ['diagnosis','tumor_site','tumor_side','histological_type']
    list_display = ['diagnosis','date_pathology','tumor_site','tumor_side','histological_type','lymph_nodes_in_specimen']
    fieldsets = (
        ('Pathology',{
            'fields': ['diagnosis',('date_pathology','specimen_type'),('tumor_site','tumor_side'),('greatest_dimension_of_tumor','additional_tumor_dimension_1','additional_tumor_dimension_2'),'tumor_focality']
        }),
        ('Histology',{
            'fields': [('histological_type','histological_subtype'),('histological_grade','histological_grading_schema'),('lymphatic_vascular_invasion','perineural_invasion','dermal_lymphatic_vascular_invasion')]
        }),
        ('Nodes',{
            'fields': [('lymph_nodes_removed','lymph_nodes_in_specimen'),('number_of_nodes_with_macrometastases','number_of_nodes_with_micrometastases','number_of_nodes_with_isolated_tumor_cells')]
        }),
    )

## Create the Stage Information Form Class
@admin.register(StageInformation)
class StageInformationAdmin (ModelAdmin):
    search = ['diagnosis__patient_id']
    list_display = ['diagnosis__patient','staging_system','stage_type','overall_stage']
    fieldsets = (
        ('Stage Information',{
            'fields' : ['diagnosis',('staging_system','stage_type')] 
        }),
        ('AJCC T Stage',{
            'fields' : [('t_stage_prefix','t_stage','t_stage_suffix')]
        }),
        ('AJCC N Stage',{
            'fields' : [('n_stage_prefix','n_stage','n_stage_suffix')]
        }),
        ('AJCC M Stage',{
            'fields' : [('m_stage_prefix','m_stage','m_stage_suffix')]
        }),
        ('Overall Stage',{
            'fields' : ['overall_stage']
        }),
    )


## Create the Comorbidity Form

@admin.register(Comorbidity)
class ComorbidityAdmin (ModelAdmin):
    pass


## Create the Lesion Form Class
@admin.register(Lesion)
class LesionAdmin (ModelAdmin):
    inlines = [LesionDICOMStudyInline]

## Create the Lesion Response Form Class
@admin.register(LesionResponse)
class LesionResponseAdmin (ModelAdmin):
    inlines = [LesionResponseDICOMStudyInline]

## Create the Radiotherapy Form Class

@admin.register(Radiotherapy)
class RadiotherapyAdmin (ModelAdmin):
    inlines=[RadiotherapyDICOMStudyInline]
    fieldsets = (
        ('Radiotherapy',{
            'fields': ['diagnosis',('radiotherapy_start_date','radiotherapy_end_date'),('radiotherapy_site','radiotherapy_side'),'treatment_volume']
        }),
        ('Description',{
            'fields': ['radiotherapy_modality','radiotherapy_type',('total_dose','total_fractions','fractions_per_day')]
        }),
    )        

## Create the Surgery Form Class
@admin.register(Surgery)
class SurgeryAdmin (ModelAdmin):
    fieldsets = (
        ('Surgery', {
            'fields':['diagnosis','surgery_date']
        }),
        ('Description',{
            'fields':['surgery_site',('surgery_side','surgery_type'),('nodal_assessment','nodal_assessment_type')]
        }),
        ('Reconstruction',{
            'fields':['reconstruction','type_reconstruction']
        }),
    )

## Create the Systemic Therapy Form Class
@admin.register(SystemicTherapy)
class SystemicTherapyAdmin (ModelAdmin):
    inlines = [SystemicTherapyScheduleInline]
    fieldsets = (
        ('Systemic Therapy',{
            'fields':['diagnosis',('systemic_therapy_start_date','systemic_therapy_end_date')]
        }),
        ('Description',{
            'fields':[('systemic_therapy_type','systemic_therapy_sequence'),('systemic_therapy_regimen','cycles_delivered')]
        }),
    )

## Create the ConcomitantMedications Form Class
@admin.register(ConcomitantMedications)
class ConcomitantMedicationsAdmin (ModelAdmin):
    fieldsets = (
        ('Concomitant Medications',{
            'fields':['diagnosis',('medication_name','medication_route'),('medication_dose','medication_dose_units'),('date_medication_start_date', 'date_medication_end_date')]
        }),
    )


## Create the Other Treatment Form Class
@admin.register(OtherTreatment)
class OtherTreatmentAdmin (ModelAdmin):
    fieldsets = (
        ('Description',{
            'fields':['diagnosis',('treatment_start_date','treatment_end_date'),'treatment']
        }),
    )


## Create the Adverse Effects form class
@admin.register(AdverseEffects)
class AdverseEffectsAdmin (ModelAdmin):
    list_fields = [ 'diagnosis', 'adverse_effect_start_date', 'adverse_effect_end_date', 'ctcae_grade_lookup', 'adverse_effect_grade']
    fieldsets = (
        ('Adverse Effects',{
            'fields':['diagnosis',('adverse_effect_start_date','adverse_effect_end_date')]
        }),
        ('Description',{
            'fields':[('ctcae_grade_lookup','adverse_effect_type','adverse_effect_grade')]
        }),
    )


## Create the Patient Outcomes form class

@admin.register(PatientOutcome)
class PatientOutcomeAdmin (ModelAdmin):
    fieldsets = (
        ('Patient Outcome',{
            'fields':['patient',('patient_status','date_of_death')]
        }),
        ('Description',{
            'fields':[('primary_cause_of_death','secondary_cause_of_death','tertiary_cause_of_death')]
        }),
    )

## Create the Outcome Form Class
@admin.register(Outcome)
class OutcomeAdmin (ModelAdmin):
    fieldsets = (
        ('Diagnosis',{
            'fields':[('diagnosis')]
        }),
        ('Description',{
            'fields':[('outcome_type','date_outcome_assessed')]
        }),
    )

#endregion

## Create the Patient Reported Outcome Form Class
@admin.register(PatientReportedOutcome)
class PatientReportedOutcomeAdmin (ModelAdmin):
    fieldsets = (
        ('Patient',{
            'fields':[('patient','pro_date')]
        }),
        ('PRO Data',{
            'fields':[('instrument','domain'),'question',('pro_answer','pro_score')]
        }),
    )



## Create the DICOM Study form Class
@admin.register(DICOMStudy)
class DICOMStudyAdmin (ModelAdmin):
    fieldsets = (
        ('Patient',{
            'fields':[('patient','study_date')]
        }),
        ('Study Data',{
            'fields':[('study_instance_uid','modality')]
        }),
    )



## Create the Project form Class
@admin.register(Project)
class ProjectAdmin(ModelAdmin):
    inlines = [DICOMStudyProjectInline]
    fieldsets = (
        ('Project',{
            'fields':[('chavi_project_id','project_name','project_abbreviation'),'description','license']
        }),
        ('Dates',{
            'fields':[('start_date','completion_date'),('project_irb_approval','project_irb_approval_number')]
        }),
    )




# Register your models here.
admin.site.register(SiteConfiguration,SingletonModelAdmin)
