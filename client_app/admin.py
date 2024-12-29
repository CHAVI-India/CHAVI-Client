from django.contrib import admin
from .models import *

class PatientProjectInline(admin.TabularInline):
    model = PatientProject
    extra = 1  # Number of empty forms to display by default
    verbose_name = "Project"
    verbose_name_plural = "Projects"

class DiagnosisDICOMStudyInline(admin.TabularInline):
    model = DiagnosisDICOMStudy
    extra = 1  # Number of empty forms to display by default
    verbose_name = "DICOM Study"
    verbose_name_plural = "DICOM Studies"

@admin.register(Diagnosis)
class DiagnosisAdmin(admin.ModelAdmin):
    inlines = [DiagnosisDICOMStudyInline]
    list_display = ['patient', 'diagnosis_date']
    search_fields = ['patient__patient_id']
    list_filter = ['diagnosis_date', 'cancer_site']
    fieldsets = (
        ('Patient', {
            "fields":('patient',"diagnosis",'diagnosis_date')    
        }),
        ('Cancer Details', {
            'fields': ('presentation_type', 'cancer_site', 'cancer_side', 'diagnostic_modality')
        }),
    )
@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    inlines = [PatientProjectInline]
    list_display = ['patient_id', 'center', 'gender', 'date_of_birth']
    search_fields = ['patient_id']
    list_filter = ['gender','chavi_consent']
    fieldsets = (
        ('Patient Information', {
            'fields': ('center', 'patient_id', 'gender', 'date_of_birth')
        }),
        ('Consent Information', {
            'fields': ('chavi_consent', 'date_chavi_consent')
        }),
    )

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['chavi_project_id', 'project_name', 'start_date', 'completion_date']
    search_fields = ['chavi_project_id', 'project_name']
    list_filter = ['project_irb_approval', 'start_date']