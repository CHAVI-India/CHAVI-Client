from django import forms

from client_app.models import Patient
from dicom_server.models import DICOMServerConfiguration, RemoteDICOMNode


class DICOMServerConfigForm(forms.ModelForm):
    class Meta:
        model = DICOMServerConfiguration
        fields = ['ae_title', 'port', 'bind_address', 'max_pdu', 'qr_timeout', 'is_enabled']


class RemoteDICOMNodeForm(forms.ModelForm):
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
        ]


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
