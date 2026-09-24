from django.apps import AppConfig


class DicomServerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dicom_server'
    verbose_name = 'DICOM Server'

    def ready(self):
        import dicom_server.signals  # noqa: F401
