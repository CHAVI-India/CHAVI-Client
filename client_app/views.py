from django.shortcuts import render, redirect, get_object_or_404
import os
from django.conf import settings
from django.views.static import serve
from django.views.generic import TemplateView, View, ListView, CreateView
from django.contrib.auth.mixins import LoginRequiredMixin
from unfold.views import UnfoldModelAdminViewMixin
from .models import *
from django.urls import reverse, reverse_lazy
from django.http import Http404
from django.contrib import admin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

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
    template_name = "client_app/patient_summary.html"
    
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
            
            # Organize data into sections
            diagnosis_info = {
                'diagnosis': diagnosis,
                
                # Diagnostic Information section
                'diagnostic_data': {
                    'pathologies': {
                        'objects': pathologies,
                        'count': pathologies.count()
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
                        'count': systemic_therapies.count()
                    },
                    'radiotherapies': {
                        'objects': radiotherapies,
                        'count': radiotherapies.count()
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


