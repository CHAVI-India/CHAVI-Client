from django.contrib import admin
from solo.admin import SingletonModelAdmin
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

#region inlinetables for many to many relations

#region comments

# Define inlines for Many to Many relations
# class PatientProjectInline(admin.TabularInline):
#     model = PatientProject
#     extra = 1

# class DiagnosisDICOMStudyInline(admin.TabularInline):
#     model = DiagnosisDICOMStudy
#     extra = 1
#     search_fields = ['dicom_study']
#     autocomplete_fields = ['dicom_study']

# class LesionDICOMStudyInline(admin.TabularInline):
#     model = LesionDICOMStudy
#     extra = 1
#     search_fields = ['dicom_study']
#     autocomplete_fields = ['dicom_study']    

# class LesionResponseDICOMStudyInline(admin.TabularInline):
#     model = LesionResponseDICOMStudy
#     extra = 1
#     search_fields = ['dicom_study']
#     autocomplete_fields = ['dicom_study']    

# class DiagnosisProjectInline(admin.TabularInline):
#     model = DiagnosisProject
#     extra = 1

# class RadiotherapyDICOMStudyInline(admin.TabularInline):
#     model = RadiotherapyDICOMStudy
#     extra = 1
#     search_fields = ['dicom_study']
#     autocomplete_fields = ['dicom_study']    

# class SurgeryDICOMStudyInline(admin.TabularInline):
#     model = SurgeryDICOMStudy
#     extra = 1
#     search_fields = ['dicom_study']
#     autocomplete_fields = ['dicom_study']    

# class SystemicTherapyDICOMStudyInline(admin.TabularInline):
#     model = SystemicTherapyDICOMStudy
#     extra = 1
#     search_fields = ['dicom_study']
#     autocomplete_fields = ['dicom_study']    


# class OutcomeDICOMStudyInline(admin.TabularInline):
#     model = OutcomeDICOMStudy
#     extra = 1
#     search_fields = ['dicom_study']
#     autocomplete_fields = ['dicom_study']    

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
       

@admin.register(LookupUniProt)
class LookupUniProtAdmin(admin.ModelAdmin):
    search_fields = ['protein_name']
    readonly_fields = ['code','gene_name','protein_name','all_gene_names','uniport_id']


@admin.register(LookupCosmic)
class LookupCosmicAdmin(admin.ModelAdmin):
    search_fields = ['gene_name']
    readonly_fields = ['code','gene_name','gene_description','gene_aliases']

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
    )
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

@admin.register(Patient)
class PatientAdmin (ImportExportModelAdmin):
    #inlines = [PatientProjectInline]
    list_filter = ['gender','chavi_consent','created_at']
    search_fields =[ 'patient_id']
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
    readonly_fields = ('center',)

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

## Create the Diagnosis Form Class
class DiagnosisResource(resources.ModelResource):
    class Meta:
        model = Diagnosis


@admin.register(Diagnosis)
class DiagnosisAdmin (ImportExportModelAdmin):
    search_fields = ['patient']
    autocomplete_fields = ['patient','diagnosis','cancer_site']
    filter_horizontal = ['diagnosis_dicom_study','diagnosis_project']
    list_filter = ['diagnosis__label','diagnostic_modality','cancer_site__label','cancer_side__label']
    list_fields = ['patient','diagnosis','diagnosis_date','diagnostic_modality','presentation_type','cancer_site__label','cancer_side__label']
    fieldsets = (
        ('Diagnosis',{
            'fields': ['patient','diagnosis',('diagnosis_date','diagnostic_modality')]
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
    class Meta:
        model = Pathology

@admin.register(Pathology)
class PathologyAdmin (ImportExportModelAdmin):
    inlines = [ImmunohistochemistryInline,CytogeneticsInline,SomaticGenomicAlterationsInline]
    autocomplete_fields = ['diagnosis','tumor_site']
    search_fields = ['diagnosis__patient_id']
    list_filter = ['date_pathology','tumor_side__label']
    list_display = ['diagnosis__patient_id','diagnosis','date_pathology','tumor_site__label','tumor_side__label','histological_type','lymph_nodes_in_specimen']
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
    resource_classes = [PathologyResource]

@admin.register(LookupStageDescriptor)
class LookupStageDescriptorAdmin(admin.ModelAdmin):
    search_fields = ['description']
    readonly_fields = ['key','description']

## Create the Stage Information Form Class
@admin.register(StageInformation)
class StageInformationAdmin (admin.ModelAdmin):
    search = ['diagnosis__patient_id']
    autocomplete_fields = ['diagnosis','overall_stage']
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
    autocomplete_fields = ['patient','comorbidity_type']
    list_display = ['patient','comorbidity_type','created_at']
    list_filter = ['comorbidity_type__label','created_at']


## Create the Lesion Form Class
@admin.register(Lesion)
class LesionAdmin (admin.ModelAdmin):
    search_fields = ['diagnosis','lesion_site','lesion_type']
    autocomplete_fields = ['diagnosis','lesion_site']
    filter_horizontal = ['lesion_dicom_study']
    fieldsets = (
        ('Lesion', {
            'fields' : [('diagnosis','date_lesion_assessed'),('lesion_site','lesion_laterality')]
        }),
        ('Dimensions', {
            'fields' : [('lesion_size_x_axis', 'lesion_size_y_axis', 'lesion_size_z_axis','lesion_size_unit'), ('lesion_volume','lesion_volume_unit')]

        }),
        ('DICOM Studies', {
            'fields' : ['lesion_dicom_study']
        })
    )   


## Create the Lesion Response Form Class
@admin.register(LesionResponse)
class LesionResponseAdmin (admin.ModelAdmin):
    autocomplete_fields = ['lesion']
    filter_horizontal = ['lesion_response_dicom_study']

## Create the Radiotherapy Form Class

@admin.register(Radiotherapy)
class RadiotherapyAdmin (admin.ModelAdmin):
    inlines=[RadiotherapyVolumeInline,RadiotherapyDoseVolumeDataInline]
    autocomplete_fields = ['diagnosis','radiotherapy_site']
    filter_horizontal = ['radiotherapy_dicom_study']
    fieldsets = (
        ('Radiotherapy',{
            'fields': ['diagnosis',('radiotherapy_start_date','radiotherapy_end_date'),('radiotherapy_site','radiotherapy_side')]
        }),
        ('Description',{
            'fields': [('radiotherapy_modality','radiotherapy_type','radiotherapy_machine'),('total_dose','radiation_dose_units'),('total_fractions','fractions_per_day')]
        }),
        ('DICOM Studies',{
            'fields': ['radiotherapy_dicom_study']
        }),
    )
 

## Create the Surgery Form Class
@admin.register(Surgery)
class SurgeryAdmin (admin.ModelAdmin):
    autocomplete_fields = ['diagnosis','surgery_site']
    filter_horizontal = ['surgery_dicom_study']
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
        ('DICOM Studies',{
            'fields': ['surgery_dicom_study']
        }),        
    )

@admin.register(LookupSystemicAgent)
class LookupSystemicAgentAdmin (admin.ModelAdmin):
    search_fields = ['systemic_agent_name']
    readonly_fields = ['code','systemic_agent_name']

## Create the Systemic Therapy Form Class
@admin.register(SystemicTherapy)
class SystemicTherapyAdmin (admin.ModelAdmin):
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

## Create the ConcomitantMedications Form Class
@admin.register(ConcomitantMedications)
class ConcomitantMedicationsAdmin (admin.ModelAdmin):
    autocomplete_fields = ['diagnosis']
    fieldsets = (
        ('Concomitant Medications',{
            'fields':['diagnosis',('medication_name','medication_route'),('medication_dose','medication_dose_units'),('date_medication_start_date', 'date_medication_end_date')]
        }),
    )


## Create the Other Treatment Form Class
@admin.register(OtherTreatment)
class OtherTreatmentAdmin (admin.ModelAdmin):
    autocomplete_fields = ['diagnosis']
    fieldsets = (
        ('Description',{
            'fields':['diagnosis',('treatment_start_date','treatment_end_date'),'treatment']
        }),
    )

@admin.register(LookupCTCAEGrade)
class LookupCTCAEGradeAdmin (admin.ModelAdmin):
    search_fields = ['ctcae_term','ctcae_grade']
    readonly_fields = ['code','ctcae_term','ctcae_grade','meddra_code','description']

## Create the Adverse Effects form class
@admin.register(AdverseEffects)
class AdverseEffectsAdmin (admin.ModelAdmin):
    autocomplete_fields = ['diagnosis','ctcae_grade_lookup']
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
    autocomplete_fields = ['patient']
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
