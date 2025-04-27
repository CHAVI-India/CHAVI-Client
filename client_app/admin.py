import os
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import User, Group
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.contrib.filters.admin import (
    RangeDateFilter, 
    RangeDateTimeFilter, 
    RangeNumericFilter, 
    RangeNumericListFilter, 
    SingleNumericFilter,
    SliderNumericFilter,
    ChoicesDropdownFilter,
    MultipleChoicesDropdownFilter,
    RelatedDropdownFilter,
    MultipleRelatedDropdownFilter,
    DropdownFilter,
    MultipleDropdownFilter    
    )
from unfold.contrib.forms.widgets import ArrayWidget

from chavi_client.settings import BASE_DIR
from .models import *
from lookup.models import *
from pathlib import Path
import tempfile
import zipfile
from pydicom import dcmread
from django.contrib import messages
from django.conf import settings
from datetime import datetime
from django.utils import timezone
import shutil
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from django.http import HttpResponse
import json
from django.contrib import messages
from django.core.paginator import Paginator
from import_export.widgets import ForeignKeyWidget,ManyToManyWidget
from import_export import fields
from import_export.admin import ImportExportModelAdmin
from unfold.contrib.import_export.forms import ExportForm, ImportForm, SelectableFieldsExportForm
from unfold.decorators import action
from .services.patient_data_export import export_patient_data
from allauth.account.decorators import secure_admin_login
from .services.dicom_data_import_per_patient import process_dicom
from .services.bulk_dicom_data_import import process_bulk_dicom
from django.urls import path
from .views import PatientSummaryView, PatientSearchView
from django.urls import reverse
from django.shortcuts import redirect

# For Django AllAuth
admin.autodiscover()
admin.site.login = secure_admin_login(admin.site.login)

#endregion
class DICOMStudyProjectInline(TabularInline):
    model = DICOMStudyProject
    extra = 1
    search_fields = ['dicom_study']
    autocomplete_fields = ['dicom_study']    

#endregion

#region Inlines for Foreign Key relations.

class SystemicTherapyScheduleInline(StackedInline):
    model = SystemicTherapySchedule
    autocomplete_fields = ['systemic_therapy_agent']
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
    autocomplete_fields =['protein_name']
    extra = 1
    tab = True
    
class CytogeneticsInline(StackedInline):
    model = Cytogenetics
    autocomplete_fields =['gene','cytogentic_abnormality']
    extra = 1
    tab = True

class SomaticGenomicAlterationsInline(StackedInline):
    model = SomaticGenomicAlterations
    autocomplete_fields = ['cosmic_gene_name']
    extra = 1
    tab = True

class GeneExpressionDataInline(StackedInline):
    model = GeneExpressionData
    autocomplete_fields = ['gene']
    extra = 1
    tab = True
class EpigeneticDataInline(StackedInline):
    model = EpigeneticData
    autocomplete_fields = ['gene']
    extra = 1
    tab = True

class RadiotherapyVolumeInline(StackedInline):
    model = RadiotherapyVolume
    extra = 1
    fieldsets = (
        ('Volume Description',{
            'fields': [('volume_name','volume_type'),('volume_dose_prescribed','radiation_dose_units','volume_fractions'),('volume_radiotherapy_start_date','volume_radiotherapy_end_date')]
        }),
        ('Anatomical Locations',{
            'fields': ['anatomical_locations']
        }),
    )
    filter_horizontal = ['anatomical_locations']
    tab=True

class RadiotherapyDoseVolumeDataInline(TabularInline):
    model = RadiotherapyDoseVolumeData
    extra = 1
    tab = True  

#endregion

#region modelclasses

# Add Model classes

## Create the Patient Form Class along with the export import configuration
class PatientResource(resources.ModelResource):
    class Meta:
        model = Patient
        import_id_fields = ['patient_id']
        widgets = {
            'date_of_birth': {'format': '%Y-%m-%d'},
            'date_of_registration': {'format': '%Y-%m-%d'},
            'date_chavi_consent': {'format': '%Y-%m-%d'},
        }


@admin.register(Patient)
class PatientAdmin(ModelAdmin, ImportExportModelAdmin):
    actions = [export_patient_data]
    list_filter = ['gender','chavi_consent','created_at']
    search_fields = ['patient_id']
    list_display = ['patient_id','gender','date_of_birth','chavi_consent','date_chavi_consent','created_at']
    filter_horizontal = ['patient_project']
    resource_classes = [PatientResource]
    fieldsets = (
        ('Demographics',{
            'fields': ['patient_id',('gender','center'),('date_of_birth','date_of_registration')]
        }),
        ('CHAVI Consent',{
            'fields': [('chavi_consent','date_chavi_consent')]
        }),
        ('Projects',{
            'fields': ['patient_project']
        }),
    )
    readonly_fields = ['center']
    change_form_template = os.path.join(BASE_DIR, 'templates', 'admin', 'change_form.html')
    guidance_text = """
    <h2>Guidance</h2>
    <p>This form allows you to enter data for patients in the CHAVI database. This is the key form to fill as the patient ID will be used for all other forms. <br>
    For patients who have a CHAVI consent done please choose Yes and input the date of the consent. You can assign a patient to multiple projects also in this form. <br> Please note that DICOM data can be associated with the patient only after the Patient ID is entered.</p>    <br>
    """



@admin.register(PatientDicomFile)
class PatientDicomFileAdmin(ModelAdmin):
    search_fields =[ 'patient__patient_id']
    list_display = ['patient', 'file', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    fieldsets = (
        ('Patient DICOM File',{
            'fields': ['patient','file']  
        }),
    )
    actions = [
        process_dicom
    ]
    change_form_template = os.path.join(BASE_DIR, 'templates', 'admin', 'change_form.html')
    guidance_text = """
    <h2>Guidance</h2>
    <p>This form allows you to enter DICOM data for a <strong>SINGLE patient</strong>. Please upload a zip file with DICOM studies belonging to a <strong>SINGLE patient only</strong> in this form. <br>
     After the zip file is uploaded and saved, you can use the action at the bottom of the listing page to process the DICOM. The processing function will extract all the DICOM files from the zip folder, ensure that the patient ID in the DICOM files match that of the patient ID in the database and then appropriately sort them into a dicom_study folder. Additionally you will see that it updates the DICOMStudies data also in the database.
      <br> <strong> Please upload a zip belonging to a single patient only as patient ID in the dicom files will be changed !! </strong> </p> After the DICOM zip file has been processed you may decide to delete the file by selecting the file in the list display page and clicking the delete selected patient dicom files action. <p> </p>   <br>
    """



## Create the Diagnosis Resource
class DiagnosisResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_diagnosis_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_diagnosis_id'] = str(uuid.uuid4())


    patient = fields.Field(attribute='patient',column_name='patient_id',widget=ForeignKeyWidget(Patient,field='patient_id'))
    cancer_system = fields.Field(attribute='cancer_system',column_name='cancer_system',widget=ForeignKeyWidget(LookupMajorCancerCategory,field='code'))
    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(LookupICDCode,field='code'))
    diagnostic_modality = fields.Field(attribute='diagnostic_modality',column_name='diagnostic_modality',widget=ForeignKeyWidget(LookupDiagnosticModality,field='code'))
    presentation_type = fields.Field(attribute='presentation_type',column_name='presentation_type',widget=ForeignKeyWidget(LookupPresentation,field='code'))
    cancer_site = fields.Field(attribute='cancer_site',column_name='cancer_site',widget=ForeignKeyWidget(LookupFMACode,field='code'))
    cancer_side = fields.Field(attribute='cancer_side',column_name='cancer_side',widget=ForeignKeyWidget(LookupLaterality,field='code'))
    diagnosis_project = fields.Field(attribute='diagnosis_project',column_name='diagnosis_project',widget=ManyToManyWidget(Project,field='chavi_project_id'))

    class Meta:
        model = Diagnosis
        import_id_fields = ['chavi_diagnosis_id']
        fields = ['chavi_diagnosis_id','patient','cancer_system','diagnosis','diagnosis_date','diagnostic_modality','presentation_type','cancer_site','cancer_side','diagnosis_project']
        widgets = {
            'diagnosis_date': {'format': '%Y-%m-%d'},
        }


class DiagnosisExportResource(resources.ModelResource):
    class Meta:
        model = Diagnosis
        fields = ['patient','chavi_diagnosis_id']

# Create the Diagnosis Form Class
@admin.register(Diagnosis)
class DiagnosisAdmin (ModelAdmin, ImportExportModelAdmin):
    search_fields = ['patient__patient_id', 'chavi_diagnosis_id']
    autocomplete_fields = ['patient','diagnosis','cancer_site','cancer_system']
    filter_horizontal = ['diagnosis_dicom_study','diagnosis_project']
    list_filter = ['diagnostic_modality','patient__patient_id']
    list_display = ['patient','diagnosis','diagnosis_date','diagnostic_modality','presentation_type']
    fieldsets = (
        ('Diagnosis',{
            'fields': ['patient','presentation_type','diagnosis',('diagnosis_date','diagnostic_modality')]
        }),
        ('Presentation',{
            "fields": ['cancer_system','cancer_site',('cancer_side')]
        }),
        ('DICOM Studies',{
            'fields': ['diagnosis_dicom_study']
        }),
        ('Projects',{
            'fields': ['diagnosis_project']
        }),
    )
    resource_classes = [DiagnosisResource,DiagnosisExportResource]
    
    def get_search_results(self, request, queryset, search_term):
        """Override to allow filtering by patient__patient_id__exact"""
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        
        # Handle query parameters for related lookups
        if 'patient__patient_id__exact' in request.GET:
            patient_id = request.GET.get('patient__patient_id__exact')
            queryset = queryset.filter(patient__patient_id=patient_id)
        
        return queryset, use_distinct
    
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return DiagnosisExportResource


## Create the Pathology Form Class
class PathologyResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_pathology_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_pathology_id'] = str(uuid.uuid4())


    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    tumor_site = fields.Field(attribute='tumor_site',column_name='tumor_site',widget=ForeignKeyWidget(LookupFMACode,field='code'))
    tumor_side = fields.Field(attribute='tumor_side',column_name='tumor_side',widget=ForeignKeyWidget(LookupLaterality,field='code'))
    histological_type = fields.Field(attribute='histological_type',column_name='histological_type',widget=ForeignKeyWidget(LookupPathology,field='code'))
    histological_grade = fields.Field(attribute='histological_grade',column_name='histological_grade',widget=ForeignKeyWidget(LookupGrade,field='code'))
    tumor_dimesion_unit = fields.Field(attribute='tumor_dimesion_unit',column_name='tumor_dimesion_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='code'))
    lymphatic_vascular_invasion = fields.Field(attribute='lymphatic_vascular_invasion',column_name='lymphatic_vascular_invasion',widget=ForeignKeyWidget(LookupPathologyDescriptors,field='code'))
    perineural_invasion = fields.Field(attribute='perineural_invasion',column_name='perineural_invasion',widget=ForeignKeyWidget(LookupPathologyDescriptors,field='code'))
    dermal_lymphatic_vascular_invasion = fields.Field(attribute='dermal_lymphatic_vascular_invasion',column_name='dermal_lymphatic_vascular_invasion',widget=ForeignKeyWidget(LookupPathologyDescriptors,field='code'))
    necrosis = fields.Field(attribute='necrosis',column_name='necrosis',widget=ForeignKeyWidget(LookupPathologyDescriptors,field='code'))
    margin_status = fields.Field(attribute='margin_status',column_name='margin_status',widget=ForeignKeyWidget(LookupMarginStatus,field='code'))    
    closest_margin_distance_unit = fields.Field(attribute='closest_margin_distance_unit',column_name='closest_margin_distance_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='code'))
    treatment_effect = fields.Field(attribute='treatment_effect',column_name='treatment_effect',widget=ForeignKeyWidget(LookupTreatmentEffect,field='code'))

    
    class Meta:
        model = Pathology
        import_id_fields = ['chavi_pathology_id']
        fields = ['chavi_pathology_id','diagnosis','date_pathology','specimen_type','tumor_site','tumor_side','greatest_dimension_of_tumor','additional_tumor_dimension_1','additional_tumor_dimension_2','tumor_dimesion_unit','tumor_focality','histological_type','histological_grade','lymphatic_vascular_invasion','perineural_invasion','dermal_lymphatic_vascular_invasion','necrosis','necrosis_percentage','mitotic_count','margin_status','closest_margin_distance','closest_margin_distance_unit','treatment_effect','primary_gleason_grade','secondary_gleason_grade','lymph_nodes_removed','lymph_nodes_in_specimen','lymph_node_extracapsular_extension','number_of_uninvolved_nodes','number_of_nodes_with_macrometastases','number_of_nodes_with_micrometastases','number_of_nodes_with_isolated_tumor_cells','number_of_nodes_with_extracapsular_extension']
        widgets = {
            'date_pathology': {'format': '%Y-%m-%d'},
        }

class PathologyExportResource(resources.ModelResource):
    class Meta:
        model = Pathology
        fields = ['diagnosis','chavi_pathology_id']


@admin.register(Pathology)
class PathologyAdmin (ModelAdmin, ImportExportModelAdmin):
    inlines = [ImmunohistochemistryInline,CytogeneticsInline,SomaticGenomicAlterationsInline,GeneExpressionDataInline,EpigeneticDataInline]
    autocomplete_fields = ['diagnosis','tumor_site','histological_type']
    search_fields = ['diagnosis__patient__patient_id', 'diagnosis__patient_id']
    list_filter = ['date_pathology','tumor_side__label','diagnosis__patient__patient_id']
    list_display = ['diagnosis__patient_id','diagnosis','date_pathology','tumor_site__label','tumor_side__label','histological_type','lymph_nodes_in_specimen']
    fieldsets = (
        ('Pathology',{
            'fields': ['diagnosis',('date_pathology','specimen_type'),'tumor_site','tumor_side']
        }),
        ('Histology',{
            'fields': ['histological_type','histological_grade']
        }),
     
        ('Pathological Features',{
            "classes": ['tab'],
            'fields': [('lymphatic_vascular_invasion','perineural_invasion','dermal_lymphatic_vascular_invasion'),('necrosis','necrosis_percentage'),('mitotic_count')]
        }),

        ('Tumor Size',{
            "classes": ['tab'],
            'fields': [('greatest_dimension_of_tumor','additional_tumor_dimension_1','additional_tumor_dimension_2'),('tumor_dimesion_unit','tumor_focality')]
        }),
        ('Margins & Margin Status',{
            "classes": ['tab'],
            'fields': ['margin_status',('closest_margin_distance','closest_margin_distance_unit')]
        }),
        ('Treatment Effect',{
            "classes": ['tab'],
            'fields': ['treatment_effect']
        }),

        ('GleasonGrade',{
            "classes": ['tab'],
            'fields': [('primary_gleason_grade','secondary_gleason_grade')]
        }),   
        ('Nodes',{
            "classes": ['tab'],
            'fields': [('lymph_nodes_removed','lymph_nodes_in_specimen','lymph_node_extracapsular_extension'),('number_of_nodes_with_macrometastases','number_of_nodes_with_micrometastases','number_of_nodes_with_isolated_tumor_cells','number_of_nodes_with_extracapsular_extension')]
        }),
    )
    compressed_fields = True
    resource_classes = [PathologyResource,PathologyExportResource]
    
    def get_search_results(self, request, queryset, search_term):
        """Override to allow filtering by diagnosis__patient__patient_id__exact"""
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        
        # Handle query parameters for related lookups
        if 'diagnosis__patient__patient_id__exact' in request.GET:
            patient_id = request.GET.get('diagnosis__patient__patient_id__exact')
            queryset = queryset.filter(diagnosis__patient__patient_id=patient_id)
        
        return queryset, use_distinct
    
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return PathologyExportResource


# Create the Stage Information Resource
class StageInformationResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_stage_information_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_stage_information_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    staging_system = fields.Field(attribute='staging_system',column_name='staging_system',widget=ForeignKeyWidget(LookupStagingSystem,field='code'))
    stage_type = fields.Field(attribute='stage_type',column_name='stage_type',widget=ForeignKeyWidget(LookupStagingType,field='code'))
    t_stage_prefix = fields.Field(attribute='t_stage_prefix',column_name='t_stage_prefix',widget=ForeignKeyWidget(LookupAJCCStagePrefix,field='code'))
    t_stage = fields.Field(attribute='t_stage',column_name='t_stage',widget=ForeignKeyWidget(LookupAJCCTStageDescriptor,field='code'))
    t_stage_suffix = fields.Field(attribute='t_stage_suffix',column_name='t_stage_suffix',widget=ForeignKeyWidget(LookupAJCCStageSuffix,field='code'))
    n_stage_prefix = fields.Field(attribute='n_stage_prefix',column_name='n_stage_prefix',widget=ForeignKeyWidget(LookupAJCCStagePrefix,field='code'))
    n_stage = fields.Field(attribute='n_stage',column_name='n_stage',widget=ForeignKeyWidget(LookupAJCCNStageDescriptor,field='code'))
    n_stage_suffix = fields.Field(attribute='n_stage_suffix',column_name='n_stage_suffix',widget=ForeignKeyWidget(LookupAJCCStageSuffix,field='code'))
    m_stage_prefix = fields.Field(attribute='m_stage_prefix',column_name='m_stage_prefix',widget=ForeignKeyWidget(LookupAJCCStagePrefix,field='code'))
    m_stage = fields.Field(attribute='m_stage',column_name='m_stage',widget=ForeignKeyWidget(LookupAJCCMStageDescriptor,field='code'))
    m_stage_suffix = fields.Field(attribute='m_stage_suffix',column_name='m_stage_suffix',widget=ForeignKeyWidget(LookupAJCCStageSuffix,field='code'))
    overall_stage = fields.Field(attribute='overall_stage',column_name='overall_stage',widget=ForeignKeyWidget(LookupStageDescriptor,field='code'))    

    class Meta:
        model = StageInformation
        import_id_fields = ['chavi_stage_information_id']
        fields = ['chavi_stage_information_id','diagnosis','staging_system','stage_type','t_stage_prefix','t_stage','t_stage_suffix','n_stage_prefix','n_stage','n_stage_suffix','m_stage_prefix','m_stage','m_stage_suffix','overall_stage']
        widgets = {
            'date_of_staging_assessment': {'format': '%Y-%m-%d'},
        }

class StageInformationExportResource(resources.ModelResource):
    class Meta:
        model = StageInformation
        fields = ['diagnosis','chavi_stage_information_id']

## Create the Stage Information Form Class
@admin.register(StageInformation)
class StageInformationAdmin (ModelAdmin, ImportExportModelAdmin):
    search = ['diagnosis__patient_id']
    autocomplete_fields = ['diagnosis','overall_stage']
    list_filter = ['diagnosis__patient__patient_id','staging_system__label','stage_type','overall_stage']
    list_display = ['diagnosis__patient','staging_system__label','stage_type','overall_stage']
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
    resource_classes = [StageInformationResource,StageInformationExportResource]
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return StageInformationExportResource


class ComorbidityResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_comorbidity_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_comorbidity_id'] = str(uuid.uuid4())


    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='patient_id'))

    class Meta:
        model = Comorbidity
        import_id_fields = ['chavi_comorbidity_id']
        fields = ['chavi_comorbidity_id','patient','comorbidity_type','date_of_comorbidity_diagnosis','date_of_comorbidity_assessment','duration_of_comorbidity','comorbidity_resolved','medication_for_comorbidity']
        widgets = {
            'date_of_comorbidity_diagnosis': {'format': '%Y-%m-%d'},
            'date_of_comorbidity_assessment': {'format': '%Y-%m-%d'},
        }

## Create the Comorbidity Form

@admin.register(Comorbidity)
class ComorbidityAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['patient','comorbidity_type']
    list_display = ['patient', 'comorbidity_type', 'date_of_comorbidity_diagnosis', 'created_at']
    list_filter = ['date_of_comorbidity_diagnosis', 'created_at']
    resource_classes = [ComorbidityResource]
    readonly_fields = ['date_of_comorbidity_diagnosis']

    fieldsets = (
        ('Patient Information', {
            'fields': ('patient', 'comorbidity_type')
        }),
        ('Dates and Duration', {
            'fields': ('date_of_comorbidity_assessment', 'duration_of_comorbidity', 'date_of_comorbidity_diagnosis'),
            'description': 'Enter the assessment date and duration in months. The diagnosis date will be automatically calculated when you save.'
        }),
        ('Status', {
            'fields': ('comorbidity_resolved', 'medication_for_comorbidity')
        }),
    )

    def save_model(self, request, obj, form, change):
        """
        Override save_model to show a message to the user about the calculated date
        """
        super().save_model(request, obj, form, change)
        if obj.date_of_comorbidity_diagnosis:
            self.message_user(
                request,
                f"Diagnosis date has been automatically calculated as {obj.date_of_comorbidity_diagnosis.strftime('%d/%m/%Y')}",
                messages.SUCCESS
            )


# Create the Lesion Resource
class LesionResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_lesion_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_lesion_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    lesion_site = fields.Field(attribute='lesion_site',column_name='lesion_site',widget=ForeignKeyWidget(LookupFMACode,field='code'))
    lesion_laterality = fields.Field(attribute='lesion_laterality',column_name='lesion_laterality',widget=ForeignKeyWidget(LookupLaterality,field='code'))
    lesion_type = fields.Field(attribute='lesion_type',column_name='lesion_type',widget=ForeignKeyWidget(LookupLesionType,field='code'))
    lesion_size_unit = fields.Field(attribute='lesion_size_unit',column_name='lesion_size_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='code'))
    lesion_volume_unit = fields.Field(attribute='lesion_volume_unit',column_name='lesion_volume_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='code'))

    class Meta:
        model = Lesion
        import_id_fields = ['chavi_lesion_id']
        fields = ['chavi_lesion_id','diagnosis','date_lesion_assessed','lesion_site','lesion_laterality','lesion_type','lesion_size_x_axis','lesion_size_y_axis','lesion_size_z_axis','lesion_size_unit','lesion_volume','lesion_volume_unit','lesion_detection_modality','lesion_suv_max']
        widgets = {
            'date_lesion_assessed': {'format': '%Y-%m-%d'},
        }

class LesionExportResource(resources.ModelResource):
    class Meta:
        model = Lesion
        fields = ['chavi_lesion_id','diagnosis']

## Create the Lesion Form Class
@admin.register(Lesion)
class LesionAdmin (ModelAdmin, ImportExportModelAdmin):
    search_fields = ['diagnosis','lesion_site','lesion_type']
    list_display = ['diagnosis','lesion_site','lesion_type','lesion_detection_modality','lesion_suv_max']
    autocomplete_fields = ['diagnosis','lesion_site']
    filter_horizontal = ['lesion_dicom_study']
    list_filter = ['diagnosis__patient__patient_id']
    fieldsets = (
        ('Lesion', {
            'fields' : [('diagnosis','date_lesion_assessed'),('lesion_site','lesion_laterality','lesion_type')]
        }),
        ('Dimensions', {
            'fields' : [('lesion_size_x_axis', 'lesion_size_y_axis', 'lesion_size_z_axis','lesion_size_unit'), ('lesion_volume','lesion_volume_unit')]

        }),
        ('Lesion Detection Modality', {
            'fields' : ['lesion_detection_modality','lesion_suv_max']
        }),        
        ('DICOM Studies', {
            'fields' : ['lesion_dicom_study']
        }),

    )   
    resource_classes = [LesionResource,LesionExportResource]
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return LesionExportResource

class LesionResponseResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_lesion_response_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_lesion_response_id'] = str(uuid.uuid4())

    lesion = fields.Field(attribute='lesion',column_name='lesion',widget=ForeignKeyWidget(Lesion,field='chavi_lesion_id'))
    lesion_response = fields.Field(attribute='lesion_response',column_name='lesion_response',widget=ForeignKeyWidget(LookupResponseType,field='code'))
    residual_lesion_size_unit = fields.Field(attribute='residual_lesion_size_unit',column_name='residual_lesion_size_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='code'))
    residual_lesion_volume_unit = fields.Field(attribute='residual_lesion_volume_unit',column_name='residual_lesion_volume_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='code'))

    class Meta:
        model = LesionResponse
        import_id_fields = ['chavi_lesion_response_id']
        fields = ['chavi_lesion_response_id','lesion','lesion_response_date','lesion_response','residual_lesion_size_x_axis','residual_lesion_size_y_axis','residual_lesion_size_z_axis','residual_lesion_size_unit','residual_lesion_volume','residual_lesion_volume_unit','lesion_response_modality','lesion_response_suv_max']
        widgets = {
            'lesion_response_date': {'format': '%Y-%m-%d'},
        }

class LesionResponseExportResource(resources.ModelResource):
    class Meta:
        model = LesionResponse
        fields = ['lesion','chavi_lesion_response_id']

## Create the Lesion Response Form Class
@admin.register(LesionResponse)
class LesionResponseAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['lesion']
    filter_horizontal = ['lesion_response_dicom_study']
    list_display = ['lesion__diagnosis', 'lesion_response_date', 'lesion_response', 'residual_lesion_volume']
    list_filter = ['lesion_response_date', 'lesion_response']
    resource_classes = [LesionResponseResource,LesionResponseExportResource]
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return LesionResponseExportResource    


class RadiotherapyResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_radiotherapy_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_radiotherapy_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    radiotherapy_modality = fields.Field(attribute='radiotherapy_modality',column_name='radiotherapy_modality',widget=ForeignKeyWidget(LookupRadiotherapyModality,field='code'))
    radiation_dose_units = fields.Field(attribute='radiation_dose_units',column_name='radiation_dose_units',widget=ForeignKeyWidget(LookupDoseUnits,field='code'))
    radiotherapy_type = fields.Field(attribute='radiotherapy_type',column_name='radiotherapy_type',widget=ForeignKeyWidget(LookupRadiotherapyType,field='code'))
    radiotherapy_technique = fields.Field(attribute='radiotherapy_technique',column_name='radiotherapy_technique',widget=ForeignKeyWidget(LookupRadiotherapyTechnique,field='code'))
    radiotherapy_side = fields.Field(attribute='radiotherapy_side',column_name='radiotherapy_side',widget=ForeignKeyWidget(LookupLaterality,field='code'))
    radiotherapy_intent = fields.Field(attribute='radiotherapy_intent',column_name='radiotherapy_intent',widget=ForeignKeyWidget(LookupTreatmentIntent,field='code'))

    class Meta:
        model = Radiotherapy
        import_id_fields = ['chavi_radiotherapy_id']
        fields = ['chavi_radiotherapy_id','diagnosis','radiotherapy_start_date','radiotherapy_intent','radiotherapy_end_date','radiotherapy_side','radiotherapy_course_type','reirradiation','radiotherapy_modality','radiotherapy_type','radiotherapy_machine','total_dose','radiation_dose_units','simultaneous_integrated_boost','simultaneous_integrated_boost_dose','total_fractions','fractions_per_day','radiotherapy_technique']
        widgets = {
            'radiotherapy_start_date': {'format': '%Y-%m-%d'},
            'radiotherapy_end_date': {'format': '%Y-%m-%d'},
        }

class RadiotherapyExportResource(resources.ModelResource):
    class Meta:
        model = Radiotherapy
        fields = ['diagnosis','chavi_radiotherapy_id']


## Create the Radiotherapy Form Class

@admin.register(Radiotherapy)
class RadiotherapyAdmin (ModelAdmin, ImportExportModelAdmin):
    inlines=[RadiotherapyVolumeInline,RadiotherapyDoseVolumeDataInline]
    autocomplete_fields = ['diagnosis']
    list_filter =['diagnosis__patient__patient_id']
    search_fields = ['diagnosis__patient__patient_id', 'diagnosis__chavi_diagnosis_id']
    filter_horizontal = ['radiotherapy_dicom_study']
    fieldsets = (
        ('Radiotherapy',{
            'fields': ['diagnosis',('radiotherapy_start_date','radiotherapy_end_date'),( 'radiotherapy_side','radiotherapy_course_type','reirradiation')]
        }),
        ('Description',{
            'fields': [('radiotherapy_intent','radiotherapy_modality'),('radiotherapy_type','radiotherapy_machine'),'radiotherapy_technique',('total_dose','radiation_dose_units'),('simultaneous_integrated_boost','simultaneous_integrated_boost_dose'),('total_fractions','fractions_per_day')]
        }),
        ('DICOM Studies',{
            'fields': ['radiotherapy_dicom_study']
        }),
    )
    resource_classes = [RadiotherapyResource,RadiotherapyExportResource]
    
    def get_search_results(self, request, queryset, search_term):
        """Override to allow filtering by diagnosis__patient__patient_id__exact"""
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        
        # Handle query parameters for related lookups
        if 'diagnosis__patient__patient_id__exact' in request.GET:
            patient_id = request.GET.get('diagnosis__patient__patient_id__exact')
            queryset = queryset.filter(diagnosis__patient__patient_id=patient_id)
        
        return queryset, use_distinct
    
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return RadiotherapyExportResource
 

## Create the Surgery Resource
class SurgeryResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_surgery_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_surgery_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    surgery_side = fields.Field(attribute='surgery_side',column_name='surgery_side',widget=ForeignKeyWidget(LookupLaterality,field='code'))
    surgery_type= fields.Field(attribute='surgery_type',column_name='surgery_type',widget=ForeignKeyWidget(LookupSurgicalProcedures,field='code'))
    nodal_assessment_type = fields.Field(attribute='nodal_assessment_type',column_name='nodal_assessment_type',widget=ForeignKeyWidget(LookupNodalAssessmentType,field='code'))

    class Meta:
        model = Surgery
        import_id_fields = ['chavi_surgery_id']
        fields = ['chavi_surgery_id','diagnosis','surgery_date','surgery_side','surgery_type','surgery_intent','nodal_assessment','nodal_assessment_type','reconstruction','type_reconstruction']
        widgets = {
            'surgery_date': {'format': '%Y-%m-%d'},
        }


## Create the Surgery Form Class
@admin.register(Surgery)
class SurgeryAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis','surgery_type']
    list_filter = ['diagnosis__patient__patient_id']
    filter_horizontal = ['surgery_dicom_study']
    fieldsets = (
        ('Surgery', {
            'fields':['diagnosis','surgery_date','surgery_intent']
        }),
        ('Description',{
            'fields':['surgery_side','surgery_type',('nodal_assessment','nodal_assessment_type')]
        }),
        ('Reconstruction',{
            'fields':['reconstruction','type_reconstruction']
        }),
        ('DICOM Studies',{
            'fields': ['surgery_dicom_study']
        }),        
    )
    resource_classes = [SurgeryResource]

# Create the Systemic Therapy Resource
class SystemicTherapyResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_systemic_therapy_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_systemic_therapy_id'] = str(uuid.uuid4())


    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    systemic_therapy_type = fields.Field(attribute='systemic_therapy_type',column_name='systemic_therapy_type',widget=ForeignKeyWidget(LookupSystemicTherapyType,field='code'))
    systemic_therapy_sequence = fields.Field(attribute='systemic_therapy_sequence',column_name='systemic_therapy_sequence',widget=ForeignKeyWidget(LookupTreatmentSequence,field='code'))
    systemic_therapy_regimen = fields.Field(attribute='systemic_therapy_regimen',column_name='systemic_therapy_regimen',widget=ForeignKeyWidget(LookupSystemicTherapyRegimen,field='code'))
    systemic_therapy_intent = fields.Field(attribute='systemic_therapy_intent',column_name='systemic_therapy_intent',widget=ForeignKeyWidget(LookupTreatmentIntent,field='code'))

    class Meta:
        model = SystemicTherapy
        import_id_fields = ['chavi_systemic_therapy_id']
        fields = ['chavi_systemic_therapy_id','diagnosis','systemic_therapy_type','systemic_therapy_sequence','systemic_therapy_intent','systemic_therapy_regimen','cycles_delivered','systemic_therapy_start_date','systemic_therapy_end_date']
        widgets = {
            'systemic_therapy_start_date': {'format': '%Y-%m-%d'},
            'systemic_therapy_end_date': {'format': '%Y-%m-%d'},
        }

class SystemicTherapyExportResource(resources.ModelResource):
    class Meta:
        model = SystemicTherapy
        fields = ['chavi_systemic_therapy_id','diagnosis']

## Create the Systemic Therapy Form Class
@admin.register(SystemicTherapy)
class SystemicTherapyAdmin (ModelAdmin, ImportExportModelAdmin):
    inlines = [SystemicTherapyScheduleInline]
    autocomplete_fields = ['diagnosis','systemic_therapy_regimen']
    search_fields = ['diagnosis__diagnosis']
    filter_horizontal =['systemic_therapy_dicom_study']
    list_filter = ['diagnosis__patient__patient_id']
    fieldsets = (
        ('Systemic Therapy',{
            'fields':['diagnosis',('systemic_therapy_start_date','systemic_therapy_end_date')]
        }),
        ('Description',{
            'fields':[('systemic_therapy_type','systemic_therapy_sequence','systemic_therapy_intent'),('systemic_therapy_regimen','cycles_delivered')]
        }),
        ('DICOM Studies',{
            'fields': ['systemic_therapy_dicom_study']
        }),        
    )
    resource_classes = [SystemicTherapyResource,SystemicTherapyExportResource]
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return SystemicTherapyExportResource

## Create the ConcomitantMedications Form Class
class ConcomitantMedicationsResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_medication_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_medication_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    medication_dose_units = fields.Field(attribute='medication_dose_units',column_name='medication_dose_units',widget=ForeignKeyWidget(LookupDoseUnits,field='code'))

    class Meta:
        model = ConcomitantMedications
        import_id_fields = ['chavi_medication_id']
        fields = ['chavi_medication_id','diagnosis','medication_name','medication_route','medication_dose','medication_dose_units','date_medication_start_date','date_medication_end_date']
        widgets = {
            'date_medication_start_date': {'format': '%Y-%m-%d'},
            'date_medication_end_date': {'format': '%Y-%m-%d'},
        }


@admin.register(ConcomitantMedications)
class ConcomitantMedicationsAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis']
    fieldsets = (
        ('Concomitant Medications',{
            'fields':['diagnosis',('medication_name','medication_route'),('medication_dose','medication_dose_units'),('date_medication_start_date', 'date_medication_end_date')]
        }),
    )
    resource_classes = [ConcomitantMedicationsResource]
    list_display = ['diagnosis', 'medication_name', 'medication_dose', 'date_medication_start_date', 'date_medication_end_date']
    list_filter = ['diagnosis__patient__patient_id','date_medication_start_date', 'date_medication_end_date', 'medication_route']


# Create the Other Treatment Resource
class OtherTreatmentResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_treatment_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_treatment_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    treatment_intent = fields.Field(attribute='treatment_intent',column_name='treatment_intent',widget=ForeignKeyWidget(LookupTreatmentIntent,field='chavi_treatment_intent_id'))
    class Meta:
        model = OtherTreatment
        import_id_fields = ['chavi_treatment_id']
        fields = ['chavi_treatment_id','diagnosis','treatment_intent','treatment_start_date','treatment_end_date','treatment']
        widgets = {
            'treatment_start_date': {'format': '%Y-%m-%d'},
            'treatment_end_date': {'format': '%Y-%m-%d'},
        }

## Create the Other Treatment Form Class
@admin.register(OtherTreatment)
class OtherTreatmentAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis']
    fieldsets = (
        ('Description',{
            'fields':['diagnosis',('treatment_start_date','treatment_end_date'),'treatment_intent','treatment']
        }),
    )
    resource_classes = [OtherTreatmentResource]
    list_display = ['diagnosis', 'treatment', 'treatment_start_date', 'treatment_end_date']
    list_filter = ['diagnosis__patient__patient_id','treatment_start_date', 'treatment_end_date']


## Create the Adverse Effects form class
class AdverseEffectsResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_adverse_effects_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_adverse_effects_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    ctcae_grade_lookup = fields.Field(attribute='ctcae_grade_lookup',column_name='ctcae_grade_lookup',widget=ForeignKeyWidget(LookupCTCAEGrade,field='code'))

    class Meta:
        model = AdverseEffects
        import_id_fields = ['chavi_adverse_effects_id']
        fields = ['chavi_adverse_effects_id','diagnosis','adverse_effect_start_date','adverse_effect_end_date','ctcae_grade_lookup']
        widgets = {
            'adverse_effect_start_date': {'format': '%Y-%m-%d'},
            'adverse_effect_end_date': {'format': '%Y-%m-%d'},
        }

class AdverseEffectsExportResource(resources.ModelResource):
    class Meta:
        model = AdverseEffects
        fields = ['diagnosis','chavi_adverse_effects_id']

# Create the Adverse Effects form Class
@admin.register(AdverseEffects)
class AdverseEffectsAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis','ctcae_grade_lookup']
    list_fields = [ 'diagnosis', 'adverse_effect_start_date', 'adverse_effect_end_date', 'ctcae_grade_lookup']
    list_filter = ['diagnosis__patient__patient_id']
    fieldsets = (
        ('Adverse Effects',{
            'fields':['diagnosis',('adverse_effect_start_date','adverse_effect_end_date')]
        }),
        ('Description',{
            'fields':[('ctcae_grade_lookup')]
        }),
    )
    resource_classes = [AdverseEffectsResource,AdverseEffectsExportResource]
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return AdverseEffectsExportResource

## Create the Patient Outcomes form class

class PatientOutcomeResource(resources.ModelResource):
    
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_patient_outcome_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_patient_outcome_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='patient_id'))
    patient_status = fields.Field(attribute='patient_status',column_name='patient_status',widget=ForeignKeyWidget(LookupOutcome,field='code'))
    
    class Meta:
        model = PatientOutcome
        import_id_fields = ['chavi_patient_outcome_id']
        fields = ['chavi_patient_outcome_id','patient','patient_status','date_of_death','death_related_to_cancer_progression']
        widgets = {
            'date_of_death': {'format': '%Y-%m-%d'},
        }

class PatientOutcomeExportResource(resources.ModelResource):
    class Meta:
        model = PatientOutcome
        fields = ['patient','chavi_patient_outcome_id']

@admin.register(PatientOutcome)
class PatientOutcomeAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['patient']
    list_display = ['patient', 'patient_status', 'date_of_death', 'death_related_to_cancer_progression']
    list_filter = ['patient_status', 'date_of_death', 'death_related_to_cancer_progression']
    resource_classes = [PatientOutcomeResource,PatientOutcomeExportResource]
    def get_export_resource_class(self):
        """
        Returns ResourceClass to use for export.
        """
        return PatientOutcomeExportResource


# Create the Outcome Resource
class OutcomeResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_outcome_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_outcome_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    outcome_type = fields.Field(attribute='outcome_type',column_name='outcome_type',widget=ForeignKeyWidget(LookupOutcomeType,field='code'))

    class Meta:
        model = Outcome
        import_id_fields = ['chavi_outcome_id']
        fields = ['chavi_outcome_id','diagnosis','date_outcome_assessed','outcome_type']
        widgets = {
            'date_outcome_assessed': {'format': '%Y-%m-%d'},
        }

## Create the Outcome Form Class
@admin.register(Outcome)
class OutcomeAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis']
    search_fields = ['diagnosis__diagnosis']
    filter_horizontal = ['outcome_dicom_study']
    list_filter = ['diagnosis__patient__patient_id']
    fieldsets = (
        ('Diagnosis',{
            'fields':[('diagnosis')]
        }),
        ('Description',{
            'fields':[('outcome_type','date_outcome_assessed')]
        }),
        ('Dicom Studies',{
            'fields':[('outcome_dicom_study')]
        }),
    )
    resource_classes = [OutcomeResource]

#endregion


# Create the Patient Reported Outcome Resource
class PatientReportedOutcomeResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_pro_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_pro_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='patient_id'))
    
    class Meta:
        model = PatientReportedOutcome
        import_id_fields = ['chavi_pro_id']
        fields = ['chavi_pro_id','patient','pro_assessment_date','pro_instrument','pro_scale','pro_question_id','pro_question','pro_answer','pro_score']
        widgets = {
            'pro_assessment_date': {'format': '%Y-%m-%d'},
        }

## Create the Patient Reported Outcome Form Class
@admin.register(PatientReportedOutcome)
class PatientReportedOutcomeAdmin (ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['patient']
    fieldsets = (
        ('Patient',{
            'fields':[('patient','pro_assessment_date')]
        }),
        ('PRO Data',{
            'fields':[('pro_instrument','pro_scale'),('pro_question_id','pro_question'),('pro_answer','pro_score')]
        }),
    )
    list_display = ['patient','pro_assessment_date', 'pro_instrument', 'pro_question_id',  'pro_score']
    list_filter = ['pro_assessment_date', 'pro_instrument', 'pro_scale']
    resource_classes = [PatientReportedOutcomeResource]

## Create the DICOM Study form Class
@admin.register(DICOMStudy)
class DICOMStudyAdmin (ModelAdmin):
    search_fields = ['patient__patient_id']
    list_display = ['patient', 'study_date', 'study_description', 'series_descriptions']
    autocomplete_fields = ['patient']
    fieldsets = (
        ('Patient',{
            'fields':[('patient','study_date')]
        }),
        ('Study Data',{
            'fields':[('study_instance_uid','study_description','series_descriptions')]
        }),
    )
    list_filter = ['study_date', 'patient']

## Create the Project form Class
@admin.register(Project)
class ProjectAdmin(ModelAdmin):
    inlines = [DICOMStudyProjectInline]
    readonly_fields = ['center']
    list_display = ['chavi_project_id', 'project_name', 'center', 'created_at']
    list_filter = ['center', 'created_at']

# Create the Laboratory Results form Class
class LaboratoryResultsResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_laboratory_result_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_laboratory_results_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='patient_id'))
    laboratory_test = fields.Field(attribute='laboratory_test',column_name='laboratory_test',widget=ForeignKeyWidget(LookupLaboratoryTest,field='code'))

    class Meta:
        model = LaboratoryResults
        import_id_fields = ['chavi_laboratory_result_id']
        fields = ['chavi_laboratory_result_id','patient','laboratory_test','result_date','result_value','result_unit']
        widgets = {
            'result_date': {'format': '%Y-%m-%d'},
        }
        
@admin.register(LaboratoryResults)
class LaboratoryResultsAdmin(ModelAdmin,ImportExportModelAdmin):
    autocomplete_fields = ['patient','laboratory_test']
    resource_classes = [LaboratoryResultsResource]



class GermlineGenomicAlterationsResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_germline_genomic_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_germline_genomic_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='patient_id'))
    cosmic_gene_name = fields.Field(attribute='cosmic_gene_name',column_name='cosmic_gene_name',widget=ForeignKeyWidget(LookupGene,field='code'))

    class Meta:
        model = GermlineGenomicAlterations
        import_id_fields = ['chavi_germline_genomic_id']
        fields = ['chavi_germline_genomic_id','patient','date_test','cosmic_gene_name','reference_sequence','protein_modification','variant_type','allele_frequency','read_depth','clinical_significance']
        widgets = {
            'date_test': {'format': '%Y-%m-%d'},
        }

@admin.register(GermlineGenomicAlterations)
class GermlineGenomicAlterationsAdmin(ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['patient','cosmic_gene_name']
    resource_classes = [GermlineGenomicAlterationsResource]
    list_display = ['patient','date_test','cosmic_gene_name','reference_sequence','protein_modification','variant_type','allele_frequency','read_depth','clinical_significance']


class SymptomResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_symptom_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_symptom_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='patient_id'))
    symptom = fields.Field(attribute='symptom',column_name='symptom',widget=ForeignKeyWidget(LookupSymptoms,field='code'))
    severity = fields.Field(attribute='severity',column_name='severity',widget=ForeignKeyWidget(LookupSeverity,field='code'))
    class Meta:
        model = Symptom
        import_id_fields = ['chavi_symptom_id']
        fields = ['chavi_symptom_id','patient','symptom','date_onset','date_symptom_assessment','duration_of_symptom','date_resolution','severity']
        widgets = {
            'date_onset': {'format': '%Y-%m-%d'},
            'date_symptom_assessment': {'format': '%Y-%m-%d'},
            'date_resolution': {'format': '%Y-%m-%d'},
        }
@admin.register(Symptom)
class SymptomAdmin(ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['patient','symptom']
    resource_classes = [SymptomResource]
    readonly_fields = ['date_onset']
    list_display = ['patient','symptom','date_onset','date_resolution','severity']




class PatientAssessmentResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_patient_assessment_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_patient_assessment_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='patient_id'))
    performance_status = fields.Field(attribute='performance_status',column_name='performance_status',widget=ForeignKeyWidget(LookupPerformanceStatus,field='code'))
    
    class Meta:
        model = PatientAssessment
        import_id_fields = ['chavi_patient_assessment_id']
        fields = ['chavi_patient_assessment_id','patient','date_assessment','height','weight','systolic_blood_pressure','diastolic_blood_pressure','pulse','respiratory_rate','performance_status','temperature']
        widgets = {
            'date_assessment': {'format': '%Y-%m-%d'},
        }
@admin.register(PatientAssessment)
class PatientAssessmentAdmin(ModelAdmin, ImportExportModelAdmin):
    autocomplete_fields = ['patient']
    resource_classes = [PatientAssessmentResource]
    list_display = ['patient','date_assessment','height','weight','systolic_blood_pressure','diastolic_blood_pressure','pulse','respiratory_rate','performance_status','temperature']


# Register your models here.
@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(ModelAdmin):
    list_display = ['chavi_center_id','center_name']

@admin.register(BulkDICOMUpload)
class BulkDICOMUploadAdmin(ModelAdmin):
    list_display = ['created_at', 'processed_at', 'status']
    readonly_fields = ['created_at', 'processed_at', 'status']
    actions = [process_bulk_dicom]
    change_form_template = os.path.join(BASE_DIR, 'templates', 'admin', 'change_form.html')
    guidance_text = """
    <h2>Guidance</h2>
    <p> This form allows you to upload DICOM data for several patients at the same time. This a convinience way to upload DICOM data for several patients in a single step but has a caveat that patient ID in the DICOM files <strong> MUST match an existing patient in the Patient database. </strong> <br>
     Therefore it is important that for all patients whose DICOM data is being uploaded the patient ID should be in a consistent format. After uploading please run the Process Bulk DICOM action to extract and organize the DICOM files. For files where a matching patient ID is found, the system will automatically associate the DICOM file with the correct patient and create a proper zip file with the patient DICOM data. If the patient ID cannot be matched it will store the DICOM data in a Unprocessed_DICOM folder for you to review.  </p>   <br>
    """


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    # Forms loaded from `unfold.forms`
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass

# Create a function to get the admin urls that we'll import in the project's urls.py
def get_custom_admin_urls():
    return [
        path('patient-search/', 
             admin.site.admin_view(lambda request: redirect('client_app:patient_search')), 
             name='patient-search'),
        path('patient-summary/', 
             admin.site.admin_view(lambda request: redirect(f"{reverse('client_app:patient_summary')}?{request.GET.urlencode()}")), 
             name='patient-summary'),
    ]