"""Loopback integration tests for the DICOM SCP.

Uses TransactionTestCase: pynetdicom association handlers run in their own
threads with separate DB connections, so test data must be committed to be
visible to them.
"""
import tempfile
from pathlib import Path

from django.test import TransactionTestCase, override_settings
from pydicom.dataset import Dataset
from pynetdicom import AE, StoragePresentationContexts
from pynetdicom.sop_class import (
    Verification, CTImageStorage,
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
)

from client_app.models import Patient, DICOMStudy, SiteConfiguration
from dicom_server.models import InboundDICOMInstance, DICOMServerConfiguration
from dicom_server.scp.server import build_ae, HANDLERS
from dicom_server.tests.utils import make_test_dataset, find_free_port


class LoopbackSCPTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        cls.ae = build_ae()
        cls.scp = cls.ae.start_server(
            ('127.0.0.1', 0), block=False, evt_handlers=HANDLERS,
        )
        cls.port = cls.scp.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.scp.shutdown()
        cls._override.disable()
        super().tearDownClass()

    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test Hospital')
        self.patient = Patient.objects.create(patient_id='MR/25/004771', gender='Female')
        self.media = Path(self._media)

    def _associate(self, *contexts):
        ae = AE()
        for cx in contexts:
            ae.add_requested_context(cx)
        assoc = ae.associate('127.0.0.1', self.port)
        self.assertTrue(assoc.is_established)
        return assoc

    def test_echo(self):
        assoc = self._associate(Verification)
        try:
            status = assoc.send_c_echo()
            self.assertEqual(status.Status, 0x0000)
        finally:
            assoc.release()

    def test_store_known_patient(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        assoc = self._associate(CTImageStorage)
        try:
            status = assoc.send_c_store(ds)
            self.assertEqual(status.Status, 0x0000)
        finally:
            assoc.release()

        study = DICOMStudy.objects.get(study_instance_uid=ds.StudyInstanceUID)
        self.assertEqual(study.patient, self.patient)
        stored = self.media / 'processed_dicom' / 'MR_25_004771'
        self.assertTrue(any(f.name.startswith(ds.SOPInstanceUID) for f in stored.glob('*/*.dcm')))
        self.assertEqual(InboundDICOMInstance.objects.get().status, 'STORED')

    def test_store_unknown_patient_rejected(self):
        ds = make_test_dataset(patient_id='NOPE')
        assoc = self._associate(CTImageStorage)
        try:
            status = assoc.send_c_store(ds)
            self.assertEqual(status.Status, 0xA700)
        finally:
            assoc.release()
        self.assertEqual(DICOMStudy.objects.count(), 0)
        self.assertEqual(InboundDICOMInstance.objects.get().status, 'REJECTED')

    def test_store_rejected_when_disabled(self):
        config = DICOMServerConfiguration.load()
        config.is_enabled = False
        config.save()
        try:
            ds = make_test_dataset(patient_id='MR/25/004771')
            assoc = self._associate(CTImageStorage)
            try:
                status = assoc.send_c_store(ds)
                self.assertEqual(status.Status, 0xA700)
            finally:
                assoc.release()
            self.assertEqual(DICOMStudy.objects.count(), 0)
        finally:
            config.is_enabled = True
            config.save()

    def test_find_patient_level(self):
        assoc = self._associate(PatientRootQueryRetrieveInformationModelFind)
        try:
            q = Dataset()
            q.QueryRetrieveLevel = 'PATIENT'
            q.PatientID = 'MR/25/004771'
            q.PatientName = ''
            responses = list(assoc.send_c_find(q, PatientRootQueryRetrieveInformationModelFind))
        finally:
            assoc.release()

        pending = [i for s, i in responses if s and s.Status == 0xFF00]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].PatientID, 'MR/25/004771')
        self.assertEqual(responses[-1][0].Status, 0x0000)

    def test_find_study_level(self):
        # Ingest a study first so C-FIND has something to return
        ds = make_test_dataset(patient_id='MR/25/004771')
        assoc = self._associate(CTImageStorage)
        try:
            assoc.send_c_store(ds)
        finally:
            assoc.release()

        assoc = self._associate(StudyRootQueryRetrieveInformationModelFind)
        try:
            q = Dataset()
            q.QueryRetrieveLevel = 'STUDY'
            q.PatientID = 'MR/25/004771'
            q.StudyInstanceUID = ''
            q.StudyDate = ''
            q.StudyDescription = ''
            q.ModalitiesInStudy = ''
            responses = list(assoc.send_c_find(q, StudyRootQueryRetrieveInformationModelFind))
        finally:
            assoc.release()

        pending = [i for s, i in responses if s and s.Status == 0xFF00]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].StudyInstanceUID, ds.StudyInstanceUID)
        self.assertEqual(pending[0].ModalitiesInStudy, 'CT')
        self.assertEqual(responses[-1][0].Status, 0x0000)

    def test_find_study_level_no_match(self):
        assoc = self._associate(StudyRootQueryRetrieveInformationModelFind)
        try:
            q = Dataset()
            q.QueryRetrieveLevel = 'STUDY'
            q.PatientID = 'NOBODY'
            q.StudyInstanceUID = ''
            responses = list(assoc.send_c_find(q, StudyRootQueryRetrieveInformationModelFind))
        finally:
            assoc.release()
        pending = [i for s, i in responses if s and s.Status == 0xFF00]
        self.assertEqual(pending, [])
        self.assertEqual(responses[-1][0].Status, 0x0000)
