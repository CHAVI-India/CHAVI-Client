from django.test import TestCase
from django_celery_beat.models import PeriodicTask

from dicom_server.models import RemoteDICOMNode
from dicom_server.services.schedule_sync import sync_node_schedule


class ScheduleSyncTests(TestCase):
    def test_enabling_creates_periodic_task(self):
        node = RemoteDICOMNode.objects.create(
            name='node', ae_title='AET', host='localhost', port=104,
            auto_retrieve_enabled=True,
            auto_retrieve_minute='0', auto_retrieve_hour='2',
        )
        sync_node_schedule(node)
        self.assertTrue(
            PeriodicTask.objects.filter(name=f'dicom-auto-retrieve-node-{node.pk}', enabled=True).exists()
        )

    def test_disabling_disables_periodic_task(self):
        node = RemoteDICOMNode.objects.create(
            name='node', ae_title='AET', host='localhost', port=104,
            auto_retrieve_enabled=True,
        )
        sync_node_schedule(node)
        node.auto_retrieve_enabled = False
        sync_node_schedule(node)
        pt = PeriodicTask.objects.get(name=f'dicom-auto-retrieve-node-{node.pk}')
        self.assertFalse(pt.enabled)
