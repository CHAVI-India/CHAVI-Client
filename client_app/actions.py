from django.http import HttpResponse
from .models import *
from .serializers import *
import json
import uuid

class UUIDEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle UUID objects"""
    def default(self, obj):
        if isinstance(obj, uuid.UUID):
            # Convert UUID to string
            return str(obj)
        return super().default(obj)

def export_patient_data(modeladmin, request, queryset):
    """
    Admin action to export all related data for selected patients as JSON
    """
    # Dictionary to store all serialized data
    export_data = {
        'patients': [],
        'dicom_studies': [],
        'diagnoses': [],
        'outcomes': [],
        'lesions': [],
        'lesion_responses': [],
        'pathologies': [],
        'immunohistochemistries': [],
        'cytogenetics': [],
        'somatic_genomic_alterations': [],
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
        'dicom_study_projects': []
    }

    context = {'request': request}

    # Serialize patient data and all related information
    for patient in queryset:
        # Patient data
        export_data['patients'].append(
            PatientSerializer(patient, context=context).data
        )

        # DICOM Studies
        dicom_studies = DICOMStudy.objects.filter(patient=patient)
        export_data['dicom_studies'].extend(
            DICOMStudySerializer(dicom_studies, many=True, context=context).data
        )

        # DICOM Study Projects
        dicom_study_projects = DICOMStudyProject.objects.filter(dicom_study__patient=patient)
        export_data['dicom_study_projects'].extend(
            DICOMStudyProjectSerializer(dicom_study_projects, many=True, context=context).data
        )

        # Diagnoses and related data
        diagnoses = Diagnosis.objects.filter(patient=patient)
        export_data['diagnoses'].extend(
            DiagnosisSerializer(diagnoses, many=True, context=context).data
        )

        for diagnosis in diagnoses:
            # Outcomes
            outcomes = Outcome.objects.filter(diagnosis=diagnosis)
            export_data['outcomes'].extend(
                OutcomeSerializer(outcomes, many=True, context=context).data
            )

            # Lesions and responses
            lesions = Lesion.objects.filter(diagnosis=diagnosis)
            export_data['lesions'].extend(
                LesionSerializer(lesions, many=True, context=context).data
            )

            for lesion in lesions:
                lesion_responses = LesionResponse.objects.filter(lesion=lesion)
                export_data['lesion_responses'].extend(
                    LesionResponseSerializer(lesion_responses, many=True, context=context).data
                )

            # Pathology and related data
            pathologies = Pathology.objects.filter(diagnosis=diagnosis)
            export_data['pathologies'].extend(
                PathologySerializer(pathologies, many=True, context=context).data
            )

            for pathology in pathologies:
                # Immunohistochemistry
                immunohistochemistries = Immunohistochemistry.objects.filter(pathology=pathology)
                export_data['immunohistochemistries'].extend(
                    ImmunohistochemistrySerializer(immunohistochemistries, many=True, context=context).data
                )

                # Cytogenetics
                cytogenetics = Cytogenetics.objects.filter(pathology=pathology)
                export_data['cytogenetics'].extend(
                    CytogeneticsSerializer(cytogenetics, many=True, context=context).data
                )

                # Somatic Genomic Alterations
                genomic_alterations = SomaticGenomicAlterations.objects.filter(pathology=pathology)
                export_data['somatic_genomic_alterations'].extend(
                    SomaticGenomicAlterationsSerializer(genomic_alterations, many=True, context=context).data
                )

            # Treatments
            other_treatments = OtherTreatment.objects.filter(diagnosis=diagnosis)
            export_data['other_treatments'].extend(
                OtherTreatmentSerializer(other_treatments, many=True, context=context).data
            )

            # Radiotherapy and related data
            radiotherapies = Radiotherapy.objects.filter(diagnosis=diagnosis)
            export_data['radiotherapies'].extend(
                RadiotherapySerializer(radiotherapies, many=True, context=context).data
            )

            for radiotherapy in radiotherapies:
                # Radiotherapy Volumes
                rt_volumes = RadiotherapyVolume.objects.filter(radiotherapy=radiotherapy)
                export_data['radiotherapy_volumes'].extend(
                    RadiotherapyVolumeSerializer(rt_volumes, many=True, context=context).data
                )

                # Radiotherapy Dose Volume Data
                rt_dose_volumes = RadiotherapyDoseVolumeData.objects.filter(radiotherapy=radiotherapy)
                export_data['radiotherapy_dose_volume_data'].extend(
                    RadiotherapyDoseVolumeDataSerializer(rt_dose_volumes, many=True, context=context).data
                )

            # Surgery
            surgeries = Surgery.objects.filter(diagnosis=diagnosis)
            export_data['surgeries'].extend(
                SurgerySerializer(surgeries, many=True, context=context).data
            )

            # Concomitant Medications
            medications = ConcomitantMedications.objects.filter(diagnosis=diagnosis)
            export_data['concomitant_medications'].extend(
                ConcomitantMedicationsSerializer(medications, many=True, context=context).data
            )

            # Systemic Therapy and Schedules
            systemic_therapies = SystemicTherapy.objects.filter(diagnosis=diagnosis)
            export_data['systemic_therapies'].extend(
                SystemicTherapySerializer(systemic_therapies, many=True, context=context).data
            )

            for therapy in systemic_therapies:
                schedules = SystemicTherapySchedule.objects.filter(systemic_therapy=therapy)
                export_data['systemic_therapy_schedules'].extend(
                    SystemicTherapyScheduleSerializer(schedules, many=True, context=context).data
                )

            # Adverse Effects
            adverse_effects = AdverseEffects.objects.filter(diagnosis=diagnosis)
            export_data['adverse_effects'].extend(
                AdverseEffectsSerializer(adverse_effects, many=True, context=context).data
            )

            # Stage Information
            stage_info = StageInformation.objects.filter(diagnosis=diagnosis)
            export_data['stage_information'].extend(
                StageInformationSerializer(stage_info, many=True, context=context).data
            )

        # Patient-specific data (not diagnosis-related)
        # PRO Instruments, Domains, and Questions
        pro_instruments = ProInstrument.objects.all()
        export_data['pro_instruments'].extend(
            ProInstrumentSerializer(pro_instruments, many=True, context=context).data
        )

        pro_domains = ProDomain.objects.filter(instrument__in=pro_instruments)
        export_data['pro_domains'].extend(
            ProDomainSerializer(pro_domains, many=True, context=context).data
        )

        pro_questions = ProQuestion.objects.filter(domain__in=pro_domains)
        export_data['pro_questions'].extend(
            ProQuestionSerializer(pro_questions, many=True, context=context).data
        )

        # Patient Reported Outcomes
        patient_reported_outcomes = PatientReportedOutcome.objects.filter(patient=patient)
        export_data['patient_reported_outcomes'].extend(
            PatientReportedOutcomeSerializer(patient_reported_outcomes, many=True, context=context).data
        )

        # Patient Outcomes
        patient_outcomes = PatientOutcome.objects.filter(patient=patient)
        export_data['patient_outcomes'].extend(
            PatientOutcomeSerializer(patient_outcomes, many=True, context=context).data
        )

        # Comorbidities
        comorbidities = Comorbidity.objects.filter(patient=patient)
        export_data['comorbidities'].extend(
            ComorbiditySerializer(comorbidities, many=True, context=context).data
        )

        # Laboratory Results
        lab_results = LaboratoryResults.objects.filter(patient=patient)
        export_data['laboratory_results'].extend(
            LaboratoryResultsSerializer(lab_results, many=True, context=context).data
        )

    # Create the response with the JSON file
    response = HttpResponse(
        json.dumps(export_data, indent=2, cls=UUIDEncoder), 
        content_type='application/json'
    )
    filename = f"patient_data_export_{queryset.count()}_patients.json"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

export_patient_data.short_description = "Export selected patients' data as JSON" 