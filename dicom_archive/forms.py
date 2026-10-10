"""Forms for the DICOM archive frontend (plan 03)."""
from django import forms
from django.core.exceptions import ValidationError

from dicom_archive.models import ArchiveConfiguration, ArchiveLocation
from dicom_archive.services.locations import prepare_location


class ArchiveConfigurationForm(forms.ModelForm):
    """Singleton archive config. Cron-field validation lives in the model's
    clean() (plan 01) — ModelForm._post_clean runs the instance full_clean(),
    so bad cron fields surface as field errors without duplicating the
    regex here."""

    class Meta:
        model = ArchiveConfiguration
        fields = [
            'enabled', 'archive_after_days', 'delete_local_after_archive',
            'archive_minute', 'archive_hour',
            'archive_day_of_week', 'archive_day_of_month',
            'archive_month_of_year', 'batch_limit',
        ]


class ArchiveLocationForm(forms.ModelForm):
    """Location CRUD. clean() proves the path is resolvable AND writable via
    services.locations.prepare_location on a transient (never saved)
    instance, mapping its ValidationError to the path field."""

    class Meta:
        model = ArchiveLocation
        fields = ['name', 'storage_type', 'path', 'is_default', 'is_active']

    def clean(self):
        cleaned = super().clean()
        storage_type = cleaned.get('storage_type')
        path = (cleaned.get('path') or '').strip()
        if storage_type and path:
            try:
                prepare_location(ArchiveLocation(
                    storage_type=storage_type, path=path,
                ))
            except ValidationError as exc:
                self.add_error('path', exc.messages[0])
        return cleaned
