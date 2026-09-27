from django.shortcuts import render, redirect, get_object_or_404
import os
import uuid
from django.conf import settings
from django.views.static import serve
from django.views.generic import TemplateView, View, ListView, CreateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from unfold.views import UnfoldModelAdminViewMixin
from .models import *
from .models import _make_canonical_id, TaskRun, Notification
from django.urls import reverse, reverse_lazy
from django.http import Http404, JsonResponse
from django.contrib import admin, messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .tasks import (
    task_extract_and_analyze_upload,
    task_process_confirmed_matches,
    task_export_patient_data,
    task_export_dicom_data_parallel,
    task_export_dicom_data,
    task_process_dicom_per_patient,
    task_process_bulk_dicom,
    task_process_unprocessed_dicom,
    task_associate_dicom_to_project,
)
from django.db import transaction
from django.db.models import Q
from rapidfuzz import process as fuzz_process, fuzz
from django.utils import timezone

# Create your views here.

def custom_403_view(request, exception=None):
    """Custom 403 error page view that works in both DEBUG and production modes."""
    return render(request, '403.html', status=403)

class HomePageView(TemplateView):
    """View for the application homepage."""
    template_name = "client_app/homepage.html"

def documentation_view(request, path=''):
    """Serve the Sphinx documentation."""
    doc_root = os.path.join(settings.BASE_DIR, 'docs', '_build', 'html')
    if not path:
        path = 'index.html'
    return serve(request, path, document_root=doc_root)

class PatientSummaryView(LoginRequiredMixin, TemplateView):
    """View for displaying patient summary and related data."""
    template_name = "client_app/patient_summary_new.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Debug: Print all GET parameters
        print("GET parameters:", self.request.GET)
        
        patient_id = self.request.GET.get('patient_id')
        
        # Debug: Print the patient_id parameter
        print("Patient ID from GET:", patient_id)
        
        if not patient_id:
            raise Http404("Patient ID is required")
            
        patient = get_object_or_404(Patient, patient_id=patient_id)
        
        # Debug: Print the patient object found
        print(f"Found patient: ID={patient.patient_id}, patient_id={patient.patient_id}")
        
        # Set title for the template
        context['title'] = f"Patient Summary: {patient.patient_id}"
        
        # Get related data to the patient
        diagnoses = Diagnosis.objects.filter(patient=patient)
        
        # Debug: Print diagnoses count
        print(f"Diagnoses count for patient {patient.patient_id}: {diagnoses.count()}")
        if diagnoses.count() > 0:
            print("First diagnosis:", diagnoses.first().diagnosis)
            print("First diagnosis ID:", diagnoses.first().chavi_diagnosis_id)
        
        comorbidities = Comorbidity.objects.filter(patient=patient)
        symptoms = Symptom.objects.filter(patient=patient)
        assessments = PatientAssessment.objects.filter(patient=patient)
        laboratory_results = LaboratoryResults.objects.filter(patient=patient)
        patient_reported_outcomes = PatientReportedOutcome.objects.filter(patient=patient)
        patient_outcomes = PatientOutcome.objects.filter(patient=patient)
        germline_mutations = GermlineGenomicAlterations.objects.filter(patient=patient)
        dicom_studies = DICOMStudy.objects.filter(patient=patient)
        
        # Get counts for patient-related data
        comorbidities_count = comorbidities.count()
        symptoms_count = symptoms.count()
        assessments_count = assessments.count()
        laboratory_results_count = laboratory_results.count()
        patient_reported_outcomes_count = patient_reported_outcomes.count()
        patient_outcomes_count = patient_outcomes.count()
        germline_mutations_count = germline_mutations.count()
        dicom_studies_count = dicom_studies.count()
        # Create a list to hold all diagnosis data with related objects and counts
        diagnosis_data = []
        
        # Get data related to each diagnosis
        for diagnosis in diagnoses:
            # Debug: Print each diagnosis being processed
            print(f"Processing diagnosis: {diagnosis.diagnosis} (ID: {diagnosis.chavi_diagnosis_id})")
            
            # Fetch all related data objects
            pathologies = Pathology.objects.filter(diagnosis=diagnosis)
            stage_information = StageInformation.objects.filter(diagnosis=diagnosis)
            lesions = Lesion.objects.filter(diagnosis=diagnosis)
            surgeries = Surgery.objects.filter(diagnosis=diagnosis)
            systemic_therapies = SystemicTherapy.objects.filter(diagnosis=diagnosis)
            radiotherapies = Radiotherapy.objects.filter(diagnosis=diagnosis)
            other_treatments = OtherTreatment.objects.filter(diagnosis=diagnosis)
            concomitant_medications = ConcomitantMedications.objects.filter(diagnosis=diagnosis)
            outcomes = Outcome.objects.filter(diagnosis=diagnosis)
            adverse_effects = AdverseEffects.objects.filter(diagnosis=diagnosis)
            # The Symptom model doesn't have a diagnosis field, so we can't filter by it
            symptoms_for_diagnosis = Symptom.objects.filter(patient=patient)
            
            # Get lesion response data for each lesion
            lesions_with_responses = []
            for lesion in lesions:
                lesion_responses = LesionResponse.objects.filter(lesion=lesion)
                lesions_with_responses.append({
                    'lesion': lesion,
                    'responses': lesion_responses,
                    'responses_count': lesion_responses.count()
                })
            
            # Get pathology child data for each pathology
            pathologies_with_children = []
            for pathology in pathologies:
                ihc_tests = Immunohistochemistry.objects.filter(pathology=pathology)
                cytogenetics_tests = Cytogenetics.objects.filter(pathology=pathology)
                somatic_alterations = SomaticGenomicAlterations.objects.filter(pathology=pathology)
                gene_expression = GeneExpressionData.objects.filter(pathology=pathology)
                epigenetic_data = EpigeneticData.objects.filter(pathology=pathology)
                pathologies_with_children.append({
                    'pathology': pathology,
                    'ihc_tests': ihc_tests,
                    'ihc_count': ihc_tests.count(),
                    'cytogenetics_tests': cytogenetics_tests,
                    'cytogenetics_count': cytogenetics_tests.count(),
                    'somatic_alterations': somatic_alterations,
                    'somatic_count': somatic_alterations.count(),
                    'gene_expression': gene_expression,
                    'gene_expression_count': gene_expression.count(),
                    'epigenetic_data': epigenetic_data,
                    'epigenetic_count': epigenetic_data.count()
                })
            
            # Get systemic therapy schedule data for each systemic therapy
            systemic_therapies_with_schedules = []
            for systemic_therapy in systemic_therapies:
                schedules = SystemicTherapySchedule.objects.filter(systemic_therapy=systemic_therapy)
                systemic_therapies_with_schedules.append({
                    'systemic_therapy': systemic_therapy,
                    'schedules': schedules,
                    'schedules_count': schedules.count()
                })
            
            # Get radiotherapy child data for each radiotherapy
            radiotherapies_with_children = []
            for radiotherapy in radiotherapies:
                volumes = RadiotherapyVolume.objects.filter(radiotherapy=radiotherapy)
                dose_volumes = RadiotherapyDoseVolumeData.objects.filter(radiotherapy=radiotherapy)
                radiotherapies_with_children.append({
                    'radiotherapy': radiotherapy,
                    'volumes': volumes,
                    'volumes_count': volumes.count(),
                    'dose_volumes': dose_volumes,
                    'dose_volumes_count': dose_volumes.count()
                })
            
            # Organize data into sections
            diagnosis_info = {
                'diagnosis': diagnosis,
                
                # Diagnostic Information section
                'diagnostic_data': {
                    'pathologies': {
                        'objects': pathologies,
                        'count': pathologies.count(),
                        'pathologies_with_children': pathologies_with_children
                    },
                    'stage_information': {
                        'objects': stage_information,
                        'count': stage_information.count()
                    },
                    'lesions': {
                        'objects': lesions,
                        'count': lesions.count(),
                        'lesions_with_responses': lesions_with_responses
                    }
                },
                
                # Treatment Information section
                'treatment_data': {
                    'surgeries': {
                        'objects': surgeries,
                        'count': surgeries.count()
                    },
                    'systemic_therapies': {
                        'objects': systemic_therapies,
                        'count': systemic_therapies.count(),
                        'systemic_therapies_with_schedules': systemic_therapies_with_schedules
                    },
                    'radiotherapies': {
                        'objects': radiotherapies,
                        'count': radiotherapies.count(),
                        'radiotherapies_with_children': radiotherapies_with_children
                    },
                    'other_treatments': {
                        'objects': other_treatments,
                        'count': other_treatments.count()
                    },
                    'concomitant_medications': {
                        'objects': concomitant_medications,
                        'count': concomitant_medications.count()
                    }
                },
                
                # Outcomes and Adverse Effects section
                'outcome_data': {
                    'outcomes': {
                        'objects': outcomes,
                        'count': outcomes.count()
                    },
                    'adverse_effects': {
                        'objects': adverse_effects,
                        'count': adverse_effects.count()
                    }
                },
                
            }
            
            # Add all diagnosis data to the list
            diagnosis_data.append(diagnosis_info)
        
        # Debug: Print final diagnosis_data length
        print(f"Final diagnosis_data length: {len(diagnosis_data)}")
        
        # Add all data to context
        context['patient'] = patient
        context['diagnoses'] = diagnoses
        context['diagnoses_count'] = diagnoses.count()
        context['diagnoses_data'] = diagnosis_data  # This should match the name used in the template
        context['diagnosis_data'] = diagnosis_data
        
        # Add patient-related objects to context
        context['comorbidities'] = {
            'objects': comorbidities,
            'count': comorbidities_count
        }
        context['patient_assessments'] = {
            'objects': assessments,
            'count': assessments_count
        }
        context['laboratory_results'] = {
            'objects': laboratory_results,
            'count': laboratory_results_count
        }
        context['patient_reported_outcomes'] = {
            'objects': patient_reported_outcomes,
            'count': patient_reported_outcomes_count
        }
        context['patient_outcomes'] = {
            'objects': patient_outcomes,
            'count': patient_outcomes_count
        }
        context['patient_symptoms'] = {
            'objects': symptoms,  # All symptoms are already filtered by patient
            'count': symptoms.count()
        }
        context['germline_mutations'] = {
            'objects': germline_mutations,
            'count': germline_mutations_count
        }
        context['dicom_studies'] = {
            'objects': dicom_studies,
            'count': dicom_studies_count
        }
        
        return context

class PatientSearchView(LoginRequiredMixin, TemplateView):
    """View for searching patients and redirecting to their summary page."""
    template_name = "client_app/patient_search.html"
    patients_per_page = 20
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Patient Search"
        
        search_term = self.request.GET.get('search', '')
        page = self.request.GET.get('page', 1)
        
        # Get the queryset based on search term
        if search_term:
            patient_list = Patient.objects.filter(patient_id__icontains=search_term).order_by('patient_id')
        else:
            # Otherwise show most recent patients
            patient_list = Patient.objects.all().order_by('-created_at')
        
        # Set up pagination
        paginator = Paginator(patient_list, self.patients_per_page)
        
        try:
            patients = paginator.page(page)
        except PageNotAnInteger:
            # If page is not an integer, deliver first page
            patients = paginator.page(1)
        except EmptyPage:
            # If page is out of range, deliver last page
            patients = paginator.page(paginator.num_pages)
            
        context.update({
            'patients': patients,
            'search_term': search_term,
            'total_patients': patient_list.count()
        })
        return context
    
    def post(self, request):
        patient_id = request.POST.get('patient_id', '')
        if patient_id:
            try:
                patient = Patient.objects.get(patient_id=patient_id)
                return redirect('admin:patient-summary', patient_id=patient.patient_id)
            except Patient.DoesNotExist:
                return render(request, 'client_app/patient_search.html', {
                    'error': f'Patient with ID {patient_id} not found',
                    'patients': Patient.objects.all().order_by('-created_at')[:self.patients_per_page]
                })
        return render(request, 'client_app/patient_search.html', {
            'error': 'Please enter a patient ID',
            'patients': Patient.objects.all().order_by('-created_at')[:self.patients_per_page]
        })


# Bulk DICOM Upload Views

class BulkDICOMUploadView(LoginRequiredMixin, TemplateView):
    """View for uploading bulk DICOM zip files"""
    template_name = "client_app/bulk_dicom_upload.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Bulk DICOM Upload"
        return context
    
    def post(self, request):
        """Handle file upload"""
        if 'dicom_file' not in request.FILES:
            messages.error(request, "No file uploaded")
            return redirect('client_app:bulk_dicom_upload')
        
        uploaded_file = request.FILES['dicom_file']
        
        # Validate file extension
        if not uploaded_file.name.endswith('.zip'):
            messages.error(request, "Only ZIP files are allowed")
            return redirect('client_app:bulk_dicom_upload')
        
        try:
            # Create upload session
            session = BulkDICOMUploadSession.objects.create(
                uploaded_file=uploaded_file,
                uploaded_by=request.user,
                status=BulkDICOMUploadSession.StatusChoices.UPLOADED
            )
            
            # Dispatch Celery task for extraction and analysis
            task_result = task_extract_and_analyze_upload.delay(
                str(session.session_id), request.user.id
            )
            session.celery_task_id = task_result.id
            session.save(update_fields=['celery_task_id'])

            messages.success(request, f"Upload received. Analyzing {uploaded_file.name} in background...")
            return redirect('client_app:task_progress', task_id=task_result.id)
                
        except Exception as e:
            messages.error(request, f"Error processing upload: {str(e)}")
            return redirect('client_app:bulk_dicom_upload')


def _get_fuzzy_patient_suggestions(dicom_patient_id, patient_qs, top_n=3, score_cutoff=30):
    """Return top_n fuzzy-matched patients for a given DICOM patient ID.
    Each result is a dict: {patient_id, gender, score}.
    Normalises IDs before scoring so separator/prefix differences don't
    penalise otherwise-identical numeric cores (e.g. '25_004771' vs 'MR/25/004771').
    """
    norm_query = _make_canonical_id(dicom_patient_id)
    all_ids = list(patient_qs.values_list('patient_id', 'gender'))
    # Map normalised key -> (original_pid, gender)
    choices = {_make_canonical_id(pid): (pid, gender) for pid, gender in all_ids}
    matches = fuzz_process.extract(
        norm_query,
        list(choices.keys()),
        scorer=fuzz.partial_ratio,
        limit=top_n,
        score_cutoff=score_cutoff,
    )
    return [
        {
            'patient_id': choices[match[0]][0],
            'gender': choices[match[0]][1] or 'N/A',
            'score': round(match[1]),
        }
        for match in matches
    ]


class BulkDICOMMatchingView(LoginRequiredMixin, TemplateView):
    """View for matching DICOM studies to patients"""
    template_name = "client_app/bulk_dicom_matching.html"

    def dispatch(self, request, *args, **kwargs):
        session_id = kwargs.get('session_id')
        session = get_object_or_404(BulkDICOMUploadSession, session_id=session_id)
        if session.status in (BulkDICOMUploadSession.StatusChoices.COMPLETED,
                              BulkDICOMUploadSession.StatusChoices.PROCESSING):
            return redirect('client_app:bulk_dicom_complete', session_id=session.session_id)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session_id = self.kwargs.get('session_id')
        
        session = get_object_or_404(BulkDICOMUploadSession, session_id=session_id)
        
        # Get all study matches for this session
        study_matches = BulkDICOMStudyMatch.objects.filter(session=session).order_by('match_status', 'dicom_patient_id')
        
        # Separate auto-matched and manual match required
        auto_matched = study_matches.filter(match_status=BulkDICOMStudyMatch.MatchStatus.AUTO_MATCHED)
        manual_required = study_matches.filter(match_status=BulkDICOMStudyMatch.MatchStatus.MANUAL_MATCH_REQUIRED)
        manually_matched = study_matches.filter(match_status=BulkDICOMStudyMatch.MatchStatus.MANUALLY_MATCHED)
        
        # Get all patients for the select2 dropdown
        patients = Patient.objects.all().order_by('patient_id')
        
        # Attach fuzzy suggestions to each manual_required study
        manual_required_with_suggestions = []
        for study in manual_required:
            suggestions = _get_fuzzy_patient_suggestions(study.dicom_patient_id, patients)
            manual_required_with_suggestions.append({
                'study': study,
                'suggestions': suggestions,
                'top_suggestion': suggestions[0] if suggestions else None,
            })
        
        context.update({
            'title': 'Match DICOM Studies to Patients',
            'session': session,
            'auto_matched': auto_matched,
            'manual_required': manual_required,
            'manual_required_with_suggestions': manual_required_with_suggestions,
            'manually_matched': manually_matched,
            'patients': patients,
            'total_studies': study_matches.count(),
        })
        
        return context
    
    def post(self, request, session_id):
        """Handle patient matching"""
        session = get_object_or_404(BulkDICOMUploadSession, session_id=session_id)
        
        # Get all study matches that need manual matching
        manual_matches = BulkDICOMStudyMatch.objects.filter(
            session=session,
            match_status=BulkDICOMStudyMatch.MatchStatus.MANUAL_MATCH_REQUIRED
        )
        
        matched_count = 0
        unmatched_count = 0
        
        for study_match in manual_matches:
            # Check if a patient was selected for this study
            patient_id = request.POST.get(f'patient_{study_match.match_id}')
            
            if patient_id:
                # Patient selected - mark as manually matched
                try:
                    patient = Patient.objects.get(patient_id=patient_id)
                    study_match.matched_patient = patient
                    study_match.match_status = BulkDICOMStudyMatch.MatchStatus.MANUALLY_MATCHED
                    study_match.save()
                    matched_count += 1
                except Patient.DoesNotExist:
                    messages.error(request, f"Patient {patient_id} not found")
            else:
                # No patient selected - mark as unmatched
                study_match.match_status = BulkDICOMStudyMatch.MatchStatus.UNMATCHED
                study_match.matched_patient = None
                study_match.save()
                unmatched_count += 1
        
        if matched_count > 0:
            messages.success(request, f"Successfully matched {matched_count} studies")
        
        if unmatched_count > 0:
            messages.info(request, f"{unmatched_count} studies marked as unmatched and will be moved to unprocessed folder")
        
        # All studies have been processed, proceed to confirmation
        session.status = BulkDICOMUploadSession.StatusChoices.MATCHING
        session.save()
        return redirect('client_app:bulk_dicom_confirmation', session_id=session.session_id)


class BulkDICOMConfirmationView(LoginRequiredMixin, TemplateView):
    """View for confirming patient matches before processing"""
    template_name = "client_app/bulk_dicom_confirmation.html"

    def dispatch(self, request, *args, **kwargs):
        session_id = kwargs.get('session_id')
        session = get_object_or_404(BulkDICOMUploadSession, session_id=session_id)
        if session.status in (BulkDICOMUploadSession.StatusChoices.COMPLETED,
                              BulkDICOMUploadSession.StatusChoices.PROCESSING):
            return redirect('client_app:bulk_dicom_complete', session_id=session.session_id)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session_id = self.kwargs.get('session_id')
        
        session = get_object_or_404(BulkDICOMUploadSession, session_id=session_id)
        
        # Get all study matches
        study_matches = BulkDICOMStudyMatch.objects.filter(session=session)
        
        # Categorize studies
        auto_matched = study_matches.filter(match_status=BulkDICOMStudyMatch.MatchStatus.AUTO_MATCHED)
        manually_matched = study_matches.filter(match_status=BulkDICOMStudyMatch.MatchStatus.MANUALLY_MATCHED)
        unmatched = study_matches.filter(match_status=BulkDICOMStudyMatch.MatchStatus.MANUAL_MATCH_REQUIRED)
        
        context.update({
            'title': 'Confirm Patient Matches',
            'session': session,
            'auto_matched': auto_matched,
            'manually_matched': manually_matched,
            'unmatched': unmatched,
            'total_studies': study_matches.count(),
        })
        
        return context
    
    def post(self, request, session_id):
        """Handle confirmation and process the studies"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"POST request received for session {session_id}")
        logger.info(f"POST data: {request.POST}")
        
        session = get_object_or_404(BulkDICOMUploadSession, session_id=session_id)
        
        action = request.POST.get('action')
        logger.info(f"Action: {action}")
        
        if action == 'confirm':
            try:
                # Mark all matched studies as confirmed
                with transaction.atomic():
                    # Confirm auto-matched studies
                    auto_count = BulkDICOMStudyMatch.objects.filter(
                        session=session,
                        match_status=BulkDICOMStudyMatch.MatchStatus.AUTO_MATCHED
                    ).update(match_status=BulkDICOMStudyMatch.MatchStatus.CONFIRMED)
                    logger.info(f"Confirmed {auto_count} auto-matched studies")
                    
                    # Confirm manually matched studies
                    manual_count = BulkDICOMStudyMatch.objects.filter(
                        session=session,
                        match_status=BulkDICOMStudyMatch.MatchStatus.MANUALLY_MATCHED
                    ).update(match_status=BulkDICOMStudyMatch.MatchStatus.CONFIRMED)
                    logger.info(f"Confirmed {manual_count} manually matched studies")
                    
                    # Mark remaining as unmatched
                    unmatched_count = BulkDICOMStudyMatch.objects.filter(
                        session=session,
                        match_status=BulkDICOMStudyMatch.MatchStatus.MANUAL_MATCH_REQUIRED
                    ).update(match_status=BulkDICOMStudyMatch.MatchStatus.UNMATCHED)
                    logger.info(f"Marked {unmatched_count} studies as unmatched")
                    
                    session.status = BulkDICOMUploadSession.StatusChoices.CONFIRMED
                    session.save()
                    logger.info("Session status updated to CONFIRMED")
                
                # Dispatch Celery task for processing confirmed matches
                logger.info("Dispatching Celery task for confirmed matches")
                task_result = task_process_confirmed_matches.delay(
                    str(session.session_id), request.user.id
                )
                session.celery_task_id = task_result.id
                session.save(update_fields=['celery_task_id'])

                messages.success(
                    request,
                    "Processing started in background. You will be notified when it completes."
                )
                return redirect('client_app:task_progress', task_id=task_result.id)
                    
            except Exception as e:
                logger.error(f"Exception in confirmation POST: {str(e)}", exc_info=True)
                messages.error(request, f"Error: {str(e)}")
                return redirect('client_app:bulk_dicom_confirmation', session_id=session.session_id)
        
        elif action == 'back':
            return redirect('client_app:bulk_dicom_matching', session_id=session.session_id)
        
        logger.warning(f"No valid action found, redirecting back to confirmation")
        return redirect('client_app:bulk_dicom_confirmation', session_id=session.session_id)


class BulkDICOMCompleteView(LoginRequiredMixin, TemplateView):
    """View showing completion status of bulk DICOM upload"""
    template_name = "client_app/bulk_dicom_complete.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session_id = self.kwargs.get('session_id')
        
        session = get_object_or_404(BulkDICOMUploadSession, session_id=session_id)
        
        # Get processing statistics
        study_matches = BulkDICOMStudyMatch.objects.filter(session=session)
        processed = study_matches.filter(match_status=BulkDICOMStudyMatch.MatchStatus.PROCESSED)
        unmatched = study_matches.filter(match_status=BulkDICOMStudyMatch.MatchStatus.UNMATCHED)
        
        context.update({
            'title': 'Upload Complete',
            'session': session,
            'processed': processed,
            'unmatched': unmatched,
            'total_studies': study_matches.count(),
        })
        
        return context


# AJAX endpoint for patient search in select2
class PatientSearchAPIView(LoginRequiredMixin, View):
    """API endpoint for searching patients (for Select2)"""
    
    def get(self, request):
        search_term = request.GET.get('q', '')
        
        all_patients = Patient.objects.all()
        # ?consented=1 restricts to consented patients — used by the
        # DICOM retrieve page; other callers keep the full list.
        if request.GET.get('consented') in ('1', 'true'):
            all_patients = all_patients.filter(chavi_consent=True)
        
        if search_term:
            # Use fuzzy matching when a search term is provided
            # Normalise both the query and candidate IDs before scoring
            all_ids = list(all_patients.values_list('patient_id', 'gender'))
            norm_choices = {_make_canonical_id(pid): (pid, gender) for pid, gender in all_ids}
            fuzzy_matches = fuzz_process.extract(
                _make_canonical_id(search_term),
                list(norm_choices.keys()),
                scorer=fuzz.partial_ratio,
                limit=20,
                score_cutoff=20,
            )
            results = [
                {
                    'id': norm_choices[match[0]][0],
                    'text': f"{norm_choices[match[0]][0]} - {norm_choices[match[0]][1] or 'N/A'} ({round(match[1])}%)"
                }
                for match in fuzzy_matches
            ]
        else:
            patients = all_patients[:20]
            results = [
                {
                    'id': patient.patient_id,
                    'text': f"{patient.patient_id} - {patient.gender or 'N/A'}"
                }
                for patient in patients
            ]
        
        return JsonResponse({'results': results})


class PatientDataExportView(LoginRequiredMixin, TemplateView):
    """View for exporting patient data with filtering capabilities"""
    template_name = "client_app/patient_data_export.html"
    patients_per_page = 20
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Patient Data Export"
        
        # Get filter parameters
        patient_id_search = self.request.GET.get('patient_id', '')
        created_from_date = self.request.GET.get('created_from_date', '')
        created_from_time = self.request.GET.get('created_from_time', '00:00')
        created_to_date = self.request.GET.get('created_to_date', '')
        created_to_time = self.request.GET.get('created_to_time', '23:59')
        updated_from_date = self.request.GET.get('updated_from_date', '')
        updated_from_time = self.request.GET.get('updated_from_time', '00:00')
        updated_to_date = self.request.GET.get('updated_to_date', '')
        updated_to_time = self.request.GET.get('updated_to_time', '23:59')
        project_filter = self.request.GET.get('project', '')
        page = self.request.GET.get('page', 1)
        
        # Start with all patients
        patient_list = Patient.objects.all()
        
        # Apply filters
        if patient_id_search:
            patient_list = patient_list.filter(patient_id__icontains=patient_id_search)
        
        # Combine date and time for created_from filter
        if created_from_date:
            created_from_datetime = f"{created_from_date} {created_from_time}:00"
            patient_list = patient_list.filter(created_at__gte=created_from_datetime)
        
        # Combine date and time for created_to filter
        if created_to_date:
            created_to_datetime = f"{created_to_date} {created_to_time}:59"
            patient_list = patient_list.filter(created_at__lte=created_to_datetime)
        
        # Combine date and time for updated_from filter
        if updated_from_date:
            updated_from_datetime = f"{updated_from_date} {updated_from_time}:00"
            patient_list = patient_list.filter(updated_at__gte=updated_from_datetime)
        
        # Combine date and time for updated_to filter
        if updated_to_date:
            updated_to_datetime = f"{updated_to_date} {updated_to_time}:59"
            patient_list = patient_list.filter(updated_at__lte=updated_to_datetime)
        
        if project_filter:
            patient_list = patient_list.filter(patient_project__chavi_project_id=project_filter)
        
        # Order by most recent
        patient_list = patient_list.order_by('-created_at').distinct()
        
        # Set up pagination
        paginator = Paginator(patient_list, self.patients_per_page)
        
        try:
            patients = paginator.page(page)
        except PageNotAnInteger:
            patients = paginator.page(1)
        except EmptyPage:
            patients = paginator.page(paginator.num_pages)
        
        # Get all projects for the filter dropdown
        projects = Project.objects.all().order_by('project_name')
        
        context.update({
            'patients': patients,
            'projects': projects,
            'patient_id_search': patient_id_search,
            'created_from_date': created_from_date,
            'created_from_time': created_from_time,
            'created_to_date': created_to_date,
            'created_to_time': created_to_time,
            'updated_from_date': updated_from_date,
            'updated_from_time': updated_from_time,
            'updated_to_date': updated_to_date,
            'updated_to_time': updated_to_time,
            'project_filter': project_filter,
            'total_patients': patient_list.count(),
            'filtered_patient_ids': list(patient_list.values_list('patient_id', flat=True))
        })
        return context
    
    def post(self, request):
        """Handle export request"""
        # Check if "Select All across all pages" was used
        export_all = request.POST.get('export_all') == 'true'
        
        if export_all:
            # Re-apply filters to get ALL matching patients across all pages
            queryset = Patient.objects.all()
            
            patient_id = request.POST.get('filter_patient_id', '')
            if patient_id:
                queryset = queryset.filter(patient_id__icontains=patient_id)
            
            created_from_date = request.POST.get('filter_created_from_date', '')
            created_from_time = request.POST.get('filter_created_from_time', '00:00')
            if created_from_date:
                queryset = queryset.filter(created_at__gte=f"{created_from_date} {created_from_time}:00")
            
            created_to_date = request.POST.get('filter_created_to_date', '')
            created_to_time = request.POST.get('filter_created_to_time', '23:59')
            if created_to_date:
                queryset = queryset.filter(created_at__lte=f"{created_to_date} {created_to_time}:59")
            
            updated_from_date = request.POST.get('filter_updated_from_date', '')
            updated_from_time = request.POST.get('filter_updated_from_time', '00:00')
            if updated_from_date:
                queryset = queryset.filter(updated_at__gte=f"{updated_from_date} {updated_from_time}:00")
            
            updated_to_date = request.POST.get('filter_updated_to_date', '')
            updated_to_time = request.POST.get('filter_updated_to_time', '23:59')
            if updated_to_date:
                queryset = queryset.filter(updated_at__lte=f"{updated_to_date} {updated_to_time}:59")
            
            project_filter = request.POST.get('filter_project', '')
            if project_filter:
                queryset = queryset.filter(patient_project__chavi_project_id=project_filter)
            
            queryset = queryset.order_by('-created_at').distinct()
        else:
            # Get selected patient IDs from the form
            selected_ids = request.POST.getlist('selected_patients')
            
            if not selected_ids:
                messages.error(request, "Please select at least one patient to export")
                return redirect('client_app:patient_data_export')
            
            # Get the patients
            queryset = Patient.objects.filter(patient_id__in=selected_ids)
        
        if queryset.count() == 0:
            messages.error(request, "No patients found for export")
            return redirect('client_app:patient_data_export')
        
        # Dispatch Celery task for patient data export
        patient_ids = list(queryset.values_list('patient_id', flat=True))
        task_uuid = str(uuid.uuid4())
        task_result = task_export_patient_data.delay(patient_ids, request.user.id, task_uuid)
        
        messages.success(request, f"Patient data export started for {len(patient_ids)} patients.")
        return redirect('client_app:task_progress', task_id=task_result.id)


class DICOMDataExportView(LoginRequiredMixin, TemplateView):
    """View for exporting DICOM data with filtering capabilities"""
    template_name = "client_app/dicom_data_export.html"
    studies_per_page = 20
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "DICOM Data Export"
        
        # Get filter parameters
        patient_id_search = self.request.GET.get('patient_id', '')
        created_from_date = self.request.GET.get('created_from_date', '')
        created_from_time = self.request.GET.get('created_from_time', '00:00')
        created_to_date = self.request.GET.get('created_to_date', '')
        created_to_time = self.request.GET.get('created_to_time', '23:59')
        updated_from_date = self.request.GET.get('updated_from_date', '')
        updated_from_time = self.request.GET.get('updated_from_time', '00:00')
        updated_to_date = self.request.GET.get('updated_to_date', '')
        updated_to_time = self.request.GET.get('updated_to_time', '23:59')
        project_filter = self.request.GET.get('project', '')
        page = self.request.GET.get('page', 1)
        
        # Start with all DICOM studies
        study_list = DICOMStudy.objects.all()
        
        # Apply filters
        if patient_id_search:
            study_list = study_list.filter(patient__patient_id__icontains=patient_id_search)
        
        # Combine date and time for created_from filter
        if created_from_date:
            created_from_datetime = f"{created_from_date} {created_from_time}:00"
            study_list = study_list.filter(created_at__gte=created_from_datetime)
        
        # Combine date and time for created_to filter
        if created_to_date:
            created_to_datetime = f"{created_to_date} {created_to_time}:59"
            study_list = study_list.filter(created_at__lte=created_to_datetime)
        
        # Combine date and time for updated_from filter
        if updated_from_date:
            updated_from_datetime = f"{updated_from_date} {updated_from_time}:00"
            study_list = study_list.filter(updated_at__gte=updated_from_datetime)
        
        # Combine date and time for updated_to filter
        if updated_to_date:
            updated_to_datetime = f"{updated_to_date} {updated_to_time}:59"
            study_list = study_list.filter(updated_at__lte=updated_to_datetime)
        
        # Filter by project through DICOMStudyProject
        if project_filter:
            study_list = study_list.filter(
                dicomstudyproject__project__chavi_project_id=project_filter
            ).distinct()
        
        # Order by most recent
        study_list = study_list.order_by('-created_at').distinct()
        
        # Set up pagination
        paginator = Paginator(study_list, self.studies_per_page)
        
        try:
            studies = paginator.page(page)
        except PageNotAnInteger:
            studies = paginator.page(1)
        except EmptyPage:
            studies = paginator.page(paginator.num_pages)
        
        # Get all projects for the filter dropdown
        projects = Project.objects.all().order_by('project_name')
        
        context.update({
            'studies': studies,
            'projects': projects,
            'patient_id_search': patient_id_search,
            'created_from_date': created_from_date,
            'created_from_time': created_from_time,
            'created_to_date': created_to_date,
            'created_to_time': created_to_time,
            'updated_from_date': updated_from_date,
            'updated_from_time': updated_from_time,
            'updated_to_date': updated_to_date,
            'updated_to_time': updated_to_time,
            'project_filter': project_filter,
            'total_studies': study_list.count(),
        })
        return context
    
    def post(self, request):
        """Handle export request - starts background task"""
        import uuid
        import threading
        from django.core.cache import cache
        
        # Check if "Select All across all pages" was used
        export_all = request.POST.get('export_all') == 'true'
        
        if export_all:
            # Re-apply filters to get ALL matching studies across all pages
            queryset = DICOMStudy.objects.all()
            
            patient_id = request.POST.get('filter_patient_id', '')
            if patient_id:
                queryset = queryset.filter(patient__patient_id__icontains=patient_id)
            
            created_from_date = request.POST.get('filter_created_from_date', '')
            created_from_time = request.POST.get('filter_created_from_time', '00:00')
            if created_from_date:
                queryset = queryset.filter(created_at__gte=f"{created_from_date} {created_from_time}:00")
            
            created_to_date = request.POST.get('filter_created_to_date', '')
            created_to_time = request.POST.get('filter_created_to_time', '23:59')
            if created_to_date:
                queryset = queryset.filter(created_at__lte=f"{created_to_date} {created_to_time}:59")
            
            updated_from_date = request.POST.get('filter_updated_from_date', '')
            updated_from_time = request.POST.get('filter_updated_from_time', '00:00')
            if updated_from_date:
                queryset = queryset.filter(updated_at__gte=f"{updated_from_date} {updated_from_time}:00")
            
            updated_to_date = request.POST.get('filter_updated_to_date', '')
            updated_to_time = request.POST.get('filter_updated_to_time', '23:59')
            if updated_to_date:
                queryset = queryset.filter(updated_at__lte=f"{updated_to_date} {updated_to_time}:59")
            
            project_filter = request.POST.get('filter_project', '')
            if project_filter:
                queryset = queryset.filter(
                    dicomstudyproject__project__chavi_project_id=project_filter
                ).distinct()
            
            queryset = queryset.order_by('-created_at').distinct()
        else:
            # Get selected study UIDs from the form
            selected_uids = request.POST.getlist('selected_studies')
            
            if not selected_uids:
                messages.error(request, "Please select at least one DICOM study to export")
                return redirect('client_app:dicom_data_export')
            
            # Get the DICOM studies
            queryset = DICOMStudy.objects.filter(study_instance_uid__in=selected_uids)
        
        if queryset.count() == 0:
            messages.error(request, "No DICOM studies found for export")
            return redirect('client_app:dicom_data_export')
        
        # Check if patient data export is requested
        include_patient_data = request.POST.get('include_patient_data') == 'true'
        
        # Get study IDs for Celery task
        study_ids = list(queryset.values_list('pk', flat=True))
        task_uuid = str(uuid.uuid4())
        
        # Dispatch Celery task for parallel DICOM export
        task_result = task_export_dicom_data_parallel.delay(
            study_ids, task_uuid, include_patient_data=include_patient_data, user_id=request.user.id
        )
        
        # Redirect to progress page with Celery task ID
        context = {
            'task_id': task_result.id,
            'study_count': queryset.count(),
            'include_patient_data': include_patient_data
        }
        return render(request, 'client_app/dicom_export_progress.html', context)


class DICOMExportProgressView(LoginRequiredMixin, View):
    """API endpoint to check DICOM export progress via celery-progress"""
    
    def get(self, request, task_id):
        from celery.result import AsyncResult
        from celery_progress.backend import Progress
        import json
        
        try:
            progress = Progress(AsyncResult(task_id))
            return JsonResponse(progress.get_info())
        except Exception:
            return JsonResponse({
                'state': 'PENDING',
                'progress': {'pending': True, 'current': 0, 'total': 0, 'percent': 0},
                'result': None,
                'complete': False,
            })


class DICOMExportDownloadView(LoginRequiredMixin, View):
    """Download the completed DICOM export ZIP file(s) from Celery task result"""
    
    def get(self, request, task_id):
        from pathlib import Path
        from django.http import FileResponse
        from celery.result import AsyncResult
        import json
        
        result = AsyncResult(task_id)
        
        if not result.ready() or not result.successful():
            messages.error(request, "Export not ready or failed")
            return redirect('client_app:dicom_data_export')
        
        task_data = result.result
        if not task_data or not task_data.get('success'):
            messages.error(request, "Export failed or no data available")
            return redirect('client_app:dicom_data_export')
        
        # Determine which file to download (dicom or patient)
        file_type = request.GET.get('file', 'dicom')
        
        if file_type == 'patient' and task_data.get('patient_data_zip_path'):
            zip_path = Path(task_data['patient_data_zip_path'])
            filename = task_data.get('patient_data_zip_filename', f'patient_data_{task_id}.zip')
        else:
            zip_path = Path(task_data['zip_path'])
            filename = task_data.get('zip_filename', f'dicom_export_{task_id}.zip')
        
        if not zip_path.exists():
            messages.error(request, "Export file not found")
            return redirect('client_app:dicom_data_export')
        
        try:
            response = FileResponse(open(zip_path, 'rb'), content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename={filename}'
            return response
        except Exception as e:
            messages.error(request, f"Error downloading file: {str(e)}")
            return redirect('client_app:dicom_data_export')


class TaskProgressView(LoginRequiredMixin, TemplateView):
    """Generic progress page for any Celery task using celery-progress"""
    template_name = "client_app/task_progress.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['task_id'] = self.kwargs.get('task_id')
        context['title'] = "Task Progress"
        return context


class TaskDownloadView(LoginRequiredMixin, View):
    """Generic download view that reads file path from Celery task result"""

    def get(self, request, task_id):
        from pathlib import Path
        from django.http import FileResponse
        from celery.result import AsyncResult

        result = AsyncResult(task_id)

        if not result.ready() or not result.successful():
            messages.error(request, "Task not ready or failed")
            return redirect('client_app:homepage')

        task_data = result.result
        if not task_data or not task_data.get('success'):
            messages.error(request, "Task produced no downloadable result")
            return redirect('client_app:homepage')

        zip_path = Path(task_data.get('zip_path', ''))
        if not zip_path.exists():
            messages.error(request, "File not found")
            return redirect('client_app:homepage')

        filename = task_data.get('zip_filename', f'export_{task_id}.zip')

        try:
            response = FileResponse(open(zip_path, 'rb'), content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename={filename}'
            return response
        except Exception as e:
            messages.error(request, f"Error downloading file: {str(e)}")
            return redirect('client_app:homepage')


# ---------------------------------------------------------------------------
# Task Run views — list, detail, resume, retry
# ---------------------------------------------------------------------------

TASK_TYPE_PERMISSIONS = {
    TaskRun.TaskType.DICOM_IMPORT: 'client_app.view_dicomstudy',
    TaskRun.TaskType.DICOM_EXPORT: 'client_app.view_dicomstudy',
    TaskRun.TaskType.BULK_DICOM: 'client_app.view_bulkdicomuploadsession',
    TaskRun.TaskType.PATIENT_EXPORT: 'client_app.view_patient',
    TaskRun.TaskType.ASSOCIATE: 'client_app.view_patient',
    TaskRun.TaskType.UNPROCESSED: 'client_app.view_dicomstudy',
    TaskRun.TaskType.DEIDENTIFICATION: 'deidentification.view_deidpatient',
}


def _get_visible_task_types(user):
    """Return a list of TaskType values the user has permission to view."""
    visible = []
    for task_type, perm in TASK_TYPE_PERMISSIONS.items():
        if user.has_perm(perm):
            visible.append(task_type)
    return visible


class TaskRunListView(LoginRequiredMixin, ListView):
    model = TaskRun
    template_name = 'client_app/taskrun_list.html'
    context_object_name = 'task_runs'
    paginate_by = 25

    def get_queryset(self):
        qs = TaskRun.objects.all().select_related('user').defer(
            'result_summary', 'task_args', 'task_kwargs', 'error_log'
        )
        if not self.request.user.is_superuser:
            visible_types = _get_visible_task_types(self.request.user)
            qs = qs.filter(task_type__in=visible_types)
        status_filter = self.request.GET.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        type_filter = self.request.GET.get('type')
        if type_filter:
            qs = qs.filter(task_type=type_filter)
        date_from = self.request.GET.get('date_from')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = self.request.GET.get('date_to')
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = TaskRun.Status.choices
        if self.request.user.is_superuser:
            ctx['type_choices'] = TaskRun.TaskType.choices
        else:
            visible_types = _get_visible_task_types(self.request.user)
            ctx['type_choices'] = [(t.value, t.label) for t in visible_types]
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['current_type'] = self.request.GET.get('type', '')
        ctx['current_date_from'] = self.request.GET.get('date_from', '')
        ctx['current_date_to'] = self.request.GET.get('date_to', '')
        return ctx


class TaskRunDetailView(LoginRequiredMixin, DetailView):
    model = TaskRun
    template_name = 'client_app/taskrun_detail.html'
    context_object_name = 'task_run'
    pk_url_kwarg = 'pk'

    def get_queryset(self):
        qs = TaskRun.objects.all()
        if not self.request.user.is_superuser:
            visible_types = _get_visible_task_types(self.request.user)
            qs = qs.filter(task_type__in=visible_types)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = self.get_object()
        from celery.result import AsyncResult
        try:
            async_result = AsyncResult(obj.task_id)
            ctx['celery_state'] = async_result.state
            ctx['celery_info'] = async_result.info if not isinstance(async_result.info, Exception) else str(async_result.info)
        except Exception:
            ctx['celery_state'] = 'UNKNOWN'
            ctx['celery_info'] = None
        return ctx


# Registry of task_name -> Celery task callable, used to generically redispatch
# tasks for resume/retry using their originally stored args/kwargs.
TASK_REGISTRY = {
    'task_extract_and_analyze_upload': task_extract_and_analyze_upload,
    'task_process_confirmed_matches': task_process_confirmed_matches,
    'task_export_patient_data': task_export_patient_data,
    'task_export_dicom_data_parallel': task_export_dicom_data_parallel,
    'task_export_dicom_data': task_export_dicom_data,
    'task_process_dicom_per_patient': task_process_dicom_per_patient,
    'task_process_bulk_dicom': task_process_bulk_dicom,
    'task_process_unprocessed_dicom': task_process_unprocessed_dicom,
    'task_associate_dicom_to_project': task_associate_dicom_to_project,
}


def _redispatch_task_run(task_run):
    """Redispatch a TaskRun using its stored task_args/task_kwargs.

    Returns the new celery AsyncResult, or None if the task cannot be redispatched
    (unknown task name or no stored arguments).
    """
    task_func = TASK_REGISTRY.get(task_run.task_name)
    if not task_func or task_run.task_args is None:
        return None
    args = task_run.task_args or []
    kwargs = task_run.task_kwargs or {}
    return task_func.delay(*args, **kwargs)


class TaskRunResumeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task_run = get_object_or_404(TaskRun, pk=pk)
        if not request.user.is_superuser:
            perm = TASK_TYPE_PERMISSIONS.get(task_run.task_type)
            if perm and not request.user.has_perm(perm):
                raise Http404
        if task_run.status not in (TaskRun.Status.FAILURE, TaskRun.Status.STALLED):
            messages.error(request, "Only failed or stalled tasks can be resumed.")
            return redirect('client_app:taskrun_detail', pk=task_run.pk)

        new_result = _redispatch_task_run(task_run)
        if not new_result:
            messages.error(request, f"Task '{task_run.task_name}' does not support automatic resume (no stored arguments found).")
            return redirect('client_app:taskrun_detail', pk=task_run.pk)

        task_run.resume_count += 1
        task_run.status = TaskRun.Status.PENDING
        task_run.error_log = None
        task_run.task_id = new_result.id
        task_run.save(update_fields=['resume_count', 'status', 'error_log', 'task_id', 'updated_at'])

        Notification.objects.create(
            user=task_run.user or request.user,
            notification_type=Notification.NotificationType.TASK_RESUMED,
            title=f"Task resumed: {task_run.task_name}",
            message=f"Task '{task_run.task_name}' has been resumed (attempt #{task_run.resume_count}).",
            task_run=task_run,
        )

        messages.success(request, f"Task resumed. New task ID: {new_result.id}")
        return redirect('client_app:task_progress', task_id=new_result.id)


class TaskRunRetryView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task_run = get_object_or_404(TaskRun, pk=pk)
        if not request.user.is_superuser:
            perm = TASK_TYPE_PERMISSIONS.get(task_run.task_type)
            if perm and not request.user.has_perm(perm):
                raise Http404
        if task_run.status not in (TaskRun.Status.FAILURE, TaskRun.Status.STALLED, TaskRun.Status.SUCCESS):
            messages.error(request, "Only failed, stalled, or completed tasks can be retried.")
            return redirect('client_app:taskrun_detail', pk=task_run.pk)

        new_result = _redispatch_task_run(task_run)
        if not new_result:
            messages.error(request, f"Task '{task_run.task_name}' does not support automatic retry (no stored arguments found).")
            return redirect('client_app:taskrun_detail', pk=task_run.pk)

        TaskRun.objects.create(
            task_id=new_result.id,
            task_name=task_run.task_name,
            task_type=task_run.task_type,
            status=TaskRun.Status.PENDING,
            user=task_run.user or request.user,
            related_session_id=task_run.related_session_id,
            task_args=task_run.task_args,
            task_kwargs=task_run.task_kwargs,
        )
        messages.success(request, f"Task retried. New task ID: {new_result.id}")
        return redirect('client_app:task_progress', task_id=new_result.id)


# ---------------------------------------------------------------------------
# Bulk DICOM Sessions listing
# ---------------------------------------------------------------------------

class BulkDICOMSessionListView(LoginRequiredMixin, ListView):
    model = BulkDICOMUploadSession
    template_name = 'client_app/bulk_dicom_session_list.html'
    context_object_name = 'sessions'
    paginate_by = 20

    def get_queryset(self):
        qs = BulkDICOMUploadSession.objects.all().select_related('uploaded_by').order_by('-created_at')
        status_filter = self.request.GET.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = BulkDICOMUploadSession.StatusChoices.choices
        ctx['current_status'] = self.request.GET.get('status', '')
        return ctx


# ---------------------------------------------------------------------------
# Notification API endpoints
# ---------------------------------------------------------------------------

class NotificationListView(LoginRequiredMixin, View):
    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:20]
        data = []
        for n in notifications:
            data.append({
                'id': n.id,
                'type': n.notification_type,
                'title': n.title,
                'message': n.message,
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat(),
                'task_run_id': n.task_run_id,
            })
        return JsonResponse({'notifications': data, 'unread_count': Notification.objects.filter(user=request.user, is_read=False).count()})


class NotificationMarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk=None):
        if pk:
            notif = get_object_or_404(Notification, pk=pk, user=request.user)
            notif.is_read = True
            notif.save(update_fields=['is_read'])
        else:
            Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'success': True, 'unread_count': Notification.objects.filter(user=request.user, is_read=False).count()})
