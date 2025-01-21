from django.db import models
from django.db.models.functions import Substr, Concat
from solo.models import SingletonModel
from django.core.validators import FileExtensionValidator
import uuid
# Center Model configuration - singleton model using Solo

class SiteConfiguration(SingletonModel):
    '''This form allows the user to add infomration regarding the site at which the client is installed. The center code will be provided by the CHAVI team for the site.'''
    chavi_center_id = models.CharField(max_length=255,default="Site ID. This will be provided to you at the time of installation.")
    center_name = models.CharField(max_length=255, default="Your Hospital")
    center_address = models.TextField(
        null=True,
        blank=True,
        help_text="The complete street address of the medical center. Should include building number, street name, and any additional address details like suite or floor number. Example: '1216 Second Street SW'. This field is optional."
    )
    center_city = models.TextField(
        null=True,
        blank=True,
        help_text="The city where the medical center is located. Should be written in full without abbreviations. Example: 'Rochester' or 'New York City'. This field is optional."
    )
    center_state = models.TextField(
        null=True,
        blank=True,
        help_text="The state or province where the medical center is located. For US locations, use the full state name or standard two-letter abbreviation. For international locations, use appropriate regional divisions. Example: 'Minnesota' or 'MN'. This field is optional."
    )
    center_country = models.TextField(
        null=True,
        blank=True,
        help_text="The country where the medical center is located. Use the full country name, not abbreviations. Example: 'United States' or 'Canada'. This field is optional."
    )

    def __str__(self):
        return self.center_name
    class Meta:
        verbose_name = "Site Configuration"

# Lookup Models

class LookupAbstract(models.Model):
    '''This is an abstract for the lookup table.'''
    code = models.CharField(max_length=50,primary_key=True)
    label = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

class LookupLaterality(LookupAbstract):
    '''This is a lookup table for the laterality i.e. Left, Right etc. ICD 11 codes are included for data sharing.'''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupICDCode(LookupAbstract):
    '''This is a lookup table with ICD 11 codes for the diagnosis.'''
    icd_version = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupFMACode(LookupAbstract):
    '''This is a lookup table with Foundational Model of Anatomy codes for the Anatomical Site of the disease.'''
    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupPresentation(LookupAbstract):
    '''This is a lookup for presentation type.'''
    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupOutcomeType(LookupAbstract):
    '''This is a lookup table where outcome type like local recurrence, nodal recurrence etc are recorded.'''
    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupLesionType(LookupAbstract):
    '''This is a lookup table where lesion location type is recorded e.g. local, nodal, distant '''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupResponseType(LookupAbstract):
    '''This is a lookup table for the response type that the lesion has had. For example complete response, partial response, stable disease, progressive disease.'''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupUniProt(models.Model):
    '''This is a lookup table from the UniProt Database for Protein Names.'''
    code = models.CharField(max_length=50,primary_key=True)
    gene_name = models.CharField(max_length=500,null=True)
    uniport_id = models.CharField(max_length=500,null=True)
    protein_name = models.CharField(max_length=500,null=True)
    all_gene_names = models.CharField(max_length=500,null=True)


    def __str__(self):
        return f'{self.gene_name}-{self.protein_name}'

class LookupCosmic(models.Model):
    '''This is a lookup table from the Cosmic Database for Gene Names.'''
    code = models.CharField(max_length=50,primary_key=True)
    gene_name = models.CharField(max_length=500,null = True)
    gene_description = models.CharField(max_length=500,null = True)
    gene_aliases = models.CharField(max_length=500,null = True)

    def __str__(self):
        return f"{self.gene_name} - {self.gene_description}"

class LookupTreatmentIntent(LookupAbstract):
    '''This is a lookup table for Treatment Intent.'''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupTreatmentSequence(LookupAbstract):
    '''This is a lookup table for Treatment Sequence.'''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupSystemicAgent(LookupAbstract):
    '''This is a lookup table for Systemic Agents.'''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupUnits(LookupAbstract):
    '''This is a lookup table for units of measurement for use in the database'''

    unit_abbreviation = models.CharField(max_length=255)
    
    def __str__(self):
        return self.unit_abbreviation

class LookupDrugRoute(LookupAbstract):
    '''This is a lookup table for drug routes.'''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupCTCAEGrade(models.Model):
    '''This is a lookup table for the NCI Common Terminology of Adverse Effects grades.'''
    code = models.CharField(max_length=50,primary_key=True)
    ctcae_term = models.CharField(max_length=255)
    meddra_code = models.CharField(max_length=255)
    ctcae_grade = models.BigIntegerField()
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.ctcae_term} - Grade {self.ctcae_grade}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['ctcae_term', 'ctcae_grade'],
                name='unique_ctcae_term_grade'
            )
        ]

class LookupOutcome(LookupAbstract):
    '''This is a lookup table for outcomes types.'''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupStagingSystem(LookupAbstract):
    '''This is a lookup table for staging systems.'''
    staging_system_version = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupAJCCStagePrefix(LookupAbstract):
    '''This is a lookup table for AJCC stage prefixes.'''
    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupAJCCStageSuffix(LookupAbstract):
    '''This is a lookup table for AJCC stage suffixes.'''

    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupAJCCTStageDescriptor (LookupAbstract):
    ''' This is a lookup table for AJJC T stage descriptors.'''
    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupAJCCNStageDescriptor (LookupAbstract):
    ''' This is a lookup table for AJJC N stage descriptors.'''
    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupAJCCMStageDescriptor (LookupAbstract):
    ''' This is a lookup table for AJJC M stage descriptors.'''
    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupStageDescriptor (LookupAbstract):
    ''' This is a lookup table for AJJC stage descriptors.'''
    def __str__(self):
        return f"{self.code} - {self.label}"

class LookupDiagnosticModality(LookupAbstract):
    ''' This is a lookup table for the diagnostic modality'''
    def __str__(self):
        return f"{self.code} - {self.label}"
    class Meta:
        verbose_name_plural= "Diagnostic Modalities"
        db_table = 'lookup_diagnostic_modality'

class LookupSystemicTherapyType(LookupAbstract):
    ''' This is a lookup table for the type of Systemic Therapy'''
    def __str__(self):
        return f"{self.code} - {self.label}"

    class Meta:
        verbose_name_plural = "Systemic Therapy Types"
        db_table = 'lookup_systemic_therapy_type'

class LookupRadiotherapyVolumeType(LookupAbstract):
    ''' This is a lookup table for the type of Radiotherapy Volume'''
    def __str__(self):
        return f"{self.code} - {self.label}"

    class Meta:
        verbose_name_plural = "Radiotherapy Volume Types"
        db_table = 'lookup_radiotherapy_volume_type'


# Project Model

class Project(models.Model):
    ''' This is a table which will contain the details of the Projects in which the data will be collected. Projects have a unique ID which is generated at the CHAVI server. However your institutional IRB approvals may be different for the projects. '''
    chavi_project_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="A unique identifier for the project."
    )
    center = models.ForeignKey(SiteConfiguration, on_delete=models.CASCADE,  null=True, blank=True, default=1, related_name="project_center")
    project_name = models.CharField(
        max_length=900,
        null=True, 
        blank=True,
        help_text="The descriptive name of the project. This should be a clear, recognizable title. Example: 'Breast Cancer Imaging Study 2023'"
    )
    project_abbreviation = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="The abbreviation for the project."
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        help_text="The date when this project officially began. Format: YYYY-MM-DD. Example: '01-01-2023'"
    )
    project_irb_approval = models.BooleanField(
        null=True,
        blank=True,
        help_text="Indicate whether this project has received IRB (Institutional Review Board) approval. Check the box for Yes, leave unchecked for No."
    )
    project_irb_approval_number = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="If IRB approval was received, enter the IRB protocol number here. This can typically be found on your IRB approval letter. Example: 'IRB-2023-123'"
    )
    completion_date = models.DateField(
        null=True,
        blank=True,
        help_text="The date when this project was or is expected to be completed. Format: YYYY-MM-DD. Example: '31-12-2024'"
    )
    description = models.TextField(
        null= True,
        blank=True,
        help_text="A detailed description of the project's purpose, goals, and methods. This should be comprehensive enough for others to understand what the project is about."
    )
    license = models.CharField(
        null=True,
        blank=True,
        max_length=255,
        help_text="The type of license under which this project's data is shared. Example: 'MIT', 'Apache 2.0', 'CC BY 4.0'"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.project_name

    class Meta:
        verbose_name_plural = "Projects"
        db_table="project"

# Core Patient Models
class Patient(models.Model):
    ''' This is the main patient model. Only patient ID and gender data are collected in this table.'''
    center = models.ForeignKey(SiteConfiguration, 
    on_delete=models.CASCADE, 
    null=True, blank=True,
    default=1,
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
        unique=True,
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
        help_text="The patient's date of birth in YYYY-MM-DD format."
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
        null=True,
        blank=True,
        help_text="A unique identifier for this specific imaging study. This is like a serial number - no two imaging studies anywhere should have the same Study Instance UID. This helps prevent any confusion between different studies."
    )
    study_date = models.DateField(
        null = True,
        blank = True,
        help_text="The date when this imaging study was performed. This is recorded as YYYY-MM-DD format (for example: 2023-12-25)."
    )
    study_description = models.CharField(
        max_length = 255,
        null = True,
        blank = True, 
        help_text = "Description of the study Provided in the DICOM Data"
    )
    series_descriptions = models.TextField(
        null = True,
        blank = True,
        help_text = "Description of the series in the study. This is a text field that can store multiple series descriptions, separated by commas."
    )
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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey('LookupICDCode',related_name= 'diagnosis_code', on_delete=models.PROTECT,
    help_text="Select the diagbnosis ICD code. If the patient has multiple diagnoses then you can add another instance of the form.")
    diagnosis_date = models.DateField(null=True, blank=True,
    help_text="Select the data at which the diagnosis was made. This can be a date when the patient came to the hospital for the first time or when a pathological proof was obtained")
    presentation_type = models.ForeignKey(LookupPresentation, on_delete=models.PROTECT,
    help_text="Select the type of presentation. This can be a new presentation or a recurrence or a metastasis.")
    cancer_site = models.ForeignKey(LookupFMACode, on_delete=models.PROTECT,
    help_text="Select the cancer site. This can be a site where the cancer was first diagnosed or a site where the cancer was recurred or metastasized.")
    cancer_side = models.ForeignKey(LookupLaterality, on_delete=models.PROTECT,
    help_text="Select the side at which the cancer was present.")
    diagnostic_modality = models.ForeignKey('LookupDiagnosticModality',on_delete=models.PROTECT,null=True, blank=True,
    help_text="If the cancer was diagnosed with a method like cytology, biopsy etc then the modality can be entered here. Please ensure that the modality is spelled correctly.")
    diagnosis_dicom_study = models.ManyToManyField('DICOMStudy', blank = True, help_text="Select the DICOM studies that were used to diagnose the cancer. You can select multiple studies.")
    diagnosis_project = models.ManyToManyField('Project', blank = True, help_text="Select the project that was used to diagnose the cancer. You can select multiple projects.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient.patient_id} - {self.diagnosis__label} - {self.diagnosis_date}"

    class Meta:
        verbose_name_plural="Diagnoses"
        db_table = 'diagnosis'    

class Outcome(models.Model):
    '''This table stores information related to the outcome of the cancer treatment for the disease. Note that the patient outcome table is separate.'''
    chavi_outcome_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE)
    date_outcome_assessed = models.DateField(null=True, blank=True,
    help_text = "Date this Outcome was assessed or documented or confirmed.")
    outcome_type = models.ForeignKey(LookupOutcomeType, on_delete=models.PROTECT,
    help_text = "Select the Type of Outcome. If you wish to add another outcome then please create another instance of the form.")
    outcome_dicom_study = models.ManyToManyField('DICOMStudy',blank = True, related_name = "outcome_dicom_study",help_text = "Select all DICOM Studies for this Disease Outcome")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.diagnosis.patient.patient_id} - {self.date_outcome_assessed}"
    
    class Meta:
        verbose_name = "Cancer Outcome"
        verbose_name_plural="Cancer Outcomes"
        db_table = 'outcome'

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
        LookupFMACode, 
        on_delete=models.PROTECT,
        help_text="The anatomical location where the lesion is found (e.g., 'Left Breast', 'Right Lung')"
    )
    lesion_type = models.ForeignKey(
        LookupLesionType, 
        on_delete=models.PROTECT,
        help_text="The type or category of the lesion (e.g., 'Primary Tumor', 'Metastatic Lesion')"
    )
    lesion_laterality = models.ForeignKey(
        LookupLaterality, 
        on_delete=models.PROTECT,
        help_text="Indicates which side of the body the lesion is on (e.g., 'Left', 'Right', 'Bilateral')"
    )
    lesion_size_x_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The width (x-axis measurement) of the lesion in the specified unit of measurement"
    )
    lesion_size_y_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The length (y-axis measurement) of the lesion in the specified unit of measurement"
    )
    lesion_size_z_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The depth (z-axis measurement) of the lesion in the specified unit of measurement"
    )
    lesion_size_unit = models.ForeignKey(
        LookupUnits, 
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
        help_text="The total volume of the lesion, calculated from the three-dimensional measurements"
    )
    lesion_volume_unit = models.ForeignKey(
        LookupUnits, 
        related_name='lesion_volume_unit',
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        help_text="The unit of measurement used for the lesion volume (e.g., 'cubic millimeters', 'cubic centimeters')"
    )
    lesion_dicom_study = models.ManyToManyField('DICOMStudy', blank = True, related_name = 'lesion_dicom_study',help_text = "Select all the DICOM Studies associated with this Lesion")
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
        LookupResponseType, 
        on_delete=models.CASCADE,
        help_text="How the lesion has responded to treatment (e.g., complete response, partial response, stable disease, etc.)"
    )
    residual_lesion_size_x_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The width (left to right measurement) of any remaining lesion after treatment"
    )
    residual_lesion_size_y_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The length (front to back measurement) of any remaining lesion after treatment"
    )
    residual_lesion_size_z_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The height (top to bottom measurement) of any remaining lesion after treatment"
    )
    residual_lesion_volume = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The total volume (size in three dimensions) of any remaining lesion after treatment"
    )
    lesion_response_dicom_study = models.ManyToManyField(
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
        null=True, 
        blank=True,
        help_text="The type of specimen collected (e.g., 'Core Biopsy', 'Surgical Resection', 'Fine Needle Aspiration')"
    )
    tumor_site = models.ForeignKey(
        LookupFMACode, 
        on_delete=models.CASCADE,
        help_text="The anatomical location of the tumor as defined by the Foundational Model of Anatomy (FMA)"
    )
    tumor_side = models.ForeignKey(
        LookupLaterality, 
        on_delete=models.CASCADE,
        help_text="The side of the body where the tumor is located (e.g., 'Left', 'Right', 'Bilateral')"
    )
    histological_type = models.CharField(
        max_length=500,
        null=True, 
        blank=True,
        help_text="The primary histological classification of the tumor (e.g., 'Adenocarcinoma', 'Squamous Cell Carcinoma')"
    )
    histological_subtype = models.CharField(
        max_length=500,
        null=True, 
        blank=True,
        help_text="A more specific classification within the histological type (e.g., 'Mucinous', 'Papillary')"
    )
    histological_grade = models.CharField(
        max_length=50,
        null=True, 
        blank=True,
        help_text="The degree of differentiation of the tumor cells (e.g., 'Grade 1', 'Grade 2', 'Grade 3')"
    )
    histological_grading_schema = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="The system used to determine the histological grade (e.g., 'Nottingham', 'Gleason', 'WHO')"
    )
    greatest_dimension_of_tumor = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The primary dimension of the tumor measured in centimeters"
    )
    additional_tumor_dimension_1 = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The second dimension of the tumor measured in centimeters"
    )
    additional_tumor_dimension_2 = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The third dimension of the tumor measured in centimeters"
    )
    tumor_focality = models.CharField(
        max_length=50,
        null=True, 
        blank=True,
        help_text="Whether the tumor is unifocal (single focus) or multifocal (multiple foci)"
    )
    lymphatic_vascular_invasion = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Presence or absence of tumor cells within lymphatic or blood vessels"
    )
    perineural_invasion = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Presence or absence of tumor cells invading nerve tissue"
    )
    dermal_lymphatic_vascular_invasion = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Presence or absence of tumor cells within dermal lymphatic vessels"
    )
    lymph_nodes_removed = models.BooleanField(
        null=True, 
        blank=True,
        help_text="Whether lymph nodes were removed in the specimen"
    )
    lymph_nodes_in_specimen = models.BigIntegerField(
        null=True, 
        blank=True,
        help_text="Total number of lymph nodes found in the specimen"
    )
    number_of_uninvolved_nodes = models.BigIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes without any tumor involvement"
    )
    number_of_nodes_with_macrometastases = models.BigIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes with visible tumor deposits"
    )
    number_of_nodes_with_micrometastases = models.BigIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes with microscopic tumor deposits (0.2-2.0mm)"
    )
    number_of_nodes_with_isolated_tumor_cells = models.BigIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes with isolated tumor cells (<0.2mm)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.pathology.patient.patient_id} - {self.pathology.histological_type}"

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
        help_text="Enter the date when the immunohistochemistry test was performed (format: YYYY-MM-DD)"
    )
    protein_name = models.ForeignKey(
        LookupUniProt, 
        on_delete=models.CASCADE,
        help_text="Select the protein that was tested for in this immunohistochemistry test"
    )
    ihc_result = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Enter the result of the immunohistochemistry test (e.g., 'Positive', 'Negative', or specific values like '3+')"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.immunohistochemistry.chavi_ihc_id}"

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
        help_text="Enter the date when the cytogenetics test was performed (format: YYYY-MM-DD)"
    )
    gene = models.ForeignKey(
        LookupCosmic, 
        on_delete=models.PROTECT,
        help_text="Select the gene that was tested for in this cytogenetics test"
    )
    cytogenetic_result = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Enter the result of the cytogenetics test (e.g., 'Normal', 'Abnormal', or specific findings)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.cytogenetics.chavi_cytogenetics_id}"
    
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
        help_text="Enter the date when the genomic testing was performed (format: YYYY-MM-DD)"
    )
    cosmic_gene_name = models.ForeignKey(
        LookupCosmic, 
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
        help_text="Enter the variant allele frequency as a decimal (e.g., 0.45 for 45%)"
    )
    read_depth = models.IntegerField(
        null=True, 
        blank=True,
        help_text="Enter the sequencing read depth at this position (e.g., 500)"
    )
    clinical_significance = models.CharField(
        max_length=50,
        null=True, 
        blank=True,
        help_text="Indicate the clinical significance of the variant (e.g., 'Pathogenic', 'Benign', 'VUS')"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.somatic_genomic_alterations.chavi_somatic_genomic_id}"
    
    class Meta:
        verbose_name_plural="Somatic Genomic Alterations"
        db_table="somatic_genomic_alterations"

class OtherTreatment(models.Model):
    ''' The table will store information on other treatments that the patient undergoes'''
    chavi_treatment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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

    def __str__ (self):
        return f"{self.treatment.chavi_treatment_id}"
    class Meta:
        verbose_name = "Other Treatment"
        verbose_name_plural="Other Treatments"
        db_table="other_treatment"

class Radiotherapy(models.Model):
    '''This table will record the radiotherapy course details for the patient's diagnosis.'''
    chavi_radiotherapy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )    
    radiotherapy_modality = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Enter the type of radiation used (e.g., 'External Beam', 'Brachytherapy', 'Proton Therapy')"
    )
    total_dose = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Enter the total radiation dose delivered during the entire course of treatment (in Gray or specified units)"
    )
    total_fractions = models.BigIntegerField(
        null=True, 
        blank=True,
        help_text="Enter the total number of treatment sessions (fractions) planned for the complete course of radiotherapy"
    )
    radiation_dose_units = models.ForeignKey(
        LookupUnits,
        related_name= 'radiation_course_dose_units',
        on_delete = models.PROTECT,
        null=True, 
        blank=True,
        help_text="Select the units used to measure the radiation dose (e.g., 'Gy', 'cGy')"
    )
    radiotherapy_type = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Enter the type of radiotherapy treatment (e.g., 'Definitive', 'Palliative', 'Adjuvant')"
    )
    radiotherapy_sequence = models.ForeignKey(
        'LookupTreatmentSequence', 
        on_delete=models.PROTECT,
        help_text="Select the sequence of this radiotherapy in relation to other treatments (e.g., 'Primary', 'Boost', 'Concurrent')"
    )
    radiotherapy_technique = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="Enter the specific technique used to deliver the radiation (e.g., 'IMRT', '3D-CRT', 'VMAT')"
    )
    fractions_per_day = models.BigIntegerField(
        null=True, 
        blank=True,
        default = 1,
        help_text="Enter the number of treatment sessions (fractions) delivered per day"
    )
    radiotherapy_site = models.ForeignKey(
        'LookupFMACode', 
        on_delete=models.PROTECT,
        help_text="Select the anatomical location where the radiation is being delivered"
    )
    radiotherapy_side = models.ForeignKey(
        'LookupLaterality', 
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
        help_text="Enter the date when the treatment was started (format: YYYY-MM-DD)"
    )
    radiotherapy_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the treatment was completed (format: YYYY-MM-DD)"
    )
    radiotherapy_dicom_study = models.ManyToManyField(
        'DICOMStudy',blank = True, 
        related_name = 'radiotherapy_dicom_studies',
        help_text="Select the DICOM studies associated with this radiotherapy course"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.radiotherapy.chavi_radiotherapy_id}"
    class Meta:
        verbose_name = "Radiotherapy Course"
        verbose_name_plural="Radiotherapy Courses"
        db_table="radiotherapy"

class RadiotherapyVolume(models.Model):
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
        'LookupRadiotherapyVolumeType',
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
        help_text="Enter the prescribed dose for this volume in Gray (Gy)",
    )
    radiation_dose_units = models.ForeignKey(
        'LookupUnits',
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
        help_text="Enter the start date for this volume (format: YYYY-MM-DD)"
    )
    volume_radiotherapy_end_date = models.DateField(    
        null=True,
        blank=True,
        help_text="Enter the end date for this volume (format: YYYY-MM-DD)"     
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
        LookupRadiotherapyVolumeType,
        on_delete=models.PROTECT,
        help_text="Select the type of volume (e.g., 'CTV', 'PTV')"
    )
    absolute_volume = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Enter the absolute volume in cubic centimeters (cc)"
    )
    relative_volume = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,      
        blank=True,     
        help_text="Enter the relative volume as a percentage (%)"
    )
    volume_units = models.ForeignKey(
        LookupUnits,
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
        help_text="Enter the absolute dose in Gray (Gy) or cGy"
    )
    relative_dose = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Enter the relative dose as a percentage (%)"
    )
    volume_dose_prescribed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Enter the dose prescribed to this volume in Gray (Gy) or cGy"
    )
    radiation_dose_units = models.ForeignKey(
        LookupUnits,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name = "radiation_dose_units",
        help_text="Select the units for the dose (e.g., 'Gy', 'cGy', '%')"
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

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
        help_text="Enter the date when the surgery was performed (format: YYYY-MM-DD)"
    )
    surgery_site = models.ForeignKey(
        LookupFMACode, 
        on_delete=models.PROTECT,
        help_text="Select the anatomical location where the surgery was performed"
    )
    surgery_side = models.ForeignKey(
        LookupLaterality, 
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="Select which side of the body the surgery was performed on (e.g., 'Left', 'Right', 'Bilateral')"
    )
    surgery_type = models.CharField(
        max_length=255,
        help_text="Enter the type of surgical procedure performed (e.g., 'Mastectomy', 'Lumpectomy', 'Excisional Biopsy')"
    )
    nodal_assessment = models.BooleanField(
        null=True, 
        blank=True,
        help_text="Indicate whether lymph nodes were assessed during surgery (check for Yes, leave unchecked for No)"
    )
    nodal_assessment_type = models.CharField(
        max_length=255,
        null=True, 
        blank=True,
        help_text="If nodes were assessed, specify the type of assessment (e.g., 'Sentinel Node Biopsy', 'Axillary Dissection')"
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
    surgery_dicom_study = models.ManyToManyField(
        'DICOMStudy',blank = True, 
        related_name = 'surgery_dicom_studies',
        help_text="Select the DICOM studies associated with this surgical procedure"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.surgery.chavi_surgery_id}"
    class Meta:
        verbose_name_plural="Surgery"
        db_table="surgery"

class ConcomitantMedications(models.Model):
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
        null=True, 
        blank=True,
        help_text="Enter the prescribed dose of the medication (can be left blank if unknown)"
    )
    medication_dose_units = models.ForeignKey(
        LookupUnits,
        on_delete=models.PROTECT,
        related_name='medication_dose_units',
        null=True,
        blank=True,
        help_text="Select the units for the medication dose (e.g., mg, mL, etc.)"
    )
    date_medication_start_date = models.DateField(
        help_text="Enter the date when the medication was started (format: YYYY-MM-DD)"
    )
    date_medication_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the medication was stopped, if applicable (format: YYYY-MM-DD)"
    )
    medication_route = models.ForeignKey(
        LookupDrugRoute, 
        on_delete=models.CASCADE,
        help_text="Select how the medication was administered (e.g., oral, intravenous, etc.)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.concomitant_medications.chavi_medication_id}"
    class Meta:
        verbose_name_plural="ConcomitantMedications"
        db_table="concomitant_medications"

class SystemicTherapy(models.Model):
    ''' This is a systemic therapy table which has details of the systemic therapy given to the patient'''

    chavi_systemic_therapy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )    
    systemic_therapy_type = models.ForeignKey(LookupSystemicTherapyType, on_delete=models.PROTECT,null=True, blank=True,
    help_text = "Select the type of systemic therapy.")
    systemic_therapy_sequence = models.ForeignKey(LookupTreatmentSequence, on_delete=models.PROTECT,
    help_text="Select the sequence for the systemic therapy")
    systemic_therapy_regimen = models.CharField(max_length=255, null=True, blank=True,help_text="Please enter the name of the systemic therapy regimen if there is a multi-drug or named regimen being used.")
    systemic_therapy_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the treatment was started (format: YYYY-MM-DD)"
    )
    systemic_therapy_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when the treatment was completed (format: YYYY-MM-DD)"
    )    
    cycles_delivered = models.BigIntegerField(null=True,blank=True,help_text="Total Number of Cycles delivered if applicable.")
    systemic_therapy_dicom_study = models.ManyToManyField(
        'DICOMStudy',blank = True, 
        related_name = 'systemic_therapy_dicom_studies',
        help_text="Select the DICOM studies associated with this systemic therapy course"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.systemic_therapy.chavi_systemic_therapy_id}"

    class Meta:
        verbose_name= "Systemic Therapy Course"
        verbose_name_plural="Systemic Therapy Courses"
        db_table="systemic_therapy"

class SystemicTherapySchedule(models.Model):
    '''This table stores the systemic therapy drug schedule for the patients'''

    chavi_systemic_therapy_schedule_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    systemic_therapy = models.ForeignKey(
        'SystemicTherapy', 
        on_delete=models.CASCADE,
        help_text="Select the systemic therapy treatment this schedule is associated with"
    )
    systemic_therapy_agent_route = models.ForeignKey(
        'LookupDrugRoute', 
        on_delete=models.PROTECT,
        help_text="Select how the medication was administered (e.g., oral, intravenous, subcutaneous)"
    )
    systemic_therapy_agent_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this specific medication was started (format: YYYY-MM-DD)"
    )
    systemic_therapy_agent_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this specific medication was stopped (format: YYYY-MM-DD)."
    )
    systemic_therapy_agent = models.ForeignKey(
        'LookupSystemicAgent', 
        on_delete=models.PROTECT,
        help_text="Select the specific medication or agent used in this treatment"
    )
    systemic_therapy_dose_planned = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Enter the planned dose for this medication (numerical value only)"
    )
    systemic_therapy_dose_administered = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Enter the actual dose of medication that was administered (numerical value only)"
    )
    systemic_therapy_dose_units = models.ForeignKey(
        'LookupUnits', 
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name= 'systemic_therapy_dose_units',
        help_text="Select the units used for the dose (e.g., mg, mg/m², mg/kg)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.systemic_therapy_schedule.chavi_systemic_therapy_schedule_id}"
    class Meta:
        verbose_name="Medication Detail"
        verbose_name_plural="Medication Details"
        db_table="systematic_therapy_schedule"    

class AdverseEffects(models.Model):
    '''This model represents adverse effects that may occur during treatment.'''

    chavi_adverse_effects_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        'Diagnosis', 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis this adverse effect is associated with"
    )
    ctcae_grade_lookup = models.ForeignKey(
        'LookupCTCAEGrade', 
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="Select the standardized CTCAE grade for this adverse effect"
    )
    adverse_effect_type = models.CharField(
        max_length=255,
        help_text="Enter the type or name of the adverse effect"
    )
    adverse_effect_grade = models.PositiveIntegerField(
        null = True,
        blank = True,
        help_text="Enter the severity grade of the adverse effect (typically 1-5, where 5 is most severe)"
    )
    adverse_effect_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this adverse effect was first noticed (format: YYYY-MM-DD)"
    )
    adverse_effect_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this adverse effect resolved, if applicable (format: YYYY-MM-DD)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def save(self, *args, **kwargs):
        if self.ctcae_grade_lookup:
            # Automatically set type and grade from the lookup
            self.adverse_effect_type = self.ctcae_grade_lookup.ctcae_term
            self.adverse_effect_grade = self.ctcae_grade_lookup.ctcae_grade
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.ctcae_grade_lookup:
            # Ensure the type and grade match the lookup
            if (self.adverse_effect_type != self.ctcae_grade_lookup.ctcae_term or
                self.adverse_effect_grade != self.ctcae_grade_lookup.ctcae_grade):
                raise ValidationError(
                    'Adverse effect type and grade must match the selected CTCAE grade lookup'
                )

    
    def __str__(self):
        return f"{self.adverse_effect_type} - {self.adverse_effect_grade}"
    class Meta:
        verbose_name_plural="Adverse Effects"
        db_table="adverse_effects"   

class ProInstrument(models.Model):
    '''This is a table which stores information on the patient reported outcome instruments.'''
    pro_instrument = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.pro_instrument

    class Meta:
        verbose_name_plural="PRO Instruments"
        db_table="pro_instrument"

class ProDomain(models.Model):
    '''This is a table which stores information on the patient reported outcome domains.'''
    instrument = models.ForeignKey(ProInstrument, on_delete=models.CASCADE)
    pro_domain = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['instrument', 'pro_domain'],
                name='unique_instrument_pro_domain'
            )
        ]

    def __str__(self):
        return f"{self.instrument.pro_instrument} - {self.pro_domain}"

class ProQuestion(models.Model):
    '''This is a table which stores information on the patient reported outcome questions.'''
    domain = models.ForeignKey(ProDomain, on_delete=models.CASCADE)
    pro_question = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['domain', 'pro_question'],
                name='unique_dommain_pro_question'
            )
        ]

class PatientReportedOutcome(models.Model):
    ''' This is the table which will store information on the patient-reported outcomes'''
    chavi_pro_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient, 
        on_delete=models.CASCADE,
        help_text="Select the patient who completed this patient-reported outcome assessment"
    )
    instrument = models.ForeignKey(
        ProInstrument, 
        on_delete=models.CASCADE,
        help_text="Select the assessment instrument or questionnaire that was used (e.g., 'EORTC QLQ-C30', 'FACT-G')"
    )
    domain = models.ForeignKey(
        ProDomain, 
        on_delete=models.CASCADE,
        help_text="Select the specific domain or category of the assessment (e.g., 'Physical Function', 'Emotional Well-being')"
    )
    question = models.ForeignKey(
        ProQuestion, 
        on_delete=models.CASCADE,
        help_text="Select the specific question from the assessment that was answered"
    )
    pro_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this assessment was completed (format: YYYY-MM-DD)"
    )
    pro_answer = models.TextField(
        null=True, 
        blank=True,
        help_text="Enter the patient's response to this specific question"
    )
    pro_score = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Enter the numerical score for this response, if applicable (e.g., on a scale of 0-10)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.patient_reported_outcome.chavi_pro_id}"

    class Meta:
        verbose_name_plural="Patient Reported Outcomes"
        db_table="patient_reported_outcome"    

class PatientOutcome(models.Model):
    ''' This is the table which will store information on the outcome of the patients'''
    chavi_pt_outcome_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE)
    patient_status = models.ForeignKey('LookupOutcome', on_delete=models.PROTECT,
    help_text="Select the patients last known status")
    date_of_death = models.DateField(null=True, blank=True,
    help_text="Enter the date of death, if applicable")
    primary_cause_of_death = models.ForeignKey('LookupICDCode', on_delete=models.PROTECT,
                                             related_name='primary_cause', null=True, blank=True,
                                             help_text="Select the primary cause of death, if applicable")
    secondary_cause_of_death = models.ForeignKey('LookupICDCode', on_delete=models.PROTECT,
                                               related_name='secondary_cause', null=True, blank=True,
                                               help_text="Select the secondary cause of death, if applicable")
    tertiary_cause_of_death = models.ForeignKey('LookupICDCode', on_delete=models.PROTECT,
                                              related_name='tertiary_cause', null=True, blank=True,
                                              help_text="Select the tertiary cause of death, if applicable")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.patient_outcome.chavi_pt_outcome_id}"

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
        'LookupICDCode', 
        on_delete=models.PROTECT,
        help_text="Select the ICD code that best describes this comorbidity"
    )
    date_of_comorbidity_diagnosis = models.DateField(
        null=True, 
        blank=True,
        help_text="Enter the date when this comorbidity was first diagnosed (format: YYYY-MM-DD)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Indicate whether this comorbidity is currently active (check for Yes, uncheck for No)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.comorbidity_type.chavi_comorbidity_id}"

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
        'LookupStagingSystem', 
        on_delete=models.PROTECT,
        help_text="Select the staging system used (e.g., 'TNM 8th Edition', 'FIGO')"
    )
    stage_type = models.CharField(
        max_length=255, 
        null=True, 
        blank=True,
        help_text="Enter the type of staging (e.g., 'Clinical', 'Pathological', 'Post-therapy')"
    )
    t_stage_prefix = models.ForeignKey(
        'LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='t_stage_prefix',
        null=True, 
        blank=True,
        help_text="Select the prefix modifiers for the T stage (e.g., 'c' for clinical, 'p' for pathological)"
    )
    t_stage = models.ForeignKey(
        'LookupAJCCTStageDescriptor',
        on_delete=models.PROTECT,
        related_name = 't_stage',
        null=True, 
        blank=True,
        help_text="Select the T stage describing the primary tumor (e.g., 'T1', 'T2', 'T3', 'T4')"
    )
    t_stage_suffix = models.ForeignKey(
        'LookupAJCCStageSuffix',
        on_delete=models.PROTECT,
        related_name='t_stage_suffix',             
        null=True, 
        blank=True,
        help_text="Enter any suffix modifiers for the T stage (e.g., 'a', 'b', 'c')"
    )
    n_stage_prefix = models.ForeignKey(
        'LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='n_stage_prefix',        
        null=True, 
        blank=True,   
        help_text="Select any prefix modifiers for the N stage (e.g., 'c' for clinical, 'p' for pathological)"
    )
    n_stage = models.ForeignKey(
        'LookupAJCCNStageDescriptor',
        on_delete=models.PROTECT,
        related_name='n_stage',
        null=True, 
        blank=True,
        help_text="Enter the N stage describing lymph node involvement (e.g., 'N0', 'N1', 'N2', 'N3')"
    )
    n_stage_suffix = models.ForeignKey(
        'LookupAJCCStageSuffix',
        on_delete=models.PROTECT,
        related_name='n_stage_suffix',         
        null=True, 
        blank=True,  
        help_text="Select any suffix modifiers for the N stage (e.g., 'a', 'b', 'c')"
    ) 
    m_stage_prefix = models.ForeignKey(
        'LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='m_stage_prefix',        
        null=True, 
        blank=True,        
        help_text="Select any prefix modifiers for the M stage (e.g., 'c' for clinical, 'p' for pathological)"
    )
    m_stage = models.ForeignKey(
        'LookupAJCCMStageDescriptor',
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="Enter the M stage describing distant metastasis (e.g., 'M0', 'M1', 'M1a', 'M1b')"
    )
    m_stage_suffix = models.ForeignKey(
        'LookupAJCCStageSuffix',
        related_name='m_stage_suffix',        
        on_delete=models.PROTECT,
        null=True, 
        blank=True,  
        help_text="Enter any suffix modifiers for the M stage (e.g., 'a', 'b', 'c')"
    ) 
    overall_stage = models.ForeignKey(
        'LookupStageDescriptor',
        on_delete=models.PROTECT,
        related_name= 'overall_stage',
        null=True, 
        blank=True,
        help_text="Enter the overall stage grouping (e.g., 'Stage I', 'Stage II', 'Stage III', 'Stage IV')"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return self.chavi_stage_information_id

    class Meta:
        verbose_name_plural="Stage Informations"
        db_table='stage_information'    
    
class DICOMStudyProject(models.Model):
    dicom_study = models.ForeignKey(DICOMStudy, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name="Project for DICOM Study"
        verbose_name_plural="Projects for DICOM Study"
        constraints = [
            models.UniqueConstraint(
                fields=['dicom_study', 'project'],
                name='unique_dicom_study_project'
            )
        ]

