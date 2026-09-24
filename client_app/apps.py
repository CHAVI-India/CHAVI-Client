from django.apps import AppConfig


class ClientAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'client_app'

    def ready(self):
        import client_app.signals  # noqa: F401
