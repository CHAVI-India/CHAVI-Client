from django import forms
from django.forms import ModelForm
from django.db import models
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Div, Field, HTML, Row, Column
from crispy_forms.bootstrap import FormActions
from django_select2.forms import ModelSelect2Widget, Select2Widget, ModelSelect2MultipleWidget
from django.contrib.admin.widgets import FilteredSelectMultiple
from .models import (
    Comorbidity, Symptom, PatientAssessment, LaboratoryResults,
    PatientOutcome, PatientReportedOutcome, GermlineGenomicAlterations,
    Diagnosis, Pathology, StageInformation, Lesion, LesionResponse,
    Surgery, Radiotherapy, SystemicTherapy, OtherTreatment,
    ConcomitantMedications, Outcome, AdverseEffects, Immunohistochemistry,
    Cytogenetics, SomaticGenomicAlterations, GeneExpressionData, EpigeneticData,
    RadiotherapyVolume, RadiotherapyDoseVolumeData, SystemicTherapySchedule,
    PatientDicomFile, DICOMStudy, Patient
)
from lookup.models import *


class Select2WidgetMixin:
    """Mixin to apply Select2 widgets to ForeignKey and ChoiceFields"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Apply Select2 to all ForeignKey and ChoiceFields
        print(f"Select2WidgetMixin: Processing {len(self.fields)} fields")
        for field_name, field in self.fields.items():
            # Apply Select2 widget to ForeignKey fields
            if isinstance(field, forms.ModelChoiceField):
                # Get search fields from the model
                model = field.queryset.model
                search_fields = self._get_search_fields(model)
                print(f"  Applying Select2 to {field_name} (model: {model.__name__}, search: {search_fields})")
                
                if isinstance(field, forms.ModelMultipleChoiceField):
                    # Use ModelSelect2MultipleWidget for M2M fields
                    field.widget = ModelSelect2MultipleWidget(
                        model=model,
                        search_fields=search_fields,
                        attrs={
                            'data-width': '100%', 
                            'data-minimum-input-length': 0,
                            'data-placeholder': f'Select {model._meta.verbose_name_plural}...'
                        }
                    )
                else:
                    field.widget = ModelSelect2Widget(
                        model=model,
                        search_fields=search_fields,
                        attrs={'data-width': '100%', 'data-minimum-input-length': 0}
                    )
                
            # Apply Select2 widget to ChoiceFields (but not for regular choices - Select2 is for AJAX)
            # For regular choice fields, add Tailwind styling
            elif isinstance(field, forms.ChoiceField) and not isinstance(field, forms.BooleanField):
                print(f"  Adding Tailwind styling to choice field {field_name}")
                field.widget.attrs.update({
                    'class': 'bg-white focus:outline-none border border-gray-300 rounded-lg py-2 px-4 block w-full appearance-none leading-normal text-gray-700'
                })
    
    def _get_search_fields(self, model):
        """Get appropriate search fields for a model"""
        search_fields = []
        model_name = model.__name__
        
        # Special handling for Patient model
        if model_name == 'Patient':
            return ['patient_id__icontains']
        
        # Special handling for LookupProtein
        if model_name == 'LookupProtein':
            return ['gene_name__icontains', 'protein_name__icontains', 'code__icontains']
        
        # Special handling for LookupCTCAEGrade
        if model_name == 'LookupCTCAEGrade':
            return ['ctcae_term__icontains', 'description__icontains', 'code__icontains']
        
        # Check if model has 'label' field (most lookup models inherit from LookupAbstract)
        if hasattr(model, 'label'):
            search_fields.append('label__icontains')
            # Also add code for better search
            if hasattr(model, 'code'):
                search_fields.append('code__icontains')
            # Add unit_abbreviation if it exists (for unit models)
            if hasattr(model, 'unit_abbreviation'):
                search_fields.append('unit_abbreviation__icontains')
            return search_fields
        
        # Try other common field names
        for fname in ['name', 'title', 'term', 'description']:
            if hasattr(model, fname):
                search_fields.append(f'{fname}__icontains')
        
        # If no common fields found, use CharField/TextField fields
        if not search_fields:
            for f in model._meta.fields:
                if isinstance(f, (models.CharField, models.TextField)) and f.name not in ['id', 'created_at', 'updated_at', 'pk']:
                    search_fields.append(f'{f.name}__icontains')
                    if len(search_fields) >= 2:
                        break
        
        # Fallback to code or pk
        if not search_fields:
            if hasattr(model, 'code'):
                search_fields = ['code__icontains']
            else:
                search_fields = ['pk__icontains']
        
        return search_fields


class CrispyFormMixin:
    """Mixin to add crispy forms helper with Tailwind styling"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'space-y-6'
        self.helper.label_class = 'block text-sm font-medium text-gray-700 mb-1'
        self.helper.field_class = 'mt-1'
        # Don't render form tag - we'll do it manually to preserve widgets
        self.helper.form_tag = False
        
        # Add submit button
        self.helper.add_input(Submit('submit', 'Save', css_class='w-full sm:w-auto px-6 py-3 bg-chavi-primary text-white font-semibold rounded-lg hover:bg-chavi-primary-dark focus:outline-none focus:ring-2 focus:ring-chavi-primary focus:ring-offset-2 transition-colors'))


# Patient-level forms
class PatientForm(CrispyFormMixin, Select2WidgetMixin, ModelForm):
    class Meta:
        model = Patient
        fields = [
            'patient_id', 'gender', 'date_of_birth', 'date_of_registration',
            'chavi_consent', 'date_chavi_consent', 'patient_project',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_of_registration': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_chavi_consent': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'chavi_consent': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('chavi_consent') and not cleaned_data.get('date_chavi_consent'):
            self.add_error('date_chavi_consent', 'Enter the date when CHAVI consent was provided.')
        return cleaned_data


class ComorbidityForm(CrispyFormMixin, Select2WidgetMixin, ModelForm):
    class Meta:
        model = Comorbidity
        fields = [
            'patient', 'comorbidity_type', 'date_of_comorbidity_assessment',
            'duration_of_comorbidity', 'comorbidity_resolved', 'medication_for_comorbidity'
        ]
        widgets = {
            'date_of_comorbidity_assessment': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'comorbidity_resolved': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
            'medication_for_comorbidity': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
        }


class SymptomForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Symptom
        fields = [
            'patient', 'symptom', 'date_symptom_assessment', 'duration_of_symptom',
            'date_resolution', 'severity'
        ]
        widgets = {
            'date_symptom_assessment': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_resolution': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class PatientAssessmentForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = PatientAssessment
        fields = [
            'patient', 'date_assessment', 'height', 'weight', 'systolic_blood_pressure',
            'diastolic_blood_pressure', 'pulse', 'temperature', 'respiratory_rate',
            'performance_status'
        ]
        widgets = {
            'date_assessment': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class LaboratoryResultsForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = LaboratoryResults
        fields = [
            'patient', 'laboratory_test', 'result_date', 'quantitative_result_value',
            'quantitative_result_unit', 'qualitative_laboratory_result'
        ]
        widgets = {
            'result_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class PatientOutcomeForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = PatientOutcome
        fields = [
            'patient', 'patient_status', 'date_of_death', 'last_date_of_follow_up',
            'death_related_to_cancer_progression'
        ]
        widgets = {
            'date_of_death': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'last_date_of_follow_up': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'death_related_to_cancer_progression': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
        }


class PatientReportedOutcomeForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = PatientReportedOutcome
        fields = [
            'patient', 'pro_assessment_date', 'pro_instrument', 'pro_scale',
            'pro_question_id', 'pro_question', 'pro_answer', 'pro_score'
        ]
        widgets = {
            'pro_assessment_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'pro_question': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'pro_answer': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }


class GermlineGenomicAlterationsForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = GermlineGenomicAlterations
        fields = [
            'patient', 'date_test', 'cosmic_gene_name', 'reference_sequence',
            'protein_modification', 'variant_type', 'allele_frequency', 'read_depth',
            'clinical_significance'
        ]
        widgets = {
            'date_test': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class PatientDicomFileForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = PatientDicomFile
        fields = ['patient', 'file']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-control', 'accept': '.zip'}),
        }


# Diagnosis-level forms
class DiagnosisForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Diagnosis
        fields = [
            'patient', 'cancer_system', 'diagnosis', 'diagnosis_date', 'presentation_type',
            'cancer_site', 'cancer_side', 'diagnostic_modality', 'study_instance_uid',
            'diagnosis_project'
        ]
        widgets = {
            'diagnosis_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class PathologyForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Pathology
        fields = [
            'diagnosis', 'date_pathology', 'specimen_type', 'tumor_site', 'tumor_side',
            'histological_type', 'histological_grade', 'greatest_dimension_of_tumor',
            'additional_tumor_dimension_1', 'additional_tumor_dimension_2', 'tumor_dimesion_unit',
            'tumor_focality', 'lymphatic_vascular_invasion', 'perineural_invasion',
            'dermal_lymphatic_vascular_invasion', 'necrosis', 'necrosis_percentage',
            'mitotic_count', 'margin_status', 'closest_margin_distance',
            'closest_margin_distance_unit', 'treatment_effect', 'primary_gleason_grade',
            'secondary_gleason_grade', 'lymph_nodes_removed', 'lymph_nodes_in_specimen',
            'lymph_node_extracapsular_extension', 'number_of_uninvolved_nodes',
            'number_of_nodes_with_macrometastases', 'number_of_nodes_with_micrometastases',
            'number_of_nodes_with_isolated_tumor_cells', 'number_of_nodes_with_extracapsular_extension'
        ]
        widgets = {
            'date_pathology': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'lymph_nodes_removed': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
            'lymph_node_extracapsular_extension': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
        }


class StageInformationForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = StageInformation
        fields = [
            'diagnosis', 'staging_system', 'stage_type', 't_stage_prefix', 't_stage',
            't_stage_suffix', 'n_stage_prefix', 'n_stage', 'n_stage_suffix',
            'm_stage_prefix', 'm_stage', 'm_stage_suffix', 'overall_stage'
        ]


class LesionForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Lesion
        fields = [
            'diagnosis', 'date_lesion_assessed', 'lesion_site', 'lesion_type',
            'lesion_laterality', 'lesion_size_x_axis', 'lesion_size_y_axis',
            'lesion_size_z_axis', 'lesion_size_unit', 'lesion_volume', 'lesion_volume_unit',
            'lesion_detection_modality', 'lesion_suv_max', 'study_instance_uid'
        ]
        widgets = {
            'date_lesion_assessed': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class LesionResponseForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = LesionResponse
        fields = [
            'lesion', 'lesion_response_date', 'lesion_response', 'residual_lesion_size_x_axis',
            'residual_lesion_size_y_axis', 'residual_lesion_size_z_axis',
            'residual_lesion_size_unit', 'residual_lesion_volume', 'residual_lesion_volume_unit',
            'lesion_response_suv_max', 'lesion_response_modality', 'study_instance_uid'
        ]
        widgets = {
            'lesion_response_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class SurgeryForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Surgery
        fields = [
            'diagnosis', 'surgery_date', 'surgery_side', 'surgery_type', 'surgery_intent',
            'nodal_assessment', 'nodal_assessment_type', 'reconstruction', 'type_reconstruction',
            'study_instance_uid'
        ]
        widgets = {
            'surgery_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'nodal_assessment': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
            'reconstruction': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
        }


class RadiotherapyForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Radiotherapy
        fields = [
            'diagnosis', 'radiotherapy_course_type', 'radiotherapy_modality', 'reirradiation',
            'total_dose', 'total_fractions', 'simultaneous_integrated_boost',
            'simultaneous_integrated_boost_dose', 'radiation_dose_units', 'radiotherapy_intent',
            'radiotherapy_type', 'radiotherapy_technique', 'fractions_per_day',
            'radiotherapy_side', 'radiotherapy_machine', 'radiotherapy_start_date',
            'radiotherapy_end_date', 'study_instance_uid'
        ]
        widgets = {
            'radiotherapy_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'radiotherapy_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'reirradiation': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
            'simultaneous_integrated_boost': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-chavi-primary focus:ring-chavi-primary border-gray-300 rounded'}),
        }


class SystemicTherapyForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = SystemicTherapy
        fields = [
            'diagnosis', 'systemic_therapy_type', 'systemic_therapy_intent',
            'systemic_therapy_sequence', 'systemic_therapy_regimen', 'systemic_therapy_start_date',
            'systemic_therapy_end_date', 'cycles_delivered', 'study_instance_uid'
        ]
        widgets = {
            'systemic_therapy_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'systemic_therapy_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class OtherTreatmentForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = OtherTreatment
        fields = [
            'diagnosis', 'treatment_intent', 'treatment', 'treatment_start_date',
            'treatment_end_date'
        ]
        widgets = {
            'treatment_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'treatment_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class ConcomitantMedicationsForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = ConcomitantMedications
        fields = [
            'diagnosis', 'medication_name', 'medication_dose', 'medication_dose_units',
            'date_medication_start_date', 'date_medication_end_date', 'medication_route'
        ]
        widgets = {
            'date_medication_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_medication_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class OutcomeForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Outcome
        fields = ['diagnosis', 'date_outcome_assessed', 'outcome_type', 'study_instance_uid']
        widgets = {
            'date_outcome_assessed': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class AdverseEffectsForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = AdverseEffects
        fields = [
            'diagnosis', 'ctcae_grade_lookup', 'adverse_effect_start_date',
            'adverse_effect_end_date'
        ]
        widgets = {
            'adverse_effect_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'adverse_effect_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


# Pathology sub-forms
class ImmunohistochemistryForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Immunohistochemistry
        fields = [
            'pathology', 'date_ihc', 'protein_name', 'ihc_result',
            'percentage_positive_tumor_cells', 'percentage_positive_immune_cells',
            'tumor_cell_staining_intensity', 'allred_score', 'cps_score', 'tps_score'
        ]
        widgets = {
            'date_ihc': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class CytogeneticsForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = Cytogenetics
        fields = [
            'pathology', 'date_cytogenetics', 'gene', 'cytogenetic_abnormality',
            'cytogenetic_result'
        ]
        widgets = {
            'date_cytogenetics': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class SomaticGenomicAlterationsForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = SomaticGenomicAlterations
        fields = [
            'pathology', 'date_test', 'cosmic_gene_name', 'reference_sequence',
            'protein_modification', 'variant_type', 'allele_frequency', 'read_depth',
            'clinical_significance'
        ]
        widgets = {
            'date_test': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class GeneExpressionDataForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = GeneExpressionData
        fields = ['pathology', 'date_test', 'gene', 'expression_value', 'expression_units']
        widgets = {
            'date_test': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class EpigeneticDataForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = EpigeneticData
        fields = [
            'pathology', 'date_test', 'gene', 'epigenetic_abnormality_type',
            'epigenetic_result'
        ]
        widgets = {
            'date_test': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


# Radiotherapy sub-forms
class RadiotherapyVolumeForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = RadiotherapyVolume
        fields = [
            'radiotherapy', 'volume_name', 'volume_type', 'volume_dose_prescribed',
            'radiation_dose_units', 'volume_fractions', 'volume_radiotherapy_start_date',
            'volume_radiotherapy_end_date', 'anatomical_locations'
        ]
        widgets = {
            'volume_radiotherapy_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'volume_radiotherapy_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class RadiotherapyDoseVolumeDataForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = RadiotherapyDoseVolumeData
        fields = [
            'radiotherapy', 'volume_name', 'volume_type', 'absolute_volume',
            'relative_volume', 'volume_units', 'absolute_dose', 'relative_dose',
            'volume_dose_prescribed', 'radiation_dose_units'
        ]


# Systemic Therapy sub-forms
class SystemicTherapyScheduleForm(Select2WidgetMixin, CrispyFormMixin, ModelForm):
    class Meta:
        model = SystemicTherapySchedule
        fields = [
            'systemic_therapy', 'systemic_therapy_agent_route', 'systemic_therapy_agent_start_date',
            'systemic_therapy_agent_end_date', 'systemic_therapy_agent', 'systemic_therapy_dose_planned',
            'systemic_therapy_dose_administered', 'systemic_therapy_dose_units'
        ]
        widgets = {
            'systemic_therapy_agent_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'systemic_therapy_agent_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
