from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal

positive_decimal_validator = [
    MinValueValidator(Decimal('0.0'))
]

class LookupAbstract(models.Model):
    '''This is an abstract for the lookup table.'''
    code = models.CharField(max_length=100,primary_key=True)
    label = models.CharField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

class LookupLaterality(LookupAbstract):
    '''This is a lookup table for the laterality i.e. Left, Right etc. ICD 11 codes are included for data sharing.'''

    def __str__(self):
        return f"{self.label}"

class LookupICDCode(LookupAbstract):
    '''This is a lookup table with ICD 11 codes for the diagnosis.'''
    icd_version = models.DecimalField(max_digits=5, decimal_places=2, validators=positive_decimal_validator)

    def __str__(self):
        return f"{self.label}"

class LookupFMACode(LookupAbstract):
    '''This is a lookup table with Foundational Model of Anatomy codes for the Anatomical Site of the disease.'''
    def __str__(self):
        return f"{self.label}"

class LookupPresentation(LookupAbstract):
    '''This is a lookup for presentation type.'''
    def __str__(self):
        return f"{self.label}"

class LookupOutcomeType(LookupAbstract):
    '''This is a lookup table where outcome type like local recurrence, nodal recurrence etc are recorded.'''
    def __str__(self):
        return f"{self.label}"

class LookupLesionType(LookupAbstract):
    '''This is a lookup table where lesion location type is recorded e.g. local, nodal, distant '''

    def __str__(self):
        return f"{self.label}"

class LookupResponseType(LookupAbstract):
    '''This is a lookup table for the response type that the lesion has had. For example complete response, partial response, stable disease, progressive disease.'''

    def __str__(self):
        return f"{self.label}"

class LookupProtein(models.Model):
    '''This is a lookup table for Protein Names.'''
    code = models.CharField(max_length=50,primary_key=True)
    gene_name = models.CharField(max_length=500,null=True)
    uniport_id = models.CharField(max_length=500,null=True)
    protein_name = models.CharField(max_length=3500,null=True)
    all_gene_names = models.CharField(max_length=500,null=True)


    def __str__(self):
        return f'{self.gene_name}'

class LookupGene(LookupAbstract):
    '''This is a lookup table for Gene Names.'''

    def __str__(self):
        return f"{self.label}"

class LookupTreatmentIntent(LookupAbstract):
    '''This is a lookup table for Treatment Intent.'''

    def __str__(self):
        return f"{self.label}"

class LookupTreatmentSequence(LookupAbstract):
    '''This is a lookup table for Treatment Sequence.'''

    def __str__(self):
        return f"{self.label}"

class LookupSystemicAgent(LookupAbstract):
    '''This is a lookup table for Systemic Agents.'''

    def __str__(self):
        return f"{self.label}"

class LookupVolumeUnits(LookupAbstract):
    '''This is a lookup table for units of measurement for use in the database for volume'''

    unit_abbreviation = models.CharField(max_length=255)
    
    def __str__(self):
        return self.unit_abbreviation
    
class LookupSizeUnits(LookupAbstract):
    '''This is a lookup table for units of measurement for use in the database for size'''

    unit_abbreviation = models.CharField(max_length=255)
    
    def __str__(self):
        return self.unit_abbreviation    
    
class LookupDoseUnits(LookupAbstract):
    '''This is a lookup table for units of measurement for use in the database for dose'''

    unit_abbreviation = models.CharField(max_length=255)
    
    def __str__(self):
        return self.unit_abbreviation    
    
class LookupLabResultsUnits(LookupAbstract):
    '''This is a lookup table for units of measurement for use in the database for lab results'''

    unit_abbreviation = models.CharField(max_length=255)
    
    def __str__(self):
        return self.unit_abbreviation    

class LookupMassUnits(LookupAbstract):
    '''This is a lookup table for units of measurement for use in the database for mass'''

    unit_abbreviation = models.CharField(max_length=255)
    
    def __str__(self):
        return self.unit_abbreviation    

class LookupDrugRoute(LookupAbstract):
    '''This is a lookup table for drug routes.'''

    def __str__(self):
        return f"{self.label}"

class LookupCTCAEGrade(models.Model):
    '''This is a lookup table for the NCI Common Terminology of Adverse Effects grades.'''
    code = models.CharField(max_length=50,primary_key=True)
    ctcae_term = models.CharField(max_length=255)
    meddra_code = models.CharField(max_length=255)
    ctcae_grade = models.PositiveIntegerField()
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.ctcae_term} - Grade {self.ctcae_grade} ({self.description})"

class LookupOutcome(LookupAbstract):
    '''This is a lookup table for outcomes types.'''

    def __str__(self):
        return f"{self.label}"

class LookupStagingSystem(LookupAbstract):
    '''This is a lookup table for staging systems.'''
    staging_system_version = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.label}"

class LookupAJCCStagePrefix(LookupAbstract):
    '''This is a lookup table for AJCC stage prefixes.'''
    def __str__(self):
        return f"{self.label}"

class LookupAJCCStageSuffix(LookupAbstract):
    '''This is a lookup table for AJCC stage suffixes.'''

    def __str__(self):
        return f"{self.label}"

class LookupAJCCTStageDescriptor (LookupAbstract):
    ''' This is a lookup table for AJJC T stage descriptors.'''
    def __str__(self):
        return f"{self.label}"

class LookupAJCCNStageDescriptor (LookupAbstract):
    ''' This is a lookup table for AJJC N stage descriptors.'''
    def __str__(self):
        return f"{self.label}"

class LookupAJCCMStageDescriptor (LookupAbstract):
    ''' This is a lookup table for AJJC M stage descriptors.'''
    def __str__(self):
        return f"{self.label}"

class LookupStageDescriptor (LookupAbstract):
    ''' This is a lookup table for AJJC stage descriptors.'''
    def __str__(self):
        return f"{self.label}"

class LookupDiagnosticModality(LookupAbstract):
    ''' This is a lookup table for the diagnostic modality'''
    def __str__(self):
        return f"{self.label}"
    class Meta:
        verbose_name_plural= "Diagnostic Modalities"
        db_table = 'lookup_diagnostic_modality'

class LookupSystemicTherapyType(LookupAbstract):
    ''' This is a lookup table for the type of Systemic Therapy'''
    def __str__(self):
        return f"{self.label}"

    class Meta:
        verbose_name_plural = "Systemic Therapy Types"
        db_table = 'lookup_systemic_therapy_type'

class LookupRadiotherapyVolumeType(LookupAbstract):
    ''' This is a lookup table for the type of Radiotherapy Volume'''
    def __str__(self):
        return f"{self.label}"

    class Meta:
        verbose_name_plural = "Radiotherapy Volume Types"

class LookupPathology(LookupAbstract):
    ''' This is a lookup table for the pathology.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Lookup Pathology"

class LookupGrade(LookupAbstract):
    ''' This is a lookup table for the grade of the pathology.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Grade"

class LookupPathologyDescriptors(LookupAbstract):
    ''' This is a lookup table for the descriptors of the pathology terms.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Pathology Descriptors"

class LookupMajorCancerCategory(LookupAbstract):
    ''' This is a lookup table for the major cancer category.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Major Cancer Category"

class LookupRadiotherapyModality(LookupAbstract):
    ''' This is a lookup table for the radiotherapy modality.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Radiotherapy Modality"

class LookupRadiotherapyType(LookupAbstract):
    ''' This is a lookup table for the radiotherapy type.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Radiotherapy Type" 

class LookupRadiotherapyTechnique(LookupAbstract):
    ''' This is a lookup table for the radiotherapy technique.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Radiotherapy Techniques"

class LookupClinicalSignificance(LookupAbstract):
    ''' This is a lookup table for the clinical significance for genetic mutations.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Clinical Significance"

class LookupIHCResult(LookupAbstract):
    ''' This is a lookup table for the IHC result.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "IHC Results"

class LookupIHCStainingIntensity(LookupAbstract):
    ''' This is a lookup table for the IHC staining intensity.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "IHC Staining Intensities"

class LookupMarginStatus(LookupAbstract):
    ''' This is a lookup table for the margin status.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Margin Status"

class LookupTreatmentEffect(LookupAbstract):
    ''' This is a lookup table for the treatment effect.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Treatment Effect"

class LookupStagingType(LookupAbstract):
    ''' This is a lookup table for the staging type.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Staging Type"

class LookupSystemicTherapyRegimen(LookupAbstract):
    ''' This is a lookup table for the systemic therapy regimen.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Systemic Therapy Regimen"

class LookupRTLocation(LookupAbstract):
    ''' This is a lookup table for the anatomical location of radiotherapy volumes'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Anatomical Location"

class LookupLaboratoryTest(LookupAbstract):
    ''' This is a lookup table for the laboratory test.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Lookup Laboratory Tests"

class LookupSymptoms(LookupAbstract):
    ''' This is a lookup table for the symptoms.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Symptoms"

class LookupSeverity(LookupAbstract):
    ''' This is a lookup table for the severity of the symptoms.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Severity"

class LookupIHCAntibody(LookupAbstract):
    ''' This is a lookup table for the antibody used in immunohistochemistry.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "IHCAntibody"

class LookupComorbidity(LookupAbstract):
    ''' This is a lookup table for the comorbidity.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Comorbidity"

class LookupPerformanceStatus(LookupAbstract):
    ''' This is a lookup table for the performance status.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Performance Status"

class LookupExpressionUnits(LookupAbstract):
    ''' This is a lookup table for the units of expression.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Expression Units"

class LookupCytogeneticAbnormality(LookupAbstract):
    ''' This is a lookup table for the cytogenetic abnormality.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Cytogenetic Abnormality"

class LookupEpigeneticAbnormalityType(LookupAbstract):
    ''' This is a lookup table for the type of epigenetic abnormality.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Epigenetic Abnormality Type"

class LookupSurgicalProcedures(LookupAbstract):
    ''' This is a lookup table for the surgical procedures.'''
    description = models.TextField()
    
    def __str__(self):
        return f"{self.label}: {self.description}"
    
    class Meta:
        verbose_name_plural = "Surgical Procedures"


class LookupNodalAssessmentType(LookupAbstract):
    ''' This is a lookup table for the type of nodal assessment.'''
    def __str__(self):
        return f"{self.label}"
    
    class Meta:
        verbose_name_plural = "Nodal Assessment Type"             