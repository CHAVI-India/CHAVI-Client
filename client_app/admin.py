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

class OutcomeDICOMStudyInline(admin.TabularInline):
    model = OutcomeDICOMStudy
    extra = 1

#endregion

#region Inlines for Foreign Key relations.



#endregion

#region modelclasses

# Add Model classes

## Create the Patient Form Class

class PatientAdmin (admin.ModelAdmin):
    inlines = [PatientProjectInline]
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

class DiagnosisAdmin (admin.ModelAdmin):
    inlines = [DiagnosisDICOMStudyInline,DiagnosisProjectInline]
    fieldsets = (
        ('Diagnosis',{
            'fields': ['patient',('diagnosis','diagnosis_date','diagnostic_modality')]
        }),
        ('Presentation',{
            "fields": ['presentation_type','cancer_site','cancer_side']
        }),    
    )

## Create the Lesion Form Class

class LesionAdmin (admin.ModelAdmin):
    inlines = [LesionDICOMStudyInline]

## Create the Lesion Response Form Class

class LesionResponseAdmin (admin.ModelAdmin):
    inlines = [LesionResponseDICOMStudyInline]

## Create the Radiotherapy Form Clas

class RadiotherapyAdmin (admin.ModelAdmin):
    inlines=[RadiotherapyDICOMStudyInline]
    fieldsets = (
        ('Radiotherapy',{
            'fields': ['diagnosis',('radiotherapy_start_date','radiotherapy_end_date'),('radiotherapy_site','radiotherapy_side'),'treatment_volume']
        }),
        ('Description',{
            'fields': ['radiotherapy_modality','radiotherapy_type',('total_dose','total_fractions','fractions_per_day')]
        }),
    )        



#endregion


# Register your models here.
admin.site.register(SiteConfiguration,SingletonModelAdmin)
admin.site.register(Patient,PatientAdmin)
admin.site.register(Comorbidity)
admin.site.register(Diagnosis,DiagnosisAdmin)
admin.site.register(Pathology)
admin.site.register(StageInformation)
admin.site.register(Lesion, LesionAdmin)
admin.site.register(LesionResponse,LesionResponseAdmin)
admin.site.register(Radiotherapy,RadiotherapyAdmin)
admin.site.register(Surgery)
admin.site.register(SystemicTherapy)
admin.site.register(PatientOutcome)
admin.site.register(Outcome)
admin.site.register(AdverseEffects)
admin.site.register(PatientReportedOutcome)
admin.site.register(DICOMStudy)
