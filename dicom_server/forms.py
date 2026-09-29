from django import forms

from client_app.models import Patient
from dicom_server.models import DICOMServerConfiguration, RemoteDICOMNode
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
