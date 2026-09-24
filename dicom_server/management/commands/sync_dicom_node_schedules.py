from django.core.management.base import BaseCommand
from dicom_server.services.schedule_sync import sync_all_node_schedules


class Command(BaseCommand):
    help = 'Sync RemoteDICOMNode auto-retrieval schedules to django-celery-beat'

    def handle(self, *args, **options):
        sync_all_node_schedules()
        self.stdout.write(self.style.SUCCESS('Schedules synced.'))
