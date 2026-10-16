"""End-to-end C-MOVE test: local patient ID differs from remote patient ID.

Scenario:
  - Local DB patient: MR/xx/12345
  - Remote PACS has the file with PatientID: xx_12345
  - Node transforms: multiple patterns producing xx/12345 and xx_12345
  - Retrieval method: C-MOVE

Verifies what PatientID ends up in the stored .dcm file and folder.
"""
import tempfile
from pathlib import Path

from django.test import TransactionTestCase, override_settings
from pydicom import dcmread
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import (
    Verification,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
)

from client_app.models import Patient, DICOMStudy, SiteConfiguration
from dicom_server.models import RemoteDICOMNode, InboundDICOMInstance, RetrievalJobStudy
from dicom_server.services import qr_client
from dicom_server.services.ingest import find_patient, sanitize
from dicom_server.scp.server import build_ae, HANDLERS
from dicom_server.tests.utils import make_test_dataset


class _StubRemotePACS:
    """Stub remote PACS that stores files under a different PatientID."""

    def __init__(self, datasets, move_dest_port):
        self.datasets = datasets
        self.move_dest_port = move_dest_port
        self.ae = AE(ae_title='STUBPACS')
        self.ae.supported_contexts = StoragePresentationContexts
        self.ae.requested_contexts = StoragePresentationContexts

        self.ae.add_supported_context(Verification)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)

        handlers = [
            (evt.EVT_C_ECHO, lambda event: 0x0000),
            (evt.EVT_C_FIND, self._handle_find),
            (evt.EVT_C_MOVE, self._handle_move),
        ]
        self.server = self.ae.start_server(
            ('127.0.0.1', 0), block=False, evt_handlers=handlers,
        )
        self.port = self.server.server_address[1]

    def _handle_find(self, event):
        q_pid = getattr(event.identifier, 'PatientID', '') or ''
        q_suid = getattr(event.identifier, 'StudyInstanceUID', '') or ''
        seen = set()
        for ds in self.datasets:
            if q_pid and ds.PatientID != q_pid:
                continue
            if q_suid and ds.StudyInstanceUID != q_suid:
                continue
            uid = ds.StudyInstanceUID
            if uid in seen:
                continue
            seen.add(uid)
            rsp = type(ds)()
            rsp.QueryRetrieveLevel = 'STUDY'
            rsp.PatientID = ds.PatientID
            rsp.StudyInstanceUID = uid
            rsp.StudyDate = getattr(ds, 'StudyDate', '')
            rsp.StudyDescription = getattr(ds, 'StudyDescription', '')
            rsp.ModalitiesInStudy = getattr(ds, 'Modality', '')
            yield 0xFF00, rsp

    def _handle_move(self, event):
        yield ('127.0.0.1', self.move_dest_port)
        q_pid = getattr(event.identifier, 'PatientID', '') or ''
        q_suid = getattr(event.identifier, 'StudyInstanceUID', '') or ''
        selected = [
            ds for ds in self.datasets
            if (not q_pid or ds.PatientID == q_pid)
            and (not q_suid or ds.StudyInstanceUID == q_suid)
        ]
        yield len(selected)
        for ds in selected:
            yield 0xFF00, ds

    def shutdown(self):
        self.server.shutdown()


class CMovePatientIDFlowTests(TransactionTestCase):
    """Full C-MOVE loopback: remote has a different PatientID than local."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        # Start our Storage SCP (receives C-STOREs from the C-MOVE)
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
        # The local patient in our DB
        self.patient = Patient.objects.create(
            patient_id='MR/xx/12345', gender='Female'
        )
        Patient.objects.filter(pk=self.patient.pk).update(chavi_consent=True)
        self.patient.chavi_consent = True
        self.media = Path(self._media)

    def test_cmove_with_different_remote_patient_id(self):
        """Remote stores the file as 'xx_12345'. We retrieve via C-MOVE.
        What ends up in the stored file?"""
        # The remote PACS has the file with PatientID='xx_12345'
        remote_ds = make_test_dataset(patient_id='xx_12345', patient_name='Test^Patient')
        pacs = _StubRemotePACS([remote_ds], move_dest_port=self.scp_port)

        # Configure the remote node with transforms that produce the remote ID
        node = RemoteDICOMNode.objects.create(
            name='stub', ae_title='STUBPACS', host='127.0.0.1', port=pacs.port,
            patient_id_transforms=[
                {'pattern': r'^MR/(.+)/(.+)$', 'replacement': r'\1_\2'},   # -> xx_12345
                {'pattern': r'^MR/(.+)/(.+)$', 'replacement': r'\1/\2'},   # -> xx/12345
            ],
        )

        try:
            # --- Phase 1: C-FIND with all candidate IDs ---
            candidate_ids = node.remote_patient_ids_for(self.patient)
            sep = '=' * 70
            print(f"\n{sep}")
            print(f"LOCAL PATIENT: {self.patient.patient_id!r}")
            print(f"  canonical_patient_id: {self.patient.canonical_patient_id!r}")
            print(f"CANDIDATE REMOTE IDs: {candidate_ids}")
            print(f"REMOTE FILE PatientID: 'xx_12345'")
            print(f"{sep}")

            studies = []
            for pid in candidate_ids:
                results = qr_client.find_studies(node, pid)
                for s in results:
                    s['remote_patient_id'] = pid
                studies.extend(results)
                print(f"  C-FIND with PatientID={pid!r}: {len(results)} studies")

            self.assertEqual(len(studies), 1, f"Expected 1 study, got {len(studies)}")
            found_pid = studies[0]['remote_patient_id']
            print(f"\nStudy found under remote_patient_id: {found_pid!r}")

            # --- Phase 2: C-MOVE using the remote_patient_id ---
            study_uid = studies[0]['study_instance_uid']
            stats = qr_client.move_study(node, study_uid, found_pid)
            print(f"\nC-MOVE stats: {stats}")
            self.assertEqual(stats['completed'], 1)
            self.assertEqual(stats['failed'], 0)

            # --- Phase 3: Inspect what was actually stored ---
            print(f"\n{sep}")
            print("RESULT:")

            # Check the DICOMStudy in our DB
            study = DICOMStudy.objects.get(study_instance_uid=study_uid)
            print(f"  DICOMStudy.patient.patient_id = {study.patient.patient_id!r}")

            # Check the actual file on disk
            stored_file = InboundDICOMInstance.objects.filter(
                study_instance_uid=study_uid,
                status=InboundDICOMInstance.Status.STORED,
            ).first()
            self.assertIsNotNone(stored_file, "No stored instance found")
            print(f"  InboundDICOMInstance.dicom_patient_id = {stored_file.dicom_patient_id!r}")
            matched_pid = stored_file.matched_patient.patient_id if stored_file.matched_patient else None
            print(f"  InboundDICOMInstance.matched_patient = {matched_pid!r}")
            print(f"  File path: {stored_file.file_path}")

            # Read the actual .dcm file and check its PatientID
            dcm_path = Path(stored_file.file_path)
            self.assertTrue(dcm_path.exists(), f"File not found: {dcm_path}")
            ds_on_disk = dcmread(dcm_path)
            print(f"\n  DICOM FILE ON DISK:")
            print(f"    PatientID   = {ds_on_disk.PatientID!r}")
            print(f"    PatientName = {ds_on_disk.PatientName!r}")

            # Check the folder name
            folder = dcm_path.parent.parent  # processed_dicom/<patient>/<study>/
            print(f"    Folder name = {folder.name!r}")
            print(f"    Expected folder (sanitize of local ID) = {sanitize(self.patient.patient_id)!r}")

            print(f"\n{sep}")
            print(f"CONCLUSION: File stored under PatientID={ds_on_disk.PatientID!r}, "
                  f"folder={folder.name!r}")
            print(f"Local patient ID was: {self.patient.patient_id!r}")
            print(f"{sep}")

            # Now assert what we expect
            self.assertEqual(study.patient, self.patient)
            # The file should have the LOCAL patient ID if everything works
            self.assertEqual(
                ds_on_disk.PatientID, self.patient.patient_id,
                f"File PatientID {ds_on_disk.PatientID!r} != local {self.patient.patient_id!r}"
            )
        finally:
            pacs.shutdown()

    def test_find_patient_resolution(self):
        """Unit-level: what does find_patient('xx_12345') resolve to when
        the only patient is 'MR/xx/12345'?"""
        sep = '=' * 70
        print(f"\n{sep}")
        print(f"find_patient resolution test")
        print(f"  DB patient: {self.patient.patient_id!r}")
        print(f"  canonical:  {self.patient.canonical_patient_id!r}")
        print(f"{sep}")

        result = find_patient('xx_12345')
        r1 = result.patient_id if result else None
        print(f"  find_patient('xx_12345') => {r1!r}")

        result2 = find_patient('xx/12345')
        r2 = result2.patient_id if result2 else None
        print(f"  find_patient('xx/12345') => {r2!r}")

        result3 = find_patient('MR/xx/12345')
        r3 = result3.patient_id if result3 else None
        print(f"  find_patient('MR/xx/12345') => {r3!r}")

        print(f"{sep}")
        self.assertEqual(result, self.patient)
        self.assertEqual(result2, self.patient)
        self.assertEqual(result3, self.patient)

    def test_auto_retrieve_cmove_uses_remote_patient_id(self):
        """Simulates the scheduled auto-retrieval flow after the fix.

        After the fix, _auto_retrieve_patient_node creates RetrievalJobStudy
        rows with remote_patient_id, so _run_job_retrieval issues C-MOVE
        with the correct remote ID (same as the manual/bulk flow).

        This test directly simulates what the fixed code does:
        1. C-FIND finds the study under remote ID 'xx_12345'
        2. Job is created with study rows including remote_patient_id
        3. task_retrieve_studies uses the remote_patient_id for C-MOVE
        4. File arrives, ingest resolves it to the local patient, rewrites PatientID
        """
        from dicom_server.tasks import task_retrieve_studies
        from dicom_server.models import RetrievalJob

        remote_ds = make_test_dataset(patient_id='xx_12345', patient_name='Test^Patient')
        pacs = _StubRemotePACS([remote_ds], move_dest_port=self.scp_port)

        node = RemoteDICOMNode.objects.create(
            name='stub', ae_title='STUBPACS', host='127.0.0.1', port=pacs.port,
            patient_id_transforms=[
                {'pattern': r'^MR/(.+)/(.+)$', 'replacement': r'\1_\2'},
                {'pattern': r'^MR/(.+)/(.+)$', 'replacement': r'\1/\2'},
            ],
        )

        sep = '=' * 70
        try:
            # --- Step 1: C-FIND (same as _auto_retrieve_patient_node) ---
            candidate_ids = node.remote_patient_ids_for(self.patient)
            print(f"\n{sep}")
            print(f"AUTO-RETRIEVAL FLOW (FIXED - scheduled pull)")
            print(f"Local patient: {self.patient.patient_id!r}")
            print(f"Candidate remote IDs: {candidate_ids}")
            print(f"Remote file PatientID: 'xx_12345'")
            print(f"{sep}")

            studies = []
            for pid in candidate_ids:
                results = qr_client.find_studies(node, pid)
                for s in results:
                    s['remote_patient_id'] = pid
                studies.extend(results)
                print(f"  C-FIND with PatientID={pid!r}: {len(results)} studies")

            self.assertEqual(len(studies), 1)
            found_uid = studies[0]['study_instance_uid']
            found_under = studies[0]['remote_patient_id']
            print(f"\n  Study found under remote ID: {found_under!r}")

            # --- Step 2: Create job + study rows (the fix) ---
            job = RetrievalJob.objects.create(
                node=node, patient=self.patient,
            )
            RetrievalJobStudy.objects.create(
                job=job, study_instance_uid=found_uid,
                remote_patient_id=found_under,
            )
            print(f"  Job + study rows created (remote_patient_id={found_under!r})")

            # --- Step 3: Retrieve ---
            result = task_retrieve_studies(node.pk, self.patient.patient_id, None, job.pk)

            # --- Step 4: Verify ---
            print(f"\n{sep}")
            print(f"RESULT:")
            print(f"  Task status: {result['status']}")
            print(f"  Instances completed: {result['instances_completed']}")

            self.assertEqual(result['instances_completed'], 1, "C-MOVE should deliver 1 instance")

            # Check the stored file
            stored_file = InboundDICOMInstance.objects.filter(
                study_instance_uid=found_uid,
                status=InboundDICOMInstance.Status.STORED,
            ).first()
            self.assertIsNotNone(stored_file, "No stored instance found")

            dcm_path = Path(stored_file.file_path)
            ds_on_disk = dcmread(dcm_path)
            print(f"\n  DICOM FILE ON DISK:")
            print(f"    PatientID   = {ds_on_disk.PatientID!r}")
            print(f"    PatientName = {ds_on_disk.PatientName!r}")
            print(f"    Folder name = {dcm_path.parent.parent.name!r}")
            print(f"\n  Local patient ID: {self.patient.patient_id!r}")
            print(f"{sep}")

            # The file should have the LOCAL patient ID (rewritten by ingest)
            self.assertEqual(ds_on_disk.PatientID, self.patient.patient_id)
            # And be stored under the local patient's folder
            self.assertEqual(dcm_path.parent.parent.name, sanitize(self.patient.patient_id))
        finally:
            pacs.shutdown()

    def test_ingest_uses_running_job_patient_not_find_patient(self):
        """When a RUNNING job exists for the study, ingest uses that job's
        patient directly — even if find_patient would resolve differently."""
        from dicom_server.services.ingest import ingest_dataset
        from dicom_server.models import RetrievalJob, RetrievalJobStudy

        # Create a second patient that find_patient would match (exact match)
        other_patient = Patient.objects.create(patient_id='xx_12345', gender='Female')
        Patient.objects.filter(pk=other_patient.pk).update(chavi_consent=True)

        # The running job says this study belongs to self.patient (MR/xx/12345)
        node = RemoteDICOMNode.objects.create(
            name='n', ae_title='TEST', host='127.0.0.1',
        )
        job = RetrievalJob.objects.create(
            node=node, patient=self.patient, status=RetrievalJob.Status.RUNNING,
        )

        ds = make_test_dataset(patient_id='xx_12345')
        RetrievalJobStudy.objects.create(
            job=job, study_instance_uid=ds.StudyInstanceUID,
            remote_patient_id='xx_12345',
        )

        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        # File should be stored under the JOB's patient, not the other one
        self.assertEqual(result.patient, self.patient)

        # Verify the file on disk has the job's patient ID
        from pydicom import dcmread
        ds_disk = dcmread(result.file_path)
        self.assertEqual(ds_disk.PatientID, self.patient.patient_id)
