from django.contrib import admin
from solo.admin import SingletonModelAdmin
from .models import *


#region inlinetables

# Define inlines for Many to Many relations
class PatientProjectInline(admin.TabularInline):
    model = PatientProject
    extra = 1

class DiagnosisDICOMStudyInline(admin.TabularInline):
    model = DiagnosisDICOMStudy
    extra = 1

class LesionDICOMStudyInline(admin.TabularInline):
    model = LesionDICOMStudy
    extra = 1

class LesionResponseDICOMStudyInline(admin.TabularInline):
    model = LesionResponseDICOMStudy
    extra = 1

class DiagnosisProjectInline(admin.TabularInline):
    model = DiagnosisProject
    extra = 1

class RadiotherapyDICOMStudyInline(admin.TabularInline):
    model = RadiotherapyDICOMStudy
    extra = 1

class SurgeryDICOMStudyInline(admin.TabularInline):
    model = SurgeryDICOMStudy
    extra = 1

class SystemicTherapyDICOMStudyInline(admin.TabularInline):
    model = SystemicTherapyDICOMStudy
    extra = 1


class OutcomeDICOMStudyInline(admin.TabularInline):
    model = OutcomeDICOMStudy
    extra = 1

class DICOMStudyProjectInline(admin.TabularInline):
    model = DICOMStudyProject
    extra = 1

#endregion

#region Inlines for Foreign Key relations.

class SystemicTherapyScheduleInline(admin.StackedInline):
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
       

class ImmunohistochemistryInline(admin.StackedInline):
    model = Immunohistochemistry
    extra = 1
    

class CytogeneticsInline(admin.StackedInline):
    model = Cytogenetics
    extra = 1
    

class SomaticGenomicAlterationsInline(admin.StackedInline):
    model = SomaticGenomicAlterations
    extra = 1
    

class RadiotherapyVolumeInline(admin.StackedInline):
    model = RadiotherapyVolume
    extra = 1
    fieldsets = (
        ('Volume Description',{
            'fields': [('volume_name','volume_type'),('volume_dose_prescribed','radiation_dose_units','volume_fractions'),('volume_radiotherapy_start_date','volume_radiotherapy_end_date')]
        }),
    )
    tab=True

class RadiotherapyDoseVolumeDataInline(admin.TabularInline):
    model = RadiotherapyDoseVolumeData
    extra = 1
    


#endregion

#region modelclasses

# Add Model classes

## Create the Patient Form Class
@admin.register(Patient)
class PatientAdmin (admin.ModelAdmin):
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

@admin.register(PatientDicomFile)
class PatientDicomFileAdmin (admin.ModelAdmin):
    list_filter = ['patient','created_at']
    search_fields =[ 'patient__patient_id']
    list_display = ['patient','file','created_at']
    fieldsets = (
        ('Patient DICOM File',{
            'fields': ['patient','file']  
        }),
    )

        
## Create the Diagnosis Form Class
@admin.register(Diagnosis)
class DiagnosisAdmin (admin.ModelAdmin):
    inlines = [DiagnosisDICOMStudyInline,DiagnosisProjectInline]
    search_fields = ['patient']
    list_filter = ['diagnosis__icd_description','diagnostic_modality','cancer_site__label','cancer_side__side_description']
    list_fields = ['patient','diagnosis','diagnosis_date','diagnostic_modality','presentation_type','cancer_site__label','cancer_side__side_description']
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
class PathologyAdmin (admin.ModelAdmin):
    inlines = [ImmunohistochemistryInline,CytogeneticsInline,SomaticGenomicAlterationsInline]
    search_fields = ['diagnosis__patient_id']
    list_filter = ['diagnosis','tumor_site__label','tumor_side__side_description','histological_type']
    list_display = ['diagnosis__patient_id','diagnosis','date_pathology','tumor_site__label','tumor_side__side_description','histological_type','lymph_nodes_in_specimen']
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
class StageInformationAdmin (admin.ModelAdmin):
    search = ['diagnosis__patient_id']
    list_filter = ['diagnosis','staging_system__staging_system','stage_type','overall_stage']
    list_display = ['diagnosis__patient','staging_system__staging_system','stage_type','overall_stage']
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
class ComorbidityAdmin (admin.ModelAdmin):
    list_display = ['patient','comorbidity_type','created_at']
    list_filter = ['comorbidity_type__icd_description','created_at']


## Create the Lesion Form Class
@admin.register(Lesion)
class LesionAdmin (admin.ModelAdmin):
    inlines = [LesionDICOMStudyInline]

## Create the Lesion Response Form Class
@admin.register(LesionResponse)
class LesionResponseAdmin (admin.ModelAdmin):
    inlines = [LesionResponseDICOMStudyInline]

## Create the Radiotherapy Form Class

@admin.register(Radiotherapy)
class RadiotherapyAdmin (admin.ModelAdmin):
    inlines=[RadiotherapyVolumeInline,RadiotherapyDICOMStudyInline,RadiotherapyDoseVolumeDataInline]
    fieldsets = (
        ('Radiotherapy',{
            'fields': ['diagnosis',('radiotherapy_start_date','radiotherapy_end_date'),('radiotherapy_site','radiotherapy_side')]
        }),
        ('Description',{
            'fields': [('radiotherapy_modality','radiotherapy_type','radiotherapy_machine'),('total_dose','radiation_dose_units'),('total_fractions','fractions_per_day')]
        }),
    )        

## Create the Surgery Form Class
@admin.register(Surgery)
class SurgeryAdmin (admin.ModelAdmin):
    inlines = [SurgeryDICOMStudyInline]
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
class SystemicTherapyAdmin (admin.ModelAdmin):
    inlines = [SystemicTherapyScheduleInline,SystemicTherapyDICOMStudyInline]
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
class ConcomitantMedicationsAdmin (admin.ModelAdmin):
    fieldsets = (
        ('Concomitant Medications',{
            'fields':['diagnosis',('medication_name','medication_route'),('medication_dose','medication_dose_units'),('date_medication_start_date', 'date_medication_end_date')]
        }),
    )


## Create the Other Treatment Form Class
@admin.register(OtherTreatment)
class OtherTreatmentAdmin (admin.ModelAdmin):
    fieldsets = (
        ('Description',{
            'fields':['diagnosis',('treatment_start_date','treatment_end_date'),'treatment']
        }),
    )


## Create the Adverse Effects form class
@admin.register(AdverseEffects)
class AdverseEffectsAdmin (admin.ModelAdmin):
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
class PatientOutcomeAdmin (admin.ModelAdmin):
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
class OutcomeAdmin (admin.ModelAdmin):
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
class PatientReportedOutcomeAdmin (admin.ModelAdmin):
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
class DICOMStudyAdmin (admin.ModelAdmin):
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
class ProjectAdmin(admin.ModelAdmin):
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
