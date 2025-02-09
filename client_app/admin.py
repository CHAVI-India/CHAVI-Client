from django.contrib import admin
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
from import_export.widgets import ForeignKeyWidget
from import_export import fields
from .services.patient_data_export import export_patient_data
from allauth.account.decorators import secure_admin_login
from .services.dicom_data_import_per_patient import process_dicom
from .services.bulk_dicom_data_import import process_bulk_dicom

# For Django AllAuth
admin.autodiscover()
admin.site.login = secure_admin_login(admin.site.login)

#endregion
class DICOMStudyProjectInline(admin.TabularInline):
    model = DICOMStudyProject
    extra = 1
    search_fields = ['dicom_study']
    autocomplete_fields = ['dicom_study']    

#endregion

#region Inlines for Foreign Key relations.

class SystemicTherapyScheduleInline(admin.StackedInline):
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
       
# Register Lookup Models so that autocomplete fields work.
@admin.register(LookupProtein)
class LookupProteinAdmin(admin.ModelAdmin):
    search_fields = ['protein_name']
    readonly_fields = ['code','gene_name','protein_name','all_gene_names','uniport_id']


@admin.register(LookupGene)
class LookupGeneAdmin(admin.ModelAdmin):
    search_fields = ['code','label']
    # readonly_fields = ['code','label']

@admin.register(LookupPathology)
class LookupPathologyAdmin(admin.ModelAdmin):
    search_fields = ['label','code']
    readonly_fields = ['code','label']

@admin.register(LookupCTCAEGrade)
class LookupCTCAEGradeAdmin (admin.ModelAdmin):
    search_fields = ['ctcae_term','ctcae_grade']
    readonly_fields = ['code','ctcae_term','ctcae_grade','meddra_code','description']

@admin.register(LookupSystemicAgent)
class LookupSystemicAgentAdmin (admin.ModelAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label']


@admin.register(LookupCytogeneticAbnormality)
class LookupCytogeneticAbnormalityAdmin(admin.ModelAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label']

@admin.register(LookupICDCode)
class LookupICDCodeAdmin (admin.ModelAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label','icd_version']

@admin.register(LookupFMACode)
class LookupFMACodeAdmin (admin.ModelAdmin):
    search_fields = ['code','label']
    readonly_fields = ['code','label']

@admin.register(LookupLaboratoryTest)
class LookupLaboratoryTestAdmin (admin.ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupStageDescriptor)
class LookupStageDescriptorAdmin(admin.ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']

@admin.register(LookupSymptoms)
class LookupSymptomsAdmin(admin.ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']

@admin.register(LookupMajorCancerCategory)
class LookupMajorCancerCategoryAdmin(admin.ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']


@admin.register(LookupIHCAntibody)
class LookupIHCAntibodyAdmin(admin.ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']

@admin.register(LookupEpigeneticAbnormalityType)
class LookupEpigeneticAbnormalityTypeAdmin(admin.ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']

@admin.register(LookupComorbidity)
class LookupComorbidityAdmin(admin.ModelAdmin):
    search_fields = ['label']
    readonly_fields = ['code','label']

# Create Inline Models


class ImmunohistochemistryInline(admin.StackedInline):
    model = Immunohistochemistry
    autocomplete_fields =['protein_name']
    extra = 1
    

class CytogeneticsInline(admin.StackedInline):
    model = Cytogenetics
    autocomplete_fields =['gene','cytogentic_abnormality']
    extra = 1
    

class SomaticGenomicAlterationsInline(admin.StackedInline):
    model = SomaticGenomicAlterations
    autocomplete_fields = ['cosmic_gene_name']
    extra = 1
    

class GeneExpressionDataInline(admin.StackedInline):
    model = GeneExpressionData
    autocomplete_fields = ['gene']
    extra = 1

class EpigeneticDataInline(admin.StackedInline):
    model = EpigeneticData
    autocomplete_fields = ['gene']
    extra = 1

class RadiotherapyVolumeInline(admin.StackedInline):
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

class RadiotherapyDoseVolumeDataInline(admin.TabularInline):
    model = RadiotherapyDoseVolumeData
    extra = 1
    

#endregion

#region modelclasses

# Add Model classes

## Create the Patient Form Class along with the export import configuration
class PatientResource(resources.ModelResource):
    class Meta:
        model = Patient
        import_id_fields = ['patient_id']

@admin.register(Patient)
class PatientAdmin(ImportExportModelAdmin):
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
    change_form_template = 'admin/client_app/change_form.html'
    guidance_text = """
    <h2>Guidance</h2>
    <p>This form allows you to enter data for patients in the CHAVI database. This is the key form to fill as the patient ID will be used for all other forms. <br>
    For patients who have a CHAVI consent done please choose Yes and input the date of the consent. You can assign a patient to multiple projects also in this form. <br> Please note that DICOM data can be associated with the patient only after the Patient ID is entered.</p>    <br>
    """



@admin.register(PatientDicomFile)
class PatientDicomFileAdmin(admin.ModelAdmin):
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
    change_form_template = 'admin/client_app/change_form.html'
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
    cancer_system = fields.Field(attribute='cancer_system',column_name='cancer_system',widget=ForeignKeyWidget(LookupMajorCancerCategory,field='label'))
    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(LookupICDCode,field='label'))
    diagnostic_modality = fields.Field(attribute='diagnostic_modality',column_name='diagnostic_modality',widget=ForeignKeyWidget(LookupDiagnosticModality,field='label'))
    presentation_type = fields.Field(attribute='presentation_type',column_name='presentation_type',widget=ForeignKeyWidget(LookupPresentation,field='label'))
    cancer_site = fields.Field(attribute='cancer_site',column_name='cancer_site',widget=ForeignKeyWidget(LookupFMACode,field='label'))
    cancer_side = fields.Field(attribute='cancer_side',column_name='cancer_side',widget=ForeignKeyWidget(LookupLaterality,field='label'))

    class Meta:
        model = Diagnosis
        import_id_fields = ['chavi_diagnosis_id']
        fields = ['patient','cancer_system','diagnosis','diagnosis_date','diagnostic_modality','presentation_type','cancer_site','cancer_side']

# Create the Diagnosis Form Class
@admin.register(Diagnosis)
class DiagnosisAdmin (ImportExportModelAdmin):
    search_fields = ['patient']
    autocomplete_fields = ['patient','diagnosis','cancer_site','cancer_system']
    filter_horizontal = ['diagnosis_dicom_study','diagnosis_project']
    list_filter = ['diagnostic_modality']
    list_fields = ['patient','diagnosis','diagnosis_date','diagnostic_modality','presentation_type']
    fieldsets = (
        ('Diagnosis',{
            'fields': ['patient','diagnosis',('diagnosis_date','diagnostic_modality')]
        }),
        ('Presentation',{
            "fields": ['cancer_system','cancer_site',('cancer_side','presentation_type')]
        }),
        ('DICOM Studies',{
            'fields': ['diagnosis_dicom_study']
        }),
        ('Projects',{
            'fields': ['diagnosis_project']
        }),
    )
    resource_classes = [DiagnosisResource]


## Create the Pathology Form Class
class PathologyResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_pathology_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_pathology_id'] = str(uuid.uuid4())


    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    tumor_site = fields.Field(attribute='tumor_site',column_name='tumor_site',widget=ForeignKeyWidget(LookupFMACode,field='label'))
    tumor_side = fields.Field(attribute='tumor_side',column_name='tumor_side',widget=ForeignKeyWidget(LookupLaterality,field='label'))
    histological_type = fields.Field(attribute='histological_type',column_name='histological_type',widget=ForeignKeyWidget(LookupPathology,field='label'))
    histological_grade = fields.Field(attribute='histological_grade',column_name='histological_grade',widget=ForeignKeyWidget(LookupGrade,field='label'))
    tumor_dimesion_unit = fields.Field(attribute='tumor_dimesion_unit',column_name='tumor_dimesion_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='label'))
    lymphatic_vascular_invasion = fields.Field(attribute='lymphatic_vascular_invasion',column_name='lymphatic_vascular_invasion',widget=ForeignKeyWidget(LookupPathologyDescriptors,field='label'))
    perineural_invasion = fields.Field(attribute='perineural_invasion',column_name='perineural_invasion',widget=ForeignKeyWidget(LookupPathologyDescriptors,field='label'))
    dermal_lymphatic_vascular_invasion = fields.Field(attribute='dermal_lymphatic_vascular_invasion',column_name='dermal_lymphatic_vascular_invasion',widget=ForeignKeyWidget(LookupPathologyDescriptors,field='label'))
    necrosis = fields.Field(attribute='necrosis',column_name='necrosis',widget=ForeignKeyWidget(LookupPathologyDescriptors,field='label'))
    margin_status = fields.Field(attribute='margin_status',column_name='margin_status',widget=ForeignKeyWidget(LookupMarginStatus,field='label'))    
    closest_margin_distance_unit = fields.Field(attribute='closest_margin_distance_unit',column_name='closest_margin_distance_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='label'))
    treatment_effect = fields.Field(attribute='treatment_effect',column_name='treatment_effect',widget=ForeignKeyWidget(LookupTreatmentEffect,field='label'))

    
    class Meta:
        model = Pathology
        import_id_fields = ['chavi_pathology_id']
        fields = ['diagnosis','date_pathology','specimen_type','tumor_site','tumor_side','greatest_dimension_of_tumor','additional_tumor_dimension_1','additional_tumor_dimension_2','tumor_dimesion_unit','tumor_focality','histological_type','histological_grade','lymphatic_vascular_invasion','perineural_invasion','dermal_lymphatic_vascular_invasion','necrosis','necrosis_percentage','mitotic_count','margin_status','closest_margin_distance','closest_margin_distance_unit','treatment_effect','primary_gleason_grade','secondary_gleason_grade','lymph_nodes_removed','lymph_nodes_in_specimen','number_of_uninvolved_nodes','number_of_nodes_with_macrometastases','number_of_nodes_with_micrometastases','number_of_nodes_with_isolated_tumor_cells']

@admin.register(Pathology)
class PathologyAdmin (ImportExportModelAdmin):
    inlines = [ImmunohistochemistryInline,CytogeneticsInline,SomaticGenomicAlterationsInline,GeneExpressionDataInline,EpigeneticDataInline]
    autocomplete_fields = ['diagnosis','tumor_site','histological_type']
    search_fields = ['diagnosis__patient_id']
    list_filter = ['date_pathology','tumor_side__label']
    list_display = ['diagnosis__patient_id','diagnosis','date_pathology','tumor_site__label','tumor_side__label','histological_type','lymph_nodes_in_specimen']
    fieldsets = (
        ('Pathology',{
            'fields': ['diagnosis',('date_pathology','specimen_type'),('tumor_site','tumor_side'),('greatest_dimension_of_tumor','additional_tumor_dimension_1','additional_tumor_dimension_2','tumor_dimesion_unit'),'tumor_focality']
        }),
        ('Histology',{
            'fields': [('histological_type','histological_grade'),('lymphatic_vascular_invasion','perineural_invasion','dermal_lymphatic_vascular_invasion'),('necrosis','necrosis_percentage'),('mitotic_count'),('margin_status','closest_margin_distance','closest_margin_distance_unit'),('treatment_effect'),('primary_gleason_grade','secondary_gleason_grade')]
        }),
        ('Nodes',{
            'fields': [('lymph_nodes_removed','lymph_nodes_in_specimen'),('number_of_nodes_with_macrometastases','number_of_nodes_with_micrometastases','number_of_nodes_with_isolated_tumor_cells')]
        }),
    )
    resource_classes = [PathologyResource]


# Create the Stage Information Resource
class StageInformationResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_stage_information_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_stage_information_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    staging_system = fields.Field(attribute='staging_system',column_name='staging_system',widget=ForeignKeyWidget(LookupStagingSystem,field='label'))
    stage_type = fields.Field(attribute='stage_type',column_name='stage_type',widget=ForeignKeyWidget(LookupStagingType,field='label'))
    t_stage_prefix = fields.Field(attribute='t_stage_prefix',column_name='t_stage_prefix',widget=ForeignKeyWidget(LookupAJCCStagePrefix,field='label'))
    t_stage = fields.Field(attribute='t_stage',column_name='t_stage',widget=ForeignKeyWidget(LookupAJCCTStageDescriptor,field='label'))
    t_stage_suffix = fields.Field(attribute='t_stage_suffix',column_name='t_stage_suffix',widget=ForeignKeyWidget(LookupAJCCStageSuffix,field='label'))
    n_stage_prefix = fields.Field(attribute='n_stage_prefix',column_name='n_stage_prefix',widget=ForeignKeyWidget(LookupAJCCStagePrefix,field='label'))
    n_stage = fields.Field(attribute='n_stage',column_name='n_stage',widget=ForeignKeyWidget(LookupAJCCNStageDescriptor,field='label'))
    n_stage_suffix = fields.Field(attribute='n_stage_suffix',column_name='n_stage_suffix',widget=ForeignKeyWidget(LookupAJCCStageSuffix,field='label'))
    m_stage_prefix = fields.Field(attribute='m_stage_prefix',column_name='m_stage_prefix',widget=ForeignKeyWidget(LookupAJCCStagePrefix,field='label'))
    m_stage = fields.Field(attribute='m_stage',column_name='m_stage',widget=ForeignKeyWidget(LookupAJCCMStageDescriptor,field='label'))
    m_stage_suffix = fields.Field(attribute='m_stage_suffix',column_name='m_stage_suffix',widget=ForeignKeyWidget(LookupAJCCStageSuffix,field='label'))
    overall_stage = fields.Field(attribute='overall_stage',column_name='overall_stage',widget=ForeignKeyWidget(LookupStageDescriptor,field='label'))    

    class Meta:
        model = StageInformation
        import_id_fields = ['chavi_stage_information_id']
        fields = ['diagnosis','staging_system','stage_type','t_stage_prefix','t_stage','t_stage_suffix','n_stage_prefix','n_stage','n_stage_suffix','m_stage_prefix','m_stage','m_stage_suffix','overall_stage']


## Create the Stage Information Form Class
@admin.register(StageInformation)
class StageInformationAdmin (ImportExportModelAdmin):
    search = ['diagnosis__patient_id']
    autocomplete_fields = ['diagnosis','overall_stage']
    list_filter = ['diagnosis','staging_system__label','stage_type','overall_stage']
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
    resource_classes = [StageInformationResource]


class ComorbidityResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_comorbidity_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_comorbidity_id'] = str(uuid.uuid4())


    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='chavi_patient_id'))

    class Meta:
        model = Comorbidity
        import_id_fields = ['chavi_comorbidity_id']
        fields = ['patient','comorbidity_type','created_at']

## Create the Comorbidity Form

@admin.register(Comorbidity)
class ComorbidityAdmin (ImportExportModelAdmin):
    autocomplete_fields = ['patient','comorbidity_type']
    list_display = ['patient', 'comorbidity_type', 'date_of_comorbidity_diagnosis', 'created_at']
    list_filter = ['date_of_comorbidity_diagnosis', 'created_at']
    resource_classes = [ComorbidityResource]


# Create the Lesion Resource
class LesionResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_lesion_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_lesion_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    lesion_site = fields.Field(attribute='lesion_site',column_name='lesion_site',widget=ForeignKeyWidget(LookupFMACode,field='label'))
    lesion_laterality = fields.Field(attribute='lesion_laterality',column_name='lesion_laterality',widget=ForeignKeyWidget(LookupLaterality,field='label'))
    lesion_type = fields.Field(attribute='lesion_type',column_name='lesion_type',widget=ForeignKeyWidget(LookupLesionType,field='label'))
    lesion_size_unit = fields.Field(attribute='lesion_size_unit',column_name='lesion_size_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='label'))
    lesion_volume_unit = fields.Field(attribute='lesion_volume_unit',column_name='lesion_volume_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='label'))

    class Meta:
        model = Lesion
        import_id_fields = ['chavi_lesion_id']
        fields = ['diagnosis','date_lesion_assessed','lesion_site','lesion_laterality','lesion_type','lesion_size_x_axis','lesion_size_y_axis','lesion_size_z_axis','lesion_size_unit','lesion_volume','lesion_volume_unit']


## Create the Lesion Form Class
@admin.register(Lesion)
class LesionAdmin (ImportExportModelAdmin):
    search_fields = ['diagnosis','lesion_site','lesion_type']
    autocomplete_fields = ['diagnosis','lesion_site']
    filter_horizontal = ['lesion_dicom_study']
    fieldsets = (
        ('Lesion', {
            'fields' : [('diagnosis','date_lesion_assessed'),('lesion_site','lesion_laterality','lesion_type')]
        }),
        ('Dimensions', {
            'fields' : [('lesion_size_x_axis', 'lesion_size_y_axis', 'lesion_size_z_axis','lesion_size_unit'), ('lesion_volume','lesion_volume_unit')]

        }),
        ('DICOM Studies', {
            'fields' : ['lesion_dicom_study']
        })
    )   
    resource_classes = [LesionResource]

class LesionResponseResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_lesion_response_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_lesion_response_id'] = str(uuid.uuid4())

    lesion = fields.Field(attribute='lesion',column_name='lesion',widget=ForeignKeyWidget(Lesion,field='chavi_lesion_id'))
    lesion_response = fields.Field(attribute='lesion_response',column_name='lesion_response',widget=ForeignKeyWidget(LookupResponseType,field='label'))
    residual_lesion_size_unit = fields.Field(attribute='residual_lesion_size_unit',column_name='residual_lesion_size_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='label'))
    residual_lesion_volume_unit = fields.Field(attribute='residual_lesion_volume_unit',column_name='residual_lesion_volume_unit',widget=ForeignKeyWidget(LookupSizeUnits,field='label'))

    class Meta:
        model = LesionResponse
        import_id_fields = ['chavi_lesion_response_id']
        fields = ['lesion','lesion_response_date','lesion_response','residual_lesion_size_x_axis','residual_lesion_size_y_axis','residual_lesion_size_z_axis','residual_lesion_size_unit','residual_lesion_volume','residual_lesion_volume_unit']

## Create the Lesion Response Form Class
@admin.register(LesionResponse)
class LesionResponseAdmin (ImportExportModelAdmin):
    autocomplete_fields = ['lesion']
    filter_horizontal = ['lesion_response_dicom_study']
    resource_classes = [LesionResponseResource]
    list_display = ['lesion', 'lesion_response_date', 'lesion_response', 'residual_lesion_volume']
    list_filter = ['lesion_response_date', 'lesion_response']


class RadiotherapyResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_radiotherapy_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_radiotherapy_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    radiotherapy_modality = fields.Field(attribute='radiotherapy_modality',column_name='radiotherapy_modality',widget=ForeignKeyWidget(LookupRadiotherapyModality,field='label'))
    radiation_dose_units = fields.Field(attribute='radiation_dose_units',column_name='radiation_dose_units',widget=ForeignKeyWidget(LookupDoseUnits,field='label'))
    radiotherapy_type = fields.Field(attribute='radiotherapy_type',column_name='radiotherapy_type',widget=ForeignKeyWidget(LookupRadiotherapyType,field='label'))
    radiotherapy_technique = fields.Field(attribute='radiotherapy_technique',column_name='radiotherapy_technique',widget=ForeignKeyWidget(LookupRadiotherapyTechnique,field='label'))
    radiotherapy_side = fields.Field(attribute='radiotherapy_side',column_name='radiotherapy_side',widget=ForeignKeyWidget(LookupLaterality,field='label'))

    class Meta:
        model = Radiotherapy
        import_id_fields = ['chavi_radiotherapy_id']
        fields = ['diagnosis','radiotherapy_start_date','radiotherapy_end_date','radiotherapy_side','radiotherapy_course_type','reirradiation','radiotherapy_modality','radiotherapy_type','radiotherapy_machine','total_dose','radiation_dose_units','simultaneous_integrated_boost','simultaneous_integrated_boost_dose','total_fractions','fractions_per_day','radiotherapy_technique']


## Create the Radiotherapy Form Class

@admin.register(Radiotherapy)
class RadiotherapyAdmin (ImportExportModelAdmin):
    inlines=[RadiotherapyVolumeInline,RadiotherapyDoseVolumeDataInline]
    autocomplete_fields = ['diagnosis']
    filter_horizontal = ['radiotherapy_dicom_study']
    fieldsets = (
        ('Radiotherapy',{
            'fields': ['diagnosis',('radiotherapy_start_date','radiotherapy_end_date'),( 'radiotherapy_side','radiotherapy_course_type','reirradiation')]
        }),
        ('Description',{
            'fields': [('radiotherapy_modality','radiotherapy_type','radiotherapy_machine'),('total_dose','radiation_dose_units'),('simultaneous_integrated_boost','simultaneous_integrated_boost_dose'),('total_fractions','fractions_per_day')]
        }),
        ('DICOM Studies',{
            'fields': ['radiotherapy_dicom_study']
        }),
    )
    resource_classes = [RadiotherapyResource]
 

## Create the Surgery Resource
class SurgeryResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_surgery_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_surgery_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    surgery_side = fields.Field(attribute='surgery_side',column_name='surgery_side',widget=ForeignKeyWidget(LookupLaterality,field='label'))


    class Meta:
        model = Surgery
        import_id_fields = ['chavi_surgery_id']
        fields = ['diagnosis','surgery_date','surgery_side','surgery_type','nodal_assessment','nodal_assessment_type','reconstruction','type_reconstruction']


## Create the Surgery Form Class
@admin.register(Surgery)
class SurgeryAdmin (ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis']
    filter_horizontal = ['surgery_dicom_study']
    fieldsets = (
        ('Surgery', {
            'fields':['diagnosis','surgery_date']
        }),
        ('Description',{
            'fields':[('surgery_side','surgery_type'),('nodal_assessment','nodal_assessment_type')]
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
    systemic_therapy_type = fields.Field(attribute='systemic_therapy_type',column_name='systemic_therapy_type',widget=ForeignKeyWidget(LookupSystemicTherapyType,field='label'))
    systemic_therapy_sequence = fields.Field(attribute='systemic_therapy_sequence',column_name='systemic_therapy_sequence',widget=ForeignKeyWidget(LookupTreatmentSequence,field='label'))
    systemic_therapy_regimen = fields.Field(attribute='systemic_therapy_regimen',column_name='systemic_therapy_regimen',widget=ForeignKeyWidget(LookupSystemicTherapyRegimen,field='label'))

    class Meta:
        model = SystemicTherapy
        import_id_fields = ['chavi_systemic_therapy_id']
        fields = ['diagnosis','systemic_therapy_type','systemic_therapy_sequence','systemic_therapy_regimen','cycles_delivered','systemic_therapy_start_date','systemic_therapy_end_date']


## Create the Systemic Therapy Form Class
@admin.register(SystemicTherapy)
class SystemicTherapyAdmin (ImportExportModelAdmin):
    inlines = [SystemicTherapyScheduleInline]
    autocomplete_fields = ['diagnosis']
    search_fields = ['diagnosis__diagnosis']
    filter_horizontal =['systemic_therapy_dicom_study']
    fieldsets = (
        ('Systemic Therapy',{
            'fields':['diagnosis',('systemic_therapy_start_date','systemic_therapy_end_date')]
        }),
        ('Description',{
            'fields':[('systemic_therapy_type','systemic_therapy_sequence'),('systemic_therapy_regimen','cycles_delivered')]
        }),
        ('DICOM Studies',{
            'fields': ['systemic_therapy_dicom_study']
        }),        
    )
    resource_classes = [SystemicTherapyResource]

## Create the ConcomitantMedications Form Class
class ConcomitantMedicationsResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_medication_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_medication_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    medication_dose_units = fields.Field(attribute='medication_dose_units',column_name='medication_dose_units',widget=ForeignKeyWidget(LookupDoseUnits,field='label'))

    class Meta:
        model = ConcomitantMedications
        import_id_fields = ['chavi_medication_id']
        fields = ['diagnosis','medication_name','medication_route','medication_dose','medication_dose_units','date_medication_start_date','date_medication_end_date']


@admin.register(ConcomitantMedications)
class ConcomitantMedicationsAdmin (ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis']
    fieldsets = (
        ('Concomitant Medications',{
            'fields':['diagnosis',('medication_name','medication_route'),('medication_dose','medication_dose_units'),('date_medication_start_date', 'date_medication_end_date')]
        }),
    )
    resource_classes = [ConcomitantMedicationsResource]
    list_display = ['diagnosis', 'medication_name', 'medication_dose', 'date_medication_start_date', 'date_medication_end_date']
    list_filter = ['date_medication_start_date', 'date_medication_end_date', 'medication_route']


# Create the Other Treatment Resource
class OtherTreatmentResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_treatment_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_treatment_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    class Meta:
        model = OtherTreatment
        import_id_fields = ['chavi_treatment_id']
        fields = ['diagnosis','treatment_start_date','treatment_end_date','treatment']

## Create the Other Treatment Form Class
@admin.register(OtherTreatment)
class OtherTreatmentAdmin (ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis']
    fieldsets = (
        ('Description',{
            'fields':['diagnosis',('treatment_start_date','treatment_end_date'),'treatment']
        }),
    )
    resource_classes = [OtherTreatmentResource]
    list_display = ['diagnosis', 'treatment', 'treatment_start_date', 'treatment_end_date']
    list_filter = ['treatment_start_date', 'treatment_end_date']


## Create the Adverse Effects form class
class AdverseEffectsResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_adverse_effects_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_adverse_effects_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    ctcae_grade_lookup = fields.Field(attribute='ctcae_grade_lookup',column_name='ctcae_grade_lookup',widget=ForeignKeyWidget(LookupCTCAEGrade,field='label'))

    class Meta:
        model = AdverseEffects
        import_id_fields = ['chavi_adverse_effects_id']
        fields = ['diagnosis','adverse_effect_start_date','adverse_effect_end_date','ctcae_grade_lookup']

# Create the Adverse Effects form Class
@admin.register(AdverseEffects)
class AdverseEffectsAdmin (ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis','ctcae_grade_lookup']
    list_fields = [ 'diagnosis', 'adverse_effect_start_date', 'adverse_effect_end_date', 'ctcae_grade_lookup']
    fieldsets = (
        ('Adverse Effects',{
            'fields':['diagnosis',('adverse_effect_start_date','adverse_effect_end_date')]
        }),
        ('Description',{
            'fields':[('ctcae_grade_lookup')]
        }),
    )
    resource_classes = [AdverseEffectsResource]

## Create the Patient Outcomes form class

class PatientOutcomeResource(resources.ModelResource):
    
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_patient_outcome_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_patient_outcome_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='chavi_patient_id'))
    patient_status = fields.Field(attribute='patient_status',column_name='patient_status',widget=ForeignKeyWidget(LookupOutcome,field='label'))
    
    class Meta:
        model = PatientOutcome
        import_id_fields = ['chavi_patient_outcome_id']
        fields = ['patient','patient_status','date_of_death','death_related_to_cancer_progression']

@admin.register(PatientOutcome)
class PatientOutcomeAdmin (ImportExportModelAdmin):
    autocomplete_fields = ['patient']
    resource_classes = [PatientOutcomeResource]
    list_display = ['patient', 'patient_status', 'date_of_death', 'death_related_to_cancer_progression']
    list_filter = ['patient_status', 'date_of_death', 'death_related_to_cancer_progression']

# Create the Outcome Resource
class OutcomeResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_outcome_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_outcome_id'] = str(uuid.uuid4())

    diagnosis = fields.Field(attribute='diagnosis',column_name='diagnosis',widget=ForeignKeyWidget(Diagnosis,field='chavi_diagnosis_id'))
    outcome_type = fields.Field(attribute='outcome_type',column_name='outcome_type',widget=ForeignKeyWidget(LookupOutcomeType,field='label'))

    class Meta:
        model = Outcome
        import_id_fields = ['chavi_outcome_id']
        fields = ['diagnosis','date_outcome_assessed','outcome_type']

## Create the Outcome Form Class
@admin.register(Outcome)
class OutcomeAdmin (ImportExportModelAdmin):
    autocomplete_fields = ['diagnosis']
    search_fields = ['diagnosis__diagnosis']
    filter_horizontal = ['outcome_dicom_study']
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

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='chavi_patient_id'))
    
    class Meta:
        model = PatientReportedOutcome
        import_id_fields = ['chavi_pro_id']
        fields = ['patient','pro_assessment_date','pro_instrument','pro_scale','pro_question_id','pro_question','pro_answer','pro_score']



## Create the Patient Reported Outcome Form Class
@admin.register(PatientReportedOutcome)
class PatientReportedOutcomeAdmin (ImportExportModelAdmin):
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
class DICOMStudyAdmin (admin.ModelAdmin):
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
class ProjectAdmin(admin.ModelAdmin):
    inlines = [DICOMStudyProjectInline]
    readonly_fields = ['center']
    list_display = ['chavi_project_id', 'center', 'created_at']
    list_filter = ['center', 'created_at']

# Create the Laboratory Results form Class
class LaboratoryResultsResource(resources.ModelResource):

    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_laboratory_result_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_laboratory_results_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='chavi_patient_id'))
    laboratory_test = fields.Field(attribute='laboratory_test',column_name='laboratory_test',widget=ForeignKeyWidget(LookupLaboratoryTest,field='label'))

    class Meta:
        model = LaboratoryResults
        import_id_fields = ['chavi_laboratory_result_id']
        fields = ['patient','laboratory_test','result_date','result_value','result_unit']
        
@admin.register(LaboratoryResults)
class LaboratoryResultsAdmin(ImportExportModelAdmin):
    autocomplete_fields = ['patient','laboratory_test']
    resource_classes = [LaboratoryResultsResource]



class GermlineGenomicAlterationsResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_germline_genomic_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_germline_genomic_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='chavi_patient_id'))
    cosmic_gene_name = fields.Field(attribute='cosmic_gene_name',column_name='cosmic_gene_name',widget=ForeignKeyWidget(LookupGene,field='label'))

    class Meta:
        model = GermlineGenomicAlterations
        import_id_fields = ['chavi_germline_genomic_id']
        fields = ['patient','date_test','cosmic_gene_name','reference_sequence','protein_modification','variant_type','allele_frequency','read_depth','clinical_significance']

@admin.register(GermlineGenomicAlterations)
class GermlineGenomicAlterationsAdmin(ImportExportModelAdmin):
    autocomplete_fields = ['patient','cosmic_gene_name']
    resource_classes = [GermlineGenomicAlterationsResource]
    list_display = ['patient','date_test','cosmic_gene_name','reference_sequence','protein_modification','variant_type','allele_frequency','read_depth','clinical_significance']


class SymptomResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_symptom_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_symptom_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='chavi_patient_id'))
    symptom = fields.Field(attribute='symptom',column_name='symptom',widget=ForeignKeyWidget(LookupSymptoms,field='label'))
    severity = fields.Field(attribute='severity',column_name='severity',widget=ForeignKeyWidget(LookupSeverity,field='label'))
    class Meta:
        model = Symptom
        import_id_fields = ['chavi_symptom_id']
        fields = ['patient','symptom','date_onset','date_resolution','severity']
@admin.register(Symptom)
class SymptomAdmin(ImportExportModelAdmin):
    autocomplete_fields = ['patient','symptom']
    resource_classes = [SymptomResource]
    list_display = ['patient','symptom','date_onset','date_resolution','severity']


class PatientAssessmentResource(resources.ModelResource):
    def before_import(self,dataset,**kwargs):
        dataset.headers.append('chavi_patient_assessment_id')
        super().before_import(dataset,**kwargs)

    def before_import_row(self,row,**kwargs):
        row['chavi_patient_assessment_id'] = str(uuid.uuid4())

    patient = fields.Field(attribute='patient',column_name='patient',widget=ForeignKeyWidget(Patient,field='chavi_patient_id'))
    performance_status = fields.Field(attribute='performance_status',column_name='performance_status',widget=ForeignKeyWidget(LookupPerformanceStatus,field='code'))
    
    class Meta:
        model = PatientAssessment
        import_id_fields = ['chavi_patient_assessment_id']
        fields = ['patient','date_assessment','height','weight','systolic_blood_pressure','diastolic_blood_pressure','pulse','respiratory_rate','performance_status','temperature']
@admin.register(PatientAssessment)
class PatientAssessmentAdmin(ImportExportModelAdmin):
    autocomplete_fields = ['patient']
    resource_classes = [PatientAssessmentResource]
    list_display = ['patient','date_assessment','height','weight','systolic_blood_pressure','diastolic_blood_pressure','pulse','respiratory_rate','performance_status','temperature']


# Register your models here.
admin.site.register(SiteConfiguration)

@admin.register(BulkDICOMUpload)
class BulkDICOMUploadAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'processed_at', 'status']
    readonly_fields = ['created_at', 'processed_at', 'status']
    actions = ['process_bulk_dicom']
    change_form_template = 'admin/client_app/change_form.html'
    guidance_text = """
    <h2>Guidance</h2>
    <p> This form allows you to upload DICOM data for several patients at the same time. This a convinience way to upload DICOM data for several patients in a single step but has a caveat that patient ID in the DICOM files <strong> MUST match an existing patient in the Patient database. </strong> <br>
     Therefore it is important that for all patients whose DICOM data is being uploaded the patient ID should be in a consistent format. After uploading please run the Process Bulk DICOM action to extract and organize the DICOM files. For files where a matching patient ID is found, the system will automatically associate the DICOM file with the correct patient and create a proper zip file with the patient DICOM data. If the patient ID cannot be matched it will store the DICOM data in a Unprocessed_DICOM folder for you to review.  </p>   <br>
    """
