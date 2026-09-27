"""
This module contains serializers for the CHAVI client application's data export functionality.

Purpose:
--------
These serializers are designed to transform Django model instances into JSON format 
for data transfer between the client and server applications. The serialization process
includes special handling of primary keys and foreign key relationships to maintain
data integrity and security.

Key Features:
------------
1. Primary Key Hashing:
   - All model primary keys (except Patient, DICOMStudy, and Project) are hashed using SHA-256
   - This ensures sensitive IDs are not exposed in the exported data
   - Hashing is consistent, allowing for reliable data linking on the server side

2. Foreign Key Handling:
   - Foreign key fields are serialized with their original names
   - Related IDs are hashed when they reference models with hashed primary keys
   - Patient IDs are kept unhashed to maintain direct reference

3. Timestamp Exclusion:
   - created_at and updated_at fields are excluded from serialization
   - This is handled by the BaseSerializer class

Implementation Details:
---------------------
1. BaseSerializer:
   - Inherits from ModelSerializer
   - Excludes created_at and updated_at fields by default
   - Serves as the base class for all other serializers

2. Field Naming Convention:
   - Primary key fields: original_name (e.g., chavi_diagnosis_id)
   - Foreign key fields: original field name (e.g., diagnosis)
   - Maintains original Django model field names

3. Data Flow:
   - Model Instance → Serializer → JSON with hashed IDs
   - Foreign keys are represented with their original field names

Example:
-------
For a model with:
    diagnosis = ForeignKey(Diagnosis)

The serialized output will have:
    {
        "diagnosis": "<hashed_id>",  # Hashed ID for the foreign key
    }

Usage:
------
These serializers are primarily used in the export_patient_data action to create
a complete JSON export of patient data. The exported JSON maintains referential 
integrity through hashed IDs while protecting sensitive information.

Note:
-----
When adding new models or relationships, ensure to:
1. Hash primary keys if they contain sensitive information
2. Maintain original field names for consistency
3. Consider data privacy and linking requirements
"""

from rest_framework import serializers
from .models import *
import hashlib
from rest_framework.relations import PrimaryKeyRelatedField

def hash_pk(pk):
    """Helper function to hash primary keys"""
    return hashlib.sha256(str(pk).encode()).hexdigest()

class BaseSerializer(serializers.ModelSerializer):
    """Base serializer to exclude created_at and modified_at fields"""
    class Meta:
        exclude = ['created_at', 'updated_at']

class PatientSerializer(BaseSerializer):
    class Meta(BaseSerializer.Meta):
        model = Patient
        exclude = BaseSerializer.Meta.exclude + [
            'chavi_consent', 'date_chavi_consent', 'canonical_patient_id',
        ]

class DICOMStudySerializer(BaseSerializer):
    class Meta(BaseSerializer.Meta):
        model = DICOMStudy
        exclude = BaseSerializer.Meta.exclude + ['series_descriptions','folder_path']

class HashedForeignKeyField(PrimaryKeyRelatedField):
    """Custom field to hash foreign key values"""
    def to_representation(self, value):
        """Return the hashed ID of the related object"""
        # Get the full related object
        if hasattr(value, '_meta'):
            # Already a full object
            full_obj = value
        else:
            # Get the full object from database
            full_obj = self.queryset.get(pk=value.pk)
            
        # Get the model name
        model_name = full_obj.__class__.__name__
        
        # Special handling for models that shouldn't be hashed
        if model_name == 'Patient':
            return full_obj.patient_id
        elif model_name == 'DICOMStudy':
            return full_obj.study_instance_uid
        elif model_name == 'Project':
            return full_obj.chavi_project_id
        elif model_name == 'SiteConfiguration':  # Site configuration
            return str(full_obj.chavi_center_id)  # Return UUID as string
            
        # For all other models, hash the primary key
        pk_field = full_obj._meta.pk.name
        return hash_pk(getattr(full_obj, pk_field))

class DiagnosisSerializer(BaseSerializer):
    chavi_diagnosis_id = serializers.SerializerMethodField()

    def get_chavi_diagnosis_id(self, obj):
        return hash_pk(obj.chavi_diagnosis_id)

    class Meta(BaseSerializer.Meta):
        model = Diagnosis


class SymptomSerializer(BaseSerializer):
    chavi_symptom_id = serializers.SerializerMethodField()
    patient = HashedForeignKeyField(queryset=Patient.objects.all())

    def get_chavi_symptom_id(self, obj):
        return hash_pk(obj.chavi_symptom_id)

    class Meta(BaseSerializer.Meta):
        model = Symptom

        
class OutcomeSerializer(BaseSerializer):
    chavi_outcome_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_outcome_id(self, obj):
        return hash_pk(obj.chavi_outcome_id)

    class Meta(BaseSerializer.Meta):
        model = Outcome

class LesionSerializer(BaseSerializer):
    chavi_lesion_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_lesion_id(self, obj):
        return hash_pk(obj.chavi_lesion_id)

    class Meta(BaseSerializer.Meta):
        model = Lesion



class LesionResponseSerializer(BaseSerializer):
    chavi_lesion_response_id = serializers.SerializerMethodField()
    lesion = HashedForeignKeyField(queryset=Lesion.objects.all())

    def get_chavi_lesion_response_id(self, obj):
        return hash_pk(obj.chavi_lesion_response_id)

    class Meta(BaseSerializer.Meta):
        model = LesionResponse

class GermlineGenomicAlterationsSerializer(BaseSerializer):
    chavi_germline_genomic_id = serializers.SerializerMethodField()
    patient = HashedForeignKeyField(queryset=Patient.objects.all())

    def get_chavi_germline_genomic_id(self, obj):
        return hash_pk(obj.chavi_germline_genomic_id)

    class Meta(BaseSerializer.Meta):
        model = GermlineGenomicAlterations

class PathologySerializer(BaseSerializer):
    chavi_pathology_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_pathology_id(self, obj):
        return hash_pk(obj.chavi_pathology_id)

    class Meta(BaseSerializer.Meta):
        model = Pathology

class ImmunohistochemistrySerializer(BaseSerializer):
    chavi_ihc_id = serializers.SerializerMethodField()
    pathology = HashedForeignKeyField(queryset=Pathology.objects.all())

    def get_chavi_ihc_id(self, obj):
        return hash_pk(obj.chavi_ihc_id)

    class Meta(BaseSerializer.Meta):
        model = Immunohistochemistry

class CytogeneticsSerializer(BaseSerializer):
    chavi_cytogenetics_id = serializers.SerializerMethodField()
    pathology = HashedForeignKeyField(queryset=Pathology.objects.all())

    def get_chavi_cytogenetics_id(self, obj):
        return hash_pk(obj.chavi_cytogenetics_id)

    class Meta(BaseSerializer.Meta):
        model = Cytogenetics

class SomaticGenomicAlterationsSerializer(BaseSerializer):
    chavi_somatic_genomic_id = serializers.SerializerMethodField()
    pathology = HashedForeignKeyField(queryset=Pathology.objects.all())

    def get_chavi_somatic_genomic_id(self, obj):
        return hash_pk(obj.chavi_somatic_genomic_id)

    class Meta(BaseSerializer.Meta):
        model = SomaticGenomicAlterations

class GeneExpressionDataSerializer(BaseSerializer):
    chavi_gene_expression_id = serializers.SerializerMethodField()
    pathology = HashedForeignKeyField(queryset=Pathology.objects.all())

    def get_chavi_gene_expression_id(self, obj):
        return hash_pk(obj.chavi_gene_expression_id)

    class Meta(BaseSerializer.Meta):
        model = GeneExpressionData

class EpigeneticDataSerializer(BaseSerializer):
    chavi_epigenetic_id = serializers.SerializerMethodField()
    pathology = HashedForeignKeyField(queryset=Pathology.objects.all())

    def get_chavi_epigenetic_id(self, obj):
        return hash_pk(obj.chavi_epigenetic_id)
    
    class Meta(BaseSerializer.Meta):
        model = EpigeneticData

class OtherTreatmentSerializer(BaseSerializer):
    chavi_treatment_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_treatment_id(self, obj):
        return hash_pk(obj.chavi_treatment_id)

    class Meta(BaseSerializer.Meta):
        model = OtherTreatment

class RadiotherapySerializer(BaseSerializer):
    chavi_radiotherapy_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_radiotherapy_id(self, obj):
        return hash_pk(obj.chavi_radiotherapy_id)

    class Meta(BaseSerializer.Meta):
        model = Radiotherapy

class RadiotherapyVolumeSerializer(BaseSerializer):
    chavi_radiotherapy_volume_id = serializers.SerializerMethodField()
    radiotherapy = HashedForeignKeyField(queryset=Radiotherapy.objects.all())

    def get_radiotherapy_volume_id(self, obj):
        return hash_pk(obj.radiotherapy_volume_id)

    class Meta(BaseSerializer.Meta):
        model = RadiotherapyVolume

class RadiotherapyDoseVolumeDataSerializer(BaseSerializer):
    radiotherapy_dose_volume_data_id = serializers.SerializerMethodField()
    radiotherapy = HashedForeignKeyField(queryset=Radiotherapy.objects.all())

    def get_radiotherapy_dose_volume_data_id(self, obj):
        return hash_pk(obj.radiotherapy_dose_volume_data_id)

    class Meta(BaseSerializer.Meta):
        model = RadiotherapyDoseVolumeData

class SurgerySerializer(BaseSerializer):
    chavi_surgery_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_surgery_id(self, obj):
        return hash_pk(obj.chavi_surgery_id)

    class Meta(BaseSerializer.Meta):
        model = Surgery

class ConcomitantMedicationsSerializer(BaseSerializer):
    chavi_medication_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_medication_id(self, obj):
        return hash_pk(obj.chavi_medication_id)

    class Meta(BaseSerializer.Meta):
        model = ConcomitantMedications

class SystemicTherapySerializer(BaseSerializer):
    chavi_systemic_therapy_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_systemic_therapy_id(self, obj):
        return hash_pk(obj.chavi_systemic_therapy_id)

    class Meta(BaseSerializer.Meta):
        model = SystemicTherapy

class SystemicTherapyScheduleSerializer(BaseSerializer):
    chavi_systemic_therapy_schedule_id = serializers.SerializerMethodField()
    systemic_therapy = HashedForeignKeyField(queryset=SystemicTherapy.objects.all())

    def get_chavi_systemic_therapy_schedule_id(self, obj):
        return hash_pk(obj.chavi_systemic_therapy_schedule_id)

    class Meta(BaseSerializer.Meta):
        model = SystemicTherapySchedule

class AdverseEffectsSerializer(BaseSerializer):
    chavi_adverse_effects_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_adverse_effects_id(self, obj):
        return hash_pk(obj.chavi_adverse_effects_id)

    class Meta(BaseSerializer.Meta):
        model = AdverseEffects

class PatientReportedOutcomeSerializer(BaseSerializer):
    chavi_pro_id = serializers.SerializerMethodField()


    def get_chavi_pro_id(self, obj):
        return hash_pk(obj.chavi_pro_id)

    class Meta(BaseSerializer.Meta):
        model = PatientReportedOutcome

class PatientOutcomeSerializer(BaseSerializer):
    chavi_patient_outcome_id = serializers.SerializerMethodField()
    patient = HashedForeignKeyField(queryset=Patient.objects.all())

    def get_chavi_patient_outcome_id(self, obj):
        return hash_pk(obj.chavi_patient_outcome_id)

    class Meta(BaseSerializer.Meta):
        model = PatientOutcome

class ComorbiditySerializer(BaseSerializer):
    chavi_comorbidity_id = serializers.SerializerMethodField()
    patient = HashedForeignKeyField(queryset=Patient.objects.all())

    def get_chavi_comorbidity_id(self, obj):
        return hash_pk(obj.chavi_comorbidity_id)

    class Meta(BaseSerializer.Meta):
        model = Comorbidity

class StageInformationSerializer(BaseSerializer):
    chavi_stage_information_id = serializers.SerializerMethodField()
    diagnosis = HashedForeignKeyField(queryset=Diagnosis.objects.all())

    def get_chavi_stage_information_id(self, obj):
        return hash_pk(obj.chavi_stage_information_id)

    class Meta(BaseSerializer.Meta):
        model = StageInformation

class LaboratoryResultsSerializer(BaseSerializer):
    chavi_laboratory_result_id = serializers.SerializerMethodField()
    patient = HashedForeignKeyField(queryset=Patient.objects.all())

    def get_chavi_laboratory_result_id(self, obj):
        return hash_pk(obj.chavi_laboratory_result_id)

    class Meta(BaseSerializer.Meta):
        model = LaboratoryResults

class PatientAssessmentSerializer(BaseSerializer):
    chavi_patient_assessment_id = serializers.SerializerMethodField()
    patient = HashedForeignKeyField(queryset=Patient.objects.all())

    def get_chavi_patient_assessment_id(self, obj):
        return hash_pk(obj.chavi_patient_assessment_id)
    
    class Meta(BaseSerializer.Meta):
        model = PatientAssessment


class DICOMStudyProjectSerializer(BaseSerializer):
    study_instance_uid = HashedForeignKeyField(queryset=DICOMStudy.objects.all())  # No hash_id_field needed
    project = HashedForeignKeyField(queryset=Project.objects.all())  # No hash_id_field needed

    class Meta(BaseSerializer.Meta):
        model = DICOMStudyProject
        exclude = BaseSerializer.Meta.exclude + ['id'] 