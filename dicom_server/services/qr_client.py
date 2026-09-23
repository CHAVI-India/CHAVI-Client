"""Query/Retrieve SCU — pull studies from configured remote DICOM nodes.

All functions take a RemoteDICOMNode and use our configured AE title as the
calling AET. Retrieval is pull-only: C-MOVE delivers to our own SCP's AE title,
C-GET receives sub-ops on the same association (handled by the same ingest path
as the SCP's C-STORE handler).
"""
import logging

from pydicom.dataset import Dataset
from pynetdicom import AE, evt, build_role, StoragePresentationContexts
from pynetdicom.sop_class import (
    Verification,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelGet,
)

from dicom_server.models import DICOMServerConfiguration, RemoteDICOMNode
from dicom_server.scp.handlers import handle_store

logger = logging.getLogger(__name__)


def _scu_ae() -> AE:
    config = DICOMServerConfiguration.load()
    ae = AE(ae_title=config.ae_title)
    ae.network_timeout = config.qr_timeout
    ae.acse_timeout = config.qr_timeout
    ae.dimse_timeout = config.qr_timeout
    return ae


def echo(node: RemoteDICOMNode) -> bool:
    """C-ECHO against a remote node. Returns True on success."""
    ae = _scu_ae()
    ae.add_requested_context(Verification)
    try:
        assoc = ae.associate(node.host, node.port, ae_title=node.ae_title)
    except Exception as e:
        logger.warning("C-ECHO association to %s failed: %s", node, e)
        return False
    if not assoc.is_established:
        return False
    try:
        status = assoc.send_c_echo()
        ok = bool(status and status.Status == 0x0000)
        logger.info("C-ECHO %s: %s", node, 'success' if ok else 'failed')
        return ok
    finally:
        assoc.release()


def find_studies(node: RemoteDICOMNode, patient_id: str) -> list[dict]:
    """Study Root C-FIND at STUDY level for a PatientID.

    Returns a list of dicts: study_instance_uid, study_date, study_description,
    modalities, instances.
    """
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    assoc = ae.associate(node.host, node.port, ae_title=node.ae_title)
    if not assoc.is_established:
        raise ConnectionError(f'Association to {node} rejected or timed out')
    try:
        q = Dataset()
        q.QueryRetrieveLevel = 'STUDY'
        q.PatientID = patient_id
        q.StudyInstanceUID = ''
        q.StudyDate = ''
        q.StudyDescription = ''
        q.ModalitiesInStudy = ''
        q.NumberOfStudyRelatedInstances = ''

        results = []
        for status, identifier in assoc.send_c_find(
            q, StudyRootQueryRetrieveInformationModelFind
        ):
            if status is None:
                raise ConnectionError(f'C-FIND on {node} timed out or aborted')
            if status.Status in (0xFF00, 0xFF01) and identifier:
                results.append({
                    'study_instance_uid': str(getattr(identifier, 'StudyInstanceUID', '') or ''),
                    'study_date': str(getattr(identifier, 'StudyDate', '') or ''),
                    'study_description': str(getattr(identifier, 'StudyDescription', '') or ''),
                    'modalities': str(getattr(identifier, 'ModalitiesInStudy', '') or ''),
                    'instances': getattr(identifier, 'NumberOfStudyRelatedInstances', None),
                })
            elif status.Status not in (0xFF00, 0xFF01, 0x0000):
                logger.warning('C-FIND on %s returned status 0x%04X', node, status.Status)
        logger.info('C-FIND %s patient %s: %d studies', node, patient_id, len(results))
        return results
    finally:
        assoc.release()


def _subop_stats(status) -> dict:
    """Extract C-MOVE/C-GET sub-operation counters from the final status."""
    if status is None:
        return {'status': None, 'remaining': 0, 'completed': 0, 'failed': 0, 'warning': 0}
    return {
        'status': status.Status,
        'remaining': int(getattr(status, 'NumberOfRemainingSuboperations', 0) or 0),
        'completed': int(getattr(status, 'NumberOfCompletedSuboperations', 0) or 0),
        'failed': int(getattr(status, 'NumberOfFailedSuboperations', 0) or 0),
        'warning': int(getattr(status, 'NumberOfWarningSuboperations', 0) or 0),
    }


def _study_identifier(study_instance_uid: str, patient_id: str | None) -> Dataset:
    q = Dataset()
    q.QueryRetrieveLevel = 'STUDY'
    if patient_id:
        q.PatientID = patient_id
    q.StudyInstanceUID = study_instance_uid
    return q


def move_study(node: RemoteDICOMNode, study_instance_uid: str,
               patient_id: str | None = None, destination: str | None = None) -> dict:
    """C-MOVE a study to our own Storage SCP (destination = our AE title).

    The remote must be able to resolve our AE title to host:port (PACS config).
    Returns sub-op stats: status/completed/failed/warning.
    """
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
    assoc = ae.associate(node.host, node.port, ae_title=node.ae_title)
    if not assoc.is_established:
        raise ConnectionError(f'Association to {node} rejected or timed out')
    try:
        destination = destination or DICOMServerConfiguration.load().ae_title
        q = _study_identifier(study_instance_uid, patient_id)
        final = None
        for status, _ in assoc.send_c_move(
            q, destination, StudyRootQueryRetrieveInformationModelMove
        ):
            if status is None:
                raise ConnectionError(f'C-MOVE on {node} timed out or aborted')
            final = status
        stats = _subop_stats(final)
        logger.info('C-MOVE %s study %s -> %s: %s', node, study_instance_uid, destination, stats)
        return stats
    finally:
        assoc.release()


def get_study(node: RemoteDICOMNode, study_instance_uid: str,
              patient_id: str | None = None) -> dict:
    """C-GET a study — instances arrive as C-STORE sub-ops on the same
    association and go through the normal ingest path (patient gating applies).

    Works when the remote cannot open a connection back to us (e.g. NAT).
    Returns sub-op stats: status/completed/failed/warning.
    """
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
    for cx in StoragePresentationContexts:
        ae.add_requested_context(cx.abstract_syntax)
    roles = [
        build_role(cx.abstract_syntax, scp_role=True)
        for cx in StoragePresentationContexts
    ]
    assoc = ae.associate(
        node.host, node.port, ae_title=node.ae_title,
        ext_neg=roles,
        evt_handlers=[(evt.EVT_C_STORE, handle_store)],
    )
    if not assoc.is_established:
        raise ConnectionError(f'Association to {node} rejected or timed out')
    try:
        q = _study_identifier(study_instance_uid, patient_id)
        final = None
        for status, _ in assoc.send_c_get(q, StudyRootQueryRetrieveInformationModelGet):
            if status is None:
                raise ConnectionError(f'C-GET on {node} timed out or aborted')
            final = status
        stats = _subop_stats(final)
        logger.info('C-GET %s study %s: %s', node, study_instance_uid, stats)
        return stats
    finally:
        assoc.release()
