"""Loopback tests for the Q/R SCU client (qr_client.py).

test_move/test_get run end-to-end against a stub pynetdicom QR SCP playing the
role of a remote PACS, plus our real Storage SCP as the destination.
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TransactionTestCase, override_settings
from pydicom.dataset import Dataset
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import (
    Verification,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelGet,
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    PatientRootQueryRetrieveInformationModelGet,
)

from client_app.models import (
    Patient, DICOMStudy, DICOMInstance, SiteConfiguration,
)
from dicom_server.models import RemoteDICOMNode, RetrievalJob
from dicom_server.services import qr_client
from dicom_server.scp.server import build_ae, HANDLERS
from dicom_server.tasks import task_retrieve_studies
from dicom_server.tests.utils import make_test_dataset


class _StubPACS:
    """A pynetdicom AE acting as a remote PACS for tests.

    patient_root=True negotiates Patient Root Q/R only (the SCU must fall
    back from Study Root). echo_only=True supports only Verification, so any
    Q/R association is rejected at the presentation-context level.
    """

    def __init__(self, datasets, move_dest=None, patient_root=False,
                 echo_only=False, abort_on_find=False):
        self.datasets = datasets
        self.move_dest = move_dest
        self.ae = AE(ae_title='STUBPACS')
        self.ae.supported_contexts = StoragePresentationContexts

        if patient_root:
            find = PatientRootQueryRetrieveInformationModelFind
            move = PatientRootQueryRetrieveInformationModelMove
            get = PatientRootQueryRetrieveInformationModelGet
        else:
            find = StudyRootQueryRetrieveInformationModelFind
            move = StudyRootQueryRetrieveInformationModelMove
            get = StudyRootQueryRetrieveInformationModelGet

        handlers = []
        self.ae.add_supported_context(Verification)
        handlers.append((evt.EVT_C_ECHO, lambda event: 0x0000))
        if not echo_only:
            self.ae.add_supported_context(find)
            handlers.append((
                evt.EVT_C_FIND,
                self._handle_find_abort if abort_on_find else self._handle_find,
            ))
            if move_dest is not None:
                self.ae.requested_contexts = StoragePresentationContexts
                self.ae.add_supported_context(move)
                handlers.append((evt.EVT_C_MOVE, self._handle_move))
            else:
                for cx in self.ae.supported_contexts:
                    cx.scp_role = True
                    cx.scu_role = False
                self.ae.add_supported_context(get)
                handlers.append((evt.EVT_C_GET, self._handle_get))

        self.server = self.ae.start_server(
            ('127.0.0.1', 0), block=False, evt_handlers=handlers,
        )
        self.port = self.server.server_address[1]

    @staticmethod
    def _handle_find_abort(event):
        """Accepts the FIND context but aborts on the query itself —
        mimics storage-only nodes (e.g. a treatment machine's data system)."""
        event.assoc.abort()
        yield 0xFF00, Dataset()  # pragma: no cover — unreachable after abort

    def _selected(self, event):
        """Datasets matching the retrieve identifier's PatientID / Study /
        Series filters (empty values act as wildcards)."""
        pid = getattr(event.identifier, 'PatientID', '') or ''
        suid = getattr(event.identifier, 'StudyInstanceUID', '') or ''
        seuid = getattr(event.identifier, 'SeriesInstanceUID', '') or ''
        return [
            ds for ds in self.datasets
            if (not pid or ds.PatientID == pid)
            and (not suid or ds.StudyInstanceUID == suid)
            and (not seuid or ds.SeriesInstanceUID == seuid)
        ]

    def _handle_move(self, event):
        yield ('127.0.0.1', self.move_dest)
        selected = self._selected(event)
        yield len(selected)
        for ds in selected:
            yield 0xFF00, ds

    def _handle_get(self, event):
        selected = self._selected(event)
        yield len(selected)
        for ds in selected:
            yield 0xFF00, ds

    def _handle_find(self, event):
        level = str(getattr(event.identifier, 'QueryRetrieveLevel', '') or '').upper()
        q_pid = getattr(event.identifier, 'PatientID', '') or ''
        q_suid = getattr(event.identifier, 'StudyInstanceUID', '') or ''
        seen = set()
        for ds in self.datasets:
            if q_pid and ds.PatientID != q_pid:
                continue
            if event.is_cancelled:
                yield 0xFE00, None
                return
            if level == 'SERIES':
                if q_suid and ds.StudyInstanceUID != q_suid:
                    continue
                uid = ds.SeriesInstanceUID
                if uid in seen:
                    continue
                seen.add(uid)
                rsp = Dataset()
                rsp.QueryRetrieveLevel = 'SERIES'
                rsp.PatientID = getattr(ds, 'PatientID', '')
                rsp.StudyInstanceUID = ds.StudyInstanceUID
                rsp.SeriesInstanceUID = uid
                rsp.SeriesDescription = getattr(ds, 'SeriesDescription', '')
                rsp.Modality = getattr(ds, 'Modality', '')
                rsp.SeriesNumber = getattr(ds, 'SeriesNumber', '')
                yield 0xFF00, rsp
            else:
                uid = ds.StudyInstanceUID
                if uid in seen:
                    continue
                seen.add(uid)
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
        # .update() bypasses post_save — avoids an auto-retrieval dispatch
        # attempt to a broker that isn't running in tests
        self.patient = Patient.objects.create(patient_id='MR/25/004771', gender='Female')
        Patient.objects.filter(pk=self.patient.pk).update(chavi_consent=True)
        self.patient.chavi_consent = True
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
        ok, reason = qr_client.echo(self._own_node())
        self.assertTrue(ok, reason)

    def test_echo_unreachable(self):
        node = self._node(port=1)  # nothing listening
        ok, reason = qr_client.echo(node)
        self.assertFalse(ok)
        self.assertTrue(reason)  # the failure reason is reported, not swallowed

    def test_find_studies_local(self):
        # Ingest a study into our SCP's store first
        from dicom_server.services.ingest import ingest_dataset
        ds = make_test_dataset(patient_id='MR/25/004771')
        ingest_dataset(ds)

        results = qr_client.find_studies(self._own_node(), 'MR/25/004771')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['study_instance_uid'], ds.StudyInstanceUID)
        self.assertEqual(results[0]['modalities'], 'CT')

    def test_find_studies_patient_root_fallback(self):
        """Remote supports only Patient Root FIND — the SCU must negotiate
        it instead of failing."""
        ds = make_test_dataset(patient_id='MR/25/004771')
        pacs = _StubPACS([ds], patient_root=True)
        try:
            results = qr_client.find_studies(
                self._node(port=pacs.port), 'MR/25/004771'
            )
        finally:
            pacs.shutdown()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['study_instance_uid'], ds.StudyInstanceUID)

    def test_move_study_patient_root_fallback(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        pacs = _StubPACS([ds], move_dest=self.scp_port, patient_root=True)
        try:
            stats = qr_client.move_study(
                self._node(port=pacs.port), ds.StudyInstanceUID, 'MR/25/004771'
            )
        finally:
            pacs.shutdown()

        self.assertEqual(stats['completed'], 1)

    def test_find_studies_all_contexts_rejected(self):
        """Peer accepts the association but rejects every presentation
        context — the error must report the rejection reason, not the
        generic 'aborted' message."""
        pacs = _StubPACS([], echo_only=True)
        try:
            with self.assertRaises(ConnectionError) as cm:
                qr_client.find_studies(
                    self._node(port=pacs.port), 'MR/25/004771'
                )
        finally:
            pacs.shutdown()

        msg = str(cm.exception)
        self.assertIn('rejected all presentation contexts', msg)
        self.assertIn('Abstract Syntax Not Supported', msg)
        self.assertNotIn('aborted', msg)

    def test_find_studies_for_patient_raises_when_all_ids_fail(self):
        node = self._node(port=1)  # nothing listening
        with self.assertRaises(ConnectionError):
            qr_client.find_studies_for_patient(node, self.patient)

    @mock.patch('dicom_server.services.qr_client.find_studies')
    def test_find_studies_for_patient_partial_failure_returns_results(self, mock_find):
        def fake(node, pid):
            if pid == 'MR/25/004771':
                raise ConnectionError('dead')
            return [{'study_instance_uid': '1.2.3', 'study_date': '',
                     'study_description': '', 'modalities': 'CT', 'instances': 1}]
        mock_find.side_effect = fake
        results = qr_client.find_studies_for_patient(
            self._node(port=1), self.patient, aliases=['ALIAS'],
        )
        self.assertEqual(len(results), 1)

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

    def test_get_study_storage_uids_within_association_limit(self):
        uids = qr_client._get_storage_uids()
        # 128 contexts max per association; 1 slot goes to the Q/R-GET model
        self.assertLessEqual(len(uids), 127)
        self.assertEqual(len(uids), len(set(uids)))  # no duplicates
        # newer RT classes are now offered, e.g. Enhanced RT Image
        self.assertIn('1.2.840.10008.5.1.4.1.1.481.23', uids)

    def test_task_retrieve_studies_unreachable_node_fails_job(self):
        node = self._node(port=1)
        job = RetrievalJob.objects.create(node=node, patient=self.patient)
        with self.assertRaises(ConnectionError):
            task_retrieve_studies(node.pk, 'MR/25/004771', None, job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILED')
        self.assertIn('C-FIND', job.error_log)

    def test_find_studies_aborted_query_raises_connection_error(self):
        """Peer accepts the FIND context then aborts mid-query — must raise
        ConnectionError, not crash on the missing Status attribute."""
        pacs = _StubPACS([], abort_on_find=True)
        try:
            with self.assertRaises(ConnectionError) as cm:
                qr_client.find_studies(
                    self._node(port=pacs.port), 'MR/25/004771'
                )
        finally:
            pacs.shutdown()

        self.assertIn('aborted', str(cm.exception))

    @mock.patch(
        'pynetdicom.association.Association.send_c_echo',
        return_value=Dataset(),
    )
    def test_echo_aborted_reports_reason(self, mock_echo):
        """Empty status dataset (abort/timeout) → (False, reason), not an
        AttributeError."""
        pacs = _StubPACS([])
        try:
            ok, reason = qr_client.echo(self._node(port=pacs.port))
        finally:
            pacs.shutdown()

        self.assertFalse(ok)
        self.assertIn('aborted', reason)

    def test_get_study_rejected_raises_actionable_error(self):
        """Peer supports C-MOVE but not C-GET — the error must name the
        operation and tell the admin how to fix the node."""
        ds = make_test_dataset(patient_id='MR/25/004771')
        pacs = _StubPACS([ds], move_dest=self.scp_port)
        try:
            node = self._node(port=pacs.port)
            with self.assertRaises(qr_client.QRModelNotAcceptedError) as cm:
                qr_client.get_study(node, ds.StudyInstanceUID, 'MR/25/004771')
        finally:
            pacs.shutdown()

        msg = str(cm.exception)
        self.assertIn('does not support C-GET', msg)
        self.assertIn('stub', msg)  # node.name
        self.assertIn('C-MOVE', msg)

    @mock.patch.object(qr_client, 'get_study')
    def test_task_fails_fast_when_get_not_negotiated(self, mock_get):
        """When the peer rejects the retrieve presentation contexts, the
        remaining studies are failed immediately instead of repeating the
        doomed association."""
        mock_get.side_effect = qr_client.QRModelNotAcceptedError(
            "peer 'STUBPACS' does not support C-GET — switch to C-MOVE"
        )
        node = self._node(port=1, prefer_c_get=True)
        job = RetrievalJob.objects.create(
            node=node, patient=self.patient, study_uids=['1.2.3', '4.5.6'],
        )

        result = task_retrieve_studies(node.pk, 'MR/25/004771', None, job.pk)

        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(len(result['studies']), 2)
        self.assertTrue(all(s['failed'] for s in result['studies']))
        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILED')
        self.assertIn('does not support C-GET', job.error_log)

    def test_probe_qr_capabilities_move_only_peer(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        pacs = _StubPACS([ds], move_dest=self.scp_port)
        try:
            caps = qr_client.probe_qr_capabilities(
                self._node(port=pacs.port)
            )
        finally:
            pacs.shutdown()

        self.assertNotIn('error', caps)
        self.assertEqual(caps['find'], 'study')
        self.assertEqual(caps['move'], 'study')
        self.assertIsNone(caps['get'])
        self.assertGreater(caps['get_storage'], 0)

    def test_probe_qr_capabilities_broken_find(self):
        """Peer negotiates the FIND context but aborts the actual query —
        reported as 'broken', not supported."""
        pacs = _StubPACS([], abort_on_find=True)
        try:
            caps = qr_client.probe_qr_capabilities(
                self._node(port=pacs.port)
            )
        finally:
            pacs.shutdown()

        self.assertNotIn('error', caps)
        self.assertEqual(caps['find'], 'broken')

    def test_probe_qr_capabilities_unreachable(self):
        caps = qr_client.probe_qr_capabilities(self._node(port=1))
        self.assertIn('error', caps)
        self.assertIsNone(caps['find'])
        self.assertIsNone(caps['move'])
        self.assertIsNone(caps['get'])

    def test_find_studies_with_series_groups_series_and_tags_id(self):
        """One association: study query per ID (alias format), then series
        query per study. The study is tagged with the remote ID that matched."""
        study_uid = '1.2.3.4'
        ds1 = make_test_dataset(patient_id='25_004771', study_uid=study_uid)
        ds2 = make_test_dataset(patient_id='25_004771', study_uid=study_uid)
        pacs = _StubPACS([ds1, ds2])
        try:
            studies, errors = qr_client.find_studies_with_series(
                self._node(port=pacs.port), ['MR/25/004771', '25_004771'],
            )
        finally:
            pacs.shutdown()

        self.assertEqual(errors, [])
        self.assertEqual(len(studies), 1)
        self.assertEqual(studies[0]['remote_patient_id'], '25_004771')
        self.assertEqual(studies[0]['study_instance_uid'], study_uid)
        self.assertEqual(len(studies[0]['series']), 2)
        self.assertIn('accession_number', studies[0])

    def test_find_studies_with_series_raises_when_all_ids_fail(self):
        with self.assertRaises(ConnectionError):
            qr_client.find_studies_with_series(
                self._node(port=1), ['A', 'B'],
            )

    def test_move_series_end_to_end(self):
        """Series-level C-MOVE delivers only the requested series."""
        study_uid = '1.2.3.5'
        ds1 = make_test_dataset(patient_id='MR/25/004771', study_uid=study_uid)
        ds2 = make_test_dataset(patient_id='MR/25/004771', study_uid=study_uid)
        pacs = _StubPACS([ds1, ds2], move_dest=self.scp_port)
        try:
            stats = qr_client.move_series(
                self._node(port=pacs.port), study_uid,
                ds1.SeriesInstanceUID, 'MR/25/004771',
            )
        finally:
            pacs.shutdown()

        self.assertEqual(stats['completed'], 1)
        self.assertTrue(
            DICOMInstance.objects.filter(
                sop_instance_uid=ds1.SOPInstanceUID).exists()
        )
        self.assertFalse(
            DICOMInstance.objects.filter(
                sop_instance_uid=ds2.SOPInstanceUID).exists()
        )

    def test_get_series_end_to_end(self):
        study_uid = '1.2.3.6'
        ds1 = make_test_dataset(patient_id='MR/25/004771', study_uid=study_uid)
        ds2 = make_test_dataset(patient_id='MR/25/004771', study_uid=study_uid)
        pacs = _StubPACS([ds1, ds2])
        try:
            stats = qr_client.get_series(
                self._node(port=pacs.port), study_uid,
                ds1.SeriesInstanceUID, 'MR/25/004771',
            )
        finally:
            pacs.shutdown()

        self.assertEqual(stats['completed'], 1)
        self.assertTrue(
            DICOMInstance.objects.filter(
                sop_instance_uid=ds1.SOPInstanceUID).exists()
        )
        self.assertFalse(
            DICOMInstance.objects.filter(
                sop_instance_uid=ds2.SOPInstanceUID).exists()
        )

    def test_task_retrieve_studies_skips_cfind_when_study_uids_set(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        pacs = _StubPACS([ds])
        try:
            node = self._node(port=pacs.port, prefer_c_get=True)
            job = RetrievalJob.objects.create(
                node=node, patient=self.patient, study_uids=[ds.StudyInstanceUID],
            )
            with mock.patch.object(
                qr_client, 'find_studies_for_patient',
                side_effect=AssertionError('C-FIND should not run'),
            ):
                result = task_retrieve_studies(node.pk, 'MR/25/004771', None, job.pk)
        finally:
            pacs.shutdown()

        job.refresh_from_db()
        self.assertEqual(job.status, 'SUCCESS')
        self.assertEqual(result['status'], 'SUCCESS')
