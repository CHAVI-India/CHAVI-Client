import re

from django import forms
from django.utils import timezone

from client_app.models import Patient
from dicom_server.models import (
    BulkRetrievalSchedule, DICOMServerConfiguration, RemoteDICOMNode,
)
from dicom_server.services import patient_ids

_TRANSFORM_HELP = (
    'One rule per line, "regex => replacement" — e.g. '
    '^MR/(\\d+)/(\\d+)$ => \\1_\\2 turns MR/25/004771 into 25_004771. '
    'Applied to every patient queried against this node.'
)


class DICOMServerConfigForm(forms.ModelForm):
    class Meta:
        model = DICOMServerConfiguration
        fields = ['ae_title', 'port', 'bind_address', 'max_pdu', 'qr_timeout', 'is_enabled']


class RemoteDICOMNodeForm(forms.ModelForm):
    patient_id_transforms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text=_TRANSFORM_HELP,
        label='Patient ID transform rules',
    )

    class Meta:
        model = RemoteDICOMNode
        fields = [
            'name', 'ae_title', 'host', 'port', 'is_active', 'prefer_c_get',
            'auto_retrieve_enabled',
            'auto_retrieve_minute', 'auto_retrieve_hour',
            'auto_retrieve_day_of_week', 'auto_retrieve_day_of_month',
            'auto_retrieve_month_of_year',
            'auto_retrieve_min_interval_minutes',
            'auto_retrieve_batch_size',
            'patient_id_transforms',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['patient_id_transforms'].initial = (
                patient_ids.transforms_to_lines(self.instance.patient_id_transforms)
            )

    def clean_patient_id_transforms(self):
        transforms = patient_ids.parse_transform_lines(
            self.cleaned_data['patient_id_transforms'],
        )
        errors = patient_ids.validate_transforms(transforms)
        if errors:
            raise forms.ValidationError(' '.join(errors))
        return transforms


class BulkRetrieveForm(forms.Form):
    node = forms.ModelChoiceField(
        queryset=RemoteDICOMNode.objects.filter(is_active=True),
        empty_label='-- Select a remote node --',
        help_text="Remote PACS/node to query",
    )
    patients = forms.ModelMultipleChoiceField(
        queryset=Patient.objects.filter(chavi_consent=True),
        widget=forms.SelectMultiple(attrs={'class': 'patient-select w-full'}),
        error_messages={
            'invalid_choice': 'One or more selected patients cannot be retrieved '
                              '— CHAVI consent is required.',
        },
        help_text="Only consented patients registered in the Patient model can be retrieved",
    )
    extra_transforms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Optional extra remote-ID rules for this query only. ' + _TRANSFORM_HELP,
        label='Extra patient ID transforms (this query only)',
    )

    def clean_extra_transforms(self):
        transforms = patient_ids.parse_transform_lines(
            self.cleaned_data['extra_transforms'],
        )
        errors = patient_ids.validate_transforms(transforms)
        if errors:
            raise forms.ValidationError(' '.join(errors))
        return transforms


class RetrieveStudiesForm(forms.Form):
    node = forms.ModelChoiceField(
        queryset=RemoteDICOMNode.objects.filter(is_active=True),
        empty_label='-- Select a remote node --',
        help_text="Remote PACS/node to query",
    )
    patient = forms.ModelChoiceField(
        queryset=Patient.objects.filter(chavi_consent=True),
        widget=forms.Select(attrs={'class': 'patient-select'}),
        error_messages={
            'invalid_choice': 'This patient cannot be retrieved — CHAVI consent is required.',
        },
        help_text="Only consented patients registered in the Patient model can be retrieved",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['node'].queryset = RemoteDICOMNode.objects.filter(is_active=True)


_CRON_RE = re.compile(r'^[\d\-\,\*/]+$')


class BulkScheduleForm(forms.ModelForm):
    patients = forms.ModelMultipleChoiceField(
        queryset=Patient.objects.filter(chavi_consent=True),
        widget=forms.SelectMultiple(attrs={'class': 'patient-select w-full'}),
        error_messages={
            'invalid_choice': 'One or more selected patients cannot be scheduled '
                              '— CHAVI consent is required.',
        },
        help_text="Only consented patients registered in the Patient model.",
    )
    extra_transforms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Optional extra remote-ID rules. ' + _TRANSFORM_HELP,
        label='Extra patient ID transforms',
    )
    run_at = forms.DateTimeField(
        required=False,
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='When to run the one-off retrieval (required for one-off mode).',
    )

    class Meta:
        model = BulkRetrievalSchedule
        fields = [
            'name', 'node', 'mode', 'patients', 'run_at',
            'minute', 'hour', 'day_of_week', 'day_of_month', 'month_of_year',
            'max_concurrent_patients', 'retrieve_new_only',
            'select_modalities', 'select_approval',
            'select_series_description', 'select_rt_label',
            'study_date_from', 'study_date_to',
        ]
        widgets = {'mode': forms.RadioSelect}

    def clean_extra_transforms(self):
        transforms = patient_ids.parse_transform_lines(
            self.cleaned_data['extra_transforms'],
        )
        errors = patient_ids.validate_transforms(transforms)
        if errors:
            raise forms.ValidationError(' '.join(errors))
        return transforms

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('mode')
        if mode == BulkRetrievalSchedule.Mode.PERIODIC:
            for name in ('minute', 'hour', 'day_of_week', 'day_of_month', 'month_of_year'):
                value = cleaned.get(name) or ''
                if not _CRON_RE.match(value):
                    self.add_error(name, 'Invalid cron field value.')
        elif mode == BulkRetrievalSchedule.Mode.ONE_OFF:
            run_at = cleaned.get('run_at')
            if not run_at:
                self.add_error('run_at', 'Required for one-off schedules.')
            else:
                if timezone.is_naive(run_at):
                    run_at = timezone.make_aware(run_at)
                if run_at < timezone.now():
                    self.add_error('run_at', 'Run time must be in the future.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.extra_transforms = self.cleaned_data['extra_transforms']
        # Re-scheduling a one-off: clear the old task id so the signal re-dispatches.
        if instance.mode == BulkRetrievalSchedule.Mode.ONE_OFF:
            if not instance.pk or instance.run_at:
                instance.one_off_task_id = ''
        if commit:
            instance.save()
            self.save_m2m()
        return instance
