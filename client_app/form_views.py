from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import CreateView, UpdateView, ListView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from .models import *
from .forms import *


class ForeignKeyInitMixin:
    """Mixin to handle foreign key initialization from URL parameters"""
    
    def get_initial(self):
        """Set initial values for foreign key fields from URL parameters"""
        initial = super().get_initial()
        
        # Map of URL parameter names to model classes and field names
        fk_mappings = {
            'patient': (Patient, 'patient_id', 'patient'),
            'diagnosis': (Diagnosis, 'chavi_diagnosis_id', 'diagnosis'),
            'pathology': (Pathology, 'chavi_pathology_id', 'pathology'),
            'lesion': (Lesion, 'chavi_lesion_id', 'lesion'),
            'radiotherapy': (Radiotherapy, 'chavi_radiotherapy_id', 'radiotherapy'),
            'systemic_therapy': (SystemicTherapy, 'chavi_systemic_therapy_id', 'systemic_therapy'),
        }
        
        for param_name, (model_class, pk_field, form_field) in fk_mappings.items():
            param_value = self.request.GET.get(param_name)
            print(f"Checking {param_name}: {param_value}")
            if param_value:
                try:
                    obj = model_class.objects.get(**{pk_field: param_value})
                    # Set the actual object instance, not pk
                    initial[form_field] = obj
                    print(f"✓ Setting initial {form_field} to {obj} (pk: {obj.pk})")
                except model_class.DoesNotExist:
                    print(f"✗ Could not find {model_class.__name__} with {pk_field}={param_value}")
                except Exception as e:
                    print(f"✗ Error finding {model_class.__name__}: {e}")
        
        return initial
    
    def get_form(self, form_class=None):
        """Modify form to make pre-filled foreign keys readonly and filter DICOM studies"""
        form = super().get_form(form_class)
        
        # Map of URL parameter names to model classes and field names
        fk_mappings = {
            'patient': (Patient, 'patient_id', 'patient'),
            'diagnosis': (Diagnosis, 'chavi_diagnosis_id', 'diagnosis'),
            'pathology': (Pathology, 'chavi_pathology_id', 'pathology'),
            'lesion': (Lesion, 'chavi_lesion_id', 'lesion'),
            'radiotherapy': (Radiotherapy, 'chavi_radiotherapy_id', 'radiotherapy'),
            'systemic_therapy': (SystemicTherapy, 'chavi_systemic_therapy_id', 'systemic_therapy'),
        }
        
        # Get the patient object for filtering DICOM studies
        patient_obj = None
        patient_id = self.request.GET.get('patient')
        if patient_id:
            try:
                patient_obj = Patient.objects.get(patient_id=patient_id)
            except Patient.DoesNotExist:
                pass
        
        # If no patient in URL, try to get it from diagnosis/pathology/lesion/etc
        if not patient_obj:
            for param_name, (model_class, pk_field, form_field) in fk_mappings.items():
                if param_name == 'patient':
                    continue
                param_value = self.request.GET.get(param_name)
                if param_value:
                    try:
                        obj = model_class.objects.get(**{pk_field: param_value})
                        # Try to find patient through various relationship paths
                        if hasattr(obj, 'patient'):
                            patient_obj = obj.patient
                            print(f"✓ Found patient via {param_name}.patient")
                            break
                        elif hasattr(obj, 'diagnosis'):
                            if hasattr(obj.diagnosis, 'patient'):
                                patient_obj = obj.diagnosis.patient
                                print(f"✓ Found patient via {param_name}.diagnosis.patient")
                                break
                        elif hasattr(obj, 'pathology'):
                            if hasattr(obj.pathology, 'diagnosis') and hasattr(obj.pathology.diagnosis, 'patient'):
                                patient_obj = obj.pathology.diagnosis.patient
                                print(f"✓ Found patient via {param_name}.pathology.diagnosis.patient")
                                break
                        elif hasattr(obj, 'lesion'):
                            if hasattr(obj.lesion, 'diagnosis') and hasattr(obj.lesion.diagnosis, 'patient'):
                                patient_obj = obj.lesion.diagnosis.patient
                                print(f"✓ Found patient via {param_name}.lesion.diagnosis.patient")
                                break
                        elif hasattr(obj, 'radiotherapy'):
                            if hasattr(obj.radiotherapy, 'diagnosis') and hasattr(obj.radiotherapy.diagnosis, 'patient'):
                                patient_obj = obj.radiotherapy.diagnosis.patient
                                print(f"✓ Found patient via {param_name}.radiotherapy.diagnosis.patient")
                                break
                        elif hasattr(obj, 'systemic_therapy'):
                            if hasattr(obj.systemic_therapy, 'diagnosis') and hasattr(obj.systemic_therapy.diagnosis, 'patient'):
                                patient_obj = obj.systemic_therapy.diagnosis.patient
                                print(f"✓ Found patient via {param_name}.systemic_therapy.diagnosis.patient")
                                break
                    except model_class.DoesNotExist:
                        pass
        
        # Filter DICOM studies to only show studies for this patient
        if patient_obj and 'study_instance_uid' in form.fields:
            from .models import DICOMStudy
            form.fields['study_instance_uid'].queryset = DICOMStudy.objects.filter(patient=patient_obj)
            print(f"✓ Filtered DICOM studies to patient {patient_obj.patient_id}")
        
        # Handle pre-filled foreign keys
        for param_name, (model_class, pk_field, form_field) in fk_mappings.items():
            param_value = self.request.GET.get(param_name)
            if param_value and form_field in form.fields:
                try:
                    obj = model_class.objects.get(**{pk_field: param_value})
                    
                    # Simply set the field to readonly and pre-fill it
                    from django import forms as django_forms
                    
                    # Keep the ModelChoiceField but limit choices to just this one object
                    form.fields[form_field].queryset = form.fields[form_field].queryset.filter(pk=obj.pk)
                    form.fields[form_field].initial = obj
                    form.fields[form_field].empty_label = None
                    
                    # Make it NOT required and NOT disabled - we'll handle it in form_valid
                    form.fields[form_field].required = False
                    form.fields[form_field].widget.attrs.update({
                        'readonly': 'readonly',
                        'style': 'pointer-events: none; background-color: #f3f4f6;',
                    })
                    form.fields[form_field].help_text = 'This field is pre-selected and cannot be changed.'
                    
                    # If this is a POST request (form submission), inject the value into form data
                    if self.request.method == 'POST':
                        if hasattr(form, 'data'):
                            form.data = form.data.copy()  # Make it mutable
                            form.data[form_field] = obj.pk
                            print(f"✓ Injected {form_field} = {obj.pk} into POST data")
                    
                    print(f"✓ Set {form_field} to {obj} (pk: {obj.pk})")
                except model_class.DoesNotExist:
                    print(f"✗ Could not find {model_class.__name__} with {pk_field}={param_value}")
        
        return form
    
    def form_valid(self, form):
        """Re-set disabled FK fields before saving (disabled fields don't submit)"""
        # Map of URL parameter names to model classes and field names
        fk_mappings = {
            'patient': (Patient, 'patient_id', 'patient'),
            'diagnosis': (Diagnosis, 'chavi_diagnosis_id', 'diagnosis'),
            'pathology': (Pathology, 'chavi_pathology_id', 'pathology'),
            'lesion': (Lesion, 'chavi_lesion_id', 'lesion'),
            'radiotherapy': (Radiotherapy, 'chavi_radiotherapy_id', 'radiotherapy'),
            'systemic_therapy': (SystemicTherapy, 'chavi_systemic_therapy_id', 'systemic_therapy'),
        }
        
        # Disabled fields don't submit, so set them on the instance directly
        for param_name, (model_class, pk_field, form_field) in fk_mappings.items():
            param_value = self.request.GET.get(param_name)
            if param_value and form_field in form.fields:
                try:
                    obj = model_class.objects.get(**{pk_field: param_value})
                    setattr(form.instance, form_field, obj)
                    print(f"✓ Setting {form_field} on instance to {obj}")
                except model_class.DoesNotExist:
                    pass
        
        print(f"Form is valid, saving {self.model.__name__}")
        return super().form_valid(form)


class BaseFormView(ForeignKeyInitMixin, LoginRequiredMixin, CreateView):
    """Base view for all form views with common functionality"""
    template_name = 'client_app/form_template.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f"Add {self.model._meta.verbose_name}"
        context['model_name'] = self.model._meta.verbose_name
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'{self.model._meta.verbose_name} added successfully!')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


# Patient-level form views
class ComorbidityCreateView(BaseFormView):
    model = Comorbidity
    form_class = ComorbidityForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class SymptomCreateView(BaseFormView):
    model = Symptom
    form_class = SymptomForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class PatientAssessmentCreateView(BaseFormView):
    model = PatientAssessment
    form_class = PatientAssessmentForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class LaboratoryResultsCreateView(BaseFormView):
    model = LaboratoryResults
    form_class = LaboratoryResultsForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class PatientOutcomeCreateView(BaseFormView):
    model = PatientOutcome
    form_class = PatientOutcomeForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class PatientReportedOutcomeCreateView(BaseFormView):
    model = PatientReportedOutcome
    form_class = PatientReportedOutcomeForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class GermlineGenomicAlterationsCreateView(BaseFormView):
    model = GermlineGenomicAlterations
    form_class = GermlineGenomicAlterationsForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class PatientDicomFileCreateView(BaseFormView):
    model = PatientDicomFile
    form_class = PatientDicomFileForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


# Diagnosis-level form views
class DiagnosisCreateView(BaseFormView):
    model = Diagnosis
    form_class = DiagnosisForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class DiagnosisUpdateView(LoginRequiredMixin, UpdateView):
    model = Diagnosis
    form_class = DiagnosisForm
    template_name = 'client_app/form_template.html'
    pk_url_kwarg = 'pk'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f"Edit {self.model._meta.verbose_name}"
        context['model_name'] = self.model._meta.verbose_name
        return context
    
    def get_form(self, form_class=None):
        """Modify form to make patient readonly and filter DICOM studies"""
        form = super().get_form(form_class)
        
        # Get the patient from the diagnosis object
        patient_obj = self.object.patient
        
        # For Select2 widgets to show the current value, we need to ensure
        # the widget's choices include the current selection
        for field_name, field in form.fields.items():
            if hasattr(form.instance, field_name):
                current_value = getattr(form.instance, field_name)
                if current_value and isinstance(field, forms.ModelChoiceField):
                    # Ensure the current value is in the queryset
                    if not isinstance(field, forms.ModelMultipleChoiceField):
                        # For single select, add current value to choices if not already there
                        if hasattr(field.widget, 'choices'):
                            field.widget.choices = [(current_value.pk, str(current_value))]
                        print(f"  Set {field_name} widget choice to {current_value}")
        
        # Make patient field readonly
        if 'patient' in form.fields:
            from django import forms as django_forms
            form.fields['patient'].queryset = Patient.objects.filter(pk=patient_obj.pk)
            form.fields['patient'].initial = patient_obj
            form.fields['patient'].empty_label = None
            form.fields['patient'].required = False
            form.fields['patient'].widget.attrs.update({
                'readonly': 'readonly',
                'style': 'pointer-events: none; background-color: #f3f4f6;',
            })
            form.fields['patient'].help_text = 'Patient cannot be changed when editing.'
            print(f"✓ Set patient to {patient_obj} (readonly)")
        
        # Filter DICOM studies to only show studies for this patient
        if 'study_instance_uid' in form.fields:
            from .models import DICOMStudy
            form.fields['study_instance_uid'].queryset = DICOMStudy.objects.filter(patient=patient_obj)
            print(f"✓ Filtered DICOM studies to patient {patient_obj.patient_id}")
        
        return form
    
    def form_valid(self, form):
        """Ensure patient is set correctly"""
        # Patient field is readonly, so set it from the object
        form.instance.patient = self.object.patient
        print(f"✓ Ensured patient is {self.object.patient}")
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.patient.patient_id}'


class PathologyCreateView(BaseFormView):
    model = Pathology
    form_class = PathologyForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class StageInformationCreateView(BaseFormView):
    model = StageInformation
    form_class = StageInformationForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class LesionCreateView(BaseFormView):
    model = Lesion
    form_class = LesionForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class LesionResponseCreateView(BaseFormView):
    model = LesionResponse
    form_class = LesionResponseForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.lesion.diagnosis.patient.patient_id}'


class SurgeryCreateView(BaseFormView):
    model = Surgery
    form_class = SurgeryForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class RadiotherapyCreateView(BaseFormView):
    model = Radiotherapy
    form_class = RadiotherapyForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class SystemicTherapyCreateView(BaseFormView):
    model = SystemicTherapy
    form_class = SystemicTherapyForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class OtherTreatmentCreateView(BaseFormView):
    model = OtherTreatment
    form_class = OtherTreatmentForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class ConcomitantMedicationsCreateView(BaseFormView):
    model = ConcomitantMedications
    form_class = ConcomitantMedicationsForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class OutcomeCreateView(BaseFormView):
    model = Outcome
    form_class = OutcomeForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


class AdverseEffectsCreateView(BaseFormView):
    model = AdverseEffects
    form_class = AdverseEffectsForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.diagnosis.patient.patient_id}'


# Pathology sub-forms
class ImmunohistochemistryCreateView(BaseFormView):
    model = Immunohistochemistry
    form_class = ImmunohistochemistryForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.pathology.diagnosis.patient.patient_id}'


class CytogeneticsCreateView(BaseFormView):
    model = Cytogenetics
    form_class = CytogeneticsForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.pathology.diagnosis.patient.patient_id}'


class SomaticGenomicAlterationsCreateView(BaseFormView):
    model = SomaticGenomicAlterations
    form_class = SomaticGenomicAlterationsForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.pathology.diagnosis.patient.patient_id}'


class GeneExpressionDataCreateView(BaseFormView):
    model = GeneExpressionData
    form_class = GeneExpressionDataForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.pathology.diagnosis.patient.patient_id}'


class EpigeneticDataCreateView(BaseFormView):
    model = EpigeneticData
    form_class = EpigeneticDataForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.pathology.diagnosis.patient.patient_id}'


# Radiotherapy sub-forms
class RadiotherapyVolumeCreateView(BaseFormView):
    model = RadiotherapyVolume
    form_class = RadiotherapyVolumeForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.radiotherapy.diagnosis.patient.patient_id}'


class RadiotherapyDoseVolumeDataCreateView(BaseFormView):
    model = RadiotherapyDoseVolumeData
    form_class = RadiotherapyDoseVolumeDataForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.radiotherapy.diagnosis.patient.patient_id}'


# Systemic Therapy sub-forms
class SystemicTherapyScheduleCreateView(BaseFormView):
    model = SystemicTherapySchedule
    form_class = SystemicTherapyScheduleForm
    
    def get_success_url(self):
        return reverse('client_app:patient_summary') + f'?patient_id={self.object.systemic_therapy.diagnosis.patient.patient_id}'


# Base classes for List and Update views
class BaseListView(LoginRequiredMixin, ListView):
    """Base view for listing model instances"""
    template_name = 'client_app/model_list.html'
    paginate_by = 25
    edit_url_name = None  # Override in subclass
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f"{self.model._meta.verbose_name_plural}"
        context['model_name'] = self.model._meta.verbose_name
        context['model_name_plural'] = self.model._meta.verbose_name_plural
        context['edit_url_name'] = self.edit_url_name or f'client_app:{self.model._meta.model_name}_edit'
        return context


class BaseUpdateView(LoginRequiredMixin, UpdateView):
    """Base view for updating model instances"""
    template_name = 'client_app/form_template.html'
    pk_url_kwarg = 'pk'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f"Edit {self.model._meta.verbose_name}"
        context['model_name'] = self.model._meta.verbose_name
        return context
    
    def get_form(self, form_class=None):
        """Set widget choices for Select2 fields with current values"""
        form = super().get_form(form_class)
        
        # For Select2 widgets to show current values
        for field_name, field in form.fields.items():
            if hasattr(form.instance, field_name):
                current_value = getattr(form.instance, field_name)
                if current_value and isinstance(field, forms.ModelChoiceField):
                    if not isinstance(field, forms.ModelMultipleChoiceField):
                        if hasattr(field.widget, 'choices'):
                            field.widget.choices = [(current_value.pk, str(current_value))]
        
        return form
