from django.conf import settings
from django.test import SimpleTestCase


class AppScaffoldTests(SimpleTestCase):
    def test_app_registered_after_dicom_server(self):
        apps = list(settings.INSTALLED_APPS)
        self.assertIn('dicom_server', apps)
        self.assertIn('dicom_archive', apps)
        self.assertGreater(apps.index('dicom_archive'), apps.index('dicom_server'))

    def test_app_config(self):
        from django.apps import apps as django_apps
        config = django_apps.get_app_config('dicom_archive')
        self.assertEqual(config.verbose_name, 'DICOM Archive')
        self.assertEqual(config.default_auto_field, 'django.db.models.BigAutoField')
