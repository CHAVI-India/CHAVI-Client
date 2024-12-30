from django.contrib import admin
from .models import *

# Register your models here.

#region pathologyform

class PathologyInline(admin.StackedInline):
    model = Pathology
    extra = 1  # Number of empty forms to display by default
    verbose_name = "Pathology"
    verbose_name_plural = "Pathologies"

@admin.register(Pathology)
class PathologyAdmin(admin.ModelAdmin):
    list_display = ['diagnosis','date_pathology']
    list_filter=['date_pathology']
    search_fields = ['diagnosis__patient__patient_id']
    autocomplete_fields = ['diagnosis']
    fieldsets = (
        ('Pathology Information', {
            'fields':("date_pathology",'specimen_type','tumor_site','tumor_side','greatest_tumor_size','greatest_dimension_of_tumor','additional_tumor_dimension_1','additional_tumor_dimension_2')
        }),
        ('Tumor Characteristics', {
            'fields': ('histological_type','histological_subtype','histological_grade','histological_grading_schema',"tumor_focality",'lymphatic_vascular_invasion','perineural_invasion','dermal_lymphatic_vascular_invasion')
        }),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "diagnosis":
            kwargs["queryset"] = Diagnosis.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

#endregion

#region diagnosisform
class DiagnosisDICOMStudyInline(admin.TabularInline):
    model = DiagnosisDICOMStudy
    extra = 1  # Number of empty forms to display by default
    verbose_name = "DICOM Study"
    verbose_name_plural = "DICOM Studies"


@admin.register(Diagnosis)
class DiagnosisAdmin(admin.ModelAdmin):
    inlines = [DiagnosisDICOMStudyInline, PathologyInline]
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

#endregion



#region lesionform
class LesionDICOMStudyInline(admin.TabularInline):
    model = LesionDICOMStudy
    extra = 1  # Number of empty forms to display by default
    verbose_name = "DICOM Study for Lesion"
    verbose_name_plural = "DICOM Studies for Lesion"


@admin.register(Lesion)
class LesionAdmin(admin.ModelAdmin):
    inlines = [LesionDICOMStudyInline]
    search_fields=['diagnosis__patient__patient_id']
    fieldsets = (
        ('Lesion Information', {
            "fields":('diagnosis','date_lesion_assessed','lesion_site','lesion_type','lesion_laterality')
        }),
        ('Lesion Measurements', {
            'fields': ('lesion_size_x_axis', 'lesion_size_y_axis', 'lesion_size_z_axis','lesion_size_unit','lesion_volume')
        }),
    )

#endregion

#region patientform
class PatientProjectInline(admin.TabularInline):
    model = PatientProject
    extra = 1  # Number of empty forms to display by default
    verbose_name = "Project"
    verbose_name_plural = "Projects"


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

#endregion

#region centerform
@admin.register(Center)
class CenterAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Center Information', {
            'fields': ('chavi_center_id','center_name')

        }),
        ('Center Address', {
            'fields': ('center_address', 'center_city', 'center_state', 'center_country')

        }),
    )

#endregion

#region projectform
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):

    list_display = ['chavi_project_id', 'project_name', 'start_date', 'completion_date']
    search_fields = ['chavi_project_id', 'project_name']
    list_filter = ['project_irb_approval', 'start_date']
#endregion
