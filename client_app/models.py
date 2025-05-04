from django.db import models
from django.db.models.functions import Substr, Concat
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
import uuid
from decimal import Decimal
from django.forms import ValidationError
from lookup.models import *
from dateutil.relativedelta import relativedelta

# Center Model configuration - singleton model using Solo
# Validators
percentage_validator = [
    MinValueValidator(Decimal('0.0')), 
    MaxValueValidator(Decimal('100.0'))
]
positive_decimal_validator = [
    MinValueValidator(Decimal('0.0'))
]
allred_score_validator = [
    MinValueValidator('0'), 
    MaxValueValidator('8')
]

# Validate date so that start date comes before or on end date
class DateValidationMixin:
    """
    Mixin to validate that start dates come before or on end dates.
    Models using this mixin should specify date_validation_pairs as a list of tuples,
    where each tuple contains (start_date_field, end_date_field).
    """
    
    def clean(self):
        super().clean()
        
        # Get date validation pairs from the model, default to empty list if not specified
        date_pairs = getattr(self, 'date_validation_pairs', [])
        
        for start_field, end_field in date_pairs:
            start_date = getattr(self, start_field)
            end_date = getattr(self, end_field)
            
            if start_date and end_date and end_date < start_date:
                raise ValidationError({
                    end_field: f'{end_field.replace("_", " ").title()} cannot be before {start_field.replace("_", " ").title()}.'
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# Site Configuration Model
class SiteConfiguration(models.Model):
    '''This form allows the user to add infomration regarding the site at which the client is installed. The center code will be provided by the CHAVI team for the site.'''
    chavi_center_id = models.CharField(max_length=255,help_text="Site ID. This will be provided to you at the time of installation.",primary_key=True)
    center_name = models.CharField(max_length=255, help_text="Your Hospital")

    def save(self, *args, **kwargs):
        if self.__class__.objects.count():
            self.pk = self.__class__.objects.first().pk
        super().save(*args, **kwargs)

    def __str__(self):
        return self.center_name
    class Meta:
        verbose_name = "Site Configuration"



# Project Model

# This function is used to get the default site configuration.
def get_default_site():
    return SiteConfiguration.objects.first()

# Define choices for units of measurement.


class Project(models.Model):
    ''' This is a table which will contain the details of the Projects in which the data will be collected. Projects have a unique ID which is generated at the CHAVI server. However your institutional IRB approvals may be different for the projects. '''
    chavi_project_id = models.CharField(max_length=255,unique=True, primary_key=True,help_text="A unique identifier for the project.")
    project_name = models.CharField(max_length=600,help_text="The name of the project.")
    center = models.ForeignKey(SiteConfiguration, on_delete=models.CASCADE,  null=True, blank=True,default=get_default_site, related_name="project_center")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.project_name

    class Meta:
        verbose_name_plural = "Projects"
        db_table="project"

# Core Patient Models
class Patient(DateValidationMixin, models.Model):
    ''' This is the main patient model. Only patient ID and gender data are collected in this table.'''
    center = models.ForeignKey(SiteConfiguration, 
    on_delete=models.CASCADE, 
    default=get_default_site,
    related_name="center")
    chavi_consent = models.BooleanField(
        null=True,
        blank=True,
        default=False,
        help_text="Indicates whether the patient has provided consent for their data to be used in the CHAVI project. This field is required and must be set to True for the patient's data to be included in the project."
    )
    date_chavi_consent = models.DateField(
        null=True,
        blank=True,
        help_text="The date when the patient provided consent for their data to be used in the CHAVI project. This field is required if chavi_consent is True." 
    )
    patient_id = models.CharField(
        max_length=255, 
        primary_key=True,
        help_text="This should be your institution's medical record number or another consistent identifier used by your center."
    )
    class Gender(models.TextChoices):
        Male = 'Male',
        Female = 'Female',
        Transgender = 'Transgender',
        Non_Binary = 'Non-Binary'

    gender = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        choices=Gender.choices,
        default=Gender.Female,
        help_text="The patient's gender"
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text="The patient's date of birth in DD/MM/YYYY format."
    )
    date_of_registration = models.DateField(
        null=True,
        blank=True,
        help_text="Date of registration in hospital."
    )
    patient_project = models.ManyToManyField(
        'Project',
        blank = True, 
        related_name="patient_project",
        help_text="The project(s) that the patient is enrolled in."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The date and time when this patient record was first created in the system. This field is automatically set and cannot be modified."
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="The date and time when this patient record was last updated. This field is automatically updated whenever any information in the record is modified."
    )
    date_validation_pairs = [
        ('date_of_birth', 'date_of_registration')
    ]

    def __str__(self):
        return self.patient_id

    class Meta:
        verbose_name_plural = "Patients"
        db_table="patient"

# File upload Model
class PatientDicomFile(models.Model):
    ''' This is a model for storing DICOM files for a patient. Uploading of the zip files is supported. A single zip file containing multiple DICOM studies is allowed.'''
    patient = models.ForeignKey(
        'Patient',
        on_delete=models.CASCADE,
        related_name='patient_dicom_files',
    )
    file = models.FileField(
        upload_to='dicom_files',
        validators=[FileExtensionValidator(allowed_extensions=["zip"])],
        help_text="Please upload a single zip file having the DICOM studies for a single patients. You can choose to upload multiple studies at the same time."
    ) 
    processed = models.BooleanField(
        default=False,
        help_text="Indicates whether the DICOM file has been processed."
    )
    processing_log = models.TextField(
        null=True,
        blank=True,
        help_text="Log of the processing of the DICOM file."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class StudyTypeChoices(models.TextChoices):
    ''' This is a choice field for the type of study. '''
    PRETREATMENT_DIAGNOSTIC_IMAGE = 'PRETREATMENT_DIAGNOSTIC_IMAGE', 'Pre-treatment Diagnostic Image'
    PLANNING_IMAGE = 'PLANNING_IMAGE', 'Planning Image'
    ON_TREATMENT_VERIFICATION_IMAGE = 'ON_TREATMENT_VERIFICATION_IMAGE', 'On-treatment Verification Image'
    PLANNING_IMAGE_FOR_ADAPTIVE_TREATMENT = 'PLANNING_IMAGE_FOR_ADAPTIVE_TREATMENT', 'Planning Image for Adaptive Treatment'
    POSTTREATMENT_THERAPY_RESPONSE_IMAGE = 'POSTTREATMENT_THERAPY_RESPONSE_IMAGE', 'Post-treatment Therapy Response Image'  
    THERAPY_DELIVERY_IMAGE = 'THERAPY_DELIVERY_IMAGE', 'Therapy Delivery Image' 
    THERAPY_QA_IMAGE = 'THERAPY_QA_IMAGE', 'Therapy QA Image'
    POSTTREATMENT_DIAGNOSTIC_IMAGE = 'POSTTREATMENT_DIAGNOSTIC_IMAGE', 'Post-treatment Diagnostic Image'
    OTHER = 'OTHER', 'Other'


# DICOM Related Models
class DICOMStudy(models.Model):
    ''' This is a table that stores information on the different DICOM studies that the patient has undergone. '''
    patient = models.ForeignKey(
        Patient, 
        on_delete=models.CASCADE,
        related_name='patient',
        help_text="Reference to the patient that this imaging study belongs to. When a patient record is deleted, all associated imaging studies will also be deleted."
    )
    study_instance_uid= models.CharField(
        max_length=255,
        unique = True,
        primary_key=True,
        help_text="A unique identifier for this specific imaging study. This is like a serial number - no two imaging studies anywhere should have the same Study Instance UID. This helps prevent any confusion between different studies."
    )
    study_date = models.DateField(
        null = True,
        blank = True,
        help_text="The date when this imaging study was performed. This is recorded as DD/MM/YYYY format (for example: 2023-12-25)."
    )
    study_description = models.CharField(
        max_length = 255,
        null = True,
        blank = True, 
        help_text = "Description of the study Provided in the DICOM Data"
    )
    study_type = models.CharField(
        max_length = 255,
        choices = StudyTypeChoices.choices,
        null = True,
        blank = True,
        help_text = "The type of study. This is a choice field that can be selected from the list of study types."
    )
    study_modalities = models.CharField(
        max_length = 255,
        null = True,
        blank = True,
        help_text = "The modalities inside the the study. "
    )
    series_descriptions = models.TextField(
        null = True,
        blank = True,
        help_text = "Description of the series in the study. This is a text field that can store multiple series descriptions, separated by commas."
    )
    folder_path = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f'{self.patient.patient_id} {self.study_date} \n'
            f'Study: {self.study_description} \n'
            f'Series: {self.series_descriptions}'
        )
        
        #f"{self.patient.patient_id} {self.study_description} {self.series_descriptions} (Date: {self.study_date})"

    class Meta:
        verbose_name_plural = "DICOM Studies"


# Clinical Data Models
class Diagnosis(models.Model):
    ''' This is a table which stores the diagnosis of the patient. The diagnosis is a key table which will have links to treatment and pathology.'''
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE,
    help_text="Select the patient")
    chavi_diagnosis_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cancer_system = models.ForeignKey('lookup.LookupMajorCancerCategory', on_delete=models.PROTECT,related_name='diagnosis_major_cancer_category',
                                              help_text="Select the major cancer category")
    diagnosis = models.ForeignKey('lookup.LookupICDCode',related_name= 'diagnosis_code', on_delete=models.PROTECT,
    help_text="Select the diagbnosis ICD code. If the patient has multiple diagnoses then you can add another instance of the form.")
    diagnosis_date = models.DateField(null=True, blank=True,
    help_text="Select the data at which the diagnosis was made. This can be a date when the patient came to the hospital for the first time or when a pathological proof was obtained")
    presentation_type = models.ForeignKey('lookup.LookupPresentation', on_delete=models.PROTECT,
    help_text="Select the type of presentation. This can be a new presentation or a recurrence or a metastasis.")
    cancer_site = models.ForeignKey('lookup.LookupFMACode', on_delete=models.PROTECT,
    help_text="Select the cancer site. This can be a site where the cancer was first diagnosed or a site where the cancer was recurred or metastasized.")
    cancer_side = models.ForeignKey('lookup.LookupLaterality', on_delete=models.PROTECT,
    help_text="Select the side at which the cancer was present.")
    diagnostic_modality = models.ForeignKey('lookup.LookupDiagnosticModality',on_delete=models.PROTECT,null=True, blank=True,
    help_text="If the cancer was diagnosed with a method like cytology, biopsy etc then the modality can be entered here. Please ensure that the modality is spelled correctly.")
    study_instance_uid = models.ManyToManyField('DICOMStudy', blank = True, help_text="Select the DICOM studies that were used to diagnose the cancer. You can select multiple studies.")
    diagnosis_project = models.ManyToManyField('Project', blank = True, help_text="Select the project that was used to diagnose the cancer. You can select multiple projects.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient.patient_id} - {self.cancer_system} - {self.presentation_type}"

    class Meta:
        verbose_name_plural="Diagnoses"
        db_table = 'diagnosis'    

class Outcome(models.Model):
    '''This table stores information related to the outcome of the cancer treatment for the disease. Note that the patient outcome table is separate.'''
    chavi_outcome_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE)
    date_outcome_assessed = models.DateField(null=True, blank=True,
    help_text = "Date this Outcome was assessed or documented or confirmed.")
    outcome_type = models.ForeignKey('lookup.LookupOutcomeType', on_delete=models.PROTECT,
    help_text = "Select the Type of Outcome. If you wish to add another outcome then please create another instance of the form.")
    study_instance_uid = models.ManyToManyField('DICOMStudy',blank = True, related_name = "outcome_dicom_study",help_text = "Select all DICOM Studies for this Disease Outcome")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.diagnosis.patient.patient_id} - {self.date_outcome_assessed}"
    
    class Meta:
        verbose_name = "Cancer Outcome"
        verbose_name_plural="Cancer Outcomes"
        db_table = 'outcome'

class ModalityChoices(models.TextChoices):
    ''' This is a lookup table for the lesion detection modality.'''
    CT = "CT", 'CT'
    MRI = "MRI", 'MRI'
    PET = "PET", 'PET'
    US = "US", 'US'
    MR_PET = "MR_PET", 'MR_PET'
    CT_PET = "CT_PET", 'CT_PET'
    BONE_SCAN = "Bone Scan", 'Bone Scan'
    FDG_PET = "FDG_PET", 'FDG_PET'
    PSMA_PET = "PSMA_PET", 'PSMA_PET'
    CLINICAL = "Clinical", 'Clinical'
    XRAY = "X-ray", 'X-ray'
    OTHER = "Other", 'Other'

class Lesion(models.Model):
    ''' This table has information on the lesions / tumors that the patient has. Allows users to record information on the gross disease, nodal disease or distant metastases.'''
    chavi_lesion_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this lesion is associated with"
    )
    date_lesion_assessed = models.DateField(
        null=True, 
        blank=True,
        help_text="The date when this lesion was first identified or assessed by a medical professional"
    )
    lesion_site = models.ForeignKey(
        'lookup.LookupFMACode', 
        on_delete=models.PROTECT,
        help_text="The anatomical location where the lesion is found (e.g., 'Left Breast', 'Right Lung')"
    )
    lesion_type = models.ForeignKey(
        'lookup.LookupLesionType', 
        on_delete=models.PROTECT,
        help_text="The type or category of the lesion (e.g., 'Primary Tumor', 'Metastatic Lesion')"
    )
    lesion_laterality = models.ForeignKey(
        'lookup.LookupLaterality', 
        on_delete=models.PROTECT,
        help_text="Indicates which side of the body the lesion is on (e.g., 'Left', 'Right', 'Bilateral')"
    )
    lesion_size_x_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The width (x-axis measurement) of the lesion in the specified unit of measurement"
    )
    lesion_size_y_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The length (y-axis measurement) of the lesion in the specified unit of measurement"
    )
    lesion_size_z_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The depth (z-axis measurement) of the lesion in the specified unit of measurement"
    )
    lesion_size_unit = models.ForeignKey(
        'lookup.LookupSizeUnits', 
        related_name='lesion_size_unit',
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        help_text="The unit of measurement used for the lesion dimensions (e.g., 'millimeters', 'centimeters')"
    )
    lesion_volume = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The total volume of the lesion, calculated from the three-dimensional measurements"
    )
    lesion_volume_unit = models.ForeignKey(
        'lookup.LookupVolumeUnits', 
        related_name='lesion_volume_unit',
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        help_text="The unit of measurement used for the lesion volume (e.g., 'cubic millimeters', 'cubic centimeters')"
    )
    lesion_detection_modality = models.CharField(
        max_length=255,
        choices=ModalityChoices.choices,
        null=True,
        blank=True,
        help_text="The modality used to detect the lesion"
    )
    lesion_suv_max = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The maximum SUV value of the lesion"
    )
    study_instance_uid = models.ManyToManyField('DICOMStudy', blank = True, related_name = 'lesion_dicom_study',help_text = "Select all the DICOM Studies associated with this Lesion")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lesion {self.chavi_lesion_id}"

    class Meta:
        verbose_name_plural = "Lesions"
        db_table="lesion"

class LesionResponse(models.Model):
    ''' This table will store information related to the response that the Lesion has.'''

    chavi_lesion_response_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesion = models.ForeignKey(
        Lesion, 
        on_delete=models.CASCADE,
        help_text="The specific lesion (abnormal tissue) that is being monitored for response to treatment"
    )
    lesion_response_date = models.DateField(
        null=True, 
        blank=True,
        help_text="The date when the lesion's response to treatment was evaluated"
    )
    lesion_response = models.ForeignKey(
        'lookup.LookupResponseType', 
        on_delete=models.CASCADE,
        help_text="How the lesion has responded to treatment (e.g., complete response, partial response, stable disease, etc.)"
    )
    residual_lesion_size_x_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The width (left to right measurement) of any remaining lesion after treatment"
    )
    residual_lesion_size_y_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The length (front to back measurement) of any remaining lesion after treatment"
    )
    residual_lesion_size_z_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The height (top to bottom measurement) of any remaining lesion after treatment"
    )
    residual_lesion_size_unit = models.ForeignKey(
        'lookup.LookupSizeUnits',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="The unit of measurement used for the residual lesion size (e.g., 'millimeters', 'centimeters')"
    )
    residual_lesion_volume = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The total volume (size in three dimensions) of any remaining lesion after treatment"
    )
    residual_lesion_volume_unit = models.ForeignKey(
        'lookup.LookupVolumeUnits',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="The unit of measurement used for the residual lesion volume (e.g., 'millimeters', 'centimeters')"
    )

    lesion_response_suv_max = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
    )
    lesion_response_modality = models.CharField(
        max_length=255,
        choices=ModalityChoices.choices,
        null=True,
        blank=True,
        help_text="The modality used to detect the lesion response"
    )
    study_instance_uid = models.ManyToManyField(
        'DICOMStudy', blank = True, 
        related_name = 'lesion_response_dicom_study', 
        help_text="The DICOM study associated with the lesion response"
    )    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lesion Response {self.chavi_lesion_response_id}"

    class Meta:
        verbose_name_plural="Lesion Responses"
        db_table="lesion_response"

class Symptom(models.Model):
    ''' This table will store information on the symptoms for the patient.'''
    chavi_symptom_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    symptom = models.ForeignKey('lookup.LookupSymptoms', on_delete=models.PROTECT)
    date_onset = models.DateField(null=True, blank=True, help_text="The date when the symptom first appeared")
    date_symptom_assessment = models.DateField(null=True, blank=True, help_text="The date when the symptom was first assessed")
    duration_of_symptom = models.PositiveIntegerField(null=True, blank=True, help_text="The duration of the symptom in months")
    date_resolution = models.DateField(null=True, blank=True, help_text="The date when the symptom resolved")
    severity = models.ForeignKey('lookup.LookupSeverity', on_delete=models.PROTECT, null=True, blank=True, help_text="The severity of the symptom")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Calculate diagnosis date if we have both assessment date and duration
        if self.date_symptom_assessment and self.duration_of_symptom:
            # Subtract months from assessment date to get diagnosis date
            self.date_onset = self.date_symptom_assessment - relativedelta(months=self.duration_of_symptom)
        super().save(*args, **kwargs)
    def __str__(self):
        return f"{self.chavi_symptom_id}"
    
    class Meta:
        verbose_name_plural = "Symptoms"
        db_table = "symptom"

class GermlineGenomicAlterations(models.Model):
    ''' This table will store information on the germline genomic alterations for the patient.'''
    chavi_germline_genomic_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    date_test = models.DateField(null=True, blank=True)
    cosmic_gene_name = models.ForeignKey('lookup.LookupGene', on_delete=models.PROTECT)
    reference_sequence = models.CharField(max_length=255, null=True, blank=True)
    protein_modification = models.CharField(max_length=255, null=True, blank=True)
    variant_type = models.CharField(max_length=255, null=True, blank=True)
    allele_frequency = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    read_depth = models.IntegerField(null=True, blank=True)
    clinical_significance = models.ForeignKey('lookup.LookupClinicalSignificance', on_delete=models.PROTECT, related_name='germline_genomic_clinical_significance',null = True, blank = True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.chavi_germline_genomic_id}"
    
    class Meta:
        verbose_name_plural = "Germline Genomic Alterations"
        db_table = "germline_genomic_alterations"

class TumorFocalityChoices(models.TextChoices):
    ''' This is a lookup table for the tumor focality.'''
    Unifocal = "Unifocal"
    Multifocal = "Multifocal"
    Multicenter = "Multicenter"
    Unknown = "Unknown"
    NotApplicable = "Not Applicable"

class SpecimenTypeChoices(models.TextChoices):
    ''' This is a lookup table for the specimen type.'''
    CORE_BIOPSY = "Core Biopsy", 'Core Biopsy'
    EXCISION_BIOPSY = "Excision Biopsy", 'Excision Biopsy'
    INCISIONAL_BIOPSY = "Incisional Biopsy", 'Incisional Biopsy'
    SURGICAL_RESECTION = "Surgical Resection", 'Surgical Resection'
    FINE_NEEDLE_ASPIRATION = "Fine Needle Aspiration", 'Fine Needle Aspiration'
    LIQUID_BIOPSY = "Liquid Biopsy", 'Liquid Biopsy'
    OTHER = "Other", 'Other'

class Pathology(models.Model):
    ''' This a table which stores the pathology information related to a diagnosis.'''

    chavi_pathology_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="The diagnosis associated with this pathology report"
    )
    date_pathology = models.DateField(
        null=True, 
        blank=True,
        help_text="The date when the pathology specimen was collected or the pathology report was issued"
    )
    specimen_type = models.CharField(
        max_length=500,
        choices=SpecimenTypeChoices.choices,
        null=True, 
        blank=True,
        help_text="The type of specimen collected (e.g., 'Core Biopsy', 'Surgical Resection', 'Fine Needle Aspiration')"
    )
    tumor_site = models.ForeignKey(
        'lookup.LookupFMACode', 
        related_name='pathology_tumor_site',
        on_delete=models.CASCADE,
        help_text="The anatomical location of the tumor as defined by the Foundational Model of Anatomy (FMA)"
    )
    tumor_side = models.ForeignKey(
        'lookup.LookupLaterality', 
        related_name='pathology_tumor_side',
        on_delete=models.CASCADE,
        help_text="The side of the body where the tumor is located (e.g., 'Left', 'Right', 'Bilateral')"
    )
    histological_type = models.ForeignKey( 
        'lookup.LookupPathology',
        related_name='pathology_histological_type',
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="The primary histological classification of the tumor (e.g., 'Adenocarcinoma', 'Squamous Cell Carcinoma')"
    )
    histological_grade = models.ForeignKey(
        'lookup.LookupGrade',
        related_name='pathology_histological_grade',
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="The degree of differentiation of the tumor cells (e.g., 'Grade 1', 'Grade 2', 'Grade 3')"
    )
    greatest_dimension_of_tumor = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The primary dimension of the tumor measured in centimeters"
    )
    additional_tumor_dimension_1 = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The second dimension of the tumor measured in centimeters"
    )
    additional_tumor_dimension_2 = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="The third dimension of the tumor measured in centimeters"
    )
    tumor_dimesion_unit = models.ForeignKey(
        'lookup.LookupSizeUnits',
        on_delete=models.PROTECT,
        related_name='pathology_tumor_dimesion_unit',
        null=True, 
        blank=True,
        help_text="The unit of measurement for the tumor dimension"
    )
    tumor_focality = models.CharField(
        max_length=100,
        null=True, 
        blank=True,
        choices=TumorFocalityChoices.choices,
        help_text="Whether the tumor is unifocal (single focus) or multifocal (multiple foci)"
    )
    lymphatic_vascular_invasion = models.ForeignKey(
        'lookup.LookupPathologyDescriptors',
        related_name='pathology_lymphatic_vascular_invasion',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Presence or absence of perineural invasion"
    )
    perineural_invasion = models.ForeignKey(
        'lookup.LookupPathologyDescriptors',
        related_name='pathology_perineural_invasion',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Presence or absence of perineural invasion"
    )
    dermal_lymphatic_vascular_invasion = models.ForeignKey(
        'lookup.LookupPathologyDescriptors',
        related_name='pathology_dermal_lymphatic_vascular_invasion',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Presence or absence of perineural invasion"
    )
    necrosis = models.ForeignKey(
        'lookup.LookupPathologyDescriptors',
        related_name='pathology_necrosis',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Presence or absence of necrosis"
    )
    necrosis_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        default=Decimal(0),
        validators=percentage_validator,
        blank=True,
        help_text="Percentage of necrosis in the specimen"
    )
    mitotic_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=positive_decimal_validator,
        help_text="Number of mitoses per 10 high power field or 2 square mm"
    )
    margin_status = models.ForeignKey(
        'lookup.LookupMarginStatus',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pathology_margin_status',
        help_text="Select the margin status of the specimen"
    )
    closest_margin_distance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=positive_decimal_validator,
        help_text="Distance to the closest margin of the specimen."
    )
    closest_margin_distance_unit = models.ForeignKey(
        'lookup.LookupSizeUnits',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pathology_closest_margin_distance_unit',
        help_text="Unit of measurement for the closest margin distance"
    )
    treatment_effect = models.ForeignKey(
        'lookup.LookupTreatmentEffect',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Select the treatment effect of the specimen",
        related_name='pathology_treatment_effect'
    )
    primary_gleason_grade = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Enter the primary Gleason grade of the specimen"
    )
    secondary_gleason_grade = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Enter the secondary Gleason grade of the specimen"
    )
    lymph_nodes_removed = models.BooleanField(
        null=True, 
        blank=True,
        help_text="Whether lymph nodes were removed in the specimen"
    )
    lymph_nodes_in_specimen = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Total number of lymph nodes found in the specimen"
    )
    lymph_node_extracapsular_extension = models.BooleanField(null=True, blank=True,help_text='Whether the lymph node had extracpsular extension')
    number_of_uninvolved_nodes = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes without any tumor involvement"
    )
    number_of_nodes_with_macrometastases = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes with visible tumor deposits"
    )
    number_of_nodes_with_micrometastases = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes with microscopic tumor deposits (0.2-2.0mm)"
    )
    number_of_nodes_with_isolated_tumor_cells = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes with isolated tumor cells (<0.2mm)"
    )
    number_of_nodes_with_extracapsular_extension = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes with extracapsular extension"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.diagnosis.patient.patient_id} - {self.histological_type}"

    class Meta:
        verbose_name_plural = "Pathology"
        db_table="pathology"    

class Immunohistochemistry(models.Model):
    ''' This is a table storing data on the Immunohistochemistry test results for the pathology.'''

    chavi_ihc_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pathology = models.ForeignKey(
        Pathology, 
        on_delete=models.CASCADE,
        help_text="Select the pathology report this immunohistochemistry test is associated with"
    )
    date_ihc = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the immunohistochemistry test was performed (format:DD/MM/YYYY)"
    )
    protein_name = models.ForeignKey(
        'lookup.LookupIHCAntibody', 
        on_delete=models.CASCADE,
        help_text="Select the antibody that was tested for in this immunohistochemistry test"
    )
    ihc_result = models.ForeignKey(
        'lookup.LookupIHCResult',
        on_delete=models.PROTECT,
        related_name='ihc_result',
        null=True, 
        blank=True,
        help_text="Select the result of the IHC staning Test overall"
    )
    percentage_positive_tumor_cells = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=percentage_validator,
        help_text="Enter the percentage of positive cells for IHC staining"
    )
    percentage_positive_immune_cells = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=percentage_validator,
        help_text="Enter the percentage of positive immune cells for IHC staining"
    )
    tumor_cell_staining_intensity = models.ForeignKey(
        'lookup.LookupIHCStainingIntensity',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Select the staining intensity of the cells for IHC staining"
    )
    allred_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Enter the Allred score for IHC staining"
    )
    cps_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of Tumor and Immune Cells with Staining per 100 Tumor Cells (CPS)")
    tps_score = models.DecimalField(
        null=True,
        max_digits=5,
        decimal_places=2,
        blank=True,
        validators=percentage_validator,
        help_text="Enter the TPS score for IHC staining in %")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.pathology.diagnosis.patient.patient_id} - {self.protein_name}"

    class Meta:
        verbose_name_plural="Immunohistochemistries"
        db_table="immunohistochemistry"

class Cytogenetics(models.Model):
    ''' This is a table which will store the cytogenetics test results for each pathology report.'''

    chavi_cytogenetics_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pathology = models.ForeignKey(
        Pathology, 
        on_delete=models.CASCADE,
        help_text="Select the pathology report this cytogenetics test is associated with"
    )
    date_cytogenetics = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the cytogenetics test was performed (format:DD/MM/YYYY)"
    )
    gene = models.ForeignKey(
        'lookup.LookupGene', 
        on_delete=models.PROTECT,
        help_text="Select the gene that was tested for in this cytogenetics test"
    )
    cytogenetic_abnormality = models.ForeignKey(
        'lookup.LookupCytogeneticAbnormality',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Select the cytogenetic abnormality if applicable"
    )
    cytogenetic_result = models.ForeignKey(
        'lookup.LookupIHCResult',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='cytogenetics_result',
        help_text="Select the result of the cytogenetics test"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.chavi_cytogenetics_id}"
    
    class Meta:
        verbose_name_plural="Cytogenetics"
        db_table="cytogenetics"

class SomaticGenomicAlterations(models.Model):  
    ''' This model represents somatic genomic alterations found in a pathology report.'''
    chavi_somatic_genomic_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pathology = models.ForeignKey(
        Pathology, 
        on_delete=models.CASCADE,
        help_text="Select the pathology report this genomic alteration is associated with"
    )
    date_test = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the genomic testing was performed (format:DD/MM/YYYY)"
    )
    cosmic_gene_name = models.ForeignKey(
        'lookup.LookupGene', 
        on_delete=models.PROTECT,
        help_text="Select the gene where the alteration was found, using COSMIC database nomenclature"
    )
    reference_sequence = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Enter the reference sequence identifier (e.g., 'NM_007294.3' for BRCA1)"
    )
    protein_modification = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Describe the protein-level change using standard nomenclature (e.g., 'p.Val600Glu' for BRAF V600E mutation)"
    )
    variant_type = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Specify the type of variant (e.g., 'Missense', 'Frameshift', 'Deletion', 'Insertion')"
    )
    allele_frequency = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the variant allele frequency as a decimal (e.g., 0.45 for 45%)"
    )
    read_depth = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Enter the sequencing read depth at this position (e.g., 500)"
    )
    clinical_significance = models.ForeignKey(
        'lookup.LookupClinicalSignificance',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="clinical_significance",
        help_text="Select the clinical significance of the variant"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.chavi_somatic_genomic_id}"
    
    class Meta:
        verbose_name_plural="Somatic Genomic Alterations"
        db_table="somatic_genomic_alterations"

class GeneExpressionData(models.Model):
    ''' This model represents gene expression data for a pathology report.'''
    chavi_gene_expression_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pathology = models.ForeignKey(
        Pathology, 
        on_delete=models.CASCADE,
        help_text="Select the pathology report this gene expression data is associated with"
    )
    date_test = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the gene expression test was performed (format:DD/MM/YYYY)"
    )
    gene = models.ForeignKey(
        'lookup.LookupGene', 
        on_delete=models.PROTECT,
        help_text="Select the gene that was tested for in this gene expression data"
    )
    expression_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the expression value of the gene"
    )
    expression_units = models.ForeignKey(
        'lookup.LookupExpressionUnits',
        on_delete=models.PROTECT,
        help_text="Select the units of expression"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.gene.code} - {self.expression_value}"   
    
    class Meta:
        verbose_name_plural="Gene Expression Data"
        db_table="gene_expression_data"
    
class EpigeneticData(models.Model):
    ''' This model represents epigenetic data for a pathology report.'''
    chavi_epigenetic_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pathology = models.ForeignKey(
        Pathology, 
        on_delete=models.CASCADE,
        help_text="Select the pathology report this epigenetic data is associated with"
    )
    date_test = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the epigenetic test was performed (format:DD/MM/YYYY)"
    )
    gene = models.ForeignKey(
        'lookup.LookupGene', 
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Select the gene that was tested for in this epigenetic data"
    )
    epigenetic_abnormality_type = models.ForeignKey(
        'lookup.LookupEpigeneticAbnormalityType',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Select the type of epigenetic abnormality if applicable"
    )
    epigenetic_result = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Enter the result of the epigenetic test"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.gene.code} - {self.epigenetic_result}"
    
    class Meta:
        verbose_name_plural="Epigenetic Data"
        db_table="epigenetic_data"
    
class OtherTreatment(DateValidationMixin, models.Model):
    ''' The table will store information on other treatments that the patient undergoes'''
    chavi_treatment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    treatment_intent = models.ForeignKey(
        'lookup.LookupTreatmentIntent',
        on_delete=models.PROTECT,
        related_name = 'other_treatment_intent',
        null=True,
        blank=True,
        help_text="Select the treatment intent"
    )
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )
    treatment = models.CharField(
        max_length=255,
        help_text="Enter the name or description of the treatment"
    )
    treatment_start_date = models.DateField(
        null = True,
        blank = True,
        help_text = "Start date of Treatment"
    )
    treatment_end_date = models.DateField(
        null = True,
        blank = True,
        help_text = "End date of Treatment"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The timestamp when this treatment record was created (automatically set)"
    )
    updated_at = models.DateTimeField(auto_now=True)

    date_validation_pairs = [
        ('treatment_start_date', 'treatment_end_date')
    ]

    def __str__ (self):
        return f"{self.chavi_treatment_id}"
    class Meta:
        verbose_name = "Other Treatment"
        verbose_name_plural="Other Treatments"
        db_table="other_treatment"

class RadiationCourseTypeChoices(models.TextChoices):
    Primary = 'Primary'
    Boost = 'Boost'

class Radiotherapy(DateValidationMixin, models.Model):
    '''This table will record the radiotherapy course details for the patient's diagnosis.'''
    chavi_radiotherapy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )
    radiotherapy_course_type = models.CharField(
        max_length=255, 
        choices=RadiationCourseTypeChoices.choices, 
        help_text="Select the type of radiotherapy course"
    )    
    radiotherapy_modality = models.ForeignKey(
        'lookup.LookupRadiotherapyModality',
        on_delete=models.PROTECT,
        help_text="Select the modality of the radiotherapy",
        null=True,
        blank=True,
        related_name="radiotherapy_modality"
    )
    reirradiation = models.BooleanField(
        null=True,
        blank=True,
        help_text="Indicate if this is a reirradiation course"
    )
    total_dose = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the total radiation dose delivered during the entire course of treatment (in Gray or specified units)"
    )
    total_fractions = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Enter the total number of fractions delivered for the complete course of radiotherapy"
    )
    simultaneous_integrated_boost = models.BooleanField(
        null=True,
        blank=True,
        help_text="Indicate if this course of treatment had a simultaneous integrated boost"
    )
    simultaneous_integrated_boost_dose = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the dose of the simultaneous integrated boost"
    )
    radiation_dose_units = models.ForeignKey(
        'lookup.LookupDoseUnits',
        related_name= 'radiation_course_dose_units',
        on_delete = models.PROTECT,
        null=True, 
        blank=True,
        help_text="Select the units used to measure the radiation dose (e.g., 'Gy', 'cGy')"
    )
    radiotherapy_intent = models.ForeignKey(
        'lookup.LookupTreatmentIntent',
        related_name="radiotherapy_intent",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Select the intent of the radiotherapy treatment (e.g., 'Curative', 'Palliative')"
    )
    radiotherapy_type = models.ForeignKey(
        'lookup.LookupRadiotherapyType',
        related_name="radiotherapy_type",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Select the type of radiotherapy treatment"
    )
    radiotherapy_technique = models.ForeignKey(
        'lookup.LookupRadiotherapyTechnique',
        related_name="radiotherapy_technique",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Select the technique used to deliver the radiation"
    )
    fractions_per_day = models.PositiveIntegerField(
        null=True, 
        blank=True,
        default = 1,
        help_text="Enter the number of treatment sessions (fractions) delivered per day"
    )
    radiotherapy_side = models.ForeignKey(
        'lookup.LookupLaterality', 
        on_delete=models.PROTECT,
        help_text="Select which side of the body is being treated (e.g., 'Left', 'Right', 'Bilateral')"
    )
    radiotherapy_machine = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Enter the name or model of the radiation therapy machine used"
    )
    radiotherapy_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the treatment was started (format:DD/MM/YYYY)"
    )
    radiotherapy_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the treatment was completed (format:DD/MM/YYYY)"
    )
    study_instance_uid = models.ManyToManyField(
        'DICOMStudy',blank = True, 
        related_name = 'radiotherapy_dicom_studies',
        help_text="Select the DICOM studies associated with this radiotherapy course"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    date_validation_pairs = [
        ('radiotherapy_start_date', 'radiotherapy_end_date')
    ]

    def __str__ (self):
        return f"{self.diagnosis} RT Course: {self.radiotherapy_course_type}-{self.radiotherapy_side}"
    class Meta:
        verbose_name = "Radiotherapy Course"
        verbose_name_plural="Radiotherapy Courses"
        db_table="radiotherapy"

class RadiotherapyVolume(DateValidationMixin, models.Model):
    ''' This table will record the volumes treated as a part of the radiotherapy course.'''
    radiotherapy_volume_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for this radiotherapy dose volume data"
    )
    radiotherapy = models.ForeignKey(
        'Radiotherapy',
        on_delete=models.CASCADE,
        help_text="Select the radiotherapy course that this volume is associated with"
    )
    volume_name = models.CharField(
        max_length=255,
        null=True,
        blank= True,        
        help_text="Enter a name or description for this volume"
    )
    volume_type = models.ForeignKey(
        'lookup.LookupRadiotherapyVolumeType',
        null=True,
        blank= True,        
        on_delete = models.PROTECT,
        help_text="Select the type of volume (e.g., PTV, CTV, OAR)"
    )

    volume_dose_prescribed = models.DecimalField(
        max_digits=10, 
        decimal_places=2,           
        null=True,
        blank= True,
        validators=positive_decimal_validator,
        help_text="Enter the prescribed dose for this volume in Gray (Gy)",
    )
    radiation_dose_units = models.ForeignKey(
        'lookup.LookupDoseUnits',
        on_delete = models.PROTECT,
        related_name= 'radiotherapy_volume_dose_units',
        null=True, 
        blank=True,
        help_text="Select the units used to measure the radiation dose (e.g., 'Gy', 'cGy')"
    )    
    volume_fractions = models.PositiveIntegerField(      
        null=True,
        blank=True,
        help_text="Enter the number of fractions for this volume"
    )
    volume_radiotherapy_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Enter the start date for this volume (format:DD/MM/YYYY)"
    )
    volume_radiotherapy_end_date = models.DateField(    
        null=True,
        blank=True,
        help_text="Enter the end date for this volume (format:DD/MM/YYYY)"     
    )
    anatomical_locations = models.ManyToManyField(
        'lookup.LookupRTLocation',
        blank=True,
        help_text="Select the anatomical locations included in this volume if applicable"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    date_validation_pairs = [
        ('volume_radiotherapy_start_date', 'volume_radiotherapy_end_date')
    ]

    def __str__(self):
        return f"{self.radiotherapy} - {self.volume_name}"

    class Meta:
        verbose_name_plural = "Radiotherapy Volumes"
        db_table = "radiotherapy_volume"    

class RadiotherapyDoseVolumeData(models.Model):
    ''' This is a table which stores the radiotherapy dose volume data for the patients'''
    radiotherapy_dose_volume_data_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for this radiotherapy dose volume data"
    )
    radiotherapy = models.ForeignKey(
        Radiotherapy,
        on_delete=models.CASCADE,
        help_text="Select the radiotherapy session that this dose volume data is associated with"
    )
    volume_name = models.CharField(
        max_length=255,
        help_text="Enter a name for this dose volume data"
    )
    volume_type = models.ForeignKey(
        'lookup.LookupRadiotherapyVolumeType',
        on_delete=models.PROTECT,
        help_text="Select the type of volume (e.g., 'CTV', 'PTV')"
    )
    absolute_volume = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the absolute volume in cubic centimeters (cc)"
    )
    relative_volume = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,      
        blank=True,  
        validators=percentage_validator,   
        help_text="Enter the relative volume as a percentage (%). Enter a value between 0 and 100."
    )
    volume_units = models.ForeignKey(
        'lookup.LookupVolumeUnits',
        on_delete=models.PROTECT,
        null=True,
        related_name='volume_units',
        blank=True,
        help_text="Select the units for the volume (e.g., 'cc', '%')"
    )
    absolute_dose = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the absolute dose in Gray (Gy) or cGy"
    )
    relative_dose = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=percentage_validator,
        help_text="Enter the relative dose as a percentage (%). Enter a value between 0 and 100."
    )
    volume_dose_prescribed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the dose prescribed to this volume in Gray (Gy) or cGy"
    )
    radiation_dose_units = models.ForeignKey(
        'lookup.LookupDoseUnits',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name = "radiation_dose_units",
        help_text="Select the units for the dose (e.g., 'Gy', 'cGy', '%')"
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.radiotherapy}-{self.volume_name}"
    class Meta:
        verbose_name = "Radiotherapy Dose Volume"
        verbose_name_plural="Radiotherapy Dose Volumes"
        db_table="radiotherapy_dose_volumes"

class Surgery(models.Model):
    ''' This is a table of surgery type that the patient will undergo'''
    chavi_surgery_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )    
    surgery_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the surgery was performed (format:DD/MM/YYYY)"
    )
    surgery_side = models.ForeignKey(
        'lookup.LookupLaterality', 
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="Select which side of the body the surgery was performed on (e.g., 'Left', 'Right', 'Bilateral')"
    )
    surgery_type =  models.ManyToManyField(
        'lookup.LookupSurgicalProcedures',
        blank=True,
        help_text="Select the type of surgery performed (e.g., 'Mastectomy', 'Lumpectomy', 'Whole Breast Irradiation')"
    )
    surgery_intent = models.ForeignKey(
        'lookup.LookupTreatmentIntent',
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="Select the intent of the surgery (e.g., 'Curative', 'Palliative')"
    )
    nodal_assessment = models.BooleanField(
        null=True, 
        blank=True,
        help_text="Indicate whether nodal assessment was performed (check for Yes, leave unchecked for No)"
    )
    nodal_assessment_type = models.ForeignKey(
        'lookup.LookupNodalAssessmentType',
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="Select the type of nodal assessment performed (e.g., 'Sentinel Node Biopsy', 'Axillary Dissection')"
    )
    reconstruction = models.BooleanField(
        null=True, 
        blank=True,
        help_text="Indicate whether reconstructive surgery was performed (check for Yes, leave unchecked for No)"
    )
    type_reconstruction = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="If reconstruction was performed, specify the type (e.g., 'Implant-Based', 'Autologous Tissue', 'DIEP Flap')"
    )
    study_instance_uid = models.ManyToManyField(
        'DICOMStudy',blank = True, 
        related_name = 'surgery_dicom_studies',
        help_text="Select the DICOM studies associated with this surgical procedure"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.diagnosis}-{self.surgery_date}"
    class Meta:
        verbose_name_plural="Surgery"
        db_table="surgery"

class ConcomitantMedications(DateValidationMixin, models.Model):
    '''This is a table of the concomitant medications that the patient may receive.'''
    chavi_medication_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )    
    medication_name = models.CharField(
        max_length=255,
        help_text="Enter the name of the medication as it appears in the medical record"
    )
    medication_dose = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=positive_decimal_validator, 
        null=True, 
        blank=True,
        help_text="Enter the prescribed dose of the medication (can be left blank if unknown)"
    )
    medication_dose_units = models.ForeignKey(
        'lookup.LookupMassUnits',
        on_delete=models.PROTECT,
        related_name='medication_dose_units',
        null=True,
        blank=True,
        help_text="Select the units for the medication dose (e.g., mg, mL, etc.)"
    )
    date_medication_start_date = models.DateField(
        help_text="Enter the date when the medication was started (format:DD/MM/YYYY)"
    )
    date_medication_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the medication was stopped, if applicable (format:DD/MM/YYYY)"
    )
    medication_route = models.ForeignKey(
        'lookup.LookupDrugRoute', 
        on_delete=models.CASCADE,
        help_text="Select how the medication was administered (e.g., oral, intravenous, etc.)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    date_validation_pairs = [
        ('date_medication_start_date', 'date_medication_end_date')
    ]

    def __str__ (self):
        return f"{self.chavi_medication_id}"
    class Meta:
        verbose_name_plural="ConcomitantMedications"
        db_table="concomitant_medications"

class SystemicTherapy(DateValidationMixin, models.Model):
    ''' This is a systemic therapy table which has details of the systemic therapy given to the patient'''

    chavi_systemic_therapy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )    
    systemic_therapy_type = models.ForeignKey('lookup.LookupSystemicTherapyType', on_delete=models.PROTECT,null=True, blank=True,
    help_text = "Select the type of systemic therapy.")
    systemic_therapy_intent = models.ForeignKey('lookup.LookupTreatmentIntent', on_delete=models.PROTECT,null=True, blank=True,
    related_name='systemic_therapy_intent', help_text="Select the intent of the systemic therapy")
    systemic_therapy_sequence = models.ForeignKey('lookup.LookupTreatmentSequence', on_delete=models.PROTECT,null=True, blank=True,
    help_text="Select the sequence for the systemic therapy")
    systemic_therapy_regimen = models.ForeignKey('lookup.LookupSystemicTherapyRegimen', on_delete=models.PROTECT,null=True, blank=True,related_name='systemic_therapy_regimen',
                                                 help_text="Select the regimen for the systemic therapy")
    systemic_therapy_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the treatment was started (format:DD/MM/YYYY)"
    )
    systemic_therapy_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the treatment was completed (format:DD/MM/YYYY)"
    )    
    cycles_delivered = models.PositiveIntegerField(null=True,blank=True,help_text="Total Number of Cycles delivered if applicable.")
    study_instance_uid = models.ManyToManyField(
        'DICOMStudy',blank = True, 
        related_name = 'systemic_therapy_dicom_studies',
        help_text="Select the DICOM studies associated with this systemic therapy course"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    date_validation_pairs = [
        ('systemic_therapy_start_date', 'systemic_therapy_end_date')
    ]

    def __str__ (self):
        return f"{self.diagnosis}-{self.systemic_therapy_regimen}"

    class Meta:
        verbose_name= "Systemic Therapy Course"
        verbose_name_plural="Systemic Therapy Courses"
        db_table="systemic_therapy"

class SystemicTherapySchedule(DateValidationMixin, models.Model):
    '''This table stores the systemic therapy drug schedule for the patients'''

    chavi_systemic_therapy_schedule_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    systemic_therapy = models.ForeignKey(
        'SystemicTherapy', 
        on_delete=models.CASCADE,
        related_name='systemic_therapy_schedule',
        null=True,
        blank=True,
        help_text="Select the systemic therapy treatment this schedule is associated with"
    )
    systemic_therapy_agent_route = models.ForeignKey(
        'lookup.LookupDrugRoute', 
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='systemic_therapy_agent_route',
        help_text="Select how the medication was administered (e.g., oral, intravenous, subcutaneous)"
    )
    systemic_therapy_agent_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this specific medication was started (format:DD/MM/YYYY)"
    )
    systemic_therapy_agent_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this specific medication was stopped (format:DD/MM/YYYY)."
    )
    systemic_therapy_agent = models.ForeignKey(
        'lookup.LookupSystemicAgent', 
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='systemic_therapy_agent',
        help_text="Select the specific medication or agent used in this treatment"
    )
    systemic_therapy_dose_planned = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the planned dose for this medication (numerical value only)"
    )
    systemic_therapy_dose_administered = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Enter the actual dose of medication that was administered (numerical value only)"
    )
    systemic_therapy_dose_units = models.ForeignKey(
        'lookup.LookupMassUnits', 
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name= 'systemic_therapy_dose_units',
        help_text="Select the units used for the dose (e.g., mg, mg/m², mg/kg)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    date_validation_pairs = [
        ('systemic_therapy_agent_start_date', 'systemic_therapy_agent_end_date')
    ]

    def __str__ (self):
        return f"{self.chavi_systemic_therapy_schedule_id}-{self.systemic_therapy_agent}-{self.systemic_therapy_agent_route}"
    class Meta:
        verbose_name="Systemic Therapy Medication Detail"
        verbose_name_plural="Systemic Therapy Medication Details"
        db_table="systematic_therapy_schedule"    

class AdverseEffects(DateValidationMixin, models.Model):
    '''This model represents adverse effects that may occur during treatment.'''

    chavi_adverse_effects_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        'Diagnosis', 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis this adverse effect is associated with"
    )
    ctcae_grade_lookup = models.ForeignKey(
        'lookup.LookupCTCAEGrade', 
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="Select the standardized CTCAE grade for this adverse effect"
    )
    adverse_effect_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this adverse effect was first noticed (format:DD/MM/YYYY)"
    )
    adverse_effect_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this adverse effect resolved, if applicable (format:DD/MM/YYYY)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    date_validation_pairs = [
        ('adverse_effect_start_date', 'adverse_effect_end_date')
    ]

    def __str__(self):
        return f"{self.diagnosis.patient.patient_id}-{self.ctcae_grade_lookup.ctcae_term}"
    
    class Meta:
        verbose_name_plural="Adverse Effects"
 
class PatientReportedOutcome(models.Model):
    ''' This is the table which will store information on the patient-reported outcomes'''
    chavi_pro_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient, 
        on_delete=models.CASCADE,
        help_text="Select the patient who completed this patient-reported outcome assessment"
    )
    pro_assessment_date = models.DateField(null=True,blank=True,help_text="Enter the date when this assessment was completed (format:DD/MM/YYYY)")
    pro_instrument = models.CharField(max_length=500, help_text="Enter the name of the instrument used for the assessment")
    pro_scale = models.CharField(max_length=500, help_text="Enter the domain the question refers to. This may represent a scale in the questionnaire")
    pro_question_id = models.CharField(max_length=500, help_text="Enter the question number from the instrument")
    pro_question = models.CharField(max_length=600, help_text="Enter the question that was asked")
    pro_answer = models.CharField(max_length=1000, help_text="Enter the answer to the question as it is recorded by the patient")
    pro_score = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Enter the numerical score for this response, if applicable "
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.chavi_pro_id}"

    class Meta:
        verbose_name_plural="Patient Reported Outcomes"
        db_table="patient_reported_outcome"    

class PatientOutcome(models.Model):
    ''' This is the table which will store information on the outcome of the patients'''
    chavi_patient_outcome_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE)
    patient_status = models.ForeignKey('lookup.LookupOutcome', on_delete=models.PROTECT,
    help_text="Select the patients last known status")
    date_of_death = models.DateField(null=True, blank=True,
    help_text="Enter the date of death, if applicable")
    last_date_of_follow_up = models.DateField(null=True, blank=True,
    help_text="Enter the last date of follow up")
    death_related_to_cancer_progression = models.BooleanField(default=False,null=True,blank=True,help_text="Indicate if the death was related to cancer progression (check for Yes, uncheck for No)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.chavi_patient_outcome_id}"

    class Meta:
        verbose_name_plural="Patient Outcomes"
        db_table="patient_outcome"

class Comorbidity(models.Model):
    ''' This is a table for recording the Comorbidities of the patients'''
    chavi_comorbidity_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient, 
        on_delete=models.CASCADE,
        help_text="Select the patient who has this comorbidity"
    )
    comorbidity_type = models.ForeignKey(
        'lookup.LookupComorbidity', 
        on_delete=models.PROTECT,
        help_text="Select the comorbidity type"
    )
    date_of_comorbidity_diagnosis = models.DateField(
        null=True, 
        blank=True,
        help_text="This will be automatically calculated based on assessment date and duration"
    )
    date_of_comorbidity_assessment = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this comorbidity was last assessed (format:DD/MM/YYYY)"
    )
    duration_of_comorbidity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Enter the duration of the comorbidity in months"
    )
    comorbidity_resolved = models.BooleanField(
        default=False,
        help_text="Indicate if the comorbidity has been resolved"
    )
    medication_for_comorbidity = models.BooleanField(
        default=False,
        help_text="Indicate if the patient is currently taking medication for the comorbidity"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Calculate diagnosis date if we have both assessment date and duration
        if self.date_of_comorbidity_assessment and self.duration_of_comorbidity:
            # Subtract months from assessment date to get diagnosis date
            self.date_of_comorbidity_diagnosis = self.date_of_comorbidity_assessment - relativedelta(months=self.duration_of_comorbidity)
        super().save(*args, **kwargs)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.comorbidity_type}"

    class Meta:
        verbose_name_plural="Comorbidities"
        db_table="comorbidity"

class StageInformation(models.Model):
    ''' This is the table which will store information on the stage of the disease.'''
    chavi_stage_information_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        'Diagnosis', 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis this staging information is associated with"
    )
    staging_system = models.ForeignKey(
        'lookup.LookupStagingSystem', 
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='staging_system',
        help_text="Select the staging system used (e.g., 'TNM 8th Edition', 'FIGO')"
    )
    stage_type = models.ForeignKey(
        'lookup.LookupStagingType',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='stage_type',
        help_text="Select the type of staging information"
    )
    t_stage_prefix = models.ForeignKey(
        'lookup.LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='t_stage_prefix',
        null=True, 
        blank=True,
        help_text="Select the prefix modifiers for the T stage (e.g., 'c' for clinical, 'p' for pathological)"
    )
    t_stage = models.ForeignKey(
        'lookup.LookupAJCCTStageDescriptor',
        on_delete=models.PROTECT,
        related_name = 't_stage',
        null=True, 
        blank=True,
        help_text="Select the T stage describing the primary tumor (e.g., 'T1', 'T2', 'T3', 'T4')"
    )
    t_stage_suffix = models.ForeignKey(
        'lookup.LookupAJCCStageSuffix',
        on_delete=models.PROTECT,
        related_name='t_stage_suffix',             
        null=True, 
        blank=True,
        help_text="Enter any suffix modifiers for the T stage (e.g., 'a', 'b', 'c')"
    )
    n_stage_prefix = models.ForeignKey(
        'lookup.LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='n_stage_prefix',        
        null=True, 
        blank=True,   
        help_text="Select any prefix modifiers for the N stage (e.g., 'c' for clinical, 'p' for pathological)"
    )
    n_stage = models.ForeignKey(
        'lookup.LookupAJCCNStageDescriptor',
        on_delete=models.PROTECT,
        related_name='n_stage',
        null=True, 
        blank=True,
        help_text="Enter the N stage describing lymph node involvement (e.g., 'N0', 'N1', 'N2', 'N3')"
    )
    n_stage_suffix = models.ForeignKey(
        'lookup.LookupAJCCStageSuffix',
        on_delete=models.PROTECT,
        related_name='n_stage_suffix',         
        null=True, 
        blank=True,  
        help_text="Select any suffix modifiers for the N stage (e.g., 'a', 'b', 'c')"
    ) 
    m_stage_prefix = models.ForeignKey(
        'lookup.LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='m_stage_prefix',        
        null=True, 
        blank=True,        
        help_text="Select any prefix modifiers for the M stage (e.g., 'c' for clinical, 'p' for pathological)"
    )
    m_stage = models.ForeignKey(
        'lookup.LookupAJCCMStageDescriptor',
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="Enter the M stage describing distant metastasis (e.g., 'M0', 'M1', 'M1a', 'M1b')"
    )
    m_stage_suffix = models.ForeignKey(
        'lookup.LookupAJCCStageSuffix',
        related_name='m_stage_suffix',        
        on_delete=models.PROTECT,
        null=True, 
        blank=True,  
        help_text="Enter any suffix modifiers for the M stage (e.g., 'a', 'b', 'c')"
    ) 
    overall_stage = models.ForeignKey(
        'lookup.LookupStageDescriptor',
        on_delete=models.PROTECT,
        related_name= 'overall_stage',
        null=True, 
        blank=True,
        help_text="Enter the overall stage grouping (e.g., 'Stage I', 'Stage II', 'Stage III', 'Stage IV')"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return self.diagnosis.diagnosis_id

    class Meta:
        verbose_name_plural="Stage Information"
        db_table='stage_information'    

class QualitativeLaboratoryResult(models.TextChoices):
    ''' This is a model for the qualitative laboratory results.'''
    Present = 'Present'
    Absent = 'Absent'
    Positive = 'Positive'
    Negative = 'Negative'
    Indeterminate = 'Indeterminate'
    Reactive = 'Reactive'
    NonReactive = 'Non-Reactive'
    Detected = 'Detected'
    NotDetected = 'Not Detected'
    Invalid = 'Invalid'
    Borderline = 'Borderline'        

class LaboratoryResults(models.Model):
    ''' This is a model for the laboratory results. This is a many to one relationship with the patient model.'''
    chavi_laboratory_result_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE,help_text="Select the patient for whom the laboratory result was obtained")
    laboratory_test = models.ForeignKey('lookup.LookupLaboratoryTest', on_delete=models.PROTECT,help_text="Select the laboratory test for which the result was obtained")
    result_date = models.DateField(null=True, blank=True,help_text="Enter the date of the laboratory result")
    quantitative_result_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Enter the value of the laboratory result")
    quantitative_result_unit = models.ForeignKey('lookup.LookupLabResultsUnits',null=True, blank=True, on_delete=models.PROTECT,help_text="Select the unit of the laboratory result")
    qualitative_laboratory_result = models.CharField(max_length=20, choices=QualitativeLaboratoryResult.choices, null=True, blank=True,help_text="Select the qualitative laboratory result")    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.laboratory_test.label}"
    
    class Meta:
        verbose_name_plural="Laboratory Results"
        db_table='laboratory_results'        

class PatientAssessment(models.Model):
    ''' This is a table for recording the assessments of the patients'''
    chavi_patient_assessment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE,help_text="Select the patient for whom the assessment was performed")
    date_assessment = models.DateField(null=True, blank=True,help_text="Enter the date of the assessment")
    height = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Enter the height of the patient in centimeters")
    weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Enter the weight of the patient in kilograms")
    systolic_blood_pressure = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Enter the systolic blood pressure of the patient in millimeters of mercury")
    diastolic_blood_pressure = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Enter the diastolic blood pressure of the patient in millimeters of mercury")
    pulse = models.PositiveIntegerField(null=True, blank=True,help_text="Enter the pulse of the patient in beats per minute")
    temperature = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Enter the temperature of the patient in degrees Celsius")
    respiratory_rate = models.PositiveIntegerField(null=True, blank=True,help_text="Enter the respiratory rate of the patient in breaths per minute")
    performance_status = models.ForeignKey('lookup.LookupPerformanceStatus', on_delete=models.PROTECT,null=True, blank=True,help_text="Select the performance status of the patient")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__ (self):
        return f"{self.patient.patient_id} - {self.date_assessment}"
    
    class Meta:
        verbose_name_plural="Patient Assessments"
        db_table='patient_assessments'
    
class DICOMStudyProject(models.Model):
    '''This is a through table for relating DICOM studies to Projects'''
    study_instance_uid = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name="Project for DICOM Study"
        verbose_name_plural="Projects for DICOM Study"
        constraints = [
            models.UniqueConstraint(
                fields=['study_instance_uid', 'project'],
                name='unique_dicom_study_project'
            )
        ]

# Model created for handling bulk uploads of DICOM files from multiple patients. It matches the DICOM files to existing patients based on the Patient ID found in the DICOM metadata.
class BulkDICOMUpload(models.Model):
    '''This model handles bulk uploads of DICOM files from multiple patients. It matches the DICOM files to existing patients based on the Patient ID found in the DICOM metadata.'''
    file = models.FileField(
        upload_to='bulk_dicom_files',
        validators=[FileExtensionValidator(allowed_extensions=["zip"])],
        help_text="Upload a zip file containing DICOM studies from multiple patients. Files will be processed and sorted based on Patient IDs found in DICOM metadata."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50, default='Pending')
    
    class Meta:
        verbose_name = "Bulk DICOM Upload"
        verbose_name_plural = "Bulk DICOM Uploads"


# This model will be used to store the data regarding unprocessed DICOM studies after bulk upload and allow users to match these with patients in the database and process them afterwards.
class UnprocessedDICOMStudies(models.Model):
    '''This model handles the unprocessed DICOM studies'''
    study_instance_uid = models.CharField(max_length=64, primary_key=True)
    dicom_patient_id = models.CharField(max_length=64, null=True, blank=True)
    patient_id = models.ForeignKey(Patient, on_delete=models.CASCADE,null=True, blank=True)
    folder_path = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Unprocessed DICOM Study"
        verbose_name_plural = "Unprocessed DICOM Studies"
        
    def __str__(self):
        return f"{self.study_instance_uid} - {self.dicom_patient_id}"
    

    