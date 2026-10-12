from django.db import models
from django.db.models.functions import Substr, Concat
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator, ValidationError
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
    center_name = models.CharField(max_length=255, help_text="Full official name of the hospital/institution where this CHAVI client is installed.")

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
    chavi_project_id = models.CharField(max_length=255,unique=True, primary_key=True,help_text="CHAVI-assigned unique identifier for the project (provided by the CHAVI team; not derived from local documents).")
    project_name = models.CharField(max_length=600,help_text="Name of the research project/study, as named in the protocol or IRB approval.")
    center = models.ForeignKey(SiteConfiguration, on_delete=models.CASCADE,  null=True, blank=True,default=get_default_site, related_name="project_center")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.project_name

    class Meta:
        verbose_name_plural = "Projects"
        db_table="project"

# Core Patient Models
def _make_canonical_id(patient_id):
    """Strip non-alphanumeric characters and uppercase a patient ID.
    e.g. 'MR/25/004771' -> 'MR25004771', '25_004771' -> '25004771'
    Used to normalise IDs before fuzzy/canonical matching so that
    format variants from different systems resolve to the same string.
    """
    import re
    return re.sub(r'[^a-zA-Z0-9]', '', patient_id).upper()


class Patient(DateValidationMixin, models.Model):
    '''
    A patient in the document: demographics and patient-level data reported in
    the clinical document. Record granularity: one record per patient; when
    the document covers more than one patient, return one record per patient
    in the order the patients appear. 
    '''
    ''' This is the main patient model. Only patient ID and gender data are collected in this table.'''
    center = models.ForeignKey(SiteConfiguration, 
    on_delete=models.CASCADE, 
    default=get_default_site,
    related_name="center")
    chavi_consent = models.BooleanField(
        null=True,
        blank=True,
        default=False,
        help_text="True if the patient (or guardian) gave documented consent for CHAVI data use. Leave blank if consent is not documented."
    )
    date_chavi_consent = models.DateField(
        null=True,
        blank=True,
        help_text="Date written consent was obtained. Set when consent is True. (DD/MM/YYYY)" 
    )
    patient_id = models.CharField(
        max_length=255, 
        primary_key=True,
        help_text="The patient's unique identifier at this institution — usually the Medical Record Number. In records it may appear as 'MRN', 'MR No', 'hospital number', or 'admission number'. Must match the identifier used on imaging and reports for the same patient."
    )
    canonical_patient_id = models.CharField(
        max_length=255, db_index=True, blank=True, default='', editable=False,
        help_text="Normalised patient_id for canonical DICOM matching (set automatically on save).",
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
        help_text="Patient's gender as documented (Male, Female, Transgender, Non-Binary). May be recorded as 'sex'. Leave blank only if unknown."
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text="Patient's date of birth. Appears as 'DOB' in records. (DD/MM/YYYY)"
    )
    date_of_registration = models.DateField(
        null=True,
        blank=True,
        help_text="Date the patient was first registered/admitted at this institution; may appear as 'registration date' or 'first visit date'. Cannot be earlier than date of birth."
    )
    patient_project = models.ManyToManyField(
        'Project',
        blank = True, 
        related_name="patient_project",
        help_text="Project(s) the patient is enrolled in. A patient may be in more than one."
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

    def save(self, *args, **kwargs):
        self.canonical_patient_id = _make_canonical_id(self.patient_id)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {'canonical_patient_id'}
        super().save(*args, **kwargs)

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
        help_text="ZIP archive of DICOM studies belonging to ONE patient; multiple studies per archive are allowed. (.zip only)"
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

class StudyTypeSource(models.TextChoices):
    AUTO = 'AUTO', 'Auto'
    MANUAL = 'MANUAL', 'Manual'


# DICOM Related Models
class DICOMStudy(models.Model):
    ''' This is a table that stores information on the different DICOM studies that the patient has undergone. '''
    patient = models.ForeignKey(
        Patient, 
        on_delete=models.CASCADE,
        related_name='patient',
        help_text="Patient this imaging study belongs to."
    )
    study_instance_uid= models.CharField(
        max_length=255,
        unique = True,
        primary_key=True,
        help_text="DICOM tag (0020,000D) Study Instance UID — globally unique identifier of this imaging study. Copy it exactly as written; never invent or truncate it."
    )
    study_date = models.DateField(
        null = True,
        blank = True,
        help_text="Date the imaging study was performed (DICOM tag (0008,0020) Study Date). (DD/MM/YYYY)"
    )
    study_description = models.CharField(
        max_length = 255,
        null = True,
        blank = True, 
        help_text = "Free-text study description from DICOM metadata (tag (0008,103E)); often names the body region and exam, e.g. 'CT NECK 3 PHASE'."
    )
    study_type = models.CharField(
        max_length = 255,
        choices = StudyTypeChoices.choices,
        null = True,
        blank = True,
        help_text = "Where the study sits in the treatment timeline: pre-treatment diagnostic, planning, on-treatment verification, planning for adaptive treatment, post-treatment response, therapy delivery, therapy QA, post-treatment diagnostic, or other."
    )

    study_type_source = models.CharField(
        max_length=10,
        choices=StudyTypeSource.choices,
        default=StudyTypeSource.AUTO,
        help_text='AUTO = set by classification rules; MANUAL = user override, never overwritten.'
    )

    study_modalities = models.CharField(
        max_length = 255,
        null = True,
        blank = True,
        help_text = "DICOM modality codes contained in the study (e.g. CT, MR, PT, RTDOSE, US); comma-separated if several."
    )
    series_descriptions = models.TextField(
        null = True,
        blank = True,
        help_text = "Descriptions of all series in the study (DICOM tag (0008,103E) per series), comma-separated."
    )
    folder_path = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, auto_classified=False, update_fields=None, **kwargs):
        if auto_classified:
            self.study_type_source = StudyTypeSource.AUTO
        elif self.pk and update_fields is not None and 'study_type' in update_fields and 'study_type_source' not in update_fields:
            self.study_type_source = StudyTypeSource.MANUAL
        elif self.pk and update_fields is None:
            old_type = DICOMStudy.objects.filter(pk=self.pk).values_list('study_type', flat=True).first()
            if old_type is not None and old_type != self.study_type:
                self.study_type_source = StudyTypeSource.MANUAL
        super().save(*args, update_fields=update_fields, **kwargs)

    def __str__(self):
        return (
            f'{self.patient.patient_id} {self.study_date} \n'
            f'Study: {self.study_description} \n'
            f'Series: {self.series_descriptions}'
        )
        
        #f"{self.patient.patient_id} {self.study_description} {self.series_descriptions} (Date: {self.study_date})"

    class Meta:
        verbose_name_plural = "DICOM Studies"


class StudyTypeRule(models.Model):
    """A configurable rule used to set DICOMStudy.study_type automatically."""

    class Operator(models.TextChoices):
        CONTAINS = 'contains', 'contains (case-insensitive)'
        EXACT = 'exact', 'exact'
        REGEX = 'regex', 'matches regex'

    class ReferenceEvent(models.TextChoices):
        NONE = 'NONE', 'None'
        DIAGNOSIS_DATE = 'DIAGNOSIS_DATE', 'Diagnosis date'
        RADIOTHERAPY_START = 'RADIOTHERAPY_START', 'Radiotherapy start'
        RADIOTHERAPY_END = 'RADIOTHERAPY_END', 'Radiotherapy end'
        SYSTEMIC_THERAPY_START = 'SYSTEMIC_THERAPY_START', 'Systemic therapy start'
        SYSTEMIC_THERAPY_END = 'SYSTEMIC_THERAPY_END', 'Systemic therapy end'

    study_type = models.CharField(max_length=50, choices=StudyTypeChoices.choices)
    priority = models.PositiveIntegerField(
        default=100,
        help_text='Rules are evaluated in ascending priority order; the first match wins.'
    )
    enabled = models.BooleanField(default=True)

    match_modality = models.CharField(max_length=255, blank=True, default='', help_text="Study/modality/series-description text this rule matches.")
    modality_operator = models.CharField(max_length=20, choices=Operator.choices, default=Operator.CONTAINS)

    match_study_description = models.CharField(max_length=255, blank=True, default='', help_text="Study/modality/series-description text this rule matches.")
    study_description_operator = models.CharField(max_length=20, choices=Operator.choices, default=Operator.CONTAINS)

    match_series_description = models.CharField(max_length=255, blank=True, default='', help_text="Study/modality/series-description text this rule matches.")
    series_description_operator = models.CharField(max_length=20, choices=Operator.choices, default=Operator.CONTAINS)

    reference_event = models.CharField(
        max_length=40, choices=ReferenceEvent.choices, default=ReferenceEvent.NONE,
        help_text='Optional clinical date used for a date-window check.'
    )
    date_window_start_days = models.IntegerField(default=-7, help_text="Days before/after the reference event for which the rule may fire (negative = before).")
    date_window_end_days = models.IntegerField(default=7, help_text="Days before/after the reference event for which the rule may fire (negative = before).")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'created_at']
        verbose_name = 'Study type rule'
        verbose_name_plural = 'Study type rules'

    def __str__(self):
        return f'{self.priority}: {self.study_type} ({"enabled" if self.enabled else "disabled"})'


# Clinical Data Models
class Diagnosis(models.Model):
    '''
    The clinical diagnosis of a patient's disease: site, side, modality,
    dates and related diagnosis-level data. Record granularity: one record
    per distinct diagnosis the document describes; most reports describe
    exactly one, so add further records only when the document clearly lists
    additional diagnoses.
    '''
    ''' This is a table which stores the diagnosis of the patient. The diagnosis is a key table which will have links to treatment and pathology.'''
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE,
    help_text="Patient to whom this diagnosis belongs")
    chavi_diagnosis_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cancer_system = models.ForeignKey('lookup.LookupMajorCancerCategory', on_delete=models.PROTECT,related_name='diagnosis_major_cancer_category',
                                              help_text="Major cancer system/organ the cancer belongs to (e.g. breast, lung, cervix).")
    diagnosis = models.ForeignKey('lookup.LookupICDCode',related_name= 'diagnosis_code', on_delete=models.PROTECT,
    help_text="ICD-11 code for the diagnosed cancer. Create a separate Diagnosis record per distinct cancer.")
    diagnosis_date = models.DateField(null=True, blank=True,
    help_text="Date the diagnosis was made. Prefer the pathological confirmation (biopsy) date; if only a clinical diagnosis exists, use the first definitive clinical assessment. (DD/MM/YYYY)")
    presentation_type = models.ForeignKey('lookup.LookupPresentation', on_delete=models.PROTECT,
    help_text="How the disease presented: new primary, recurrence, or metastasis.")
    cancer_site = models.ForeignKey('lookup.LookupFMACode', on_delete=models.PROTECT,
    help_text="Anatomical location of the cancer (FMA code) — first-diagnosis site, or recurrence/metastasis site.")
    cancer_side = models.ForeignKey('lookup.LookupLaterality', on_delete=models.PROTECT,
    help_text="Side of the body where the cancer is (left/right/bilateral/midline).")
    diagnostic_modality = models.ForeignKey('lookup.LookupDiagnosticModality',on_delete=models.PROTECT,null=True, blank=True,
    help_text="Method used to establish the diagnosis (biopsy, cytology, FNA, imaging, endoscopy…).")
    study_instance_uid = models.ManyToManyField('DICOMStudy', blank = True, help_text="Imaging studies that supported or confirmed this diagnosis.")
    diagnosis_project = models.ManyToManyField('Project', blank = True, help_text="CHAVI project(s) this diagnosis belongs to.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient.patient_id} - {self.cancer_system} - {self.presentation_type}"

    class Meta:
        verbose_name_plural="Diagnoses"
        db_table = 'diagnosis'    

class Outcome(models.Model):
    '''
    Outcome events of a diagnosis: outcome type, date and status. Record
    granularity: one record per distinct outcome event described.
    '''
    '''This table stores information related to the outcome of the cancer treatment for the disease. Note that the patient outcome table is separate.'''
    chavi_outcome_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE, help_text="Disease (diagnosis record) for which this treatment outcome was assessed.")
    date_outcome_assessed = models.DateField(null=True, blank=True,
    help_text = "Date the outcome was assessed, documented, or confirmed (e.g. imaging review date). (DD/MM/YYYY)")
    outcome_type = models.ForeignKey('lookup.LookupOutcomeType', on_delete=models.PROTECT,
    help_text = "Outcome category observed for this disease. Add a new Outcome record for each later assessment.")
    study_instance_uid = models.ManyToManyField('DICOMStudy',blank = True, related_name = "outcome_dicom_study",help_text = "Imaging studies on which this outcome was assessed.")
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
    NASAL_ENDOSCOPY = 'NASAL_ENDOSCOPY', 'NASAL_ENDOSCOPY'
    LARYNGOSCOPY = 'LARYNGOSCOPY', 'LARYNGOSCOPY'
    UPPER_GI_ENDOSCOPY = 'UPPER_GI_ENDOSCOPY', 'UPPER_GI_ENDOSCOPY'
    SIGMOIDOSCOPY = 'SIGMOIDOSCOPY', 'SIGMOIDOSCOPY'
    PROCTOSCOPY = 'PROCTOSCOPY', 'PROCTOSCOPY'
    ERCP = 'ERCP', 'ERCP'
    CHOLANGIOGRAPHY = 'CHOLANGIOGRAPHY', 'CHOLANGIOGRAPHY'
    OTOSCOPY = 'OTOSCOPY', 'OTOSCOPY'
    COLONOSCOPY = 'COLONOSCOPY', 'COLONOSCOPY'
    CAPSULE_ENDOSCOPY = 'CAPSULE_ENDOSCOPY', 'CAPSULE_ENDOSCOPY'
    COLPOSCOPY = 'COLPOSCOPY', 'COLPOSCOPY'
    CYSTOSCOPY = 'CYSTOSCOPY', 'CYSTOSCOPY'
    URETEROSCOPY = 'URETEROSCOPY', 'URETEROSCOPY'
    LAPAROSCOPY = 'LAPAROSCOPY', 'LAPAROSCOPY'
    CLINICAL = "Clinical", 'Clinical'
    XRAY = "X-ray", 'X-ray'
    OTHER = "Other", 'Other'

class Lesion(models.Model):
    '''
    Anatomical lesions of a diagnosis: site, type, laterality, size and
    volume. Record granularity: one record per distinct lesion described; a
    document may describe several lesions and each gets its own record.
    '''
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
        help_text="Date the lesion was assessed/measured (report date of the imaging or exam where it was described). (DD/MM/YYYY)"
    )
    lesion_site = models.ForeignKey(
        'lookup.LookupFMACode', 
        on_delete=models.PROTECT,
        help_text="Anatomical location of the lesion (FMA code), e.g. left breast, right lung, liver."
    )
    lesion_type = models.ForeignKey(
        'lookup.LookupLesionType', 
        on_delete=models.PROTECT,
        help_text="Category of the lesion: primary/gross tumor, nodal disease, or distant metastasis."
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
        help_text="First dimension of the lesion as reported (when a report gives 'a × b × c' or 'L × W × H', take the first value). Numeric, in lesion_size_unit (usually mm). Blank if no size given."
    )
    lesion_size_y_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Second reported dimension (middle value of 'a × b × c'). Blank if the report gives fewer than two dimensions."
    )
    lesion_size_z_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Third reported dimension (last value of 'a × b × c'). Blank if not reported."
    )
    lesion_size_unit = models.ForeignKey(
        'lookup.LookupSizeUnits', 
        related_name='lesion_size_unit',
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        help_text="Unit of the three size fields (mm, cm). Reports usually use mm."
    )
    lesion_volume = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Volume of the lesion if stated in the report (e.g. 'volume 12.3 cc'). In lesion_volume_unit. Blank if not stated."
    )
    lesion_volume_unit = models.ForeignKey(
        'lookup.LookupVolumeUnits', 
        related_name='lesion_volume_unit',
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        help_text="Unit of the lesion volume (e.g. mm³, cm³/cc)."
    )
    lesion_detection_modality = models.CharField(
        max_length=255,
        choices=ModalityChoices.choices,
        null=True,
        blank=True,
        help_text="Modality that detected or describes this lesion (CT, MRI, PET, US, endoscopy, clinical exam…)."
    )
    lesion_suv_max = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Maximum standardized uptake value (SUVmax) of the lesion on PET. Unitless."
    )
    study_instance_uid = models.ManyToManyField('DICOMStudy', blank = True, related_name = 'lesion_dicom_study',help_text = "Imaging study/studies in which this lesion was detected or assessed.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lesion {self.chavi_lesion_id}"

    class Meta:
        verbose_name_plural = "Lesions"
        db_table="lesion"

class LesionResponse(models.Model):
    '''
    Assessment of a lesion's response to treatment, including residual size
    and volume. Record granularity: one record per distinct response
    assessment described for a lesion; a baseline assessment and a
    post-treatment assessment of the same lesion are separate records.
    '''
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
        help_text="The date when the lesion's response to treatment was evaluated. (DD/MM/YYYY)"
    )
    lesion_response = models.ForeignKey(
        'lookup.LookupResponseType', 
        on_delete=models.CASCADE,
        help_text="Response category at this assessment (e.g. complete response, partial response, stable disease, progression)."
    )
    residual_lesion_size_x_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="First dimension of the REMAINING disease at this assessment (first value of 'a × b × c'). In residual_lesion_size_unit. Blank if no residual disease or no size given."
    )
    residual_lesion_size_y_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Second dimension of the remaining disease at this assessment (middle value of 'a × b × c'). In residual_lesion_size_unit. Blank if the report gives fewer than two dimensions."
    )
    residual_lesion_size_z_axis = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Third dimension of the remaining disease at this assessment (last value of 'a × b × c'). In residual_lesion_size_unit. Blank if not reported."
    )
    residual_lesion_size_unit = models.ForeignKey(
        'lookup.LookupSizeUnits',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Unit of the residual size fields (mm, cm)."
    )
    residual_lesion_volume = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Volume of remaining disease at this assessment, in residual_lesion_volume_unit. Blank if none."
    )
    residual_lesion_volume_unit = models.ForeignKey(
        'lookup.LookupVolumeUnits',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Unit of the residual volume (mm³, cm³/cc)."
    )

    lesion_response_suv_max = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="SUVmax of the residual lesion at the response assessment on PET. Blank if no residual uptake reported.",
    )
    lesion_response_modality = models.CharField(
        max_length=255,
        choices=ModalityChoices.choices,
        null=True,
        blank=True,
        help_text="Modality used to assess the response (CT, MRI, PET…)."
    )
    study_instance_uid = models.ManyToManyField(
        'DICOMStudy', blank = True, 
        related_name = 'lesion_response_dicom_study', 
        help_text="Imaging study used for this response assessment."
    )    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lesion Response {self.chavi_lesion_response_id}"

    class Meta:
        verbose_name_plural="Lesion Responses"
        db_table="lesion_response"

class Symptom(models.Model):
    '''
    Symptoms experienced by a patient, with severity where stated. Record
    granularity: one record per distinct symptom described.
    '''
    ''' This table will store information on the symptoms for the patient.'''
    chavi_symptom_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, help_text="Patient who has this symptom.")
    symptom = models.ForeignKey('lookup.LookupSymptoms', on_delete=models.PROTECT, help_text="The symptom recorded (from the symptom list), e.g. pain, dyspnoea, weight loss.")
    date_onset = models.DateField(null=True, blank=True, help_text="Date the symptom first started. If not stated but assessment date + duration are given, it is derived as assessment date minus duration. (DD/MM/YYYY)")
    date_symptom_assessment = models.DateField(null=True, blank=True, help_text="Date the symptom was assessed/documented. (DD/MM/YYYY)")
    duration_of_symptom = models.PositiveIntegerField(null=True, blank=True, help_text="How long the symptom had been present before assessment, in whole months.")
    date_resolution = models.DateField(null=True, blank=True, help_text="Date the symptom resolved or improved, if applicable.")
    severity = models.ForeignKey('lookup.LookupSeverity', on_delete=models.PROTECT, null=True, blank=True, help_text="Severity/grade of the symptom.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def prepare_for_save(self):
        # Calculate diagnosis date if we have both assessment date and duration
        if self.date_symptom_assessment and self.duration_of_symptom:
            # Subtract months from assessment date to get diagnosis date
            self.date_onset = self.date_symptom_assessment - relativedelta(months=self.duration_of_symptom)

    def save(self, *args, **kwargs):
        self.prepare_for_save()
        super().save(*args, **kwargs)
    def __str__(self):
        return f"{self.chavi_symptom_id}"
    
    class Meta:
        verbose_name_plural = "Symptoms"
        db_table = "symptom"

class GermlineGenomicAlterations(models.Model):
    ''' This table will store information on the germline genomic alterations for the patient.'''
    chavi_germline_genomic_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, help_text="Patient who underwent this germline (inherited) genetic test.")
    date_test = models.DateField(null=True, blank=True, help_text="Date the germline genetic test was performed. (DD/MM/YYYY)")
    cosmic_gene_name = models.ForeignKey('lookup.LookupGene', on_delete=models.PROTECT, help_text="Gene in which the germline variant was found (COSMIC gene nomenclature), e.g. BRCA1, BRCA2.")
    reference_sequence = models.CharField(max_length=255, null=True, blank=True, help_text="Reference transcript identifier (e.g. NM_007294.3).")
    protein_modification = models.CharField(max_length=255, null=True, blank=True, help_text="Protein-level change (e.g. p.R42Q, c.123G>A).")
    variant_type = models.CharField(max_length=255, null=True, blank=True, help_text="Variant type (e.g. missense, nonsense, frameshift, deletion, insertion, splice-site).")
    allele_frequency = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Variant allele frequency as a decimal (0.05 = 5%).")
    read_depth = models.IntegerField(null=True, blank=True, help_text="Sequencing read depth (coverage) at the variant.")
    clinical_significance = models.ForeignKey('lookup.LookupClinicalSignificance', on_delete=models.PROTECT, related_name='germline_genomic_clinical_significance',null = True, blank = True, help_text="Clinical significance of the variant (e.g. pathogenic, VUS, benign).")
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
    PUNCH_BIOPSY = "Punch Biopsy", 'Punch Biopsy'
    EXCISION_BIOPSY = "Excision Biopsy", 'Excision Biopsy'
    INCISIONAL_BIOPSY = "Incisional Biopsy", 'Incisional Biopsy'
    SURGICAL_RESECTION = "Surgical Resection", 'Surgical Resection'
    FINE_NEEDLE_ASPIRATION = "Fine Needle Aspiration", 'Fine Needle Aspiration'
    LIQUID_BIOPSY = "Liquid Biopsy", 'Liquid Biopsy'
    OTHER = "Other", 'Other'

class Pathology(models.Model):
    '''
        Histopathology findings for a diagnosis: gross and microscopic description, tumor dimensions, margins, lymph-node findings. Record granularity: one record per pathology report. The specimens listed in a report (for example a primary resection specimen plus lymph-node specimens from the same case even if bilateral neck node dissection is performed) are parts of the SAME record, not separate records - combine every finding of the report into that one record. Microscopic descriptions such as histology, invasion and margins describe the report as a whole. 
    There can be exceptions where the patient has undergone surgery of two sites at the same time - e.g. carcinoma breast (mastectomy) and carcinoma thyroid. In these case patient will have two diagnoses. Similarly when the patient has had surgery on both sides breast they will have two diagnoses - right and left breast. Note that recurrence disease is usually specified clearly. 
    When lymph node sampling, lymph node dissection or sentinel lymph node biopsy is done the total lymph node count may need to be calculated as it may not be explicitly specified or specified in places. For example total sentinel lymph nodes and total nodes in dissection. This will be true for involved nodes, nodes with macro/micro metastases / isolated tumor cells. Total number of involved nodes is usually nodes with macrometastases + micrometastases. If bilateral nodal dissection is there then involvement of both sides nodes needs to be added. 
    Tumour size and margins may also be inconsistently specified - for example size in gross or microscopic description. Prefer microscopic size where ever possible. Go through both sections carefully. Always review comments and addendum if available they often contain useful information about the pathology.
    Pathology reports may have several dates. Prefer the date of authorisation or date of report if it is available
    '''
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
        help_text="Date of the pathology report. Prefer the report authorization/report date; if the report date is unavailable, use the specimen collection date. (DD/MM/YYYY)"
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
        help_text="Largest tumor dimension from the pathology report. Unit in tumor_dimesion_unit (usually cm)."
    )
    additional_tumor_dimension_1 = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Second tumor dimension as reported. Unit in tumor_dimesion_unit."
    )
    additional_tumor_dimension_2 = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Third tumor dimension as reported. Unit in tumor_dimesion_unit."
    )
    tumor_dimesion_unit = models.ForeignKey(
        'lookup.LookupSizeUnits',
        on_delete=models.PROTECT,
        related_name='pathology_tumor_dimesion_unit',
        null=True, 
        blank=True,
        help_text="Unit of the three tumor dimension fields (cm, mm)."
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
        help_text="Presence or absence of lymphovascular or lymphovascular space invasion (LVI or LVSI)."
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
        help_text="Presence or absence of dermal lymphatic invasion."
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
        help_text="0–100, percent of the specimen that is necrotic. If a range is provided, enter the max value."
    )
    mitotic_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=positive_decimal_validator,
        help_text="Mitotic count per 10 high-power fields (or per 2 mm², as reported)."
    )
    margin_status = models.ForeignKey(
        'lookup.LookupMarginStatus',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pathology_margin_status',
        help_text="Status of the resection margin in the specimen."
    )
    closest_margin_distance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=positive_decimal_validator,
        help_text="Distance to the closest margin of the specimen, in closest_margin_distance_unit (usually mm)."
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
        help_text="Treatment effect seen in the specimen (e.g. regression/necrosis after neoadjuvant therapy).",
        related_name='pathology_treatment_effect'
    )
    primary_gleason_grade = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Primary Gleason pattern (1–5); prostate cancer only."
    )
    secondary_gleason_grade = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Secondary Gleason pattern (1–5); prostate cancer only."
    )
    lymph_nodes_removed = models.BooleanField(
        null=True, 
        blank=True,
        help_text="Whether lymph nodes were examined in the specimen (True/False)."
    )
    lymph_nodes_in_specimen = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Total lymph nodes examined."
    )
    lymph_node_extracapsular_extension = models.BooleanField(null=True, blank=True,help_text='Whether any lymph node showed extracapsular extension.')
    number_of_uninvolved_nodes = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Number of negative (tumor-free) or uninvolved lymph nodes. Sometimes written as lymph node show reactive hyperplasia or granulolomatous lymphadenitis."
    )
    number_of_nodes_with_macrometastases = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Number of lymph nodes with macrometastases (>2 mm). If the metastasis dimension is unavailable, count as macrometastases."
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
    '''
    Immunohistochemistry (IHC) staining results for a pathology specimen:
    marker, staining pattern and scoring and other parameters. Record granularity: one record
    per marker (protein) reported; when one report covers several markers,
    each marker gets its own record and all of them belong to the same
    pathology record.  Note that multiple genes may be reported in the same report.
    '''
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
        help_text="Date the IHC test was performed. This can be the date of pathology if the dates for IHC are not explicitly provided. (DD/MM/YYYY)"
    )
    protein_name = models.ForeignKey(
        'lookup.LookupIHCAntibody', 
        on_delete=models.CASCADE,
        help_text="Antibody/target marker tested (e.g. ER, PR, HER2, Ki-67, PD-L1, p53)."
    )
    ihc_result = models.ForeignKey(
        'lookup.LookupIHCResult',
        on_delete=models.PROTECT,
        related_name='ihc_result',
        null=True, 
        blank=True,
        help_text="Overall qualitative result of the stain (e.g. positive, negative, equivocal)."
    )
    percentage_positive_tumor_cells = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=percentage_validator,
        help_text="Percentage of tumor cells with positive staining (0–100)."
    )
    percentage_positive_immune_cells = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=percentage_validator,
        help_text="Percentage of (tumor-infiltrating) immune cells with positive staining (0–100)."
    )
    tumor_cell_staining_intensity = models.ForeignKey(
        'lookup.LookupIHCStainingIntensity',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Staining intensity grade of the tumor cells (e.g. 0–3)."
    )
    allred_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Allred score (0–8): staining intensity score plus percentage-score category."
    )
    cps_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Combined Positive Score (CPS): stained tumor and immune cells per 100 tumor cells.")
    tps_score = models.DecimalField(
        null=True,
        max_digits=5,
        decimal_places=2,
        blank=True,
        validators=percentage_validator,
        help_text="Tumor Proportion Score (TPS): percent of tumor cells with positive membrane staining (0–100).")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.pathology.diagnosis.patient.patient_id} - {self.protein_name}"

    class Meta:
        verbose_name_plural="Immunohistochemistries"
        db_table="immunohistochemistry"

class Cytogenetics(models.Model):
    '''
    Cytogenetic findings for a pathology specimen: gene and cytogenetic
    abnormality with result. Record granularity: one record per
    gene/abnormality the document describes. Note that multiple genes may be reported in the same report.
    '''
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
        help_text="Date the cytogenetics test was performed. (DD/MM/YYYY)"
    )
    gene = models.ForeignKey(
        'lookup.LookupGene', 
        on_delete=models.PROTECT,
        help_text="Gene tested."
    )
    cytogenetic_abnormality = models.ForeignKey(
        'lookup.LookupCytogeneticAbnormality',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Type of abnormality found (e.g. translocation, amplification, deletion, mutation)."
    )
    cytogenetic_result = models.ForeignKey(
        'lookup.LookupIHCResult',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='cytogenetics_result',
        help_text="Result of the test (e.g. positive, negative, not detected)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.chavi_cytogenetics_id}"
    
    class Meta:
        verbose_name_plural="Cytogenetics"
        db_table="cytogenetics"

class SomaticGenomicAlterations(models.Model):  
    '''
    Somatic genomic alterations found in a pathology specimen: gene,
    alteration type and result. Record granularity: one record per
    alteration (gene/variant) the document describes.
    '''
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
        help_text="Date the genomic testing was performed. (DD/MM/YYYY)"
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
        help_text="Variant allele frequency as a decimal (0.45 = 45%)."
    )
    read_depth = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Sequencing read depth (coverage) at the variant."
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
    '''
    Gene expression measurements for a pathology specimen: gene, expression
    value and units. Record granularity: one record per gene measured.
    '''
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
        help_text="Date the gene expression test was performed. (DD/MM/YYYY)"
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
        help_text="Measured expression level of the gene (e.g. mRNA amount, FISH count, score)."
    )
    expression_units = models.ForeignKey(
        'lookup.LookupExpressionUnits',
        on_delete=models.PROTECT,
        help_text="Unit of the expression value (e.g. fold-change, TPM, arbitrary units, % positive cells)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.gene.code} - {self.expression_value}"   
    
    class Meta:
        verbose_name_plural="Gene Expression Data"
        db_table="gene_expression_data"
    
class EpigeneticData(models.Model):
    '''
    Epigenetic findings for a pathology specimen: gene/locus, abnormality
    type and result. Record granularity: one record per gene/locus the
    document describes.
    '''
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
        help_text="Date the epigenetic test was performed. (DD/MM/YYYY)"
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
        help_text="Type of epigenetic change (e.g. promoter hypermethylation, hypomethylation)."
    )
    epigenetic_result = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Result of the epigenetic test (e.g. 'hypermethylated', positive/negative)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.gene.code} - {self.epigenetic_result}"
    
    class Meta:
        verbose_name_plural="Epigenetic Data"
        db_table="epigenetic_data"
    
class OtherTreatment(DateValidationMixin, models.Model):
    '''
    Treatment other than systemic therapy or radiotherapy (for example
    interventional or local treatments), with its intent. Record granularity:
    one record per distinct other-treatment event described.
    '''
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
        help_text="Name or description of the treatment (e.g. drug name, 'immunotherapy', 'hormonal therapy')."
    )
    treatment_start_date = models.DateField(
        null = True,
        blank = True,
        help_text = "Start date of the treatment. (DD/MM/YYYY)"
    )
    treatment_end_date = models.DateField(
        null = True,
        blank = True,
        help_text = "End date of the treatment. Blank if still ongoing. (DD/MM/YYYY)"
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
    '''
    A radiotherapy course for a diagnosis: modality, dose, technique, side,
    intent and fractions. Record granularity: one record per distinct
    radiotherapy course the document describes.
    '''
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
        help_text="Primary course or boost course."
    )    
    radiotherapy_modality = models.ForeignKey(
        'lookup.LookupRadiotherapyModality',
        on_delete=models.PROTECT,
        help_text="Radiation modality/technology (e.g. 3D-CRT, IMRT, VMAT, brachytherapy, proton).",
        null=True,
        blank=True,
        related_name="radiotherapy_modality"
    )
    reirradiation = models.BooleanField(
        null=True,
        blank=True,
        help_text="True if this is re-irradiation of a previously irradiated region."
    )
    total_dose = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Total dose for the whole course. Unit in radiation_dose_units (Gy or cGy)."
    )
    total_fractions = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Total number of fractions in the course."
    )
    simultaneous_integrated_boost = models.BooleanField(
        null=True,
        blank=True,
        help_text="True if a simultaneous integrated boost (SIB) was part of this course."
    )
    simultaneous_integrated_boost_dose = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="SIB dose. Unit in radiation_dose_units."
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
        help_text="Manufacturer/model of the treatment machine (e.g. 'Varian TrueBeam')."
    )
    radiotherapy_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date the radiotherapy course was started. (DD/MM/YYYY)"
    )
    radiotherapy_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date the radiotherapy course ended. Blank if ongoing. (DD/MM/YYYY)"
    )
    study_instance_uid = models.ManyToManyField(
        'DICOMStudy',blank = True, 
        related_name = 'radiotherapy_dicom_studies',
        help_text="Imaging studies for this course (planning CT, verification images)."
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
    '''
    Target volumes treated as part of a radiotherapy course. Record
    granularity: one record per distinct volume/structure described.
    '''
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
        help_text="Name of the structure/volume as in the plan (e.g. 'PTV1', 'Lung', 'Brain stem')."
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
        help_text="Dose prescribed to this volume. Unit in radiation_dose_units.",
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
        help_text="Number of fractions to this volume."
    )
    volume_radiotherapy_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date this volume was started. (DD/MM/YYYY)"
    )
    volume_radiotherapy_end_date = models.DateField(    
        null=True,
        blank=True,
        help_text="Date this volume was ended. Blank if ongoing. (DD/MM/YYYY)"     
    )
    anatomical_locations = models.ManyToManyField(
        'lookup.LookupRTLocation',
        blank=True,
        help_text="Anatomical sites covered by this volume."
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
    '''
    Dose-volume metrics for a structure treated in a radiotherapy course.
    Record granularity: one record per distinct structure with reported dose
    metrics. Note this data is supposed to represent a dose received by a volume so a report may have multiple such values. 
    '''
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
        help_text="Physical volume of the structure, in cc (volume_units)."
    )
    relative_volume = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,      
        blank=True,  
        validators=percentage_validator,   
        help_text="Volume as a percentage of the reference organ (e.g. lung, liver), 0–100."
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
        help_text="Absolute dose metric for this volume (e.g. Dmean, D95). Unit in radiation_dose_units."
    )
    relative_dose = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=percentage_validator,
        help_text="Dose metric as a percentage, 0–100."
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
    '''
    Surgical procedures performed for a diagnosis: type, side, date, nodal
    assessment and reconstruction. Record granularity: one record per
    distinct surgical procedure/event the document describes; separate
    procedures reported in the same document are separate records. Surgery details may be partly present in the histopathology reports also in which extract what is available. Note that if the patient has undergone surgery to left and right side seperately then these need to be reported as seperate surgeries. Note that the date of surgery may not be the same as date of pathology. 
    '''
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
        help_text="Date the surgery was performed. (DD/MM/YYYY)"
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
        help_text="Surgical procedure(s) performed (e.g. mastectomy, lumpectomy, axillary dissection, biopsy)."
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
        help_text="True if nodal assessment was performed; False otherwise."
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
        help_text="True if reconstructive surgery was performed; False otherwise."
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
        help_text="Imaging studies related to the surgery (pre- or post-operative)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.diagnosis}-{self.surgery_date}"
    class Meta:
        verbose_name_plural="Surgery"
        db_table="surgery"

class ConcomitantMedications(DateValidationMixin, models.Model):
    '''
    Medications a patient takes alongside their cancer treatment: drug,
    dose, route. Record granularity: one record per distinct medication
    described.
    '''
    '''This is a table of the concomitant medications that the patient may receive.'''
    chavi_medication_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )    
    medication_name = models.CharField(
        max_length=255,
        help_text="Medication name exactly as documented (generic name preferred)."
    )
    medication_dose = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=positive_decimal_validator, 
        null=True, 
        blank=True,
        help_text="Dose per administration/cycle. Unit in medication_dose_units."
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
        help_text="Date the medication was started. (DD/MM/YYYY)"
    )
    date_medication_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date the medication was stopped. Blank if still being taken. (DD/MM/YYYY)"
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
    '''
    A systemic (pharmacological) treatment course for a diagnosis: type,
    regimen, sequence, intent and dosing. Record granularity: one record per
    distinct therapy course described; separate courses in the same document
    are separate records.
    '''
    ''' This is a systemic therapy table which has details of the systemic therapy given to the patient'''

    chavi_systemic_therapy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        Diagnosis, 
        on_delete=models.CASCADE,
        help_text="Select the diagnosis that this treatment is associated with"
    )    
    systemic_therapy_type = models.ForeignKey('lookup.LookupSystemicTherapyType', on_delete=models.PROTECT,null=True, blank=True,
    help_text = "Type of systemic therapy (e.g. chemotherapy, immunotherapy, hormonal, targeted, bispecific).")
    systemic_therapy_intent = models.ForeignKey('lookup.LookupTreatmentIntent', on_delete=models.PROTECT,null=True, blank=True,
    related_name='systemic_therapy_intent', help_text="Select the intent of the systemic therapy")
    systemic_therapy_sequence = models.ForeignKey('lookup.LookupTreatmentSequence', on_delete=models.PROTECT,null=True, blank=True,
    help_text="Sequence/line of therapy (e.g. first-line, second-line, induction, consolidation, adjuvant).")
    systemic_therapy_regimen = models.ForeignKey('lookup.LookupSystemicTherapyRegimen', on_delete=models.PROTECT,null=True, blank=True,related_name='systemic_therapy_regimen',
                                                 help_text="Select the regimen for the systemic therapy")
    systemic_therapy_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date the systemic therapy course was started. (DD/MM/YYYY)"
    )
    systemic_therapy_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date the systemic therapy course ended. Blank if ongoing. (DD/MM/YYYY)"
    )    
    cycles_delivered = models.PositiveIntegerField(null=True,blank=True,help_text="Number of cycles actually delivered.")
    study_instance_uid = models.ManyToManyField(
        'DICOMStudy',blank = True, 
        related_name = 'systemic_therapy_dicom_studies',
        help_text="Imaging studies used to assess this course."
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
    '''
    The drug schedule of a systemic therapy course: agents, routes, doses
    and units per line of the schedule. Record granularity: one record per
    scheduled drug/line; all lines of one course belong to the same
    SystemicTherapy record.
    '''
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
        help_text="Date this specific agent was started. (DD/MM/YYYY)"
    )
    systemic_therapy_agent_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date this specific agent was stopped. Blank if ongoing. (DD/MM/YYYY)"
    )
    systemic_therapy_agent = models.ForeignKey(
        'lookup.LookupSystemicAgent', 
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='systemic_therapy_agent',
        help_text="Specific drug/agent in this course (e.g. 'paclitaxel')."
    )
    systemic_therapy_dose_planned = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Planned dose per cycle/administration. Unit in systemic_therapy_dose_units."
    )
    systemic_therapy_dose_administered = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=positive_decimal_validator,
        help_text="Dose actually administered. Unit in systemic_therapy_dose_units."
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
    '''
    Treatment adverse effects for a diagnosis, graded per CTCAE. Record
    granularity: one record per distinct adverse effect described.
    '''
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
        help_text="CTCAE term and grade (1–5) of the adverse event/toxicity."
    )
    adverse_effect_start_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date the adverse effect first occurred. (DD/MM/YYYY)"
    )
    adverse_effect_end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Date it resolved, if resolved. Blank if ongoing. (DD/MM/YYYY)"
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
    '''
    Patient-reported outcome measurements for a patient (prognostic and
    outcome scores). Record granularity: one record per distinct reported
    outcome measurement described.
    '''
    ''' This is the table which will store information on the patient-reported outcomes'''
    chavi_pro_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient, 
        on_delete=models.CASCADE,
        help_text="Select the patient who completed this patient-reported outcome assessment"
    )
    pro_assessment_date = models.DateField(null=True,blank=True,help_text="Date this PRO assessment was completed. (DD/MM/YYYY)")
    pro_instrument = models.CharField(max_length=500, help_text="Name of the PRO questionnaire (e.g. EORTC QLQ-C30, FACT).")
    pro_scale = models.CharField(max_length=500, help_text="Domain/scale of the instrument the question belongs to.")
    pro_question_id = models.CharField(max_length=500, help_text="Question/item number or code from the instrument.")
    pro_question = models.CharField(max_length=600, help_text="Text of the question as asked.")
    pro_answer = models.CharField(max_length=1000, help_text="Patient's answer exactly as recorded.")
    pro_score = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Numeric score for the response, if applicable."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.chavi_pro_id}"

    class Meta:
        verbose_name_plural="Patient Reported Outcomes"
        db_table="patient_reported_outcome"    

class PatientOutcome(models.Model):
    '''
    Overall outcome status of a patient (for example alive/dead status).
    Record granularity: one record per patient.
    '''
    ''' This is the table which will store information on the outcome of the patients'''
    chavi_patient_outcome_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE)
    patient_status = models.ForeignKey('lookup.LookupOutcome', on_delete=models.PROTECT,
    help_text="Patient's last known status (e.g. alive, dead, lost to follow-up).")
    date_of_death = models.DateField(null=True, blank=True,
    help_text="Date of death, if applicable. Blank if alive. (DD/MM/YYYY)")
    last_date_of_follow_up = models.DateField(null=True, blank=True,
    help_text="Date of the most recent follow-up. (DD/MM/YYYY)")
    death_related_to_cancer_progression = models.BooleanField(default=False,null=True,blank=True,help_text="True if death was attributed to cancer progression.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.chavi_patient_outcome_id}"

    class Meta:
        verbose_name_plural="Patient Outcomes"
        db_table="patient_outcome"

class Comorbidity(models.Model):
    '''
    Co-existing diseases or conditions (comorbidities) of a patient. Record
    granularity: one record per distinct comorbidity described.
    '''
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
        help_text="Non-cancer condition (e.g. diabetes, hypertension, COPD)."
    )
    date_of_comorbidity_diagnosis = models.DateField(
        null=True, 
        blank=True,
        help_text="Date the comorbidity was diagnosed. If blank, derived as assessment date minus duration. (DD/MM/YYYY)"
    )
    date_of_comorbidity_assessment = models.DateField(
        null=True, 
        blank=True,
        help_text="Date the comorbidity was last assessed. (DD/MM/YYYY)"
    )
    duration_of_comorbidity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Enter the duration of the comorbidity in months"
    )
    comorbidity_resolved = models.BooleanField(
        default=False,
        help_text="Whether the comorbidity is resolved (True/False)."
    )
    medication_for_comorbidity = models.BooleanField(
        default=False,
        help_text="Whether the patient is on medication for it (True/False)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def prepare_for_save(self):
        # Calculate diagnosis date if we have both assessment date and duration
        if self.date_of_comorbidity_assessment and self.duration_of_comorbidity:
            # Subtract months from assessment date to get diagnosis date
            self.date_of_comorbidity_diagnosis = self.date_of_comorbidity_assessment - relativedelta(months=self.duration_of_comorbidity)

    def save(self, *args, **kwargs):
        self.prepare_for_save()
        super().save(*args, **kwargs)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.comorbidity_type}"

    class Meta:
        verbose_name_plural="Comorbidities"
        db_table="comorbidity"

class StageInformation(models.Model):
    '''
    Cancer staging for a diagnosis: TNM descriptors, overall stage group and
    the staging system used. Record granularity: one record per diagnosis; a
    report's staging line (e.g. "pT3 pN3b, AJCC 8th edition") is ONE stage
    assessment, so split it across the fields of a single record. Pay special attention to the prefix and suffix of the stage.
    '''
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
        help_text="Basis of staging (clinical / pathological / restaging)."
    )
    t_stage_prefix = models.ForeignKey(
        'lookup.LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='t_stage_prefix',
        null=True, 
        blank=True,
        help_text="Prefix showing basis: 'c' = clinical, 'p' = pathological."
    )
    t_stage = models.ForeignKey(
        'lookup.LookupAJCCTStageDescriptor',
        on_delete=models.PROTECT,
        related_name = 't_stage',
        null=True, 
        blank=True,
        help_text="T descriptor for the primary tumor (T0–T4 with sub-scores)."
    )
    t_stage_suffix = models.ForeignKey(
        'lookup.LookupAJCCStageSuffix',
        on_delete=models.PROTECT,
        related_name='t_stage_suffix',             
        null=True, 
        blank=True,
        help_text="Sub-classification suffix (a/b/c)."
    )
    n_stage_prefix = models.ForeignKey(
        'lookup.LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='n_stage_prefix',        
        null=True, 
        blank=True,   
        help_text="Prefix showing basis: 'c' = clinical, 'p' = pathological."
    )
    n_stage = models.ForeignKey(
        'lookup.LookupAJCCNStageDescriptor',
        on_delete=models.PROTECT,
        related_name='n_stage',
        null=True, 
        blank=True,
        help_text="N descriptor for lymph-node involvement (N0–N3)."
    )
    n_stage_suffix = models.ForeignKey(
        'lookup.LookupAJCCStageSuffix',
        on_delete=models.PROTECT,
        related_name='n_stage_suffix',         
        null=True, 
        blank=True,  
        help_text="Sub-classification suffix (a/b/c)."
    ) 
    m_stage_prefix = models.ForeignKey(
        'lookup.LookupAJCCStagePrefix',
        on_delete=models.PROTECT,
        related_name='m_stage_prefix',        
        null=True, 
        blank=True,        
        help_text="Prefix showing basis: 'c' = clinical, 'p' = pathological."
    )
    m_stage = models.ForeignKey(
        'lookup.LookupAJCCMStageDescriptor',
        on_delete=models.PROTECT,
        null=True, 
        blank=True,
        help_text="M descriptor for distant metastasis (M0, M1, M1a/M1b/M1c)."
    )
    m_stage_suffix = models.ForeignKey(
        'lookup.LookupAJCCStageSuffix',
        related_name='m_stage_suffix',        
        on_delete=models.PROTECT,
        null=True, 
        blank=True,  
        help_text="Sub-classification suffix (a/b/c)."
    ) 
    overall_stage = models.ForeignKey(
        'lookup.LookupStageDescriptor',
        on_delete=models.PROTECT,
        related_name= 'overall_stage',
        null=True, 
        blank=True,
        help_text="Overall stage grouping (I, II, III, IV)."
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
    '''
    Laboratory test results for a patient: test, quantitative or qualitative
    value, units. Record granularity: one record per distinct test result
    described; different values of the same test (for example on different
    dates) are separate records.
    '''
    ''' This is a model for the laboratory results. This is a many to one relationship with the patient model.'''
    chavi_laboratory_result_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE,help_text="Select the patient for whom the laboratory result was obtained")
    laboratory_test = models.ForeignKey('lookup.LookupLaboratoryTest', on_delete=models.PROTECT,help_text="Test that was measured (e.g. haemoglobin, CA 125, LDH).")
    result_date = models.DateField(null=True, blank=True,help_text="Date of the laboratory result. (DD/MM/YYYY)")
    quantitative_result_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Numeric result. Leave blank when the result is qualitative.")
    quantitative_result_unit = models.ForeignKey('lookup.LookupLabResultsUnits',null=True, blank=True, on_delete=models.PROTECT,help_text="Select the unit of the laboratory result")
    qualitative_laboratory_result = models.CharField(max_length=20, choices=QualitativeLaboratoryResult.choices, null=True, blank=True,help_text="Qualitative result (positive, negative, present, absent, detected…). Leave blank when the result is numeric.")    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__ (self):
        return f"{self.patient.patient_id} - {self.laboratory_test.label}"
    
    class Meta:
        verbose_name_plural="Laboratory Results"
        db_table='laboratory_results'        

class PatientAssessment(models.Model):
    '''
    Clinical assessments of a patient (for example performance status).
    Record granularity: one record per distinct assessment described.
    '''
    ''' This is a table for recording the assessments of the patients'''
    chavi_patient_assessment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE,help_text="Select the patient for whom the assessment was performed")
    date_assessment = models.DateField(null=True, blank=True,help_text="Date of the assessment. (DD/MM/YYYY)")
    height = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Height in centimeters (cm).")
    weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Weight in kilograms (kg).")
    systolic_blood_pressure = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Systolic blood pressure in mmHg (from '120/80', take 120).")
    diastolic_blood_pressure = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Diastolic blood pressure in mmHg (from '120/80', take 80).")
    pulse = models.PositiveIntegerField(null=True, blank=True,help_text="Heart rate in beats per minute.")
    temperature = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,validators=positive_decimal_validator,help_text="Body temperature in degrees Celsius.")
    respiratory_rate = models.PositiveIntegerField(null=True, blank=True,help_text="Respiratory rate in breaths per minute.")
    performance_status = models.ForeignKey('lookup.LookupPerformanceStatus', on_delete=models.PROTECT,null=True, blank=True,help_text="Performance status score (ECOG/WHO 0–4).")
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

# Model created for handling bulk uploads of DICOM files from multiple patients. It matches the DICOM files to existing patients based on the Patient ID found in the DICOM metadata.
class BulkDICOMUpload(models.Model):
    '''This model handles bulk uploads of DICOM files from multiple patients. It matches the DICOM files to existing patients based on the Patient ID found in the DICOM metadata.'''
    file = models.FileField(
        upload_to='bulk_dicom_files',
        validators=[
            FileExtensionValidator(allowed_extensions=["zip"])
        ],
        help_text="Upload a zip file containing DICOM studies from multiple patients. Files will be processed and sorted based on Patient IDs found in DICOM metadata. Maximum file size: 10GB."
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


# Model to track bulk DICOM upload sessions for the frontend workflow
class BulkDICOMUploadSession(models.Model):
    '''This model tracks bulk DICOM upload sessions for the frontend workflow with manual patient matching'''
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_file = models.FileField(
        upload_to='bulk_dicom_sessions',
        validators=[FileExtensionValidator(allowed_extensions=["zip"])],
        help_text="Uploaded zip file containing DICOM studies from multiple patients"
    )
    temp_directory = models.CharField(max_length=500, null=True, blank=True, help_text="Temporary directory path for extracted files")
    
    class StatusChoices(models.TextChoices):
        UPLOADED = 'UPLOADED', 'Uploaded'
        EXTRACTED = 'EXTRACTED', 'Extracted'
        ANALYZED = 'ANALYZED', 'Analyzed'
        MATCHING = 'MATCHING', 'Awaiting Manual Matching'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
    
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.UPLOADED
    )
    
    uploaded_by = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='bulk_dicom_sessions'
    )
    
    # Statistics
    total_studies = models.IntegerField(default=0)
    auto_matched_studies = models.IntegerField(default=0)
    manual_match_required = models.IntegerField(default=0)
    unmatched_studies = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    error_log = models.TextField(null=True, blank=True)

    # Checkpoint / resume fields
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, help_text="Celery task id of the most recently dispatched task")
    progress_current = models.IntegerField(default=0)
    progress_total = models.IntegerField(default=0)
    progress_description = models.CharField(max_length=255, null=True, blank=True)
    last_progress_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of last progress update, used for stall detection")
    resume_count = models.IntegerField(default=0, help_text="Number of times this session has been resumed")

    class Meta:
        verbose_name = "Bulk DICOM Upload Session"
        verbose_name_plural = "Bulk DICOM Upload Sessions"
        ordering = ['-created_at']

    def __str__(self):
        return f"Session {self.session_id} - {self.status}"

    @property
    def progress_percent(self):
        if self.progress_total > 0:
            return int(self.progress_current / self.progress_total * 100)
        return 0


# Model to track individual studies within a bulk upload session
class BulkDICOMStudyMatch(models.Model):
    '''This model tracks individual DICOM studies within a bulk upload session and their patient matching status'''
    match_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        BulkDICOMUploadSession,
        on_delete=models.CASCADE,
        related_name='study_matches'
    )
    
    study_instance_uid = models.CharField(max_length=255)
    dicom_patient_id = models.CharField(max_length=255)
    
    # Study metadata
    study_description = models.CharField(max_length=255, null=True, blank=True)
    study_date = models.DateField(null=True, blank=True)
    modalities = models.CharField(max_length=255, null=True, blank=True)
    series_descriptions = models.TextField(null=True, blank=True)
    file_count = models.IntegerField(default=0)
    
    # Matching information
    class MatchStatus(models.TextChoices):
        AUTO_MATCHED = 'AUTO_MATCHED', 'Automatically Matched'
        MANUAL_MATCH_REQUIRED = 'MANUAL_MATCH_REQUIRED', 'Manual Match Required'
        MANUALLY_MATCHED = 'MANUALLY_MATCHED', 'Manually Matched'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        UNMATCHED = 'UNMATCHED', 'Unmatched'
        PROCESSED = 'PROCESSED', 'Processed'
    
    match_status = models.CharField(
        max_length=30,
        choices=MatchStatus.choices,
        default=MatchStatus.MANUAL_MATCH_REQUIRED
    )
    
    matched_patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bulk_study_matches'
    )
    
    # Folder path where DICOM files are stored temporarily
    temp_folder_path = models.CharField(max_length=500, null=True, blank=True)
    
    # Final folder path after processing
    final_folder_path = models.CharField(max_length=500, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Bulk DICOM Study Match"
        verbose_name_plural = "Bulk DICOM Study Matches"
        unique_together = ['session', 'study_instance_uid']
    
    def __str__(self):
        return f"{self.study_instance_uid} - {self.dicom_patient_id} ({self.match_status})"


# Model to track all DICOM-related Celery task runs with progress and resume capability
class TaskRun(models.Model):
    '''Tracks all dispatched DICOM import/export Celery tasks with progress, status, and resume support.'''

    class TaskType(models.TextChoices):
        DICOM_IMPORT = 'DICOM_IMPORT', 'DICOM Import'
        DICOM_EXPORT = 'DICOM_EXPORT', 'DICOM Export'
        BULK_DICOM = 'BULK_DICOM', 'Bulk DICOM'
        PATIENT_EXPORT = 'PATIENT_EXPORT', 'Patient Export'
        ASSOCIATE = 'ASSOCIATE', 'Associate to Project'
        UNPROCESSED = 'UNPROCESSED', 'Process Unprocessed DICOM'
        DEIDENTIFICATION = 'DEIDENTIFICATION', 'Deidentification'
        DICOM_ARCHIVE = 'DICOM_ARCHIVE', 'DICOM Archive'
        DICOM_DEARCHIVE = 'DICOM_DEARCHIVE', 'DICOM De-archive'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        STARTED = 'STARTED', 'Started'
        PROGRESS = 'PROGRESS', 'In Progress'
        SUCCESS = 'SUCCESS', 'Success'
        FAILURE = 'FAILURE', 'Failure'
        STALLED = 'STALLED', 'Stalled'
        CANCELLED = 'CANCELLED', 'Cancelled'

    task_id = models.CharField(max_length=255, unique=True, help_text="Celery task id")
    task_name = models.CharField(max_length=255, help_text="Celery task name")
    task_type = models.CharField(
        max_length=30,
        choices=TaskType.choices,
        default=TaskType.DICOM_IMPORT
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    user = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='task_runs'
    )

    progress_current = models.IntegerField(default=0)
    progress_total = models.IntegerField(default=0)
    progress_description = models.CharField(max_length=255, null=True, blank=True)
    last_progress_at = models.DateTimeField(null=True, blank=True)

    resume_count = models.IntegerField(default=0, help_text="Number of times this task has been resumed")
    manifest_path = models.CharField(max_length=500, null=True, blank=True, help_text="Path to JSONL manifest for per-file checkpointing")

    task_args = models.JSONField(null=True, blank=True, help_text="Original positional arguments used to dispatch this task, for resume/retry")
    task_kwargs = models.JSONField(null=True, blank=True, help_text="Original keyword arguments used to dispatch this task, for resume/retry")

    result_summary = models.JSONField(null=True, blank=True, help_text="Task return value stored as JSON")
    error_log = models.TextField(null=True, blank=True)

    related_session_id = models.UUIDField(null=True, blank=True, help_text="Links to BulkDICOMUploadSession when applicable")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Task Run"
        verbose_name_plural = "Task Runs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['user']),
            models.Index(fields=['task_type']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.task_name} ({self.task_id[:8]}...) - {self.status}"

    @property
    def progress_percent(self):
        if self.progress_total > 0:
            return int(self.progress_current / self.progress_total * 100)
        return 0

    @property
    def duration_seconds(self):
        if self.completed_at and self.created_at:
            return (self.completed_at - self.created_at).total_seconds()
        elif self.last_progress_at and self.created_at:
            return (self.last_progress_at - self.created_at).total_seconds()
        return None


# In-app notification model for task events
class Notification(models.Model):
    '''In-app notifications for task completion, failure, stall, and resume events.'''

    class NotificationType(models.TextChoices):
        TASK_COMPLETED = 'TASK_COMPLETED', 'Task Completed'
        TASK_FAILED = 'TASK_FAILED', 'Task Failed'
        TASK_STALLED = 'TASK_STALLED', 'Task Stalled'
        TASK_RESUMED = 'TASK_RESUMED', 'Task Resumed'

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        default=NotificationType.TASK_COMPLETED
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    task_run = models.ForeignKey(
        TaskRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
        ]

    def __str__(self):
        return f"{self.notification_type} - {self.title} ({'read' if self.is_read else 'unread'})"


# DICOM Series and Instance models (for deidentification metadata extraction)
class DICOMSeries(models.Model):
    study = models.ForeignKey(
        DICOMStudy,
        on_delete=models.CASCADE,
        related_name='series',
        help_text="Reference to the DICOM study this series belongs to."
    )
    series_instance_uid = models.CharField(
        max_length=128,
        unique=True,
        help_text="DICOM tag (0020,000E) — Series Instance UID."
    )
    series_date = models.DateField(
        null=True,
        blank=True,
        help_text="DICOM tag (0008,0021) — Series Date. (DD/MM/YYYY)"
    )
    modality = models.CharField(
        max_length=16,
        help_text="DICOM tag (0008,0060) — Modality (e.g. CT, MR, RTPLAN)."
    )
    frame_of_reference_uid = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text="DICOM tag (0020,0052) — Frame of Reference UID."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.modality} - {self.series_instance_uid[:30]}..."

    class Meta:
        verbose_name_plural = "DICOM Series"
        db_table = "dicom_series"


class DICOMInstance(models.Model):
    series = models.ForeignKey(
        DICOMSeries,
        on_delete=models.CASCADE,
        related_name='instances',
        help_text="Reference to the DICOM series this instance belongs to."
    )
    sop_instance_uid = models.CharField(
        max_length=128,
        unique=True,
        help_text="DICOM tag (0008,0018) — SOP Instance UID."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.sop_instance_uid[:30]}..."

    class Meta:
        verbose_name_plural = "DICOM Instances"
        db_table = "dicom_instances"