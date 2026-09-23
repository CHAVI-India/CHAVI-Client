"""Loopback tests for the Q/R SCU client (qr_client.py).

test_move/test_get run end-to-end against a stub pynetdicom QR SCP playing the
role of a remote PACS, plus our real Storage SCP as the destination.
"""
import tempfile
from pathlib import Path

from django.test import TransactionTestCase, override_settings
from pydicom.dataset import Dataset
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import (
    Verification,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelGet,
)

from client_app.models import Patient, DICOMStudy, SiteConfiguration
from dicom_server.models import RemoteDICOMNode, RetrievalJob
from dicom_server.services import qr_client
from dicom_server.scp.server import build_ae, HANDLERS
from dicom_server.tasks import task_retrieve_studies
from dicom_server.tests.utils import make_test_dataset


class _StubPACS:
    """A pynetdicom AE acting as a remote PACS for tests."""

    def __init__(self, datasets, move_dest=None):
        self.datasets = datasets
        self.move_dest = move_dest
        self.ae = AE(ae_title='STUBPACS')
        self.ae.supported_contexts = StoragePresentationContexts

        handlers = []
        self.ae.add_supported_context(Verification)
        handlers.append((evt.EVT_C_ECHO, lambda event: 0x0000))
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
        handlers.append((evt.EVT_C_FIND, self._handle_find))
        if move_dest is not None:
            self.ae.requested_contexts = StoragePresentationContexts
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)
            handlers.append((evt.EVT_C_MOVE, self._handle_move))
        else:
            for cx in self.ae.supported_contexts:
                cx.scp_role = True
                cx.scu_role = False
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
            handlers.append((evt.EVT_C_GET, self._handle_get))

        self.server = self.ae.start_server(
            ('127.0.0.1', 0), block=False, evt_handlers=handlers,
        )
        self.port = self.server.server_address[1]

    def _handle_move(self, event):
        yield ('127.0.0.1', self.move_dest)
        yield len(self.datasets)
        for ds in self.datasets:
            yield 0xFF00, ds

    def _handle_get(self, event):
        yield len(self.datasets)
        for ds in self.datasets:
            yield 0xFF00, ds

    def _handle_find(self, event):
        seen = set()
        for ds in self.datasets:
            uid = ds.StudyInstanceUID
            if uid in seen:
                continue
            seen.add(uid)
            if event.is_cancelled:
                yield 0xFE00, None
                return
            rsp = Dataset()
            rsp.QueryRetrieveLevel = 'STUDY'
            rsp.PatientID = getattr(ds, 'PatientID', '')
            rsp.StudyInstanceUID = uid
            rsp.StudyDate = getattr(ds, 'StudyDate', '')
            rsp.StudyDescription = getattr(ds, 'StudyDescription', '')
            rsp.ModalitiesInStudy = getattr(ds, 'Modality', '')
            yield 0xFF00, rsp

    def shutdown(self):
        self.server.shutdown()


class QRClientTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        cls.ae = build_ae()
        cls.scp = cls.ae.start_server(('127.0.0.1', 0), block=False, evt_handlers=HANDLERS)
        cls.scp_port = cls.scp.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.scp.shutdown()
        cls._override.disable()
        super().tearDownClass()

    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test Hospital')
        self.patient = Patient.objects.create(patient_id='MR/25/004771', gender='Female')
        self.media = Path(self._media)

    def _node(self, port, **kwargs):
        return RemoteDICOMNode.objects.create(
            name='stub', ae_title='STUBPACS', host='127.0.0.1', port=port, **kwargs
        )

    def _own_node(self):
        from dicom_server.models import DICOMServerConfiguration
        return RemoteDICOMNode(
            name='self', ae_title=DICOMServerConfiguration.load().ae_title,
            host='127.0.0.1', port=self.scp_port,
        )

    def test_echo_local(self):
        self.assertTrue(qr_client.echo(self._own_node()))

    def test_echo_unreachable(self):
        node = self._node(port=1)  # nothing listening
        self.assertFalse(qr_client.echo(node))

    def test_find_studies_local(self):
        # Ingest a study into our SCP's store first
        from dicom_server.services.ingest import ingest_dataset
        ds = make_test_dataset(patient_id='MR/25/004771')
        ingest_dataset(ds)

        results = qr_client.find_studies(self._own_node(), 'MR/25/004771')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['study_instance_uid'], ds.StudyInstanceUID)
        self.assertEqual(results[0]['modalities'], 'CT')

    def test_move_study_end_to_end(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        pacs = _StubPACS([ds], move_dest=self.scp_port)
        try:
            node = self._node(port=pacs.port)
            stats = qr_client.move_study(node, ds.StudyInstanceUID, 'MR/25/004771')
        finally:
            pacs.shutdown()

        self.assertEqual(stats['completed'], 1)
        self.assertEqual(stats['failed'], 0)
        self.assertTrue(
            DICOMStudy.objects.filter(study_instance_uid=ds.StudyInstanceUID).exists()
        )

    def test_get_study_end_to_end(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        pacs = _StubPACS([ds])
        try:
            node = self._node(port=pacs.port)
            stats = qr_client.get_study(node, ds.StudyInstanceUID, 'MR/25/004771')
        finally:
            pacs.shutdown()

        self.assertEqual(stats['completed'], 1)
        self.assertTrue(
            DICOMStudy.objects.filter(study_instance_uid=ds.StudyInstanceUID).exists()
        )

    def test_get_unknown_patient_fails_subop(self):
        ds = make_test_dataset(patient_id='NOPE')
        pacs = _StubPACS([ds])
        try:
            node = self._node(port=pacs.port)
            stats = qr_client.get_study(node, ds.StudyInstanceUID, 'NOPE')
        finally:
            pacs.shutdown()

        self.assertEqual(stats['completed'], 0)
        self.assertEqual(stats['failed'], 1)
        self.assertFalse(
            DICOMStudy.objects.filter(study_instance_uid=ds.StudyInstanceUID).exists()
        )

    def test_task_retrieve_studies_cget(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        pacs = _StubPACS([ds])
        try:
            node = self._node(port=pacs.port, prefer_c_get=True)
            job = RetrievalJob.objects.create(node=node, patient=self.patient)
            result = task_retrieve_studies(node.pk, 'MR/25/004771', None, job.pk)
        finally:
            pacs.shutdown()

        job.refresh_from_db()
        self.assertEqual(job.status, 'SUCCESS')
        self.assertEqual(job.instances_received, 1)
        self.assertTrue(
            DICOMStudy.objects.filter(study_instance_uid=ds.StudyInstanceUID).exists()
        )
        self.assertEqual(result['status'], 'SUCCESS')
