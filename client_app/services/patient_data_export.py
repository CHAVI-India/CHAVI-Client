from django.http import HttpResponse
from ..models import *
from ..serializers import *
import json
import uuid
import zipfile
import io
import os
import hashlib

class UUIDEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle UUID objects"""
    def default(self, obj):
        if isinstance(obj, uuid.UUID):
            # Convert UUID to string
            return str(obj)
        return super().default(obj)

def export_patient_data(modeladmin, request, queryset):
    """
    Admin action to export patient data as individual JSON files within a zip archive.
    
    This function performs the following steps:
    1. Creates an in-memory zip file to store all patient data files
    2. For each patient in the queryset:
        - Collects all related data from various models (diagnoses, treatments, outcomes, etc.)
        - Serializes the data into JSON format
        - Creates a unique filename using a hash of the patient ID
        - Adds the JSON file to the zip archive
    3. Returns the zip file as an HTTP response for download

    Detailed Process:
    ----------------
    For each model:
        The function queries and processes results by:
        1. Querying the database for all test results associated with the patient
           using <Model>.objects.filter(patient=patient)
        2. Serializing the results using <Model>Serializer, which converts each
           field into a dictionary containing:
        3. Adding all serialized results to the patient's data collection using extend()
    
    Args:
        modeladmin: The ModelAdmin instance that called the action
        request: The current HttpRequest object
        queryset: A QuerySet containing the selected Patient objects
    
    Returns:
        HttpResponse: A response containing the zip file with all patient data files
    """
    # Create an in-memory buffer to store the zip file
    # Using BytesIO allows us to create the zip file in memory without writing to disk
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Create a context dictionary for DRF serializers that includes the request object
        context = {'request': request}
        
        # Process each patient individually
        for patient in queryset:
            # Initialize a dictionary to store all data related to this patient
            # Each key represents a different type of data (diagnoses, treatments, etc.)
            # The values will be lists of serialized data for each type
            patient_data = {
                'patients': [],
                'dicom_studies': [],
                'diagnoses': [],
                'outcomes': [],
                'lesions': [],
                'lesion_responses': [],
                'germline_genomic_alterations': [],
                'pathologies': [],
                'immunohistochemistries': [],
                'cytogenetics': [],
                'somatic_genomic_alterations': [],
                'gene_expression_data': [],
                'epigenetic_data': [],
                'other_treatments': [],
                'radiotherapies': [],
                'radiotherapy_volumes': [],
                'radiotherapy_dose_volume_data': [],
                'surgeries': [],
                'concomitant_medications': [],
                'systemic_therapies': [],
                'systemic_therapy_schedules': [],
                'adverse_effects': [],
                'pro_instruments': [],
                'pro_domains': [],
                'pro_questions': [],
                'patient_reported_outcomes': [],
                'patient_outcomes': [],
                'comorbidities': [],
                'stage_information': [],
                'laboratory_results': [],
                'symptoms': [],
                'patient_assessments': [],
                'dicom_study_projects': []
            }

            # Serialize the patient's basic information
            patient_data['patients'].append(
                PatientSerializer(patient, context=context).data
            )

            # Collect and serialize DICOM studies
            # These are medical imaging studies associated with the patient
            dicom_studies = DICOMStudy.objects.filter(patient=patient)
            patient_data['dicom_studies'].extend(
                DICOMStudySerializer(dicom_studies, many=True, context=context).data
            )

            # Collect and serialize DICOM study projects
            # These represent the research projects associated with each DICOM study
            dicom_study_projects = DICOMStudyProject.objects.filter(study_instance_uid__patient=patient)
            patient_data['dicom_study_projects'].extend(
                DICOMStudyProjectSerializer(dicom_study_projects, many=True, context=context).data
            )

            # Collect all diagnoses for this patient
            # A patient may have multiple diagnoses, each with its own related data
            diagnoses = Diagnosis.objects.filter(patient=patient)
            patient_data['diagnoses'].extend(
                DiagnosisSerializer(diagnoses, many=True, context=context).data
            )

            # For each diagnosis, collect all related information
            for diagnosis in diagnoses:
                # Collect outcome data for this diagnosis
                outcomes = Outcome.objects.filter(diagnosis=diagnosis)
                patient_data['outcomes'].extend(
                    OutcomeSerializer(outcomes, many=True, context=context).data
                )

                # Collect lesion data and their responses
                lesions = Lesion.objects.filter(diagnosis=diagnosis)
                patient_data['lesions'].extend(
                    LesionSerializer(lesions, many=True, context=context).data
                )

                # For each lesion, collect response data
                for lesion in lesions:
                    lesion_responses = LesionResponse.objects.filter(lesion=lesion)
                    patient_data['lesion_responses'].extend(
                        LesionResponseSerializer(lesion_responses, many=True, context=context).data
                    )

                # Collect pathology data and related information
                pathologies = Pathology.objects.filter(diagnosis=diagnosis)
                patient_data['pathologies'].extend(
                    PathologySerializer(pathologies, many=True, context=context).data
                )

                # For each pathology record, collect related data
                for pathology in pathologies:
                    # Collect immunohistochemistry data
                    immunohistochemistries = Immunohistochemistry.objects.filter(pathology=pathology)
                    patient_data['immunohistochemistries'].extend(
                        ImmunohistochemistrySerializer(immunohistochemistries, many=True, context=context).data
                    )

                    # Cytogenetics
                    cytogenetics = Cytogenetics.objects.filter(pathology=pathology)
                    patient_data['cytogenetics'].extend(
                        CytogeneticsSerializer(cytogenetics, many=True, context=context).data
                    )

                    # Somatic Genomic Alterations
                    genomic_alterations = SomaticGenomicAlterations.objects.filter(pathology=pathology)
                    patient_data['somatic_genomic_alterations'].extend(
                        SomaticGenomicAlterationsSerializer(genomic_alterations, many=True, context=context).data
                    )

                    # Gene Expression Data
                    gene_expression_data = GeneExpressionData.objects.filter(pathology=pathology)
                    patient_data['gene_expression_data'].extend(
                        GeneExpressionDataSerializer(gene_expression_data, many=True, context=context).data
                    )

                    # Epigenetic Data
                    epigenetic_data = EpigeneticData.objects.filter(pathology=pathology)
                    patient_data['epigenetic_data'].extend(
                        EpigeneticDataSerializer(epigenetic_data, many=True, context=context).data
                    )

                # Collect treatment-related data
                # This includes various types of treatments: radiotherapy, surgery, medications, etc.
                other_treatments = OtherTreatment.objects.filter(diagnosis=diagnosis)
                patient_data['other_treatments'].extend(
                    OtherTreatmentSerializer(other_treatments, many=True, context=context).data
                )

                # Radiotherapy and related data
                radiotherapies = Radiotherapy.objects.filter(diagnosis=diagnosis)
                patient_data['radiotherapies'].extend(
                    RadiotherapySerializer(radiotherapies, many=True, context=context).data
                )

                for radiotherapy in radiotherapies:
                    # Radiotherapy Volumes
                    rt_volumes = RadiotherapyVolume.objects.filter(radiotherapy=radiotherapy)
                    patient_data['radiotherapy_volumes'].extend(
                        RadiotherapyVolumeSerializer(rt_volumes, many=True, context=context).data
                    )

                    # Radiotherapy Dose Volume Data
                    rt_dose_volumes = RadiotherapyDoseVolumeData.objects.filter(radiotherapy=radiotherapy)
                    patient_data['radiotherapy_dose_volume_data'].extend(
                        RadiotherapyDoseVolumeDataSerializer(rt_dose_volumes, many=True, context=context).data
                    )

                # Surgery
                surgeries = Surgery.objects.filter(diagnosis=diagnosis)
                patient_data['surgeries'].extend(
                    SurgerySerializer(surgeries, many=True, context=context).data
                )

                # Concomitant Medications
                medications = ConcomitantMedications.objects.filter(diagnosis=diagnosis)
                patient_data['concomitant_medications'].extend(
                    ConcomitantMedicationsSerializer(medications, many=True, context=context).data
                )

                # Systemic Therapy and Schedules
                systemic_therapies = SystemicTherapy.objects.filter(diagnosis=diagnosis)
                patient_data['systemic_therapies'].extend(
                    SystemicTherapySerializer(systemic_therapies, many=True, context=context).data
                )

                for therapy in systemic_therapies:
                    schedules = SystemicTherapySchedule.objects.filter(systemic_therapy=therapy)
                    patient_data['systemic_therapy_schedules'].extend(
                        SystemicTherapyScheduleSerializer(schedules, many=True, context=context).data
                    )

                # Adverse Effects
                adverse_effects = AdverseEffects.objects.filter(diagnosis=diagnosis)
                patient_data['adverse_effects'].extend(
                    AdverseEffectsSerializer(adverse_effects, many=True, context=context).data
                )

                # Stage Information
                stage_info = StageInformation.objects.filter(diagnosis=diagnosis)
                patient_data['stage_information'].extend(
                    StageInformationSerializer(stage_info, many=True, context=context).data
                )

            # Patient Reported Outcomes
            patient_reported_outcomes = PatientReportedOutcome.objects.filter(patient=patient)
            patient_data['patient_reported_outcomes'].extend(
                PatientReportedOutcomeSerializer(patient_reported_outcomes, many=True, context=context).data
            )

            # Patient Outcomes
            patient_outcomes = PatientOutcome.objects.filter(patient=patient)
            patient_data['patient_outcomes'].extend(
                PatientOutcomeSerializer(patient_outcomes, many=True, context=context).data
            )

            # Comorbidities
            comorbidities = Comorbidity.objects.filter(patient=patient)
            patient_data['comorbidities'].extend(
                ComorbiditySerializer(comorbidities, many=True, context=context).data
            )

            # Somatic Genomic Alterations
            genomic_alterations = GermlineGenomicAlterations.objects.filter(patient=patient)
            patient_data['germline_genomic_alterations'].extend(
                GermlineGenomicAlterationsSerializer(genomic_alterations, many=True, context=context).data
            )

            # Symptoms
            symptoms = Symptom.objects.filter(patient=patient)
            patient_data['symptoms'].extend(
                SymptomSerializer(symptoms, many=True, context=context).data
            )

            # Patient Assessments
            patient_assessments = PatientAssessment.objects.filter(patient=patient)
            patient_data['patient_assessments'].extend(
                PatientAssessmentSerializer(patient_assessments, many=True, context=context).data
            )

            # Laboratory Results
            lab_results = LaboratoryResults.objects.filter(patient=patient)
            patient_data['laboratory_results'].extend(
                LaboratoryResultsSerializer(lab_results, many=True, context=context).data
            )

            # Create a unique filename using a hash of the patient ID
            # This ensures privacy by not using the actual patient ID in the filename
            # while still maintaining uniqueness
            patient_json = json.dumps(patient_data, indent=2, cls=UUIDEncoder)
            patient_id_hash = hashlib.sha256(str(patient.patient_id).encode()).hexdigest()
            filename = f"patient_{patient_id_hash}_data.json"
            zip_file.writestr(filename, patient_json)

    # Prepare the HTTP response
    # First, reset the buffer position to the beginning
    zip_buffer.seek(0)
    
    # Create the HTTP response with the zip file content
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    # Set the filename for the downloaded zip file
    response['Content-Disposition'] = f'attachment; filename="patient_data_export_{queryset.count()}_patients.zip"'
    
    return response

def export_patient_data_to_file(queryset, zip_path, request=None):
    """
    Export patient data to a ZIP file on disk.
    
    This function creates a ZIP file containing individual JSON files for each patient
    with all their related clinical data. Used by the DICOM export to optionally
    include patient data alongside DICOM files.
    
    Args:
        queryset: Django QuerySet of Patient objects to export
        zip_path: Path object or string path where the ZIP file should be created
        request: Optional HttpRequest object for serializer context
        
    Returns:
        dict: Result with success status, counts, and file information
    """
    from pathlib import Path
    
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create context for serializers
    context = {'request': request} if request else {}
    
    total_patients = queryset.count()
    processed_patients = 0
    total_files = 0
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for patient in queryset:
            patient_data = {
                'patients': [],
                'dicom_studies': [],
                'diagnoses': [],
                'outcomes': [],
                'lesions': [],
                'lesion_responses': [],
                'germline_genomic_alterations': [],
                'pathologies': [],
                'immunohistochemistries': [],
                'cytogenetics': [],
                'somatic_genomic_alterations': [],
                'gene_expression_data': [],
                'epigenetic_data': [],
                'other_treatments': [],
                'radiotherapies': [],
                'radiotherapy_volumes': [],
                'radiotherapy_dose_volume_data': [],
                'surgeries': [],
                'concomitant_medications': [],
                'systemic_therapies': [],
                'systemic_therapy_schedules': [],
                'adverse_effects': [],
                'pro_instruments': [],
                'pro_domains': [],
                'pro_questions': [],
                'patient_reported_outcomes': [],
                'patient_outcomes': [],
                'comorbidities': [],
                'stage_information': [],
                'laboratory_results': [],
                'symptoms': [],
                'patient_assessments': [],
                'dicom_study_projects': []
            }

            # Serialize the patient's basic information
            patient_data['patients'].append(
                PatientSerializer(patient, context=context).data
            )

            # Collect and serialize DICOM studies
            dicom_studies = DICOMStudy.objects.filter(patient=patient)
            patient_data['dicom_studies'].extend(
                DICOMStudySerializer(dicom_studies, many=True, context=context).data
            )

            # Collect DICOM study projects
            dicom_study_projects = DICOMStudyProject.objects.filter(study_instance_uid__patient=patient)
            patient_data['dicom_study_projects'].extend(
                DICOMStudyProjectSerializer(dicom_study_projects, many=True, context=context).data
            )

            # Collect all diagnoses for this patient
            diagnoses = Diagnosis.objects.filter(patient=patient)
            patient_data['diagnoses'].extend(
                DiagnosisSerializer(diagnoses, many=True, context=context).data
            )

            # For each diagnosis, collect all related information
            for diagnosis in diagnoses:
                # Collect outcome data for this diagnosis
                outcomes = Outcome.objects.filter(diagnosis=diagnosis)
                patient_data['outcomes'].extend(
                    OutcomeSerializer(outcomes, many=True, context=context).data
                )

                # Collect lesion data and their responses
                lesions = Lesion.objects.filter(diagnosis=diagnosis)
                patient_data['lesions'].extend(
                    LesionSerializer(lesions, many=True, context=context).data
                )

                # For each lesion, collect response data
                for lesion in lesions:
                    lesion_responses = LesionResponse.objects.filter(lesion=lesion)
                    patient_data['lesion_responses'].extend(
                        LesionResponseSerializer(lesion_responses, many=True, context=context).data
                    )

                # Collect pathology data and related information
                pathologies = Pathology.objects.filter(diagnosis=diagnosis)
                patient_data['pathologies'].extend(
                    PathologySerializer(pathologies, many=True, context=context).data
                )

                # For each pathology record, collect related data
                for pathology in pathologies:
                    immunohistochemistries = Immunohistochemistry.objects.filter(pathology=pathology)
                    patient_data['immunohistochemistries'].extend(
                        ImmunohistochemistrySerializer(immunohistochemistries, many=True, context=context).data
                    )

                    cytogenetics = Cytogenetics.objects.filter(pathology=pathology)
                    patient_data['cytogenetics'].extend(
                        CytogeneticsSerializer(cytogenetics, many=True, context=context).data
                    )

                    genomic_alterations = SomaticGenomicAlterations.objects.filter(pathology=pathology)
                    patient_data['somatic_genomic_alterations'].extend(
                        SomaticGenomicAlterationsSerializer(genomic_alterations, many=True, context=context).data
                    )

                    gene_expression_data = GeneExpressionData.objects.filter(pathology=pathology)
                    patient_data['gene_expression_data'].extend(
                        GeneExpressionDataSerializer(gene_expression_data, many=True, context=context).data
                    )

                    epigenetic_data = EpigeneticData.objects.filter(pathology=pathology)
                    patient_data['epigenetic_data'].extend(
                        EpigeneticDataSerializer(epigenetic_data, many=True, context=context).data
                    )

                # Collect treatment-related data
                other_treatments = OtherTreatment.objects.filter(diagnosis=diagnosis)
                patient_data['other_treatments'].extend(
                    OtherTreatmentSerializer(other_treatments, many=True, context=context).data
                )

                radiotherapies = Radiotherapy.objects.filter(diagnosis=diagnosis)
                patient_data['radiotherapies'].extend(
                    RadiotherapySerializer(radiotherapies, many=True, context=context).data
                )

                for radiotherapy in radiotherapies:
                    rt_volumes = RadiotherapyVolume.objects.filter(radiotherapy=radiotherapy)
                    patient_data['radiotherapy_volumes'].extend(
                        RadiotherapyVolumeSerializer(rt_volumes, many=True, context=context).data
                    )

                    rt_dose_volumes = RadiotherapyDoseVolumeData.objects.filter(radiotherapy=radiotherapy)
                    patient_data['radiotherapy_dose_volume_data'].extend(
                        RadiotherapyDoseVolumeDataSerializer(rt_dose_volumes, many=True, context=context).data
                    )

                surgeries = Surgery.objects.filter(diagnosis=diagnosis)
                patient_data['surgeries'].extend(
                    SurgerySerializer(surgeries, many=True, context=context).data
                )

                medications = ConcomitantMedications.objects.filter(diagnosis=diagnosis)
                patient_data['concomitant_medications'].extend(
                    ConcomitantMedicationsSerializer(medications, many=True, context=context).data
                )

                systemic_therapies = SystemicTherapy.objects.filter(diagnosis=diagnosis)
                patient_data['systemic_therapies'].extend(
                    SystemicTherapySerializer(systemic_therapies, many=True, context=context).data
                )

                for therapy in systemic_therapies:
                    schedules = SystemicTherapySchedule.objects.filter(systemic_therapy=therapy)
                    patient_data['systemic_therapy_schedules'].extend(
                        SystemicTherapyScheduleSerializer(schedules, many=True, context=context).data
                    )

                adverse_effects = AdverseEffects.objects.filter(diagnosis=diagnosis)
                patient_data['adverse_effects'].extend(
                    AdverseEffectsSerializer(adverse_effects, many=True, context=context).data
                )

                stage_info = StageInformation.objects.filter(diagnosis=diagnosis)
                patient_data['stage_information'].extend(
                    StageInformationSerializer(stage_info, many=True, context=context).data
                )

            # Patient Reported Outcomes
            patient_reported_outcomes = PatientReportedOutcome.objects.filter(patient=patient)
            patient_data['patient_reported_outcomes'].extend(
                PatientReportedOutcomeSerializer(patient_reported_outcomes, many=True, context=context).data
            )

            # Patient Outcomes
            patient_outcomes = PatientOutcome.objects.filter(patient=patient)
            patient_data['patient_outcomes'].extend(
                PatientOutcomeSerializer(patient_outcomes, many=True, context=context).data
            )

            # Comorbidities
            comorbidities = Comorbidity.objects.filter(patient=patient)
            patient_data['comorbidities'].extend(
                ComorbiditySerializer(comorbidities, many=True, context=context).data
            )

            # Germline Genomic Alterations
            genomic_alterations = GermlineGenomicAlterations.objects.filter(patient=patient)
            patient_data['germline_genomic_alterations'].extend(
                GermlineGenomicAlterationsSerializer(genomic_alterations, many=True, context=context).data
            )

            # Symptoms
            symptoms = Symptom.objects.filter(patient=patient)
            patient_data['symptoms'].extend(
                SymptomSerializer(symptoms, many=True, context=context).data
            )

            # Patient Assessments
            patient_assessments = PatientAssessment.objects.filter(patient=patient)
            patient_data['patient_assessments'].extend(
                PatientAssessmentSerializer(patient_assessments, many=True, context=context).data
            )

            # Laboratory Results
            lab_results = LaboratoryResults.objects.filter(patient=patient)
            patient_data['laboratory_results'].extend(
                LaboratoryResultsSerializer(lab_results, many=True, context=context).data
            )

            # Create a unique filename using a hash of the patient ID
            patient_json = json.dumps(patient_data, indent=2, cls=UUIDEncoder)
            patient_id_hash = hashlib.sha256(str(patient.patient_id).encode()).hexdigest()
            filename = f"patient_{patient_id_hash}_data.json"
            zip_file.writestr(filename, patient_json)
            total_files += 1
            processed_patients += 1
    
    return {
        'success': True,
        'processed_patients': processed_patients,
        'total_files': total_files,
        'zip_path': str(zip_path),
        'zip_size': zip_path.stat().st_size if zip_path.exists() else 0
    }


# Short description for the admin interface
export_patient_data.short_description = "Export selected patients' data as JSON files (zipped)" 