from django.apps import AppConfig


class DicomArchiveConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dicom_archive'
    verbose_name = 'DICOM Archive'

    def ready(self):
        import dicom_archive.signals  # noqa: F401
