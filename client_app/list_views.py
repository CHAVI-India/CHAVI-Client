"""
List and Update views for all models
This file contains ListView and UpdateView for each model to allow viewing and editing records
"""
from django.views.generic import ListView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from .models import *
from .forms import *
from .form_views import BaseListView, BaseUpdateView


# Patient-level List and Update Views
class ComorbidityListView(BaseListView):
    model = Comorbidity
    
    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            queryset = queryset.filter(patient__patient_id=patient_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            context['patient'] = Patient.objects.get(patient_id=patient_id)
            context['add_url'] = reverse('client_app:comorbidity_add') + f'?patient={patient_id}'
        return context
    
class ComorbidityUpdateView(BaseUpdateView):
    model = Comorbidity
    form_class = ComorbidityForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class SymptomListView(BaseListView):
    model = Symptom
    
    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            queryset = queryset.filter(patient__patient_id=patient_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            context['patient'] = Patient.objects.get(patient_id=patient_id)
            context['add_url'] = reverse('client_app:symptom_add') + f'?patient={patient_id}'
        return context

class SymptomUpdateView(BaseUpdateView):
    model = Symptom
    form_class = SymptomForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


# Diagnosis-level List and Update Views
class DiagnosisListView(BaseListView):
    model = Diagnosis
    
    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            queryset = queryset.filter(patient__patient_id=patient_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            context['patient'] = Patient.objects.get(patient_id=patient_id)
            context['add_url'] = reverse('client_app:diagnosis_add') + f'?patient={patient_id}'
        return context


class PathologyListView(BaseListView):
    model = Pathology
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:pathology_add') + f'?diagnosis={diagnosis_id}'
        return context

class PathologyUpdateView(BaseUpdateView):
    model = Pathology
    form_class = PathologyForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class LesionListView(BaseListView):
    model = Lesion
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:lesion_add') + f'?diagnosis={diagnosis_id}'
        return context

class LesionUpdateView(BaseUpdateView):
    model = Lesion
    form_class = LesionForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class RadiotherapyListView(BaseListView):
    model = Radiotherapy
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:radiotherapy_add') + f'?diagnosis={diagnosis_id}'
        return context

class RadiotherapyUpdateView(BaseUpdateView):
    model = Radiotherapy
    form_class = RadiotherapyForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class SystemicTherapyListView(BaseListView):
    model = SystemicTherapy
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:systemictherapy_add') + f'?diagnosis={diagnosis_id}'
        return context

class SystemicTherapyUpdateView(BaseUpdateView):
    model = SystemicTherapy
    form_class = SystemicTherapyForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


# Additional patient-level views
class PatientOutcomeListView(BaseListView):
    model = PatientOutcome
    
    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            queryset = queryset.filter(patient__patient_id=patient_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            context['patient'] = Patient.objects.get(patient_id=patient_id)
            context['add_url'] = reverse('client_app:patientoutcome_add') + f'?patient={patient_id}'
        return context

class PatientOutcomeUpdateView(BaseUpdateView):
    model = PatientOutcome
    form_class = PatientOutcomeForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class PatientReportedOutcomeListView(BaseListView):
    model = PatientReportedOutcome
    
    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            queryset = queryset.filter(patient__patient_id=patient_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            context['patient'] = Patient.objects.get(patient_id=patient_id)
            context['add_url'] = reverse('client_app:patientreportedoutcome_add') + f'?patient={patient_id}'
        return context

class PatientReportedOutcomeUpdateView(BaseUpdateView):
    model = PatientReportedOutcome
    form_class = PatientReportedOutcomeForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class GermlineGenomicAlterationsListView(BaseListView):
    model = GermlineGenomicAlterations
    
    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            queryset = queryset.filter(patient__patient_id=patient_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            context['patient'] = Patient.objects.get(patient_id=patient_id)
            context['add_url'] = reverse('client_app:germlinegenomicalterations_add') + f'?patient={patient_id}'
        return context

class GermlineGenomicAlterationsUpdateView(BaseUpdateView):
    model = GermlineGenomicAlterations
    form_class = GermlineGenomicAlterationsForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class LaboratoryResultsListView(BaseListView):
    model = LaboratoryResults
    
    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            queryset = queryset.filter(patient__patient_id=patient_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            context['patient'] = Patient.objects.get(patient_id=patient_id)
            context['add_url'] = reverse('client_app:laboratoryresults_add') + f'?patient={patient_id}'
        return context

class LaboratoryResultsUpdateView(BaseUpdateView):
    model = LaboratoryResults
    form_class = LaboratoryResultsForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class PatientAssessmentListView(BaseListView):
    model = PatientAssessment
    
    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            queryset = queryset.filter(patient__patient_id=patient_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient_id')
        if patient_id:
            context['patient'] = Patient.objects.get(patient_id=patient_id)
            context['add_url'] = reverse('client_app:patientassessment_add') + f'?patient={patient_id}'
        return context

class PatientAssessmentUpdateView(BaseUpdateView):
    model = PatientAssessment
    form_class = PatientAssessmentForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


# Additional diagnosis-level views
class StageInformationListView(BaseListView):
    model = StageInformation
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:stageinformation_add') + f'?diagnosis={diagnosis_id}'
        return context

class StageInformationUpdateView(BaseUpdateView):
    model = StageInformation
    form_class = StageInformationForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class SurgeryListView(BaseListView):
    model = Surgery
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:surgery_add') + f'?diagnosis={diagnosis_id}'
        return context

class SurgeryUpdateView(BaseUpdateView):
    model = Surgery
    form_class = SurgeryForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class OtherTreatmentListView(BaseListView):
    model = OtherTreatment
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:othertreatment_add') + f'?diagnosis={diagnosis_id}'
        return context

class OtherTreatmentUpdateView(BaseUpdateView):
    model = OtherTreatment
    form_class = OtherTreatmentForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class ConcomitantMedicationsListView(BaseListView):
    model = ConcomitantMedications
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:concomitantmedications_add') + f'?diagnosis={diagnosis_id}'
        return context

class ConcomitantMedicationsUpdateView(BaseUpdateView):
    model = ConcomitantMedications
    form_class = ConcomitantMedicationsForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class OutcomeListView(BaseListView):
    model = Outcome
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:outcome_add') + f'?diagnosis={diagnosis_id}'
        return context

class OutcomeUpdateView(BaseUpdateView):
    model = Outcome
    form_class = OutcomeForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class AdverseEffectsListView(BaseListView):
    model = AdverseEffects
    
    def get_queryset(self):
        queryset = super().get_queryset()
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            queryset = queryset.filter(diagnosis__chavi_diagnosis_id=diagnosis_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        diagnosis_id = self.request.GET.get('diagnosis_id')
        if diagnosis_id:
            diagnosis = Diagnosis.objects.get(chavi_diagnosis_id=diagnosis_id)
            context['diagnosis'] = diagnosis
            context['patient'] = diagnosis.patient
            context['add_url'] = reverse('client_app:adverseeffects_add') + f'?diagnosis={diagnosis_id}'
        return context

class AdverseEffectsUpdateView(BaseUpdateView):
    model = AdverseEffects
    form_class = AdverseEffectsForm
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'
