from django.contrib import admin
from .models import *
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
from .actions import export_patient_data



@admin.action(description = "Extract and Process DICOM File and extract metadata")
def process_dicom(modeladmin, request, queryset):
    '''
    This custom admin action is there to do the following :
    1. Unzip the uploaded zipped file into the temporary directory.
    2. From the directory take all DICOM files and change the Patient ID tag to match that of the patient ID in the query set. This ensures that the de-identification process will produce the same ID even if the patient has undergone imaging at different centers. 
    3. Extract the SOP Instance UID and Study Instance UID and then create save the files inside a folder inside the Media directory. The folder is specific for each patient. Thus all studies for a given patient will be stored in the same folder. 
    4. The created folder structure will thus look like this Patient_id > StudyInstanceUID > SOPInstanceUID.dcm
    5. Delete the temporary directory where the files were processed.
    '''
    # Function to sanitize paths
    def sanitize(path):
        return path.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
    
    for obj in queryset:
        # If the file is not there there raise an error.
        if not obj.file:
            messages.error(request, f"No file found for {obj.patient.patient_id}")
            continue

        # Create the temporary directory where the files will be processed.    
        temp_dir = Path(tempfile.TemporaryDirectory().name)
        # Extract Patient ID from the queryset for the object
        patient_id = obj.patient.patient_id
        # Keep the sanitized patient_id for future paths. 
        patient_path = sanitize(patient_id)
        save_path = Path(settings.MEDIA_ROOT) / patient_path
        save_path.mkdir(exist_ok=True, parents=True)

        study_uids = set()
        study_descriptions = {}  # Dict of sets for descriptions
        study_dates = {}  # Dict of sets for dates
        series_descriptions = {}  # Dict of sets for series descriptions

        try:
            # First we will extract all the files from the zip file
            with zipfile.ZipFile(obj.file.path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # Next we will process each DICOM file and extract the metadata

            dicom_files = [files for files in temp_dir.glob('**/*') if files.is_file()]

            for file in dicom_files:
                try:
                    # Read the DICOM Dataset
                    ds = dcmread(file)
                    # Get the Study Instance UID. We will use this to create folder paths.
                    study_instance_uid = ds.StudyInstanceUID
                    
                    # Collect study description with corresponding UID
                    if hasattr(ds, 'StudyDescription'):
                        study_descriptions[study_instance_uid] = ds.StudyDescription


                    # Collect study date with corresponding UID
                    if hasattr(ds, 'StudyDate') and ds.StudyDate:
                        try:
                            study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                            study_dates[study_instance_uid] = study_date
                        except ValueError as e:
                            messages.warning(request, f"Invalid date format in DICOM file {file.name}: {str(e)}")                    

                    # Collect series descriptions
                    if hasattr(ds, 'SeriesDescription'):
                        # Initialize a set for this study if it doesn't exist
                        if study_instance_uid not in series_descriptions:
                            series_descriptions[study_instance_uid] = set()
                        # Add the series description to the set
                        series_descriptions[study_instance_uid].add(ds.SeriesDescription)                    
                    
                    # Get the SOP Instance UID. This will become the filename.
                    sop_instance_uid = ds.SOPInstanceUID

                    # Ensure paths are sanitized for future use.
                    folder_path = sanitize(study_instance_uid)
                    file_path = sanitize(sop_instance_uid)

                    # Overwrite the patient ID with the patient ID. 
                    # This will ensure all DICOM files of a patient from different sources will have the same ID and help de-identification and linkage.
                    ds.PatientID = patient_id

                    # Create the directory structure

                    study_dir = Path(save_path) / folder_path
                    study_dir.mkdir(exist_ok=True, parents=True)
                    # Save the DICOM file
                    ds.save_as(study_dir / f"{file_path}.dcm")

                    # Add Study Instance UID, Modality and Study Description to sets prepared previously.
                    study_uids.add(study_instance_uid)


                except Exception as e:
                    messages.error(request, f"Error processing DICOM file {file.name} for {obj.patient.patient_id}: {str(e)}")
                    continue        
            
            #  Processing Study UID into the DICOMStudy Table
            for uid in study_uids:
                try: 
                    # Convert set of series descriptions to comma-separated string
                    series_desc_string = ', '.join(sorted(series_descriptions.get(uid, []))) if uid in series_descriptions else ''
                    
                    DICOMStudy.objects.update_or_create(
                        patient=obj.patient,
                        study_instance_uid=uid,
                        defaults={
                            'study_description': study_descriptions.get(uid),
                            'study_date': study_dates.get(uid),
                            'series_descriptions': series_desc_string,  # Add the new field
                        }
                    )
                    messages.success(request,f"Added DICOM study UID {uid} Data for {obj.patient.patient_id}")
                except Exception as e:
                    messages.error(request,f"Error adding DICOM data for Study")   

            # Convert the folder to zip format.

            try:
                shutil.make_archive(base_name=f"{save_path}", format = 'zip', root_dir = save_path)
                messages.success(request, f"Successfully converted folder to zip for {obj.patient.patient_id}")
                shutil.rmtree(save_path)
            except Exception as e:
                messages.error(request, f"Error converting folder to zip for {obj.patient.patient_id}: {str(e)}")

        except zipfile.BadZipFile:
            messages.error(request, f"Invalid zip file for {obj.patient.patient_id}")
            continue


# @admin.action(description = "Export all Patient Data as a JSON object")

# def export_patient_data(self, request, queryset):
#     """
#     Custom admin action to export complete patient data including all related models
#     """
#     try:
#         # Check if the queryset is too large
#         if queryset.count() > 100:  # Adjust this threshold as needed
#             messages.warning(
#                 request,
#                 "Exporting large number of patients. This might take a while."
#             )

#         # Process in chunks for large datasets
#         paginator = Paginator(queryset, 20)  # Process 20 patients at a time
#         all_data = []

#         for page_number in paginator.page_range:
#             page = paginator.page(page_number)
#             # Serialize each chunk
#             serializer = PatientSerializer(page.object_list, many=True)
#             all_data.extend(serializer.data)

#         # Convert to JSON with nice formatting
#         json_data = json.dumps(all_data, indent=2)
        
#         # Create the HTTP response with JSON file
#         response = HttpResponse(json_data, content_type='application/json')
        
#         # If single patient, use their ID in filename, otherwise use count
#         if queryset.count() == 1:
#             filename = f"patient_{queryset.first().patient_id}_complete_data.json"
#         else:
#             filename = f"patients_{queryset.count()}_complete_data.json"
        
#         response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
#         # Add success message
#         messages.success(
#             request, 
#             f"Successfully exported complete data for {queryset.count()} patient(s)"
#         )
        
#         return response

#     except Exception as e:
#         messages.error(request, f"Error exporting patient data: {str(e)}")
#         return None
#region inlinetables for many to many relations

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
       

@admin.register(LookupProtein)
class LookupProteinAdmin(admin.ModelAdmin):
    search_fields = ['protein_name']
    readonly_fields = ['code','gene_name','protein_name','all_gene_names','uniport_id']


@admin.register(LookupGene)
class LookupGeneAdmin(admin.ModelAdmin):
    search_fields = ['gene_name']
    readonly_fields = ['code','gene_name','gene_description','gene_aliases']

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
    search_fields = ['label']
    readonly_fields = ['code','label']


class ImmunohistochemistryInline(admin.StackedInline):
    model = Immunohistochemistry
    autocomplete_fields =['protein_name']
    extra = 1
    

class CytogeneticsInline(admin.StackedInline):
    model = Cytogenetics
    autocomplete_fields =['gene']
    extra = 1
    

class SomaticGenomicAlterationsInline(admin.StackedInline):
    model = SomaticGenomicAlterations
    autocomplete_fields = ['cosmic_gene_name']
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
@admin.register(PatientDicomFile)
class PatientDicomFileAdmin (admin.ModelAdmin):
    search_fields =[ 'patient__patient_id']
    list_display = ['patient','file','created_at','updated_at']
    fieldsets = (
        ('Patient DICOM File',{
            'fields': ['patient','file']  
        }),
    )
    actions = [
        process_dicom
    ]

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
    autocomplete_fields = ['patient','diagnosis','cancer_site']
    filter_horizontal = ['diagnosis_dicom_study','diagnosis_project']
    list_filter = ['diagnostic_modality']
    list_fields = ['patient','diagnosis','diagnosis_date','diagnostic_modality','presentation_type']
    fieldsets = (
        ('Diagnosis',{
            'fields': ['patient','cancer_system','diagnosis',('diagnosis_date','diagnostic_modality')]
        }),
        ('Presentation',{
            "fields": [('presentation_type','cancer_site','cancer_side')]
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
    inlines = [ImmunohistochemistryInline,CytogeneticsInline,SomaticGenomicAlterationsInline]
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
    autocomplete_fields = ['patient']
    list_display = ['patient','comorbidity_type','created_at']
    list_filter = ['created_at']
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

## Create the Patient Reported Outcome Form Class
@admin.register(PatientReportedOutcome)
class PatientReportedOutcomeAdmin (admin.ModelAdmin):
    autocomplete_fields = ['patient']
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
    search_fields = ['patient__patient_id']
    list_display = ['patient','study_date','study_description','series_descriptions']
    autocomplete_fields = ['patient']
    fieldsets = (
        ('Patient',{
            'fields':[('patient','study_date')]
        }),
        ('Study Data',{
            'fields':[('study_instance_uid','study_description','series_descriptions')]
        }),
    )

## Create the Project form Class
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    inlines = [DICOMStudyProjectInline]
    readonly_fields = ['center']

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



# Register your models here.
admin.site.register(SiteConfiguration)
