"""Live interoperability tests against a public DICOM test server.

Disabled by default — run explicitly with:

    DICOM_LIVE_TESTS=1 python manage.py test dicom_server.tests.test_live

Defaults target https://www.dicomserver.co.uk (C-ECHO/C-FIND/C-GET/C-STORE on
ports 104 and 11112). Override via DICOM_LIVE_HOST / DICOM_LIVE_PORT /
DICOM_LIVE_AET.

WARNING: the target is a PUBLIC server — only synthetic/anonymised datasets are
ever pushed, and only via the test-only push_dataset() helper. The shipped
application never sends instances outward.

C-MOVE is intentionally NOT exercised here: dicomserver.co.uk requires the
move destination to be reachable at the requesting IP, which fails behind
NAT. C-MOVE is covered locally by the stub-PACS tests in test_qr.py.
"""
import os
import unittest

from django.test import TransactionTestCase, tag

from client_app.models import DICOMStudy, Patient, SiteConfiguration
from dicom_server.models import (
    InboundDICOMInstance, RemoteDICOMNode,
)
from dicom_server.services import qr_client
from dicom_server.tests.utils import make_test_dataset, push_dataset

LIVE = os.environ.get('DICOM_LIVE_TESTS')
HOST = os.environ.get('DICOM_LIVE_HOST', 'www.dicomserver.co.uk')
PORT = int(os.environ.get('DICOM_LIVE_PORT', '11112'))
AET = os.environ.get('DICOM_LIVE_AET', 'DICOMSERVER')

SYNTHETIC_PATIENT_ID = 'CHAVI-LIVE-TEST-001'


@tag('live')
@unittest.skipUnless(LIVE, 'Set DICOM_LIVE_TESTS=1 to run live DICOM tests')
class LiveDicomServerTest(TransactionTestCase):
    """End-to-end against a public test server: echo, find, and a
    C-STORE → C-FIND → C-GET roundtrip through the real ingest path."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.node = RemoteDICOMNode(
            name='live-test', ae_title=AET, host=HOST, port=PORT,
            prefer_c_get=True,
        )

    def setUp(self):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Hospital',
        )
        self.patient = Patient.objects.create(
            patient_id=SYNTHETIC_PATIENT_ID, gender='Female',
        )
        # .update() bypasses post_save — no auto-retrieval dispatch
        Patient.objects.filter(pk=self.patient.pk).update(chavi_consent=True)
        self.patient.chavi_consent = True

    def test_live_echo(self):
        ok, reason = qr_client.echo(self.node)
        self.assertTrue(ok, reason)

    def test_live_find(self):
        """C-FIND for our synthetic patient — pushes a dataset first so the
        query has something to match."""
        ds = make_test_dataset(patient_id=SYNTHETIC_PATIENT_ID)
        status = push_dataset(HOST, PORT, AET, ds)
        self.assertIsNotNone(status, 'association to live server failed')
        self.assertEqual(status.Status, 0x0000, f'C-STORE rejected: 0x{status.Status:04X}')

        studies = qr_client.find_studies(self.node, SYNTHETIC_PATIENT_ID)
        uids = [s['study_instance_uid'] for s in studies]
        if ds.StudyInstanceUID not in uids:
            self.skipTest('server did not retain/return the pushed study')

    def test_live_store_find_get_roundtrip(self):
        """Push a synthetic instance, query it, pull it back via C-GET, and
        verify it lands in DICOMStudy through the normal ingest path."""
        ds = make_test_dataset(patient_id=SYNTHETIC_PATIENT_ID)
        status = push_dataset(HOST, PORT, AET, ds)
        self.assertIsNotNone(status, 'association to live server failed')
        self.assertEqual(status.Status, 0x0000, f'C-STORE rejected: 0x{status.Status:04X}')

        studies = qr_client.find_studies(self.node, SYNTHETIC_PATIENT_ID)
        uids = [s['study_instance_uid'] for s in studies]
        if ds.StudyInstanceUID not in uids:
            self.skipTest('server did not retain/return the pushed study')

        stats = qr_client.get_study(self.node, ds.StudyInstanceUID, SYNTHETIC_PATIENT_ID)
        self.assertGreaterEqual(stats['completed'], 1)
        self.assertTrue(
            DICOMStudy.objects.filter(study_instance_uid=ds.StudyInstanceUID).exists(),
        )
        self.assertTrue(
            InboundDICOMInstance.objects.filter(
                sop_instance_uid=ds.SOPInstanceUID, status='STORED',
            ).exists(),
        )

    def test_live_unknown_patient_get_rejected(self):
        """A C-GET-delivered instance for a patient not in the Patient model
        must be rejected by ingest even though the remote serves it."""
        unknown_id = 'CHAVI-LIVE-UNKNOWN-999'
        ds = make_test_dataset(patient_id=unknown_id)
        status = push_dataset(HOST, PORT, AET, ds)
        self.assertIsNotNone(status)
        self.assertEqual(status.Status, 0x0000)

        stats = qr_client.get_study(self.node, ds.StudyInstanceUID, unknown_id)
        self.assertEqual(stats['completed'], 0)
        self.assertTrue(
            InboundDICOMInstance.objects.filter(
                sop_instance_uid=ds.SOPInstanceUID, status='REJECTED',
            ).exists(),
        )
